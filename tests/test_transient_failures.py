from sentury.harness.state import AnalysisState, is_transient_failure_message
from sentury.memory.session_index import preview_from_history, visible_messages


GENERIC_FALLBACK = (
    "⚠️ No momento não consegui acessar os provedores de IA para montar esta resposta "
    "(provavelmente limite de uso temporário)."
)


def test_transient_provider_failure_is_pruned_with_user_turn():
    state = AnalysisState.new("s1", "u1")
    state.history = [
        {"role": "user", "content": "Como está o Medida geral?"},
        {"role": "assistant", "content": "Medida geral em -31,2."},
        {"role": "user", "content": "monte um html sobre o medida"},
        {"role": "assistant", "content": GENERIC_FALLBACK},
    ]

    removed = state.prune_transient_failures()

    assert removed == 2
    assert [m["content"] for m in state.history if m["role"] != "system"] == [
        "Como está o Medida geral?",
        "Medida geral em -31,2.",
    ]


def test_regenerate_removes_latest_matching_turn_only():
    state = AnalysisState.new("s1", "u1")
    state.history = [
        {"role": "user", "content": "Como está o Medida geral?"},
        {"role": "assistant", "content": "Medida geral em -31,2."},
        {"role": "user", "content": "faça novamente"},
        {"role": "assistant", "content": "Refiz o dashboard."},
    ]

    assert state.remove_latest_user_turn("faça novamente") is True
    assert [m["content"] for m in state.history] == [
        "Como está o Medida geral?",
        "Medida geral em -31,2.",
    ]


def test_session_index_ignores_transient_failures():
    history = [
        {"role": "user", "content": "Como está o Medida geral?"},
        {"role": "assistant", "content": "Medida geral em -31,2."},
        {"role": "user", "content": "monte um html sobre o medida"},
        {"role": "assistant", "content": GENERIC_FALLBACK},
    ]

    assert is_transient_failure_message(history[-1])
    assert len(visible_messages(history)) == 3
    assert preview_from_history(history) == "monte um html sobre o medida"


def test_artifact_payload_stays_out_of_history_and_public_state():
    state = AnalysisState.new("artifact-state", "u1")
    metadata = state.store_artifact({
        "type": "html",
        "filename": "plano.html",
        "mime_type": "text/html",
        "content_base64": "cGF5bG9hZC1naWdhbnRl",
        "verified_preview_base64": "cHJldmlldy1naWdhbnRl",
    })
    state.history = [{"role": "assistant", "content": "Pronto.", "attachment": metadata}]

    public = state.to_dict()
    persisted = state.to_persisted_dict()

    attachment = public["history"][0]["attachment"]
    assert "content_base64" not in attachment
    assert "verified_preview_base64" not in attachment
    assert "artifacts" not in public
    assert persisted["artifacts"][metadata["artifact_id"]]["attachment"]["content_base64"] == "cGF5bG9hZC1naWdhbnRl"

    restored = AnalysisState.from_dict(persisted)
    assert restored.get_artifact(metadata["artifact_id"])["verified_preview_base64"] == "cHJldmlldy1naWdhbnRl"


def test_legacy_python_result_is_removed_from_session_anchor():
    state = AnalysisState.from_dict({
        "session_id": "legacy-python",
        "user_id": "u1",
        "results": {
            "resultado_001": {
                "tool": "consultar_medida",
                "arguments": {},
                "summary": {"medida": -31.2},
                "row_count": 1,
                "created_at": 10,
            },
            "resultado_002": {
                "tool": "executar_python",
                "arguments": {"codigo": "save_html(... base64 ...)"},
                "summary": {"codigo": "save_html(... base64 ...)"},
                "row_count": 1,
                "created_at": 20,
            },
        },
        "last_result_id": "resultado_002",
    })

    assert set(state.results) == {"resultado_001"}
    assert state.last_result_id == "resultado_001"


def test_legacy_history_attachment_is_migrated_without_exposing_payload():
    state = AnalysisState.from_dict({
        "session_id": "legacy-artifact",
        "user_id": "u1",
        "history": [{
            "role": "assistant",
            "content": "Artefato pronto.",
            "attachment": {
                "type": "html",
                "filename": "legado.html",
                "mime_type": "text/html",
                "content_base64": "PGgxPkxlZ2FkbzwvaDE+",
            },
        }],
    })

    metadata = state.history[0]["attachment"]
    assert metadata["artifact_id"]
    assert "content_base64" not in metadata
    assert state.get_artifact(metadata["artifact_id"])["content_base64"] == "PGgxPkxlZ2FkbzwvaDE+"
