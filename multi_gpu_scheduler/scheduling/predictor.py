from __future__ import annotations

import math
import pickle
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from .models import JobFeatures, RuntimePrediction

JOB_TYPES = ("monomer", "protein_complex", "protein_ligand")


def feature_vector(features: JobFeatures) -> list[float]:
    tokens = features.estimated_tokens
    return [
        float(features.total_residues),
        float(features.max_chain_length),
        float(features.protein_chains),
        float(features.ligand_count),
        float(features.ligand_atoms),
        float(features.msa_depth),
        float(tokens),
        float(tokens**2),
        float(tokens * features.msa_depth),
        float(features.input_bytes),
        float(features.recycling_steps),
        float(features.sampling_steps),
        float(features.diffusion_samples),
        *(1.0 if features.job_type == job_type else 0.0 for job_type in JOB_TYPES),
    ]


@dataclass(frozen=True, slots=True)
class TrainingObservation:
    job_id: str
    features: JobFeatures
    runtime_seconds: float
    peak_memory_gib: float
    biological_group_id: str = ""
    split: str = ""
    hardware: str = ""
    benchmark_sha256: str = ""

    def __post_init__(self) -> None:
        if not self.job_id:
            raise ValueError("job_id is required")
        if any(
            not math.isfinite(v) or v <= 0 for v in (self.runtime_seconds, self.peak_memory_gib)
        ):
            raise ValueError("training labels must be positive")


@dataclass(slots=True)
class PredictorBundle:
    runtime_p50_model: HistGradientBoostingRegressor
    runtime_p90_model: HistGradientBoostingRegressor
    memory_p90_model: HistGradientBoostingRegressor
    runtime_calibration_seconds: float
    memory_calibration_gib: float
    training_job_ids: tuple[str, ...]
    provenance: dict | None = None

    def predict(self, features: JobFeatures) -> RuntimePrediction:
        matrix = np.asarray([feature_vector(features)], dtype=float)
        runtime_p50 = max(0.001, float(self.runtime_p50_model.predict(matrix)[0]))
        runtime_p90 = float(self.runtime_p90_model.predict(matrix)[0])
        memory_p90 = float(self.memory_p90_model.predict(matrix)[0])
        return RuntimePrediction(
            runtime_p50_seconds=runtime_p50,
            runtime_p90_seconds=max(runtime_p50, runtime_p90 + self.runtime_calibration_seconds),
            memory_p90_gib=max(0.001, memory_p90 + self.memory_calibration_gib),
        )

    def save(self, path: Path) -> None:
        path.write_bytes(pickle.dumps(self, protocol=pickle.HIGHEST_PROTOCOL))

    @classmethod
    def load(cls, path: Path) -> PredictorBundle:
        value = pickle.loads(path.read_bytes())
        if not isinstance(value, cls):
            raise TypeError("file does not contain a PredictorBundle")
        return value


@dataclass(frozen=True, slots=True)
class TrainingResult:
    predictor: PredictorBundle
    calibration_job_ids: tuple[str, ...]
    runtime_p50_mae_seconds: float
    runtime_p90_coverage: float
    memory_p90_coverage: float


def _quantile_model(quantile: float, seed: int, sample_count: int):
    return HistGradientBoostingRegressor(
        loss="quantile",
        quantile=quantile,
        learning_rate=0.06,
        max_iter=250,
        max_leaf_nodes=15,
        min_samples_leaf=max(2, min(10, sample_count // 8)),
        l2_regularization=0.1,
        random_state=seed,
    )


def _upper_conformal_offset(actual: np.ndarray, predicted: np.ndarray, coverage: float) -> float:
    residuals = actual - predicted
    rank = min(len(residuals), math.ceil((len(residuals) + 1) * coverage))
    return float(np.sort(residuals)[rank - 1])


def train_predictor(
    observations: list[TrainingObservation],
    *,
    calibration_fraction: float = 0.2,
    coverage: float = 0.9,
    seed: int = 42,
    explicit_splits: bool = False,
) -> TrainingResult:
    """Train grouped quantile models and calibrate upper bounds on unseen job IDs."""

    if not 0.1 <= calibration_fraction <= 0.4:
        raise ValueError("calibration_fraction must be between 0.1 and 0.4")
    if not 0.5 < coverage < 1:
        raise ValueError("coverage must be between 0.5 and 1")
    hardware = {o.hardware for o in observations if o.hardware}
    if len(hardware) > 1:
        raise ValueError("mixed hardware requires a hardware-aware model")
    fingerprints = {o.benchmark_sha256 for o in observations if o.benchmark_sha256}
    if len(fingerprints) > 1:
        raise ValueError("profiles come from different benchmark versions")
    job_partitions = {}
    for item in observations:
        identity = (item.biological_group_id, item.split)
        if job_partitions.setdefault(item.job_id, identity) != identity:
            raise ValueError("job has inconsistent biological group or partition")
    if explicit_splits:
        if any(
            not o.biological_group_id
            or o.split not in {"train", "calibration", "test"}
            or not o.hardware
            or not o.benchmark_sha256
            for o in observations
        ):
            raise ValueError(
                "explicit splits require biological groups, hardware, benchmark hash and valid splits"
            )
        group_splits = {}
        for item in observations:
            previous = group_splits.setdefault(item.biological_group_id, item.split)
            if previous != item.split:
                raise ValueError("biological group crosses partitions")
        if set(group_splits.values()) != {"train", "calibration", "test"}:
            raise ValueError(
                "explicit benchmark profiles require train, calibration and test partitions"
            )
        # Test observations never enter fitting or calibration.
        observations = [o for o in observations if o.split != "test"]
    job_ids = sorted({observation.job_id for observation in observations})
    if len(job_ids) < 10:
        raise ValueError("at least 10 distinct jobs are required")
    groups = sorted({o.biological_group_id or o.job_id for o in observations})
    random.Random(seed).shuffle(groups)
    calibration_groups = set(groups[: max(2, round(len(groups) * calibration_fraction))])
    calibration_ids = {
        o.job_id
        for o in observations
        if (
            o.split == "calibration"
            if explicit_splits
            else (o.biological_group_id or o.job_id) in calibration_groups
        )
    }
    training = [item for item in observations if item.job_id not in calibration_ids]
    calibration = [item for item in observations if item.job_id in calibration_ids]
    if not training or not calibration:
        raise ValueError("training and calibration partitions must both be non-empty")
    calibration_count = len({o.biological_group_id or o.job_id for o in calibration})
    if explicit_splits and math.ceil((calibration_count + 1) * coverage) > calibration_count:
        raise ValueError("too few independent calibration groups for the requested coverage")
    if {o.biological_group_id or o.job_id for o in training} & {
        o.biological_group_id or o.job_id for o in calibration
    }:
        raise ValueError("biological group crosses fitting and calibration")

    train_x = np.asarray([feature_vector(item.features) for item in training], dtype=float)
    train_runtime = np.asarray([item.runtime_seconds for item in training], dtype=float)
    train_memory = np.asarray([item.peak_memory_gib for item in training], dtype=float)
    p50_model = _quantile_model(0.5, seed, len(training)).fit(train_x, train_runtime)
    p90_model = _quantile_model(0.9, seed + 1, len(training)).fit(train_x, train_runtime)
    memory_model = _quantile_model(0.9, seed + 2, len(training)).fit(train_x, train_memory)

    calibration_x = np.asarray([feature_vector(item.features) for item in calibration], dtype=float)
    actual_runtime = np.asarray([item.runtime_seconds for item in calibration], dtype=float)
    actual_memory = np.asarray([item.peak_memory_gib for item in calibration], dtype=float)
    raw_p50 = p50_model.predict(calibration_x)
    raw_p90 = p90_model.predict(calibration_x)
    raw_memory_p90 = memory_model.predict(calibration_x)

    def group_offset(actual, predicted):
        residuals = {}
        for item, residual in zip(calibration, actual - predicted, strict=True):
            group = item.biological_group_id or item.job_id
            residuals[group] = max(residuals.get(group, -math.inf), float(residual))
        values = np.asarray(list(residuals.values()))
        return _upper_conformal_offset(values, np.zeros_like(values), coverage)

    runtime_offset = group_offset(actual_runtime, raw_p90)
    memory_offset = group_offset(actual_memory, raw_memory_p90)
    calibrated_runtime = raw_p90 + runtime_offset
    calibrated_memory = raw_memory_p90 + memory_offset

    bundle = PredictorBundle(
        runtime_p50_model=p50_model,
        runtime_p90_model=p90_model,
        memory_p90_model=memory_model,
        runtime_calibration_seconds=runtime_offset,
        memory_calibration_gib=memory_offset,
        training_job_ids=tuple(sorted(set(job_ids) - calibration_ids)),
        provenance={
            "feature_schema": "submission-features-v1",
            "hardware": sorted(hardware),
            "benchmark_sha256": sorted(fingerprints),
            "grouping": "explicit-biological" if explicit_splits else "group-or-legacy-job-id",
            "training_groups": sorted({o.biological_group_id or o.job_id for o in training}),
            "calibration_groups": sorted({o.biological_group_id or o.job_id for o in calibration}),
            "calibration_unit": "maximum residual per biological group",
        },
    )
    return TrainingResult(
        predictor=bundle,
        calibration_job_ids=tuple(sorted(calibration_ids)),
        runtime_p50_mae_seconds=float(np.mean(np.abs(actual_runtime - raw_p50))),
        runtime_p90_coverage=float(np.mean(actual_runtime <= calibrated_runtime)),
        memory_p90_coverage=float(np.mean(actual_memory <= calibrated_memory)),
    )
