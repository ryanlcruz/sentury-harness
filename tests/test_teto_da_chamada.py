"""Nenhum provedor pode demorar mais que o turno inteiro.

O orçamento de um turno é de **120s** (`LoopBudget.max_elapsed_ms`). O Claude Code
esperava **300s** e o Codex **180s**: os dois maiores que o turno que estão
servindo. Um provedor que desiste depois de o turno já estar morto não protege
ninguém: garante queimar o orçamento inteiro e devolver *"Desculpe, tive um
problema"* quando já não há mais nada a fazer.

Medido: uma rodada no Dedicado levou **300,3s**, com `responder_ms: 300108`. A
mesma chamada, isolada, leva **14,6s**. Os 300s foram esperar o próprio timeout.

E toda chamada que passa de 60s ganha aviso no log. Sem isso, uma chamada lenta é
indistinguível de uma travada até o timeout estourar, e a diferença importa: uma
pede paciência, a outra pede investigação.
"""
from robinbandit.providers import claude_code_provider as cc
from robinbandit.providers import codex_provider as cx
from sentury.config import settings
from sentury.harness.loop_budget import LoopBudget


def test_o_teto_cabe_no_orcamento_do_turno():
    """A relação que importa: a chamada tem que terminar dentro do turno."""
    orcamento_s = LoopBudget.from_settings(settings).max_elapsed_ms / 1000
    assert cc._TETO_DA_CHAMADA_S < orcamento_s, (cc._TETO_DA_CHAMADA_S, orcamento_s)
    assert cx._TETO_DA_CHAMADA_S < orcamento_s, (cx._TETO_DA_CHAMADA_S, orcamento_s)


def test_claude_nasce_dentro_do_teto():
    assert cc.ClaudeCodeProvider(models=["x"]).timeout <= cc._TETO_DA_CHAMADA_S


def test_codex_nasce_dentro_do_teto():
    assert cx.CodexProvider(models=["x"]).timeout <= cx._TETO_DA_CHAMADA_S


def test_pedido_maior_que_o_teto_e_cortado():
    """Era o caso real: o provedor nascia com 300s e ninguém percebia."""
    assert cc.ClaudeCodeProvider(models=["x"], timeout=300.0).timeout <= cc._TETO_DA_CHAMADA_S
    assert cx.CodexProvider(models=["x"], timeout=600.0).timeout <= cx._TETO_DA_CHAMADA_S


def test_pedido_menor_continua_valendo():
    """O teto é limite, não imposição: quem quer menos, recebe menos."""
    assert cc.ClaudeCodeProvider(models=["x"], timeout=30.0).timeout == 30.0
    assert cx.CodexProvider(models=["x"], timeout=30.0).timeout == 30.0


def test_o_aviso_vem_antes_do_teto():
    """Avisar só no timeout não avisa nada: o turno já acabou."""
    assert cc._AVISO_DE_LENTIDAO_S < cc._TETO_DA_CHAMADA_S
    assert cx._AVISO_DE_LENTIDAO_S < cx._TETO_DA_CHAMADA_S
