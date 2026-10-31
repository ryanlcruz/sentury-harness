from __future__ import annotations

import asyncio
import base64
from pathlib import Path
import tempfile
from typing import List, Optional, TypedDict


class RenderVerificationResult(TypedDict, total=False):
    status: str
    checks_run: List[str]
    preview_available: bool
    errors: List[str]
    preview_content_base64: str
    preview_mime_type: str
    preview_filename: str
    preview_source: str


def _load_sync_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    return sync_playwright


def verify_render_preview(artifact_type: str, payload: bytes) -> Optional[RenderVerificationResult]:
    """Verifica o render (Playwright). SEGURO de chamar de contexto sync OU async:
    o `sync_playwright` NÃO roda dentro de um loop asyncio, então se detectarmos um
    loop rodando (ex.: chamado de dentro do orquestrador async), a verificação roda
    numa thread separada. Sem isso, a validação (VALIDADO) falhava em silêncio."""
    try:
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False
    if in_loop:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_verify_render_preview_impl, artifact_type, payload).result()
    return _verify_render_preview_impl(artifact_type, payload)


def _verify_render_preview_impl(artifact_type: str, payload: bytes) -> Optional[RenderVerificationResult]:
    sync_playwright = _load_sync_playwright()
    if sync_playwright is None:
        return None

    artifact_type = (artifact_type or "").strip().lower()
    if artifact_type == "html":
        return _render_html_preview(payload, sync_playwright)
    if artifact_type == "svg":
        return _render_svg_preview(payload, sync_playwright)
    return None


def _is_environment_unavailable(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(token in message for token in (
        "executable doesn't exist",
        "please run the following command",
        "playwright install",
        "failed to launch",
        "browserType.launch".lower(),
    ))


def _render_html_preview(payload: bytes, sync_playwright) -> Optional[RenderVerificationResult]:
    html_text = payload.decode("utf-8", errors="ignore")
    return _render_document_preview("html", html_text, sync_playwright)


def _render_svg_preview(payload: bytes, sync_playwright) -> Optional[RenderVerificationResult]:
    svg_text = payload.decode("utf-8", errors="ignore")
    wrapper = (
        "<!doctype html><html><body style=\"margin:0;padding:24px;background:#ffffff;\">"
        f"{svg_text}"
        "</body></html>"
    )
    return _render_document_preview("svg", wrapper, sync_playwright)


def _render_document_preview(kind: str, html_text: str, sync_playwright) -> Optional[RenderVerificationResult]:
    try:
        js_errors: List[str] = []
        with tempfile.TemporaryDirectory(prefix="sentury-render-verify-") as temp_dir:
            html_path = Path(temp_dir) / f"{kind}-preview.html"
            html_path.write_text(html_text, encoding="utf-8")

            with sync_playwright() as playwright:
                from ..tools.navegador_local import abrir

                browser = abrir(playwright)
                page = browser.new_page(viewport={"width": 1440, "height": 960})
                # Exceções não capturadas sinalizam falha de renderização.
                # Mensagens de console incluem ruído de rede e causam falsos positivos.
                page.on("pageerror", lambda e: js_errors.append(str(e)[:200]))
                page.goto(html_path.as_uri(), wait_until="load")
                page.wait_for_timeout(200)  # deixa scripts/render assentarem
                screenshot = page.screenshot(full_page=True)
                browser.close()

        checks = [f"{kind}_browser_render"]
        errors: List[str] = []
        if js_errors:
            # dedup preservando ordem
            vistos = list(dict.fromkeys(js_errors))
            errors.append("erro de JavaScript ao renderizar: " + " | ".join(vistos[:3]))

        if screenshot and not errors:
            checks.append(f"{kind}_screenshot")
            return {
                "status": "ok",
                "checks_run": checks,
                "preview_available": True,
                "preview_content_base64": base64.b64encode(screenshot).decode("ascii"),
                "preview_mime_type": "image/png",
                "preview_filename": f"{kind}-verified-preview.png",
                "preview_source": "browser_screenshot",
                "errors": [],
            }

        return {
            "status": "broken" if errors else "warning",
            "checks_run": checks,
            "preview_available": False,
            "errors": errors or [f"{kind} render verification produced empty screenshot"],
        }
    except Exception as exc:
        if _is_environment_unavailable(exc):
            return None
        return {
            "status": "warning",
            "checks_run": [f"{kind}_browser_render_attempted"],
            "preview_available": False,
            "errors": [f"{kind} render verification failed: {exc}"],
        }
