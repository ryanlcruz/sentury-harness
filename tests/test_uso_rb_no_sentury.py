"""O turno real alimenta os mesmos arquivos consumidos pelo painel do RB."""
import pytest

from robinbandit.routing.sentury import ChainProvider, use_ultra_provider, clear_ultra_provider
from robinbandit.providers import ReinforcedProvider
from robinbandit.state import uso
from robinbandit.state.atividade import Atividade


class Modelo:
    name = "chatgpt_codex"
    models = ["modelo-teste"]
    last_model = "chatgpt_codex:modelo-teste"
    last_usage = None

    async def complete(self, messages, temperature=0.2, **kwargs):
        return "resposta"


@pytest.mark.asyncio
@pytest.mark.parametrize("dedicado", [False, True])
async def test_chamada_sem_tokens_aparece_no_uso_e_na_atividade(dedicado):
    atividade = Atividade(persistir=True)
    modelo = Modelo()
    cadeia = ChainProvider([modelo], activity=atividade)
    token = use_ultra_provider(ReinforcedProvider([modelo], name="ultra_max")) if dedicado else None
    try:
        assert await cadeia.complete([{"role": "user", "content": "texto fictício"}]) == "resposta"
    finally:
        if token is not None:
            clear_ultra_provider(token)
    assert uso.total(1)["chamadas"] == 1
    assert uso.total(1)["chamadas_sem_uso"] == 1
    assert uso.por_provedor(1)[0]["provedor"] == "chatgpt_codex"
    assert Atividade(persistir=True).resumo()[0]["provedor"] == "chatgpt_codex"


@pytest.mark.asyncio
async def test_aviso_local_nao_e_contado_como_chamada_de_modelo():
    from robinbandit.providers.groq_provider import FallbackProvider
    cadeia = ChainProvider([FallbackProvider()])
    await cadeia.complete([{"role": "user", "content": "texto fictício"}])
    assert uso.total(1)["chamadas"] == 0
