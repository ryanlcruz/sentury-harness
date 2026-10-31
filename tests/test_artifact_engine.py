import base64
import io
import zipfile

from sentury.artifacts.planner import plan_artifact_request
from sentury.artifacts.planner import build_artifact_prompt
from sentury.artifacts.validation import validate_artifact


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _b64_bytes(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def _office_package(entries: dict[str, str]) -> str:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in entries.items():
            archive.writestr(path, content)
    return _b64_bytes(buffer.getvalue())


def _tiny_png_b64() -> str:
    return "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO2s7gAAAABJRU5ErkJggg=="


def test_plano_sai_do_anexo_produzido():
    """O formato da entrega é o do arquivo que voltou da ferramenta."""
    casos = {
        "pdf": ("document", "pdf"), "xlsx": ("spreadsheet", "xlsx"), "csv": ("spreadsheet", "csv"),
        "pptx": ("presentation", "pptx"), "svg": ("diagram", "svg"), "html": ("document", "html"),
        "excalidraw": ("diagram", "excalidraw"), "chart_json": ("analysis", "chart"),
    }
    for tipo, (natureza, formato) in casos.items():
        plano = plan_artifact_request({"type": tipo})
        assert (plano["artifact_kind"], plano["preferred_format"]) == (natureza, formato)
        assert plano["delivery_mode"] == "attachment"


def test_sem_anexo_a_entrega_e_o_texto():
    """Sem arquivo produzido, não há formato a presumir: a resposta é o texto."""
    for anexo in (None, {}, {"type": "formato-desconhecido"}):
        plano = plan_artifact_request(anexo)
        assert plano["preferred_format"] == "markdown"
        assert plano["delivery_mode"] == "inline"


def test_plano_nao_le_o_pedido():
    """Pedido em qualquer língua ou com erro de digitação recebe o mesmo
    tratamento: o planejador nem recebe a mensagem."""
    import inspect

    assert "user_message" not in inspect.signature(plan_artifact_request).parameters
    assert not inspect.signature(build_artifact_prompt).parameters


def test_artifact_prompt_guides_svg_layout_helper():
    prompt = build_artifact_prompt()

    assert "save_svg_diagram" in prompt
    assert "layout='flow'" in prompt
    assert "nao nomes de ferramentas" in prompt
    assert "Escolha o layout" in prompt


def test_artifact_prompt_nao_declara_formato():
    prompt = build_artifact_prompt()
    assert "preferred_format:" not in prompt
    assert "incluindo negacoes" in prompt
    assert "sem resultado real" in prompt


def test_artifact_prompt_aponta_as_skills_de_design():
    """A escolha da skill de design é do modelo; o contrato só diz onde ela está."""
    assert "skills tem as de design" in build_artifact_prompt()


def test_custom_html_prompt_allows_local_script_without_external_network():
    prompt = build_artifact_prompt()

    assert "JavaScript local/inline" in prompt
    assert "sem <script>" not in prompt
    assert "sem fetch" in prompt
    assert "bibliotecas CDN" in prompt


def test_artifact_validation_contract_for_pdf_attachment():
    validation = validate_artifact({
        "type": "pdf",
        "filename": "relatorio.pdf",
        "mime_type": "application/pdf",
        "content_base64": _b64_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"),
    })

    assert validation["status"] == "ok"
    assert validation["downloadable_artifact"] is True
    assert validation["preview_available"] is False
    assert "content_base64" in validation["checks_run"]
    assert "pdf_signature" in validation["checks_run"]


def test_artifact_validation_detects_invalid_pdf_signature():
    validation = validate_artifact({
        "type": "pdf",
        "filename": "quebrado.pdf",
        "mime_type": "application/pdf",
        "content_base64": _b64_bytes(b"not a pdf"),
    })

    assert validation["status"] == "error"
    assert "missing pdf signature" in validation["errors"]


def test_artifact_validation_checks_xlsx_structure():
    validation = validate_artifact({
        "type": "xlsx",
        "filename": "dados.xlsx",
        "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "content_base64": _office_package({
            "[Content_Types].xml": "<Types/>",
            "xl/workbook.xml": "<workbook/>",
            "xl/worksheets/sheet1.xml": "<worksheet/>",
        }),
    })

    assert validation["status"] == "ok"
    assert "zip_open" in validation["checks_run"]
    assert "office_content_types" in validation["checks_run"]
    assert "xlsx_workbook" in validation["checks_run"]


def test_artifact_validation_detects_invalid_xlsx_structure():
    validation = validate_artifact({
        "type": "xlsx",
        "filename": "dados.xlsx",
        "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "content_base64": _office_package({
            "[Content_Types].xml": "<Types/>",
            "docProps/core.xml": "<core/>",
        }),
    })

    assert validation["status"] == "error"
    assert "missing xlsx workbook" in validation["errors"]


def test_artifact_validation_checks_pptx_structure():
    validation = validate_artifact({
        "type": "pptx",
        "filename": "deck.pptx",
        "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "content_base64": _office_package({
            "[Content_Types].xml": "<Types/>",
            "ppt/presentation.xml": "<presentation/>",
            "ppt/slides/slide1.xml": "<slide/>",
        }),
    })

    assert validation["status"] == "ok"
    assert "zip_open" in validation["checks_run"]
    assert "office_content_types" in validation["checks_run"]
    assert "pptx_presentation" in validation["checks_run"]


def test_artifact_validation_warns_for_csv_without_delimiter():
    validation = validate_artifact({
        "type": "csv",
        "filename": "dados.csv",
        "mime_type": "text/csv",
        "content_base64": _b64("apenas texto"),
    })

    assert validation["status"] == "warning"
    assert "csv payload missing delimiter" in validation["errors"]


def test_artifact_validation_checks_csv_shape():
    validation = validate_artifact({
        "type": "csv",
        "filename": "dados.csv",
        "mime_type": "text/csv",
        "content_base64": _b64("mes,valor\njan,10\nfev,20"),
    })

    assert validation["status"] == "ok"
    assert "utf8_csv" in validation["checks_run"]
    assert "csv_delimiter" in validation["checks_run"]
    assert "csv_rows" in validation["checks_run"]


def test_artifact_validation_checks_chart_payload_contract():
    validation = validate_artifact({
        "type": "chart_json",
        "filename": "grafico.png",
        "mime_type": "image/png",
        "content_base64": _tiny_png_b64(),
        "chart_data": {
            "type": "line",
            "data": {
                "labels": ["jan", "fev"],
                "datasets": [{"label": "Medida", "data": [10, 20]}],
            },
        },
    })

    assert validation["status"] == "ok"
    assert validation["preview_available"] is True
    assert "chart_payload" in validation["checks_run"]
    assert "chart_type" in validation["checks_run"]
    assert "chart_datasets" in validation["checks_run"]
    assert "png_open" in validation["checks_run"]
    assert "png_dimensions" in validation["checks_run"]


def test_artifact_validation_warns_for_chart_payload_without_datasets():
    validation = validate_artifact({
        "type": "chart_json",
        "filename": "grafico.png",
        "mime_type": "image/png",
        "content_base64": _tiny_png_b64(),
        "chart_data": {
            "type": "line",
            "data": {
                "labels": ["jan", "fev"],
            },
        },
    })

    assert validation["status"] == "warning"
    assert "chart payload missing datasets" in validation["errors"]


def test_artifact_validation_checks_png_dimensions():
    validation = validate_artifact({
        "type": "png",
        "filename": "preview.png",
        "mime_type": "image/png",
        "content_base64": _tiny_png_b64(),
    })

    assert validation["status"] == "ok"
    assert "png_open" in validation["checks_run"]
    assert "png_dimensions" in validation["checks_run"]


def test_artifact_validation_detects_invalid_png_bytes():
    validation = validate_artifact({
        "type": "png",
        "filename": "preview.png",
        "mime_type": "image/png",
        "content_base64": _b64_bytes(b"not a png"),
    })

    assert validation["status"] == "error"
    assert "invalid png payload" in validation["errors"][0]


def test_artifact_validation_detects_invalid_excalidraw_payload():
    validation = validate_artifact({
        "type": "excalidraw",
        "filename": "fluxo.excalidraw",
        "mime_type": "application/json",
        "content_base64": "e30=",
    })

    assert validation["status"] == "error"
    assert validation["downloadable_artifact"] is True
    assert validation["errors"]


def test_artifact_validation_checks_html_structure():
    validation = validate_artifact({
        "type": "html",
        "filename": "painel.html",
        "mime_type": "text/html",
        "content_base64": _b64("<!doctype html><html><body><h1>ok</h1></body></html>"),
    })

    assert validation["status"] == "ok"
    assert validation["preview_available"] is True
    assert "utf8_html" in validation["checks_run"]
    assert "html_root" in validation["checks_run"]
    assert "html_body" in validation["checks_run"]


def test_artifact_validation_merges_optional_html_render_verification(monkeypatch):
    monkeypatch.setattr(
        "sentury.artifacts.validation.verify_render_preview",
        lambda artifact_type, payload: {
            "status": "ok",
            "checks_run": ["html_browser_render"],
            "preview_available": True,
            "preview_content_base64": _tiny_png_b64(),
            "preview_mime_type": "image/png",
            "preview_filename": "painel.verified.png",
            "errors": [],
        },
    )

    attachment = {
        "type": "html",
        "filename": "painel.html",
        "mime_type": "text/html",
        "content_base64": _b64("<!doctype html><html><body><h1>ok</h1></body></html>"),
    }
    validation = validate_artifact(attachment)

    assert validation["status"] == "ok"
    assert "html_browser_render" in validation["checks_run"]
    assert attachment["verified_preview_base64"] == _tiny_png_b64()
    assert attachment["verified_preview_mime_type"] == "image/png"
    assert attachment["verified_preview_filename"] == "painel.verified.png"


def test_artifact_validation_warns_for_html_without_body():
    validation = validate_artifact({
        "type": "html",
        "filename": "fragmento.html",
        "mime_type": "text/html",
        "content_base64": _b64("<div>ok</div>"),
    })

    assert validation["status"] == "warning"
    assert "missing <body tag" in validation["errors"]


def test_artifact_validation_checks_svg_structure_and_viewbox():
    validation = validate_artifact({
        "type": "svg",
        "filename": "fluxo.svg",
        "mime_type": "image/svg+xml",
        "content_base64": _b64('<svg viewBox="0 0 100 100"><rect width="20" height="20"/></svg>'),
    })

    assert validation["status"] == "ok"
    assert validation["preview_available"] is True
    assert "utf8_svg" in validation["checks_run"]
    assert "svg_root" in validation["checks_run"]
    assert "svg_viewbox" in validation["checks_run"]


def test_artifact_validation_escalates_when_svg_render_verifier_warns(monkeypatch):
    monkeypatch.setattr(
        "sentury.artifacts.validation.verify_render_preview",
        lambda artifact_type, payload: {
            "status": "warning",
            "checks_run": ["svg_browser_render"],
            "preview_available": True,
            "errors": ["svg render overflow"],
        },
    )

    validation = validate_artifact({
        "type": "svg",
        "filename": "fluxo.svg",
        "mime_type": "image/svg+xml",
        "content_base64": _b64('<svg viewBox="0 0 100 100"><rect width="20" height="20"/></svg>'),
    })

    assert validation["status"] == "warning"
    assert "svg_browser_render" in validation["checks_run"]
    assert "svg render overflow" in validation["errors"]


def test_artifact_validation_warns_for_svg_without_sizing():
    validation = validate_artifact({
        "type": "svg",
        "filename": "solto.svg",
        "mime_type": "image/svg+xml",
        "content_base64": _b64("<svg><rect/></svg>"),
    })

    assert validation["status"] == "warning"
    assert "missing sizing hints" in validation["errors"]
