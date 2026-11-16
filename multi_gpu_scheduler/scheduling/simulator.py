from __future__ import annotations

import heapq
import math
from dataclasses import asdict, dataclass

from .models import Assignment, GPUDevice, SchedulingJob, SimulationMetrics
from .policies import SchedulingPolicy


class UnschedulableWorkloadError(RuntimeError):
    """Raised instead of silently dropping jobs that cannot fit available GPUs."""


@dataclass(frozen=True, slots=True)
class SimulationResult:
    policy: str
    assignments: tuple[Assignment, ...]
    metrics: SimulationMetrics

    def as_dict(self) -> dict:
        return {
            "policy": self.policy,
            "metrics": asdict(self.metrics),
            "assignments": [asdict(assignment) for assignment in self.assignments],
        }


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _jain_fairness(values: list[float]) -> float:
    if not values or not any(values):
        return 1.0
    return sum(values) ** 2 / (len(values) * sum(value**2 for value in values))


def simulate(
    jobs: list[SchedulingJob],
    gpus: list[GPUDevice],
    policy: SchedulingPolicy,
    *,
    starvation_threshold_seconds: float,
) -> SimulationResult:
    """Run a deterministic, non-preemptive simulation until every job completes."""

    if not jobs:
        raise ValueError("at least one job is required")
    if not gpus:
        raise ValueError("at least one GPU is required")
    if starvation_threshold_seconds <= 0:
        raise ValueError("starvation_threshold_seconds must be positive")
    if len({job.job_id for job in jobs}) != len(jobs):
        raise ValueError("job_id values must be unique")
    if len({gpu.gpu_id for gpu in gpus}) != len(gpus):
        raise ValueError("gpu_id values must be unique")

    devices = {gpu.gpu_id: gpu for gpu in gpus}
    future = sorted(jobs, key=lambda job: (job.submitted_at, job.job_id))
    future_index = 0
    waiting: list[SchedulingJob] = []
    idle = dict(devices)
    running: list[tuple[float, str, SchedulingJob, Assignment]] = []
    assignments: list[Assignment] = []
    owner_service: dict[str, float] = {}
    now = future[0].submitted_at

    while len(assignments) < len(jobs):
        while future_index < len(future) and future[future_index].submitted_at <= now:
            waiting.append(future[future_index])
            future_index += 1

        while running and running[0][0] <= now:
            _, gpu_id, job, assignment = heapq.heappop(running)
            idle[gpu_id] = devices[gpu_id]
            reserved = assignment.predicted_runtime_p90_seconds / devices[gpu_id].speed_factor
            owner_service[job.owner_id] = (
                owner_service.get(job.owner_id, 0.0) + assignment.service_seconds - reserved
            )
            assignments.append(assignment)

        while waiting and idle:
            decision = policy.choose(waiting, list(idle.values()), now, owner_service)
            if decision is None:
                break
            job = next((item for item in waiting if item.job_id == decision.job_id), None)
            gpu = idle.get(decision.gpu_id)
            if job is None or gpu is None:
                raise RuntimeError("policy returned an invalid scheduling decision")
            if job.actual_peak_memory_gib > gpu.memory_gib:
                raise UnschedulableWorkloadError(
                    f"job {job.job_id} actually requires {job.actual_peak_memory_gib:.2f} GiB "
                    f"but policy assigned it to {gpu.gpu_id} with {gpu.memory_gib:.2f} GiB"
                )
            waiting.remove(job)
            idle.pop(gpu.gpu_id)
            duration = job.actual_runtime_seconds / gpu.speed_factor
            assignment = Assignment(
                job_id=job.job_id,
                owner_id=job.owner_id,
                gpu_id=gpu.gpu_id,
                submitted_at=job.submitted_at,
                started_at=now,
                finished_at=now + duration,
                predicted_runtime_p90_seconds=job.prediction.runtime_p90_seconds,
                actual_peak_memory_gib=job.actual_peak_memory_gib,
            )
            owner_service[job.owner_id] = (
                owner_service.get(job.owner_id, 0.0)
                + job.prediction.runtime_p90_seconds / gpu.speed_factor
            )
            heapq.heappush(running, (assignment.finished_at, gpu.gpu_id, job, assignment))

        if len(assignments) == len(jobs):
            break
        if running:
            now = min(
                running[0][0],
                future[future_index].submitted_at if future_index < len(future) else math.inf,
            )
            continue
        if future_index < len(future):
            now = future[future_index].submitted_at
            continue
        if waiting:
            details = ", ".join(
                f"{job.job_id} predicted={job.prediction.memory_p90_gib:.2f}GiB"
                for job in waiting
            )
            capacities = ", ".join(
                f"{gpu.gpu_id}={gpu.memory_gib:.2f}GiB" for gpu in gpus
            )
            raise UnschedulableWorkloadError(
                f"no compatible GPU for queued jobs ({details}); capacities: {capacities}"
            )

    assignments.sort(key=lambda item: (item.started_at, item.gpu_id, item.job_id))
    flows = [item.flow_seconds for item in assignments]
    waits = [item.waiting_seconds for item in assignments]
    started_at = min(job.submitted_at for job in jobs)
    finished_at = max(item.finished_at for item in assignments)
    makespan = finished_at - started_at
    busy_seconds = sum(item.service_seconds for item in assignments)
    owners = sorted({job.owner_id for job in jobs})
    service_by_owner = {
        owner: sum(item.service_seconds for item in assignments if item.owner_id == owner)
        for owner in owners
    }
    mean_slowdown_by_owner = {
        owner: sum(
            item.flow_seconds / item.service_seconds
            for item in assignments
            if item.owner_id == owner
        )
        / sum(item.owner_id == owner for item in assignments)
        for owner in owners
    }
    metrics = SimulationMetrics(
        completed_jobs=len(assignments),
        mean_flow_seconds=sum(flows) / len(flows),
        p95_flow_seconds=_percentile(flows, 0.95),
        mean_waiting_seconds=sum(waits) / len(waits),
        makespan_seconds=makespan,
        gpu_utilization=busy_seconds / (makespan * len(gpus)) if makespan else 0.0,
        jain_fairness=_jain_fairness(
            [1 / slowdown for slowdown in mean_slowdown_by_owner.values()]
        ),
        starvation_count=sum(wait >= starvation_threshold_seconds for wait in waits),
        owner_service_seconds=service_by_owner,
    )
    return SimulationResult(policy=policy.name, assignments=tuple(assignments), metrics=metrics)
