"""Run one offline Boltz example and retain measured provenance and checks.

Run inside the local workbench image with this directory mounted at /evidence,
and an already populated, read-only Boltz cache at /workspace/cache.
Refuses to overwrite a previous run. See README.md for the Docker command.
"""
import csv
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import gemmi
import torch
import yaml


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def persist(path, record):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, indent=2) + '\n')
    temporary.replace(path)


def finite_json(value):
    if isinstance(value, dict):
        return all(finite_json(v) for v in value.values())
    if isinstance(value, list):
        return all(finite_json(v) for v in value)
    return not isinstance(value, float) or math.isfinite(value)


def main():
    root = Path('/evidence')
    cache = Path('/workspace/cache')
    report = root / 'run-record.json'
    outputs = root / 'outputs'
    if report.exists() or outputs.exists():
        raise SystemExit('Refusing to overwrite prior evidence; use a fresh directory.')
    input_data = yaml.safe_load((root / 'input.yaml').read_text())
    sequence = input_data['sequences'][0]['protein']['sequence']
    with (root / 'msa.csv').open() as stream:
        rows = list(csv.DictReader(stream))
    assert rows and rows[0]['sequence'] == sequence, 'MSA query mismatch'
    assert all(len(''.join(c for c in row['sequence'] if not c.islower())) == len(sequence) for row in rows)
    checkpoints = [cache / 'boltz2_conf.ckpt', cache / 'boltz2_aff.ckpt']
    assert all(p.is_file() for p in checkpoints) and (cache / 'mols').is_dir()
    # Capture the effective default values as well as explicitly specified flags.
    command = [
        'boltz', 'predict', '/evidence/input.yaml', '--out_dir', str(outputs),
        '--cache', str(cache), '--model', 'boltz2', '--devices', '1',
        '--accelerator', 'gpu', '--seed', '42', '--recycling_steps', '3',
        '--sampling_steps', '200', '--diffusion_samples', '1',
        '--max_parallel_samples', '1', '--num_workers', '0',
        '--preprocessing-threads', '4', '--step_scale', '1.5',
        '--sampling_steps_affinity', '200', '--diffusion_samples_affinity', '5',
        '--max_msa_seqs', '8192', '--num_subsampled_msa', '1024',
        '--output_format', 'mmcif', '--checkpoint', str(checkpoints[0]),
        '--affinity_checkpoint', str(checkpoints[1]),
    ]
    import boltz.main
    defaults = {p.name: ({'callable': p.default.__qualname__} if callable(p.default) else p.default) for p in boltz.main.predict.params}
    record = {
        'schema_version': 1, 'status': 'preparing', 'record_created_at': utc(),
        'purpose': 'New offline CLI example using the local workbench image; not a replay of the historical random trajectory or a browser timing.',
        'historical_job': 'd5c2056a335a', 'command': command,
        'image_id': os.environ.get('HELIXFLOW_IMAGE_ID'),
        'network': 'Docker --network none', 'cache_mount': 'read-only; prepopulated',
        'seed': 42, 'cli_defaults': defaults,
        'python': platform.python_version(), 'platform': platform.platform(),
        'packages': {d.metadata['Name']: d.version for d in importlib.metadata.distributions()},
        'torch_cuda': torch.version.cuda, 'gpu': torch.cuda.get_device_name(0),
        'gpu_total_bytes': torch.cuda.get_device_properties(0).total_memory,
        'gpu_driver': subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version,memory.total','--format=csv,noheader'], text=True).strip(),
        'cpu_model': next((s.split(':',1)[1].strip() for s in Path('/proc/cpuinfo').read_text().splitlines() if s.startswith('model name')), None),
        'logical_cpus': os.cpu_count(),
        'system_memory': next(s for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemTotal:')),
        'protein_residues': len(sequence), 'msa_rows': len(rows), 'msa_query_matches': True,
        'inputs_sha256': {p.name: digest(p) for p in [root/'input.yaml',root/'msa.csv',root/'reproduce.py']},
        'checkpoints_sha256': {p.name: digest(p) for p in checkpoints},
    }
    mol_hashes = {str(p.relative_to(cache)): digest(p) for p in sorted((cache/'mols').glob('*.pkl'))}
    persist(root/'molecule-cache-sha256.json', mol_hashes)
    record['molecule_cache_files'] = len(mol_hashes)
    record['molecule_cache_manifest_sha256'] = digest(root/'molecule-cache-sha256.json')
    record.update(status='running', started_at=utc())
    persist(report, record)
    print(json.dumps({'status':'running','started_at':record['started_at'],'msa_rows':len(rows)}), flush=True)
    started = time.perf_counter()
    with (root/'run.log').open('w') as log:
        process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, cwd=root)
    duration = time.perf_counter() - started
    record.update(finished_at=utc(), process_wall_seconds=duration, return_code=process.returncode, status='validating')
    persist(report, record)
    cifs = sorted(outputs.rglob('*.cif'))
    confidence = sorted(outputs.rglob('confidence_*.json'))
    affinity = sorted(outputs.rglob('affinity_*.json'))
    log_text = (root/'run.log').read_text(errors='replace')
    checks = {
        'return_code_zero': process.returncode == 0,
        'one_structure': len(cifs) == 1,
        'one_confidence_json': len(confidence) == 1,
        'one_affinity_json': len(affinity) == 1,
        'no_msa_mismatch_warning': 'MSA does not match input sequence' not in log_text,
        'no_remote_msa_call': 'Calling MSA server' not in log_text,
        'zero_failed_structure_predictions': 'Number of failed examples: 0' in log_text,
        'both_prediction_stages_report_zero_failures': log_text.count('Number of failed examples: 0') == 2,
    }
    if len(cifs) == 1:
        structure = gemmi.read_structure(str(cifs[0]))
        chains = {c.name:len(c) for c in structure[0]}
        record['structure'] = {'models':len(structure),'chain_residues':chains,
            'atoms':sum(len(r) for m in structure for c in m for r in c)}
        checks['expected_chains'] = len(structure) == 1 and chains == {'A':len(sequence),'B':1}
        checks['finite_coordinates'] = all(math.isfinite(v) for m in structure for c in m for r in c for a in r for v in (a.pos.x,a.pos.y,a.pos.z))
    for kind, paths in [('confidence',confidence),('affinity',affinity)]:
        if len(paths) == 1:
            data = json.loads(paths[0].read_text())
            record[kind] = data
            checks[kind+'_finite_values'] = finite_json(data)
    checks['affinity_probability_in_range'] = 0 <= record.get('affinity',{}).get('affinity_probability_binary',-1) <= 1
    record['checks'] = checks
    record['outputs_sha256'] = {str(p.relative_to(root)):digest(p) for p in sorted(outputs.rglob('*')) if p.is_file()}
    record['log_sha256'] = digest(root/'run.log')
    record['status'] = 'completed' if all(checks.values()) else 'validation_failed'
    record['timing_scope'] = 'Boltz subprocess startup through exit: local preprocessing, model loading, structure and affinity inference, output writes. Excludes container startup, provenance hashing, validation, model download and historical remote MSA generation.'
    persist(report, record)
    print(json.dumps({'status':record['status'],'seconds':duration,'checks':checks}), flush=True)
    raise SystemExit(0 if all(checks.values()) else 1)


if __name__ == '__main__':
    main()
