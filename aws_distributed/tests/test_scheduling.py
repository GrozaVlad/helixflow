import pytest

from shared.scheduling import decide, priority_from_runtime, share_identifier


def test_shorter_prediction_receives_higher_batch_priority():
    assert priority_from_runtime(60) > priority_from_runtime(600)


def test_missing_prediction_falls_back_without_dropping_job():
    decision = decide("researcher@example.org", {})
    assert decision.policy == "fcfs-fallback"
    assert decision.scheduling_priority == 1
    assert decision.fallback_reason


def test_prediction_maps_to_fair_share_decision():
    decision = decide(
        "researcher@example.org",
        {
            "scheduling_prediction": {
                "runtime_p50_seconds": 120,
                "runtime_p90_seconds": 180,
                "memory_p90_gib": 12,
                "predictor_version": "model-1",
            }
        },
    )
    assert decision.policy == "uaf-sjf-aws-batch"
    assert decision.scheduling_priority == priority_from_runtime(180)
    assert decision.share_identifier == share_identifier("researcher@example.org")
    assert "@" not in decision.share_identifier


@pytest.mark.parametrize("runtime", [0, -1, float("nan"), float("inf")])
def test_invalid_runtime_is_rejected(runtime):
    with pytest.raises(ValueError):
        priority_from_runtime(runtime)
