from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def a3m_depth(paths: list[Path]) -> int:
    depths = []
    for path in paths:
        if path.suffix.lower() != ".a3m" or not path.is_file():
            continue
        depths.append(
            sum(line.startswith(">") for line in path.read_text(encoding="utf-8").splitlines())
        )
    return max(depths, default=0)


def attach_scheduling_prediction(
    s3: Any,
    bucket: str,
    source: Path,
    manifest: dict[str, Any],
    msa_paths: list[Path],
    workdir: Path,
) -> dict[str, Any]:
    """Attach a server-generated prediction when a trusted model is configured."""

    model_key = os.environ.get("SCHEDULER_MODEL_S3_KEY")
    if not model_key:
        return manifest

    from scheduling.features import extract_features
    from scheduling.predictor import PredictorBundle

    model_path = workdir / "scheduler-predictor.pkl"
    s3.download_file(bucket, model_key, str(model_path))
    features = extract_features(
        source,
        options=manifest.get("options"),
        msa_depth_override=a3m_depth(msa_paths),
    )
    prediction = PredictorBundle.load(model_path).predict(features)
    manifest["scheduling_prediction"] = {
        "schema_version": "1.0",
        "runtime_p50_seconds": prediction.runtime_p50_seconds,
        "runtime_p90_seconds": prediction.runtime_p90_seconds,
        "memory_p90_gib": prediction.memory_p90_gib,
        "predictor_version": os.environ.get("SCHEDULER_MODEL_VERSION", model_key),
    }
    return manifest
