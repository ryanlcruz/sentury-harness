"""O agente escreve as próprias skills procedurais.

Só a pasta de skills do usuário recebe escrita. Skill embutida ou de setor não
muda no lugar: a primeira escrita copia a pasta para a do usuário, e a cópia
passa a valer sobre a original (o carregador lê a pasta do usuário primeiro).
Toda escrita guarda o que havia antes, então `desfazer` volta um passo.
"""
from __future__ import annotations

import json
import re
import shutil
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

from .skill_loader import SKILL_SUPPORT_DIRS, SkillLoader

ACOES = ("criar", "corrigir", "acrescentar", "anexar", "aposentar", "desfazer")
_HISTORICO = ".historico"
# Nome de skill descreve uma classe de tarefa; data, número de caso e "fix-" são do dia.
_NOME_DO_DIA = ("fix-", "debug-", "hoje", "today", "temp", "tmp", "teste", "test-", "caso-")
_MESES = ("janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro")


def pasta_do_usuario() -> Path:
    from ..tools.arquivos import casa_do_sentury

    return casa_do_sentury() / "skills"


def pasta_embutida() -> Path:
    return Path(__file__).resolve().parent


def _slug(nome: str) -> str:
    texto = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", texto.strip().lower()).strip("-")


def nome_de_classe(slug: str) -> bool:
    """O nome serve a uma classe de tarefa, não a um caso do dia."""
    if not slug or not 4 <= len(slug) <= 48:
        return False
    if any(t in slug for t in _NOME_DO_DIA) or any(m in slug for m in _MESES):
        return False
    return not re.search(r"\d{3,}", slug)


def _carregador() -> SkillLoader:
    return SkillLoader(pasta_embutida(), pasta_do_usuario(), com_setor=True)


def _pasta_da_skill(nome: str) -> Optional[Path]:
    conteudo = _carregador().load_skill(nome)
    return Path(conteudo.path) if conteudo else None


def _registrar(slug: str, entrada: Dict[str, Any]) -> None:
    pasta = pasta_do_usuario() / _HISTORICO
    pasta.mkdir(parents=True, exist_ok=True)
    with open(pasta / f"{slug}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({**entrada, "quando": time.time()}, ensure_ascii=False) + "\n")
    _manual_muda()


def _manual_muda() -> None:
    """O manual guarda as skills em cache; a escrita o faz remontar."""
    from ..knowledge.manual import esquecer

    esquecer()


def _pasta_gravavel(nome: str) -> tuple:
    """(pasta do usuário para esta skill, se a cópia acabou de ser criada)."""
    origem = _pasta_da_skill(nome)
    if origem is None:
        raise LookupError(f"não há skill chamada '{nome}'; veja os nomes com `listar_skills`")
    usuario = pasta_do_usuario().resolve()
    if usuario in origem.resolve().parents:
        return origem, False
    destino = usuario / origem.name
    if destino.exists():
        return destino, False
    shutil.copytree(origem, destino)
    return destino, True


def parecidas(nome: str, descricao: str, corpo: str = "", *, corte: float = 0.25,
              limite: int = 3) -> List[Dict[str, Any]]:
    """Skills que já cobrem quase o mesmo assunto (memory/semelhanca.py).

    Sem modelo, para caber em toda tentativa de criar.
    """
    from ..memory.semelhanca import semelhantes

    existentes = {e.name: e for e in _carregador().scan_skills(force=True) if e.name != _slug(nome)}
    acervo = {n: f"{n.replace('-', ' ')} {e.description}" for n, e in existentes.items()}
    novo = f"{str(nome).replace('-', ' ')} {descricao} {str(corpo)[:400]}"
    return [{"nome": n, "descricao": existentes[n].description, "semelhanca": nota}
            for n, nota in semelhantes(novo, acervo, corte=corte, limite=limite)]


_TEXTO_NA_COMPARACAO = 1500


def texto_da_skill(nome: str) -> str:
    """O corpo do SKILL.md, sem o cabeçalho, cortado para caber na pausa."""
    from .skill_loader import parse_frontmatter

    pasta = _pasta_da_skill(nome)
    if pasta is None:
        return "(não encontrada)"
    _, corpo = parse_frontmatter((pasta / "SKILL.md").read_text(encoding="utf-8"))
    corpo = corpo.strip()
    return corpo if len(corpo) <= _TEXTO_NA_COMPARACAO else corpo[:_TEXTO_NA_COMPARACAO] + "\n[...]"


def sobrepostas(corte: float = 0.5) -> List[Dict[str, Any]]:
    """Pares de skills da pasta do usuário que tratam quase da mesma tarefa.

    Só as do usuário: as que vêm prontas não se fundem. Serve à pausa de
    revisão, que decide se junta e aposenta a que sobrou.
    """
    from ..memory.semelhanca import semelhantes

    usuario = pasta_do_usuario().resolve()
    proprias = {e.name: e for e in _carregador().scan_skills(force=True)
                if usuario in Path(e.path).resolve().parents}
    textos = {n: f"{n.replace('-', ' ')} {e.description}" for n, e in proprias.items()}
    pares, vistos = [], set()
    for nome, texto in textos.items():
        outras = {n: t for n, t in textos.items() if n != nome}
        for outra, nota in semelhantes(texto, outras, corte=corte):
            par = tuple(sorted((nome, outra)))
            if par not in vistos:
                vistos.add(par)
                pares.append({"skills": list(par), "semelhanca": nota})
    return pares


def criar(nome: str, descricao: str, corpo: str, mesmo_assim: bool = False) -> Dict[str, Any]:
    slug = _slug(nome)
    if not nome_de_classe(slug):
        return {"erro": (f"'{slug}' parece nome de um caso do dia. Dê o nome da classe de tarefa "
                         "(por exemplo `revisao-de-contrato`), ou corrija uma skill que já existe.")}
    if _pasta_da_skill(slug) is not None:
        return {"erro": f"a skill '{slug}' já existe; use `corrigir` para mudar o que ela diz."}
    if not str(corpo or "").strip():
        return {"erro": "`corpo` é o texto da skill: quando usar, os passos e as armadilhas."}
    if not mesmo_assim:
        proximas = parecidas(slug, descricao, corpo)
        if proximas:
            return {
                "status": "não criada",
                "parecidas": proximas,
                "motivo": ("já existe skill sobre quase o mesmo assunto; duas skills para a mesma "
                           "tarefa dividem o que se aprende e uma fica velha"),
                "saida": ("carregue a parecida com `executar_skill` e corrija-a com `corrigir`; se "
                          "a tarefa for de fato outra, chame `criar` de novo com `mesmo_assim: true`"),
            }
    pasta = pasta_do_usuario() / slug
    pasta.mkdir(parents=True, exist_ok=False)
    descricao = " ".join(str(descricao or "").split())[:120] or "Skill aprendida."
    (pasta / "SKILL.md").write_text(
        f"---\nname: {slug}\ndescription: {descricao}\ncategory: aprendida\ntags: [aprendida]\n---\n\n"
        f"{str(corpo).strip()}\n", encoding="utf-8")
    _registrar(slug, {"acao": "criar", "arquivo": "SKILL.md", "antes": None, "copia_criada": False})
    return {"status": "criada", "skill": slug, "pasta": str(pasta)}


_TEXTO_NO_ERRO = 2500


def _com_texto_atual(motivo: str, atual: str, arquivo: str) -> str:
    """O erro já traz o texto da skill: o modelo acerta o trecho na próxima
    tentativa sem gastar uma volta só para ler."""
    corte = "" if len(atual) <= _TEXTO_NO_ERRO else "\n[...]"
    return f"{motivo}\n\nTexto atual de {arquivo}:\n{atual[:_TEXTO_NO_ERRO]}{corte}"


def corrigir(nome: str, trecho: str, novo: str, arquivo: str = "SKILL.md") -> Dict[str, Any]:
    trecho = str(trecho or "")
    if not trecho.strip():
        return {"erro": ("`trecho` é o texto exato que vai ser trocado. Para pôr uma lição nova sem "
                         "trocar nada, use `acrescentar`.")}
    relativo = _relativo_seguro(arquivo)
    if relativo is None:
        return {"erro": "arquivo fora da skill; use `SKILL.md` ou um caminho em references/, templates/, scripts/ ou assets/"}
    try:
        pasta, copia = _pasta_gravavel(nome)
    except LookupError as exc:
        return {"erro": str(exc)}
    alvo = pasta / relativo
    if not alvo.is_file():
        return {"erro": f"'{relativo}' não existe na skill '{nome}'"}
    atual = alvo.read_text(encoding="utf-8")
    vezes = atual.count(trecho)
    if vezes != 1:
        if copia:
            shutil.rmtree(pasta, ignore_errors=True)
        return {"erro": _com_texto_atual(
            f"o trecho aparece {vezes} vez(es) em {relativo}; ele precisa aparecer uma vez só. "
            "Copie do texto abaixo, ou use `acrescentar` se a lição é nova.", atual, relativo)}
    if str(novo or "").strip() and str(novo).strip() in atual:
        if copia:
            shutil.rmtree(pasta, ignore_errors=True)
        return {"status": "nada a mudar", "motivo": "o texto novo já está na skill"}
    alvo.write_text(atual.replace(trecho, str(novo or "")), encoding="utf-8")
    _registrar(pasta.name, {"acao": "corrigir", "arquivo": relativo, "antes": atual, "copia_criada": copia})
    return {"status": "corrigida", "skill": pasta.name, "arquivo": relativo,
            "copia_do_usuario": copia}


def acrescentar(nome: str, novo: str, secao: str = "") -> Dict[str, Any]:
    """Põe uma lição nova no SKILL.md: sob a seção pedida (criada se não existir)
    ou no fim. Não precisa copiar trecho nenhum."""
    novo = str(novo or "").strip()
    if not novo:
        return {"erro": "`novo` é o texto da lição a acrescentar"}
    try:
        pasta, copia = _pasta_gravavel(nome)
    except LookupError as exc:
        return {"erro": str(exc)}
    alvo = pasta / "SKILL.md"
    atual = alvo.read_text(encoding="utf-8")
    if novo in atual:
        if copia:
            shutil.rmtree(pasta, ignore_errors=True)
        return {"status": "nada a mudar", "motivo": "a lição já está na skill"}
    secao = str(secao or "").strip().lstrip("#").strip()
    linhas = atual.rstrip("\n").split("\n")
    titulo = next((i for i, l in enumerate(linhas)
                   if l.startswith("## ") and l[3:].strip().lower() == secao.lower()), None) if secao else None
    if titulo is not None:
        fim = next((i for i in range(titulo + 1, len(linhas)) if linhas[i].startswith("## ")), len(linhas))
        while fim > titulo + 1 and not linhas[fim - 1].strip():
            fim -= 1
        linhas[fim:fim] = [novo]
        texto = "\n".join(linhas) + "\n"
    elif secao:
        texto = "\n".join(linhas) + f"\n\n## {secao}\n\n{novo}\n"
    else:
        texto = "\n".join(linhas) + f"\n\n{novo}\n"
    alvo.write_text(texto, encoding="utf-8")
    _registrar(pasta.name, {"acao": "acrescentar", "arquivo": "SKILL.md", "antes": atual, "copia_criada": copia})
    return {"status": "acrescentada", "skill": pasta.name, "secao": secao or None, "copia_do_usuario": copia}


def anexar(nome: str, arquivo: str, conteudo: str) -> Dict[str, Any]:
    relativo = _relativo_seguro(arquivo)
    if relativo is None or relativo == "SKILL.md":
        return {"erro": "arquivo de apoio mora em references/, templates/, scripts/ ou assets/"}
    try:
        pasta, copia = _pasta_gravavel(nome)
    except LookupError as exc:
        return {"erro": str(exc)}
    alvo = pasta / relativo
    antes = alvo.read_text(encoding="utf-8") if alvo.is_file() else None
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text(str(conteudo or ""), encoding="utf-8")
    _registrar(pasta.name, {"acao": "anexar", "arquivo": relativo, "antes": antes, "copia_criada": copia})
    return {"status": "anexado", "skill": pasta.name, "arquivo": relativo,
            "lembrete": "diga no SKILL.md, numa linha, que este arquivo existe e para que serve"}


def aposentar(nome: str) -> Dict[str, Any]:
    """Tira de uso uma skill da pasta do usuário, guardando a pasta inteira no
    histórico: `desfazer` a traz de volta. Embutida e de setor não se aposentam."""
    origem = _pasta_da_skill(nome)
    usuario = pasta_do_usuario().resolve()
    if origem is None:
        return {"erro": f"não há skill chamada '{nome}'; veja os nomes com `listar_skills`"}
    if usuario not in Path(origem).resolve().parents:
        return {"erro": ("skill que vem pronta não se aposenta; se a sobra é uma cópia sua, "
                         "aposente a cópia e a original volta a valer")}
    guarda = usuario / _HISTORICO / "aposentadas" / f"{origem.name}-{int(time.time() * 1000)}"
    guarda.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(origem), str(guarda))
    _registrar(origem.name, {"acao": "aposentar", "arquivo": "", "antes": None, "copia_criada": False,
                             "guardada_em": str(guarda)})
    return {"status": "aposentada", "skill": origem.name}


def desfazer(nome: str) -> Dict[str, Any]:
    slug = _slug(nome)
    historico = pasta_do_usuario() / _HISTORICO / f"{slug}.jsonl"
    linhas = historico.read_text(encoding="utf-8").splitlines() if historico.is_file() else []
    if not linhas:
        return {"erro": f"não há escrita do agente para desfazer em '{slug}'"}
    ultima = json.loads(linhas[-1])
    pasta = pasta_do_usuario() / slug
    if ultima.get("acao") == "aposentar":
        guardada = Path(ultima.get("guardada_em") or "")
        if not guardada.is_dir():
            return {"erro": f"a cópia guardada de '{slug}' não está mais no histórico"}
        shutil.move(str(guardada), str(pasta))
    elif ultima.get("acao") in ("criar", "instalar") or ultima.get("copia_criada"):
        # A skill nasceu desta escrita, ou a cópia do usuário nasceu dela: some
        # inteira, e a embutida (se houver) volta a valer.
        shutil.rmtree(pasta, ignore_errors=True)
    elif ultima.get("antes") is None:
        (pasta / ultima["arquivo"]).unlink(missing_ok=True)
    else:
        (pasta / ultima["arquivo"]).write_text(ultima["antes"], encoding="utf-8")
    historico.write_text("".join(l + "\n" for l in linhas[:-1]), encoding="utf-8")
    return {"status": "desfeito", "skill": slug, "acao_desfeita": ultima.get("acao")}


def _relativo_seguro(arquivo: str) -> Optional[str]:
    relativo = str(arquivo or "SKILL.md").replace("\\", "/").strip().lstrip("/")
    partes = [p for p in relativo.split("/") if p]
    if not partes or ".." in partes:
        return None
    if partes == ["SKILL.md"]:
        return "SKILL.md"
    if partes[0] not in SKILL_SUPPORT_DIRS or len(partes) < 2:
        return None
    return "/".join(partes)


def executar(argumentos: Dict[str, Any]) -> Dict[str, Any]:
    argumentos = argumentos or {}
    acao = str(argumentos.get("acao") or "").strip().lower()
    nome = str(argumentos.get("nome") or "").strip()
    if acao not in ACOES:
        return {"erro": f"acao deve ser uma de: {', '.join(ACOES)}"}
    if not nome:
        return {"erro": "`nome` da skill é obrigatório"}
    if acao == "criar":
        return criar(nome, argumentos.get("descricao", ""), argumentos.get("corpo", ""),
                     mesmo_assim=bool(argumentos.get("mesmo_assim")))
    if acao == "corrigir":
        return corrigir(nome, argumentos.get("trecho", ""), argumentos.get("novo", ""),
                        argumentos.get("arquivo") or "SKILL.md")
    if acao == "acrescentar":
        return acrescentar(nome, argumentos.get("novo", ""), argumentos.get("secao", ""))
    if acao == "anexar":
        return anexar(nome, argumentos.get("arquivo", ""), argumentos.get("conteudo", ""))
    if acao == "aposentar":
        return aposentar(nome)
    return desfazer(nome)
