"""O cofre é o lugar das chaves: vence o .env; o ambiente do processo vence o cofre."""
import os

from pydantic_settings import BaseSettings, SettingsConfigDict

from sentury import config


class _Config(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    CHAVE_DE_TESTE: str = ""
    OUTRA_DE_TESTE: str = ""


def test_cofre_vence_o_env_e_o_ambiente_vence_o_cofre(tmp_path, monkeypatch):
    from robinbandit import secrets

    env = tmp_path / ".env"
    env.write_text("CHAVE_DE_TESTE=do-env\nOUTRA_DE_TESTE=do-env\n", encoding="utf-8")
    monkeypatch.setattr(secrets, "_carregar", lambda: {"CHAVE_DE_TESTE": "do-cofre",
                                                        "OUTRA_DE_TESTE": "do-cofre"})
    monkeypatch.delenv("CHAVE_DE_TESTE", raising=False)
    monkeypatch.setenv("OUTRA_DE_TESTE", "do-processo")
    config._carregar_cofre_no_ambiente()
    lido = _Config(_env_file=str(env))
    assert lido.CHAVE_DE_TESTE == "do-cofre"
    assert lido.OUTRA_DE_TESTE == "do-processo"
    os.environ.pop("CHAVE_DE_TESTE", None)
