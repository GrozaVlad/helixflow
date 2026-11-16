from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite


@dataclass(frozen=True, slots=True)
class JobFeatures:
    """Static features available before a job is admitted to a GPU."""

    job_type: str
    total_residues: int
    max_chain_length: int
    protein_chains: int = 1
    ligand_count: int = 0
    ligand_atoms: int = 0
    msa_depth: int = 0
    estimated_tokens: int = 0
    input_bytes: int = 0
    recycling_steps: int = 3
    sampling_steps: int = 200
    diffusion_samples: int = 1

    def __post_init__(self) -> None:
        numeric = (
            self.total_residues,
            self.max_chain_length,
            self.protein_chains,
            self.ligand_count,
            self.ligand_atoms,
            self.msa_depth,
            self.estimated_tokens,
            self.input_bytes,
        )
        if not self.job_type:
            raise ValueError("job_type is required")
        if any(value < 0 for value in numeric):
            raise ValueError("job features cannot be negative")


@dataclass(frozen=True, slots=True)
class RuntimePrediction:
    """Resource estimates; calibration and validity depend on prediction provenance."""

    runtime_p50_seconds: float
    runtime_p90_seconds: float
    memory_p90_gib: float

    def __post_init__(self) -> None:
        if not all(isfinite(value) for value in (
            self.runtime_p50_seconds, self.runtime_p90_seconds, self.memory_p90_gib
        )):
            raise ValueError("predictions must be finite")
        if self.runtime_p50_seconds <= 0:
            raise ValueError("runtime_p50_seconds must be positive")
        if self.runtime_p90_seconds < self.runtime_p50_seconds:
            raise ValueError("runtime p90 cannot be below p50")
        if self.memory_p90_gib <= 0:
            raise ValueError("memory_p90_gib must be positive")


@dataclass(frozen=True, slots=True)
class SchedulingJob:
    """A durable GPU-ready job; policies may order it but never discard it."""

    job_id: str
    owner_id: str
    submitted_at: float
    features: JobFeatures
    prediction: RuntimePrediction
    actual_runtime_seconds: float
    actual_peak_memory_gib: float

    def __post_init__(self) -> None:
        if not self.job_id or not self.owner_id:
            raise ValueError("job_id and owner_id are required")
        if not all(isfinite(value) for value in (
            self.submitted_at, self.actual_runtime_seconds, self.actual_peak_memory_gib
        )):
            raise ValueError("job timing and memory values must be finite")
        if self.submitted_at < 0:
            raise ValueError("submitted_at cannot be negative")
        if self.actual_runtime_seconds <= 0 or self.actual_peak_memory_gib <= 0:
            raise ValueError("actual runtime and memory must be positive")


@dataclass(frozen=True, slots=True)
class GPUDevice:
    gpu_id: str
    memory_gib: float
    speed_factor: float = 1.0

    def __post_init__(self) -> None:
        if not self.gpu_id:
            raise ValueError("gpu_id is required")
        if not all(isfinite(value) for value in (self.memory_gib, self.speed_factor)):
            raise ValueError("GPU memory and speed_factor must be finite")
        if self.memory_gib <= 0 or self.speed_factor <= 0:
            raise ValueError("GPU memory and speed_factor must be positive")


@dataclass(frozen=True, slots=True)
class Assignment:
    job_id: str
    owner_id: str
    gpu_id: str
    submitted_at: float
    started_at: float
    finished_at: float
    predicted_runtime_p90_seconds: float
    actual_peak_memory_gib: float

    @property
    def waiting_seconds(self) -> float:
        return self.started_at - self.submitted_at

    @property
    def flow_seconds(self) -> float:
        return self.finished_at - self.submitted_at

    @property
    def service_seconds(self) -> float:
        return self.finished_at - self.started_at


@dataclass(frozen=True, slots=True)
class SimulationMetrics:
    completed_jobs: int
    mean_flow_seconds: float
    p95_flow_seconds: float
    mean_waiting_seconds: float
    makespan_seconds: float
    gpu_utilization: float
    jain_fairness: float
    starvation_count: int
    owner_service_seconds: dict[str, float] = field(default_factory=dict)
