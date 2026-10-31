"""Skills de fora: buscar e ver não gravam nada; instalar pergunta sempre.

A aprovação vale para a skill e o commit que o cartão mostrou, nem para outra
skill nem para o repositório mudado depois. A skill instalada guarda de onde
veio, perde o gatilho de ativação automática e nunca roda shell ao carregar.
"""
import asyncio
import json

import pytest

from sentury.skills import de_fora, escrita
from sentury.tools import permissoes, web

COMMIT = "a" * 40
SKILL_MD = """---
name: leitor-de-faturas
description: Lê faturas em PDF e devolve os totais.
gatilhos: [qualquer pedido]
---

# Leitor de faturas

Rode `scripts/extrai.py` e confira o total. Data: !`whoami`
"""


def _arvore(*arquivos):
    return {"tree": [{"type": "blob", "path": caminho, "size": tamanho} for caminho, tamanho in arquivos]}


@pytest.fixture
def rede(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    respostas = {
        "https://skills.sh/api/search?q=fatura%20pdf": {"skills": [
            {"id": "dono/repo/leitor-de-faturas", "source": "dono/repo", "skillId": "leitor-de-faturas",
             "name": "leitor-de-faturas", "installs": 1200}]},
        "https://api.github.com/repos/dono/repo": {"default_branch": "main", "license": {"spdx_id": "MIT"}},
        "https://api.github.com/repos/dono/repo/git/ref/heads/main": {"object": {"sha": COMMIT}},
        f"https://api.github.com/repos/dono/repo/git/trees/{COMMIT}?recursive=1": _arvore(
            ("skills/leitor-de-faturas/SKILL.md", 300),
            ("skills/leitor-de-faturas/scripts/extrai.py", 40),
            ("skills/leitor-de-faturas/logo.png", 900),
            ("skills/leitor-de-planilhas/SKILL.md", 200),
            ("skills/outra-coisa/SKILL.md", 100)),
        f"https://raw.githubusercontent.com/dono/repo/{COMMIT}/skills/leitor-de-faturas/SKILL.md": SKILL_MD,
        f"https://raw.githubusercontent.com/dono/repo/{COMMIT}/skills/leitor-de-faturas/scripts/extrai.py":
            "print('total')\n",
    }
    pedidas = []

    async def falso(url, timeout=20.0):
        pedidas.append(url)
        if url not in respostas:
            return {"ok": False, "status": 404, "corpo": "", "motivo": "não encontrado"}
        corpo = respostas[url]
        return {"ok": True, "status": 200, "truncado": False,
                "corpo": corpo if isinstance(corpo, str) else json.dumps(corpo)}

    monkeypatch.setattr(web, "ler_bruto", falso)
    return pedidas


def _rodar(argumentos, sessao="s1"):
    return asyncio.run(de_fora.executar(argumentos, sessao))


def _instalada():
    return escrita.pasta_do_usuario() / "leitor-de-faturas"


def test_buscar_traz_repositorio_e_instalacoes(rede):
    r = _rodar({"acao": "buscar", "consulta": "fatura pdf"})
    assert r["skills"] == [{"id": "dono/repo/leitor-de-faturas", "nome": "leitor-de-faturas",
                            "repositorio": "dono/repo", "instalacoes": 1200}]


def test_ver_mostra_licenca_scripts_e_nao_grava(rede):
    r = _rodar({"acao": "ver", "id": "dono/repo/leitor-de-faturas"})
    assert r["licenca"] == "MIT" and r["commit"] == COMMIT[:12]
    assert r["scripts"] == ["scripts/extrai.py"]
    assert r["fora_da_copia"] == ["logo.png"], "binário não entra"
    assert "Leitor de faturas" in r["texto"] and r["ja_instalada"] is False
    assert not escrita.pasta_do_usuario().exists()


def test_instalar_pergunta_e_so_grava_depois_do_sim(rede):
    pedido = _rodar({"acao": "instalar", "id": "dono/repo/leitor-de-faturas"})
    assert pedido["precisa_permissao"] and pedido["so_desta_vez"]
    assert "Licença: MIT" in pedido["motivo"] and "scripts/extrai.py" in pedido["motivo"]
    assert not _instalada().exists()

    permissoes.responder(pedido["comando"], "uma_vez", "s1")
    r = _rodar({"acao": "instalar", "id": "dono/repo/leitor-de-faturas"})
    assert r["status"] == "instalada"
    texto = (_instalada() / "SKILL.md").read_text(encoding="utf-8")
    assert "origem: \"skills.sh/dono/repo/leitor-de-faturas\"" in texto
    assert f"commit: {COMMIT}" in texto and "license: \"MIT\"" in texto
    assert "gatilhos" not in texto, "texto de fora não se ativa sozinho"
    assert (_instalada() / "scripts/extrai.py").read_text(encoding="utf-8") == "print('total')\n"
    assert not (_instalada() / "logo.png").exists()
    assert all(u.startswith(("https://api.github.com/", "https://raw.githubusercontent.com/")) for u in rede)


def test_permitir_tudo_nao_dispensa_o_cartao(rede, monkeypatch):
    permissoes.definir_permitir_tudo(True)
    try:
        assert _rodar({"acao": "instalar", "id": "dono/repo/leitor-de-faturas"}, "s2")["precisa_permissao"]
    finally:
        permissoes.definir_permitir_tudo(False)
    assert not _instalada().exists()


def test_aprovar_uma_skill_nao_instala_outra(rede):
    pedido = _rodar({"acao": "instalar", "id": "dono/repo/leitor-de-faturas"}, "s3")
    permissoes.responder(pedido["comando"], "uma_vez", "s3")
    outra = _rodar({"acao": "instalar", "id": "dono/repo/leitor-de-faturas", "nome": "faturas-dois"}, "s3")
    assert outra.get("precisa_permissao"), "a aprovação foi para outro nome"
    assert not (escrita.pasta_do_usuario() / "faturas-dois").exists()


def test_skill_de_fora_carrega_com_aviso_e_sem_shell(rede, monkeypatch):
    pedido = _rodar({"acao": "instalar", "id": "dono/repo/leitor-de-faturas"}, "s4")
    permissoes.responder(pedido["comando"], "uma_vez", "s4")
    _rodar({"acao": "instalar", "id": "dono/repo/leitor-de-faturas"}, "s4")
    monkeypatch.setenv("SENTURY_ENABLE_SKILLS_INLINE_SHELL", "1")
    skill = escrita._carregador().load_skill("leitor-de-faturas")
    assert skill.metadata.origem == "skills.sh/dono/repo/leitor-de-faturas"
    assert "!`whoami`" in skill.body, "carregar não executa nada"
    bloco = skill.to_context_block()
    assert "[SKILL DE FORA]" in bloco and "licença MIT" in bloco


def test_desfazer_remove_a_instalacao(rede):
    pedido = _rodar({"acao": "instalar", "id": "dono/repo/leitor-de-faturas"}, "s5")
    permissoes.responder(pedido["comando"], "uma_vez", "s5")
    _rodar({"acao": "instalar", "id": "dono/repo/leitor-de-faturas"}, "s5")
    assert escrita.executar({"acao": "desfazer", "nome": "leitor-de-faturas"})["acao_desfeita"] == "instalar"
    assert not _instalada().exists()


def test_licenca_sem_nome_aponta_o_arquivo(rede, monkeypatch):
    local = {"arquivos": [{"caminho": "SKILL.md", "bytes": 1}, {"caminho": "LICENSE.txt", "bytes": 1}],
             "licenca_do_repositorio": "", "id": "d/r/s", "repositorio": "d/r", "commit": COMMIT,
             "fora_da_copia": []}
    assert de_fora._resumo(local, {})["licenca"] == "em LICENSE.txt, leia antes"
    local["arquivos"].pop()
    assert de_fora._resumo(local, {})["licenca"] == "não declarada"


def test_nome_ja_usado_e_id_estranho_viram_erro(rede):
    pedido = _rodar({"acao": "instalar", "id": "dono/repo/leitor-de-faturas"}, "s6")
    permissoes.responder(pedido["comando"], "uma_vez", "s6")
    _rodar({"acao": "instalar", "id": "dono/repo/leitor-de-faturas"}, "s6")
    assert "já existe" in _rodar({"acao": "instalar", "id": "dono/repo/leitor-de-faturas"}, "s6")["erro"]
    for estranho in ("dono/repo/../x", "dono/repo", "https://x/y/z"):
        assert "erro" in _rodar({"acao": "ver", "id": estranho})


def test_buscar_e_ver_sao_leitura_e_instalar_escreve():
    from sentury.tools.registry import efeito_de

    assert efeito_de("find_skills", {"acao": "buscar"}) == "leitura"
    assert efeito_de("find_skills", {"acao": "ver"}) == "leitura"
    assert efeito_de("find_skills", {"acao": "instalar"}) == "escrita"
