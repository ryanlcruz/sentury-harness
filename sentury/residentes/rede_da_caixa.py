"""A rede privada expõe apenas o proxy, sem endereço de ponte no host."""
import ipaddress
import json
import os
import re
import socket
import threading
from urllib.parse import urlsplit

from .proxy_da_caixa import Proxy

PORTA = 3128
MODO = "com.docker.network.bridge.gateway_mode_ipv4"
_SERVIDORES = {}
_LOCK = threading.RLock()


def nome_da_rede(agente):
    from .caixa import nomes

    return nomes(agente)[0].replace("sentury-caixa-", "sentury-rede-", 1)


def comando_criar(agente):
    return ["docker", "network", "create", "--driver", "bridge", "--internal", "--opt", f"{MODO}=isolated",
            "--label", "sentury.servico=rede", "--label", f"sentury.residente={agente.nome}", nome_da_rede(agente)]


def segura(dados, agente, hq_id, caixa_id=""):
    permitidos = {hq_id, caixa_id} - {""}
    return (dados.get("Driver") == "bridge" and dados.get("Internal") is True
            and not dados.get("EnableIPv6") and dados.get("Options") == {MODO: "isolated"}
            and dados.get("Labels", {}).get("sentury.servico") == "rede"
            and dados.get("Labels", {}).get("sentury.residente") == agente.nome
            and set(dados.get("Containers") or {}) <= permitidos)


def _inspecionar(argv):
    from .caixa import _docker

    resultado = _docker(argv)
    if resultado.returncode:
        raise RuntimeError("Não consegui inspecionar a rede da caixa.")
    return json.loads(resultado.stdout)[0]


def _hq():
    identidade = os.environ.get("HOSTNAME", "")
    if not re.fullmatch(r"[a-f0-9]{12,64}", identidade):
        raise RuntimeError("A rede de internet precisa da HQ em container; a caixa continua sem rede.")
    dados = _inspecionar(["docker", "inspect", identidade])
    if dados.get("Config", {}).get("Labels", {}).get("sentury.servico") != "hq":
        raise RuntimeError("O container indicado não é a HQ.")
    escuta = os.environ.get("SENTURY_HQ_LISTEN_ADDRESS", "")
    if not escuta or ipaddress.ip_address(escuta).is_unspecified:
        raise RuntimeError("A API da HQ precisa escutar só na rede de entrada, não na rede das caixas.")
    redes = dados.get("NetworkSettings", {}).get("Networks", {})
    if not any(n.get("IPAddress") == escuta and not nome.startswith("sentury-rede-") for nome, n in redes.items()):
        raise RuntimeError("O endereço de escuta da HQ não pertence à rede de entrada.")
    if dados.get("HostConfig", {}).get("Sysctls", {}).get("net.ipv4.ip_forward") != "0":
        raise RuntimeError("Desative o encaminhamento de IP na HQ antes de liberar internet à caixa.")
    return dados


def garantir(agente):
    from .caixa import _docker, nomes

    with _LOCK:
        hq = _hq()
        nome = nome_da_rede(agente)
        caixa = _docker(["docker", "inspect", nomes(agente)[0]])
        caixa_id = json.loads(caixa.stdout)[0].get("Id", "") if not caixa.returncode else ""
        visto = _docker(["docker", "network", "inspect", nome])
        if visto.returncode:
            criado = _docker(comando_criar(agente))
            if criado.returncode:
                raise RuntimeError("Não consegui criar a rede isolada; confira se o Docker aceita o modo isolated.")
        dados = _inspecionar(["docker", "network", "inspect", nome])
        if not segura(dados, agente, hq["Id"], caixa_id):
            raise RuntimeError("A rede da caixa não satisfaz o isolamento; ela não será usada.")
        if hq["Id"] not in dados.get("Containers", {}):
            resultado = _docker(["docker", "network", "connect", nome, hq["Id"]])
            if resultado.returncode:
                raise RuntimeError("Não consegui conectar o proxy da HQ à rede privada.")
        hq = _inspecionar(["docker", "inspect", hq["Id"]])
        ip = hq["NetworkSettings"]["Networks"][nome]["IPAddress"]
        if not ipaddress.ip_address(ip).is_private:
            raise RuntimeError("O proxy precisa de um endereço privado na rede própria.")
        if ip == os.environ["SENTURY_HQ_LISTEN_ADDRESS"]:
            raise RuntimeError("A rede da caixa não pode ser a rede de entrada da HQ.")
        return nome, ip


def iniciar_proxy(agente):
    from .caixa import nomes

    with _LOCK:
        rede, ip_hq = garantir(agente)
        caixa = _inspecionar(["docker", "inspect", nomes(agente)[0]])
        conexoes = caixa.get("NetworkSettings", {}).get("Networks", {})
        if set(conexoes) != {rede}:
            raise RuntimeError("A caixa está conectada a outra rede; o proxy não será liberado.")
        origem = conexoes[rede]["IPAddress"]
        proibidos = _enderecos_da_hq()
        chave = (rede, ip_hq, origem, proibidos)
        anterior = _SERVIDORES.get(rede)
        if anterior and anterior[0] == chave:
            return
        if anterior:
            anterior[1].shutdown()
            anterior[1].server_close()
        servidor = Proxy((ip_hq, PORTA), origem, proibidos)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        _SERVIDORES[rede] = chave, servidor


def _enderecos_da_hq():
    nomes = {socket.gethostname()}
    for variavel in ("SENTURY_HQ_URL", "SENTURY_HQ_PUBLIC_URL"):
        if valor := os.environ.get(variavel):
            host = urlsplit(valor).hostname
            if not host:
                raise RuntimeError("O endereço da HQ precisa de uma URL válida antes de abrir o proxy.")
            nomes.add(host)
    proibidos = {n.casefold() for n in nomes}
    for nome in nomes:
        try:
            proibidos.update(str(ipaddress.ip_address(r[4][0])) for r in socket.getaddrinfo(nome, None, type=socket.SOCK_STREAM))
        except OSError as exc:
            raise RuntimeError("Não consegui resolver o endereço da HQ; o proxy não será aberto.") from exc
    return frozenset(proibidos)


def encerrar_proxies():
    with _LOCK:
        for _, servidor in _SERVIDORES.values():
            servidor.shutdown()
            servidor.server_close()
        _SERVIDORES.clear()
