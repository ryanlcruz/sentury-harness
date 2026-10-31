import shutil
import subprocess
from pathlib import Path

import pytest


CLIENT = Path("sentury/client")


def test_referencia_do_client_preserva_id_tipo_e_data_sem_carregar_base64():
    node = shutil.which("node")
    if not node or not (CLIENT / "node_modules/typescript").exists():
        pytest.skip("o teste do client precisa de Node e npm install")
    script = """
    const fs = require('fs'), ts = require('typescript'), assert = require('node:assert/strict');
    const codigo = ts.transpileModule(fs.readFileSync('src/domain/artifact-remoto.ts', 'utf8'), {
      compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}
    }).outputText;
    const modulo = {exports: {}};
    new Function('exports', codigo)(modulo.exports);
    const item = {id: 'imagem-1', sessionId: 's1', title: 'tela.png', type: 'png', createdAt: 10000};
    const r = modulo.exports.referenciaDeArtefato(item);
    assert.equal(r.id, item.id); assert.equal(r.sessionId, 's1');
    assert.equal(r.formato, 'png'); assert.equal(r.type, 'file');
    assert.equal(r.createdAt, '1970-01-01T00:00:10.000Z');
    assert.deepEqual(r.attachment, {artifact_id: 'imagem-1', type: 'png',
      filename: 'tela.png', payload_persisted: true});
    assert.equal('content_base64' in r.attachment, false);
    """
    resultado = subprocess.run([node, "-e", script], cwd=CLIENT, capture_output=True, text=True, timeout=30)
    assert resultado.returncode == 0, resultado.stderr


def test_biblioteca_adota_a_referencia_e_o_painel_usa_o_visualizador_existente():
    biblioteca = (CLIENT / "src/features/workbench/ArtifactsView.tsx").read_text(encoding="utf-8")
    painel = (CLIENT / "src/features/workbench/WorkbenchPanel.tsx").read_text(encoding="utf-8")
    assert "if (!item.local) addArtifact(referenciaDeArtefato(item))" in biblioteca
    assert "onClick={() => abrir(artifact)}" in biblioteca
    assert "rawAttachment={activeArtifact.attachment}" in painel
    assert "key={activeArtifact.id}" in painel
