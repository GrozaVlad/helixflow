"""Test a separately launched workbench through its public localhost API.

The container must have the frozen alignment mounted at /validation/msa.csv.
This performs one real GPU prediction. It does not overwrite historical jobs.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:18001')
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error('Use a new report path; existing evidence will not be overwritten.')
    def get(path):
        with urllib.request.urlopen(args.base_url + path, timeout=20) as response:
            return response.read()
    health = json.loads(get('/api/health'))
    assert health['cuda_available'], health
    assert json.loads(get('/api/jobs')) == [], 'Use a fresh, isolated test service'
    page = get('/')
    viewer = get('/static/viewer.js')
    assert b'viewer.js' in page and b'"#080b10"' in viewer
    molstar = get('/static/molstar/molstar.js')
    data = args.input.read_text().replace('/evidence/msa.csv', '/validation/msa.csv').encode()
    boundary = 'helixflow-' + uuid.uuid4().hex
    chunks = []
    def field(name, value):
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, value in {'use_msa_server':'false','use_potentials':'false','override':'false',
                        'recycling_steps':'3','sampling_steps':'200','diffusion_samples':'1'}.items():
        field(name, value)
    chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="release_check.yaml"\r\nContent-Type: application/yaml\r\n\r\n'.encode()+data+b'\r\n')
    chunks.append(f'--{boundary}--\r\n'.encode())
    request = urllib.request.Request(args.base_url+'/api/jobs', data=b''.join(chunks),
        headers={'Content-Type':f'multipart/form-data; boundary={boundary}'})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=30) as response:
        assert response.status == 202
        job = json.load(response)
    print('Submitted isolated GPU test:', job['id'], flush=True)
    deadline = time.monotonic()+900
    while job['status'] in ('queued','running') and time.monotonic()<deadline:
        time.sleep(2)
        job = json.loads(get('/api/jobs/'+job['id']))
    elapsed = time.perf_counter()-started
    log = get('/api/jobs/'+job['id']+'/log').decode(errors='replace')
    downloaded = {}
    for name in job.get('files',[]):
        if name.endswith('.cif') or Path(name).name.startswith(('confidence_','affinity_')):
            payload = get('/api/jobs/'+job['id']+'/files/'+name)
            downloaded[name] = {'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
    checks = {
        'healthy_gpu':health['status']=='ok' and health['cuda_available'],
        'viewer_fix_present':b'"#080b10"' in viewer,
        'molstar_served':len(molstar)>100_000,
        'completed':job['status']=='completed' and job.get('return_code')==0,
        'one_structure_downloaded':sum(p.endswith('.cif') for p in downloaded)==1,
        'confidence_and_affinity_downloaded':sum(Path(p).name.startswith(('confidence_','affinity_')) for p in downloaded)==2,
        'no_msa_mismatch':'MSA does not match input sequence' not in log,
        'both_prediction_stages_succeeded':log.count('Number of failed examples: 0')==2,
    }
    report={'tested_at':datetime.now(timezone.utc).isoformat(),'image':'grozavlad/helixflow:local-2026-11-16',
            'health':health,'job':job,'checks':checks,'api_observed_seconds':elapsed,
            'timing_note':'Single API smoke test, includes polling delay; not a study benchmark.',
            'downloads':downloaded,'log':log,
            'viewer_js_sha256':hashlib.sha256(viewer).hexdigest(),
            'molstar_js_sha256':hashlib.sha256(molstar).hexdigest()}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(checks,indent=2),flush=True)
    if not all(checks.values()):
        raise SystemExit('Smoke test failed; inspect report before publishing.')


if __name__=='__main__':
    main()
