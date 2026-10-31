"""Ler e escrever arquivo, com as guardas do espaço de trabalho.

Comando se julga pelo verbo; arquivo só pelo alvo: escrever em `README.md` e
em `.env` é a mesma operação com consequências opostas.
"""
from __future__ import annotations

import contextvars
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .parecidos import com_sugestao, sugestoes

logger = logging.getLogger(__name__)

# Arquivo grande volta a cada turno no histórico: o teto força leitura por trecho.
LIMITE_LEITURA = 200_000
LIMITE_LINHAS = 2_000


ARQUIVO_DE_PASTAS = "pastas.json"


class PastaNaoLiberada(Exception):
    """O caminho existe, mas está fora do que o dono da máquina liberou.

    Não é um erro do agente: é uma pergunta que falta fazer. Recusar seco
    obrigava a pessoa a mover o arquivo à mão.
    """

    def __init__(self, alvo: "Path"):
        self.alvo = alvo
        self.pasta = alvo if alvo.is_dir() else alvo.parent
        super().__init__(f"'{alvo}' esta fora das pastas liberadas")


def instalacao_do_sentury() -> Path:
    """A pasta onde o proprio Sentury mora."""
    return Path(__file__).resolve().parent.parent.parent


PASTA_PADRAO = "Sentury"

# A pasta de um turno repetido: o replay refaz o turno com a pasta de trabalho
# que ele teve, e não com a desta máquina hoje.
PASTA_FIXADA: contextvars.ContextVar = contextvars.ContextVar("sentury_pasta_fixada", default="")


def raiz_de_trabalho() -> Path:
    """Onde o agente trabalha.

    Escolha da interface > `SENTURY_WORKSPACE` > diretorio atual. O diretorio
    atual costuma ser a propria instalacao (de onde o servidor sobe), e
    trabalhar ali significa que um erro do agente mexe no harness que esta
    rodando. Nesse caso o padrao vira `~/Sentury`, criada na hora.
    """
    escolhido = PASTA_FIXADA.get() or _configuracao().get("trabalho") or os.environ.get("SENTURY_WORKSPACE")
    if escolhido:
        try:
            return Path(str(escolhido)).expanduser().resolve()
        except Exception:
            pass

    atual = Path(os.getcwd()).resolve()
    if atual != instalacao_do_sentury():
        return atual

    padrao = (Path.home() / PASTA_PADRAO).resolve()
    try:
        padrao.mkdir(parents=True, exist_ok=True)
    except OSError:
        return atual
    return padrao


def casa_do_sentury() -> Path:
    """Onde mora o que e desta maquina, nao do projeto."""
    escolhida = os.environ.get("SENTURY_HOME")
    return Path(escolhida).expanduser() if escolhida else (Path.home() / ".sentury")


def pasta_de_rascunho(session_id: str = "") -> Path:
    """O bloco de anotacoes do agente, por sessao.

    Para o trabalho INTERMEDIARIO: o script de uma tentativa, o recorte de
    dado, a saida longa demais para caber na conversa. Sem um lugar assim, isso
    ia parar na pasta do usuario: sujando o material dele e pedindo permissao
    para algo que nem e dele.

    Fica fora do projeto e fora das pastas liberadas, entao nunca aparece num
    `git status` nem se mistura ao que o dono guardou.
    """
    limpo = "".join(c for c in str(session_id or "avulso") if c.isalnum() or c in "-_")[:60]
    alvo = casa_do_sentury() / "rascunho" / (limpo or "avulso")
    try:
        alvo.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return alvo


def apagar_rascunho(session_id: str) -> bool:
    """Apaga o rascunho da sessao inteiro, junto com a conversa.

    Apagar a conversa e deixar o curriculo anexado em disco era apagar pela
    metade. Calcula o caminho sem criar a pasta (ao contrario de
    `pasta_de_rascunho`) e so apaga o que esta DENTRO de `rascunho/`.
    """
    import shutil

    limpo = "".join(c for c in str(session_id or "") if c.isalnum() or c in "-_")[:60]
    if not limpo:
        return False
    base = (casa_do_sentury() / "rascunho").resolve()
    alvo = (base / limpo).resolve()
    if alvo.parent != base or not alvo.is_dir():
        return False
    shutil.rmtree(alvo, ignore_errors=True)
    return not alvo.exists()


def e_rascunho(alvo: Path) -> bool:
    """Se o caminho esta no rascunho de alguma sessao.

    Escrever ali nao pede autorizacao: pedir permissao para o agente anotar no
    proprio bloco seria pedir permissao para ele pensar. O que exige permissao
    e tocar no material de alguem.
    """
    try:
        base = (casa_do_sentury() / "rascunho").resolve()
        return base == alvo or base in alvo.parents
    except Exception:
        return False


def _configuracao() -> Dict[str, Any]:
    import json

    try:
        dados = json.loads(_arquivo_de_pastas().read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dados if isinstance(dados, dict) else {}


def _gravar_configuracao(dados: Dict[str, Any]) -> None:
    import json

    arquivo = _arquivo_de_pastas()
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def tudo_liberado() -> bool:
    return bool(_configuracao().get("universal"))


def definir_trabalho(caminho: str) -> Dict[str, Any]:
    """Troca a pasta de trabalho."""
    alvo = Path(str(caminho or "").strip()).expanduser()
    try:
        alvo = alvo.resolve()
    except Exception as exc:
        return {"ok": False, "erro": f"caminho invalido: {exc}"}
    if not alvo.is_dir():
        return {"ok": False, "erro": com_sugestao(
            f"'{alvo}' nao existe ou nao e uma pasta", alvo)}
    dados = _configuracao()
    dados["trabalho"] = str(alvo)
    _gravar_configuracao(dados)
    return {"ok": True, "trabalho": str(alvo)}


def definir_universal(ligado: bool) -> Dict[str, Any]:
    """Libera a maquina inteira, ou volta a restringir."""
    dados = _configuracao()
    dados["universal"] = bool(ligado)
    _gravar_configuracao(dados)
    return {"ok": True, "universal": bool(ligado)}


def _arquivo_de_pastas() -> Path:
    from ..memory.local_session_store import default_sentury_home

    return default_sentury_home(os.environ.get("SENTURY_HOME", "")) / ARQUIVO_DE_PASTAS


def pastas_extras() -> List[Path]:
    """Pastas fora da de trabalho que o dono da máquina liberou.

    Recusar o Downloads por estar fora da raiz não era uma decisão que alguém
    tomou: era o default.
    """
    dados = _configuracao()
    achadas = []
    for bruto in (dados.get("pastas") or []):
        try:
            caminho = Path(str(bruto)).expanduser().resolve()
        except Exception:
            continue
        if caminho.is_dir():
            achadas.append(caminho)
    return achadas


def liberar_pasta(caminho: str) -> Dict[str, Any]:
    """Põe uma pasta na lista de permitidas."""
    import json

    alvo = Path(str(caminho or "").strip()).expanduser()
    if not str(alvo):
        return {"ok": False, "erro": "falta o caminho da pasta"}
    try:
        alvo = alvo.resolve()
    except Exception as exc:
        return {"ok": False, "erro": f"caminho invalido: {exc}"}
    if not alvo.is_dir():
        return {"ok": False, "erro": com_sugestao(
            f"'{alvo}' nao existe ou nao e uma pasta", alvo)}
    try:
        _recusar_sensivel(alvo)
    except Exception as exc:  # ComandoRecusado
        return {"ok": False, "erro": f"{exc}: essa pasta nao se libera por politica"}

    atuais = [str(p) for p in pastas_extras()]
    if str(alvo) not in atuais:
        atuais.append(str(alvo))
    _gravar_configuracao({**_configuracao(), "pastas": atuais})
    return {"ok": True, "pasta": str(alvo), "pastas": atuais}


def esquecer_pasta(caminho: str) -> Dict[str, Any]:
    alvo = str(Path(str(caminho or "").strip()).expanduser().resolve())
    restantes = [str(p) for p in pastas_extras() if str(p) != alvo]
    _gravar_configuracao({**_configuracao(), "pastas": restantes})
    return {"ok": True, "pastas": restantes}


def _resolver(caminho: str) -> Path:
    """Caminho dentro do espaço de trabalho, ou erro. Checa depois do
    `resolve()`: `a/../../etc/passwd` é barrado pelo que é, não pelo que parece."""
    bruto = str(caminho or "").strip()
    if not bruto:
        raise ValueError("falta o caminho do arquivo")
    raiz = raiz_de_trabalho()
    alvo = (raiz / bruto).resolve() if not Path(bruto).is_absolute() else Path(bruto).resolve()
    # Credencial e pasta proibida (`.ssh`, `.aws`) sao recusadas antes do cartao
    # de liberar pasta e valem mesmo com a maquina toda liberada.
    _recusar_sensivel(alvo)
    if tudo_liberado() or e_rascunho(alvo):
        return alvo
    permitidas = [raiz] + pastas_extras()
    if not any(base == alvo or base in alvo.parents for base in permitidas):
        raise PastaNaoLiberada(alvo)
    return alvo


def _pedir_a_pasta(fora: "PastaNaoLiberada", operacao: str) -> Dict[str, Any]:
    """Transforma o "fora do espaco" numa pergunta ao dono da maquina."""
    return {
        "ok": False,
        "precisa_permissao": True,
        "chave": f"acessar_pasta {fora.pasta}",
        "comando": f"acessar_pasta {fora.pasta}",
        "motivo": f"'{fora.pasta}' ainda nao esta liberada para o agente",
        "pasta": str(fora.pasta),
        "operacao": operacao,
    }


def _recusar_o_proprio_sentury(alvo: Path) -> None:
    """Escrever no código do próprio Sentury não é trabalho do turno.

    Quando a pasta de trabalho é a da instalação, um erro do agente reescreve o
    harness que está rodando. Ler continua livre.
    """
    instalacao = instalacao_do_sentury()
    if not (alvo == instalacao or instalacao in alvo.parents):
        return
    if raiz_de_trabalho() != instalacao:
        raise ValueError(f"'{alvo.name}' faz parte da instalacao do Sentury; escrita recusada")

    relativo = str(alvo.relative_to(instalacao)).replace("\\", "/")
    if any(relativo.startswith(p) for p in ("sentury/", "tests/", ".git/")):
        raise ValueError(
            f"'{relativo}' e codigo do proprio Sentury; escrita recusada. Escolha outra "
            "pasta de trabalho em Harness > Onde ele pode mexer."
        )


def _recusar_sensivel(alvo: Path) -> None:
    """Ler segredo é tão grave quanto escrever: o conteúdo vai para a conversa
    e para o journal."""
    from .shell import _recusar_alvo_sensivel

    _recusar_alvo_sensivel(str(alvo))
    _recusar_alvo_sensivel(alvo.name)


# Formatos que não são texto mas carregam texto. Sem isto, um relatório em PDF
# ou uma planilha ficavam ilegíveis para um agente de análise.
CONVERTIVEIS = {
    ".pdf", ".docx", ".xlsx", ".xlsm", ".pptx", ".csv", ".epub",
    ".html", ".htm", ".xml", ".json", ".zip",
}


def _converter(alvo: Path) -> Optional[str]:
    """Documento em Markdown, via MarkItDown. `None` quando não dá."""
    try:
        from markitdown import MarkItDown

        return (MarkItDown().convert(str(alvo)).text_content or "").strip() or None
    except Exception as exc:
        logger.warning("Nao consegui converter %s: %s", alvo.name, exc)
        return None


def ler(caminho: str, *, inicio: int = 1, linhas: int = 0) -> Dict[str, Any]:
    """Lê um arquivo. Documento (PDF, planilha, slide) vira Markdown.

    Leitura não pede autorização.
    """
    try:
        alvo = _resolver(caminho)
        _recusar_sensivel(alvo)
    except PastaNaoLiberada as fora:
        return _pedir_a_pasta(fora, "ler_arquivo")
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}

    if not alvo.is_file():
        return {"ok": False, "erro": f"'{caminho}' nao existe ou nao e arquivo"}

    convertido = False
    if alvo.suffix.lower() in CONVERTIVEIS:
        texto = _converter(alvo)
        if texto is None:
            return {"ok": False, "erro": f"nao consegui extrair texto de '{alvo.name}'"}
        bruto, convertido = texto, True
    else:
        try:
            bruto = alvo.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}

    todas = bruto.splitlines()
    comeco = max(1, int(inicio or 1)) - 1
    teto = int(linhas) if linhas else LIMITE_LINHAS
    recorte = todas[comeco:comeco + teto]
    conteudo = "\n".join(recorte)

    return {
        "ok": True,
        "caminho": str(alvo),
        "conteudo": conteudo[:LIMITE_LEITURA],
        "linhas_totais": len(todas),
        "primeira_linha": comeco + 1,
        "ultima_linha": comeco + len(recorte),
        # Quem lê precisa saber que o texto veio de uma conversão: layout,
        # imagem e formatação ficaram pelo caminho.
        "convertido": convertido,
        "truncado": (comeco + len(recorte)) < len(todas) or len(conteudo) > LIMITE_LEITURA,
    }


def comando_de_escrita(operacao: str, alvo: Path, argumentos: dict) -> str:
    from ..exec.criticas import motivo

    comando = f'{operacao} "{alvo}"'
    if motivo(comando):
        import hashlib
        import json

        conteudo = ({"conteudo": str(argumentos.get("conteudo") or "")}
                    if operacao == "escrever_arquivo" else {
                        "antes": str(argumentos.get("antes") or ""),
                        "depois": str(argumentos.get("depois") or ""),
                        "todas": bool(argumentos.get("todas", False)),
                    })
        bruto = json.dumps(conteudo, sort_keys=True, ensure_ascii=False)
        comando += " --conteudo-sha256=" + hashlib.sha256(bruto.encode("utf-8")).hexdigest()
    return comando


def _pedir_autorizacao(operacao: str, alvo: Path, session_id: str, argumentos: Optional[dict] = None) -> Optional[Dict[str, Any]]:
    from .permissoes import avaliar

    comando = comando_de_escrita(operacao, alvo, argumentos or {})
    decisao = avaliar(comando, session_id)
    if decisao["precisa_perguntar"]:
        return {
            "ok": False, "precisa_permissao": True, "chave": decisao["chave"],
            "comando": comando,
            "so_desta_vez": bool(decisao.get("so_desta_vez")),
            "motivo": decisao["motivo"], "caminho": str(alvo), "operacao": operacao,
        }
    if not decisao["permitido"]:
        return {"ok": False, "recusado": True, "motivo": decisao["motivo"], "caminho": str(alvo)}
    return None


def _anotar_versao(alvo: Path, session_id: str, por: str) -> None:
    """Uma versao na linha do tempo do arquivo, se der.

    Silencioso de proposito: histórico e o registro do trabalho, nao o
    trabalho. Se ele falhar (disco cheio, permissao, arquivo enorme) a
    escrita segue, porque o contrario seria o agente nao conseguir editar por
    causa da funcao que existe para ajudar quando a edicao der errado.
    """
    if e_rascunho(alvo):
        return   # anotacao do agente nao e material de ninguem
    try:
        from ..memory.versoes import anotar
        anotar(alvo, session_id=session_id, por=por)
    except Exception:
        logger.debug("versao nao anotada para %s", alvo, exc_info=True)


def escrever(caminho: str, conteudo: str, *, session_id: str = "") -> Dict[str, Any]:
    """Cria ou substitui um arquivo inteiro. Pede autorização."""
    try:
        alvo = _resolver(caminho)
        _recusar_sensivel(alvo)
        _recusar_o_proprio_sentury(alvo)
    except PastaNaoLiberada as fora:
        return _pedir_a_pasta(fora, "escrever_arquivo")
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}

    # O rascunho e o bloco de anotacoes do agente. Pedir autorizacao para ele
    # escrever ali seria pedir permissao para pensar: e o que exige permissao
    # e tocar no material de alguem, que o rascunho nao e.
    if not e_rascunho(alvo):
        pendente = _pedir_autorizacao("escrever_arquivo", alvo, session_id, {"conteudo": conteudo})
        if pendente:
            return pendente

    existia = alvo.is_file()
    antes = alvo.read_text(encoding="utf-8", errors="replace") if existia else ""
    # O estado de partida e o unico que ninguem consegue reconstruir depois.
    if existia:
        _anotar_versao(alvo, session_id, "como estava")
    try:
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(conteudo, encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}
    _anotar_versao(alvo, session_id, "escrever_arquivo")

    logger.info("Arquivo %s (%s)", alvo, "substituido" if existia else "criado")
    from .diff_de_arquivo import montar

    return {
        "ok": True, "caminho": str(alvo), "criado": not existia,
        "linhas": len(conteudo.splitlines()),
        "linhas_antes": len(antes.splitlines()) if existia else 0,
        # So para a tela: o execute_tool tira antes de o resultado ir ao modelo.
        "diff_para_a_tela": montar(str(alvo), antes, conteudo, criado=not existia),
    }


def editar(
    caminho: str, antes: str, depois: str, *, session_id: str = "", todas: bool = False
) -> Dict[str, Any]:
    """Troca um trecho exato por outro. Pede autorização.

    O texto de antes garante que o agente viu o arquivo como ele está agora.
    """
    if not antes:
        return {"ok": False, "erro": "falta o trecho a substituir"}
    if antes == depois:
        return {"ok": False, "erro": "o trecho novo e igual ao antigo"}

    try:
        alvo = _resolver(caminho)
        _recusar_sensivel(alvo)
    except PastaNaoLiberada as fora:
        return _pedir_a_pasta(fora, "editar_arquivo")
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}
    if not alvo.is_file():
        return {"ok": False, "erro": f"'{caminho}' nao existe"}

    try:
        conteudo = alvo.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}

    ocorrencias = conteudo.count(antes)
    if ocorrencias == 0:
        return {"ok": False, "erro": "nao encontrei esse trecho no arquivo; releia antes de editar"}
    if ocorrencias > 1 and not todas:
        return {
            "ok": False,
            "erro": f"o trecho aparece {ocorrencias} vezes; inclua mais contexto ou peca todas=True",
        }

    if not e_rascunho(alvo):
        pendente = _pedir_autorizacao("editar_arquivo", alvo, session_id, {
            "antes": antes, "depois": depois, "todas": todas,
        })
        if pendente:
            return pendente

    _anotar_versao(alvo, session_id, "como estava")
    novo = conteudo.replace(antes, depois) if todas else conteudo.replace(antes, depois, 1)
    try:
        alvo.write_text(novo, encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}
    _anotar_versao(alvo, session_id, "editar_arquivo")

    from .diff_de_arquivo import montar

    return {
        "ok": True, "caminho": str(alvo), "substituicoes": ocorrencias if todas else 1,
        "linhas": len(novo.splitlines()),
        # So para a tela: o execute_tool tira antes de o resultado ir ao modelo.
        "diff_para_a_tela": montar(str(alvo), conteudo, novo),
    }


def listar(caminho: str = ".", *, padrao: str = "*") -> Dict[str, Any]:
    """O que existe numa pasta. Leitura, não pede autorização."""
    try:
        alvo = _resolver(caminho)
    except PastaNaoLiberada as fora:
        return _pedir_a_pasta(fora, "listar_arquivos")
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}
    if not alvo.is_dir():
        # O caminho relativo resolve contra a pasta de trabalho; dizer onde
        # procurou e o que existe ao lado deixa o modelo se corrigir.
        perto = sugestoes(alvo)
        resposta = {"ok": False,
                    "erro": f"'{caminho}' nao e uma pasta (procurei em {alvo})"}
        if perto:
            resposta["erro"] += f". Existe ao lado: {', '.join(perto)}"
            resposta["parecidos"] = perto
        return resposta

    IGNORADAS = ("__pycache__", "node_modules", ".git", ".venv")

    def _coletar(molde: str) -> List[Dict[str, Any]]:
        achados: List[Dict[str, Any]] = []
        for item in sorted(alvo.glob(molde)):
            if any(parte in IGNORADAS for parte in item.parts):
                continue
            achados.append({
                "nome": item.name,
                # Com padrao recursivo, o nome sozinho nao diz onde o item esta.
                "caminho": str(item.relative_to(alvo)).replace(chr(92), "/"),
                "tipo": "pasta" if item.is_dir() else "arquivo",
                "bytes": item.stat().st_size if item.is_file() else None,
            })
        return achados

    itens = _coletar(padrao)
    # Pasta so com subpastas: um nivel a mais e leitura barata e poupa outra volta.
    desceu = False
    if padrao == "*" and itens and not any(i["tipo"] == "arquivo" for i in itens):
        mais = _coletar("*/*")
        if mais:
            itens = itens + mais
            desceu = True
    saida = {"ok": True, "caminho": str(alvo), "itens": itens[:500], "total": len(itens)}
    if desceu:
        saida["nota"] = (
            "a pasta so tinha subpastas, entao o conteudo delas veio tambem; "
            "veja o campo `caminho` de cada item"
        )
    if not itens and padrao != "*":
        # Zero com filtro nao e pasta vazia; mostrar o que existe poupa outra listagem.
        sem_filtro = _coletar("*")
        nomes = ", ".join(i["nome"] for i in sem_filtro[:30]) or "nenhum"
        saida["nota"] = (
            f"nenhum item casa com o padrao `{padrao}`; sem filtro a pasta tem "
            f"{len(sem_filtro)} item(ns): {nomes}"
        )
    return saida


__all__ = ["editar", "escrever", "listar", "ler", "raiz_de_trabalho"]


# Um arquivo de 20 MB na conversa entope o histórico e o transporte; acima
# disto o caminho certo é o disco mesmo.
LIMITE_DE_ENTREGA = 20 * 1024 * 1024


def entregar(caminho: str) -> Dict[str, Any]:
    """Entrega um arquivo do espaço de trabalho como anexo baixável.

    Gravar no disco e entregar são coisas diferentes: `escrever_arquivo` deixa
    o arquivo na máquina, e quem está na conversa não recebe nada.
    """
    import base64
    import mimetypes

    alvo = _resolver(caminho)
    _recusar_sensivel(alvo)
    if not alvo.is_file():
        return {"ok": False, "erro": f"'{caminho}' nao existe ou nao e um arquivo"}

    tamanho = alvo.stat().st_size
    if tamanho > LIMITE_DE_ENTREGA:
        return {
            "ok": False,
            "erro": f"'{alvo.name}' tem {tamanho // (1024 * 1024)} MB; o limite para anexar e "
                    f"{LIMITE_DE_ENTREGA // (1024 * 1024)} MB",
            "caminho": str(alvo),
        }

    extensao = alvo.suffix.lstrip(".").lower() or "bin"
    tipo, _ = mimetypes.guess_type(alvo.name)
    return {
        "ok": True,
        "attachment": {
            "type": extensao,
            "filename": alvo.name,
            "mime_type": tipo or "application/octet-stream",
            "content_base64": base64.b64encode(alvo.read_bytes()).decode("ascii"),
        },
        "bytes": tamanho,
    }
