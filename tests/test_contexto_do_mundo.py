"""O agente passa a saber quando e agora e ate quando o dado vai.

Duas lacunas que se explicam juntas.

A DATA chegava so ao planejador (`_generate_plan`), e so ela: sem hora, sem dia
da semana. Entao o respondedor nao sabia em que dia estava, "daqui a duas horas"
era incomputavel, e converter "toda segunda de manha" em `0 9 * * 1` (que e o
que `schedule_task` pede) exigia deduzir o dia da semana de uma data ISO.

E a COBERTURA do dado nao chegava a lugar nenhum. `periodo_disponivel()` estava
implementado em quatro stores com ZERO chamadores. Por isso nasceu um guardrail
que afirmava um fato FALSO (que o dataset ia "ate o comeco do mes atual", quando
ia ate 6 de julho) e na sequencia mandava o modelo nao reclamar de defasagem.
Guardrail existindo porque a informacao nao existia.
"""
import asyncio
import re
from datetime import datetime
from pathlib import Path

import pytest

from sentury.harness.contexto_do_mundo import ambiente_do_turno
from sentury.tools.shell import agora




# --------------------------------------------------------------- o agora

def test_o_agora_traz_dia_da_semana_data_e_hora():
    texto = "\n".join(agora())
    hoje = datetime.now()
    assert hoje.strftime("%d/%m/%Y") in texto
    assert hoje.date().isoformat() in texto
    assert re.search(r"\d{2}:\d{2}", texto)


def test_o_dia_da_semana_vem_escrito():
    """Deduzir o dia da semana de uma data ISO e conta que modelo erra: e e
    exatamente o que `schedule_task` pede que ele faca."""
    dias = ("segunda-feira", "terca-feira", "quarta-feira", "quinta-feira",
            "sexta-feira", "sabado", "domingo")
    texto = "\n".join(agora()).lower()
    assert any(d in texto for d in dias)


def test_a_convencao_do_cron_vem_junto():
    """Em cron a semana comeca no DOMINGO. Converter de cabeca e o erro mais
    comum de quem agenda "toda segunda", e o numero certo esta na linha."""
    texto = "\n".join(agora())
    assert "0=domingo" in texto
    esperado = (datetime.now().weekday() + 1) % 7
    assert f"hoje e {esperado}." in texto


def test_o_agora_mora_junto_do_ambiente():
    """Uma diz ONDE o comando roda, a outra diz QUANDO o turno acontece. Sao a
    mesma categoria de fato sobre o mundo."""
    from sentury.tools import shell

    assert callable(shell.agora) and callable(shell.ambiente)


def test_os_dois_lados_recebem_o_agora():
    """A data chegava so ao planejador. O respondedor (que escreve o texto que
    o usuario le) nao sabia em que dia estava."""
    texto = ambiente_do_turno("s1")
    assert "### AGORA" in texto
    assert "### AMBIENTE" in texto












# --------------------------------------- o guardrail que afirmava o falso

def test_o_contexto_temporal_falso_morreu():
    """Ele dizia que o dataset ia "ate o comeco de {mes atual}" quando ia ate 6
    de julho (dois meses e dez dias antes) e mandava o modelo nao reclamar de
    defasagem. Um guardrail nao pode sustentar a propria premissa com um fato
    que o dado contradiz."""
    fonte = Path("sentury/harness/orchestrator.py").read_text(encoding="utf-8")
    assert "CONTEXTO TEMPORAL (obrigatório)" not in fonte
    assert "MAIS RECENTE disponível" not in fonte




class TestACoberturaSaiu:
    """O generalista abria conversa dizendo "estou com a base de dados aberta
    (de janeiro a julho de 2026)": uma base que ele não tem.

    A cobertura lia o store, que é o de CX. Travá-la no generalista era meio
    conserto; a cobertura do dado de um plug é assunto do plug, não do mundo
    do agente. Se o setor precisar dizer o recorte, ele diz: pelo `planner`
    dele ou pelo resultado da própria ferramenta, que já carrega o período.
    """

    def test_o_mundo_nao_fala_mais_de_dataset(self):
        from sentury.harness import contexto_do_mundo as ctx

        assert not hasattr(ctx, "cobertura")

    def test_o_orquestrador_nao_injeta_mais(self):
        import io as _io

        fonte = _io.open("sentury/harness/orchestrator.py", encoding="utf-8").read()
        assert "cobertura" not in fonte
