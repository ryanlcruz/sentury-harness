"""Rotas da tela de Configurações para as escolhas da instalação (embeddings e voz).

Cada rota devolve o cardápio de `ajustes.yaml` com o que está escolhido e se a
chave do provedor está no cofre; nenhuma devolve a chave.
"""
from __future__ import annotations

import asyncio
import sys
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import ajustes
from .memory import embeddings

router = APIRouter(prefix="/sentury/ajustes", tags=["ajustes"])

# Um par que só um modelo que entende sentido liga: o teste mostra a diferença na hora.
EXEMPLO_RELACIONADO = ("agora temos 3 vagas abertas no suporte",
                       "Decidimos desligar 3 colaboradores do time de suporte para fechar o orçamento.")
EXEMPLO_SEM_RELACAO = "escreva um poema sobre o mar"


def _entradas(secao: str) -> Dict[str, Dict[str, Any]]:
    return dict(((ajustes.cardapio().get(secao) or {}).get("provedores") or {}))


def _url_local(base_url: str) -> str:
    """Servidor local só no próprio computador: a rota não vira porta para a rede interna."""
    url = str(base_url or "").rstrip("/")
    if not (url.startswith("http://127.0.0.1:") or url.startswith("http://localhost:")):
        raise HTTPException(status_code=422, detail="o servidor local precisa estar em 127.0.0.1 ou localhost")
    return url


# Embeddings ------------------------------------------------------------------

class EscolhaDeEmbeddings(BaseModel):
    provedor: str = Field(..., max_length=40)
    modelo: str = Field(default="", max_length=200)
    base_url: str = Field(default="", max_length=200)


def _estado_dos_embeddings() -> Dict[str, Any]:
    atual = embeddings.escolha()
    provedores = []
    for nome, entrada in _entradas(embeddings.SECAO).items():
        provedores.append({
            "nome": nome, "rotulo": entrada.get("rotulo", nome), "descricao": entrada.get("descricao", ""),
            "tem_chave": ajustes.tem_chave(entrada), "precisa_chave": bool(entrada.get("chave")),
            "chave_env": str(entrada.get("chave") or ""),
            "base_url": entrada.get("base_url", ""), "modelos": list((entrada.get("modelos") or {}).keys()),
            "modelos_do_servidor": bool(entrada.get("modelos_do_servidor")),
        })
    return {"escolha": {"provedor": atual["provedor"], "modelo": atual["modelo"], "base_url": atual["base_url"]},
            "origem": atual["origem"], "ligado": embeddings.ligado(), "provedores": provedores}


def _validar(escolha: EscolhaDeEmbeddings) -> Dict[str, Any]:
    entrada = ajustes.provedor(embeddings.SECAO, escolha.provedor)
    if not entrada:
        raise HTTPException(status_code=422, detail=f"provedor desconhecido: {escolha.provedor}")
    valores = {"provedor": escolha.provedor}
    if escolha.provedor == "nenhum":
        return valores
    if entrada.get("modelos_do_servidor"):
        valores["base_url"] = _url_local(escolha.base_url or entrada.get("base_url", ""))
        if not escolha.modelo.strip():
            raise HTTPException(status_code=422, detail="escolha um modelo do servidor local")
    elif escolha.modelo not in (entrada.get("modelos") or {}):
        raise HTTPException(status_code=422, detail=f"modelo fora da lista de {escolha.provedor}")
    if not ajustes.tem_chave(entrada):
        raise HTTPException(status_code=422, detail=f"a chave de {entrada.get('rotulo', escolha.provedor)} "
                                                    "não está cadastrada em Provedores")
    valores["modelo"] = escolha.modelo.strip()
    return valores


@router.get("/embeddings")
async def ver_embeddings() -> Dict[str, Any]:
    return _estado_dos_embeddings()


@router.put("/embeddings")
async def escolher_embeddings(escolha: EscolhaDeEmbeddings) -> Dict[str, Any]:
    ajustes.gravar(embeddings.SECAO, _validar(escolha))
    principal = sys.modules.get(f"{__package__}.main")
    if principal is not None:  # a base de conceitos montada no início passa a seguir a escolha nova
        try:
            principal._refresh_knowledge_base()
        except Exception:
            pass
    return _estado_dos_embeddings()


@router.post("/embeddings/testar")
async def testar_embeddings(escolha: EscolhaDeEmbeddings) -> Dict[str, Any]:
    """Mede o modelo num par que tem relação e num que não tem, sem gravar nada."""
    valores = _validar(escolha)
    if valores["provedor"] == "nenhum":
        return {"ok": True, "mensagem": "Sem modelo: a busca compara palavras."}
    entrada = ajustes.provedor(embeddings.SECAO, valores["provedor"])
    base = valores.get("base_url") or entrada.get("base_url", "")
    pergunta, decisao = EXEMPLO_RELACIONADO
    inicio = time.monotonic()
    try:
        vetores = await asyncio.to_thread(embeddings.chamar, base, ajustes.chave(entrada), valores["modelo"],
                                          [pergunta, decisao, EXEMPLO_SEM_RELACAO], 15.0)
    except Exception as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {str(exc)[:200]}"}
    ms = round((time.monotonic() - inicio) * 1000)
    corte = embeddings.corte_do({"entrada": entrada, "modelo": valores["modelo"]})
    relacionado = round(embeddings.cosseno(vetores[0], vetores[1]), 3)
    sem_relacao = round(embeddings.cosseno(vetores[2], vetores[1]), 3)
    return {"ok": True, "ms": ms, "dimensoes": len(vetores[0]), "corte": corte, "relacionado": relacionado,
            "sem_relacao": sem_relacao, "separa": relacionado >= corte > sem_relacao,
            "exemplo": {"pergunta": pergunta, "decisao": decisao, "sem_relacao": EXEMPLO_SEM_RELACAO}}


@router.get("/embeddings/servidor-local")
async def modelos_do_servidor_local(base_url: str = "http://127.0.0.1:1234/v1") -> Dict[str, Any]:
    """Os modelos que o servidor local oferece; os de embeddings primeiro quando ele diz o tipo."""
    base = _url_local(base_url)
    raiz = base[:-3] if base.endswith("/v1") else base
    try:
        async with httpx.AsyncClient(timeout=3.0) as cliente:
            # O LM Studio diz o tipo de cada modelo nesta rota; os outros servidores só listam.
            detalhada = await cliente.get(f"{raiz}/api/v0/models")
            if detalhada.status_code == 200:
                dados = detalhada.json().get("data") or []
                return {"ligado": True, "modelos": [m["id"] for m in dados if m.get("type") == "embeddings"],
                        "outros": [m["id"] for m in dados if m.get("type") != "embeddings"]}
            simples = await cliente.get(f"{base}/models")
            simples.raise_for_status()
            return {"ligado": True, "modelos": [m["id"] for m in simples.json().get("data") or []], "outros": []}
    except httpx.HTTPError:
        return {"ligado": False, "modelos": [], "outros": []}


# Voz -------------------------------------------------------------------------

class EscolhaDeVoz(BaseModel):
    provedor: str = Field(..., max_length=40)
    modelo: str = Field(default="", max_length=200)
    voz: str = Field(default="", max_length=60)


def escolha_de_voz() -> Dict[str, str]:
    """Provedor, modelo e voz da ligação: a escolha da tela, ou o padrão do cardápio."""
    cardapio = ajustes.cardapio().get("voz") or {}
    lido = ajustes.ler("voz")
    nome = str(lido.get("provedor") or cardapio.get("padrao") or "gemini_live")
    entrada = ajustes.provedor("voz", nome)
    from .config import settings

    # Sem escolha na tela, vale o modelo do ambiente antes do padrão do cardápio.
    do_ambiente = getattr(settings, "GEMINI_LIVE_MODEL", "") if nome == "gemini_live" else ""
    return {"provedor": nome, "modelo": str(lido.get("modelo") or do_ambiente or entrada.get("modelo_padrao") or ""),
            "voz": str(lido.get("voz") or entrada.get("voz_padrao") or "")}


async def _modelos_ao_vivo(chave: str) -> List[str]:
    """Os modelos do Gemini que aceitam conversa ao vivo, pela própria API."""
    if not chave:
        return []
    try:
        async with httpx.AsyncClient(timeout=6.0) as cliente:
            resposta = await cliente.get("https://generativelanguage.googleapis.com/v1beta/models",
                                         params={"pageSize": 1000}, headers={"x-goog-api-key": chave})
            resposta.raise_for_status()
            return sorted(m["name"].split("/", 1)[-1] for m in resposta.json().get("models") or []
                          if "bidiGenerateContent" in (m.get("supportedGenerationMethods") or []))
    except Exception:
        return []


@router.get("/voz")
async def ver_voz() -> Dict[str, Any]:
    atual = escolha_de_voz()
    provedores = []
    for nome, entrada in _entradas("voz").items():
        modelos = await _modelos_ao_vivo(ajustes.chave(entrada)) if nome == "gemini_live" else []
        padrao = entrada.get("modelo_padrao")
        if padrao and padrao not in modelos:
            modelos.insert(0, padrao)
        provedores.append({"nome": nome, "rotulo": entrada.get("rotulo", nome), "descricao": entrada.get("descricao", ""),
                           "tem_chave": ajustes.tem_chave(entrada), "modelos": modelos,
                           "vozes": list(entrada.get("vozes") or [])})
    return {"escolha": atual, "provedores": provedores}


@router.put("/voz")
async def escolher_voz(escolha: EscolhaDeVoz) -> Dict[str, Any]:
    entrada = ajustes.provedor("voz", escolha.provedor)
    if not entrada:
        raise HTTPException(status_code=422, detail=f"provedor de voz desconhecido: {escolha.provedor}")
    vozes = entrada.get("vozes") or []
    if escolha.voz and vozes and escolha.voz not in vozes:
        raise HTTPException(status_code=422, detail=f"voz fora da lista de {escolha.provedor}")
    ajustes.gravar("voz", {"provedor": escolha.provedor, "modelo": escolha.modelo.strip(), "voz": escolha.voz})
    return await ver_voz()


# Modelos locais --------------------------------------------------------------

class PedidoDeModelo(BaseModel):
    modelo: str = Field(default="", max_length=300)
    base_url: str = Field(default="http://127.0.0.1:1234/v1", max_length=200)


class PedidoDeDownload(BaseModel):
    repositorio: str = Field(..., max_length=200, pattern=r"^[\w.-]+/[\w.-]+$")
    arquivo: str = Field(..., max_length=300)


def _estado_local() -> Dict[str, Any]:
    from . import modelos_locais as ml

    memoria = ml.memoria_da_maquina()
    return {"lmstudio": bool(ml.lms()), "pasta": str(ml.pasta_de_modelos()), "memoria": memoria,
            "baixados": ml.baixados(), "servidor": ml.servidor(), "escolhido": ml.escolhido(),
            "baixando": ml.andamento()}


def _reconstruir_cadeia() -> None:
    principal = sys.modules.get(f"{__package__}.main")
    if principal is not None:
        principal._refresh_provider_chains()


@router.get("/modelos-locais")
async def ver_modelos_locais() -> Dict[str, Any]:
    return await asyncio.to_thread(_estado_local)


@router.post("/modelos-locais/rodar")
async def rodar_modelo_local(pedido: PedidoDeModelo) -> Dict[str, Any]:
    """Liga o servidor do LM Studio e carrega o modelo baixado."""
    from . import modelos_locais as ml

    if pedido.modelo not in {m["chave"] for m in ml.baixados()}:
        raise HTTPException(status_code=422, detail="esse modelo não está na pasta do LM Studio")
    resultado = await asyncio.to_thread(ml.carregar, pedido.modelo)
    return {**resultado, "estado": await asyncio.to_thread(_estado_local)}


@router.post("/modelos-locais/descarregar")
async def descarregar_modelo_local(pedido: PedidoDeModelo) -> Dict[str, Any]:
    from . import modelos_locais as ml

    resultado = await asyncio.to_thread(ml.descarregar, pedido.modelo)
    return {**resultado, "estado": await asyncio.to_thread(_estado_local)}


@router.post("/modelos-locais/testar")
async def testar_modelo_local(pedido: PedidoDeModelo) -> Dict[str, Any]:
    from . import modelos_locais as ml

    return await asyncio.to_thread(ml.testar, pedido.modelo, _url_local(pedido.base_url))


@router.put("/modelos-locais/usar")
async def usar_modelo_local(pedido: PedidoDeModelo) -> Dict[str, Any]:
    """O modelo carregado vira o provedor local do roteador; vazio tira."""
    from . import modelos_locais as ml

    base = _url_local(pedido.base_url)
    if pedido.modelo and pedido.modelo not in ml.servidor(base)["carregados"]:
        raise HTTPException(status_code=422, detail="carregue o modelo no servidor antes de usar")
    await asyncio.to_thread(ml.usar, pedido.modelo)
    _reconstruir_cadeia()
    return await asyncio.to_thread(_estado_local)


@router.get("/modelos-locais/procurar")
async def procurar_modelos_para_baixar(termo: str) -> Dict[str, Any]:
    from . import modelos_locais as ml

    try:
        return {"resultados": await asyncio.to_thread(ml.buscar_para_baixar, termo.strip()[:80])}
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"a biblioteca de modelos não respondeu: {exc}") from exc


@router.get("/modelos-locais/procurar/arquivos")
async def arquivos_no_hugging_face(repositorio: str) -> Dict[str, Any]:
    from . import modelos_locais as ml

    PedidoDeDownload(repositorio=repositorio, arquivo="x")  # valida o formato dono/nome
    try:
        return {"arquivos": await asyncio.to_thread(ml.arquivos_do_repositorio, repositorio)}
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"a biblioteca de modelos não respondeu: {exc}") from exc


@router.post("/modelos-locais/baixar")
async def baixar_do_hugging_face(pedido: PedidoDeDownload) -> Dict[str, Any]:
    from . import modelos_locais as ml

    if not pedido.arquivo.lower().endswith(".gguf") or ".." in pedido.arquivo:
        raise HTTPException(status_code=422, detail="escolha um arquivo .gguf do repositório")
    return await asyncio.to_thread(ml.baixar, pedido.repositorio, pedido.arquivo)


# Navegador -------------------------------------------------------------------

class EscolhaDoNavegador(BaseModel):
    perfil: str = Field(..., pattern=r"^(pessoa|agente)$")
    nome: str = Field(default="", max_length=40, pattern=r"^[\w ]*$")


def _estado_do_navegador() -> Dict[str, Any]:
    from .tools import perfil_do_agente as perfil

    cardapio = ajustes.cardapio().get("navegador") or {}
    return {"escolha": {"perfil": perfil.perfil_escolhido(), "nome": perfil.nome_do_perfil()},
            "origem": "tela" if ajustes.ler("navegador") else "env",
            "perfis": [{"nome": nome, **dados} for nome, dados in (cardapio.get("perfis") or {}).items()],
            "chrome_encontrado": bool(perfil._chrome())}


@router.get("/navegador")
async def ver_navegador() -> Dict[str, Any]:
    return _estado_do_navegador()


@router.put("/navegador")
async def escolher_navegador(escolha: EscolhaDoNavegador) -> Dict[str, Any]:
    """Grava a escolha; o Chrome do agente ganha (ou refaz) o atalho no menu Iniciar."""
    from .tools import perfil_do_agente as perfil

    nome = escolha.nome.strip() or str((ajustes.cardapio().get("navegador") or {}).get("nome_padrao") or "Agente")
    atalho = ""
    if escolha.perfil == "agente" and sys.platform == "win32":
        try:
            atalho = str(await asyncio.to_thread(perfil.criar_atalho, nome))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"não consegui criar o atalho do Chrome: {exc}") from exc
    ajustes.gravar("navegador", {"perfil": escolha.perfil, "nome": nome})
    return {**_estado_do_navegador(), "atalho": atalho}


# Servidores locais do roteador -------------------------------------------------

def _catalogo_do_roteador() -> Dict[str, Dict[str, Any]]:
    principal = sys.modules.get(f"{__package__}.main")
    config = getattr(principal, "_robin_config", None)
    return dict(getattr(config, "providers", {}) or {})


@router.get("/locais")
async def detectar_locais() -> Dict[str, Any]:
    """O que já está instalado e rodando nesta máquina, sem a pessoa precisar dizer."""
    from . import modelos_locais as ml

    try:
        from robinbandit.accounts.account_config import overrides_de_modelos

        em_uso = overrides_de_modelos()
    except Exception:
        em_uso = {}
    return {"locais": await asyncio.to_thread(ml.detectar, _catalogo_do_roteador(), em_uso)}
