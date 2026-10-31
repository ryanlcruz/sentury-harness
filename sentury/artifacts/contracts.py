from __future__ import annotations

from typing import List, Literal, TypedDict


ArtifactStatus = Literal["ok", "warning", "error", "skipped"]


class _ArtifactPlanRequired(TypedDict):
    artifact_kind: str
    preferred_format: str
    generator: str
    validator: str
    delivery_mode: str


class ArtifactPlan(_ArtifactPlanRequired, total=False):
    layout_hint: str
    presentation_style: str


class ArtifactValidationResult(TypedDict):
    status: ArtifactStatus
    checks_run: List[str]
    preview_available: bool
    downloadable_artifact: bool
    errors: List[str]
