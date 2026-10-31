"""Gatilhos que não dependem do modelo lembrar de puxá-los.

Uma instrução no prompt é um pedido: o modelo pode seguir, esquecer, ou
decidir que não vale a pena desta vez. Um hook dispara porque o evento
aconteceu, e o modelo descobre pelo resultado.

Essa diferença é o que separa "ele pode editar arquivo" de "toda vez que ele
edita, o teste roda e o resultado volta para ele". Sem isso, a verificação
depende de o modelo se lembrar de verificar justamente quando errou.

Três decisões:

- Vêm todos desligados. Um gatilho que roda comando sem ninguém ter pedido
  seria uma porta de execução aberta por padrão.
- Passam pela mesma política de permissão do shell. Declarar um hook diz
  quando um comando roda, não dá o direito de rodá-lo.
- A falha do hook não derruba o turno. Ela vira observação para o agente: um
  teste que quebrou é informação, não motivo para perder o trabalho.
"""
from __future__ import annotations

import fnmatch
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Eventos que um hook pode observar. Nomes do que ACONTECEU, não do que fazer:
# quem declara descreve o momento, não a implementação.
EVENTOS = ("arquivo_alterado", "ferramenta_concluida")

# Teto próprio, curto. Um gatilho que trava segura a resposta do usuário, e a
# pessoa não pediu por ele: ela pediu outra coisa.
TIMEOUT_PADRAO_S = 90.0


def _padrao() -> Dict[str, Any]:
    return {"hooks": []}


def declarados() -> List[Dict[str, Any]]:
    """Hooks do YAML. Sem arquivo, nenhum: e nenhum é o estado seguro."""
    from ..policies import carregar

    dados = carregar("hooks", _padrao())
    saida = []
    for item in dados.get("hooks") or []:
        if not isinstance(item, dict):
            continue
        evento = str(item.get("quando") or "").strip()
        if evento not in EVENTOS:
            if evento:
                logger.warning("Hook '%s' observa evento desconhecido: %s", item.get("nome"), evento)
            continue
        saida.append({
            "nome": str(item.get("nome") or "sem nome"),
            "quando": evento,
            "padrao": str(item.get("padrao") or "*"),
            "ferramenta": str(item.get("ferramenta") or ""),
            "comando": str(item.get("comando") or ""),
            "descricao": str(item.get("descricao") or ""),
            "ativo": bool(item.get("ativo")),
            "timeout_s": float(item.get("timeout_s") or TIMEOUT_PADRAO_S),
        })
    return saida


def _casa(hook: Dict[str, Any], *, alvo: str = "", ferramenta: str = "") -> bool:
    if hook["ferramenta"] and hook["ferramenta"] != ferramenta:
        return False
    padrao = hook["padrao"]
    if padrao in ("", "*"):
        return True
    if not alvo:
        return False
    # Casa contra o caminho inteiro e contra o nome do arquivo: `*.py` deve
    # pegar `sentury/tools/shell.py`, que fnmatch sozinho não casaria.
    from pathlib import Path

    return fnmatch.fnmatch(alvo, padrao) or fnmatch.fnmatch(Path(alvo).name, padrao)


def aplicaveis(evento: str, *, alvo: str = "", ferramenta: str = "") -> List[Dict[str, Any]]:
    return [
        hook for hook in declarados()
        if hook["ativo"] and hook["quando"] == evento
        and _casa(hook, alvo=alvo, ferramenta=ferramenta)
    ]


def disparar(
    evento: str,
    *,
    alvo: str = "",
    ferramenta: str = "",
    session_id: str = "",
    habilitado: bool = True,
) -> List[Dict[str, Any]]:
    """Roda os hooks do evento e devolve o que cada um observou.

    Nunca levanta: o hook existe para acrescentar informação, e derrubar o
    turno por causa dele seria pior do que não tê-lo.
    """
    encontrados = aplicaveis(evento, alvo=alvo, ferramenta=ferramenta)
    if not encontrados:
        return []

    from ..tools.shell import executar

    observacoes = []
    for hook in encontrados:
        if not hook["comando"]:
            continue
        logger.info("Hook '%s' disparado por %s (%s)", hook["nome"], evento, alvo or ferramenta)
        try:
            resultado = executar(
                hook["comando"],
                habilitado=habilitado,
                timeout=hook["timeout_s"],
                session_id=session_id,
                segundo_plano=True,
            )
        except Exception as exc:
            observacoes.append({
                "hook": hook["nome"], "ok": False,
                "motivo": f"{type(exc).__name__}: {exc}",
            })
            continue

        observacoes.append({
            "hook": hook["nome"],
            "descricao": hook["descricao"],
            "comando": hook["comando"],
            "ok": bool(resultado.get("ok")),
            "precisa_permissao": bool(resultado.get("precisa_permissao")),
            "em_segundo_plano": bool(resultado.get("em_segundo_plano")),
            "id": resultado.get("id"),
            "saida": (resultado.get("saida") or resultado.get("saida_parcial") or "")[-2000:],
            "erro": (resultado.get("erro") or resultado.get("motivo") or "")[:500],
        })
    return observacoes


def como_mensagem(observacoes: List[Dict[str, Any]]) -> Optional[str]:
    """O que o agente lê. Escrito como observação, não como ordem: foi o
    ambiente que respondeu, e ele decide o que fazer com isso."""
    if not observacoes:
        return None
    linhas = [
        "GATILHO AUTOMÁTICO (rodou por causa do que você acabou de fazer, "
        "não porque alguém pediu agora):",
    ]
    for item in observacoes:
        cabeca = f"- {item['hook']}: `{item.get('comando', '')}`"
        if item.get("precisa_permissao"):
            linhas.append(f"{cabeca} — não rodou: precisa da autorização do usuário.")
            continue
        if item.get("em_segundo_plano"):
            linhas.append(f"{cabeca} — ainda rodando (id `{item.get('id')}`).")
            continue
        linhas.append(f"{cabeca} — {'passou' if item['ok'] else 'FALHOU'}")
        corpo = (item.get("erro") if not item["ok"] else "") or item.get("saida") or ""
        if corpo.strip():
            linhas.append(f"  {corpo.strip()[-800:]}")
    linhas.append(
        "Se algo falhou aqui, foi efeito do que você fez agora: trate antes de seguir."
    )
    return "\n".join(linhas)


def arquivos_tocados(ferramenta: str, resultado: Any) -> List[str]:
    """Arquivos que a ferramenta mexeu, quando ela conta.

    `executar_python` reporta `arquivos_gerados`; escrever e editar reportam o
    `caminho`. O `caminho` só conta quando a ferramenta escreve, porque ler um
    arquivo também o devolve. Quem não reporta nada não dispara hook de arquivo:
    melhor um gatilho que não roda do que um que roda sobre uma suposição.
    """
    if not isinstance(resultado, dict) or not resultado.get("ok", True):
        return []
    achados = []
    for campo in ("arquivos_gerados", "arquivos", "arquivos_alterados"):
        valor = resultado.get(campo)
        if isinstance(valor, (list, tuple)):
            achados.extend(str(item) for item in valor if item)
    caminho = resultado.get("caminho")
    if isinstance(caminho, str) and caminho and caminho not in achados:
        from ..tools.registry import efeito_de

        if efeito_de(ferramenta) != "leitura":
            achados.append(caminho)
    return achados


def depois_da_ferramenta(state: Any, ferramenta: str, resultado: Any) -> None:
    """Roda os gatilhos do que acabou de acontecer e deixa o que eles viram no
    histórico, para o agente ler no mesmo turno.

    Nunca levanta: o hook acrescenta informação, e derrubar o turno por causa
    dele seria pior do que não tê-lo.
    """
    try:
        sessao = getattr(state, "session_id", "") or ""
        observacoes = list(disparar("ferramenta_concluida", ferramenta=ferramenta, session_id=sessao))
        for caminho in arquivos_tocados(ferramenta, resultado):
            observacoes.extend(disparar(
                "arquivo_alterado", alvo=caminho, ferramenta=ferramenta, session_id=sessao,
            ))
        aviso = como_mensagem(observacoes)
        if aviso:
            state.history.append({"role": "system", "content": aviso})
    except Exception as exc:
        logger.warning("Falha ao disparar hooks de %s: %s", ferramenta, exc)


__all__ = [
    "EVENTOS", "aplicaveis", "arquivos_tocados", "como_mensagem", "declarados",
    "depois_da_ferramenta", "disparar",
]
