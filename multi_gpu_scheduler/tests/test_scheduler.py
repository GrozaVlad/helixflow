import pytest

from scheduling.models import GPUDevice, JobFeatures, RuntimePrediction, SchedulingJob
from scheduling.policies import UncertaintyAwareFairSJF, make_policy
from scheduling.simulator import UnschedulableWorkloadError, simulate


def job(
    job_id: str,
    runtime: float,
    *,
    submitted: float = 0,
    owner: str = "researcher-a",
    memory: float = 8,
    tokens: int = 100,
) -> SchedulingJob:
    return SchedulingJob(
        job_id=job_id,
        owner_id=owner,
        submitted_at=submitted,
        features=JobFeatures(
            job_type="monomer",
            total_residues=tokens,
            max_chain_length=tokens,
            estimated_tokens=tokens,
        ),
        prediction=RuntimePrediction(runtime * 0.9, runtime, memory),
        actual_runtime_seconds=runtime,
        actual_peak_memory_gib=memory,
    )


def test_simulation_drains_every_accepted_job():
    jobs = [job("long", 30), job("short", 2), job("medium", 8)]
    result = simulate(
        jobs,
        [GPUDevice("gpu-0", 24)],
        make_policy("uaf_sjf", starvation_threshold_seconds=100),
        starvation_threshold_seconds=100,
    )
    assert result.metrics.completed_jobs == len(jobs)
    assert {assignment.job_id for assignment in result.assignments} == {
        "long",
        "short",
        "medium",
    }


def test_sjf_reduces_mean_flow_time_against_fcfs():
    jobs = [job("long", 30), job("short", 2), job("medium", 8)]
    gpu = [GPUDevice("gpu-0", 24)]
    fcfs = simulate(
        jobs,
        gpu,
        make_policy("fcfs"),
        starvation_threshold_seconds=100,
    )
    sjf = simulate(
        jobs,
        gpu,
        make_policy("predicted_sjf"),
        starvation_threshold_seconds=100,
    )
    assert sjf.metrics.mean_flow_seconds < fcfs.metrics.mean_flow_seconds


def test_aging_overrides_new_short_job():
    old = job("old-long", 40, submitted=0)
    new = job("new-short", 2, submitted=12)
    policy = UncertaintyAwareFairSJF(starvation_threshold_seconds=10)
    decision = policy.choose([old, new], [GPUDevice("gpu-0", 24)], 12, {})
    assert decision is not None
    assert decision.job_id == "old-long"


def test_memory_prediction_routes_job_to_compatible_gpu():
    large = job("large", 10, memory=20)
    policy = make_policy("uaf_sjf", starvation_threshold_seconds=100)
    decision = policy.choose(
        [large],
        [GPUDevice("small", 16), GPUDevice("large", 32)],
        0,
        {},
    )
    assert decision is not None
    assert decision.gpu_id == "large"


def test_unschedulable_job_is_reported_not_dropped():
    too_large = job("too-large", 10, memory=30)
    with pytest.raises(UnschedulableWorkloadError, match="no compatible GPU"):
        simulate(
            [too_large],
            [GPUDevice("gpu-0", 24)],
            make_policy("uaf_sjf", starvation_threshold_seconds=100),
            starvation_threshold_seconds=100,
        )


def test_arrival_uses_idle_gpu_before_other_job_finishes():
    result = simulate(
        [job("long", 100), job("later", 2, submitted=5)],
        [GPUDevice("a", 24), GPUDevice("b", 24)],
        make_policy("fcfs"),
        starvation_threshold_seconds=100,
    )
    later = next(a for a in result.assignments if a.job_id == "later")
    assert later.started_at == 5


def test_incompatible_aged_job_does_not_block_compatible_job():
    policy = make_policy("uaf_sjf", starvation_threshold_seconds=10)
    decision = policy.choose(
        [job("old-large", 50, memory=20), job("new", 2, submitted=19)],
        [GPUDevice("small", 16)], 20, {},
    )
    assert decision.job_id == "new"


def test_simultaneous_arrival_and_completion():
    result = simulate(
        [job("first", 5), job("second", 2, submitted=5)],
        [GPUDevice("a", 24)], make_policy("fcfs"), starvation_threshold_seconds=100,
    )
    assert result.assignments[1].started_at == 5


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_nonfinite_prediction_rejected(value):
    with pytest.raises(ValueError, match="finite"):
        RuntimePrediction(value, value, 1)


def test_fair_service_prefers_less_served_owner():
    policy = make_policy("fair_service")
    decision = policy.choose(
        [job("short", 1, owner="a"), job("long", 100, owner="b")],
        [GPUDevice("gpu", 16)], 0, {"a": 100, "b": 0},
    )
    assert decision.job_id == "long"
