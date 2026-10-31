"""Assinatura gruda no modelo que responde, e o Claude Code enfim é alcançável.

## O que estava quebrado

`ClaudeCodeProvider` **nunca funcionou como tier**. Ele expõe `generate()`, e
`ReinforcedProvider.complete` faz `inspect.signature(provider.complete)`: o
`AttributeError` era engolido pelo `except Exception` do laço e o tier inteiro
reportava *"nenhuma conta do Reforçado respondeu"*. Chamado direto, o provedor
responde normalmente e ainda reporta uso (entrada, saída, cacheado, `custo_usd`),
que o Codex nem faz. Estava pronto e inalcançável.

## A escolha sobre queda de modelo

A lista de modelos era tentada **sempre na mesma ordem**. Então um modelo morto
custava uma tentativa (e um `app-server` inteiro) em toda chamada seguinte,
antes de chegar no que responde. Medido numa rodada real: `gpt-5.6-sol` deu *"at
capacity"*, e cada uma das quatro chamadas do turno pagou esse tropeço de novo.

A decisão foi grudar no que funcionou e só soltar quando ele cair. Não é
"escolher um e nunca mudar": é não reaprender o mesmo fracasso a cada chamada.
"""
import pytest

from robinbandit.providers.codex_provider import CodexProvider


class _ClienteFalso:
    """Responde por um modelo só; os outros levantam."""

    def __init__(self, *, binary=None, timeout=None, vivo="b", registro=None):
        self.vivo = vivo
        self.registro = registro

    async def complete(self, messages, *, model, reasoning_effort=None):
        if self.registro is not None:
            self.registro.append(model)
        if model != self.vivo:
            raise RuntimeError(f"{model} at capacity")
        return "ok", None


def _provedor(registro, vivo="b"):
    return CodexProvider(
        models=["a", "b", "c"],
        client_factory=lambda **kw: _ClienteFalso(vivo=vivo, registro=registro),
    )


@pytest.fixture(autouse=True)
def _autenticado(monkeypatch):
    from robinbandit.providers import codex_provider as cp

    monkeypatch.setattr(
        cp, "codex_auth_status",
        lambda *a, **k: cp.CodexAuthStatus(True, "codex_cli", "autenticado"),
    )
    # O grude vive no MODULO de propósito (ver a docstring de `_GRUDADO`), então
    # ele atravessa testes. Sem limpar, o segundo teste herda o que o primeiro
    # aprendeu e falha por um motivo que não existe.
    cp._GRUDADO.clear()
    yield
    cp._GRUDADO.clear()


@pytest.mark.asyncio
async def test_a_primeira_chamada_percorre_a_lista():
    registro = []
    p = _provedor(registro)
    assert await p.complete([{"role": "user", "content": "oi"}]) == "ok"
    assert registro == ["a", "b"], registro


@pytest.mark.asyncio
async def test_a_segunda_chamada_nao_repete_o_que_ja_caiu():
    """O desperdício que isto fecha: `a` custava uma tentativa e um processo
    em toda chamada, para sempre."""
    registro = []
    p = _provedor(registro)
    await p.complete([{"role": "user", "content": "oi"}])
    registro.clear()
    await p.complete([{"role": "user", "content": "de novo"}])
    assert registro == ["b"], registro


@pytest.mark.asyncio
async def test_quando_o_grudado_cai_a_lista_volta_a_valer():
    """Grudar não pode virar teimosia: o modelo que morre é solto."""
    registro = []
    p = CodexProvider(
        models=["a", "b", "c"],
        client_factory=lambda **kw: _ClienteFalso(vivo=kw.get("_vivo", "b"), registro=registro),
    )
    await p.complete([{"role": "user", "content": "oi"}])
    assert p._modelo_grudado == "b"

    # `b` morre; `c` passa a ser o único vivo.
    p._client_factory = lambda **kw: _ClienteFalso(vivo="c", registro=registro)
    registro.clear()
    assert await p.complete([{"role": "user", "content": "e agora"}]) == "ok"
    assert registro[0] == "b", "não tentou o grudado primeiro"
    assert p._modelo_grudado == "c", "não grudou no novo"


@pytest.mark.asyncio
async def test_preferencia_explicita_vence_o_grudado():
    registro = []
    p = _provedor(registro, vivo="c")
    await p.complete([{"role": "user", "content": "oi"}])
    registro.clear()
    await p.complete([{"role": "user", "content": "oi"}], preferred_model="c")
    assert registro[0] == "c", registro


# ------------------------------------------- o Claude Code fala a língua da cadeia

def test_claude_code_tem_o_metodo_que_a_cadeia_chama():
    """Sem `complete`, `ReinforcedProvider` levantava AttributeError e o tier
    inteiro dizia "nenhuma conta respondeu": com o provedor pronto do lado."""
    from robinbandit.providers.claude_code_provider import ClaudeCodeProvider

    assert callable(getattr(ClaudeCodeProvider, "complete", None))


def test_claude_code_expoe_o_que_a_cadeia_le_depois():
    from robinbandit.providers.claude_code_provider import ClaudeCodeProvider

    p = ClaudeCodeProvider(models=["claude-haiku-4-5"])
    for atributo in ("last_model", "last_attempted_model", "last_usage",
                     "last_quota", "last_tool_calls", "model_failures"):
        assert hasattr(p, atributo), atributo
