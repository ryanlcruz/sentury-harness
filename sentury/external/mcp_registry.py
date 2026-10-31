"""Servidores MCP: registro, conexão e catálogo de ferramentas.

MCP fala JSON-RPC 2.0. No transporte `stdio` é uma mensagem JSON por linha,
com o servidor rodando como subprocesso; no `http` é um POST por chamada.

Segredo não entra aqui: o registro guarda o NOME da variável de ambiente que
o servidor precisa, nunca o valor. Quem resolve o valor é o processo, na hora
de subir o servidor.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_TIMEOUT_PADRAO = 20.0

PROTOCOL_VERSION = "2025-06-18"
CLIENTE = {"name": "sentury", "version": "1.0"}

# Id de servidor que veio de um pacote de setor. O prefixo e o que separa o
# que o usuario configurou do que o pacote trouxe: e o que permite recusar
# escrita sem precisar reler o pacote a cada chamada.
PREFIXO_DE_PACOTE = "pacote:"


def caminho_da_config() -> Path:
    home = os.environ.get("SENTURY_HOME") or str(Path.home() / ".sentury")
    return Path(home) / "mcp.json"


def carregar() -> Dict[str, Any]:
    caminho = caminho_da_config()
    if not caminho.exists():
        return {"servidores": []}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        # Config quebrada não derruba a tela: o registro volta vazio.
        return {"servidores": []}
    servidores = dados.get("servidores") if isinstance(dados, dict) else None
    return {"servidores": [s for s in (servidores or []) if isinstance(s, dict)]}


def _gravar(dados: Dict[str, Any]) -> None:
    caminho = caminho_da_config()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(caminho)


def _do_setor_ativo() -> List[Dict[str, Any]]:
    """Servidores que o pacote do setor ativo traz. So do ATIVO: o do setor
    desligado nao deveria aparecer, e subir processo dele seria pior ainda."""
    try:
        from ..domains.carregador import mcp_do_pacote
        from ..domains.escolha import GENERALISTA
        from ..domains.registry import get_active_domain

        nome = getattr(get_active_domain(), "name", "")
        if not nome or nome == GENERALISTA:
            return []
        return mcp_do_pacote(nome)
    except Exception:
        logger.debug("MCP do pacote nao foi lido", exc_info=True)
        return []


def listar() -> List[Dict[str, Any]]:
    """Os do usuario mais os do pacote do setor ativo.

    Some na leitura, nunca na escrita: gravar o do pacote no arquivo do usuario
    deixaria servidor orfao quando o setor fosse desinstalado, e impediria uma
    atualizacao do pacote de chegar em quem ja instalou.
    """
    do_usuario = carregar()["servidores"]
    ja_tem = {s.get("id") for s in do_usuario}
    return do_usuario + [s for s in _do_setor_ativo() if s.get("id") not in ja_tem]


def salvar(item: Dict[str, Any]) -> Dict[str, Any]:
    """Cria ou atualiza um servidor. Sem `id`, gera um."""
    transporte = str(item.get("transporte") or "stdio").strip().lower()
    if transporte not in {"stdio", "http"}:
        raise ValueError("transporte deve ser stdio ou http")

    nome = str(item.get("nome") or "").strip()
    if not nome:
        raise ValueError("nome obrigatorio")

    pedido = str(item.get("id") or "").strip()
    if pedido.startswith(PREFIXO_DE_PACOTE):
        raise ValueError(
            "este servidor vem do pacote do setor; edite o mcp.json do pacote"
        )

    registro = {
        "id": pedido or uuid.uuid4().hex[:12],
        "nome": nome[:80],
        "transporte": transporte,
        "comando": str(item.get("comando") or "").strip(),
        "args": [str(a) for a in (item.get("args") or []) if str(a).strip()],
        "url": str(item.get("url") or "").strip(),
        # Só o nome da variável; o valor fica no ambiente do processo.
        "env_vars": [str(v).strip() for v in (item.get("env_vars") or []) if str(v).strip()],
        "ativo": bool(item.get("ativo", True)),
    }
    if transporte == "stdio" and not registro["comando"]:
        raise ValueError("stdio exige um comando")
    if transporte == "http" and not registro["url"]:
        raise ValueError("http exige uma url")

    with _LOCK:
        dados = carregar()
        restantes = [s for s in dados["servidores"] if s.get("id") != registro["id"]]
        dados["servidores"] = restantes + [registro]
        _gravar(dados)
    return registro


def remover(servidor_id: str) -> bool:
    if str(servidor_id or "").startswith(PREFIXO_DE_PACOTE):
        # Devolver False aqui seria mentir de um jeito ruim: a tela mostraria
        # "nao encontrado" para um servidor que esta bem ali na lista.
        raise ValueError(
            "este servidor vem do pacote do setor; remova-o do pacote ou troque de setor"
        )
    with _LOCK:
        dados = carregar()
        antes = len(dados["servidores"])
        dados["servidores"] = [s for s in dados["servidores"] if s.get("id") != servidor_id]
        if len(dados["servidores"]) == antes:
            return False
        _gravar(dados)
    return True


def obter(servidor_id: str) -> Optional[Dict[str, Any]]:
    return next((s for s in listar() if s.get("id") == servidor_id), None)


def _ambiente(spec: Dict[str, Any]) -> Dict[str, str]:
    """Ambiente do subprocesso com as variáveis declaradas, quando existirem."""
    env = dict(os.environ)
    faltando = [nome for nome in (spec.get("env_vars") or []) if not os.environ.get(nome)]
    if faltando:
        logger.info("MCP %s: variaveis ausentes %s", spec.get("nome"), ", ".join(faltando))
    return env


async def _checar_supply_chain(spec: Dict[str, Any]) -> None:
    """Recusa antes de baixar quando o pacote tem alerta de malware.

    `npx -y algum-pacote` baixa e executa codigo de terceiro. A declaracao vem
    do usuario; o conteudo do pacote, nao.
    """
    from ..tools.dependencias import verificar_comando

    veredito = await verificar_comando(spec.get("comando", ""), spec.get("args") or [])
    if not veredito.get("permitido"):
        raise RuntimeError(veredito.get("motivo") or "pacote recusado pela checagem de malware")
    if veredito.get("aviso"):
        logger.warning("MCP %s: %s", spec.get("nome") or spec.get("id"), veredito["aviso"])


async def _stdio_tools(spec: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    await _checar_supply_chain(spec)
    processo = await asyncio.create_subprocess_exec(
        spec["comando"], *spec.get("args", []),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_ambiente(spec),
    )

    async def enviar(mensagem: Dict[str, Any]) -> None:
        assert processo.stdin is not None
        processo.stdin.write((json.dumps(mensagem) + "\n").encode("utf-8"))
        await processo.stdin.drain()

    async def resposta(id_esperado: int) -> Dict[str, Any]:
        assert processo.stdout is not None
        while True:
            linha = await processo.stdout.readline()
            if not linha:
                raise RuntimeError("servidor encerrou sem responder")
            try:
                dado = json.loads(linha.decode("utf-8").strip() or "{}")
            except json.JSONDecodeError:
                # Servidor que loga em stdout: ignora o ruído e segue lendo.
                continue
            if dado.get("id") == id_esperado:
                return dado

    try:
        await enviar({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENTE,
            },
        })
        inicial = await asyncio.wait_for(resposta(1), timeout=timeout)
        if inicial.get("error"):
            raise RuntimeError(str(inicial["error"].get("message") or "initialize falhou"))

        await enviar({"jsonrpc": "2.0", "method": "notifications/initialized"})
        await enviar({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        lista = await asyncio.wait_for(resposta(2), timeout=timeout)
        if lista.get("error"):
            raise RuntimeError(str(lista["error"].get("message") or "tools/list falhou"))

        servidor = (inicial.get("result") or {}).get("serverInfo") or {}
        return {
            "servidor": servidor,
            "tools": (lista.get("result") or {}).get("tools") or [],
        }
    finally:
        try:
            processo.terminate()
            await asyncio.wait_for(processo.wait(), timeout=5)
        except Exception:
            try:
                processo.kill()
            except Exception:
                pass


async def _http_tools(spec: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    import httpx

    cabecalhos = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    async with httpx.AsyncClient(timeout=timeout) as cliente:
        inicial = await cliente.post(spec["url"], headers=cabecalhos, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENTE},
        })
        inicial.raise_for_status()
        dados_iniciais = _corpo_jsonrpc(inicial.text)
        sessao = inicial.headers.get("mcp-session-id")
        if sessao:
            cabecalhos["Mcp-Session-Id"] = sessao

        lista = await cliente.post(spec["url"], headers=cabecalhos, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        })
        lista.raise_for_status()
        dados_lista = _corpo_jsonrpc(lista.text)

    return {
        "servidor": (dados_iniciais.get("result") or {}).get("serverInfo") or {},
        "tools": (dados_lista.get("result") or {}).get("tools") or [],
    }


def _corpo_jsonrpc(texto: str) -> Dict[str, Any]:
    """Aceita JSON puro ou SSE (`data: {...}`), que alguns servidores usam."""
    limpo = (texto or "").strip()
    if limpo.startswith("{"):
        return json.loads(limpo)
    for linha in limpo.splitlines():
        if linha.startswith("data:"):
            corpo = linha[5:].strip()
            if corpo.startswith("{"):
                return json.loads(corpo)
    raise RuntimeError("resposta nao era JSON-RPC")


async def _stdio_call(spec: Dict[str, Any], ferramenta: str, argumentos: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    """Handshake, `tools/call` e desliga. Um processo por chamada.

    Manter o servidor vivo entre turnos daria estado escondido: dois pedidos
    partilhando um processo que ninguem ve. Enquanto nao houver um dono claro
    desse ciclo de vida, cada chamada e isolada.
    """
    await _checar_supply_chain(spec)
    processo = await asyncio.create_subprocess_exec(
        spec["comando"], *spec.get("args", []),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_ambiente(spec),
    )

    async def enviar(mensagem: Dict[str, Any]) -> None:
        assert processo.stdin is not None
        processo.stdin.write((json.dumps(mensagem) + "\n").encode("utf-8"))
        await processo.stdin.drain()

    async def resposta(id_esperado: int) -> Dict[str, Any]:
        assert processo.stdout is not None
        while True:
            linha = await processo.stdout.readline()
            if not linha:
                raise RuntimeError("servidor encerrou sem responder")
            try:
                dado = json.loads(linha.decode("utf-8").strip() or "{}")
            except json.JSONDecodeError:
                continue
            if dado.get("id") == id_esperado:
                return dado

    try:
        await enviar({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENTE},
        })
        await asyncio.wait_for(resposta(1), timeout=timeout)
        await enviar({"jsonrpc": "2.0", "method": "notifications/initialized"})
        await enviar({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": ferramenta, "arguments": argumentos or {}},
        })
        saida = await asyncio.wait_for(resposta(2), timeout=timeout)
        if saida.get("error"):
            raise RuntimeError(str(saida["error"].get("message") or "tools/call falhou"))
        return saida.get("result") or {}
    finally:
        try:
            processo.terminate()
            await asyncio.wait_for(processo.wait(), timeout=5)
        except Exception:
            try:
                processo.kill()
            except Exception:
                pass


async def _http_call(spec: Dict[str, Any], ferramenta: str, argumentos: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    import httpx

    cabecalhos = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    async with httpx.AsyncClient(timeout=timeout) as cliente:
        inicial = await cliente.post(spec["url"], headers=cabecalhos, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENTE},
        })
        inicial.raise_for_status()
        sessao = inicial.headers.get("mcp-session-id")
        if sessao:
            cabecalhos["Mcp-Session-Id"] = sessao
        chamada = await cliente.post(spec["url"], headers=cabecalhos, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": ferramenta, "arguments": argumentos or {}},
        })
        chamada.raise_for_status()
        dados = _corpo_jsonrpc(chamada.text)
    if dados.get("error"):
        raise RuntimeError(str(dados["error"].get("message") or "tools/call falhou"))
    return dados.get("result") or {}


def _texto_do_resultado(resultado: Dict[str, Any]) -> str:
    """MCP devolve blocos tipados; o agente le texto."""
    partes = []
    for bloco in (resultado.get("content") or []):
        if not isinstance(bloco, dict):
            continue
        if bloco.get("type") == "text":
            partes.append(str(bloco.get("text") or ""))
        elif bloco.get("type"):
            partes.append(f"[{bloco['type']}]")
    return "\n".join(p for p in partes if p)[:20_000]


async def chamar(
    spec: Dict[str, Any],
    ferramenta: str,
    argumentos: Optional[Dict[str, Any]] = None,
    timeout: float = _TIMEOUT_PADRAO,
) -> Dict[str, Any]:
    """Executa uma ferramenta do servidor. Nunca levanta: devolve o erro."""
    inicio = time.time()
    nome = str(ferramenta or "").strip()
    if not nome:
        return {"ok": False, "erro": "nome da ferramenta vazio"}
    try:
        if spec.get("transporte") == "http":
            resultado = await _http_call(spec, nome, argumentos or {}, timeout)
        else:
            resultado = await _stdio_call(spec, nome, argumentos or {}, timeout)
    except Exception as exc:
        return {
            "ok": False,
            "servidor": spec.get("nome"),
            "ferramenta": nome,
            "erro": f"{type(exc).__name__}: {exc}"[:300],
            "ms": int((time.time() - inicio) * 1000),
        }
    texto = _texto_do_resultado(resultado)
    deu_errado = bool(resultado.get("isError"))
    saida = {
        "ok": not deu_errado,
        "servidor": spec.get("nome"),
        "ferramenta": nome,
        "texto": texto,
        "ms": int((time.time() - inicio) * 1000),
    }
    if deu_errado:
        # O servidor pode recusar de duas formas: erro JSON-RPC (vira excecao
        # aqui em cima) ou `isError` com o motivo no conteudo. No segundo caso
        # o motivo ficava so no texto e quem le o retorno via `erro` vazio.
        saida["erro"] = texto or f"a ferramenta '{nome}' falhou no servidor"
    return saida


async def inspecionar(spec: Dict[str, Any], timeout: float = _TIMEOUT_PADRAO) -> Dict[str, Any]:
    """Conecta, lê o catálogo e desliga. Nunca levanta: devolve o erro."""
    inicio = time.time()
    try:
        if spec.get("transporte") == "http":
            dados = await _http_tools(spec, timeout)
        else:
            dados = await _stdio_tools(spec, timeout)
        return {
            "conectado": True,
            "ms": int((time.time() - inicio) * 1000),
            "servidor": dados["servidor"],
            "tools": [
                {
                    "nome": str(t.get("name") or ""),
                    "descricao": str(t.get("description") or "")[:400],
                }
                for t in dados["tools"] if isinstance(t, dict)
            ],
        }
    except Exception as exc:
        return {
            "conectado": False,
            "ms": int((time.time() - inicio) * 1000),
            "erro": f"{type(exc).__name__}: {exc}"[:300],
            "tools": [],
        }
