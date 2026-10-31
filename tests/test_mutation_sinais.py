"""A entrada do Mutation começa do que o Sentury notou, não de um formulário.

Os sinais saem do uso real e ignoram o que é fluxo normal; uma frase ou um sinal
vira alvo e hipótese pelo modelo, e sem modelo o rascunho sai da própria frase.
"""
import json
import time
from types import SimpleNamespace

from sentury.mutation import rascunho, sinais


def _traco(tid, pedido, resultados, idade_dias=1):
    return SimpleNamespace(id=tid, mensagem=pedido, gravado_em=time.time() - idade_dias * 86400,
                           resultados_ferramentas=[{"tool": t, "resultado": r} for t, r in resultados])


def test_sinais_agrupam_o_uso_real_e_ignoram_o_fluxo_normal(monkeypatch):
    tracos = {
        "desenvolvimento": [
            _traco("T-1", "crie o nexo", [("pedir_ao_agente", {"ok": False, "erro": "não existe agente 'criar_agente'"})]),
            _traco("T-2", "de novo", [("pedir_ao_agente", {"ok": False, "erro": "não existe agente 'x'"})]),
            _traco("T-3", "crie", [("criar_agente", {"precisa_permissao": True, "codigo_erro": "EXEC_PRECISA_PERMISSAO"})]),
            _traco("T-4", "antigo", [("ler_arquivo", {"erro": "sumiu"})], idade_dias=90),
            _traco("T-5", "deu certo", [("ler_arquivo", {"ok": True, "conteudo": "x"})]),
        ],
        "avaliacao": [_traco("T-9", "plantado", [("ler_arquivo", {"erro": "inexistente de propósito"})])],
    }
    monkeypatch.setattr(sinais.replay, "listar", lambda conjunto: tracos.get(conjunto, []))
    achados = sinais.listar()
    assert [(s["ferramenta"], s["vezes"]) for s in achados] == [("pedir_ao_agente", 2)]
    assert achados[0]["pedido"] == "de novo" and achados[0]["tracos"] == ["T-1", "T-2"]
    assert sinais.por_id(achados[0]["id"])["ferramenta"] == "pedir_ao_agente"


class Modelo:
    def __init__(self, resposta):
        self.resposta = resposta
        self.mensagens = None

    async def complete(self, mensagens, **_k):
        self.mensagens = mensagens
        if isinstance(self.resposta, Exception):
            raise self.resposta
        return self.resposta


async def test_o_modelo_redige_alvo_e_hipotese_a_partir_da_frase_e_do_sinal():
    modelo = Modelo('```json\n' + json.dumps({"alvo": "orientação do criar_agente",
                                               "hipotese": "O modelo chama criar_agente em vez de pedir_ao_agente.",
                                               "observacao": "pedir_ao_agente falhou 2 vezes"}) + '\n```')
    sinal = {"ferramenta": "pedir_ao_agente", "vezes": 2, "tipo": "erro", "pedido": "crie", "erro": "não existe"}
    saida = await rascunho.redigir("ele confunde criar com pedir", sinal, modelo)
    assert saida["pelo_modelo"] and saida["alvo"] == "orientação do criar_agente"
    assert "pedir_ao_agente" in modelo.mensagens[1]["content"]


async def test_sem_modelo_o_rascunho_sai_da_frase_e_a_tela_nao_trava():
    saida = await rascunho.redigir("responder mais curto quando a pergunta é simples", {}, Modelo(RuntimeError("fora")))
    assert saida["pelo_modelo"] is False
    assert saida["hipotese"] == "responder mais curto quando a pergunta é simples" and saida["alvo"]
    sem = await rascunho.redigir("", {"ferramenta": "executar_comando", "vezes": 3, "erro": "timeout"}, None)
    assert "executar_comando" in sem["alvo"] and "timeout" in sem["observacao"]


def test_o_rascunho_usa_o_modo_escolhido_na_tela(monkeypatch):
    """Fora do chat o pedido cairia no roteamento automático; com o modo da tela,
    o rascunho sai do mesmo modelo que a pessoa escolheu para conversar."""
    import robinbandit.sentury as rb
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import sentury.main as principal
    from sentury.mutation import api

    usados = []
    monkeypatch.setattr(principal, "_tier_provider_for", lambda modo: f"nivel-{modo}" if modo == "ultra_max" else None)
    monkeypatch.setattr(rb, "use_ultra_provider", lambda nivel: usados.append(nivel) or "marca")
    monkeypatch.setattr(rb, "clear_ultra_provider", lambda marca: usados.append(f"solto-{marca}"))

    async def redigir(texto, sinal, modelo):
        return {"alvo": "a", "hipotese": texto, "observacao": "", "pelo_modelo": True}

    monkeypatch.setattr(rascunho, "redigir", redigir)
    app = FastAPI()
    app.include_router(api.router)
    resposta = TestClient(app).post("/sentury/mutacoes/rascunho", json={"texto": "mais curto", "modo": "ultra_max"})
    assert resposta.status_code == 200 and usados == ["nivel-ultra_max", "solto-marca"]
