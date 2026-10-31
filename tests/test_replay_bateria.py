"""A bancada não usa a casa original nem inicializa embeddings externos."""
import os

from scripts import replay_bateria


def test_casa_descartavel_preserva_a_original_e_desliga_embeddings(tmp_path, monkeypatch):
    original = tmp_path / "original"
    original.mkdir()
    (original / "marcador.txt").write_text("preservado", encoding="utf-8")
    (original / "tracos").mkdir()
    base = tmp_path / "bancada"
    base.mkdir()
    monkeypatch.setenv("SENTURY_HOME", str(original))
    monkeypatch.delenv("SENTURY_TRACOS_DIR", raising=False)
    monkeypatch.setenv("SENTURY_GEMINI_EMBEDDINGS", "true")
    monkeypatch.setenv("SENTURY_EMBEDDINGS", "true")
    monkeypatch.setattr(replay_bateria.tempfile, "mkdtemp", lambda **_: str(base))

    assert replay_bateria._casa_descartavel() == base
    assert os.environ["SENTURY_HOME"] == str(base / "casa")
    assert os.environ["SENTURY_TRACOS_DIR"] == str(original / "tracos")
    assert os.environ["SENTURY_GEMINI_EMBEDDINGS"] == "false"
    assert os.environ["SENTURY_EMBEDDINGS"] == "false"
    assert (base / "casa" / "marcador.txt").read_text(encoding="utf-8") == "preservado"
    assert not (base / "casa" / "tracos").exists()
    (base / "casa" / "marcador.txt").write_text("só na cópia", encoding="utf-8")
    assert (original / "marcador.txt").read_text(encoding="utf-8") == "preservado"
