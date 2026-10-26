"""Categorized routing, legacy preservation and exploratory output regression tests."""
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

import test_core
from _common import WorkflowError, build_report_text, load_project, write_json
from plan_workflow import plan, close_routes
from plan_custom_workflow import plan_custom
from reserve_results import reserve
from result_paths import (infer_category, result_path, require_unused_result,
                          validate_plan_result, validate_output_commands)
from submit_workflow import submit


class ResultLayoutTests(unittest.TestCase):
    def test_qc_planner_rejects_obsolete_runtime_before_freezing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = test_core.SkillTests().generate(Path(temp), 'rna')
            (root / 'Scripts/Common/run_task.py').write_text('print("obsolete runtime")\n')
            result = subprocess.run([
                sys.executable, str(test_core.ROOT / 'scripts/plan_methylation_reads_qc.py'),
                '--project', str(root), '--spec', str(root / 'unused.json'), '--run-id', 'qc-test'],
                text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Runtime contract failed', result.stderr)
            self.assertFalse((root / '.workflow/run_projects').exists())

    def test_final_model_owns_prerequisite_features_and_iterations(self):
        for route, category in [('scanpy', 'scanpy'), ('methscan_dmr', 'methscan'),
                                ('allcools', 'allcools'), ('methylvi_vmr', 'methylvi'),
                                ('methylvi_allcools', 'methylvi'), ('methylvi_vmr_dmr', 'methylvi')]:
            self.assertEqual(infer_category(close_routes({route: True})), category)
        self.assertEqual(infer_category(close_routes({'scanpy': True, 'methylvi_vmr': True})), 'multiomics')
        for mode in ['methscan', 'methylvi']:
            self.assertEqual(infer_category({'methylation_iteration': True},
                                           {'methylation_iteration': [{'mode': mode}]}), mode)

    def test_results_link_and_legacy_plan_preservation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); project = root / 'executor'; project.mkdir()
            owner = root / 'owner/Results'; owner.mkdir(parents=True)
            (project / 'Results').symlink_to(owner, target_is_directory=True)
            path = result_path(project, 'trial', 'methylvi')
            self.assertEqual(path, owner / 'runs/methylvi/trial')
            legacy = {'run_id': 'old', 'result_dir': str(owner / 'runs/old')}
            before = dict(legacy); validate_plan_result(project, legacy)
            self.assertEqual(legacy, before)
            plan_v2 = dict(result_layout_version=2, result_category='methylvi',
                           run_id='trial', result_dir=str(path))
            validate_plan_result(project, plan_v2)
            plan_v2['result_dir'] = str(owner / 'runs/trial')
            with self.assertRaises(WorkflowError):
                validate_plan_result(project, plan_v2)

    def test_reservation_preserves_existing_output_and_blocks_aliases(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = reserve(root, 'weight-search', 'methylvi', ['source'])
            manifest = json.loads((path / 'result_manifest.json').read_text())
            self.assertEqual(manifest['status'], 'reserved')
            (path / 'keep.txt').write_text('preserve')
            for category in ['methylvi', 'allcools']:
                with self.assertRaises(WorkflowError):
                    reserve(root, 'weight-search', category)
            self.assertEqual((path / 'keep.txt').read_text(), 'preserve')
            (root / 'Results/runs/legacy').mkdir()
            with self.assertRaises(WorkflowError):
                require_unused_result(root, 'legacy', 'scanpy')
            for bad in ['../escape', 'bad/name', '..', '', 'run*']:
                with self.assertRaises(WorkflowError):
                    result_path(root, bad, 'scanpy')
            with self.assertRaises(WorkflowError):
                result_path(root, 'trial', 'methlvi')
            (root / 'Results/runs/scanpy').symlink_to(root)
            with self.assertRaises(WorkflowError):
                result_path(root, 'escape', 'scanpy')

    def test_custom_command_uses_plan_output_root_but_may_read_old_inputs(self):
        validate_output_commands({'plot': ['python', 'plot.py', '--source',
                                          '/study/Results/runs/legacy/data', '--output', '{result_dir}/publication']})
        for command in [['--output', '{project}/Results/runs/{run_id}/plot'],
                        ['--outdir=/study/Results/runs/plot']]:
            with self.assertRaises(WorkflowError):
                validate_output_commands({'plot': command})

    def test_generated_custom_dag_writes_categorized_output_and_index(self):
        with tempfile.TemporaryDirectory() as temp:
            root = test_core.SkillTests().generate(Path(temp), 'rna')
            self.assertTrue((root / 'AGENTS.md').is_file())
            self.assertTrue((root / 'tools/reserve_results.py').is_file())
            cfg_path = root / 'config/analysis.yaml'; cfg = json.loads(cfg_path.read_text())
            writer = root / 'tools/write_fixture.py'
            writer.write_text('import json,sys\nfrom pathlib import Path\n'
                              'p=Path(sys.argv[1]); p.mkdir(parents=True)\n'
                              '(p/"metric.tsv").write_text("value\\n1\\n")\n'
                              'Path(sys.argv[2]).write_text(json.dumps({"artifacts":[str(p/"metric.tsv")]}))\n')
            cfg['analysis']['task_commands']['custom'] = [
                '{python}', '{project}/tools/write_fixture.py', '{result_dir}/tables', '{task_dir}/task_outputs.json']
            write_json(cfg_path, cfg)
            spec = root / 'config/tasks.json'
            write_json(spec, [{'name': 'custom', 'profile': 'summary'}])
            with self.assertRaises(WorkflowError):
                plan_custom(root, spec, 'unspecified')
            planned = plan_custom(root, spec, 'benchmark-test', 'benchmark')
            self.assertEqual(planned['result_category'], 'benchmark')
            submit(root, 'benchmark-test')
            output = root / 'Results/runs/benchmark/benchmark-test/tables/metric.tsv'
            self.assertTrue(output.is_file())
            self.assertFalse((root / 'Results/runs/benchmark-test').exists())
            detail = next((root / 'Results/Index/runs').glob('*.md')).read_text()
            self.assertIn(str(output), detail)

    def test_builtin_plan_records_owner_and_collision_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = test_core.SkillTests().generate(Path(temp), 'rna')
            p = plan(root, 'scanpy', 'rna-test')
            self.assertEqual(p['result_dir'], str(root / 'Results/runs/scanpy/rna-test'))
            self.assertEqual(p['result_layout_version'], 2)
            reserve(root, 'exploration', 'scanpy')
            with self.assertRaises(WorkflowError):
                plan(root, 'scanpy', 'exploration')
