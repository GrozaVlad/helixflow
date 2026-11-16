"""Small regression tests for release selection and integrity safeguards."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('builder', Path(__file__).resolve().parents[1] /
                                             'build_curated_evidence.py')
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)
V = BUILDER.VERIFIER


class PackagingTests(unittest.TestCase):
    def test_excluded_payloads(self):
        for path in (
            'phase-4-comparison/study/trials/x/runtime-cache/triton/cache.json',
            'phase-4-comparison/study/trials/x/inputs/j/msa-0.a3m',
            'phase-4-comparison/study/trials/x/queue.sqlite3',
            'phase-2-profiling/predictor.pkl',
            'phase-5-recovery/phase.json',
            'phase-4-comparison/study/trials/x/attempts/a/output/processed/records/input.json',
        ):
            self.assertIsNone(BUILDER.selection(Path(path)), path)

    def test_measurements_and_representative(self):
        prefix = 'phase-4-comparison/study/trials/'
        self.assertIsNotNone(BUILDER.selection(Path(prefix + 'x/attempts/a/telemetry.json')))
        output = '/attempts/a/output/boltz_results_input/predictions/input/'
        self.assertIsNotNone(BUILDER.selection(Path(prefix + 'x' + output + 'confidence.json')))
        self.assertIsNone(BUILDER.selection(Path(prefix + 'x' + output + 'model.cif')))
        for extension in ('cif', 'npz'):
            self.assertIsNotNone(BUILDER.selection(Path(prefix + BUILDER.REPRESENTATIVE +
                                                        output + 'model.' + extension)))

    def test_path_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                V.safe_path(root, '../outside')

    def test_tampering_and_missing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / 'record.json'
            payload.write_text('{}')
            (root / 'MANIFEST.json').write_text(json.dumps({'files': {
                'record.json': {'bytes': 2, 'sha256': V.digest(payload)}}}))
            with patch.object(V, 'validate_records', return_value={}):
                self.assertEqual(V.verify(root)['status'], 'PASSED')
                payload.write_text('[]')
                with self.assertRaises(ValueError):
                    V.verify(root)
                payload.unlink()
                with self.assertRaises(ValueError):
                    V.verify(root)


if __name__ == '__main__':
    unittest.main()
