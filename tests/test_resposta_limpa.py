"""Formato de arquivo não é texto de conversa.

Os casos saíram de uma resposta real:

- cerca ```json aberta e fechada sem nada dentro, com botão de copiar;
- `- [ ]* 1.4`, `- [ ]! Triagem pronta?`, `_Agenda: 0 8 * * 1_` na prosa;
- o plano escrito fase por fase, do lado do card que mostra o mesmo.
"""
from types import SimpleNamespace

from sentury.harness.resposta_limpa import AVISO_DO_CARD, avisar_do_card, limpar


class TestOQueSai:
    def test_cerca_vazia_some(self):
        assert "```" not in limpar("Segue.\n\n```json\n\n```\n\nFim.")

    def test_cerca_com_conteudo_fica(self):
        """Apagar código de verdade é pior que deixar passar uma cerca vazia."""
        texto = "Veja:\n\n```python\nprint(1)\n```"
        assert "print(1)" in limpar(texto)

    def test_marca_de_portao_e_de_opcional_saem(self):
        limpo = limpar("- [ ]! Triagem pronta?\n- [ ]* 1.4 Anotar")
        assert "[ ]!" not in limpo and "[ ]*" not in limpo
        # A tarefa continua: o que sai é o sinal, não o texto.
        assert "Triagem pronta?" in limpo and "Anotar" in limpo

    def test_checkbox_comum_continua(self):
        """`- [ ] fazer isso` é markdown legítimo que o usuário pode querer."""
        assert "- [ ] fazer isso" in limpar("- [ ] fazer isso")

    def test_linha_de_agenda_e_requisito_saem(self):
        limpo = limpar("Passo\n_Agenda: 0 8 * * 1_\n_Requisito: R1 — provar_\nFim")
        assert "Agenda:" not in limpo and "Requisito:" not in limpo
        assert "Passo" in limpo and "Fim" in limpo

    def test_vazio_nao_quebra(self):
        assert limpar("") == "" and limpar(None) is None


class TestOAvisoDoCard:
    def test_entra_quando_o_turno_mexeu_no_plano(self):
        estado = SimpleNamespace(history=[])
        assert avisar_do_card(estado, "criar_plano") is True
        assert AVISO_DO_CARD in estado.history[0]["content"]

    def test_nao_entra_para_outra_ferramenta(self):
        estado = SimpleNamespace(history=[])
        assert avisar_do_card(estado, "buscar_web") is False
        assert estado.history == []

    def test_uma_vez_por_turno(self):
        """Repetir o aviso gasta contexto sem mudar nada."""
        estado = SimpleNamespace(history=[])
        avisar_do_card(estado, "criar_plano")
        assert avisar_do_card(estado, "status_da_tarefa") is False
        assert len(estado.history) == 1
