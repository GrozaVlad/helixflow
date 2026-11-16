"""Read-only checks for the portable evidence; no GPU or third-party packages."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    data = json.loads((ROOT / 'results/measurements.json').read_text())
    for relative, expected in data['source_sha256'].items():
        path = ROOT / 'evidence' / relative
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != expected:
            raise ValueError(f'Evidence hash mismatch: {relative}')
    trials = data['trials']
    assert len(trials) == 108
    assert len({t['trial_id'] for t in trials}) == 108
    assert all(t['SUCCEEDED'] == 12 and t['FAILED'] == t['UNSCHEDULABLE'] == 0 for t in trials)
    assert len(data['prediction_observations']) == 24
    workload = ROOT / 'workloads/public-v1-heme-ccd'
    frozen = json.loads((workload / 'frozen.json').read_text())['sha256']
    verified = 0
    for relative, expected in frozen.items():
        if relative.startswith(('msas/', 'source-cache/')):
            continue  # Large frozen assets live in the separately staged archive.
        path = workload / relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, relative
        verified += 1
    print(f'PASS: source hashes, 108 trials / 1296 successful jobs, 24 predictions, {verified} frozen files.')
    print('MSAs and full raw attempt outputs are not verified by this lightweight check.')


if __name__ == '__main__':
    main()
