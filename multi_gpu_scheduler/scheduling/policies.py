from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import GPUDevice, SchedulingJob


@dataclass(frozen=True, slots=True)
class Decision:
    job_id: str
    gpu_id: str


class SchedulingPolicy(Protocol):
    name: str

    def choose(
        self,
        waiting: list[SchedulingJob],
        idle_gpus: list[GPUDevice],
        now: float,
        owner_service_seconds: dict[str, float],
    ) -> Decision | None: ...


def _feasible(job: SchedulingJob, gpu: GPUDevice, memory_safety_fraction: float) -> bool:
    return job.prediction.memory_p90_gib <= gpu.memory_gib * memory_safety_fraction


class _OrderedPolicy:
    name = "ordered"

    def __init__(self, memory_safety_fraction: float = 0.9) -> None:
        if not 0 < memory_safety_fraction <= 1:
            raise ValueError("memory_safety_fraction must be in (0, 1]")
        self.memory_safety_fraction = memory_safety_fraction

    def job_key(self, job: SchedulingJob) -> tuple[float, ...]:
        raise NotImplementedError

    def choose(
        self,
        waiting: list[SchedulingJob],
        idle_gpus: list[GPUDevice],
        now: float,
        owner_service_seconds: dict[str, float],
    ) -> Decision | None:
        del now, owner_service_seconds
        for job in sorted(waiting, key=lambda item: (*self.job_key(item), item.submitted_at)):
            compatible = [
                gpu
                for gpu in idle_gpus
                if _feasible(job, gpu, self.memory_safety_fraction)
            ]
            if compatible:
                gpu = min(
                    compatible,
                    key=lambda item: job.prediction.runtime_p50_seconds / item.speed_factor,
                )
                return Decision(job.job_id, gpu.gpu_id)
        return None


class FCFSPolicy(_OrderedPolicy):
    name = "fcfs"

    def job_key(self, job: SchedulingJob) -> tuple[float, ...]:
        return (job.submitted_at,)


class TokenSJFPolicy(_OrderedPolicy):
    name = "token_sjf"

    def job_key(self, job: SchedulingJob) -> tuple[float, ...]:
        return (float(job.features.estimated_tokens),)


class PredictedMedianSJFPolicy(_OrderedPolicy):
    name = "predicted_sjf"

    def job_key(self, job: SchedulingJob) -> tuple[float, ...]:
        return (job.prediction.runtime_p50_seconds,)


class OracleSJFPolicy(_OrderedPolicy):
    name = "oracle_sjf"

    def job_key(self, job: SchedulingJob) -> tuple[float, ...]:
        return (job.actual_runtime_seconds,)


class FairServicePolicy(_OrderedPolicy):
    """Least-accounted-service owner first, then FIFO; not AWS Batch fair-share."""

    name = "fair_service"

    def choose(self, waiting, idle_gpus, now, owner_service_seconds):
        del now
        pairs = [
            (job, gpu) for job in waiting for gpu in idle_gpus
            if _feasible(job, gpu, self.memory_safety_fraction)
        ]
        if not pairs:
            return None
        job, gpu = min(pairs, key=lambda pair: (
            owner_service_seconds.get(pair[0].owner_id, 0),
            pair[0].submitted_at, pair[0].job_id,
            pair[0].prediction.runtime_p90_seconds / pair[1].speed_factor,
        ))
        return Decision(job.job_id, gpu.gpu_id)


class UncertaintyAwareFairSJF:
    """Risk-aware SJF with compatible-job aging and predicted-memory filtering."""

    name = "uaf_sjf"

    def __init__(
        self,
        starvation_threshold_seconds: float,
        memory_safety_fraction: float = 0.9,
        fairness_weight: float = 0.25,
    ) -> None:
        if starvation_threshold_seconds <= 0:
            raise ValueError("starvation_threshold_seconds must be positive")
        if not 0 < memory_safety_fraction <= 1:
            raise ValueError("memory_safety_fraction must be in (0, 1]")
        if fairness_weight < 0:
            raise ValueError("fairness_weight cannot be negative")
        self.starvation_threshold_seconds = starvation_threshold_seconds
        self.memory_safety_fraction = memory_safety_fraction
        self.fairness_weight = fairness_weight

    def choose(
        self,
        waiting: list[SchedulingJob],
        idle_gpus: list[GPUDevice],
        now: float,
        owner_service_seconds: dict[str, float],
    ) -> Decision | None:
        feasible_pairs = [
            (job, gpu)
            for job in waiting
            for gpu in idle_gpus
            if _feasible(job, gpu, self.memory_safety_fraction)
        ]
        if not feasible_pairs:
            return None

        urgent_ids = {
            job.job_id
            for job, _gpu in feasible_pairs
            if now - job.submitted_at >= self.starvation_threshold_seconds
        }
        if urgent_ids:
            feasible_pairs = [pair for pair in feasible_pairs if pair[0].job_id in urgent_ids]
            job, gpu = min(
                feasible_pairs,
                key=lambda pair: (
                    pair[0].submitted_at,
                    pair[0].prediction.runtime_p90_seconds / pair[1].speed_factor,
                    pair[0].job_id,
                ),
            )
            return Decision(job.job_id, gpu.gpu_id)

        owners_waiting = {job.owner_id for job in waiting}
        minimum_service = min(owner_service_seconds.get(owner, 0.0) for owner in owners_waiting)

        def score(pair: tuple[SchedulingJob, GPUDevice]) -> tuple[float, float, str]:
            job, gpu = pair
            risk_adjusted_runtime = job.prediction.runtime_p90_seconds / gpu.speed_factor
            service_lead = owner_service_seconds.get(job.owner_id, 0.0) - minimum_service
            return (
                risk_adjusted_runtime + self.fairness_weight * service_lead,
                job.submitted_at,
                job.job_id,
            )

        job, gpu = min(feasible_pairs, key=score)
        return Decision(job.job_id, gpu.gpu_id)


POLICIES = ("fcfs", "token_sjf", "predicted_sjf", "fair_service", "uaf_sjf", "oracle_sjf")


def make_policy(
    name: str,
    *,
    starvation_threshold_seconds: float = 3600,
    memory_safety_fraction: float = 0.9,
    fairness_weight: float = 0.25,
) -> SchedulingPolicy:
    common = {"memory_safety_fraction": memory_safety_fraction}
    if name == "fcfs":
        return FCFSPolicy(**common)
    if name == "token_sjf":
        return TokenSJFPolicy(**common)
    if name == "predicted_sjf":
        return PredictedMedianSJFPolicy(**common)
    if name == "oracle_sjf":
        return OracleSJFPolicy(**common)
    if name == "fair_service":
        return FairServicePolicy(**common)
    if name == "uaf_sjf":
        return UncertaintyAwareFairSJF(
            starvation_threshold_seconds=starvation_threshold_seconds,
            fairness_weight=fairness_weight,
            **common,
        )
    raise ValueError(f"unknown scheduling policy: {name}")
