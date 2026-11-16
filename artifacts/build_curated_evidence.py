"""Build an auditable evidence release from the retained experiment backup.

No inference or network calls. Original evidence is never modified. Requires Python 3.11+.
"""
import argparse
from collections import Counter
import gzip
import importlib.util
import json
from pathlib import Path
import re
import shutil
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('evidence_verifier', ROOT / 'curated-evidence/verify_evidence.py')
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
PHASES = {'pilot', 'phase-2-profiling', 'phase-3-concurrency',
          'phase-4-comparison', 'phase-5-recovery-r3'}
REPRESENTATIVE = 'burst-r1-g4-uaf_sjf'
TEXT = {'.json', '.csv', '.yaml', '.log'}
PATTERNS = {
    'private_key': r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
    'aws_access_key': r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    'github_token': r'\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{30,})\b',
    'credential_assignment': r'''(?i)["']?(?:api_key|api_token|access_token|secret_access_key|aws_secret_access_key|password|authorization)["']?\s*[:=]\s*["']?[^\s"',}]{12,}''',
}


def selection(relative):
    parts = relative.parts
    if parts[0] not in PHASES:
        if len(parts) == 1 and relative.name in ('preflight.json', 'pilot-validation.json'):
            return 'environment'
        return None
    if 'runtime-cache' in parts or 'processed' in parts:
        return None
    if 'output' in parts or any(p.startswith('boltz_results_') for p in parts):
        if 'predictions' not in parts:
            return None
        if relative.suffix == '.json':
            return 'prediction_confidence'
        if REPRESENTATIVE in parts and relative.suffix in ('.cif', '.npz'):
            return 'representative_prediction'
        return None
    if relative.suffix in TEXT:
        return 'measurement_or_configuration'
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True,
                        help='Original vast-58269544 directory containing remote-results')
    parser.add_argument('--output', type=Path, default=ROOT / 'release-assets')
    parser.add_argument('--dry-run', action='store_true', help='Inventory and scan; do not package')
    args = parser.parse_args()
    remote = args.source.resolve() / 'remote-results'
    candidates = []
    excluded = Counter()
    for path in sorted(remote.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Unexpected source symlink: {path.relative_to(remote)}')
        if not path.is_file():
            continue
        relative = path.relative_to(remote)
        category = selection(relative)
        if category:
            candidates.append((path, Path('remote-results') / relative, category))
        else:
            excluded['files'] += 1
            excluded['bytes'] += path.stat().st_size
    for path in sorted((ROOT / 'evidence').rglob('*')):
        if path.is_file():
            candidates.append((path, Path('selected-evidence') / path.relative_to(ROOT / 'evidence'),
                               'selected_public_evidence'))
    for name in ('README.md', 'verify_evidence.py'):
        candidates.append((ROOT / 'curated-evidence' / name, Path(name), 'release_documentation'))
    findings = []
    for source, relative, category in candidates:
        if source.suffix not in TEXT:
            continue
        content = source.read_text()
        for label, pattern in PATTERNS.items():
            if re.search(pattern, content):
                findings.append({'file': str(relative), 'pattern': label})
    overview = {'selected_files': len(candidates),
                'selected_bytes': sum(p.stat().st_size for p, _, _ in candidates),
                'excluded': dict(excluded), 'secret_pattern_findings': findings}
    print(json.dumps(overview, indent=2), flush=True)
    if findings:
        raise ValueError('Review potential secrets before packaging; matched values not printed')
    if args.dry_run:
        return
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output / 'helixflow-curated-evidence.tar.gz'
    if archive.exists():
        raise FileExistsError(f'Refusing to replace existing release: {archive}')
    print('Verifying all original comparison and recovery receipt hashes...', flush=True)
    source_audit = VERIFIER.validate_records(args.source.resolve(), require_full_outputs=True)
    with tempfile.TemporaryDirectory(prefix='helixflow-evidence-') as temporary:
        package = Path(temporary) / 'helixflow-curated-evidence'
        package.mkdir()
        inventory = {}
        for source, relative, category in candidates:
            destination = package / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            checksum = VERIFIER.digest(destination)
            if checksum != VERIFIER.digest(source):
                raise ValueError(f'Source changed during copy: {relative}')
            inventory[str(relative)] = {'sha256': checksum, 'bytes': destination.stat().st_size,
                                        'category': category}
        manifest = {'schema_version': '1.0', 'software': 'https://github.com/GrozaVlad/helixflow',
                    'source_label': 'vast-58269544 retained experiment backup',
                    'original_records_modified': False, 'representative_trial': REPRESENTATIVE,
                    'source_output_audit': source_audit,
                    'secret_scan': {'status': 'no_pattern_matches', 'patterns': list(PATTERNS),
                                    'scope': 'selected JSON, CSV, YAML, and log text; not a guarantee'},
                    'excluded_source_totals': dict(excluded),
                    'excluded_categories': ['runtime caches', 'MSAs', 'processed intermediates',
                                            'pickle models', 'SQLite/WAL and locks',
                                            'superseded recovery runs',
                                            'non-representative CIF and NPZ predictions'],
                    'files': inventory}
        (package / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
        verification = VERIFIER.verify(package)
        representative = list((package / 'remote-results/phase-4-comparison/study/trials' /
                               REPRESENTATIVE).rglob('*.cif'))
        if len(representative) != 12:
            raise ValueError('Expected 12 representative structures')
        # Canonical tar metadata and gzip timestamp make unchanged builds repeatable.
        def normalize(info):
            info.uid = info.gid = info.mtime = 0
            info.uname = info.gname = ''
            info.mode = 0o755 if info.isdir() else 0o644
            return info
        staged = Path(temporary) / archive.name
        with staged.open('wb') as stream, gzip.GzipFile(filename='', mode='wb', fileobj=stream,
                                                       mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode='w') as tar:
                tar.add(package, arcname=package.name, filter=normalize)
        # Re-read every tar member: no extraction or unchecked links.
        with tarfile.open(staged, 'r:gz') as tar:
            seen = set()
            for member in tar:
                if member.isdir():
                    continue
                VERIFIER.require(member.isfile(), 'Non-file archive member')
                relative = str(Path(member.name).relative_to(package.name))
                VERIFIER.require(relative not in seen, 'Duplicate archive member')
                seen.add(relative)
                data = tar.extractfile(member).read()
                VERIFIER.require(data == (package / relative).read_bytes(), 'Archive content mismatch')
            VERIFIER.require(seen == set(inventory) | {'MANIFEST.json'}, 'Archive inventory mismatch')
        shutil.copyfile(staged, archive)
    public_names = ('helixflow-curated-evidence.tar.gz', 'public-v1-heme-ccd-public.tar.gz')
    checksums = ''.join(f'{VERIFIER.digest(args.output / name)}  {name}\n'
                        for name in public_names if (args.output / name).is_file())
    (args.output / 'SHA256SUMS').write_text(checksums)
    result = {'archive': archive.name, 'bytes': archive.stat().st_size,
              'sha256': VERIFIER.digest(archive), 'payload_bytes': overview['selected_bytes'],
              'source_output_audit': source_audit, 'archive_verification': verification,
              'representative_structures': 12, 'secret_pattern_findings': findings}
    (args.output / 'curated-evidence-validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
