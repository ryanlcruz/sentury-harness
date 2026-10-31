"""A saída HTTP conecta no endereço aprovado, sem resolver o nome uma segunda vez."""
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import select
import socket
import threading
import time
from urllib.parse import urlsplit

TETO_DO_CORPO = 16 * 1024 * 1024
TETO_DO_TUNEL = 300
_TRANSICAO = tuple(ipaddress.ip_network(n) for n in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32"))
_HOP = {"connection", "proxy-connection", "proxy-authorization", "keep-alive", "te", "trailer", "transfer-encoding", "upgrade"}


class DestinoRecusado(ValueError):
    pass


def endereco_publico(texto):
    ip = ipaddress.ip_address(texto)
    if not ip.is_global or ip.is_multicast or ip.is_unspecified:
        raise DestinoRecusado("O proxy só conecta em endereços públicos.")
    if ip.version == 6 and (ip.ipv4_mapped or any(ip in n for n in _TRANSICAO)):
        raise DestinoRecusado("Endereço de transição não é aceito pelo proxy.")
    return str(ip)


def resolver(host, porta, *, resolver_dns=None, proibidos=()):
    if porta not in (80, 443) or not host or len(host) > 253:
        raise DestinoRecusado("Destino HTTP inválido: use as portas 80 ou 443.")
    consulta = resolver_dns or socket.getaddrinfo
    resultados = consulta(host, porta, type=socket.SOCK_STREAM)
    enderecos = list(dict.fromkeys(endereco_publico(item[4][0]) for item in resultados))
    if host.casefold() in proibidos or any(ip in proibidos for ip in enderecos):
        raise DestinoRecusado("O proxy não conecta na própria HQ.")
    if not enderecos:
        raise DestinoRecusado("O nome não tem endereço público disponível.")
    return enderecos


def conectar(host, porta, *, proibidos=()):
    enderecos = resolver(host, porta, proibidos=proibidos)
    erro = None
    for ip in enderecos:
        familia = socket.AF_INET6 if ":" in ip else socket.AF_INET
        conexao = socket.socket(familia, socket.SOCK_STREAM)
        conexao.settimeout(15)
        try:
            conexao.connect((ip, porta))
            return conexao
        except OSError as exc:
            erro = exc
            conexao.close()
    raise OSError("O destino público não respondeu.") from erro


def _destino(texto, *, tunel=False):
    url = urlsplit("https://" + texto if tunel else texto)
    if url.scheme not in ("http", "https") or url.username or url.password or url.fragment:
        raise DestinoRecusado("O proxy aceita URL HTTP sem credenciais.")
    porta = url.port or (443 if url.scheme == "https" else 80)
    if tunel and (porta != 443 or url.path or url.query):
        raise DestinoRecusado("O túnel aceita somente HTTPS na porta 443.")
    if not tunel and url.scheme != "http":
        raise DestinoRecusado("HTTPS usa um túnel, não uma requisição HTTP em texto.")
    return url, porta


class Proxy(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, endereco, origem, proibidos=()):
        self.origem = origem
        self.proibidos = frozenset(proibidos)
        self.vagas = threading.BoundedSemaphore(16)
        super().__init__(endereco, Pedido)

    def verify_request(self, request, client_address):
        return client_address[0] == self.origem

    def process_request(self, request, client_address):
        if not self.vagas.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.vagas.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.vagas.release()


class Pedido(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, *args):
        pass

    def _permitido(self):
        if self.client_address[0] != self.server.origem:
            self.send_error(403, "Origem fora da caixa.")
            return False
        return True

    def do_CONNECT(self):
        if not self._permitido():
            return
        estabelecido = False
        try:
            url, porta = _destino(self.path, tunel=True)
            remoto = conectar(url.hostname, porta, proibidos=self.server.proibidos)
            with remoto:
                self.send_response(200, "Connection established")
                self.end_headers()
                self.wfile.flush()
                estabelecido = True
                prazo = time.monotonic() + TETO_DO_TUNEL
                while time.monotonic() < prazo:
                    prontas, _, _ = select.select([self.connection, remoto], [], [], 30)
                    if not prontas:
                        return
                    for fonte in prontas:
                        dados = fonte.recv(64 * 1024)
                        if not dados:
                            return
                        (remoto if fonte is self.connection else self.connection).sendall(dados)
        except (OSError, ValueError):
            if not estabelecido:
                self.send_error(403, "Destino recusado ou indisponível.")
            self.close_connection = True

    def _http(self):
        if not self._permitido():
            return
        conexao = None
        enviada = False
        try:
            url, porta = _destino(self.path)
            if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) > 1:
                raise DestinoRecusado("Corpo ambíguo não é aceito pelo proxy.")
            tamanho = int(self.headers.get("Content-Length", "0"))
            if not 0 <= tamanho <= TETO_DO_CORPO:
                raise DestinoRecusado("O corpo passou do teto do proxy.")
            corpo = self.rfile.read(tamanho) if tamanho else None
            if corpo is not None and len(corpo) != tamanho:
                raise DestinoRecusado("O corpo recebido está incompleto.")
            conexao = HTTPConnection(url.hostname, porta, timeout=30)
            conexao.sock = conectar(url.hostname, porta, proibidos=self.server.proibidos)
            hop = _HOP | {c.strip().lower() for c in self.headers.get("Connection", "").split(",")}
            cabecalhos = {k: v for k, v in self.headers.items() if k.lower() not in hop | {"host"}}
            cabecalhos["Host"] = url.netloc
            cabecalhos["Connection"] = "close"
            conexao.request(self.command, (url.path or "/") + ("?" + url.query if url.query else ""), body=corpo, headers=cabecalhos)
            resposta = conexao.getresponse()
            self.send_response(resposta.status)
            for chave, valor in resposta.getheaders():
                if chave.lower() not in _HOP:
                    self.send_header(chave, valor)
            self.end_headers()
            enviada = True
            while parte := resposta.read(64 * 1024):
                self.wfile.write(parte)
        except (OSError, ValueError, HTTPException):
            if not enviada:
                self.send_error(403, "Destino recusado ou indisponível.")
            self.close_connection = True
        finally:
            if conexao is not None:
                conexao.close()

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _http
