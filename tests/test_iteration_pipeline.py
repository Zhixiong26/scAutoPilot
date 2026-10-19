"""Exercise completed evidence -> review -> apply -> next candidate with real tiny H5ADs."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from _common import load_project, load_samples, signature, write_json, write_tsv, SAMPLE_COLUMNS
from init_project import DEFAULT_ANALYSIS
from apply_scanpy_round import apply, ApplyError
from scautopilot.review import controller
from scautopilot.review.backend import PARAMETERS, DIRECTIONS, QUALITY

HAS_NUMERIC = all(importlib.util.find_spec(name) for name in ('anndata', 'numpy', 'sklearn'))


class AnnotationHandoffTests(unittest.TestCase):
    def test_custom_columns_preserve_review_flags_and_eligibility(self):
        import csv
        spec = importlib.util.spec_from_file_location('handoff_annotation',
            ROOT / 'assets/project-template/Scripts/Common/annotation.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / 'input.tsv', Path(tmp) / 'output.tsv'
            source.write_text('barcode\tidentity\trequires_review\tdmr_eligible\treview_status\tevidence\n'
                'a\tT cell\ttrue\t1\tpending\tmarkers\n'
                'b\tB cell\tfalse\t0\tapproved\texcluded\n'
                'c\tT cell\tfalse\t1\tapproved\tconfirmed\n')
            module.normalize_annotation_table(source, target, 'barcode', 'identity')
            with target.open() as handle:
                rows = list(csv.DictReader(handle, delimiter='\t'))
            self.assertEqual([row['cell_id'] for row in rows], ['a', 'b', 'c'])
            self.assertEqual(rows[0]['evidence'], 'markers')
            self.assertEqual(module.annotation_row_issue(rows[0]), 'unresolved_requires_review')
            self.assertEqual(module.annotation_row_issue(rows[1]), 'not_dmr_eligible')
            self.assertIsNone(module.annotation_row_issue(rows[2]))


@unittest.skipUnless(HAS_NUMERIC, 'requires analysis environment')
class IterationPipelineTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        import pandas as pd
        import anndata as ad
        self.np, self.pd, self.ad = np, pd, ad
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / 'assets/project-template', self.root, dirs_exist_ok=True)
        write_json(self.root / 'config/project.yaml', {'schema_version': 2,
            'project': {'id': 'fixture'}, 'annotation': {}})
        write_json(self.root / 'config/analysis.yaml', {'schema_version': 2, 'analysis': DEFAULT_ANALYSIS})
        write_json(self.root / 'config/scheduler.yaml', {'schema_version': 2, 'backend': 'local'})
        (self.root / 'config/environments.tsv').write_text('stage\tpython\texecutable\tversion_command\trequired\n')
        write_tsv(self.root / 'config/samples.tsv', SAMPLE_COLUMNS, [{
            'sample_id': 'sample', 'cell_id_prefix': 'prefix', 'condition': 'treated', 'batch': 'batch1',
            'include': '1', 'rna_path': 'Data/matrix', 'rna_format': '10x_mtx'}])
        opt = json.loads((self.root / 'config/optimization.yaml').read_text())
        opt['scanpy_mvp']['visual_review']['enabled'] = False
        opt['scanpy_mvp']['decision_backend'] = {'mode': 'command', 'command': ['fixture']}
        write_json(self.root / 'config/optimization.yaml', opt)
        spec = importlib.util.spec_from_file_location('fixture_scanpy_runner',
            self.root / 'Scripts/Scanpy/run_scanpy_notebook.py')
        self.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runner)
        self.raw = {'backend': 'fixture', 'accept_probability': 0.1, 'escalate_probability': 0.1,
            'parameter': {name: float(name == 'n_neighbors') for name in PARAMETERS},
            'direction': {name: float(name == 'increase') for name in DIRECTIONS},
            'quality': {name: float(name == 'acceptable') for name in QUALITY}}
        self.env = mock.patch.dict(os.environ, {'SCMO_HOST_ROLE': 'standalone'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.candidate('first')

    def candidate(self, run_id):
        result = self.root / 'Results/runs' / run_id
        params = self.runner.build_parameters(self.root, load_project(self.root),
            load_samples(self.root, require_paths=False), result / 'scanpy', run_id)
        source = result / 'scanpy/iterations' / params['iteration_id'] / 'candidate_analysis.h5ad'
        source.parent.mkdir(parents=True)
        rng = self.np.random.RandomState(0)
        obs = self.pd.DataFrame({'leiden': ['0'] * 48 + ['1'] * 48,
            'candidate_cell_type': ['A'] * 48 + ['B'] * 48, 'sample': ['s1', 's2'] * 48},
            index=['cell_%03d' % i for i in range(96)])
        data = self.ad.AnnData(self.np.zeros((96, 80)), obs=obs)
        data.obsm['X_pca_harmony'] = rng.normal(size=(96, int(params['pca_n_comps'])))
        data.obsm['X_umap_after_harmony'] = data.obsm['X_pca_harmony'][:, :2]
        data.uns['annotation_status'] = 'candidate'
        data.write_h5ad(source)
        sidecar = result / 'scanpy/scanpy_parameters.json'
        write_json(sidecar, params)
        state = self.root / '.workflow/runs' / run_id
        task = state / 'tasks/scanpy'
        task.mkdir(parents=True)
        write_json(state / 'plan.json', {'run_id': run_id, 'result_dir': str(result),
            'input_signature': 'input-' + run_id, 'code_signature': 'code',
            'tasks': [{'id': 'scanpy', 'parameters': {}}]})
        write_json(task / 'task_outputs.json', {'artifacts': [str(source), str(sidecar)]})
        write_json(task / 'task_status.json', {'status': 'complete', 'return_code': 0,
            'input_signature': 'input-' + run_id, 'code_signature': 'code',
            'command': ['fixture'], 'task_signature': signature({'command': ['fixture'], 'parameters': {}}),
            'outputs': [str(task / 'task_outputs.json')]})
        (task / 'task.COMPLETE').touch()
        write_json(state / 'run_summary.json', {'status': 'complete',
            'tasks': [{'task': 'scanpy', 'evidence_valid': True}]})
        return source

    def review(self, run='first', session='session'):
        with mock.patch.object(controller, 'command_backend', return_value=dict(self.raw)):
            return controller.review_scanpy_run(self.root, run, session)

    def test_review_apply_next_review_preserves_fixed_k_and_exact_sample(self):
        first = self.review()
        self.assertEqual(first['status'], 'next_candidate')
        apply(self.root, 'session', 'round_000', 'second')
        self.candidate('second')
        self.review('second')
        base = self.root / '.workflow/optimization/session'
        a, b = [json.loads((base / r / 'state.json').read_text()) for r in ('round_000', 'round_001')]
        self.assertEqual(a['benchmark'], b['benchmark'])
        self.assertEqual(b['parameters']['n_neighbors'], 20)
        self.assertEqual(b['previous']['metric_delta']['knn_preservation'], 0)
        self.assertEqual(b['visual']['status'], 'disabled')
        self.assertFalse(list(base.glob('.round-*')))

    def test_full_config_drift_and_damaged_source_prevent_application(self):
        self.review()
        path = self.root / 'config/analysis.yaml'
        original = json.loads(path.read_text())
        changed = json.loads(path.read_text())
        changed['analysis']['scanpy']['seed'] = 7
        write_json(path, changed)
        with self.assertRaisesRegex(ApplyError, 'complete frozen'):
            apply(self.root, 'session', 'round_000', 'second')
        write_json(path, original)
        source = self.root / 'Results/runs/first/scanpy/scanpy_parameters.json'
        source.write_text(source.read_text() + '\n')
        with self.assertRaisesRegex(ApplyError, 'source evidence changed'):
            apply(self.root, 'session', 'round_000', 'second')

    def test_interrupted_apply_recovers_same_run_without_double_change(self):
        import apply_scanpy_round as module
        self.review()
        original = module.atomic_json
        def interrupt(path, value):
            if path.name == 'applied.json':
                raise OSError('simulated interruption')
            original(path, value)
        with mock.patch.object(module, 'atomic_json', side_effect=interrupt), self.assertRaises(OSError):
            apply(self.root, 'session', 'round_000', 'second')
        record = apply(self.root, 'session', 'round_000', 'second')
        self.assertEqual(record['next_run_id'], 'second')
        self.assertEqual(load_project(self.root)['analysis']['scanpy']['neighbors']['n_neighbors'], 20)
        with self.assertRaises(ApplyError):
            apply(self.root, 'session', 'round_000', 'third')

    def test_escalation_beats_accept_and_terminal_round_cannot_continue(self):
        self.raw.update(accept_probability=0.95, escalate_probability=0.95)
        first = self.review()
        self.assertEqual(first['status'], 'review_required')
        with self.assertRaisesRegex(controller.ReviewError, 'stopped or requires review'):
            self.review()

    def test_failure_never_publishes_partial_round_and_disabled_vision_is_free(self):
        with mock.patch.object(controller, 'calculate_visual_metrics', side_effect=AssertionError('disabled')):
            self.review()
        with mock.patch.object(controller, '_write_immutable', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.review(session='failure')
        self.assertFalse(list((self.root / '.workflow/optimization/failure').glob('round_*')))
        self.assertFalse(list((self.root / '.workflow/optimization/failure').glob('.round-*')))

    def test_missing_task_evidence_and_path_traversal_fail_before_review(self):
        (self.root / '.workflow/runs/first/tasks/scanpy/task.COMPLETE').unlink()
        with self.assertRaisesRegex(ValueError, 'completion marker'):
            self.review()
        with self.assertRaisesRegex(ValueError, 'path-safe'):
            self.review(session='../escape')

    def test_benchmark_is_invariant_to_row_order_and_candidate_graph_k(self):
        from scautopilot.review.benchmark import calculate_scanpy_benchmarks
        path = self.root / 'Results/runs/first/scanpy/iterations/first/candidate_analysis.h5ad'
        first = calculate_scanpy_benchmarks(path, {'n_pcs': 30, 'n_neighbors': 10}, max_cells=30)
        data = self.ad.read_h5ad(path)
        target = path.with_name('reordered.h5ad')
        data[::-1].copy().write_h5ad(target)
        second = calculate_scanpy_benchmarks(target, {'n_pcs': 30, 'n_neighbors': 50}, max_cells=30)
        self.assertEqual(first, second)
        self.assertIsNotNone(first['embedding']['trustworthiness'])
        self.assertFalse(first['biology']['independent'])

    def test_sample_metadata_survives_reader_and_missing_values_are_not_inferred(self):
        import ast
        params = self.runner.build_parameters(self.root, load_project(self.root),
            load_samples(self.root, require_paths=False), self.root / 'out', 'r')
        notebook = json.loads((self.root / 'Scripts/Scanpy/Notebooks/scanpy_workflow.ipynb').read_text())
        reader = next(c for c in notebook['cells'] if c.get('id') == 'reader')
        namespace = {'Path': Path, 'ad': self.ad, 'pd': self.pd, 'PARAMETERS': params, 'GROUP_KEY': 'group',
            'sc': mock.Mock(read_10x_h5=mock.Mock(return_value=self.ad.AnnData(self.np.zeros((2, 3)))))}
        exec(compile(ast.parse(''.join(reader['source'])), 'reader', 'exec'), namespace)
        data = namespace['read_10x_matrix'](Path('fixture.h5'), 'prefix', '10x_h5')
        self.assertEqual(data.obs['sample_id'].tolist(), ['sample', 'sample'])
        self.assertEqual(data.obs['group'].tolist(), ['treated', 'treated'])
        self.assertEqual(data.obs['batch'].tolist(), ['batch1', 'batch1'])
        params['inputs']['prefix']['metadata']['condition'] = ''
        namespace['sc'].read_10x_h5.return_value = self.ad.AnnData(self.np.zeros((2, 3)))
        data = namespace['read_10x_matrix'](Path('fixture.h5'), 'prefix', '10x_h5')
        self.assertTrue(data.obs['condition'].isna().all())
        data.write_h5ad(self.root / 'metadata.h5ad')

    def test_reviewed_labels_require_explicit_boolean_independence(self):
        from scautopilot.review.benchmark import calculate_scanpy_benchmarks
        path = self.root / 'Results/runs/first/scanpy/iterations/first/candidate_analysis.h5ad'
        data = self.ad.read_h5ad(path)
        data.obs['cell_type'] = data.obs.pop('candidate_cell_type')
        data.uns['annotation_status'] = 'reviewed'
        for flag, expected in [(False, False), ('false', False), (True, True)]:
            data.uns['annotation_reference_independent'] = flag
            data.write_h5ad(path)
            actual = calculate_scanpy_benchmarks(path, {'n_pcs': 30}, max_cells=30)
            self.assertEqual(actual['biology']['independent'], expected)

    def test_model_accept_alone_cannot_end_search(self):
        self.raw['accept_probability'] = 1.0
        result = self.review()
        self.assertEqual(result['status'], 'next_candidate')
        self.assertEqual(result['incumbent_run_id'], 'first')
        decision = json.loads((self.root / '.workflow/optimization/session/round_000/decision.json').read_text())
        self.assertEqual(decision['acceptance_role'], 'advisory_only')

    def test_incumbent_restore_is_explicit_and_applied(self):
        self.review()
        apply(self.root, 'session', 'round_000', 'second')
        self.candidate('second')
        self.review('second')
        plan = json.loads((self.root / '.workflow/optimization/session/round_001/round_plan.json').read_text())
        self.assertTrue(plan['restore_incumbent'])
        self.assertEqual(plan['base_parameters']['n_neighbors'], 15)
        self.assertEqual(plan['current_parameters']['n_neighbors'], 20)
        self.assertEqual(plan['next_parameters']['n_neighbors'], 10)
        apply(self.root, 'session', 'round_001', 'third')
        self.candidate('third')
        self.review('third')

    def test_fixed_evaluation_survives_different_pca_capacity(self):
        self.raw['parameter'] = {name: float(name == 'n_pcs') for name in PARAMETERS}
        self.review()
        apply(self.root, 'session', 'round_000', 'second')
        self.candidate('second')
        self.review('second')
        base = self.root / '.workflow/optimization/session'
        a, b = [json.loads((base / r / 'state.json').read_text()) for r in ('round_000', 'round_001')]
        self.assertNotEqual(a['pca_n_comps'], b['pca_n_comps'])
        self.assertEqual(a['benchmark'], b['benchmark'])
        self.assertEqual(a['benchmark']['reference_mode'], 'frozen_session_baseline')

    def test_changed_independent_reference_cannot_compare(self):
        from scautopilot.review.benchmark import calculate_scanpy_benchmarks
        path = self.root / 'Results/runs/first/scanpy/iterations/first/candidate_analysis.h5ad'
        data = self.ad.read_h5ad(path)
        data.obs['cell_type'] = data.obs['candidate_cell_type']
        data.uns.update(annotation_status='reviewed', annotation_reference_independent=True)
        data.write_h5ad(path)
        first = calculate_scanpy_benchmarks(path, {'n_pcs': 30}, max_cells=30)
        # Keep dependent labels present: the explicitly independent column wins.
        self.assertTrue(first['biology']['independent'])
        data.obs['cell_type'] = ['A'] * 96
        data.write_h5ad(path)
        second = calculate_scanpy_benchmarks(path, {'n_pcs': 30}, max_cells=30)
        self.assertNotEqual(first['evaluation']['metadata_sha256'], second['evaluation']['metadata_sha256'])

    def test_no_silent_pc_clipping(self):
        from scautopilot.review.benchmark import calculate_scanpy_benchmarks
        path = self.root / 'Results/runs/first/scanpy/iterations/first/candidate_analysis.h5ad'
        with self.assertRaisesRegex(ValueError, 'silent clipping'):
            calculate_scanpy_benchmarks(path, {'n_pcs': 60})

    def test_full_cell_identity_not_just_sample(self):
        from scautopilot.review.benchmark import calculate_scanpy_benchmarks
        path = self.root / 'Results/runs/first/scanpy/iterations/first/candidate_analysis.h5ad'
        first = calculate_scanpy_benchmarks(path, {'n_pcs': 30}, max_cells=4)
        data = self.ad.read_h5ad(path)
        data = data[:-1].copy()
        other = path.with_name('different_cells.h5ad'); data.write_h5ad(other)
        with self.assertRaisesRegex(ValueError, 'complete cell and feature'):
            calculate_scanpy_benchmarks(other, {'n_pcs': 30}, max_cells=4, reference_h5ad=path)

    def test_tampered_incumbent_refuses_restore(self):
        self.review()
        apply(self.root, 'session', 'round_000', 'second')
        self.candidate('second'); self.review('second')
        source = self.root / '.workflow/optimization/session/round_000/state.json'
        state = json.loads(source.read_text()); state['parameters']['resolution'] = 1.0
        write_json(source, state)
        with self.assertRaisesRegex(ApplyError, 'base state'):
            apply(self.root, 'session', 'round_001', 'third')

    def test_visual_sample_is_stable_under_row_reordering(self):
        from scautopilot.review.visual import calculate_visual_metrics
        path = self.root / 'Results/runs/first/scanpy/iterations/first/candidate_analysis.h5ad'
        first = calculate_visual_metrics(path, max_cells=30)
        data = self.ad.read_h5ad(path)
        target = path.with_name('visual_reordered.h5ad')
        data[::-1].copy().write_h5ad(target)
        self.assertEqual(first, calculate_visual_metrics(target, max_cells=30))

    def test_mutated_decision_history_is_not_reinterpreted(self):
        self.review()
        apply(self.root, 'session', 'round_000', 'second')
        self.candidate('second')
        path = self.root / '.workflow/optimization/session/round_000/decision.json'
        decision = json.loads(path.read_text())
        decision['search']['no_improvement_streak'] = 0
        decision['search']['phase'] = 'layout'
        write_json(path, decision)
        with self.assertRaisesRegex(controller.ReviewError, 'identity changed'):
            self.review('second')


if __name__ == '__main__':
    unittest.main()
