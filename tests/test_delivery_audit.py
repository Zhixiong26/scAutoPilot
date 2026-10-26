"""Delivery completeness is stricter than successful tasks or an overview."""
import json
from pathlib import Path
import tempfile
import unittest
from test_figures_comparison import dummy_delivery, mark_complete, write_json, sha, delivery_record
from audit_delivery import audit
from record_figure_review import record


def complete(root):
    run, result, plan, manifest, _ = dummy_delivery(root)
    data = json.loads(manifest.read_text())
    for name in ('a.png', 'a.pdf'):
        (manifest.parent / name).write_bytes(b'fixture')
        data['artifacts'].append({'path': name, 'bytes': 7, 'sha256': sha(manifest.parent / name)})
    data['figures'][0]['files'] += ['a.png', 'a.pdf']
    data['panels'][0].update(route='scanpy', column='candidate_cell_type', annotation_status='candidate_auto_annotated_requires_review')
    for row in data['route_coverage']:
        row.update(selected=row['route'] == 'scanpy', entries=1 if row['route'] == 'scanpy' else 0,
                   status='rendered' if row['route'] == 'scanpy' else 'not_selected')
    write_json(manifest, data)
    figure = next(x for x in plan['tasks'] if x['id'] == 'figures_comparison')
    mark_complete(run, plan, figure, [manifest])
    identity = {x: data[x] for x in ('run_id', 'task', 'input_signature', 'code_signature', 'plan_sha256')}
    write_json(run / 'tasks/figures_comparison/task_outputs.json', delivery_record(manifest, identity))
    write_json(run / 'workflow_summary.json', {'status': 'complete', 'verified_tasks': ['scanpy', 'figures_comparison']})
    mark_complete(run, plan, plan['tasks'][-1], [run / 'workflow_summary.json'])
    book = result / 'executed.ipynb'
    write_json(book, {'cells': [{'cell_type': 'code', 'source': ['1+1'], 'execution_count': 1, 'outputs': []}]})
    write_json(result / 'scanpy/completion_summary.json', {'notebook': str(book)})
    (root / 'Results/RESULTS_INDEX.md').write_text('test delivery')
    record(root, 'test', 'passed', 'fixture', 'test image review', ['a_preview.png', 'single_panels/a.png'])
    return run, result, plan, manifest


class DeliveryAuditTests(unittest.TestCase):
    def test_planner_propagates_single_line_setting(self):
        from plan_workflow import make_tasks
        tasks = make_tasks({'scanpy': True}, {'figures_comparison': {'legend_single_line': True}})
        self.assertTrue(next(x for x in tasks if x['id'] == 'figures_comparison')['parameters']['legend_single_line'])
        with self.assertRaises(RuntimeError):
            make_tasks({'scanpy': True}, {'figures_comparison': {'legend_single_line': 'false'}})

    def test_complete_candidate_does_not_require_biological_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); complete(root)
            report = audit(root, 'test', ['scanpy'])
            self.assertEqual(report['status'], 'complete', report)
            self.assertFalse(report['grants_biological_approval'])

    def test_custom_success_and_preview_cannot_hide_missing_comparison(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run, result, plan, _ = complete(root)
            plan['tasks'] = plan['tasks'][:1]
            plan['routes'] = {}
            write_json(run / 'plan.json', plan)
            (result / 'overview_preview.png').write_bytes(b'preview')
            report = audit(root, 'test', ['scanpy'])
            self.assertIn('publication_comparison', report['failed_checks'])
            self.assertIn('missing formal', next(x['detail'] for x in report['checks'] if x['check'] == 'publication_comparison'))

    def test_missing_summary_is_not_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run, _, _, _ = complete(root)
            (run / 'workflow_summary.json').unlink()
            self.assertEqual(audit(root, 'test', ['scanpy'])['status'], 'incomplete')

    def test_pending_and_stale_review_fail(self):
        for stale in (False, True):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp); run, _, _, _ = complete(root)
                path = run / 'figure_review.json'
                if stale:
                    data = json.loads(path.read_text()); data['manifest_sha256'] = 'old'
                    write_json(path, data)
                else:
                    path.unlink()
                self.assertIn('visual_review', audit(root, 'test', ['scanpy'])['failed_checks'])

    def test_missing_pdf_and_additional_promised_file_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); _, _, _, manifest = complete(root)
            (manifest.parent / 'a.pdf').unlink()
            report = audit(root, 'test', ['scanpy'], required=['missing_dotplot.pdf'])
            self.assertEqual(report['status'], 'incomplete')
            self.assertIn('required:missing_dotplot.pdf', report['failed_checks'])

    def test_unselected_requested_route_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); complete(root)
            self.assertIn('publication_comparison', audit(root, 'test', ['scanpy', 'allcools'])['failed_checks'])

    def test_wrong_annotation_source_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); _, result, _, _ = complete(root)
            write_json(result / 'annotation/candidate_delivery.json', {'source_run': 'unrelated'})
            report = audit(root, 'test', ['scanpy'], ['test'], 'test')
            self.assertIn('annotation_binding', report['failed_checks'])


if __name__ == '__main__':
    unittest.main()
