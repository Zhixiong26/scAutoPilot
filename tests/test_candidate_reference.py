"""Candidate references preserve exact cells/evidence and never approve labels."""
import csv
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from _common import WorkflowError, signature, write_json
from prepare_scanpy_candidate_reference import prepare
from figures_comparison_evidence import sha
from init_project import RUNTIME_TOOLS


class CandidateReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        common = self.root / 'Scripts/Common'
        common.mkdir(parents=True)
        shutil.copy2(ROOT / 'assets/project-template/Scripts/Common/annotation.py', common)
        self.result = self.root / 'Results/runs/source'
        self.result.mkdir(parents=True)
        self.table = self.result / 'annotation.tsv'
        self.table.write_text('cell_id\tcell_type\tleiden\ns_B\tUnassigned\t1\ns_A\tUnassigned\t0\n')
        self.status = self.result / 'annotation_status.json'
        write_json(self.status, {'analysis_signature': 'analysis', 'n_cells': 2, 'n_clusters': 2})
        run_dir = self.root / '.workflow/runs/source'
        task_dir = run_dir / 'tasks/scanpy'
        task_dir.mkdir(parents=True)
        write_json(run_dir / 'plan.json', {'run_id': 'source', 'result_dir': str(self.result),
            'input_signature': 'input', 'code_signature': 'code', 'tasks': [{'id': 'scanpy', 'parameters': {}}]})
        write_json(task_dir / 'task_outputs.json', {'artifacts': [str(self.table), str(self.status)]})
        write_json(task_dir / 'task_status.json', {'status': 'complete', 'return_code': 0,
            'input_signature': 'input', 'code_signature': 'code', 'command': ['fixture'],
            'task_signature': signature({'command': ['fixture'], 'parameters': {}}),
            'outputs': [str(task_dir / 'task_outputs.json')]})
        self.complete = task_dir / 'task.COMPLETE'
        self.complete.touch()
        self.worksheet = self.root / 'proposals.tsv'
        self.header = 'cluster\tcell_type\tconfidence\talternatives\tevidence\n'
        self.worksheet.write_text(self.header + '0\tT/NK cells\thigh\t\tCD3E\n1\tMixed lineage (review)\tlow\tB cells\tCD79A and CD3E\n')
        self.output = Path('Data/Annotation/proposal-v1')

    def export(self):
        return prepare(self.root, 'source', self.worksheet, self.output)

    def test_complete_reference_preserves_order_marker_evidence_and_source(self):
        before = sha(self.table)
        path = self.export()
        with path.open() as stream:
            rows = list(csv.DictReader(stream, delimiter='\t'))
        self.assertEqual([r['cell_id'] for r in rows], ['s_B', 's_A'])
        self.assertEqual([r['cell_type'] for r in rows], ['Mixed lineage (review)', 'T/NK cells'])
        self.assertEqual(rows[0]['marker_evidence'], 'CD79A and CD3E')
        self.assertTrue(all(r['review_status'] == 'agent_proposed_unapproved' for r in rows))
        manifest = json.loads(path.with_name('provenance.json').read_text())
        self.assertFalse(manifest['independent_reference'])
        self.assertEqual(manifest['artifacts'][0]['sha256'], sha(path))
        self.assertEqual(manifest['sources'][str(self.table)], before)
        self.assertEqual(sha(self.table), before)
        with self.assertRaisesRegex(WorkflowError, 'already exists'):
            self.export()

    def test_invalid_mapping_fails_before_publishing(self):
        for body in ['0\tT cells\thigh\t\tCD3E\n',
                     '0\tT cells\thigh\t\tCD3E\n0\tB cells\thigh\t\tCD79A\n',
                     '0\tUnassigned\thigh\t\tCD3E\n1\tB cells\thigh\t\tCD79A\n',
                     '0\tT cells\thigh\t\t\n1\tB cells\thigh\t\tCD79A\n']:
            with self.subTest(body=body):
                self.worksheet.write_text(self.header + body)
                with self.assertRaises(WorkflowError):
                    self.export()
                self.assertFalse((self.root / self.output).exists())

    def test_wrong_run_worksheet_and_incomplete_task_are_refused(self):
        self.worksheet.write_text('cluster\tcell_type\tconfidence\talternatives\tevidence\tsource_run\n'
                                  '0\tT cells\thigh\t\tCD3E\tother-run\n')
        with self.assertRaisesRegex(WorkflowError, 'source_run'):
            self.export()
        self.complete.unlink()
        with self.assertRaisesRegex(ValueError, 'completion marker'):
            self.export()

    def test_duplicate_cells_and_escaping_destinations_are_refused(self):
        self.table.write_text('cell_id\tcell_type\tleiden\ns_A\tUnassigned\t0\ns_A\tUnassigned\t1\n')
        with self.assertRaisesRegex(WorkflowError, 'duplicate cell'):
            self.export()
        for path in [Path('/tmp/proposal'), Path('Data/../outside'), Path('Results/proposal')]:
            with self.assertRaises(WorkflowError):
                prepare(self.root, 'source', self.worksheet, path)
        (self.root / 'Data').mkdir()
        with tempfile.TemporaryDirectory() as outside:
            (self.root / 'Data/external').symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(WorkflowError, 'outside'):
                prepare(self.root, 'source', self.worksheet, Path('Data/external/proposal'))

    def test_helper_is_distributed_to_generated_projects(self):
        self.assertIn('prepare_scanpy_candidate_reference.py', RUNTIME_TOOLS)


if __name__ == '__main__':
    unittest.main()
