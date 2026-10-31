import shutil
import subprocess
from pathlib import Path

import pytest


RAIZ = Path(__file__).resolve().parents[1]
MODULO = "./sentury/client/src/stores/execution-permissions.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node nao instalado")
def test_duas_aprovacoes_fecham_somente_o_bloco_certo():
    programa = f"""
      import assert from 'node:assert/strict';
      import {{
        createExecutionPermissionState,
        registerExecution,
        attachExecutionPermission,
        resolveExecutionPermission,
        permissionForExecution,
      }} from {MODULO!r};

      let state = createExecutionPermissionState();
      state = registerExecution(state, 'p1s0');
      state = registerExecution(state, 'p1s1');
      state = attachExecutionPermission(state, 'p1s0', {{
        chave: 'arquivo:a', comando: 'editar a.txt', motivo: 'escrita'
      }});
      state = attachExecutionPermission(state, 'p1s1', {{
        chave: 'arquivo:b', comando: 'editar b.txt', motivo: 'escrita'
      }});

      assert.equal(permissionForExecution(state, 'p1s0').comando, 'editar a.txt');
      assert.equal(permissionForExecution(state, 'p1s1').comando, 'editar b.txt');

      // Aprovar e negar usam a mesma transicao: a decisao fecha a pendencia
      // daquele id, sem deslocar nem apagar a outra.
      state = resolveExecutionPermission(state, 'p1s0');
      assert.equal(permissionForExecution(state, 'p1s0'), undefined);
      assert.equal(permissionForExecution(state, 'p1s1').comando, 'editar b.txt');
      state = resolveExecutionPermission(state, 'p1s1');
      assert.equal(permissionForExecution(state, 'p1s1'), undefined);
    """
    subprocess.run(
        [shutil.which("node"), "--input-type=module", "--eval", programa],
        cwd=RAIZ,
        check=True,
        capture_output=True,
        text=True,
    )


def test_command_run_expoe_a_permissao_para_o_cartao():
    contrato = (
        RAIZ / "sentury/client/src/contracts/domain/session.ts"
    ).read_text(encoding="utf-8")
    trecho = contrato.split("export interface CommandRun", 1)[1].split("}", 1)[0]
    assert "permissao?: PermissaoPayload" in trecho
