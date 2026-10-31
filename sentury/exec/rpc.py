"""RPC local e efemero entre o sandbox Python e o processo da API."""
from __future__ import annotations

import contextvars
import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Dict, Optional


class ServidorRPC:
    """Publica apenas a allowlist recebida em ``127.0.0.1:0``."""

    def __init__(self, ferramentas: Dict[str, Callable[..., Any]]):
        self._ferramentas = dict(ferramentas)
        self._contexto = contextvars.copy_context()
        self.token = secrets.token_urlsafe(32)
        self._servidor: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        if self._servidor is None:
            raise RuntimeError("RPC ainda nao iniciado")
        host, porta = self._servidor.server_address[:2]
        return f"http://{host}:{porta}/rpc"

    def iniciar(self) -> "ServidorRPC":
        dono = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _formato: str, *_args: Any) -> None:
                return

            def _json(self, status: int, carga: Dict[str, Any]) -> None:
                corpo = json.dumps(carga, ensure_ascii=False, default=str).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)

            def _descartar_corpo(self) -> None:
                # Responder sem ler o corpo fecha a conexao com o cliente ainda
                # enviando; no Windows ele recebe WinError 10053 em vez do 401.
                try:
                    tamanho = int(self.headers.get("Content-Length", "0"))
                    if 0 < tamanho <= 1_000_000:
                        self.rfile.read(tamanho)
                except (ValueError, OSError):
                    pass

            def do_POST(self) -> None:  # noqa: N802 - nome do protocolo HTTP
                if self.path != "/rpc":
                    self._descartar_corpo()
                    self._json(404, {"erro": "endpoint inexistente"})
                    return
                recebido = self.headers.get("Authorization", "")
                if not hmac.compare_digest(recebido, f"Bearer {dono.token}"):
                    self._descartar_corpo()
                    self._json(401, {"erro": "token invalido"})
                    return
                try:
                    tamanho = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    tamanho = 0
                if tamanho <= 0 or tamanho > 1_000_000:
                    self._json(413, {"erro": "pedido vazio ou grande demais"})
                    return
                try:
                    pedido = json.loads(self.rfile.read(tamanho))
                except (ValueError, OSError):
                    self._json(400, {"erro": "JSON invalido"})
                    return
                nome = str(pedido.get("ferramenta") or "")
                ferramenta = dono._ferramentas.get(nome)
                if ferramenta is None:
                    self._json(403, {"erro": "ferramenta nao permitida"})
                    return
                args = pedido.get("argumentos") or []
                kwargs = pedido.get("nomeados") or {}
                if not isinstance(args, list) or not isinstance(kwargs, dict):
                    self._json(400, {"erro": "argumentos invalidos"})
                    return
                try:
                    resultado = dono._contexto.run(ferramenta, *args, **kwargs)
                    self._json(200, {"ok": True, "resultado": resultado})
                except BaseException as exc:  # falha volta ao filho; API segue viva
                    self._json(500, {"erro": f"{type(exc).__name__}: {exc}"})

        self._servidor = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._servidor.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="sentury-python-rpc",
            daemon=True,
        )
        self._thread.start()
        return self

    def fechar(self) -> None:
        if self._servidor is not None:
            if self._thread is not None and self._thread.is_alive():
                self._servidor.shutdown()
            self._servidor.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._servidor = None
        self._thread = None

    def __enter__(self) -> "ServidorRPC":
        return self.iniciar()

    def __exit__(self, *_args: Any) -> None:
        self.fechar()
