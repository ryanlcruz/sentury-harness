"""Seis unidades, o processo morre na quarta, a volta começa na quarta.

O processo é morto de verdade (`os._exit`, sem `finally` nem flush): um
`raise` dentro do teste deixaria o Python fechar arquivos com calma, e isso não
é o que acontece quando a máquina cai.
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from sentury.memory.unidades import DESCARTADA, FEITO, FAZENDO, REVISAR, Missao

VAGAS = [("vaga-a", "pagina"), ("vaga-a", "empresa"), ("vaga-b", "pagina"),
         ("vaga-b", "empresa"), ("vaga-c", "pagina"), ("vaga-c", "empresa")]

_RODADA = textwrap.dedent("""
    import json, os, sys
    from pathlib import Path
    from sentury.memory.unidades import Missao

    raiz, morrer_em = Path(sys.argv[1]), int(sys.argv[2])
    m = Missao("vagas", raiz=raiz)
    m.registrar(json.loads(sys.argv[3]))
    for n, reg in enumerate(m.proximas(), start=1):
        if m.abrir(reg["alvo"], reg["item"], sessao=str(os.getpid())) is None:
            continue
        if n == morrer_em:
            os._exit(9)
        m.fechar(reg["alvo"], reg["item"], evidencia={"pid": os.getpid()})
""")


def _rodar(raiz: Path, morrer_em: int) -> int:
    raiz_do_repo = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [sys.executable, "-c", _RODADA, str(raiz), str(morrer_em), json.dumps(VAGAS)],
        cwd=raiz_do_repo, env={**os.environ, "PYTHONPATH": str(raiz_do_repo)},
        capture_output=True, text=True, timeout=60,
    ).returncode


def test_morre_na_quarta_e_retoma_na_quarta(tmp_path):
    assert _rodar(tmp_path, morrer_em=4) == 9

    m = Missao("vagas", raiz=tmp_path)
    antes = {(r["alvo"], r["item"]): r for r in m.unidades()}
    assert [r["estado"] for r in m.unidades()] == [FEITO, FEITO, FEITO, FAZENDO, "pendente", "pendente"]
    # a que morreu entre abrir e fechar volta com a tentativa contada
    assert antes[("vaga-b", "empresa")]["tentativas"] == 1
    assert [(r["alvo"], r["item"]) for r in m.proximas()][0] == ("vaga-b", "empresa")

    assert _rodar(tmp_path, morrer_em=0) == 0

    depois = Missao("vagas", raiz=tmp_path).unidades()
    assert len(depois) == 6, "chave duplicada na retomada"
    assert all(r["estado"] == FEITO for r in depois)
    # as tres primeiras nao foram refeitas: mesma evidencia, mesmo carimbo
    for reg in depois[:3]:
        assert reg["evidencia"] == antes[(reg["alvo"], reg["item"])]["evidencia"]
        assert reg["updated_at"] == antes[(reg["alvo"], reg["item"])]["updated_at"]
        assert reg["tentativas"] == 1
    assert depois[3]["tentativas"] == 2


def test_registrar_de_novo_nao_duplica(tmp_path):
    m = Missao("x", raiz=tmp_path)
    assert m.registrar(VAGAS) == 6
    assert m.registrar(VAGAS + [("vaga-d", "pagina")]) == 1
    assert len(m.unidades()) == 7


def test_descartada_e_resultado_e_nao_volta_para_a_fila(tmp_path):
    m = Missao("x", raiz=tmp_path)
    m.registrar(VAGAS[:2])
    m.abrir("vaga-a", "pagina")
    m.fechar("vaga-a", "pagina", DESCARTADA, nota="pede 5 anos de experiencia")
    assert [(r["alvo"], r["item"]) for r in m.proximas()] == [("vaga-a", "empresa")]


def test_a_que_morre_sempre_vai_para_revisao(tmp_path):
    m = Missao("x", raiz=tmp_path, max_tentativas=2)
    m.registrar(VAGAS[:1])
    assert m.abrir("vaga-a", "pagina") and m.abrir("vaga-a", "pagina")
    assert m.abrir("vaga-a", "pagina") is None
    assert m.unidades()[0]["estado"] == REVISAR
    assert m.proximas() == []


def test_fechar_como_pendente_e_erro(tmp_path):
    m = Missao("x", raiz=tmp_path)
    m.registrar(VAGAS[:1])
    with pytest.raises(ValueError):
        m.fechar("vaga-a", "pagina", "pendente")
