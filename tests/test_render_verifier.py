from sentury.artifacts.render_verifier import verify_render_preview


def test_render_verifier_returns_none_when_playwright_is_unavailable(monkeypatch):
    monkeypatch.setattr("sentury.artifacts.render_verifier._load_sync_playwright", lambda: None)

    result = verify_render_preview("html", b"<html><body>ok</body></html>")

    assert result is None


def test_render_verifier_routes_html_to_browser_runner(monkeypatch):
    monkeypatch.setattr("sentury.artifacts.render_verifier._load_sync_playwright", lambda: object())
    monkeypatch.setattr(
        "sentury.artifacts.render_verifier._render_html_preview",
        lambda payload, playwright: {
            "status": "ok",
            "checks_run": ["html_browser_render"],
            "preview_available": True,
            "errors": [],
        },
    )

    result = verify_render_preview("html", b"<html><body>ok</body></html>")

    assert result["status"] == "ok"
    assert "html_browser_render" in result["checks_run"]


def test_render_verifier_routes_svg_to_browser_runner(monkeypatch):
    monkeypatch.setattr("sentury.artifacts.render_verifier._load_sync_playwright", lambda: object())
    monkeypatch.setattr(
        "sentury.artifacts.render_verifier._render_svg_preview",
        lambda payload, playwright: {
            "status": "warning",
            "checks_run": ["svg_browser_render"],
            "preview_available": True,
            "errors": ["svg render overflow"],
        },
    )

    result = verify_render_preview("svg", b"<svg viewBox='0 0 10 10'></svg>")

    assert result["status"] == "warning"
    assert result["errors"] == ["svg render overflow"]
