import json
from pathlib import Path
import tempfile
import unittest

import test_core
from _common import WorkflowError, sha256_file, update_results_index, load_samples
from audit_runtime import audit, require_contract
from inspect_resources import choose
from validate_project import prepared_inventory
from plan_custom_workflow import plan_custom


class RuntimeDeliveryContracts(unittest.TestCase):
    def test_custom_plan_freezes_task_spec_and_uses_maintained_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = test_core.SkillTests().generate(Path(temp), 'rna')
            spec = root / 'config/custom_tasks.json'
            spec.write_text(json.dumps([{'name':'workflow_summary','profile':'summary'}]))
            result = plan_custom(root, spec, 'custom', 'scanpy')
            self.assertEqual(result['plan_identity_version'], 2)
            self.assertEqual(result['delivery_contract'], 'rna_full_v2')
            self.assertTrue(result['runtime_identity'])
            self.assertTrue((root/'tools/rna_overview_layout.py').is_file())
            self.assertEqual(result['tasks'][0]['outputs'], ['{task_dir}/task_outputs.json'])
            with self.assertRaisesRegex(WorkflowError, 'Preserve existing'):
                plan_custom(root, spec, 'custom', 'scanpy')
            external = Path(temp) / 'tasks.json'; external.write_text(spec.read_text())
            with self.assertRaisesRegex(WorkflowError, 'frozen under'):
                plan_custom(root, external, 'external', 'scanpy')

    def test_summary_hook_and_inspector_block_numerical_only_rna_delivery(self):
        import subprocess,sys
        from unittest.mock import patch
        from inspect_run import inspect
        with tempfile.TemporaryDirectory() as temp:
            root=test_core.SkillTests().generate(Path(temp),'rna')
            spec=root/'config/custom_tasks.json'
            spec.write_text(json.dumps([{'name':'workflow_summary','profile':'summary'}]))
            plan_custom(root,spec,'numeric_only','scanpy')
            result=subprocess.run([sys.executable,str(root/'Scripts/Common/run_task.py'),
                '--project',str(root),'--run-id','numeric_only','--task','workflow_summary'],
                capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            run=root/'.workflow/runs/numeric_only'
            report=json.loads((run/'delivery_audit.json').read_text())
            self.assertEqual(report['status'],'incomplete')
            self.assertIn('overview_requirements',report['failed_checks'])
            self.assertTrue((run/'tasks/workflow_summary/task.COMPLETE').exists())
            with patch('inspect_run.sacct_usage',return_value={}): summary=inspect(root,'numeric_only')
            self.assertEqual(summary['status'],'awaiting_complete_delivery')
            self.assertFalse((run/'workflow.COMPLETE').exists())

    def test_legacy_executor_is_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = test_core.SkillTests().generate(Path(temp), 'rna')
            self.assertEqual(audit(root)['status'], 'valid')
            executor = root / 'Scripts/Common/run_task.py'
            executor.write_text('print("legacy executor")\n')
            before = executor.read_bytes()
            with self.assertRaisesRegex(WorkflowError, 'update_results_index'):
                require_contract(root)
            self.assertEqual(before, executor.read_bytes())

    def test_invalid_master_index_configuration_fails_preflight(self):
        with tempfile.TemporaryDirectory() as temp:
            root = test_core.SkillTests().generate(Path(temp), 'rna')
            (root / 'Results/index_targets.json').write_text('{"additional_results_roots":"wrong"}')
            self.assertEqual(audit(root)['status'], 'invalid')

    def test_custom_embedding_cannot_bypass_shared_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = test_core.SkillTests().generate(Path(temp), 'rna')
            script = root / 'Scripts/custom_plot.py'
            script.write_text('fig = sc.pl.umap(data, return_fig=True)\nfig.savefig("plot.png")\n')
            config = root / 'config/analysis.yaml'
            data = json.loads(config.read_text())
            data['analysis']['task_commands'] = {'custom_plot':['{python}', '{project}/Scripts/custom_plot.py']}
            config.write_text(json.dumps(data))
            with self.assertRaisesRegex(WorkflowError, 'bypasses save_embedding'):
                require_contract(root)

    def test_index_compacts_tasks_and_preserves_cross_project_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); master = root / 'master/Results'
            for name in ('one', 'two'):
                results = root / name / 'Results'; results.mkdir(parents=True)
                (results / 'index_targets.json').write_text(json.dumps({'additional_results_roots':[str(master)]}))
                (results / 'RESULTS_INDEX.md').write_text('Human notes\n')
                file = results / 'plot.png'; file.write_bytes(b'fixture')
                for task in ('counts', 'plot'):
                    update_results_index(results, 'same-run', task, [file])
                text = (results / 'RESULTS_INDEX.md').read_text()
                self.assertTrue(text.startswith('Human notes'))
                self.assertEqual(text.count('### `same-run`'), 1)
                detail = next((results / 'Index/runs').glob('*.md')).read_text()
                self.assertIn('same-run / counts', detail)
                self.assertIn('same-run / plot', detail)
                update_results_index(results, 'same-run', 'plot', [file])
                self.assertEqual(text, (results / 'RESULTS_INDEX.md').read_text())
            self.assertEqual((master / 'RESULTS_INDEX.md').read_text().count('### `same-run`'), 2)

    def test_eligible_partitions_preserve_constraints_and_observed_capacity(self):
        nodes = [dict(name=n, partition=p, state=st, cpu_total=c, real_memory_mb=m,
                      schedulable_cpu=idle, schedulable_memory_mb=free, state_detail=detail)
                 for n,p,st,c,m,idle,free,detail in [
                     ('a','cpu','idle',8,64000,8,60000,''),
                     ('b','fat','allocated',32,128000,0,0,''),
                     ('c','bad','idle',32,128000,32,120000,''),
                     ('d','drained','idle',32,128000,32,120000,'IDLE+DRAIN'),
                     ('e','tiny','idle',1,2000,1,1000,'')]]
        profile = {k:dict(cpus=4,memory='8G') for k in ('floor','target','ceiling')}
        original = json.dumps(nodes)
        selected = choose(nodes, {'partitions':['cpu','fat','drained','tiny']}, profile)
        self.assertEqual(set(selected['eligible_partitions']), {'cpu','fat'})
        self.assertEqual(json.dumps(nodes), original)
        selected = choose(nodes, {'partitions':['cpu','fat'], 'exclude_nodes':['b']}, profile)
        self.assertEqual(selected['eligible_partitions'], ['cpu'])

    def test_derived_input_requires_matching_ids_hashes_and_no_raw_route(self):
        with tempfile.TemporaryDirectory() as temp:
            root = test_core.SkillTests().generate(Path(temp), 'rna')
            artifact = root / 'derived.h5ad'; artifact.write_bytes(b'abcd')
            manifest = root / 'config/prepared.json'
            rows = load_samples(root); ids = [r['sample_id'] for r in rows if r['include']]
            manifest.write_text(json.dumps({'sample_ids':ids,'artifacts':[
                {'path':str(artifact),'bytes':4,'sha256':sha256_file(artifact)}]}))
            cfg = {'analysis':{'prepared_inputs':{'kind':'derived_artifacts','manifest':str(manifest)}}}
            quick = prepared_inventory(root,cfg,'quick',set())
            full = prepared_inventory(root,cfg,'full',set())
            self.assertEqual(quick,full)
            with self.assertRaisesRegex(WorkflowError, 'without raw-data routes'):
                prepared_inventory(root,cfg,'full',{'scanpy'})
            artifact.write_bytes(b'efgh')
            with self.assertRaisesRegex(WorkflowError, 'SHA-256 mismatch'):
                prepared_inventory(root,cfg,'full',set())


if __name__ == '__main__':
    unittest.main()
