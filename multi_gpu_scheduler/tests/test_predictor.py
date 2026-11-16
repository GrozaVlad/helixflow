from pathlib import Path

from scheduling.models import JobFeatures
from scheduling.predictor import PredictorBundle, TrainingObservation, train_predictor


def test_quantile_predictor_trains_calibrates_and_round_trips(tmp_path: Path):
    observations = []
    for index in range(30):
        features = JobFeatures(
            job_type=("monomer", "protein_complex", "protein_ligand")[index % 3],
            total_residues=100 + index * 20,
            max_chain_length=100 + index * 10,
            protein_chains=1 + (index % 2),
            ligand_count=index % 3 == 2,
            ligand_atoms=20 if index % 3 == 2 else 0,
            msa_depth=10 + index,
            estimated_tokens=110 + index * 22,
        )
        for repeat in range(2):
            observations.append(
                TrainingObservation(
                    job_id=f"job-{index}",
                    features=features,
                    runtime_seconds=20 + index * 3 + repeat,
                    peak_memory_gib=4 + index * 0.2,
                )
            )
    result = train_predictor(observations, seed=7)
    assert set(result.predictor.training_job_ids).isdisjoint(result.calibration_job_ids)
    assert result.runtime_p90_coverage >= 0.9
    assert result.memory_p90_coverage >= 0.9

    model_path = tmp_path / "predictor.pkl"
    result.predictor.save(model_path)
    prediction = PredictorBundle.load(model_path).predict(observations[0].features)
    assert prediction.runtime_p90_seconds >= prediction.runtime_p50_seconds > 0
    assert prediction.memory_p90_gib > 0
