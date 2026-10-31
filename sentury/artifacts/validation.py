from __future__ import annotations

import base64
import io
import json
from typing import Optional
import zipfile

from .contracts import ArtifactValidationResult
from .render_verifier import verify_render_preview


def empty_validation_result() -> ArtifactValidationResult:
    return {
        "status": "skipped",
        "checks_run": [],
        "preview_available": False,
        "downloadable_artifact": False,
        "errors": [],
    }


def _escalate_status(current: str, new_status: str) -> str:
    order = {"ok": 0, "warning": 1, "broken": 2, "error": 2, "skipped": -1}
    return new_status if order.get(new_status, 0) > order.get(current, 0) else current


def _validate_office_package(
    result: ArtifactValidationResult,
    decoded_bytes: bytes,
    *,
    required_path: str,
    required_check: str,
    missing_error: str,
) -> ArtifactValidationResult:
    try:
        with zipfile.ZipFile(io.BytesIO(decoded_bytes)) as archive:
            names = set(archive.namelist())
    except Exception as exc:
        result["status"] = "error"
        result["errors"].append(f"invalid office package: {exc}")
        return result

    result["checks_run"].append("zip_open")

    if "[Content_Types].xml" in names:
        result["checks_run"].append("office_content_types")
    else:
        result["status"] = _escalate_status(result["status"], "error")
        result["errors"].append("missing office content types")

    if required_path in names:
        result["checks_run"].append(required_check)
    else:
        result["status"] = _escalate_status(result["status"], "error")
        result["errors"].append(missing_error)

    return result


def _merge_render_verification(
    result: ArtifactValidationResult,
    artifact_type: str,
    decoded_bytes: bytes,
    attachment: Optional[dict] = None,
) -> ArtifactValidationResult:
    render_result = verify_render_preview(artifact_type, decoded_bytes)
    if not render_result:
        return result

    result["checks_run"].extend(render_result.get("checks_run", []))
    result["preview_available"] = result["preview_available"] or render_result.get("preview_available", False)
    result["status"] = _escalate_status(result["status"], render_result.get("status", "ok"))
    result["errors"].extend(render_result.get("errors", []))
    if attachment and render_result.get("preview_content_base64"):
        attachment["verified_preview_base64"] = render_result["preview_content_base64"]
        attachment["verified_preview_mime_type"] = render_result.get("preview_mime_type", "image/png")
        if render_result.get("preview_filename"):
            attachment["verified_preview_filename"] = render_result["preview_filename"]
        if render_result.get("preview_source"):
            attachment["verified_preview_source"] = render_result["preview_source"]
    return result


def _validate_png_payload(
    result: ArtifactValidationResult,
    decoded_bytes: bytes,
) -> ArtifactValidationResult:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(decoded_bytes)) as image:
            width, height = image.size
            image_format = (image.format or "").upper()
    except Exception as exc:
        result["status"] = _escalate_status(result["status"], "error")
        result["errors"].append(f"invalid png payload: {exc}")
        return result

    if image_format == "PNG":
        result["checks_run"].append("png_open")
    else:
        result["status"] = _escalate_status(result["status"], "error")
        result["errors"].append(f"invalid png payload: expected PNG, got {image_format or 'unknown'}")
        return result

    if width > 0 and height > 0:
        result["checks_run"].append("png_dimensions")
    else:
        result["status"] = _escalate_status(result["status"], "warning")
        result["errors"].append("png has empty dimensions")

    return result


def validate_artifact(attachment: Optional[dict]) -> ArtifactValidationResult:
    if not attachment:
        return empty_validation_result()

    result: ArtifactValidationResult = {
        "status": "ok",
        "checks_run": [],
        "preview_available": False,
        "downloadable_artifact": bool(attachment.get("content_base64") or attachment.get("content")),
        "errors": [],
    }

    artifact_type = str(attachment.get("type") or "").lower().strip()
    content_base64 = attachment.get("content_base64")
    decoded_bytes = b""

    if content_base64:
        result["checks_run"].append("content_base64")
        try:
            decoded_bytes = base64.b64decode(content_base64, validate=False)
        except Exception as exc:
            result["status"] = "error"
            result["errors"].append(f"base64 decode failed: {exc}")
            return result

    if artifact_type == "chart_json":
        result["preview_available"] = True
        result["checks_run"].append("chart_payload")
        chart_data = attachment.get("chart_data") or {}
        chart_type = chart_data.get("type")
        chart_payload = chart_data.get("data") or {}
        labels = chart_payload.get("labels")
        datasets = chart_payload.get("datasets")

        if chart_type:
            result["checks_run"].append("chart_type")
        else:
            result["status"] = _escalate_status(result["status"], "warning")
            result["errors"].append("chart payload missing type")

        if isinstance(labels, list):
            result["checks_run"].append("chart_labels")
        else:
            result["status"] = _escalate_status(result["status"], "warning")
            result["errors"].append("chart payload missing labels")

        if isinstance(datasets, list) and datasets:
            result["checks_run"].append("chart_datasets")
        else:
            result["status"] = _escalate_status(result["status"], "warning")
            result["errors"].append("chart payload missing datasets")
        if decoded_bytes:
            result = _validate_png_payload(result, decoded_bytes)
        return result

    if artifact_type in {"pdf", "xlsx", "csv", "pptx", "png"}:
        if not decoded_bytes:
            result["status"] = "error"
            result["errors"].append("binary payload missing")
            return result

        if artifact_type == "pdf":
            if decoded_bytes.startswith(b"%PDF-"):
                result["checks_run"].append("pdf_signature")
            else:
                result["status"] = _escalate_status(result["status"], "error")
                result["errors"].append("missing pdf signature")
                return result

            if b"%%EOF" in decoded_bytes[-64:]:
                result["checks_run"].append("pdf_eof")
            else:
                result["status"] = _escalate_status(result["status"], "warning")
                result["errors"].append("missing pdf eof marker")
            return result

        if artifact_type == "xlsx":
            return _validate_office_package(
                result,
                decoded_bytes,
                required_path="xl/workbook.xml",
                required_check="xlsx_workbook",
                missing_error="missing xlsx workbook",
            )

        if artifact_type == "pptx":
            return _validate_office_package(
                result,
                decoded_bytes,
                required_path="ppt/presentation.xml",
                required_check="pptx_presentation",
                missing_error="missing pptx presentation",
            )

        if artifact_type == "png":
            return _validate_png_payload(result, decoded_bytes)

        if artifact_type == "csv":
            try:
                csv_text = decoded_bytes.decode("utf-8")
            except Exception as exc:
                result["status"] = "error"
                result["errors"].append(f"csv decode failed: {exc}")
                return result

            result["checks_run"].append("utf8_csv")
            rows = [line for line in csv_text.splitlines() if line.strip()]
            if rows:
                result["checks_run"].append("csv_rows")
            else:
                result["status"] = _escalate_status(result["status"], "warning")
                result["errors"].append("csv payload has no rows")

            if any(delimiter in csv_text for delimiter in (",", ";", "\t")):
                result["checks_run"].append("csv_delimiter")
            else:
                result["status"] = _escalate_status(result["status"], "warning")
                result["errors"].append("csv payload missing delimiter")
            return result

        return result

    if artifact_type == "html":
        result["preview_available"] = True
        try:
            html_text = decoded_bytes.decode("utf-8")
        except Exception:
            html_text = ""
        result["checks_run"].append("utf8_html")
        html_lower = html_text.lower()
        if html_text and "<" not in html_text:
            result["status"] = _escalate_status(result["status"], "warning")
            result["errors"].append("html payload has no tags")
            return result
        if "<html" in html_lower:
            result["checks_run"].append("html_root")
        else:
            result["status"] = _escalate_status(result["status"], "warning")
            result["errors"].append("missing <html root")
        if "<body" in html_lower:
            result["checks_run"].append("html_body")
        else:
            result["status"] = _escalate_status(result["status"], "warning")
            result["errors"].append("missing <body tag")
        return _merge_render_verification(result, artifact_type, decoded_bytes, attachment)

    if artifact_type == "svg":
        result["preview_available"] = True
        try:
            svg_text = decoded_bytes.decode("utf-8")
        except Exception:
            svg_text = ""
        result["checks_run"].append("utf8_svg")
        svg_lower = svg_text.lower()
        if "<svg" not in svg_lower:
            result["status"] = _escalate_status(result["status"], "error")
            result["errors"].append("missing <svg root")
            return result
        result["checks_run"].append("svg_root")
        if "</svg>" not in svg_lower:
            result["status"] = _escalate_status(result["status"], "error")
            result["errors"].append("missing </svg> close")
        if "viewbox=" in svg_lower:
            result["checks_run"].append("svg_viewbox")
        elif 'width="' in svg_lower and 'height="' in svg_lower:
            result["checks_run"].append("svg_dimensions")
        else:
            result["status"] = _escalate_status(result["status"], "warning")
            result["errors"].append("missing sizing hints")
        return _merge_render_verification(result, artifact_type, decoded_bytes, attachment)

    if artifact_type == "excalidraw":
        try:
            payload = json.loads(decoded_bytes.decode("utf-8"))
            result["checks_run"].append("json_parse")
        except Exception as exc:
            result["status"] = "error"
            result["errors"].append(f"invalid json: {exc}")
            return result
        if payload.get("type") != "excalidraw" or not isinstance(payload.get("elements"), list):
            result["status"] = "error"
            result["errors"].append("missing excalidraw envelope")
        return result

    if artifact_type == "ascii":
        result["checks_run"].append("plain_text")
        return result

    return result


def validate_delivery(attachment: Optional[dict]) -> ArtifactValidationResult:
    """Confere o anexo que o turno produziu; sem anexo não há o que conferir."""
    if attachment:
        return validate_artifact(attachment)
    return empty_validation_result()
