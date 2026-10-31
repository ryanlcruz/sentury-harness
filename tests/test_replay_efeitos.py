"""O replay repete o turno sem escrever nas dependências, e diz o que foi barrado."""
import pytest

from sentury.mutation import replay
from sentury.mutation.efeitos import ESCRITAS, SomenteLeitura, somente_leitura


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_TRACOS_DIR", str(tmp_path / "tracos"))
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    from sentury.config import settings

    monkeypatch.setattr(settings, "SENTURY_GRAVAR_TRACOS", True, raising=False)


class _Memoria:
    def __init__(self):
        self.fatos = ["gosta de tabela"]
        self.lembrados = []

    async def all(self, user_id):
        return list(self.fatos)

    async def remember(self, user_id, texto, sessao=None):
        self.lembrados.append(texto)
        return True

    def forget(self, user_id, texto):
        self.fatos.remove(texto)
        return True


class TestSomenteLeitura:
    async def test_escrita_e_recusada_anotada_e_devolve_o_neutro(self):
        memoria, anotadas = _Memoria(), []
        protegida = SomenteLeitura(memoria, "memory", anotadas.append)

        assert await protegida.remember("u", "mora em Recife") is False
        assert memoria.lembrados == []
        assert anotadas == [{"dependencia": "memory", "metodo": "remember"}]

    async def test_leitura_passa_igual(self):
        protegida = SomenteLeitura(_Memoria(), "memory", lambda _e: None)
        assert await protegida.all("u") == ["gosta de tabela"]

    def test_escrita_sincrona_tambem_e_recusada(self):
        memoria, anotadas = _Memoria(), []
        assert SomenteLeitura(memoria, "memory", anotadas.append).forget("u", "gosta de tabela") is False
        assert memoria.fatos == ["gosta de tabela"]
        assert anotadas[0]["metodo"] == "forget"

    def test_dependencia_ausente_continua_ausente(self):
        deps, _ = somente_leitura(memory=None, skills=_Memoria())
        assert deps["memory"] is None and isinstance(deps["skills"], SomenteLeitura)

    def test_toda_escrita_declarada_tem_dono_conhecido(self):
        assert set(ESCRITAS) == {"memory", "experience_library", "skills", "store"}


class _OrquestradorQueLembra:
    """Um turno que, como o de verdade, guarda um fato na memória ao responder."""

    def __init__(self, memoria):
        self.memory = memoria

    async def handle_message(self, state, mensagem):
        await self.memory.remember(state.user_id, "prefere resumo curto")
        return {"message": "feito", "harness": {"ferramentas": []}}


class TestNaBateria:
    async def test_bateria_repete_sem_escrever_e_lista_o_que_barrou(self):
        replay.gravar(mensagem="resume", respostas_llm=[], conjunto="desenvolvimento", determinista=True,
                      resultado_observado={"mensagem": "feito", "ferramentas": [], "anexo": ""},
                      ambiente={"despacho": "texto"})
        memoria = _Memoria()

        def construir(_planner, _responder):
            deps, recusadas = somente_leitura(memory=memoria)
            orquestrador = _OrquestradorQueLembra(deps["memory"])
            orquestrador.efeitos_recusados = recusadas
            return orquestrador

        resultado = await replay.bateria(construir)

        assert resultado["fiel"] is True and resultado["iguais"] == 1
        assert memoria.lembrados == []
        assert resultado["efeitos_recusados"][0]["efeitos"] == [{"dependencia": "memory", "metodo": "remember"}]

    async def test_sem_escrita_a_lista_fica_vazia(self):
        replay.gravar(mensagem="oi", respostas_llm=[], conjunto="desenvolvimento", determinista=True,
                      resultado_observado={"mensagem": "ola", "ferramentas": [], "anexo": ""},
                      ambiente={"despacho": "texto"})

        class _SoResponde:
            async def handle_message(self, state, mensagem):
                return {"message": "ola", "harness": {"ferramentas": []}}

        resultado = await replay.bateria(lambda _p, _r: _SoResponde())
        assert resultado["fiel"] is True and resultado["efeitos_recusados"] == []
