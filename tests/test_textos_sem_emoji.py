"""Impede símbolos de emoji no texto versionado, inclusive skills."""
from pathlib import Path
import re
import subprocess


RAIZ = Path(__file__).resolve().parents[1]
EMOJI = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D\u23E9-\u23FA\u20E3]")


def test_textos_versionados_sem_emoji():
    arquivos = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "sentury"], cwd=RAIZ,
    ).decode("utf-8").split("\0")
    encontrados = []
    for nome in filter(None, arquivos):
        # Apagado e ainda não commitado continua na lista do git.
        if not (RAIZ / nome).is_file():
            continue
        bruto = (RAIZ / nome).read_bytes()
        if b"\0" in bruto:
            continue
        try:
            texto = bruto.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for numero, linha in enumerate(texto.splitlines(), 1):
            if EMOJI.search(linha):
                encontrados.append(f"{nome}:{numero}")
    assert not encontrados, "Emoji em texto: " + ", ".join(encontrados)


def test_preferencias_preservadas_no_passo_nativo():
    from sentury.context.base import _texto_base
    from sentury.harness.passo_unico import base_do_passo

    base = base_do_passo(_texto_base("PLANNER_SYSTEM_PROMPT"))
    assert "A mensagem atual tem prioridade" in base
    assert '"plan":' not in base
    assert "### Quando perguntar" in base
