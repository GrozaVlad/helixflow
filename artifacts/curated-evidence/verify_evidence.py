"""Verify a curated evidence directory without GPUs or external dependencies."""
import csv
import hashlib
import json
from pathlib import Path


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_path(root, relative):
    path = (root / relative).resolve()
    require(path.is_relative_to(root.resolve()), f'Unsafe path: {relative}')
    return path


def validate_records(root, require_full_outputs=False):
    comparison = root / 'remote-results/phase-4-comparison'
    study = comparison / 'study'
    phase, plan, index = [read(p) for p in
                          (comparison / 'phase.json', study / 'plan.json', study / 'index.json')]
    require(phase['status'] == 'COMPLETED', 'Comparison incomplete')
    require(digest(study / 'plan.json') == index['plan_sha256'] == phase['plan_sha256'],
            'Plan hash mismatch')
    require(len(plan['trials']) == 108, 'Expected 108 planned trials')
    require(len({t['id'] for t in plan['trials']}) == 108, 'Duplicate trial IDs')
    for name, expected in plan['manifests'].items():
        require(digest(safe_path(study, name)) == expected, f'Manifest mismatch: {name}')
    counts = {'trials': 0, 'comparison_jobs': 0, 'comparison_outputs_verified': 0,
              'comparison_outputs_omitted': 0, 'recovery_outputs_verified': 0,
              'recovery_outputs_omitted': 0}

    def check_receipt(folder, attempt, category):
        directory = safe_path(folder / 'attempts', attempt['attempt_id'])
        receipt = read(directory / 'receipt.json')
        require(receipt == attempt['receipt'], 'Receipt differs from report')
        require(receipt['return_code'] == 0 and receipt['sample_errors'] == 0,
                'Successful receipt reports errors')
        for name, expected in receipt['artifacts'].items():
            path = safe_path(directory / 'output', name)
            if path.is_file():
                require(digest(path) == expected, f'Output hash mismatch: {path}')
                counts[f'{category}_outputs_verified'] += 1
            else:
                require(not require_full_outputs, f'Missing original output: {path}')
                counts[f'{category}_outputs_omitted'] += 1

    for trial in plan['trials']:
        state = index['trials'][trial['id']]
        require(state['state'] == 'COMPLETE', 'Incomplete trial')
        folder = safe_path(study / 'trials', trial['id'])
        path = folder / 'report/report.json'
        require(digest(path) == state['report_sha256'], 'Report hash mismatch')
        report = read(path)
        require(report['metrics']['counts']['SUCCEEDED'] == 12, 'Wrong success count')
        require(len(report['jobs']) == len(report['attempts']) == 12, 'Wrong job/attempt count')
        require(len({j['job_id'] for j in report['jobs']}) == 12, 'Duplicate job IDs')
        require({a['job_id'] for a in report['attempts']} ==
                {j['job_id'] for j in report['jobs']}, 'Attempt/job mismatch')
        for job in report['jobs']:
            require(job['status'] == 'SUCCEEDED', 'Comparison job failed')
        for attempt in report['attempts']:
            require(attempt['status'] == 'SUCCEEDED', 'Comparison attempt failed')
            check_receipt(folder, attempt, 'comparison')
            for name in ('telemetry.json', 'request.json', 'run.log'):
                require((folder / 'attempts' / attempt['attempt_id'] / name).is_file(),
                        f'Missing attempt evidence: {name}')
        counts['trials'] += 1
        counts['comparison_jobs'] += len(report['jobs'])
    summary = read(comparison / 'report/summary.json')
    require(summary['completed_trials'] == 108, 'Aggregate trial count mismatch')
    require(counts['comparison_outputs_verified'] + counts['comparison_outputs_omitted'] == 15552,
            'Wrong comparison output count')
    recovery = root / 'remote-results/phase-5-recovery-r3'
    state = read(recovery / 'phase.json')
    require(state['status'] == 'COMPLETED' and len(state['cases']) == 4, 'Recovery incomplete')
    jobs = attempts = successes = failures = 0
    for case in state['cases']:
        require(case['status'] == 'PASSED', 'Recovery scenario did not pass')
        folder = safe_path(recovery, case['campaign'])
        report = read(folder / 'report/report.json')
        jobs += len(report['jobs'])
        attempts += len(report['attempts'])
        for job in report['jobs']:
            good = [a for a in report['attempts'] if a['job_id'] == job['job_id']
                    and a['status'] == 'SUCCEEDED']
            if job['status'] == 'SUCCEEDED':
                require(len(good) == 1 and job['published_attempt'] == good[0]['attempt_id'],
                        'Recovery publication mismatch')
                successes += 1
            else:
                require(job['status'] == 'FAILED' and not good and job['published_attempt'] is None,
                        'Unexpected recovery outcome')
                failures += 1
        for attempt in report['attempts']:
            if attempt['status'] == 'SUCCEEDED':
                check_receipt(folder, attempt, 'recovery')
    require((jobs, attempts, successes, failures) == (9, 11, 7, 2), 'Recovery accounting mismatch')
    require(counts['recovery_outputs_verified'] + counts['recovery_outputs_omitted'] == 77,
            'Wrong recovery output count')
    profiling = root / 'remote-results/phase-2-profiling'
    profiles = list((profiling / 'profiling').glob('*-r[12].json'))
    require(len(profiles) == 120, 'Expected 120 profiles')
    require(len({p.stem.rsplit('-r', 1)[0] for p in profiles}) == 60, 'Expected 60 profile targets')
    with (profiling / 'predictor-plots/held-out-predictions.csv').open() as stream:
        require(len(list(csv.DictReader(stream))) == 24, 'Expected 24 held-out predictions')
    counts.update(profiles=120, recovery_jobs=jobs, recovery_attempts=attempts,
                  recovery_successes=successes, recovery_expected_failures=failures)
    return counts


def verify(root):
    manifest = read(root / 'MANIFEST.json')
    expected = manifest['files']
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()
              and p.name != 'MANIFEST.json' and '__pycache__' not in p.parts}
    require(actual == set(expected), 'Missing or unexpected payload files')
    for name, entry in expected.items():
        path = safe_path(root, name)
        require(not path.is_symlink(), f'Unexpected symlink: {name}')
        require(path.stat().st_size == entry['bytes'] and digest(path) == entry['sha256'],
                f'Payload mismatch: {name}')
    counts = validate_records(root)
    counts.update(status='PASSED', payload_files=len(expected))
    return counts


if __name__ == '__main__':
    print(json.dumps(verify(Path(__file__).resolve().parent), indent=2))
