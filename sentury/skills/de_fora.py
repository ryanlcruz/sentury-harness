"""Skills de fora: procurar no diretório público, ver antes e instalar com a pessoa.

A busca usa o diretório público de skills; o texto mora no GitHub. `ver` não
grava nada e prende a skill num commit, para o que a pessoa aprova ser o que
entra. `instalar` pergunta sempre na hora, mesmo com "permitir tudo": a skill é
texto e script de terceiro que passa a valer na máquina dela.

O cabeçalho da skill instalada é reescrito pelo Sentury: guarda origem, commit e
licença, e descarta gatilho de ativação automática, que deixaria um texto de
fora entrar em qualquer pedido.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from pathlib import PurePosixPath
from typing import Any, Dict, Optional
from urllib.parse import quote

from . import escrita
from .skill_loader import parse_frontmatter

ACOES = ("buscar", "ver", "instalar")
BUSCA_PADRAO = "https://skills.sh/api/search"
_GITHUB = "https://api.github.com/repos/"
_BRUTO = "https://raw.githubusercontent.com/"

MAX_ARQUIVOS = 40
MAX_BYTES_ARQUIVO = 400_000
MAX_BYTES_TOTAL = 1_500_000
MAX_TEXTO_NO_VER = 6_000
# Só texto entra: o download decodifica como texto, e binário chegaria corrompido.
_DE_TEXTO = {".md", ".txt", ".py", ".js", ".mjs", ".ts", ".sh", ".ps1", ".bat", ".json", ".yaml",
             ".yml", ".toml", ".ini", ".cfg", ".html", ".css", ".csv", ".xml", ".sql", ".rb", ".go"}
_DE_SCRIPT = {".py", ".js", ".mjs", ".ts", ".sh", ".ps1", ".bat", ".rb", ".go"}
_REPOSITORIO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_PARTE_SEGURA = re.compile(r"^[A-Za-z0-9_.-]+$")


def _url_de_busca() -> str:
    return os.environ.get("SENTURY_SKILLS_BUSCA_URL", "").strip() or BUSCA_PADRAO


async def _json(url: str) -> Any:
    from ..tools.web import ler_bruto

    resposta = await ler_bruto(url)
    if not resposta.get("ok"):
        motivo = resposta.get("motivo") or f"status {resposta.get('status')}"
        raise LookupError(f"{url} não respondeu: {motivo}")
    try:
        return json.loads(resposta.get("corpo") or "")
    except ValueError as exc:
        raise LookupError(f"{url} não devolveu JSON") from exc


async def _texto(url: str) -> str:
    from ..tools.web import ler_bruto

    resposta = await ler_bruto(url)
    if not resposta.get("ok"):
        raise LookupError(f"não deu para baixar {url}: {resposta.get('motivo') or resposta.get('status')}")
    if resposta.get("truncado"):
        raise LookupError(f"{url} passa do tamanho que uma skill pode ter")
    return str(resposta.get("corpo") or "")


async def buscar(consulta: str, limite: int = 8) -> Dict[str, Any]:
    consulta = " ".join(str(consulta or "").split())
    if len(consulta) < 2:
        return {"erro": "`consulta` é o assunto da skill, por exemplo `pdf` ou `planilha excel`"}
    dados = await _json(f"{_url_de_busca()}?q={quote(consulta)}")
    achadas = []
    for item in (dados.get("skills") if isinstance(dados, dict) else None) or []:
        if not isinstance(item, dict):
            continue
        achadas.append({
            "id": str(item.get("id") or ""),
            "nome": str(item.get("name") or item.get("skillId") or ""),
            "repositorio": str(item.get("source") or ""),
            "instalacoes": int(item.get("installs") or 0),
        })
    achadas = achadas[:max(1, min(int(limite or 8), 20))]
    return {"consulta": consulta, "skills": achadas,
            "proximo_passo": "`ver` com o `id` mostra o texto, a licença e os arquivos antes de instalar"}


def _separar_id(skill_id: str) -> tuple:
    """`dono/repo/skill` em (repositório, skill)."""
    partes = [p for p in str(skill_id or "").strip().strip("/").split("/") if p]
    if len(partes) != 3 or not all(_PARTE_SEGURA.match(p) for p in partes):
        raise ValueError("`id` tem a forma dono/repositorio/skill, como veio do `buscar`")
    return "/".join(partes[:2]), partes[2]


def _relativo_valido(caminho: str) -> bool:
    partes = PurePosixPath(caminho).parts
    return bool(partes) and all(p not in ("..", ".") and not p.startswith(".") for p in partes)


async def _localizar(skill_id: str) -> Dict[str, Any]:
    """Acha a pasta da skill no repositório, presa no commit atual do ramo padrão."""
    repositorio, skill = _separar_id(skill_id)
    if not _REPOSITORIO.match(repositorio):
        raise ValueError("repositório inválido")
    repo = await _json(_GITHUB + repositorio)
    ramo = str(repo.get("default_branch") or "main")
    ref = await _json(f"{_GITHUB}{repositorio}/git/ref/heads/{quote(ramo)}")
    commit = str((ref.get("object") or {}).get("sha") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise LookupError(f"não achei o commit atual de {repositorio}")
    arvore = await _json(f"{_GITHUB}{repositorio}/git/trees/{commit}?recursive=1")
    itens = [i for i in arvore.get("tree") or [] if i.get("type") == "blob"]
    candidatas = [str(i["path"]) for i in itens
                  if str(i.get("path", "")).endswith("SKILL.md")
                  and PurePosixPath(i["path"]).parent.name.lower() == skill.lower()]
    if not candidatas:
        raise LookupError(f"não achei o SKILL.md de '{skill}' em {repositorio}")
    pasta = str(PurePosixPath(sorted(candidatas, key=len)[0]).parent)
    prefixo = "" if pasta == "." else pasta + "/"
    arquivos, de_fora = [], []
    for item in itens:
        caminho = str(item.get("path", ""))
        if not caminho.startswith(prefixo):
            continue
        relativo = caminho[len(prefixo):]
        tamanho = int(item.get("size") or 0)
        if not _relativo_valido(relativo) or PurePosixPath(relativo).suffix.lower() not in _DE_TEXTO \
                or tamanho > MAX_BYTES_ARQUIVO:
            de_fora.append(relativo)
            continue
        arquivos.append({"caminho": relativo, "bytes": tamanho})
    licenca = str(((repo.get("license") or {}) if isinstance(repo.get("license"), dict) else {}).get("spdx_id") or "")
    return {"id": f"{repositorio}/{skill}", "repositorio": repositorio, "skill": skill, "commit": commit,
            "pasta": pasta, "arquivos": arquivos, "fora_da_copia": de_fora, "licenca_do_repositorio": licenca}


def _cabe(local: Dict[str, Any]) -> Optional[str]:
    if len(local["arquivos"]) > MAX_ARQUIVOS:
        return f"a skill tem {len(local['arquivos'])} arquivos; o limite é {MAX_ARQUIVOS}"
    total = sum(a["bytes"] for a in local["arquivos"])
    if total > MAX_BYTES_TOTAL:
        return f"a skill tem {total // 1000} KB; o limite é {MAX_BYTES_TOTAL // 1000} KB"
    return None


def _url_bruta(local: Dict[str, Any], relativo: str) -> str:
    caminho = relativo if local["pasta"] == "." else f"{local['pasta']}/{relativo}"
    return f"{_BRUTO}{local['repositorio']}/{local['commit']}/{quote(caminho)}"


def _resumo(local: Dict[str, Any], frontmatter: Dict[str, Any]) -> Dict[str, Any]:
    scripts = [a["caminho"] for a in local["arquivos"] if PurePosixPath(a["caminho"]).suffix.lower() in _DE_SCRIPT]
    arquivo_de_licenca = next((a["caminho"] for a in local["arquivos"]
                               if PurePosixPath(a["caminho"]).stem.upper() in ("LICENSE", "LICENCE")), "")
    licenca = str(frontmatter.get("license") or local["licenca_do_repositorio"]
                  or (f"em {arquivo_de_licenca}, leia antes" if arquivo_de_licenca else "não declarada"))
    return {
        "id": local["id"], "repositorio": f"github.com/{local['repositorio']}", "commit": local["commit"][:12],
        "descricao": " ".join(str(frontmatter.get("description") or "").split())[:300],
        "licenca": licenca, "arquivos": [a["caminho"] for a in local["arquivos"]], "scripts": scripts,
        "fora_da_copia": local["fora_da_copia"],
        "kb": round(sum(a["bytes"] for a in local["arquivos"]) / 1000, 1),
    }


async def ver(skill_id: str) -> Dict[str, Any]:
    local = await _localizar(skill_id)
    texto = await _texto(_url_bruta(local, "SKILL.md"))
    frontmatter, corpo = parse_frontmatter(texto)
    resumo = _resumo(local, frontmatter)
    nome = escrita._slug(local["skill"])
    parecidas = escrita.parecidas(nome, resumo["descricao"], corpo, corte=0.4)
    corte = "" if len(texto) <= MAX_TEXTO_NO_VER else "\n[...]"
    return {**resumo, "texto": texto[:MAX_TEXTO_NO_VER] + corte, "excede_limite": _cabe(local),
            "ja_instalada": escrita._pasta_da_skill(nome) is not None, "parecidas_suas": parecidas,
            "proximo_passo": ("antes de `instalar`, diga à pessoa de onde vem, a licença e os scripts; "
                              "se uma parecida já cobre a tarefa, ela pode não precisar desta")}


def _cabecalho(nome: str, resumo: Dict[str, Any], local: Dict[str, Any]) -> str:
    def linha(valor: str) -> str:
        return json.dumps(" ".join(str(valor or "").split()), ensure_ascii=False)

    return ("---\n"
            f"name: {nome}\n"
            f"description: {linha(resumo['descricao'][:200] or 'Skill instalada de fora.')}\n"
            "category: de-fora\n"
            "tags: [de-fora]\n"
            f"license: {linha(resumo['licenca'])}\n"
            f"origem: {linha('skills.sh/' + local['id'])}\n"
            f"repositorio: {linha(resumo['repositorio'])}\n"
            f"commit: {local['commit']}\n"
            f"instalada_em: {time.strftime('%Y-%m-%d')}\n"
            "---\n\n")


# O registro de permissão assina só o programa (`find_skills`); a skill e o
# commit que o cartão mostrou ficam aqui, para a aprovação não servir a outra.
_MOSTRADAS: Dict[str, str] = {}


def _pedido_do_cartao(resumo: Dict[str, Any], nome: str, sessao: str) -> Optional[Dict[str, Any]]:
    """None quando a pessoa aprovou esta skill neste commit; senão o cartão."""
    from ..exec.contrato import CodigoDeErro
    from ..exec.politica import avaliar

    comando = f"find_skills instalar {resumo['id']}@{resumo['commit']} como {nome}"
    decisao = avaliar(comando, sessao, checar_alvo=False, na_hora=True, consumir=False)
    if decisao.get("permitido") and _MOSTRADAS.get(sessao) == comando:
        avaliar(comando, sessao, checar_alvo=False, na_hora=True)
        _MOSTRADAS.pop(sessao, None)
        return None
    scripts = ", ".join(resumo["scripts"]) or "nenhum"
    base = {"ok": False, "executado": False, "fase": "permissao", "chave": comando, "comando": comando,
            "motivo": (f"instalar a skill {nome} de {resumo['repositorio']} ({len(resumo['arquivos'])} "
                       f"arquivos, {resumo['kb']} KB). Texto e scripts de terceiro passam a valer como "
                       f"skill sua. Licença: {resumo['licenca']}. Scripts: {scripts}")}
    if decisao.get("precisa_perguntar") or decisao.get("permitido"):
        _MOSTRADAS[sessao] = comando
        return {**base, "precisa_permissao": True, "so_desta_vez": True,
                "codigo_erro": CodigoDeErro.PRECISA_PERMISSAO}
    return {**base, "recusado": True, "motivo": str(decisao.get("motivo") or ""),
            "codigo_erro": CodigoDeErro.RECUSADO_POLITICA}


async def instalar(skill_id: str, nome: str = "", sessao: str = "") -> Dict[str, Any]:
    local = await _localizar(skill_id)
    excesso = _cabe(local)
    if excesso:
        return {"erro": excesso}
    slug = escrita._slug(nome or local["skill"])
    if not 2 <= len(slug) <= 64:
        return {"erro": "o nome da skill precisa ter entre 2 e 64 letras ou números"}
    if escrita._pasta_da_skill(slug) is not None:
        return {"erro": (f"já existe uma skill chamada '{slug}'. Para ter as duas, instale com outro "
                         "`nome`; para trocar, `aprender_skill` com `aposentar` a sua antes")}
    texto = await _texto(_url_bruta(local, "SKILL.md"))
    frontmatter, corpo = parse_frontmatter(texto)
    resumo = _resumo(local, frontmatter)
    cartao = _pedido_do_cartao(resumo, slug, sessao)
    if cartao is not None:
        return cartao

    destino = escrita.pasta_do_usuario() / slug
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporaria = tempfile.mkdtemp(prefix=f".{slug}-", dir=destino.parent)
    try:
        for arquivo in local["arquivos"]:
            relativo = arquivo["caminho"]
            conteudo = (_cabecalho(slug, resumo, local) + corpo.lstrip("\n")
                        if relativo == "SKILL.md" else await _texto(_url_bruta(local, relativo)))
            alvo = os.path.join(temporaria, *PurePosixPath(relativo).parts)
            os.makedirs(os.path.dirname(alvo), exist_ok=True)
            with open(alvo, "w", encoding="utf-8", newline="") as f:
                f.write(conteudo)
        shutil.move(temporaria, destino)
    except Exception:
        shutil.rmtree(temporaria, ignore_errors=True)
        raise
    escrita._registrar(slug, {"acao": "instalar", "arquivo": "SKILL.md", "antes": None, "copia_criada": False,
                              "origem": resumo["id"], "commit": local["commit"]})
    return {"status": "instalada", "skill": slug, "origem": resumo["repositorio"], "commit": resumo["commit"],
            "licenca": resumo["licenca"], "scripts": resumo["scripts"],
            "fora_da_copia": resumo["fora_da_copia"],
            "lembrete": "`aprender_skill` com `desfazer` remove a instalação"}


async def executar(argumentos: Dict[str, Any], sessao: str = "") -> Dict[str, Any]:
    argumentos = argumentos or {}
    acao = str(argumentos.get("acao") or "").strip().lower()
    if acao not in ACOES:
        return {"erro": f"acao deve ser uma de: {', '.join(ACOES)}"}
    try:
        if acao == "buscar":
            return await buscar(argumentos.get("consulta", ""), argumentos.get("limite") or 8)
        skill_id = str(argumentos.get("id") or "")
        if acao == "ver":
            return await ver(skill_id)
        return await instalar(skill_id, str(argumentos.get("nome") or ""), sessao)
    except (LookupError, ValueError) as exc:
        return {"erro": str(exc)}


__all__ = ["ACOES", "buscar", "executar", "instalar", "ver"]
