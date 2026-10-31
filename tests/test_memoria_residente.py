"""A memória do residente como acervo: tudo guardado, o turno recebe o que cabe."""
import pytest

from sentury.memory import embeddings
from sentury.residentes import escopo, memoria, registro, worker
from sentury.residentes.ferramentas import _memoria

ATLAS = {"nome": "atlas", "papel": "agente de infraestrutura da VPS",
         "objetivo": "manter a VPS de pé", "ferramentas": ["ler_arquivo"]}


@pytest.fixture(autouse=True)
def casa_limpa(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    # Sem modelo de embeddings o teste não depende de rede nem do `.env` de quem roda.
    monkeypatch.setattr(embeddings, "ligado", lambda: False)
    worker.configurar(None)
    registro.criar(ATLAS)
    yield
    worker.configurar(None)


def _encher(n=40):
    for i in range(n):
        registro.anotar_memoria("atlas", f"rotina número {i} da manutenção semanal, sem nada fora do normal " * 2)


def test_memoria_pequena_vai_inteira():
    registro.anotar_memoria("atlas", "o disco enche às sextas")
    registro.anotar_memoria("atlas", "a pessoa prefere relatório curto")
    texto = memoria.para_o_turno("atlas", "qualquer coisa")
    assert "o disco enche às sextas" in texto and "relatório curto" in texto and "buscar" not in texto


def test_memoria_grande_leva_as_recentes_e_a_antiga_parecida_com_o_pedido():
    """Passou do teto do turno: a nota antiga só volta quando o pedido é sobre ela, e o
    resto fica guardado, achável por `buscar`."""
    registro.anotar_memoria("atlas", "certificado TLS do nginx vence em março e renova pelo certbot")
    _encher()
    sobre_tls = memoria.para_o_turno("atlas", "o certificado TLS do nginx vai vencer?")
    outro = memoria.para_o_turno("atlas", "quanto custa o plano da VPS?")
    assert "certbot" in sobre_tls and "certbot" not in outro
    assert "rotina número 39" in outro and "rotina número 0 " not in outro
    assert "`buscar`" in outro and len(outro) < len(registro.ler_memoria("atlas")) / 3
    assert "certbot" in registro.ler_memoria("atlas")
    linhas = sobre_tls.split("\n")
    assert linhas.index(next(l for l in linhas if "certbot" in l)) < linhas.index(
        next(l for l in linhas if "rotina número 39" in l))


def test_nota_que_repete_uma_antiga_troca_a_antiga(monkeypatch):
    registro.anotar_memoria("atlas", "a VPS roda Ubuntu 22.04")
    registro.anotar_memoria("atlas", "o backup roda às 3h")
    monkeypatch.setattr(embeddings, "repetida", lambda novo, acervo: next(
        (n for n, t in acervo.items() if "Ubuntu" in t), None))
    trocada = memoria.anotar("atlas", "a VPS roda Ubuntu 24.04")
    guardado = registro.ler_memoria("atlas")
    assert "22.04" in trocada and "22.04" not in guardado
    assert "24.04" in guardado and "o backup roda às 3h" in guardado


def test_repeticao_so_vale_com_corte_medido(monkeypatch):
    """Sem `repeticao` no cardápio, nota parecida não troca outra: juntar duas distintas apagaria uma."""
    monkeypatch.setattr(embeddings, "ligado", lambda: True)
    monkeypatch.setattr(embeddings, "vetores", lambda textos, guardar=True: [[1.0, 0.0] for _ in textos])
    entrada = {"modelos": {"m": {"corte": 0.5}}}
    monkeypatch.setattr(embeddings, "escolha", lambda: {"provedor": "x", "modelo": "m", "entrada": entrada})
    assert embeddings.repetida("a", {"0": "a"}) is None
    entrada["modelos"]["m"]["repeticao"] = 0.9
    assert embeddings.repetida("a", {"0": "a"}) == "0"


def test_ferramenta_busca_e_le_sem_devolver_o_acervo_inteiro():
    registro.anotar_memoria("atlas", "certificado TLS do nginx renova pelo certbot")
    _encher()
    with escopo.vestido(registro.carregar("atlas")):
        achou = _memoria({"acao": "buscar", "termo": "certificado nginx"})
        lido = _memoria({"acao": "ler"})
        anotado = _memoria({"acao": "anotar", "nota": "porta 22 só por chave"})
        sem_termo = _memoria({"acao": "buscar"})
    assert achou["ok"] and any("certbot" in n for n in achou["notas"])
    assert lido["total"] == 41 and len(lido["notas"]) == memoria.QUANTAS_AO_LER
    assert anotado == {"ok": True, "anotado": "porta 22 só por chave"}
    assert not sem_termo["ok"]


def test_nota_vira_uma_linha():
    registro.anotar_memoria("atlas", "Decisão:\n- item um\n- item dois")
    assert memoria.notas("atlas")[0].endswith("Decisão: - item um - item dois")
