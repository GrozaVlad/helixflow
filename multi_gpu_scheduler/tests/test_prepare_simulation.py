import random

import pytest

from experiments.prepare_simulation import arrival_times


def test_poisson_arrivals_are_seeded_and_monotonic():
    first = arrival_times(8, "poisson", 0.1, random.Random(42))
    second = arrival_times(8, "poisson", 0.1, random.Random(42))
    assert first == second
    assert first == sorted(first)
    assert len(set(first)) == len(first)


def test_arrival_rate_must_be_positive_when_time_advances():
    with pytest.raises(ValueError, match="rate must be positive"):
        arrival_times(2, "burst", 0, random.Random(42))
