"""Evidence regressions and small source adapters; no scientific recomputation."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'assets/project-template/Scripts/Common'))
from _common import signature, validate_recorded_outputs, write_json, WorkflowError
from plan_workflow import make_tasks
from figures_comparison_evidence import (ROUTES, sha, delivery_record, validate_manifest,
                                         review_state, task_evidence)
import figures_comparison as renderer

HAS_NUMERIC = all(importlib.util.find_spec(x) is not None for x in ('anndata', 'scanpy', 'numpy', 'PIL'))


def fixture(root, routes=('scanpy',)):
    analysis = {'methscan': {'vmr_thresholds': [0.1, 0.2]},
                'methylvi': {'feature_targets': [10, 20], 'supervised_umap_weights': [0.3]}}
    tasks = make_tasks({x: x in routes for x in ROUTES}, analysis)
    result = root / 'Results/runs/test'
    result.mkdir(parents=True)
    run_dir = root / '.workflow/runs/test'
    run_dir.mkdir(parents=True)
    plan = {'run_id': 'test', 'tasks': tasks, 'result_dir': str(result),
            'input_signature': 'input', 'code_signature': 'code'}
    write_json(run_dir / 'plan.json', plan)
    artifact = result / 'fixture.txt'; artifact.write_text('source')
    for item in tasks:
        if item['id'] in ('figures_comparison', 'workflow_summary'):
            continue
        mark_complete(run_dir, plan, item, [artifact])
    return run_dir, result, plan


def mark_complete(run_dir, plan, item, artifacts):
    directory = run_dir / 'tasks' / item['id']
    directory.mkdir(parents=True, exist_ok=True)
    outputs = directory / 'task_outputs.json'
    write_json(outputs, {'artifacts': [str(x) for x in artifacts]})
    write_json(directory / 'task_status.json', {'status': 'complete', 'return_code': 0,
        'command': ['fixture'], 'input_signature': plan['input_signature'], 'code_signature': plan['code_signature'],
        'task_signature': signature({'command': ['fixture'], 'parameters': item.get('parameters', {})}),
        'outputs': [str(outputs)]})
    (directory / 'task.COMPLETE').touch()


def dummy_delivery(root):
    run_dir, result, plan = fixture(root)
    output = result / 'figures_comparison'; output.mkdir()
    identity = {x: plan[x] for x in ('run_id', 'input_signature', 'code_signature')}
    identity.update(task='figures_comparison', plan_sha256=sha(run_dir / 'plan.json'))
    names = ['README.md', 'route_coverage.tsv', 'panel_composition.tsv', 'source_index.tsv', 'a_preview.png', 'single_panels/a.png']
    for name in names:
        path = output / name; path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'fixture-artifact')
    data = dict(identity, schema_version=1, status='rendered_verified', presentation_only=True,
                analysis_rerun=False, coordinates_recomputed=False,
                route_coverage=[{'route': x} for x in ROUTES], panels=[{'single_png': 'single_panels/a.png'}],
                figures=[{'files': ['a_preview.png']}],
                sources=[{'path': str(run_dir/'plan.json'), 'sha256': sha(run_dir/'plan.json'), 'kind': 'task_evidence'}],
                artifacts=[{'path': name, 'bytes': (output/name).stat().st_size, 'sha256': sha(output/name)} for name in names])
    manifest = output / 'delivery_manifest.json'; write_json(manifest, data)
    task = run_dir / 'tasks/figures_comparison'; task.mkdir()
    record = delivery_record(manifest, identity)
    write_json(task/'task_outputs.json', record)
    return run_dir, result, plan, manifest, record


class DeliveryEvidenceTests(unittest.TestCase):
    def test_inspection_and_resume_reject_a_damaged_delivery(self):
        from inspect_run import inspect
        from submit_workflow import completed_evidence
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir, result, plan, manifest, record = dummy_delivery(root)
            figure = next(x for x in plan['tasks'] if x['id'] == 'figures_comparison')
            mark_complete(run_dir, plan, figure, [manifest])
            write_json(run_dir/'tasks/figures_comparison/task_outputs.json', record)
            mark_complete(run_dir, plan, plan['tasks'][-1], [result/'fixture.txt'])
            with mock.patch('inspect_run.sacct_usage', return_value={}):
                state = inspect(root, 'test')
                self.assertEqual(state['status'], 'complete')
                self.assertEqual(state['visual_review_status'], 'pending')
                self.assertTrue(completed_evidence(run_dir, 'figures_comparison', 'input'))
                (manifest.parent/'a_preview.png').unlink()
                state = inspect(root, 'test')
                self.assertNotEqual(state['status'], 'complete')
                self.assertEqual(state['analysis_status'], 'complete')
                self.assertEqual(state['figure_delivery_status'], 'failed')
                self.assertFalse(completed_evidence(run_dir, 'figures_comparison', 'input'))

    def test_atomic_publication_recovery_and_concurrent_writer(self):
        import fcntl
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); run_dir,result,plan=fixture(root)
            coverage=[{'route':x,'selected':x=='scanpy','entries':0,
                       'status':'not_applicable' if x=='scanpy' else 'not_selected',
                       'reason':'fixture'} for x in ROUTES]
            original_write=renderer.write_json
            def interrupted(path, value):
                if Path(path).name=='task_outputs.json':
                    raise OSError('simulated crash after publish')
                return original_write(path,value)
            with (result/'.figures_comparison.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaisesRegex(ValueError,'publisher'):
                    renderer.run(root,'test')
            with mock.patch.object(renderer,'build_specs',return_value=({},coverage,[])), \
                    mock.patch.object(renderer,'render_groups',return_value=([],[],[])), \
                    mock.patch.object(renderer,'write_json',side_effect=interrupted):
                with self.assertRaisesRegex(OSError,'simulated crash'):
                    renderer.run(root,'test')
            manifest=result/'figures_comparison/delivery_manifest.json'
            digest=sha(manifest)
            with mock.patch.object(renderer,'render_groups',side_effect=AssertionError('must not redraw')):
                renderer.run(root,'test')
            self.assertEqual(sha(manifest),digest)
            self.assertTrue(validate_recorded_outputs([str(run_dir/'tasks/figures_comparison/task_outputs.json')])[0])

    def test_dag_enabled_disabled_and_routes(self):
        tasks = make_tasks({'scanpy': True}, {})
        self.assertEqual([x['id'] for x in tasks], ['scanpy', 'figures_comparison', 'workflow_summary'])
        self.assertEqual(tasks[1]['dependencies'], ['scanpy'])
        self.assertEqual(tasks[1]['environment'], 'scanpy_allcools')
        self.assertEqual(tasks[1]['outputs'], ['{task_dir}/task_outputs.json'])
        self.assertEqual(tasks[2]['dependencies'], ['figures_comparison'])
        self.assertEqual(len(make_tasks({'scanpy': True}, {'figures_comparison': {'enabled': False}})), 2)
        self.assertEqual(make_tasks({}, {}), [])
        with self.assertRaises(WorkflowError):
            make_tasks({'scanpy': True}, {'figures_comparison': {'enabled': 'false'}})
        for route in ROUTES:
            with self.subTest(route=route):
                items = make_tasks({route: True}, {})
                self.assertEqual(items[-1]['id'], 'workflow_summary')
                self.assertEqual(items[-2]['id'], 'figures_comparison')

    def test_all_artifacts_checked_for_absence_and_same_size_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir, result, plan, manifest, record = dummy_delivery(Path(temp))
            outputs = run_dir/'tasks/figures_comparison/task_outputs.json'
            self.assertEqual(validate_recorded_outputs([str(outputs)]), (True, None))
            path = manifest.parent/'single_panels/a.png'
            original = path.read_bytes()
            path.write_bytes(b'X'*len(original))
            self.assertFalse(validate_recorded_outputs([str(outputs)])[0])
            path.write_bytes(original); path.unlink()
            self.assertFalse(validate_recorded_outputs([str(outputs)])[0])

    def test_manifest_identity_and_path_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir, result, plan, manifest, record = dummy_delivery(Path(temp))
            data = json.loads(manifest.read_text())
            data['artifacts'][0]['path'] = '../outside'
            write_json(manifest, data)
            with self.assertRaisesRegex(ValueError, 'artifact path'):
                validate_manifest(manifest)
            record['delivery_evidence']['identity']['run_id'] = 'wrong'
            write_json(run_dir/'tasks/figures_comparison/task_outputs.json', record)
            self.assertFalse(validate_recorded_outputs([str(run_dir/'tasks/figures_comparison/task_outputs.json')])[0])

    def test_review_binds_manifest_and_inspected_files(self):
        from record_figure_review import record as review
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir, result, plan, manifest, outputs = dummy_delivery(root)
            item = next(x for x in plan['tasks'] if x['id'] == 'figures_comparison')
            task_dir = run_dir/'tasks/figures_comparison'
            write_json(task_dir/'task_status.json', {'status': 'complete', 'return_code': 0,
                'command': ['fixture'], 'input_signature': 'input', 'code_signature': 'code',
                'task_signature': signature({'command': ['fixture'], 'parameters': item['parameters']}),
                'outputs': [str(task_dir/'task_outputs.json')]})
            (task_dir/'task.COMPLETE').touch()
            self.assertEqual(review_state(manifest, run_dir/'figure_review.json'), 'pending')
            with self.assertRaisesRegex(ValueError, 'all previews'):
                review(root, 'test', 'passed', 'reviewer', 'inspected', ['a_preview.png'])
            review(root, 'test', 'passed', 'reviewer', 'inspected labels', ['a_preview.png', 'single_panels/a.png'])
            self.assertEqual(review_state(manifest, run_dir/'figure_review.json'), 'passed')
            (manifest.parent/'a_preview.png').write_bytes(b'changed')
            self.assertEqual(review_state(manifest, run_dir/'figure_review.json'), 'stale')

    def test_source_requires_all_ancestors_and_ignores_pending_self(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run_dir, result, plan = fixture(root)
            spec = next(x for x in plan['tasks'] if x['id'] == 'figures_comparison')['parameters']
            sources = renderer.Sources(root, plan, spec)
            sources.verify()
            (run_dir/'tasks/scanpy/task.COMPLETE').unlink()
            with self.assertRaisesRegex(ValueError, 'completion marker'):
                renderer.Sources(root, plan, spec)

    def test_source_change_and_unregistered_cross_run_link(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run_dir, result, plan = fixture(root)
            spec = next(x for x in plan['tasks'] if x['id'] == 'figures_comparison')['parameters']
            sources = renderer.Sources(root, plan, spec)
            sources.context = 'scanpy'; sources.file(result/'fixture.txt')
            (result/'fixture.txt').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'Source changed'):
                sources.verify()
            outside = root/'other.txt'; outside.write_text('data')
            link = result/'linked.txt'; link.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, 'unregistered cross-run'):
                sources.file(link)

    def test_legacy_output_record_remains_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp); (path/'artifact').touch()
            write_json(path/'task_outputs.json', {'artifacts': [str(path/'artifact')]})
            self.assertTrue(validate_recorded_outputs([str(path/'task_outputs.json')])[0])


@unittest.skipUnless(HAS_NUMERIC, 'source adapter fixtures require the plotting environment')
class SourceAdapterTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        import pandas as pd
        self.np, self.pd = np, pd
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write_embedding(self, path, candidate=False, ids=None):
        import anndata as ad
        np, pd = self.np, self.pd
        ids = ids or ['s_1','s_2','s_3','s_4']
        labels = ['A', 'B', 'A', 'B'][:len(ids)]
        obs = pd.DataFrame(index=ids)
        for col in ('candidate_cell_type' if candidate else 'cell_type', 'manual_celltype', 'rna_cell_type',
                    'methylVI_leiden', 'leiden', 'L1', 'cohort', 'sample_id'):
            obs[col] = pd.Categorical(labels)
        data = ad.AnnData(obs=obs)
        data.obsm['X_umap'] = np.arange(len(ids)*2).reshape(-1,2).astype(float)
        data.obsm['X_umap_after_harmony'] = data.obsm['X_umap'].copy()
        data.obsm['X_umap_target_weight_0p3'] = data.obsm['X_umap'] + 0.5
        for col in obs:
            data.uns[col+'_colors'] = ['#ff0000','#0000ff']
        path.parent.mkdir(parents=True, exist_ok=True); data.write_h5ad(path)
        return data

    def populate(self, routes):
        run_dir, result, plan = fixture(self.root, routes)
        spec = next(x for x in plan['tasks'] if x['id'] == 'figures_comparison')['parameters']
        for item in spec['models']:
            name, p = item['id'], item['parameters']
            if name == 'scanpy':
                path = result/'scanpy/iterations/test/candidate_analysis.h5ad'
                self.write_embedding(path, candidate=True)
                write_json(result/'scanpy/parameters.json', {'sample_palette': ['#ff0000','#0000ff']})
                write_json(result/'scanpy/completion_summary.json', {'run_id': 'test', 'annotation_key': 'candidate_cell_type',
                    'annotation_status': 'candidate', 'artifacts': [str(path)], 'parameters': str(result/'scanpy/parameters.json')})
            elif name.startswith('methscan_vmr_'):
                base = result/'methscan/06_scanpy'/('var_%s'%p['threshold'])
                ids = ['s_1','s_2','s_3'] if p['threshold'] == 0.1 else ['s_1','s_2','s_3','s_4']
                data = self.write_embedding(base/'objects/methscan_vmr.h5ad', ids=ids)
                (base/'tables').mkdir()
                table = data.obs.copy(); table['UMAP1'] = data.obsm['X_umap'][:,0]; table['UMAP2'] = data.obsm['X_umap'][:,1]
                table.to_csv(base/'tables/cell_embedding.tsv',sep='\t')
                self.pd.DataFrame({'pass_min_observed_vmrs': [True]*len(ids)}, index=ids).to_csv(base/'tables/cell_missingness_qc.tsv',sep='\t')
                write_json(base/'run_parameters.json', {'retained_cells':len(ids)})
                authority=result/'methscan/03_filtered/column_header.txt'; authority.parent.mkdir(exist_ok=True)
                authority.write_text('s_1\ns_2\ns_3\ns_4\n')
            elif name == 'allcools_features':
                base = result/'methylvi/allcools/features_20'
                self.write_embedding(base/'allcools.h5ad'); write_json(base/'cluster_summary.json', {'target_features':20})
            elif name == 'methscan_hypo_heatmaps':
                write_json(result/'methscan/hypo_dmr_heatmap_summary.json', {'status':'complete',
                    'plots': {'status':'complete', 'samples':[{'sample_id':'S','status':'no_dmrs','dmrs':0}]}})
            elif name.startswith('methylvi_') and 'features_' not in name:
                if name.startswith('methylvi_allcools_'):
                    base=result/'methylvi/allcools'/('features_%s'%p['features'])
                else:
                    base=result/'methylvi'/('vmr_dmr' if name.startswith('methylvi_vmr_dmr_') else 'vmr')/('var_%s'%p['threshold'])/('features_%s'%p['features'])
                self.write_embedding(base/'results/methylvi_embedding.h5ad')
                self.write_embedding(base/'results/supervised_umap/methylvi_supervised_umap.h5ad')
                write_json(base/'results/supervised_umap/supervised_umap_summary.json', {'status':'complete','target_key':'cell_type',
                    'target_weights':[0.3],'cells':4})
        return run_dir, result, plan, spec

    def test_explicit_display_palette_survives_h5ad_and_overrides_methscan_fallback(self):
        path = self.root / 'display.h5ad'
        data = self.write_embedding(path)
        data.obs['rna_cell_type'] = self.pd.Categorical(['T/NK', 'B', 'T/NK', 'B'])
        data.uns['rna_cell_type_display_order'] = ['B', 'T/NK']
        data.uns['rna_cell_type_display_palette'] = ['#112233', '#aabbcc']
        data.write_h5ad(path)
        source = mock.Mock()
        source.file.return_value = path
        obs, coordinates, colors = renderer.embedding(source, path)
        palette, order, origin = renderer.palette_for(obs, colors, 'rna_cell_type', methscan=True)
        self.assertEqual(order, ['B', 'T/NK'])
        self.assertEqual(palette, {'B': '#112233', 'T/NK': '#aabbcc'})
        self.assertEqual(origin['origin'], 'source_display_palette')
        self.assertTrue(self.np.array_equal(coordinates['X_umap'], data.obsm['X_umap']))

    def test_display_metadata_rejects_missing_duplicate_and_unknown_labels(self):
        obs = self.pd.DataFrame({'label': ['A', 'B']})
        for colors in [
            {'label_display_order': ['A', 'B']},
            {'label_display_palette': ['red', 'blue']},
            {'label_display_order': ['A', 'B'], 'label_display_palette': ['red']},
            {'label_display_order': ['A', 'A'], 'label_display_palette': ['red', 'blue']},
            {'label_display_order': ['A', 'C'], 'label_display_palette': ['red', 'blue']},
        ]:
            with self.subTest(colors=colors), self.assertRaises(ValueError):
                renderer.palette_for(obs, colors, 'label', methscan=True)

    def test_methscan_saved_categorical_palette_precedes_reconstruction(self):
        obs = self.pd.DataFrame({'label': self.pd.Categorical(['B', 'A'], categories=['A', 'B'])})
        palette, order, origin = renderer.palette_for(obs, {'label_colors': ['red', 'blue']}, 'label', methscan=True)
        self.assertEqual(palette, {'A': '#ff0000', 'B': '#0000ff'})
        self.assertEqual(origin['origin'], 'source_uns')
        _, _, fallback = renderer.palette_for(obs, {}, 'label', methscan=True)
        self.assertEqual(fallback['origin'], 'source_methscan_sorted_tab20')

    def test_seven_routes_candidate_fields_and_vmr_subsets(self):
        run_dir, result, plan, spec = self.populate(ROUTES)
        sources=renderer.Sources(self.root,plan,spec)
        groups, coverage, dmr=renderer.build_specs(self.root,plan,spec,sources)
        self.assertEqual(len(coverage),7)
        scanpy=groups['scanpy_ordinary'][0]
        self.assertEqual([p['column'] for p in scanpy],['candidate_cell_type','leiden','cohort'])
        self.assertEqual([len(r[0]['ids']) for r in groups['methscan_vmr_ordinary']],[3,4])
        self.assertEqual(groups['allcools_ordinary'][0][1]['column'],'L1')
        self.assertTrue(any(x['route']=='methscan_dmr' and x['status']=='not_applicable' for x in coverage))
        self.assertTrue(all(len(row)==2 for k,rows in groups.items() if k.endswith('supervised') for row in rows))
        sources.verify()

    def test_supervised_skip_and_missing_weight(self):
        run_dir, result, plan, spec = self.populate(('methylvi_allcools',))
        sources=renderer.Sources(self.root,plan,spec); sources.context='methylvi_allcools_10'
        base=result/'methylvi/allcools/features_10'
        path=base/'results/methylvi_embedding.h5ad'
        obs,coords,colors=renderer.embedding(sources,path)
        obs['cell_type']=self.pd.Categorical(['A']*4)
        summary=base/'results/supervised_umap/supervised_umap_summary.json'
        write_json(summary,{'status':'skipped','reason':'fewer than two real labels','target_key':'cell_type',
            'target_weights':[0.3],'cells':4,'coordinate_files':{},'figure_files':[]})
        panels,reason=renderer.supervised_panels(sources,base,(obs,coords,colors),'m','methylvi_allcools',spec)
        self.assertEqual(panels,[]); self.assertTrue(reason)
        obs['cell_type']=self.pd.Categorical(['A','B','A','B'])
        with self.assertRaisesRegex(ValueError,'unsupported supervised skip'):
            renderer.supervised_panels(sources,base,(obs,coords,colors),'m','methylvi_allcools',spec)

    def test_missing_planned_weight_and_duplicate_cells_fail(self):
        import anndata as ad
        run_dir,result,plan,spec=self.populate(('methylvi_allcools',))
        base=result/'methylvi/allcools/features_10'
        path=base/'results/supervised_umap/methylvi_supervised_umap.h5ad'
        data=ad.read_h5ad(path); del data.obsm['X_umap_target_weight_0p3']; data.write_h5ad(path)
        sources=renderer.Sources(self.root,plan,spec); sources.context='methylvi_allcools_10'
        ordinary=renderer.embedding(sources,base/'results/methylvi_embedding.h5ad')
        with self.assertRaisesRegex(ValueError,'embedding lacks'):
            renderer.supervised_panels(sources,base,ordinary,'model','methylvi_allcools',spec)
        path=base/'results/methylvi_embedding.h5ad'
        data=ad.read_h5ad(path); data.obs_names=['dup']*data.n_obs; data.write_h5ad(path)
        sources=renderer.Sources(self.root,plan,spec); sources.context='methylvi_allcools_10'
        with self.assertRaisesRegex(ValueError,'duplicate embedding'):
            renderer.embedding(sources,path)

    @unittest.skipUnless(os.environ.get('SCMO_FIGURE_SMOKE') == '1', 'render smoke requires a compute allocation')
    def test_render_publish_recover_and_tamper(self):
        run_dir,result,plan,spec=self.populate(('scanpy',))
        output=renderer.run(self.root,'test')
        manifest=output/'delivery_manifest.json'
        digest=sha(manifest)
        data=validate_manifest(manifest)
        self.assertEqual(len(data['panels']),3)
        self.assertTrue(validate_recorded_outputs([str(run_dir/'tasks/figures_comparison/task_outputs.json')])[0])
        for panel in data['panels']:
            self.assertEqual(renderer.image_info(output/panel['single_png']),[2400,2400])
        (run_dir/'tasks/figures_comparison/task_outputs.json').unlink()
        renderer.run(self.root,'test')
        self.assertEqual(sha(manifest),digest)
        (output/data['panels'][0]['single_png']).write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'checksum'):
            renderer.run(self.root,'test')


if __name__ == '__main__':
    unittest.main()
