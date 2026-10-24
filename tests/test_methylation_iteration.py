"""Executable methylation iteration: boundaries, reuse, DAG and tiny analyses."""
import copy
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
from scautopilot.review.methylation import (validate_spec, next_trial, guarded_compare,
    fingerprint, source_evidence, execute, derive, digest_array, digest_graph, read_representation)
from _common import signature, write_json, task_is_implemented
from plan_workflow import make_tasks


def spec(mode='methscan'):
    return {'id': mode, 'mode': mode, 'source_run': 'source', 'source_task': 'source_task',
        'source_h5ad': 'Results/runs/source/source.h5ad',
        'baseline': {'n_pcs': 5, 'n_neighbors': 8, 'resolution': 0.8, 'min_dist': 0.5},
        'grids': {'n_pcs': [3, 5] if mode == 'methscan' else [5], 'n_neighbors': [5, 8, 12],
                  'resolution': [0.4, 0.8, 1.2], 'min_dist': [0.3, 0.5]},
        'sample_key': 'sample_id', 'label_key': 'cell_type', 'qc_keys': ['depth'],
        'max_rounds': 3, 'evaluation_cells': 80, 'evaluation_k': 5, 'confirmation_seeds': [11, 23]}


class PolicyTests(unittest.TestCase):
    def test_modes_and_strict_parameters(self):
        for mode in ('methscan', 'methylvi'):
            self.assertEqual(validate_spec(spec(mode))['mode'], mode)
        for change in ({'mode': 'dmr'}, {'raw_p': 0.01}, {'max_rounds': 0},
                       {'evaluation_cells': 100000}, {'min_seed_ari': float('nan')}, {'id': '../bad'}):
            with self.assertRaises(ValueError):
                validate_spec(dict(spec(), **change))

    def test_no_latent_truncation(self):
        value = spec('methylvi'); value['grids']['n_pcs'] = [3, 5]
        with self.assertRaises(ValueError): validate_spec(value)

    def test_grid_does_not_repeat_or_cross_representation_capacity(self):
        value = validate_spec(spec()); value['grids']['n_pcs'] = [5, 20]
        value['grids']['resolution'] = [0.8]; value['grids']['n_neighbors'] = [8]
        result = next_trial(value['baseline'], set(), value, 'science', 80, 5)
        self.assertIsNone(result[0]); self.assertEqual(result[2][0]['reason'], 'outside_retained_representation')
        value = validate_spec(spec())
        params, axis, _ = next_trial(value['baseline'], set(), value, 'science', 80, 5)
        self.assertEqual(axis, 'resolution')
        other = next_trial(value['baseline'], {fingerprint(params)}, value, 'science', 80, 5)
        self.assertNotEqual(params, other[0])

    def test_baseline_guard_prevents_drift(self):
        from test_iteration_search import state
        baseline, incumbent, candidate = state(), state('inc'), state('candidate')
        incumbent['clustering']['silhouette'] += 0.1
        incumbent['embedding']['trustworthiness'] -= 0.009
        candidate = copy.deepcopy(incumbent)
        candidate['clustering']['silhouette'] += 0.1
        candidate['embedding']['trustworthiness'] -= 0.009
        self.assertFalse(guarded_compare(candidate, incumbent, baseline, {})['selected'])

    def test_dag_has_no_raw_or_training_dependencies(self):
        tasks = make_tasks({'methylation_iteration': True}, {'methylation_iteration': [spec(), spec('methylvi')]})
        self.assertEqual([t['id'] for t in tasks], ['methylation_iter_methscan', 'methylation_iter_methylvi', 'workflow_summary'])
        self.assertTrue(all(not t['dependencies'] for t in tasks[:2]))
        self.assertTrue(all(task_is_implemented(t['id'], {}) for t in tasks))
        with self.assertRaises(Exception):
            make_tasks({'methylation_iteration': True}, {'methylation_iteration': [spec(), spec()]})

    def test_login_guard_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch('_common.host_role', return_value='submit'):
            out = Path(tmp) / 'output'
            with self.assertRaisesRegex(ValueError, 'compute'):
                execute(tmp, spec(), out)
            self.assertFalse(out.exists())


class NumericTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import anndata, numpy, pandas, scanpy
        cls.ad, cls.np, cls.pd, cls.sc = anndata, numpy, pandas, scanpy

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT / 'assets/project-template/Scripts/Common', self.root / 'Scripts/Common')
        self.env = mock.patch.dict(os.environ, {'SCMO_HOST_ROLE': 'standalone'})
        self.env.start(); self.addCleanup(self.env.stop)
        rng = self.np.random.RandomState(17)
        rep = self.np.vstack([rng.normal(i * 5, 0.5, (40, 5)) for i in range(2)]).astype('float32')
        self.obj = self.ad.AnnData(X=rep.copy(), obs=self.pd.DataFrame({
            'sample_id': ['s1', 's2'] * 40, 'cell_type': ['A'] * 40 + ['B'] * 40,
            'depth': rng.randint(10, 500, 80)}, index=['cell_%03d' % i for i in range(80)]))
        self.obj.obsm['X_pca'] = rep.copy(); self.obj.obsm['X_methylVI'] = rep.copy()
        self.sc.pp.neighbors(self.obj, use_rep='X_pca', n_neighbors=8, random_state=0)
        self.sc.tl.leiden(self.obj, resolution=0.8, random_state=0)
        self.sc.tl.umap(self.obj, min_dist=0.5, spread=1, random_state=0)

    def source(self, mode='methscan'):
        value = validate_spec(spec(mode))
        if mode == 'methylvi':
            self.obj.uns['neighbors']['params']['use_rep'] = 'X_methylVI'
            self.obj.obs['methylVI_leiden'] = self.obj.obs['leiden'].copy()
            self.obj.uns['methylVI_leiden'] = copy.deepcopy(self.obj.uns['leiden'])
        source = self.root / value['source_h5ad']; source.parent.mkdir(parents=True, exist_ok=True)
        self.obj.write_h5ad(source)
        directory = self.root / '.workflow/runs/source'
        task_dir = directory / 'tasks/source_task'; task_dir.mkdir(parents=True)
        item = {'id': 'source_task', 'parameters': {}}
        write_json(directory / 'plan.json', {'result_dir': str(source.parent), 'input_signature': 'input', 'code_signature': 'code', 'tasks': [item]})
        write_json(task_dir / 'task_outputs.json', {'artifacts': [str(source)]})
        write_json(task_dir / 'task_status.json', {'status': 'complete', 'return_code': 0,
            'input_signature': 'input', 'code_signature': 'code', 'command': [],
            'task_signature': signature({'command': [], 'parameters': {}}),
            'outputs': [str(task_dir / 'task_outputs.json')]})
        (task_dir / 'task.COMPLETE').touch()
        return value, source

    def test_reuse_invariants_and_wrong_baseline(self):
        value, source = self.source()
        obj = read_representation(source, value)
        old = value['baseline']
        partition = derive(obj, old, dict(old, resolution=0.4), 0)
        self.assertEqual(digest_graph(obj.obsp['connectivities']), digest_graph(partition.obsp['connectivities']))
        self.assertEqual(digest_array(obj.obsm['X_umap']), digest_array(partition.obsm['X_umap']))
        layout = derive(obj, old, dict(old, min_dist=0.3), 0)
        self.assertTrue(layout.obs['iteration_leiden'].equals(obj.obs['iteration_leiden']))
        altered = copy.deepcopy(value); altered['baseline']['min_dist'] = 0.1
        with self.assertRaisesRegex(ValueError, 'min_dist'):
            read_representation(source, altered)

    def test_source_requires_completion_and_ownership(self):
        value, source = self.source()
        self.assertEqual(source_evidence(self.root, value)['source_h5ad'], str(source))
        other = source.parent / 'other.h5ad'; shutil.copy2(source, other)
        with self.assertRaisesRegex(ValueError, 'owned'):
            source_evidence(self.root, dict(value, source_h5ad=str(other)))
        (self.root / '.workflow/runs/source/tasks/source_task/task.COMPLETE').unlink()
        with self.assertRaisesRegex(ValueError, 'completion'):
            source_evidence(self.root, value)

    def test_methscan_full_loop(self):
        self.run_loop('methscan')

    def test_methylvi_full_loop(self):
        self.run_loop('methylvi')

    def test_variable_latent_summary(self):
        import importlib.util
        from types import SimpleNamespace
        path = ROOT / 'assets/project-template/Scripts/Methylvi/vmr_dmr/03_summarize_vmr_dmr_models.py'
        module_spec = importlib.util.spec_from_file_location('vmr_dmr_summary_fixture', path)
        module = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(module)
        obj = SimpleNamespace(n_obs=80, n_vars=3, obsm={'X_methylVI': self.np.zeros((80, 3))})
        self.assertEqual(module.validate_embedding_shape(obj, {'n_latent': 3}, 80), 3)
        with self.assertRaises(ValueError): module.validate_embedding_shape(obj, {'n_latent': 20}, 80)
        with self.assertRaises(ValueError): module.validate_embedding_shape(obj, {'n_latent': True}, 80)

    def test_generated_dag_end_to_end(self):
        from _common import SAMPLE_COLUMNS, write_tsv
        from plan_workflow import plan
        from submit_workflow import submit
        from inspect_run import inspect as inspect_run
        value, _ = self.source()
        value['max_rounds'] = 1
        shutil.copytree(ROOT / 'assets/project-template', self.root, dirs_exist_ok=True)
        shutil.copytree(ROOT / 'scripts', self.root / 'tools')
        shutil.copytree(ROOT / 'scautopilot', self.root / 'tools/scautopilot')
        (self.root / 'Data/fixture').mkdir(parents=True)
        write_json(self.root / 'config/project.yaml', {'schema_version': 2, 'project': {'id': 'synthetic'}})
        write_json(self.root / 'config/analysis.yaml', {'schema_version': 2,
            'analysis': {'methylation_iteration': [value]}})
        profile = {'floor': {'cpus': 1, 'memory': '1G'},
                   'target': {'cpus': 2, 'memory': '2G', 'time': '00:05:00'},
                   'ceiling': {'cpus': 2, 'memory': '4G'}}
        write_json(self.root / 'config/scheduler.yaml', {'schema_version': 2, 'backend': 'local',
            'local': {'max_threads': 2, 'max_memory': '4G'},
            'profiles': {k: profile for k in ('default', 'plot', 'summary')}})
        write_tsv(self.root / 'config/samples.tsv', SAMPLE_COLUMNS,
            [{'sample_id': 's1', 'include': '1', 'allc_root': 'Data/fixture'}])
        write_tsv(self.root / 'config/environments.tsv',
            ['stage', 'python', 'executable', 'version_command', 'required'],
            [{'stage': s, 'python': sys.executable, 'executable': sys.executable, 'required': '1'}
             for s in ('orchestrator', 'scanpy_allcools')])
        payload = plan(self.root, 'methylation_iteration', 'screen')
        self.assertEqual(len(payload['tasks']), 2)
        preflight = json.loads((self.root / '.workflow/runs/screen/preflight.json').read_text())
        self.assertEqual(preflight['counts']['allc_cells'], 0)
        submit(self.root, 'screen')
        result = inspect_run(self.root, 'screen')
        self.assertEqual(result['status'], 'complete', result)
        index = (self.root / 'Results/RESULTS_INDEX.md').read_text()
        pages = list((self.root / 'Results/Index/runs').glob('screen-*.md'))
        self.assertEqual(len(pages), 1)
        self.assertIn(pages[0].relative_to(self.root / 'Results').as_posix(), index)
        self.assertIn('methylation_iter_', pages[0].read_text())

    def run_loop(self, mode):
        from figures_comparison_evidence import sha
        value, source = self.source(mode)
        before = sha(source)
        expected = source_evidence(self.root, value)
        output = self.root / 'output'
        summary = execute(self.root, value, output, expected)
        self.assertEqual(before, sha(source))
        self.assertEqual(summary['rounds'], 3)
        self.assertFalse(summary['model_retrained'])
        self.assertFalse(summary['features_recomputed'])
        self.assertFalse(summary['biological_approval'])
        self.assertEqual(len(list((output / 'figures_comparison').glob('*.png'))), 6)
        manifest = json.loads((output / 'iteration_manifest.json').read_text())
        for artifact in manifest['artifacts']:
            self.assertEqual(artifact['sha256'], sha(output / artifact['path']))
        kept = self.ad.read_h5ad(output / 'selected_embedding.h5ad')
        self.assertTrue(self.np.array_equal(kept.obsm['X_rep'], self.obj.obsm['X_pca']))
        resumed = read_representation(output / 'selected_embedding.h5ad',
                                      dict(value, baseline=summary['parameters']))
        self.assertTrue(self.np.array_equal(resumed.obsm['X_rep'], kept.obsm['X_rep']))
        with self.assertRaises(FileExistsError): execute(self.root, value, output, expected)
        bad = dict(expected, source_status_sha256='bad')
        with self.assertRaisesRegex(ValueError, 'changed after planning'):
            execute(self.root, value, self.root / 'wrong', bad)


if __name__ == '__main__':
    unittest.main()
