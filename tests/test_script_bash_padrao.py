"""Com bash detectado, o script roda em bash; sem ele, em PowerShell."""
from pathlib import Path

from sentury.tools import script


def test_bash_quando_existe(monkeypatch):
    monkeypatch.setattr(script, "_interpretador", lambda nome: "/bin/bash" if nome == "bash" else "/x/pwsh")
    assert script.linguagem_padrao() == "bash"


def test_powershell_quando_nao_ha_bash(monkeypatch):
    monkeypatch.setattr(script, "_interpretador", lambda nome: None if nome == "bash" else "/x/pwsh")
    assert script.linguagem_padrao() == "powershell"


def test_o_lancador_do_wsl_nao_conta_como_bash(monkeypatch, tmp_path):
    """System32\bash.exe abre um Linux separado; nao e o bash que queremos."""
    monkeypatch.setattr(script.shutil, "which",
                        lambda nome: r"C:\Windows\System32\bash.exe" if nome == "bash" else None)
    for var in ("ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        monkeypatch.setenv(var, str(tmp_path / "vazio"))
    assert script._bash_do_windows() is None


def test_acha_o_bash_ao_lado_do_git(monkeypatch, tmp_path):
    bash = tmp_path / "Git" / "bin" / "bash.exe"
    bash.parent.mkdir(parents=True)
    bash.write_text("")
    git = tmp_path / "Git" / "cmd" / "git.exe"
    git.parent.mkdir(parents=True)
    git.write_text("")
    monkeypatch.setattr(script.shutil, "which", lambda nome: str(git) if nome == "git" else None)
    for var in ("ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        monkeypatch.setenv(var, str(tmp_path / "vazio"))
    assert Path(script._bash_do_windows()) == bash
