from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from pydantic import BaseModel, Field


class SchedulingPrediction(BaseModel):
    schema_version: str = "1.0"
    runtime_p50_seconds: float = Field(gt=0)
    runtime_p90_seconds: float = Field(gt=0)
    memory_p90_gib: float = Field(gt=0)
    predictor_version: str


class SchedulingDecision(BaseModel):
    policy: str
    share_identifier: str
    scheduling_priority: int = Field(ge=0, le=9999)
    prediction: SchedulingPrediction | None = None
    fallback_reason: str | None = None


def share_identifier(owner_id: str) -> str:
    """Return a privacy-preserving AWS Batch fair-share identifier."""

    prefix = re.sub(r"[^A-Za-z0-9]", "", owner_id)[:12] or "researcher"
    digest = hashlib.sha256(owner_id.encode()).hexdigest()[:16]
    return f"{prefix}-{digest}"


def priority_from_runtime(runtime_p90_seconds: float) -> int:
    """Map conservative runtime to [1, 9999], where shorter jobs rank higher."""

    if not math.isfinite(runtime_p90_seconds) or runtime_p90_seconds <= 0:
        raise ValueError("runtime_p90_seconds must be finite and positive")
    priority = round(9999 / (1 + runtime_p90_seconds / 60))
    return max(1, min(9999, priority))


def decide(owner_id: str, prepared_manifest: dict[str, Any]) -> SchedulingDecision:
    raw_prediction = prepared_manifest.get("scheduling_prediction")
    if raw_prediction is None:
        return SchedulingDecision(
            policy="fcfs-fallback",
            share_identifier=share_identifier(owner_id),
            scheduling_priority=1,
            fallback_reason="prepared manifest has no scheduling prediction",
        )
    prediction = SchedulingPrediction.model_validate(raw_prediction)
    return SchedulingDecision(
        policy="uaf-sjf-aws-batch",
        share_identifier=share_identifier(owner_id),
        scheduling_priority=priority_from_runtime(prediction.runtime_p90_seconds),
        prediction=prediction,
    )
