from experiments.crossfit_trace import grouped_folds


def test_grouped_folds_are_complete_disjoint_and_reproducible():
    job_ids = [f"job-{index}" for index in range(17)]
    folds = grouped_folds(job_ids, 5, seed=11)
    assert folds == grouped_folds(job_ids, 5, seed=11)
    assert sorted(job_id for fold in folds for job_id in fold) == sorted(job_ids)
    assert sum(len(set(fold)) for fold in folds) == len(job_ids)


def test_grouped_folds_reject_invalid_fold_count():
    try:
        grouped_folds(["a", "b"], 3, seed=1)
    except ValueError as error:
        assert "cannot exceed" in str(error)
    else:
        raise AssertionError("invalid fold count was accepted")
