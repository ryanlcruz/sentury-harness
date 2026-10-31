"""Número dentro do bloco vivo passa pelo mesmo grounding do texto.

O grounding lê o bloco como a pessoa lê: o texto visível e os números do
script entram; tag, CSS e atributos não, senão o estilo vira número sem lastro.
"""
from sentury.harness.grounding import texto_para_conferir
from sentury.harness.guardrails import currency_guardrail, decimal_observer
from sentury.harness.state import AnalysisState

BLOCO = """Resumo:

```vivo
<style>.cartao{letter-spacing:0.06em;opacity:.85}</style>
<div class="cartao" style="padding:1.5em">
  <div class="rotulo">Vendas</div>
  <div class="numero">R$ 98.000</div>
</div>
<script>const base = 120.4; const fator = 1.07;</script>
```
"""


def _estado_com_evidencia(texto):
    estado = AnalysisState.new("s", "u")
    estado.history.append({"role": "system", "content": f'RESULTADO DA FERRAMENTA "executar_python" (já executada): {texto}'})
    return estado


def test_o_bloco_e_lido_pelo_texto_visivel_e_pelos_numeros_do_script():
    lido = texto_para_conferir(BLOCO)
    assert "R$ 98.000" in lido and "Vendas" in lido
    assert "120.4" in lido and "1.07" in lido
    assert "0.06" not in lido and "1.5" not in lido and "<div" not in lido
    assert texto_para_conferir(BLOCO.replace("```vivo", "```html")) == lido


def test_valor_inventado_no_bloco_ganha_aviso():
    estado = _estado_com_evidencia("{'total': 120400.0}")
    resultado = currency_guardrail(estado, BLOCO)
    assert resultado.aviso and "98.000" in resultado.aviso


def test_estilo_do_bloco_nao_vira_numero_sem_lastro():
    from sentury.harness.grounding import classify_numbers, evidence_text

    estado = _estado_com_evidencia("{'base': 120.4, 'fator': 1.07}")
    classes = classify_numbers(texto_para_conferir(BLOCO), evidence_text(estado))
    assert not {0.06, 0.85, 1.5} & set(classes["suspect"])
    assert {120.4, 1.07} <= set(classes["grounded"])
    assert decimal_observer(estado, BLOCO).detail["grounded"] >= 2


def test_valor_do_painel_passa_pelo_grounding():
    painel = '```painel\n{"tipo": "numeros", "itens": [{"rotulo": "Vendas", "valor": "R$ 98.000"}]}\n```'
    assert "R$ 98.000" in texto_para_conferir(painel)
    estado = _estado_com_evidencia("{'total': 120400.0}")
    assert currency_guardrail(estado, painel).aviso
    sim = '```painel\n{"tipo": "simulador", "resultados": [{"formula": "120.4 * 1.5"}]}\n```'
    assert "1.5" not in texto_para_conferir(sim)
