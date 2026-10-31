from types import SimpleNamespace

import pytest

from sentury.residentes import manifesto, proxy_da_caixa as proxy, rede_da_caixa as rede, caixa


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "172.18.0.2", "192.168.1.1", "169.254.169.254", "0.0.0.0", "::1", "fe80::1", "fc00::1", "::ffff:8.8.8.8", "64:ff9b::808:808", "2002:0808:0808::1", "224.0.0.1"])
def test_proxy_recusa_endereco_interno_e_transicao(ip):
    with pytest.raises(ValueError):
        proxy.endereco_publico(ip)


def _respostas(*ips):
    return [(2, 1, 6, "", (ip, 443)) for ip in ips]


def test_resolucao_mista_nao_escolhe_so_o_publico():
    with pytest.raises(proxy.DestinoRecusado):
        proxy.resolver("pagina.test", 443, resolver_dns=lambda *a, **k: _respostas("8.8.8.8", "127.0.0.1"))


def test_conexao_usa_ip_checado_sem_segundo_dns(monkeypatch):
    consultas = []
    destinos = []
    def dns(*args, **kwargs):
        consultas.append(args)
        return _respostas("8.8.8.8") if len(consultas) == 1 else _respostas("127.0.0.1")
    conexao = SimpleNamespace(settimeout=lambda _: None, connect=destinos.append)
    monkeypatch.setattr(proxy.socket, "getaddrinfo", dns)
    monkeypatch.setattr(proxy.socket, "socket", lambda *a: conexao)
    assert proxy.conectar("pagina.test", 443) is conexao
    assert destinos == [("8.8.8.8", 443)]
    assert len(consultas) == 1


def test_nova_requisicao_recheca_dns(monkeypatch):
    consultas = []
    def dns(*args, **kwargs):
        consultas.append(args)
        return _respostas("8.8.8.8") if len(consultas) == 1 else _respostas("169.254.169.254")
    monkeypatch.setattr(proxy.socket, "getaddrinfo", dns)
    assert proxy.resolver("pagina.test", 443) == ["8.8.8.8"]
    with pytest.raises(proxy.DestinoRecusado):
        proxy.resolver("pagina.test", 443)


def test_hq_publica_e_alias_sao_recusados():
    dns = lambda *a, **k: _respostas("8.8.8.8")
    with pytest.raises(proxy.DestinoRecusado, match="HQ"):
        proxy.resolver("hq.test", 443, resolver_dns=dns, proibidos={"hq.test"})
    with pytest.raises(proxy.DestinoRecusado, match="HQ"):
        proxy.resolver("alias.test", 443, resolver_dns=dns, proibidos={"8.8.8.8"})


def test_hq_publica_configurada_entra_na_recusa(monkeypatch):
    monkeypatch.setenv("SENTURY_HQ_PUBLIC_URL", "https://hq.test")
    monkeypatch.setattr(rede.socket, "getaddrinfo", lambda *a, **k: _respostas("8.8.8.8"))
    assert {"hq.test", "8.8.8.8"} <= rede._enderecos_da_hq()


@pytest.mark.parametrize("url", ["https://x:8000", "x:8000", "127.0.0.1:9222/cdp", "usuario:senha@site.test:443"])
def test_tunel_nao_aceita_porta_livre_nem_credencial(url):
    with pytest.raises(ValueError):
        proxy._destino(url, tunel=True)


def test_manifesto_padrao_e_edicao(tmp_path, monkeypatch):
    from sentury.residentes import registro

    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    dados = {"nome": "atlas", "papel": "infra", "objetivo": "ver", "ferramentas": ["ler_arquivo"]}
    assert registro.criar(dados).rede == "nenhuma"
    assert registro.editar("atlas", {"rede": "internet"}).rede == "internet"
    assert registro.carregar("atlas").rede == "internet"
    with pytest.raises(manifesto.ManifestoInvalido):
        registro.editar("atlas", {"rede": "host"})


def test_rede_apenas_da_caixa_e_hq():
    agente = manifesto.Manifesto("atlas", "infra", "ver", rede="internet")
    cmd = rede.comando_criar(agente)
    assert "--internal" in cmd and f"{rede.MODO}=isolated" in cmd
    dados = {"Driver": "bridge", "Internal": True, "EnableIPv6": False,
             "Options": {rede.MODO: "isolated"}, "Labels": {"sentury.servico": "rede", "sentury.residente": "atlas"},
             "Containers": {"hq": {}, "caixa": {}}}
    assert rede.segura(dados, agente, "hq", "caixa")
    dados["Containers"]["outro"] = {}
    assert not rede.segura(dados, agente, "hq", "caixa")
    dados["Containers"].pop("outro")
    dados["Options"][rede.MODO] = "nat"
    assert not rede.segura(dados, agente, "hq", "caixa")


def test_comando_nao_aceita_rede_arbitraria():
    agente = manifesto.Manifesto("atlas", "infra", "ver", rede="internet")
    with pytest.raises(ValueError):
        caixa.comando_criar(agente, "imagem", rede="bridge")
    cmd = caixa.comando_criar(agente, "imagem", rede=rede.nome_da_rede(agente), proxy="http://172.19.0.2:3128")
    assert cmd[cmd.index("--network") + 1] == rede.nome_da_rede(agente)
    assert "--read-only" in cmd and "--cap-drop" in cmd and "--user" in cmd
    assert "docker.sock" not in " ".join(cmd)


def test_sem_rede_recusa_conexao_acrescentada():
    agente = manifesto.Manifesto("atlas", "infra", "ver")
    dados = {"NetworkSettings": {"Networks": {"bridge": {"IPAddress": "172.18.0.2"}}}}
    assert not caixa._rede_segura(dados, agente, "none", "")


def test_proxy_http_recusa_loopback_antes_de_conectar():
    from contextlib import closing
    from http.client import HTTPConnection
    import threading

    servidor = proxy.Proxy(("127.0.0.1", 0), "127.0.0.1")
    tarefa = threading.Thread(target=servidor.serve_forever, daemon=True)
    tarefa.start()
    try:
        with closing(HTTPConnection("127.0.0.1", servidor.server_port, timeout=3)) as conexao:
            conexao.request("GET", "http://127.0.0.1/")
            assert conexao.getresponse().status == 403
    finally:
        servidor.shutdown()
        servidor.server_close()
        tarefa.join(3)
