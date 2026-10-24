"""Regression contracts for the 2026-10-16 project/runtime audit."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_core
from _common import (WorkflowError, execution_code_hashes, runtime_identity,
                     seal_recorded_outputs, signed_plan_digest, validate_recorded_outputs, update_results_index)
from validate_project import validate
import plan_workflow
import submit_workflow as submitter
from inspect_resources import choose
from inspect_run import sacct_usage
from submit_workflow import slurm_job_state, submit


class AuditRegressions(unittest.TestCase):
    def test_resume_rebinds_waiting_child_and_preserves_external_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = test_core.SkillTests().generate(Path(tmp), 'rna')
            run = root/'.workflow/runs/resume'; run.mkdir(parents=True)
            tasks = [plan_workflow.task('parent','trainer'), plan_workflow.task('child','trainer',['parent'])]
            plan = dict(run_id='resume',input_signature='s',code_signature='c',routes={},tasks=tasks)
            (run/'plan.json').write_text(json.dumps(plan))
            old = [{'task':'parent','status':'submitted','job_id':'101'},
                   {'task':'child','status':'submitted','job_id':'102',
                    'sbatch':['sbatch','--dependency','afterok:101:999'], 'throttle_dependencies':['888']}]
            (run/'submissions.json').write_text(json.dumps(old))
            cfg = {'scheduler':{'backend':'slurm','partitions':['cpu'],'max_parallel':1},
                   'analysis':{'task_commands':{'parent':['true'],'child':['true']}}}
            recommendation = {'recommendation':dict(partition='cpu',cpus=1,memory='1G',time='00:01:00')}
            calls = []
            def fake(command, **kwargs):
                calls.append(command)
                return b'201\n' if command[0]=='sbatch' else b''
            with patch.object(submitter,'validate',return_value={'status':'valid','input_signature':'s'}), \
                 patch.object(submitter,'load_project',return_value=cfg), \
                 patch.object(submitter,'completed_evidence',return_value=False), \
                 patch.object(submitter,'slurm_job_state',side_effect=lambda j:'FAILED' if j=='101' else 'PENDING'), \
                 patch.object(submitter,'inspect',return_value=recommendation), \
                 patch.object(submitter.subprocess,'check_output',side_effect=fake):
                outcome = submitter.submit(root,'resume',skip_full_validation=True)
            self.assertEqual(outcome['jobs']['child'],'102')
            repairs = [c for c in calls if c[0]=='scontrol']
            self.assertEqual(len(repairs),1)
            self.assertIn('Dependency=afterok:201:999,afterany:888',repairs[0])

    def test_dry_run_preserves_plan_and_submission_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = test_core.SkillTests().generate(Path(tmp),'rna')
            plan_workflow.plan(root,'scanpy','preview')
            run = root/'.workflow/runs/preview'; plan = (run/'plan.json').read_bytes()
            (run/'submissions.json').write_text('[]\n')
            submit(root,'preview',dry_run=True)
            self.assertEqual((run/'plan.json').read_bytes(),plan)
            self.assertEqual((run/'submissions.json').read_text(),'[]\n')
            self.assertTrue((run/'submission_preview.json').exists())

    def test_results_index_update_is_idempotent_and_preserves_manual_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); index = root/'RESULTS_INDEX.md'; index.write_text('# Manual index\n')
            artifact = root/'a.png'; artifact.write_bytes(b'fixture')
            update_results_index(root,'run','task',[artifact])
            first = index.read_text()
            update_results_index(root,'run','task',[artifact])
            self.assertEqual(first,index.read_text())
            self.assertTrue(first.startswith('# Manual index\n'))

    def test_empty_artifact_requires_explicit_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root/'result.tsv'; data.touch()
            record = root/'task_outputs.json'; record.write_text(json.dumps({'artifacts':[str(data)]}))
            with self.assertRaises(WorkflowError): seal_recorded_outputs([str(record)])
            record.write_text(json.dumps({'artifacts':[str(data)],'allow_empty_artifacts':[str(data)]}))
            seal_recorded_outputs([str(record)])
            self.assertTrue(validate_recorded_outputs([str(record)])[0])

    def test_rna_directory_child_change_invalidates_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = test_core.SkillTests().generate(Path(tmp), 'rna')
            before = validate(project)['input_signature']
            matrix = next(Path(tmp).rglob('matrix.mtx'))
            content = matrix.read_text()
            matrix.write_text(content + '\n')
            self.assertNotEqual(before, validate(project)['input_signature'])

    def test_r_source_is_signed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'Scripts').mkdir()
            script = root/'Scripts/test.R'; script.write_text('x <- 1\n')
            before = execution_code_hashes(root)
            script.write_text('x <- 2\n')
            self.assertNotEqual(before, execution_code_hashes(root))

    def test_runtime_identity_includes_samples_and_environment_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = test_core.SkillTests().generate(Path(tmp),'rna')
            for filename in ('samples.tsv','environments.tsv'):
                before = runtime_identity(root)
                path = root/'config'/filename
                path.write_text(path.read_text()+'\n')
                self.assertNotEqual(before,runtime_identity(root))

    def test_queued_code_mutation_refused_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = test_core.SkillTests().generate(Path(tmp), 'rna')
            plan_workflow.plan(root, 'scanpy', 'mutation')
            script = root/'Scripts/new_source.R'; script.write_text('changed <- TRUE\n')
            env = dict(os.environ, SCMO_HOST_ROLE='standalone')
            result = subprocess.run([sys.executable, str(root/'Scripts/Common/run_task.py'),
                '--project', str(root), '--run-id', 'mutation', '--task', 'scanpy'],
                env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('changed after planning', result.stderr)
            self.assertFalse((root/'.workflow/runs/mutation/tasks/scanpy/task.COMPLETE').exists())

    def test_plan_bookkeeping_is_not_scientific_identity(self):
        plan = {'tasks':[{'id':'a'}], 'input_signature':'x', 'status':'planned'}
        before = signed_plan_digest(plan)
        plan.update(status='submitted', job_ids={'a':'123'})
        self.assertEqual(before, signed_plan_digest(plan))
        plan['tasks'][0]['id'] = 'b'
        self.assertNotEqual(before, signed_plan_digest(plan))

    def test_custom_summary_has_output_contract(self):
        self.assertEqual(plan_workflow.task('workflow_summary','summary')['outputs'],
                         ['{task_dir}/task_outputs.json'])

    def test_completed_artifact_truncation_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root/'result.tsv'; data.write_text('gene\tvalue\nA\t1\n')
            record = root/'task_outputs.json'; record.write_text(json.dumps({'artifacts':[str(data)]}))
            seal_recorded_outputs([str(record)])
            self.assertTrue(validate_recorded_outputs([str(record)])[0])
            data.write_text('')
            self.assertFalse(validate_recorded_outputs([str(record)])[0])

    def test_purged_squeue_falls_back_to_sacct(self):
        error = subprocess.CalledProcessError(1, 'squeue', output=b'squeue: error: Invalid job id specified')
        with patch('submit_workflow.subprocess.check_output', side_effect=[error,b'COMPLETED|\n']):
            self.assertEqual(slurm_job_state('123'), 'COMPLETED')

    def test_controller_failure_does_not_trigger_history_retry(self):
        error = subprocess.CalledProcessError(1, 'squeue', output=b'Unable to contact slurm controller')
        with patch('submit_workflow.subprocess.check_output', side_effect=error) as query:
            with self.assertRaises(WorkflowError): slurm_job_state('123')
            self.assertEqual(query.call_count, 1)

    def test_rss_uses_job_step_peak(self):
        output = b'123|COMPLETED|00:01|2|6G||00:01|0:0|\n123.batch|COMPLETED|00:01|2||539580K|00:01|0:0|\n'
        with patch('inspect_run.subprocess.check_output', return_value=output):
            result = sacct_usage(['123'])['123']
        self.assertEqual(result['max_rss'], '539580K')
        self.assertEqual(result['max_rss_source'], '123.batch')

    def test_busy_healthy_capacity_can_queue(self):
        node = dict(name='n', partition='cpu', state='allocated', cpu_total=56,
                    real_memory_mb=257400, schedulable_cpu=0, schedulable_memory_mb=0)
        profile = {level:dict(cpus=2,memory='8G') for level in ('floor','target','ceiling')}
        result = choose([node], {'partitions':['cpu']}, profile)
        self.assertFalse(result['immediately_available'])
        self.assertEqual(result['cpus'], 2)
        node['state_detail'] = 'ALLOCATED+DRAIN'
        with self.assertRaises(WorkflowError): choose([node], {'partitions':['cpu']}, profile)

    def test_vmr_dmr_models_do_not_depend_on_each_other(self):
        tasks = plan_workflow.make_tasks({'methylvi_vmr_dmr':True}, {})
        models = [t for t in tasks if t['id'].startswith('methylvi_vmr_dmr_')]
        self.assertTrue(models)
        for task in models:
            self.assertIn('pooled_dmr_counts', task['dependencies'])
            self.assertFalse(any(d.startswith('methylvi_vmr_dmr_') for d in task['dependencies']))


if __name__ == '__main__':
    unittest.main()
