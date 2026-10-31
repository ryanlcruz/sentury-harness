"""O controle do navegador fica dentro da caixa; o CDP não tem porta publicada."""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

_INTERATIVOS = {"button", "checkbox", "combobox", "link", "menuitem", "option", "radio", "searchbox", "tab", "textbox"}


def _alvos():
    abrir = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with abrir.open("http://127.0.0.1:9222/json/list", timeout=2) as resposta:
        return [a for a in json.load(resposta) if a.get("type") == "page"]


def iniciar():
    try:
        alvos = _alvos()
        if alvos:
            return alvos[0]["webSocketDebuggerUrl"]
    except OSError:
        pass
    argumentos = ["chromium", "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                  "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=9222",
                  "--user-data-dir=/workspace/.navegador", "--window-size=1280,800",
                  "--disable-quic", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                  "--proxy-bypass-list=<-loopback>", "about:blank"]
    if proxy := os.environ.get("https_proxy"):
        argumentos.insert(-1, f"--proxy-server={proxy}")
    processo = subprocess.Popen(argumentos, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
    prazo = time.monotonic() + 15
    while time.monotonic() < prazo:
        if processo.poll() is not None:
            raise RuntimeError("O Chromium da caixa não iniciou.")
        try:
            alvos = _alvos()
            if alvos:
                return alvos[0]["webSocketDebuggerUrl"]
        except OSError:
            pass
        time.sleep(0.1)
    raise TimeoutError("O CDP da caixa não respondeu.")


class CDP:
    def __init__(self):
        import websocket

        self.ws = websocket.create_connection(iniciar(), timeout=20, suppress_origin=True, http_no_proxy=["127.0.0.1"])
        self.indice = 0
        self.trava = threading.Lock()
        self.chamar("Emulation.setDeviceMetricsOverride", {"width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": False})

    def enviar(self, metodo, argumentos=None):
        with self.trava:
            self.indice += 1
            self.ws.send(json.dumps({"id": self.indice, "method": metodo, "params": argumentos or {}}))
            return self.indice

    def chamar(self, metodo, argumentos=None):
        identidade = self.enviar(metodo, argumentos)
        while True:
            evento = json.loads(self.ws.recv())
            if evento.get("id") == identidade:
                if evento.get("error"):
                    raise RuntimeError(str(evento["error"].get("message", "Falha no CDP"))[:240])
                return evento.get("result", {})

    def arvore(self):
        saida = []
        for no in self.chamar("Accessibility.getFullAXTree").get("nodes", []):
            if no.get("ignored"):
                continue
            papel = (no.get("role") or {}).get("value", "")
            nome = (no.get("name") or {}).get("value", "")
            if not nome:
                continue
            item = {"role": papel, "name": str(nome)[:1000]}
            if papel in _INTERATIVOS and no.get("backendDOMNodeId"):
                item["ref"] = f"e{no['backendDOMNodeId']}"
            saida.append(item)
            if len(saida) >= 1000:
                break
        return saida

    def observar(self):
        info = self.chamar("Runtime.evaluate", {"expression": "({url:location.href,titulo:document.title})", "returnByValue": True})
        return {**(info.get("result", {}).get("value") or {}), "arvore": self.arvore()}

    def alvo(self, args):
        ref = str(args.get("ref") or "")
        if not ref and args.get("nome"):
            achados = [n for n in self.arvore() if n.get("ref") and n["name"].casefold() == str(args["nome"]).casefold()]
            if len(achados) != 1:
                raise ValueError("O nome precisa identificar um único elemento da página.")
            ref = achados[0]["ref"]
        if not re.fullmatch(r"e[0-9]+", ref):
            raise ValueError("O alvo precisa de uma referência observada na página.")
        return int(ref[1:])

    def executar(self, tipo, args):
        if tipo == "navegar":
            self.chamar("Page.enable")
            resultado = self.chamar("Page.navigate", {"url": args["url"]})
            if resultado.get("errorText"):
                raise RuntimeError(resultado["errorText"])
            prazo = time.monotonic() + 10
            while time.monotonic() < prazo:
                frame = self.chamar("Page.getFrameTree").get("frameTree", {}).get("frame", {})
                info = self.chamar("Runtime.evaluate", {"expression": "document.readyState", "returnByValue": True})
                if (not resultado.get("loaderId") or frame.get("loaderId") == resultado["loaderId"]) and info.get("result", {}).get("value") == "complete":
                    break
                time.sleep(0.05)
        elif tipo == "clicar":
            alvo = self.alvo(args)
            self.chamar("DOM.scrollIntoViewIfNeeded", {"backendNodeId": alvo})
            caixa = self.chamar("DOM.getBoxModel", {"backendNodeId": alvo})["model"]["content"]
            x, y = sum(caixa[::2]) / 4, sum(caixa[1::2]) / 4
            for evento in ("mousePressed", "mouseReleased"):
                self.chamar("Input.dispatchMouseEvent", {"type": evento, "x": x, "y": y, "button": "left", "clickCount": 1})
        elif tipo == "digitar":
            if args.get("ref") or args.get("nome"):
                self.chamar("DOM.focus", {"backendNodeId": self.alvo(args)})
            self.chamar("Input.insertText", {"text": str(args.get("texto") or "")})
            if args.get("enviar"):
                for evento in ("keyDown", "keyUp"):
                    self.chamar("Input.dispatchKeyEvent", {"type": evento, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
        elif tipo == "rolar":
            dy = min(3000, max(-3000, int(args.get("pixels") or 600)))
            self.chamar("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": 640, "y": 400, "deltaX": 0, "deltaY": dy})
        elif tipo == "imagens":
            return {"dados": self.chamar("Page.captureScreenshot", {"format": "png"})["data"], "screenshot": True}
        elif tipo == "encerrar":
            self.enviar("Browser.close")
            return {"dados": "Navegador da caixa encerrado."}
        elif tipo == "console":
            return {"dados": [], "aviso": "O histórico do console não está disponível neste provedor."}
        elif tipo != "snapshot":
            raise ValueError("Ação não disponível no navegador da caixa.")
        return {"dados": self.observar()}


def transmitir(cdp):
    import websocket

    def comandos():
        for linha in sys.stdin:
            try:
                dado = json.loads(linha)
                cdp.enviar(dado["metodo"], dado.get("argumentos"))
            except (KeyError, ValueError, OSError):
                break
        cdp.ws.close()

    cdp.chamar("Page.startScreencast", {"format": "jpeg", "quality": 70, "maxWidth": 1280, "maxHeight": 800, "everyNthFrame": 1})
    threading.Thread(target=comandos, daemon=True).start()
    cdp.ws.settimeout(0.25)
    ultimo = 0.0
    pendente = None
    while True:
        try:
            evento = json.loads(cdp.ws.recv())
        except websocket.WebSocketTimeoutException:
            evento = {}
        if evento.get("method") == "Page.screencastFrame":
            parametros = evento["params"]
            cdp.enviar("Page.screencastFrameAck", {"sessionId": parametros["sessionId"]})
            pendente = {"tipo": "quadro", "dados": parametros["data"], "metadata": parametros["metadata"]}
        agora = time.monotonic()
        if pendente and agora - ultimo >= 0.25:
            print(json.dumps(pendente), flush=True)
            ultimo, pendente = agora, None


def main():
    pedido = json.loads(sys.stdin.readline(1_000_001))
    cdp = CDP()
    try:
        if pedido.get("acao") == "screencast":
            transmitir(cdp)
            return
        retorno = cdp.executar(pedido["acao"], pedido.get("argumentos") or {})
        print(json.dumps({"ok": True, **retorno}), flush=True)
    finally:
        cdp.ws.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "erro": str(exc)[:300]}), flush=True)
