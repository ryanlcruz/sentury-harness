"""O deploy da HQ expõe apenas as rotas autenticadas dos residentes."""
import os
import socket


class SomenteHQ:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not (scope["path"] == "/hq" or scope["path"].startswith("/hq/")):
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        if scope["type"] == "websocket" and not (scope["path"].startswith("/hq/agents/") and scope["path"].endswith("/tela")):
            await send({"type": "websocket.close", "code": 1008})
            return
        await self.app(scope, receive, send)


def iniciar():
    if not os.environ.get("SENTURY_HQ_TOKEN", "").strip():
        raise SystemExit("Defina SENTURY_HQ_TOKEN antes de subir a HQ.")
    # A leitura de página pelo servidor recusa endereço interno: ver tools/web.py.
    os.environ["SENTURY_EM_SERVIDOR"] = "1"
    import uvicorn
    from ..main import app
    endereco = os.environ.get("SENTURY_HQ_LISTEN_ADDRESS") or socket.gethostbyname(socket.gethostname())
    os.environ["SENTURY_HQ_LISTEN_ADDRESS"] = endereco
    uvicorn.run(SomenteHQ(app), host=endereco, port=8000)


if __name__ == "__main__":
    iniciar()
