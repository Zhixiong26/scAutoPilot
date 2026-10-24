import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from _common import WorkflowError, write_json, sha256_file
from test_figures_comparison import mark_complete
from verify_derived_inputs import producer_closure, verify_producer_artifact, read_h5ad_for_consumer, verify_spec


class DerivedInputGateTests(unittest.TestCase):
    def fixture(self, root):
        tasks = [dict(id='prepare', dependencies=[]), dict(id='train', dependencies=['prepare']),
                 dict(id='failed_plot', dependencies=['train'])]
        plan = dict(tasks=tasks, input_signature='input', code_signature='code')
        write_json(root/'plan.json', plan)
        artifact = root/'embedding'; artifact.write_bytes(b'example')
        for item in tasks[:2]:mark_complete(root, plan, item, [artifact])
        write_json(root/'tasks/failed_plot/task_status.json', {'status':'failed'})
        return dict(path=str(artifact), sha256=sha256_file(artifact), run_dir=str(root), task_id='train')

    def test_failed_sibling_does_not_block_verified_producer(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec=self.fixture(Path(tmp));proof=verify_producer_artifact(spec)
            self.assertEqual([r['task_id'] for r in proof['checked_tasks']], ['prepare','train'])

    def test_failed_required_ancestor_still_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);spec=self.fixture(root)
            (root/'tasks/prepare/task.COMPLETE').unlink()
            with self.assertRaisesRegex(ValueError, 'completion marker'):verify_producer_artifact(spec)

    def test_mutated_or_undeclared_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);spec=self.fixture(root)
            Path(spec['path']).write_bytes(b'mutated')
            with self.assertRaisesRegex(WorkflowError, 'SHA-256'):verify_producer_artifact(spec)
            other=root/'other';other.write_bytes(b'other');spec.update(path=str(other),sha256=sha256_file(other))
            with self.assertRaisesRegex(WorkflowError, 'not declared'):verify_producer_artifact(spec)

    def test_cycles_and_missing_dependencies_rejected(self):
        with self.assertRaisesRegex(WorkflowError,'Cycle'):
            producer_closure({'tasks':[dict(id='a',dependencies=['a'])]},'a')
        with self.assertRaisesRegex(WorkflowError,'Missing'):
            producer_closure({'tasks':[dict(id='a',dependencies=['b'])]},'a')

    def test_consumer_read_error_reports_environment_without_mutating(self):
        import types
        fake=types.SimpleNamespace(__version__='old',read_h5ad=mock.Mock(side_effect=ValueError('nullable-string-array')))
        with mock.patch.dict(sys.modules,{'anndata':fake}),mock.patch('verify_derived_inputs.host_role',return_value='compute'):
            with self.assertRaisesRegex(WorkflowError,'nullable-string-array') as cm:read_h5ad_for_consumer('input.h5ad')
            self.assertIsInstance(cm.exception.__cause__,ValueError)
        with mock.patch('verify_derived_inputs.host_role',return_value='submit'):
            with self.assertRaisesRegex(WorkflowError,'compute allocation'):read_h5ad_for_consumer('input.h5ad')

    def test_real_h5ad_read_checks_saved_ids_and_coordinates(self):
        try:import anndata as ad;import numpy as np
        except ImportError:self.skipTest('anndata/numpy unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);spec=self.fixture(root);a=ad.AnnData(np.ones((3,2)));a.obsm['X_umap']=np.arange(6).reshape(3,2)
            path=Path(spec['path']);a.write_h5ad(path);spec.update(sha256=sha256_file(path),format='h5ad',expected_cells=3,required_obsm=['X_umap'])
            with mock.patch('verify_derived_inputs.host_role',return_value='compute'):
                result=verify_spec({'sources':[spec]});self.assertEqual(result['sources'][0]['cells'],3)
                b=read_h5ad_for_consumer(path);np.testing.assert_array_equal(a.obsm['X_umap'],b.obsm['X_umap'])
