"""Tela de provedores: o catálogo inteiro à vista e o motor de regras fora dela."""
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1] / "sentury" / "client" / "src" / "features" / "runtime"


def test_motor_de_regras_nao_aparece_como_provedor():
    """O último recurso é interno: não se configura, então não ocupa a tela."""
    tela = (RUNTIME / "ProvidersView.tsx").read_text(encoding="utf-8")
    assert "item.key === 'fallback' || item.ultimo_recurso" in tela
    assert "internos(provider)" in tela


def test_provedor_sem_chave_recebe_a_chave_ali_mesmo():
    """Sem chave, o provedor fica em Adicionar provedor e a chave vai para o mesmo cofre."""
    tela = (RUNTIME / "ProvidersView.tsx").read_text(encoding="utf-8")
    adicionar = (RUNTIME / "AdicionarProvedor.tsx").read_text(encoding="utf-8")
    assert "<AdicionarProvedor" in tela and "mostrarSemCredencial" not in tela
    assert "/sentury/providers/keys" in adicionar and 'type="password"' in adicionar
