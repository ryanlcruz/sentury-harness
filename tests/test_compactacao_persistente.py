import os
import subprocess
import sys
from pathlib import Path

import pytest

from sentury.harness.compactacao_persistente import (
    CompactacaoEmAndamento,
    DiarioDeCompactacao,
    hash_do_contexto,
    verificar_janela_auxiliar,
)


def test_hash_do_contexto_e_estavel_e_sensivel_ao_snapshot():
    a = [{"role": "user", "content": "um"}]
    b = [{"content": "um", "role": "user"}]
    assert hash_do_contexto(a) == hash_do_contexto(b)
    assert hash_do_contexto(a) != hash_do_contexto(a + [{"role": "assistant", "content": "dois"}])


def test_lease_isola_a_sessao_e_expira(tmp_path):
    agora = [100.0]
    diario = DiarioDeCompactacao(tmp_path / "compactacoes.db", relogio=lambda: agora[0])
    primeira = diario.adquirir_lease("s1", "turno-a", ttl_segundos=10)
    assert primeira is not None
    assert diario.adquirir_lease("s1", "turno-b", ttl_segundos=10) is None

    agora[0] = 111.0
    segunda = diario.adquirir_lease("s1", "turno-b", ttl_segundos=10)
    assert segunda is not None

    with pytest.raises(CompactacaoEmAndamento):
        with diario.lease("s1", dono="turno-c"):
            pass


def test_resultado_sobrevive_a_morte_antes_da_troca_de_estado(tmp_path):
    """O filho grava e morre sem liberar lease nem atualizar AnalysisState."""

    banco = tmp_path / "compactacoes.db"
    raiz = Path(__file__).resolve().parents[1]
    programa = r"""
import os
import sys
from sentury.harness.compactacao_persistente import DiarioDeCompactacao, hash_do_contexto

banco = sys.argv[1]
entrada = [{"role": "user", "content": "conversa antiga"}]
saida = [{"role": "system", "content": "resumo duravel"}]
diario = DiarioDeCompactacao(banco)
lease = diario.adquirir_lease("sessao-crash", "processo-que-cai", ttl_segundos=300)
assert lease is not None
diario.salvar(lease, hash_do_contexto(entrada), saida, {"human_summary": "resumo duravel"})
os._exit(0)
"""
    subprocess.run(
        [sys.executable, "-c", programa, str(banco)],
        cwd=raiz,
        check=True,
        env={**os.environ, "PYTHONPATH": str(raiz)},
    )

    chamadas_do_modelo = 0
    entrada = [{"role": "user", "content": "conversa antiga"}]
    reiniciado = DiarioDeCompactacao(banco)
    gravada = reiniciado.recuperar("sessao-crash", hash_do_contexto(entrada))
    if gravada is None:  # este ramo representaria a chamada cara repetida
        chamadas_do_modelo += 1

    assert chamadas_do_modelo == 0
    assert gravada is not None
    assert gravada.historico == [{"role": "system", "content": "resumo duravel"}]
    assert gravada.estado_conversa["human_summary"] == "resumo duravel"


def test_sonda_avisa_quando_auxiliar_nao_comporta_o_limiar():
    insuficiente = verificar_janela_auxiliar(32_000, 60_000, nome_auxiliar="flash")
    assert insuficiente.cabe is False
    assert insuficiente.limiar_efetivo == 32_000
    assert "flash" in str(insuficiente.aviso)

    suficiente = verificar_janela_auxiliar(128_000, 60_000)
    assert suficiente.cabe is True
    assert suficiente.limiar_efetivo == 60_000
    assert suficiente.aviso is None


@pytest.mark.asyncio
async def test_stop_cancela_o_turno_mas_nao_joga_o_resumo_fora(tmp_path):
    diario = DiarioDeCompactacao(tmp_path / "compactacoes.db")
    snapshot = [{"role": "user", "content": "historico"}]
    identidade = hash_do_contexto(snapshot)
    iniciou = __import__("asyncio").Event()
    liberar_modelo = __import__("asyncio").Event()
    chamadas = 0

    async def modelo():
        nonlocal chamadas
        chamadas += 1
        iniciou.set()
        await liberar_modelo.wait()
        return (
            [{"role": "system", "content": "resumo depois do stop"}],
            {"human_summary": "resumo depois do stop"},
        )

    asyncio = __import__("asyncio")
    turno = asyncio.create_task(
        diario.obter_ou_produzir("s-stop", identidade, modelo, dono="turno")
    )
    await iniciou.wait()
    turno.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turno

    liberar_modelo.set()
    for _ in range(20):
        await asyncio.sleep(0.01)
        if diario.recuperar("s-stop", identidade) is not None:
            break

    gravada = diario.recuperar("s-stop", identidade)
    assert gravada is not None
    assert gravada.historico[0]["content"] == "resumo depois do stop"

    async def nao_deveria_chamar():
        raise AssertionError("o modelo foi chamado uma segunda vez")

    reutilizada = await diario.obter_ou_produzir(
        "s-stop", identidade, nao_deveria_chamar, dono="turno-seguinte"
    )
    assert reutilizada.id == gravada.id
    assert chamadas == 1
