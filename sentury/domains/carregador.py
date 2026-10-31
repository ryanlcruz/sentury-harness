"""Setor declarado numa pasta, sem código: `pack.yaml` e pronto.

Um Sentury por especialidade (`sentury-coder`, `sentury-science`) seria uma
cópia do harness por área, e um defeito corrigido numa não chegaria nas
outras. Nesta semana foram oito defeitos silenciosos; com três cópias, vinte
e quatro correções.

O caminho é o contrário: **um agente, muitos pacotes**. O pacote traz as
métricas, a persona e quais ferramentas e skills o setor expõe; o motor é
sempre o mesmo, e conserto feito uma vez vale para todos.

A pasta:

    dominios/
      coder/
        pack.yaml        ← o que o setor é
        skills/          ← skills próprias (opcional)

Ligar e desligar é `SENTURY_DOMAIN`, ou tirar a pasta de lá.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .pack import FORMAS_DE_GRAFICO, DomainPack

logger = logging.getLogger(__name__)

ARQUIVO = "pack.yaml"


def pasta_dos_pacotes() -> Path:
    escolhido = os.environ.get("SENTURY_DOMAIN_PACKS")
    if escolhido:
        return Path(escolhido).expanduser()
    return Path(__file__).resolve().parent / "setores"


def _texto(valor: Any) -> str:
    return str(valor or "").strip()


def _conjunto(valor: Any) -> frozenset:
    if isinstance(valor, str):
        return frozenset({valor.strip()} - {""})
    return frozenset(_texto(item) for item in (valor or []) if _texto(item))


def ler(caminho: Path) -> Optional[DomainPack]:
    """Monta um pacote a partir do `pack.yaml`.

    Devolve `None` quando o arquivo está quebrado ou incompleto, com o motivo
    no log: um pacote meio carregado daria um agente que fala de um setor sem
    saber medir nada dele.
    """
    arquivo = caminho / ARQUIVO if caminho.is_dir() else caminho
    if not arquivo.is_file():
        return None
    try:
        import yaml

        dados = yaml.safe_load(arquivo.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("Pacote de setor ilegivel (%s): %s", arquivo, exc)
        return None
    if not isinstance(dados, dict):
        return None

    nome = _texto(dados.get("nome")) or arquivo.parent.name
    metricas = dados.get("metricas") or {}
    if not isinstance(metricas, dict):
        logger.warning("Pacote '%s': `metricas` deve ser um mapa.", nome)
        return None

    meta: Dict[str, Dict[str, str]] = {}
    maior_melhor: Dict[str, bool] = {}
    experiencia, operacao = set(), set()
    for chave, bruto in metricas.items():
        if not isinstance(bruto, dict):
            continue
        metrica = _texto(chave)
        meta[metrica] = {
            "label": _texto(bruto.get("label")) or metrica,
            "unidade": _texto(bruto.get("unidade")),
            "fonte": _texto(bruto.get("fonte")),
            "descricao": _texto(bruto.get("descricao")),
        }
        if "maior_melhor" in bruto:
            maior_melhor[metrica] = bool(bruto.get("maior_melhor"))
        # Sem grupo declarado a métrica cai em operação: é o lado que não
        # promete leitura de percepção do cliente.
        (experiencia if _texto(bruto.get("grupo")) == "experiencia" else operacao).add(metrica)

    if not meta:
        logger.warning("Pacote '%s' nao declara metrica nenhuma; ignorado.", nome)
        return None

    persona = _texto(dados.get("persona")) or None
    caminho_persona = _texto(dados.get("persona_arquivo"))
    if caminho_persona:
        alvo = (arquivo.parent / caminho_persona)
        if alvo.is_file():
            persona = alvo.read_text(encoding="utf-8").strip() or persona
        else:
            logger.warning("Pacote '%s': persona_arquivo '%s' nao existe.", nome, caminho_persona)

    # O planner do setor vem SEMPRE de arquivo: sao dezenas de linhas com
    # schema e exemplo de query, e enfiar isso dentro do YAML tornaria o
    # pack.yaml ilegivel para quem so quer trocar uma metrica.
    planner = None
    nome_do_planner = _texto(dados.get("planner_arquivo")) or "planner.md"
    alvo_planner = arquivo.parent / nome_do_planner
    if alvo_planner.is_file():
        planner = alvo_planner.read_text(encoding="utf-8").strip() or None
    elif dados.get("planner_arquivo"):
        logger.warning(
            "Pacote '%s': planner_arquivo '%s' nao existe.", nome, nome_do_planner,
        )

    # A voz da RESPOSTA FINAL do setor. Arquivo ganha do campo inline: sao
    # regras de varios paragrafos, como o planner.
    persona_resposta = _texto(dados.get("persona_resposta")) or None
    alvo_resposta = arquivo.parent / "persona_resposta.md"
    if alvo_resposta.is_file():
        persona_resposta = alvo_resposta.read_text(encoding="utf-8").strip() or persona_resposta

    # O corpus conceitual vem de arquivo pelo mesmo motivo do planner: sao
    # paragrafos inteiros, e enfiar isso no pack.yaml o tornaria ilegivel.
    conhecimento: tuple = ()
    alvo_saber = arquivo.parent / (_texto(dados.get("conhecimento_arquivo")) or "conhecimento.yaml")
    if alvo_saber.is_file():
        try:
            lido = yaml.safe_load(alvo_saber.read_text(encoding="utf-8")) or {}
            conhecimento = tuple(
                e for e in (lido.get("conhecimento") or [])
                if isinstance(e, dict) and e.get("texto")
            )
        except Exception:
            logger.warning("Pacote %r: conhecimento.yaml ilegivel; seguindo sem ele.", nome)

    # Cada entrada e uma analise do setor e as palavras que apontam para ela.
    dicas: list = []
    for item in (dados.get("dicas_de_grafico") or []):
        if not isinstance(item, dict):
            continue
        ferramenta = _texto(item.get("ferramenta"))
        termos = tuple(
            str(x).strip().lower() for x in (item.get("termos") or []) if str(x).strip()
        )
        if ferramenta and termos:
            dicas.append((ferramenta, termos))

    # Fontes de dados e publicos que o setor oferece ao pedir o alvo de um material.
    fontes: list = []
    for item in (dados.get("fontes_de_dados") or []):
        if not isinstance(item, dict) or not _texto(item.get("rotulo")):
            continue
        fontes.append({
            "rotulo": _texto(item.get("rotulo")),
            "descricao": _texto(item.get("descricao")) or "",
            "ferramenta": _texto(item.get("ferramenta")) or "",
            "termos": tuple(str(x).strip().lower() for x in (item.get("termos") or []) if str(x).strip()),
        })
    publicos = [
        {"rotulo": _texto(item.get("rotulo")), "descricao": _texto(item.get("descricao")) or ""}
        for item in (dados.get("publicos") or [])
        if isinstance(item, dict) and _texto(item.get("rotulo"))
    ]
    atalhos = [
        {
            "comando": _texto(item.get("comando")).lstrip("/").lower(),
            "descricao": _texto(item.get("descricao")) or "",
            "pergunta": _texto(item.get("pergunta")),
        }
        for item in (dados.get("atalhos") or [])
        if isinstance(item, dict) and _texto(item.get("comando")) and _texto(item.get("pergunta"))
    ]
    exemplos_de_pedido = tuple(str(x).strip() for x in (dados.get("exemplos_de_pedido") or []) if str(x).strip())
    cores_de_rotulo = {
        str(papel): tuple(str(t).strip().lower() for t in (termos or []) if str(t).strip())
        for papel, termos in (dados.get("cores_de_rotulo") or {}).items()
        if str(papel) in ("positivo", "neutro", "negativo")
    }

    # Cada entrega e uma ferramenta e como a saida dela chega ao usuario.
    entregas: dict = {}
    for item in (dados.get("entregas") or []):
        if not isinstance(item, dict):
            continue
        ferramenta = _texto(item.get("ferramenta"))
        if not ferramenta:
            continue
        entregas[ferramenta] = {
            chave: _texto(item.get(chave))
            for chave in ("titulo", "arquivo", "aviso", "reescrita")
            if _texto(item.get(chave))
        }

    # Recortes do setor, lidos uma vez e usados pela guarda e pelo filtro.
    dimensoes: dict = {
        str(nome): tuple(str(v).strip() for v in (valores or []) if str(v).strip())
        for nome, valores in (dados.get("dimensoes") or {}).items()
    }

    # Uma guarda e: o que dispara, o que injetar, e o que extrair da frase.
    guardas: list = []
    for item in (dados.get("guardas") or []):
        if not isinstance(item, dict):
            continue
        ferramenta = _texto(item.get("ferramenta"))
        gatilhos = item.get("gatilhos") or {}
        if not ferramenta or not isinstance(gatilhos, dict):
            continue
        guardas.append({
            "ferramenta": ferramenta,
            "argumento": _texto(item.get("argumento")),
            # valor do argumento -> frases que apontam para ele
            "gatilhos": {
                str(valor): tuple(
                    str(f).strip().lower() for f in (frases or []) if str(f).strip()
                )
                for valor, frases in gatilhos.items()
            },
            "exige_dados": bool(item.get("exige_dados", True)),
            # So os NOMES: os valores moram em `dimensoes`, no setor. Repetir
            # a lista aqui criaria a terceira copia das mesmas regioes.
            "dimensoes": tuple(
                str(x).strip() for x in (item.get("dimensoes") or []) if str(x).strip()
            ),
        })

    responder = None
    nome_do_responder = _texto(dados.get("responder_arquivo")) or "responder.md"
    alvo_responder = arquivo.parent / nome_do_responder
    if alvo_responder.is_file():
        responder = alvo_responder.read_text(encoding="utf-8").strip() or None
    elif dados.get("responder_arquivo"):
        logger.warning(
            "Pacote '%s': responder_arquivo '%s' nao existe.", nome, nome_do_responder,
        )

    return DomainPack(
        name=nome,
        metric_meta=meta,
        higher_is_better=maior_melhor,
        cx_metrics=frozenset(experiencia),
        ops_metrics=frozenset(operacao),
        persona=persona,
        planner=planner,
        responder=responder,
        texto_de_terceiros=_conjunto(dados.get("texto_de_terceiros")),
        tabelas_no_sandbox=tuple(dados.get("tabelas_no_sandbox") or ()),
        conhecimento=conhecimento,
        dicas_de_grafico=tuple(dicas),
        fontes_de_dados=tuple(fontes),
        publicos=tuple(publicos),
        atalhos=tuple(atalhos),
        exemplos_de_pedido=exemplos_de_pedido,
        cores_de_rotulo=cores_de_rotulo,
        titulos_de_secao={str(k): str(v) for k, v in (dados.get("titulos_de_secao") or {}).items()},
        rotulos_de_coluna={str(k): str(v) for k, v in (dados.get("rotulos_de_coluna") or {}).items()},
        titulos_de_passo={str(k): str(v) for k, v in (dados.get("titulos_de_passo") or {}).items()},
        colunas_de_grafico={
            str(k): (str(v[0]), str(v[1]))
            for k, v in (dados.get("colunas_de_grafico") or {}).items()
            if isinstance(v, (list, tuple)) and len(v) >= 2
        },
        formas_de_grafico={
            str(k): str(v) for k, v in (dados.get("formas_de_grafico") or {}).items()
            if str(v) in FORMAS_DE_GRAFICO
        },
        titulos_de_painel={
            str(k): str(v) for k, v in (dados.get("titulos_de_painel") or {}).items()
        },
        analise_de_base=str(dados.get("analise_de_base") or ""),
        ferramenta_de_causa=_texto(dados.get("ferramenta_de_causa")) or None,
        entregas=entregas,
        guardas=tuple(guardas),
        dimensoes=dimensoes,
        responder_persona=persona_resposta,
        expected_sources=_conjunto(dados.get("fontes")),
        capabilities=_conjunto(dados.get("capacidades")),
    )


def descobrir(pasta: Optional[str] = None) -> List[DomainPack]:
    """Todos os pacotes válidos da pasta. Pasta ausente devolve lista vazia:
    um agente sem pacote é o generalista, não um erro."""
    base = Path(pasta).expanduser() if pasta else pasta_dos_pacotes()
    if not base.is_dir():
        return []
    achados = []
    for item in sorted(base.iterdir()):
        if not item.is_dir():
            continue
        pack = ler(item)
        if pack:
            achados.append(pack)
    return achados


def registrar_descobertos(pasta: Optional[str] = None) -> List[str]:
    """Põe no registro o que a pasta declarar. Chamado no arranque."""
    from . import register_domain

    nomes = []
    for pack in descobrir(pasta):
        register_domain(pack)
        nomes.append(pack.name)
        logger.info("Setor '%s' carregado da pasta.", pack.name)
    return nomes


def carregar_codigo_do_setor(nome: str, pasta: Optional[str] = None) -> List[str]:
    """Roda o `tools.py` do setor, se houver.

    Só do setor ATIVO: código de pacote roda no mesmo processo, e carregar o
    de todo mundo daria superfície que ninguém pediu.
    """
    from .extensao import carregar

    base = Path(pasta).expanduser() if pasta else pasta_dos_pacotes()
    alvo = base / nome
    return carregar(alvo, nome) if alvo.is_dir() else []


PREFIXO_MCP = "pacote:"


def mcp_do_pacote(nome: str, pasta: Optional[str] = None) -> List[dict]:
    """Servidores MCP declarados pelo proprio pacote.

    O formato e o mesmo do `mcp.json` do usuario, e por isso um pacote pode ser
    testado copiando um bloco que ja funciona. O que muda e o `id`: ele ganha o
    prefixo do pacote, para nao colidir com um id do usuario e para que
    `salvar` e `remover` saibam recusar: o servidor e do pacote, e some junto
    com ele.
    """
    import json

    base = Path(pasta).expanduser() if pasta else pasta_dos_pacotes()
    alvo = base / nome / "mcp.json"
    if not alvo.is_file():
        return []
    try:
        dados = json.loads(alvo.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError) as exc:
        # Pacote com json quebrado nao derruba a tela de MCP do usuario.
        logger.warning("Pacote '%s': mcp.json ilegivel (%s).", nome, exc)
        return []

    crus = dados.get("servidores") if isinstance(dados, dict) else None
    saida = []
    for item in (crus or []):
        if not isinstance(item, dict):
            continue
        proprio = dict(item)
        bruto = str(proprio.get("id") or proprio.get("nome") or "").strip()
        if not bruto:
            continue
        proprio["id"] = f"{PREFIXO_MCP}{nome}:{bruto}"
        proprio["origem"] = f"pacote {nome}"
        # O pacote declara o NOME da variavel; o valor continua sendo do
        # ambiente de quem instalou, como em qualquer credencial.
        proprio["env_vars"] = [
            str(v).strip() for v in (proprio.get("env_vars") or []) if str(v).strip()
        ]
        saida.append(proprio)
    return saida


def skills_do_pacote(nome: str, pasta: Optional[str] = None) -> Optional[Path]:
    """Pasta de skills do setor, quando ele traz as próprias."""
    base = Path(pasta).expanduser() if pasta else pasta_dos_pacotes()
    alvo = base / nome / "skills"
    return alvo if alvo.is_dir() else None


__all__ = ["ARQUIVO", "PREFIXO_MCP", "carregar_codigo_do_setor", "descobrir", "ler",
           "mcp_do_pacote",
           "pasta_dos_pacotes", "registrar_descobertos", "skills_do_pacote"]
