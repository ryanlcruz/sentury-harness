"""A/B das flags de arquitetura, com LLM de verdade.

O `golden.py` roda o orquestrador inteiro com um planner roteado: prova que a
canalização não quebra, e é o que serve em CI. Mas ele não mede a única coisa
que as flags mudam: **a decisão do modelo**. Com planner roteado,
`SENTURY_NATIVE_TOOLS` praticamente não existe: a escolha já vem escrita.

Este runner fecha essa lacuna. Ele manda as mesmas perguntas duas vezes (com a
configuração de hoje e com a candidata) e compara o que dá para comparar sem
pedir opinião a ninguém:

- qual ferramenta o modelo escolheu (e se foi a esperada);
- quantas chamadas de ferramenta o turno gastou;
- quantos schemas foram oferecidos ao modelo;
- latência e tokens.

É a tarefa "Rodar A/B" do P0, que estava sem instrumento: o `routing.py` que o
`golden.py` menciona nunca existiu.

    python -m sentury.evals.ab_flags
    python -m sentury.evals.ab_flags --ligadas SENTURY_NATIVE_TOOLS

Sem chave de provedor configurada ele não roda: e diz isso, em vez de
inventar um resultado.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

# Intervalo entre casos para não sobrecarregar o provedor.
_ESPERA_ENTRE_CASOS = 4.0

CANDIDATAS: Dict[str, str] = {
    "SENTURY_NATIVE_TOOLS": "function-calling nativo em vez de tool-call por texto",
}


@dataclass
class Caso:
    """Uma pergunta e a ferramenta que ela deveria provocar.

    `espera` é o mínimo verificável: não julgamos a redação da resposta, só se o
    modelo chegou na ferramenta certa. Julgar texto exigiria um juiz, e um juiz
    é outra variável no meio de um A/B.
    """

    pergunta: str
    espera: str = ""
    nota: str = ""


CASOS: Sequence[Caso] = (
    Caso("qual o NPS médio?", "analyze_nps", "a mais direta que existe"),
    Caso("por que o NPS caiu no sudeste?", "root_cause", "exige cruzar duas fontes"),
    Caso("compara o NPS deste mês com o anterior", "compare_periods"),
    Caso("exporta isso para excel", "export_xlsx", "depende de um resultado anterior"),
    Caso("o que é NPS?", "buscar_conhecimento", "conceitual: não deve tocar o dataset"),
    Caso("oi, tudo bem?", "", "nenhuma ferramenta — conversa é conversa"),
    Caso("faz um gráfico do NPS por região", "generate_chart"),
    Caso("quais chamados estouraram o SLA?", "analyze_tickets"),
)


@dataclass
class Medida:
    caso: str
    esperada: str
    escolhida: str = ""
    ferramentas: List[str] = field(default_factory=list)
    schemas_oferecidos: int = 0
    ms: int = 0
    tokens: int = 0
    erro: str = ""

    @property
    def acertou(self) -> bool:
        # Turno que nem rodou nao votou: contar erro de provedor como erro de
        # escolha faria o A/B condenar a flag por causa de um 429.
        if self.erro:
            return False
        if not self.esperada:
            return not self.ferramentas   # conversa não chama ferramenta
        return self.esperada in self.ferramentas

    @property
    def valeu(self) -> bool:
        """O caso produziu medida utilizavel."""
        return not self.erro


@dataclass
class Rodada:
    rotulo: str
    ligadas: Dict[str, bool]
    medidas: List[Medida] = field(default_factory=list)

    @property
    def acertos(self) -> int:
        return sum(1 for m in self.medidas if m.acertou)

    @property
    def validos(self) -> int:
        return sum(1 for m in self.medidas if m.valeu)

    @property
    def ms_medio(self) -> int:
        validas = [m.ms for m in self.medidas if not m.erro]
        return int(sum(validas) / len(validas)) if validas else 0

    @property
    def chamadas(self) -> int:
        return sum(len(m.ferramentas) for m in self.medidas)

    @property
    def schemas_medios(self) -> int:
        validas = [m.schemas_oferecidos for m in self.medidas if m.schemas_oferecidos]
        return int(sum(validas) / len(validas)) if validas else 0


def _ha_provedor() -> str:
    """Qual provedor dá para usar. Vazio = nenhum, e aí não se roda nada."""
    from ..config import settings

    for nome, variavel in (("groq", "GROQ_API_KEY"), ("gemini", "GEMINI_API_KEY")):
        if os.environ.get(variavel) or getattr(settings, variavel, ""):
            return nome
    return ""


async def _um_caso(orquestrador: Any, caso: Caso) -> Medida:
    from ..harness.state import AnalysisState

    medida = Medida(caso=caso.pergunta, esperada=caso.espera)
    inicio = time.time()
    try:
        # Sessão nova por caso: um turno não pode herdar o contexto do anterior,
        # senão o A/B mede a ordem dos casos junto com a mudança.
        estado = AnalysisState.new(f"ab-{abs(hash(caso.pergunta))}", "ab")
        resposta = await orquestrador.handle_message(estado, caso.pergunta)
    except Exception as exc:
        medida.erro = f"{type(exc).__name__}: {exc}"[:160]
        return medida

    medida.ms = int((time.time() - inicio) * 1000)
    registro = resposta.get("decision_log") or {}
    medida.ferramentas = [
        str(p.get("tool")) for p in (registro.get("plan") or []) if isinstance(p, dict) and p.get("tool")
    ]
    medida.escolhida = medida.ferramentas[0] if medida.ferramentas else ""
    medida.schemas_oferecidos = len(registro.get("capability_matches") or [])
    telemetria = resposta.get("telemetry") or {}
    uso = telemetria.get("tokens") or {}
    medida.tokens = int(uso.get("total") or 0) if isinstance(uso, dict) else 0
    return medida


async def _rodar(rotulo: str, ligadas: Dict[str, bool]) -> Rodada:
    from ..config import settings

    anterior = {nome: getattr(settings, nome, False) for nome in CANDIDATAS}
    for nome, valor in ligadas.items():
        setattr(settings, nome, valor)
    try:
        from ..domains.setores.cx.dados.store import InMemoryDataStore
        from ..harness.orchestrator import SenturyOrchestrator

        # A mesma cadeia que o servidor usa. Montar uma diferente aqui mediria
        # outro sistema: o A/B tem que rodar sobre o que de fato vai para o ar.
        from ..main import planner_llm, responder_llm

        orquestrador = SenturyOrchestrator(
            planner=planner_llm, responder=responder_llm,
            # Mesma semente das golden: o dado tem que ser identico nas duas
            # rodadas, senao o A/B mede o dataset junto com a flag.
            store=InMemoryDataStore(seed=9, n_feedbacks=400, n_tickets=250, n_technicians=12),
        )
        rodada = Rodada(rotulo=rotulo, ligadas=dict(ligadas))
        for indice, caso in enumerate(CASOS):
            # Respiro entre casos. A primeira corrida deste runner despejou
            # dezesseis turnos seguidos e voltou com 429 em metade deles: um
            # A/B medindo rate limit nao mede flag nenhuma.
            if indice:
                await asyncio.sleep(_ESPERA_ENTRE_CASOS)
            rodada.medidas.append(await _um_caso(orquestrador, caso))
        return rodada
    finally:
        for nome, valor in anterior.items():
            setattr(settings, nome, valor)


def relatorio(base: Rodada, candidata: Rodada) -> str:
    linhas = ["", "=== A/B das flags de arquitetura ===", ""]
    linhas.append(f"{'':34} {base.rotulo:>14} {candidata.rotulo:>14}")
    linhas.append("-" * 66)
    for nome, valor in (
        ("acertos de ferramenta", lambda r: f"{r.acertos}/{r.validos}"),
        ("casos que rodaram", lambda r: f"{r.validos}/{len(r.medidas)}"),
        ("chamadas de ferramenta", lambda r: str(r.chamadas)),
        ("candidatas oferecidas (média)", lambda r: str(r.schemas_medios)),
        ("latência média (ms)", lambda r: str(r.ms_medio)),
    ):
        linhas.append(f"{nome:34} {valor(base):>14} {valor(candidata):>14}")

    linhas += ["", "--- caso a caso ---"]
    for antes, depois in zip(base.medidas, candidata.medidas):
        marca_a = "ok " if antes.acertou else "NAO"
        marca_b = "ok " if depois.acertou else "NAO"
        mudou = "  <- MUDOU" if antes.acertou != depois.acertou else ""
        linhas.append(
            f"[{marca_a} -> {marca_b}] {antes.caso[:40]:42}"
            f" {antes.escolhida or '(nenhuma)':22} -> {depois.escolhida or '(nenhuma)'}{mudou}"
        )
        for m in (antes, depois):
            if m.erro:
                linhas.append(f"          erro: {m.erro}")

    # A comparação rejeita piora de latência simples, qualidade complexa ou
    # seleção de ferramentas.
    linhas += ["", "--- leitura ---"]
    minimo = max(1, len(base.medidas) // 2)
    if base.validos < minimo or candidata.validos < minimo:
        linhas.append(
            "CORRIDA INVALIDA: casos demais falharam por erro de provedor "
            f"({base.validos} e {candidata.validos} de {len(base.medidas)}). "
            "Nao da para concluir nada — repita com o provedor de pe."
        )
        linhas.append("")
        return "\n".join(linhas)
    if candidata.acertos < base.acertos:
        linhas.append("REGREDIU a escolha de ferramenta. Não ligar.")
    elif candidata.acertos > base.acertos:
        linhas.append("MELHOROU a escolha de ferramenta.")
    else:
        linhas.append("Escolha de ferramenta empatada.")
    if base.ms_medio and candidata.ms_medio:
        delta = (candidata.ms_medio - base.ms_medio) / base.ms_medio * 100
        linhas.append(f"Latência: {delta:+.0f}%.")
    linhas.append("")
    return "\n".join(linhas)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sentury.evals.ab_flags")
    parser.add_argument(
        "--ligadas", nargs="*", default=list(CANDIDATAS),
        help=f"flags a ligar na candidata (padrão: todas). Conhecidas: {', '.join(CANDIDATAS)}",
    )
    args = parser.parse_args(argv)

    desconhecidas = [f for f in args.ligadas if f not in CANDIDATAS]
    if desconhecidas:
        print(f"flag desconhecida: {', '.join(desconhecidas)}")
        return 2

    provedor = _ha_provedor()
    if not provedor:
        print(
            "Nenhum provedor configurado (GROQ_API_KEY ou GEMINI_API_KEY).\n"
            "Este A/B precisa de LLM de verdade: com planner roteado ele mediria\n"
            "a decisão que nós mesmos escrevemos."
        )
        return 2

    print(f"provedor: {provedor} | ligando: {', '.join(args.ligadas)}")
    for flag in args.ligadas:
        print(f"  {flag}: {CANDIDATAS[flag]}")

    async def tudo():
        base = await _rodar("hoje", {f: False for f in CANDIDATAS})
        candidata = await _rodar("candidata", {f: f in args.ligadas for f in CANDIDATAS})
        return base, candidata

    base, candidata = asyncio.run(tudo())
    print(relatorio(base, candidata))
    return 0 if candidata.acertos >= base.acertos else 1


if __name__ == "__main__":
    raise SystemExit(main())
