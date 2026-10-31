"""Até quatro perguntas numa ida: o modelo agrupa as decisões, a pessoa responde
todas de uma vez (na tela ou em botões no Telegram) e a resposta volta inteira."""
import json

import pytest

from sentury.external.telegram_perguntas import PerguntasTelegram
from sentury.harness import perguntas


def _pergunta(texto, opcoes, multi=False):
    return {"question": texto, "options": [{"label": o} for o in opcoes], "multiSelect": multi}


def _plano(*questoes, intro=""):
    return [{"tool": "perguntar_usuario", "arguments": {"intro": intro, "questions": list(questoes)}}]


class TestExtrair:
    def test_limites_vem_do_yaml(self):
        assert perguntas.limites() == (4, 5)

    def test_corta_no_teto_e_descarta_o_que_nao_e_escolha(self):
        plano = _plano(*[_pergunta(f"q{i}", ["a", "b"]) for i in range(6)],
                       _pergunta("so uma opcao", ["a"]))
        extraido = perguntas.extrair(plano)
        assert [q["question"] for q in extraido["questions"]] == ["q0", "q1", "q2", "q3"]
        assert extraido["intro"]

    def test_opcao_repetida_some_e_escolha_multipla_fica(self):
        extraido = perguntas.extrair(_plano(_pergunta("canais", ["Email", "Email", "Telegram", "x", "y", "z", "w"], multi=True)))
        q = extraido["questions"][0]
        assert [o["label"] for o in q["options"]] == ["Email", "Telegram", "x", "y", "z"]
        assert q["multiSelect"] is True

    def test_sem_pergunta_valida_nao_ha_esclarecimento(self):
        assert perguntas.extrair(_plano(_pergunta("", ["a", "b"]))) is None
        assert perguntas.extrair([{"tool": "ler_arquivo", "arguments": {}}]) is None


class TestResposta:
    @pytest.fixture
    def duas(self):
        return [{"question": "formato", "multiSelect": False, "options": [{"label": "PDF"}, {"label": "Planilha"}]},
                {"question": "canais", "multiSelect": True, "options": [{"label": "Email"}, {"label": "Telegram"}]}]

    def test_conjunto_completo_volta_estruturado(self, duas):
        dado = perguntas.resposta(duas, [{"selecionadas": ["PDF"]},
                                         {"selecionadas": ["Email", "Telegram"], "outro": " e WhatsApp "}])
        assert dado["respostas"][1] == {"pergunta": "canais", "selecionadas": ["Email", "Telegram"], "outro": "e WhatsApp"}

    @pytest.mark.parametrize("respostas, trecho", [
        ([{"selecionadas": ["PDF"]}], "todas as perguntas"),
        ([{"selecionadas": ["PDF", "Planilha"]}, {"selecionadas": ["Email"]}], "não corresponde"),
        ([{"selecionadas": ["Word"]}, {"selecionadas": ["Email"]}], "não corresponde"),
        ([{"selecionadas": []}, {"selecionadas": ["Email"]}], "Falta uma resposta"),
        ([{"selecionadas": ["PDF"], "pergunta": "outra"}, {"selecionadas": ["Email"]}], "mudou"),
    ])
    def test_resposta_que_nao_bate_e_recusada(self, duas, respostas, trecho):
        with pytest.raises(ValueError, match=trecho):
            perguntas.resposta(duas, respostas)

    def test_retomada_valida_contra_a_pergunta_pendente(self, duas):
        class Estado:
            history = [{"role": "system", "clarification": {"questions": duas}}]

        texto = json.dumps({"respostas": [{"selecionadas": ["Planilha"]}, {"selecionadas": [], "outro": "SMS"}]})
        dado = json.loads(perguntas.validar_retomada(Estado(), texto))
        assert dado["respostas"][0]["selecionadas"] == ["Planilha"]
        assert perguntas.validar_retomada(Estado(), "texto comum da pessoa") == "texto comum da pessoa"


class TestTelegram:
    def _abrir(self):
        fluxo = PerguntasTelegram()
        clar = {"questions": [
            {"question": "formato", "multiSelect": False, "options": [{"label": "PDF"}, {"label": "Planilha"}]},
            {"question": "canais", "multiSelect": True, "options": [{"label": "Email"}, {"label": "Telegram"}]},
        ]}
        return fluxo, fluxo.abrir(chat_id=7, session_id="s", clarification=clar)

    def test_uma_pergunta_por_mensagem_ate_fechar_o_conjunto(self):
        fluxo, chave = self._abrir()
        assert fluxo.mensagem(chave, 7)["text"].startswith("1 de 2: formato")
        assert fluxo.tocar(f"sq:{chave}:0:0", 7)[1] is None
        assert "2 de 2" in fluxo.mensagem(chave, 7)["text"]
        fluxo.tocar(f"sq:{chave}:1:0", 7)
        fluxo.tocar(f"sq:{chave}:1:1", 7)
        _, final, _ = fluxo.tocar(f"sq:{chave}:1:ok", 7)
        assert json.loads(final)["respostas"][1]["selecionadas"] == ["Email", "Telegram"]
        assert fluxo.obter(chave, 7) is None

    def test_outra_resposta_por_texto_livre(self):
        fluxo, chave = self._abrir()
        fluxo.tocar(f"sq:{chave}:0:outro", 7)
        _, texto, _ = fluxo.texto_livre(7, "  um resumo em texto  ")
        assert texto is None and fluxo.obter(chave, 7)["indice"] == 1

    def test_toque_de_outro_chat_ou_etapa_velha_nao_vale(self):
        fluxo, chave = self._abrir()
        assert fluxo.tocar(f"sq:{chave}:0:0", 99) is None
        fluxo.tocar(f"sq:{chave}:0:0", 7)
        assert fluxo.tocar(f"sq:{chave}:0:1", 7) is None


def test_bolha_mostra_as_respostas_e_nao_o_json():
    """O texto que vai ao servidor é o pacote de respostas em JSON; a tela mostra
    um cartão com cada pergunta e o que foi escolhido, ao vivo e ao recarregar,
    porque o histórico guarda o mesmo texto."""
    import shutil
    import subprocess
    from pathlib import Path

    cliente = Path("sentury/client")
    node = shutil.which("node")
    if not node or not (cliente / "node_modules/typescript").exists():
        import pytest
        pytest.skip("o teste do client precisa de Node e npm install")
    script = """
    const fs = require('fs'), ts = require('typescript'), assert = require('node:assert/strict');
    const codigo = ts.transpileModule(fs.readFileSync('src/domain/clarification.ts', 'utf8'), {
      compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}
    }).outputText;
    const modulo = {exports: {}};
    new Function('exports', 'require', codigo)(modulo.exports, require);
    const ler = modulo.exports.lerRespostas;
    const texto = JSON.stringify({respostas: [
      {pergunta: 'Que dados?', selecionadas: ['Arquivos', 'Banco'], outro: ''},
      {pergunta: 'Entrega?', selecionadas: [], outro: 'Por e-mail'}]});
    assert.deepEqual(ler(texto), [{pergunta: 'Que dados?', escolhas: ['Arquivos', 'Banco'], outro: ''},
                                  {pergunta: 'Entrega?', escolhas: [], outro: 'Por e-mail'}]);
    assert.equal(ler('oi, tudo bem?'), null);
    assert.equal(ler('{"outra": 1}'), null);
    assert.equal(ler('{"respostas": [] }'), null);
    """
    resultado = subprocess.run([node, "-e", script], cwd=cliente, capture_output=True, text=True, timeout=30)
    assert resultado.returncode == 0, resultado.stderr
    bolha = (cliente / "src/features/chat/MessageBubble.tsx").read_text(encoding="utf-8")
    assert "lerRespostas(message.content)" in bolha and 'aria-label="Suas escolhas"' in bolha
