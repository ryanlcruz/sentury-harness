"""Aplica proibições permanentes antes de consultar permissões concedidas.

A análise inclui argumentos de interpretadores, onde comandos perigosos podem
estar escondidos. A ordem é: bloqueio permanente, alvo sensível, negações e
então permissões. Este módulo decide o que nem pode ser perguntado.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _politica_do_shell() -> Dict[str, Any]:
    """A tabela de alvos proibidos mora no `shell.yaml`, que já é lido."""
    try:
        from ..tools.shell import politica

        return politica() or {}
    except Exception:  # pragma: no cover - política ausente não pode derrubar o turno
        logger.warning("Nao consegui ler a politica do shell; seguindo sem alvos proibidos.")
        return {}


def alvo_sensivel(texto: str) -> Optional[str]:
    """Credencial mencionada no texto, ou None.

    Vale para o CORPO de um script, não para argumento solto: o `validar()` do
    shell já checa argumento por argumento, e repetir aqui daria dois motivos
    diferentes para a mesma recusa.
    """
    baixo = str(texto or "").lower()
    if not baixo:
        return None
    tabela = _politica_do_shell()
    for alvo in (tabela.get("alvos_proibidos") or []):
        if str(alvo).lower() in baixo:
            return f"o texto menciona '{alvo}', que guarda credencial"
    for pasta in (tabela.get("pastas_proibidas") or []):
        marca = str(pasta).lower()
        if f"/{marca}/" in baixo or "\\" + marca + "\\" in baixo:
            return f"o texto alcanca a pasta '{pasta}', que guarda credencial"
    return None


def recusa_sem_apelacao(texto: str, *, checar_alvo: bool = True) -> Optional[str]:
    """O motivo de nunca rodar, ou None. Antes de qualquer permissão."""
    from . import hardline

    motivo = hardline.recusar(texto)
    if motivo:
        return f"recusado sem apelacao: {motivo}"
    return alvo_sensivel(texto) if checar_alvo else None


def avaliar(
    comando: str,
    session_id: str = "",
    *,
    corpo: str = "",
    checar_alvo: bool = True,
    na_hora: bool = False,
    consumir: bool = True,
) -> Dict[str, Any]:
    """Se isto pode rodar agora, e por quê.

    `comando` é a linha; `corpo` é o conteúdo do script, quando houver: os
    dois passam pelo hardline, porque `python -c "..."` esconde no argumento o
    que um `.py` esconderia no arquivo.

    Devolve o mesmo formato de `permissoes.avaliar`, mais `sem_apelacao`, que
    diz se a recusa é discutível. Recusa sem apelação não vira pergunta: a
    interface que perguntasse estaria oferecendo o que não existe.
    """
    for texto in (comando, corpo):
        motivo = recusa_sem_apelacao(texto, checar_alvo=checar_alvo) if texto else None
        if motivo:
            return {
                "permitido": False,
                "precisa_perguntar": False,
                "sem_apelacao": True,
                "chave": "",
                "motivo": motivo,
            }

    from ..tools.permissoes import avaliar as _do_registro
    from ..tools.shell import partes_do_comando
    from .criticas import _contexto
    import ntpath

    try:
        partes = partes_do_comando(_contexto(comando)[0])
    except ValueError:
        partes = []
    programa = ntpath.basename(partes[0]).lower().removesuffix(".exe") if partes else ""
    if programa in (_politica_do_shell().get("negados") or []):
        return {
            "permitido": False, "precisa_perguntar": False, "sem_apelacao": True,
            "chave": "", "motivo": f"'{programa}' nao e permitido em nenhum modo",
        }

    decisao = dict(_do_registro(comando, session_id, na_hora=na_hora, consumir=consumir))
    decisao["sem_apelacao"] = False
    return decisao


def cartao_de_destrutiva(ferramenta: str, argumentos: Dict[str, Any], session_id: str = "") -> Optional[Dict[str, Any]]:
    """O cartão de uma ação declarada `destrutiva` no tools.yaml, ou None.

    Destrutiva é o que apaga ou não dá para desfazer: pergunta sempre, na hora,
    mesmo com "permitir tudo", "sempre" ou "nesta conversa". Só a aprovação
    desta vez deixa passar, e ela vale para uma execução.
    """
    from ..tools.registry import efeito_de

    if efeito_de(ferramenta, argumentos) != "destrutiva":
        return None
    acao = str((argumentos or {}).get("acao") or "").strip()
    chave = f"{ferramenta} {acao}".strip()
    decisao = avaliar(chave, session_id, checar_alvo=False, na_hora=True)
    if decisao.get("permitido"):
        return None
    from .contrato import CodigoDeErro

    base = {"ok": False, "executado": False, "fase": "permissao", "chave": chave,
            "motivo": "esta ação apaga ou não dá para desfazer", "comando": chave}
    if decisao.get("precisa_perguntar"):
        return {**base, "precisa_permissao": True, "so_desta_vez": True,
                "codigo_erro": CodigoDeErro.PRECISA_PERMISSAO}
    return {**base, "recusado": True, "motivo": str(decisao.get("motivo") or ""),
            "codigo_erro": CodigoDeErro.RECUSADO_POLITICA}


def comando_a_autorizar(ferramenta: str, argumentos: Dict[str, Any]) -> str:
    """O texto que o registro de permissao avalia para este passo, ou "".

    Serve a pre-checagem do plano, que pergunta antes de executar. Vazio
    quando o passo nao altera nada ou o alvo so existe depois de outro passo.
    """
    argumentos = argumentos or {}
    if ferramenta in ("escrever_arquivo", "editar_arquivo"):
        alvo = str(argumentos.get("caminho") or argumentos.get("path") or "")
        from ..tools.arquivos import PastaNaoLiberada, comando_de_escrita, _resolver
        from ..tools.shell import ComandoRecusado

        try:
            return comando_de_escrita(ferramenta, _resolver(alvo), argumentos)
        except (OSError, ValueError, PastaNaoLiberada, ComandoRecusado):
            return ""
    if ferramenta == "executar_comando":
        comando = str(argumentos.get("comando") or "")
        # Leitura nao pede nada; comando composto e avaliado trecho por trecho.
        from ..tools.shell import composto, so_leitura
        from .criticas import no_diretorio

        try:
            return "" if so_leitura(comando) or composto(comando) is not None else no_diretorio(
                comando, str(argumentos.get("diretorio") or ""),
            )
        except Exception:
            return comando
    if ferramenta == "browser":
        from ..tools.browser_contracts import Action

        from ..tools.browser_registry import descrever

        # Roteiro com passo invalido so levanta ao ler os passos: a recusa com o
        # motivo e da politica do laco, que devolve o erro ao modelo.
        try:
            action = Action.de_argumentos(argumentos)
            # a chave e o primeiro termo; o alvo vai junto para a pessoa ler
            return descrever(action) if action.pede_autorizacao else ""
        except ValueError:
            return ""
    return ""


__all__ = ["alvo_sensivel", "avaliar", "cartao_de_destrutiva", "comando_a_autorizar", "recusa_sem_apelacao"]
