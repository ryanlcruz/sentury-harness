"""O estado do turno mora numa variável de contexto, não no orquestrador."""
import asyncio

from sentury.harness import turno


def test_turnos_ao_mesmo_tempo_nao_misturam_o_estado():
    """A conversa e o residente rodam no mesmo orquestrador: a resposta direta de
    um não pode aparecer no outro, mesmo com as voltas intercaladas."""
    async def um_turno(nome, espera):
        turno.novo().resposta_direta = nome
        await asyncio.sleep(espera)
        return turno.atual().resposta_direta

    async def os_dois():
        return await asyncio.gather(um_turno("conversa", 0.02), um_turno("residente", 0.01))

    assert asyncio.run(os_dois()) == ["conversa", "residente"]


def test_o_orquestrador_le_o_turno_da_tarefa_e_cada_mensagem_abre_um_novo():
    from sentury.harness.orchestrator import SenturyOrchestrator

    async def cenario():
        primeiro = turno.novo()
        primeiro.reparos_json = 2
        assert SenturyOrchestrator.turno.fget(None) is primeiro
        segundo = turno.novo()
        return segundo.reparos_json, turno.atual() is segundo

    assert asyncio.run(cenario()) == (0, True)
