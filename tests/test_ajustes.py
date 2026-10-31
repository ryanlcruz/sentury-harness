"""Escolhas da instalação pela tela: embeddings que acham pelo sentido e a voz da ligação."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sentury import ajustes, ajustes_api
from sentury.memory import decisoes, embeddings


@pytest.fixture(autouse=True)
def casa(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    monkeypatch.setenv("GEMINI_API_KEY", "chave-de-teste")
    embeddings._falhou_em.clear()
    return tmp_path


def _sentido(texto: str):
    """Um modelo de mentira que entende que vaga e desligamento são do mesmo assunto."""
    t = texto.lower()
    if "vaga" in t or "deslig" in t:
        return [1.0, 0.0, 0.0]
    if "backup" in t or "cópia" in t:
        return [0.0, 1.0, 0.0]
    return [0.0, 0.0, 1.0]


@pytest.fixture
def modelo_falso(monkeypatch):
    chamadas = []

    def chamar(base_url, chave, modelo, textos, tempo=4.0):
        chamadas.append(list(textos))
        return [_sentido(t) for t in textos]

    monkeypatch.setattr(embeddings, "chamar", chamar)
    return chamadas


def _api():
    app = FastAPI()
    app.include_router(ajustes_api.router)
    return TestClient(app)


def test_escolha_fica_na_casa_e_nao_no_repositorio(casa):
    ajustes.gravar("embeddings", {"provedor": "gemini", "modelo": "gemini-embedding-001"})
    assert (casa / "ajustes.json").exists()
    assert ajustes.ler("embeddings")["provedor"] == "gemini" and ajustes.ler("voz") == {}


def test_sem_escolha_fica_desligado_e_a_decisao_usa_palavras():
    """Quem não escolheu nada não paga chamada nenhuma."""
    assert not embeddings.ligado()
    assert embeddings.semelhantes("vagas", {"a": "desligar"}) is None


def test_decisao_achada_pelo_sentido_que_as_palavras_nao_acham(modelo_falso):
    """'Três vagas' traz de volta 'desligar três pessoas', que não divide palavra com o pedido."""
    decisoes.registrar("mesa:m1", "Corte no suporte", "Decidimos desligar três pessoas do time.", ["nina"],
                       em=1.0)
    decisoes.registrar("mesa:m2", "Backup", "Backup diário às 3h.", ["tito"], em=1.0)
    pedido = "agora temos 3 vagas abertas"
    assert decisoes.para_o_turno(pedido, agora=10_000_000) is None
    ajustes.gravar("embeddings", {"provedor": "gemini", "modelo": "gemini-embedding-001"})
    secao = decisoes.para_o_turno(pedido, agora=10_000_000)
    assert "Corte no suporte" in secao and "Backup" not in secao


def test_vetor_guardado_nao_e_pedido_de_novo(modelo_falso):
    """Só o pedido novo custa chamada: o acervo fica em cache no disco."""
    ajustes.gravar("embeddings", {"provedor": "gemini", "modelo": "gemini-embedding-001"})
    acervo = {"a": "desligar três pessoas", "b": "backup diário"}
    embeddings.semelhantes("vagas abertas", acervo)
    embeddings.semelhantes("outras vagas", acervo)
    assert modelo_falso[2] == ["outras vagas"]


def test_acervo_grande_vai_em_lotes_e_o_lote_que_voltou_fica(monkeypatch):
    """Um acervo inteiro numa chamada passa do tempo dela; em lotes, o que já voltou
    fica no cache mesmo quando um lote seguinte falha."""
    chamadas = []

    def chamar(base_url, chave, modelo, textos, tempo=4.0):
        chamadas.append(len(textos))
        if len(chamadas) == 2:
            raise RuntimeError("lento demais")
        return [_sentido(t) for t in textos]

    monkeypatch.setattr(embeddings, "chamar", chamar)
    ajustes.gravar("embeddings", {"provedor": "gemini", "modelo": "gemini-embedding-001"})
    textos = [f"nota {i}" for i in range(embeddings.LOTE * 2 + 3)]
    assert embeddings.vetores(textos) is None
    assert chamadas == [embeddings.LOTE, embeddings.LOTE]
    embeddings._falhou_em.clear()
    assert embeddings.vetores(textos) is not None
    assert chamadas[2:] == [embeddings.LOTE, 3]


def test_memoria_da_pessoa_traz_a_antiga_que_o_pedido_toca(modelo_falso):
    """As 30 últimas entram como sempre; a antiga volta quando o pedido é sobre ela."""
    from sentury.memory.user_memory import build_memory_context

    memorias = [{"texto": "o backup do servidor roda às 3h"}] + [{"texto": f"fato {i}"} for i in range(40)]
    ajustes.gravar("embeddings", {"provedor": "gemini", "modelo": "gemini-embedding-001"})
    sobre = build_memory_context(memorias, pedido="a cópia de segurança já rodou?")
    outro = build_memory_context(memorias, pedido="qual é o fato?")
    assert "backup do servidor" in sobre and "backup do servidor" not in outro
    assert "fato 39" in sobre and "fato 10\n" in outro + "\n" and "fato 9\n" not in outro + "\n"


def test_provedor_fora_volta_para_as_palavras_e_descansa(monkeypatch):
    """O turno não espera o mesmo erro duas vezes, e a decisão ainda chega pelas palavras."""
    chamadas = []

    def falha(*args, **kwargs):
        chamadas.append(1)
        raise RuntimeError("fora do ar")

    monkeypatch.setattr(embeddings, "chamar", falha)
    ajustes.gravar("embeddings", {"provedor": "gemini", "modelo": "gemini-embedding-001"})
    decisoes.registrar("mesa:m1", "Corte no suporte", "Demitir 3 pessoas do time de suporte.", ["nina"], em=1.0)
    secao = decisoes.para_o_turno("o time de suporte vai abrir vagas", agora=10_000_000)
    assert "Corte no suporte" in secao
    decisoes.para_o_turno("o time de suporte vai abrir vagas", agora=10_000_000)
    assert len(chamadas) == 1


def test_tela_valida_provedor_chave_e_servidor_local(monkeypatch):
    cliente = _api()
    assert cliente.put("/sentury/ajustes/embeddings", json={"provedor": "inventado"}).status_code == 422
    assert cliente.put("/sentury/ajustes/embeddings",
                       json={"provedor": "gemini", "modelo": "outro"}).status_code == 422
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    sem_chave = cliente.put("/sentury/ajustes/embeddings", json={"provedor": "openai", "modelo": "text-embedding-3-small"})
    assert sem_chave.status_code == 422 and "Provedores" in sem_chave.json()["detail"]
    fora = cliente.put("/sentury/ajustes/embeddings",
                       json={"provedor": "local", "modelo": "nomic", "base_url": "http://10.0.0.5:1234/v1"})
    assert fora.status_code == 422
    estado = cliente.put("/sentury/ajustes/embeddings", json={"provedor": "gemini", "modelo": "gemini-embedding-001"}).json()
    assert estado["ligado"] and estado["escolha"]["provedor"] == "gemini"
    gemini = next(p for p in estado["provedores"] if p["nome"] == "gemini")
    assert gemini["tem_chave"] and "chave-de-teste" not in str(estado)


def test_testar_mostra_se_o_modelo_separa_sem_gravar(modelo_falso):
    resultado = _api().post("/sentury/ajustes/embeddings/testar",
                            json={"provedor": "gemini", "modelo": "gemini-embedding-001"}).json()
    assert resultado["ok"] and resultado["separa"] and resultado["relacionado"] > resultado["sem_relacao"]
    assert ajustes.ler("embeddings") == {}


def test_voz_escolhida_na_tela_vale_para_a_ligacao(monkeypatch):
    async def sem_rede(chave):
        return ["gemini-live-de-teste"]

    monkeypatch.setattr(ajustes_api, "_modelos_ao_vivo", sem_rede)
    cliente = _api()
    assert cliente.put("/sentury/ajustes/voz", json={"provedor": "gemini_live", "voz": "Ninguem"}).status_code == 422
    estado = cliente.put("/sentury/ajustes/voz",
                         json={"provedor": "gemini_live", "modelo": "gemini-live-de-teste", "voz": "Kore"}).json()
    assert estado["escolha"] == {"provedor": "gemini_live", "modelo": "gemini-live-de-teste", "voz": "Kore"}
    assert "gemini-live-de-teste" in estado["provedores"][0]["modelos"]
    assert ajustes_api.escolha_de_voz()["voz"] == "Kore"


def test_chrome_do_agente_escolhido_na_tela_vence_o_env(monkeypatch):
    """A escolha da tela vale; o `.env` só é lido enquanto ela não existe."""
    from sentury.config import settings
    from sentury.tools import perfil_do_agente as perfil

    monkeypatch.setattr(settings, "SENTURY_NAVEGADOR_PERFIL", "agente")
    monkeypatch.setattr(settings, "SENTURY_NAVEGADOR_AGENTE_NOME", "Velho")
    assert perfil.perfil_escolhido() == "agente" and perfil.nome_do_perfil() == "Velho"
    assert _api().get("/sentury/ajustes/navegador").json()["origem"] == "env"
    estado = _api().put("/sentury/ajustes/navegador", json={"perfil": "pessoa"}).json()
    assert estado["escolha"]["perfil"] == "pessoa" and estado["origem"] == "tela"
    assert "Chrome dela" in perfil.navegador_escolhido()
    criados = []
    monkeypatch.setattr(perfil, "criar_atalho", lambda nome: criados.append(nome) or f"atalho-{nome}")
    monkeypatch.setattr(ajustes_api.sys, "platform", "win32")
    estado = _api().put("/sentury/ajustes/navegador", json={"perfil": "agente", "nome": "Coruja"}).json()
    assert criados == ["Coruja"] and perfil.nome_do_perfil() == "Coruja" and estado["atalho"] == "atalho-Coruja"
    assert _api().put("/sentury/ajustes/navegador", json={"perfil": "outro"}).status_code == 422
