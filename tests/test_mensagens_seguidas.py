"""Duas falas seguidas da pessoa chegam ao modelo nos dois caminhos.

O caminho de texto descartava a primeira; o nativo juntava. Agora os dois
juntam, na ordem, e a conversa que o modelo vê é a mesma.
"""
from sentury.harness.conversa import montar, preparar_legado

HISTORICO = [
    {"role": "user", "content": "lê o pedidos.csv"},
    {"role": "assistant", "content": "São 1.834 pedidos."},
    {"role": "user", "content": "os arquivos desse ERP são sempre em latin-1"},
]


def _falas_da_pessoa(mensagens):
    return "\n".join(str(m["content"]) for m in mensagens if m["role"] == "user")


def test_caminho_de_texto_junta_as_falas_seguidas():
    mensagens = preparar_legado("sistema", HISTORICO, "agora conta os cancelados")
    falas = _falas_da_pessoa(mensagens)
    assert "sempre em latin-1" in falas and "conta os cancelados" in falas
    assert falas.index("latin-1") < falas.index("cancelados")


def test_os_dois_caminhos_veem_as_mesmas_falas():
    texto = _falas_da_pessoa(preparar_legado("sistema", HISTORICO, "agora conta os cancelados"))
    nativo = _falas_da_pessoa(montar("sistema", HISTORICO, "agora conta os cancelados"))
    for fala in ("lê o pedidos.csv", "sempre em latin-1", "conta os cancelados"):
        assert fala in texto and fala in nativo
