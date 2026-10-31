from pathlib import Path


CSS = Path("sentury/client/src/styles/index.css").read_text(encoding="utf-8")
APP = Path("sentury/client/src/app/AppShell.tsx").read_text(encoding="utf-8")
STORE = Path("sentury/client/src/stores/chat-store.ts").read_text(encoding="utf-8")
PERMISSAO = Path(
    "sentury/client/src/features/chat/PermissionSheet.tsx",
).read_text(encoding="utf-8")
COMPOSER = Path("sentury/client/src/features/chat/Composer.tsx").read_text(
    encoding="utf-8",
)
ATLAS = Path("sentury/client/src/dev/InterfaceAtlas.tsx").read_text(encoding="utf-8")
CALL_OVERLAY = Path("sentury/client/src/features/chat/CallOverlay.tsx").read_text(
    encoding="utf-8",
)


def test_client_tem_um_token_de_movimento_e_reduced_motion():
    assert "--sentury-motion-duration: 200ms" in CSS
    assert "--sentury-stream-duration: 150ms" in CSS
    assert "prefers-reduced-motion: reduce" in CSS


def test_stream_anima_so_o_fragmento_novo():
    assert "lastToken: event.text" in STORE
    assert "stream.text.slice(0, -stream.lastToken.length)" in APP
    assert 'className="sentury-stream-token"' in APP
    assert "filter: blur(4px)" in CSS
    assert "stream?.text.length" in APP


def test_trabalho_pulsa_indicador_sem_mover_o_bloco():
    trecho = CSS.split("@keyframes sentury-working-pulse", 1)[1].split("}", 2)[0]
    assert "opacity" in trecho
    assert "transform" not in trecho
    assert "sentury-spinner-turn 900ms linear infinite" in CSS


def test_so_permissao_recebe_pulso_rapido_colorido():
    assert "sentury-needs-user" in PERMISSAO
    assert "sentury-needs-user-pulse 600ms" in CSS
    assert CSS.count("sentury-needs-user-pulse 600ms") == 1
    assert "sentury-needs-user-pulse 600ms ease-in-out var(--sentury-motion-duration) 2" in CSS


def test_chave_intelligence_e_asset_estao_no_client():
    assert "'intelligence'" in COMPOSER
    assert "'intelligence'" in ATLAS
    assert "/sentury-intelligence.webp" in CALL_OVERLAY
    asset = Path("sentury/client/public/sentury-intelligence.webp")
    assert asset.is_file()
    assert asset.stat().st_size > 0
