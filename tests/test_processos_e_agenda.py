"""`processos(acao=...)` e `agenda(acao=...)` no lugar de seis ferramentas.

Cada ação chega na mesma função das antigas, que saem da mesa e continuam
despachando. A ação de leitura pode ser cortada pelo Parar mesmo dentro de
ferramenta de execução.
"""
import asyncio

import pytest

from sentury.harness.state import AnalysisState
from sentury.tools.catalog import execute_tool
from sentury.tools.registry import ferramentas_do_setor_ativo, interrompivel


def _rodar(tool, argumentos):
    return asyncio.run(execute_tool(None, AnalysisState("s", "u"), tool, argumentos))


def test_processos_leva_cada_acao_a_funcao_antiga(monkeypatch):
    from sentury.tools import processos

    chamadas = []
    monkeypatch.setattr(processos, "listar", lambda apenas_rodando=True: chamadas.append(("listar", apenas_rodando)) or [])
    monkeypatch.setattr(processos, "estado", lambda pid: chamadas.append(("ver", pid)) or {"ok": True})
    monkeypatch.setattr(processos, "encerrar", lambda pid: chamadas.append(("encerrar", pid)) or {"ok": True})

    assert _rodar("processos", {"acao": "listar"}) == {"processos": []}
    _rodar("processos", {"acao": "ver", "id": "p1"})
    _rodar("processos", {"acao": "encerrar", "id": "p1"})
    assert chamadas == [("listar", True), ("ver", "p1"), ("encerrar", "p1")]


def test_agenda_leva_cada_acao_a_funcao_antiga(monkeypatch):
    from sentury.external import agendador

    chamadas = []
    monkeypatch.setattr(agendador, "listar", lambda sessao: chamadas.append(("listar", sessao)) or {"ok": True})
    monkeypatch.setattr(agendador, "cancelar", lambda job: chamadas.append(("cancelar", job)) or {"ok": True})
    monkeypatch.setattr(agendador, "agendar", lambda **k: chamadas.append(("agendar", k["tarefa"])) or {"ok": True})

    _rodar("agenda", {"acao": "listar"})
    _rodar("agenda", {"acao": "cancelar", "id": "j1"})
    _rodar("agenda", {"acao": "agendar", "tarefa": "conferir o relatório", "cron": "0 9 * * 1"})
    assert chamadas == [("listar", "s"), ("cancelar", "j1"), ("agendar", "conferir o relatório")]


@pytest.mark.parametrize("tool,validas", [
    ("processos", "listar, ver ou encerrar"),
    ("agenda", "agendar, listar ou cancelar"),
])
def test_acao_desconhecida_diz_as_validas(tool, validas):
    assert validas in _rodar(tool, {"acao": "apagar_tudo"})["erro"]


def test_leitura_pode_ser_cortada_e_o_resto_espera():
    assert interrompivel("processos", {"acao": "listar"}) and interrompivel("processos", {"acao": "ver"})
    assert not interrompivel("processos", {"acao": "encerrar"})
    assert interrompivel("agenda", {"acao": "listar"})
    assert not interrompivel("agenda", {"acao": "agendar"}) and not interrompivel("agenda")
    # Ferramenta sem ações continua pela categoria.
    assert not interrompivel("escrever_arquivo", {"acao": "listar"})


def test_so_as_novas_vao_a_mesa():
    na_mesa = set(ferramentas_do_setor_ativo())
    assert {"processos", "agenda"} <= na_mesa
    antigas = {"running_commands", "command_status", "kill_command", "schedule_task", "list_schedules", "cancel_schedule"}
    assert not antigas & na_mesa
