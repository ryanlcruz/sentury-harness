"""O arquivo que o Sentury entrega fica na pasta de documentos, e a conversa
guarda só onde ele está."""
import base64
from pathlib import Path

from sentury.artifacts import destino
from sentury.harness.state import AnalysisState


def test_a_pasta_escolhida_vale_e_o_nome_nao_sobrescreve(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTURY_ARTEFATOS_DIR", str(tmp_path / "entregas"))
    pasta = destino.pasta_de_entregas()
    assert pasta == (tmp_path / "entregas").resolve() and pasta.is_dir()
    (pasta / "grafico.png").write_bytes(b"x")
    assert destino.caminho_livre("grafico.png").name == "grafico-2.png"
    assert destino.caminho_livre("../fora.txt").parent == pasta, "nome com caminho não sai da pasta"


def test_linux_usa_a_pasta_declarada_no_xdg(monkeypatch, tmp_path):
    """O nome traduzido (Documentos) está em user-dirs.dirs; sem pasta própria o
    XDG aponta para o home, e isso não conta como Documentos."""
    monkeypatch.delenv("XDG_DOCUMENTS_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    (tmp_path / ".config").mkdir()
    dirs = tmp_path / ".config" / "user-dirs.dirs"
    dirs.write_text('XDG_DOCUMENTS_DIR="$HOME/Documentos"\n', encoding="utf-8")
    assert destino._documentos_do_xdg(tmp_path) == tmp_path / "Documentos"
    dirs.write_text('XDG_DOCUMENTS_DIR="$HOME/"\n', encoding="utf-8")
    assert destino._documentos_do_xdg(tmp_path) is None


def test_a_conversa_guarda_a_referencia_e_le_do_disco(tmp_path):
    arquivo = tmp_path / "relatorio.pdf"
    arquivo.write_bytes(b"%PDF-1.4 teste")
    state = AnalysisState.new("entregas", "u")
    anexo = {"type": "pdf", "filename": "relatorio.pdf", "caminho": str(arquivo),
             "content_base64": base64.b64encode(arquivo.read_bytes()).decode("ascii")}
    meta = state.store_artifact(anexo)
    guardado = state.artifacts[meta["artifact_id"]]["attachment"]
    assert "content_base64" not in guardado, "a sessão não carrega cópia do arquivo"
    lido = state.get_artifact(meta["artifact_id"])
    assert base64.b64decode(lido["content_base64"]) == b"%PDF-1.4 teste"
    arquivo.unlink()
    sumiu = state.get_artifact(meta["artifact_id"])
    assert sumiu["ausente"] is True and sumiu["caminho"] == str(arquivo)
