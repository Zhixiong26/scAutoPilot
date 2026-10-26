#!/usr/bin/env python3
"""Audit a full analytical delivery, including custom and multi-run workflows.

This is an explicit delivery gate, not a scheduler or biological approval. Use
the user's requested routes, never infer scope from a possibly incomplete DAG.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from _common import write_json
from figures_comparison_evidence import ROUTES, read_json, sha, task_evidence, validate_manifest, review_state


def audit(project, run_id, routes, source_runs=(), annotation_run=None, required=()):
    root = Path(project).resolve()
    checks, plans = [], {}

    def check(name, operation):
        try:
            detail = operation()
            checks.append({'check': name, 'status': 'passed', 'detail': detail})
            return detail
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, StopIteration, AssertionError) as error:
            checks.append({'check': name, 'status': 'failed', 'detail': str(error) or name})
            return None

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def load_run(owner):
        require(owner not in ('', '.', '..') and '/' not in owner, 'invalid run ID')
        directory = root / '.workflow/runs' / owner
        plan = read_json(directory / 'plan.json')
        require(plan['run_id'] == owner, 'plan/run mismatch')
        require(bool(plan['tasks']), 'empty task plan')
        for item in plan['tasks']:
            task_evidence(directory, plan, item)
        plans[owner] = plan
        return {'run_id': owner, 'tasks': [x['id'] for x in plan['tasks']]}

    check('requested_routes', lambda: require(bool(routes) and set(routes) <= set(ROUTES), 'supply explicit supported routes'))
    owners = list(dict.fromkeys([run_id] + list(source_runs) + ([annotation_run] if annotation_run else [])))
    for owner in owners:
        check('task_evidence:' + owner, lambda owner=owner: load_run(owner))

    def publication():
        plan = plans[run_id]
        tasks = {x['id']: x for x in plan['tasks']}
        require('figures_comparison' in tasks, 'missing formal figures_comparison task; overview previews do not substitute')
        require('workflow_summary' in tasks, 'missing workflow_summary task')
        require('figures_comparison' in tasks['workflow_summary']['dependencies'], 'summary must depend on comparison')
        summary = read_json(root / '.workflow/runs' / run_id / 'workflow_summary.json')
        require(summary.get('status') == 'complete' and 'figures_comparison' in summary.get('verified_tasks', []),
                'summary has not verified comparison')
        path = Path(plan['result_dir']) / 'figures_comparison/delivery_manifest.json'
        manifest = validate_manifest(path)
        coverage = {x['route']: x for x in manifest['route_coverage']}
        for route in routes:
            row = coverage[route]
            require(row.get('selected') is True, 'requested route omitted: ' + route)
            require(row.get('status') == 'rendered' and row.get('entries', 0) > 0 or
                    row.get('status') == 'not_applicable' and bool(row.get('reason', '').strip()),
                    'route lacks delivery or explicit not-applicable reason: ' + route)
        names = {x['path'] for x in manifest['artifacts']}
        if manifest.get('panels'):
            require(bool(manifest.get('figures')), 'panels lack comparison atlas')
            for figure in manifest['figures']:
                files = figure['files']
                require(any(x.endswith('.pdf') for x in files) and
                        any(x.endswith('_preview.png') for x in files) and
                        any(x.endswith('.png') and not x.endswith('_preview.png') for x in files),
                        'atlas requires full PNG, PDF and preview')
            require(any(x.startswith('single_panels/') and x.endswith('.png') for x in names), 'single panels missing')
        if 'scanpy' in routes:
            panels = [x for x in manifest.get('panels', []) if x.get('route') == 'scanpy']
            require(any(x.get('column') in ('candidate_cell_type', 'cell_type') for x in panels),
                    'Scanpy cell-type delivery missing; diagnostic Leiden/cohort plots are insufficient')
            require(all(x.get('annotation_status') != 'candidate_annotation_incomplete' for x in panels), 'annotation incomplete')
        return {'manifest': str(path), 'sha256': sha(path)}

    delivered = check('publication_comparison', publication)
    if delivered:
        def review():
            path = Path(delivered['manifest'])
            record = root / '.workflow/runs' / run_id / 'figure_review.json'
            state = review_state(path, record)
            require(state == 'passed', 'visual review is ' + state)
            manifest, review = read_json(path), read_json(record)
            inspected = set(review['inspected'])
            expected = {x['path'] for x in manifest['artifacts']
                        if x['path'].endswith('_preview.png') or x['path'].startswith('dmr/') and x['path'].endswith('.png')}
            require(expected <= inspected, 'not all previews/DMR images inspected')
            require(not manifest.get('panels') or any(x.startswith('single_panels/') for x in inspected), 'single-panel review missing')
            return state
        check('visual_review', review)

    if annotation_run:
        def annotation():
            result = Path(plans[annotation_run]['result_dir'])
            candidate = read_json(result / 'annotation/candidate_delivery.json')
            require(candidate.get('source_run') in source_runs, 'annotation is not bound to a declared analysis source')
            source = read_json(Path(plans[candidate['source_run']]['result_dir']) / 'scanpy/completion_summary.json')
            require(candidate['analysis_signature'] == source['analysis_signature'], 'annotation analysis signature mismatch')
            require(candidate['placeholder_cells'] == 0, 'annotation contains placeholder cells')
            require(candidate['cells'] == source['n_cells'], 'annotation/source cell count differs')
            require(sha(candidate['source_h5ad']) == candidate['source_sha256'], 'annotation input changed')
            require(sha(result / 'annotation/candidate_annotated.h5ad') == candidate['derived_h5ad_sha256'], 'annotated H5AD changed')
            require(delivered is not None, 'formal delivery required to bind annotation')
            manifest = read_json(delivered['manifest'])
            inputs = {x['sha256'] for x in manifest['sources'] if x.get('kind') == 'derived_input' and x['path'].endswith('.h5ad')}
            require(candidate['derived_h5ad_sha256'] in inputs, 'publication does not use the declared annotated H5AD')
            return {'placeholder_cells': 0, 'biological_approval': candidate.get('approval', False)}
        check('annotation_binding', annotation)

    if 'scanpy' in routes:
        def notebook():
            candidates = [plans[x] for x in source_runs if x in plans] or [plans[run_id]]
            paths = [Path(x['result_dir']) / 'scanpy/completion_summary.json' for x in candidates]
            summaries = [read_json(x) for x in paths if x.is_file()]
            require(bool(summaries), 'Scanpy completion summary missing')
            for summary in summaries:
                book = read_json(summary['notebook'])
                code = [x for x in book['cells'] if x['cell_type'] == 'code' and ''.join(x.get('source', [])).strip()]
                require(bool(code) and any(x.get('execution_count') is not None for x in code), 'notebook has no executed code')
                require(not any(o.get('output_type') == 'error' for x in code for o in x.get('outputs', [])), 'notebook contains execution errors')
            return [x['notebook'] for x in summaries]
        check('executed_notebook', notebook)

    def artifact(name):
        path = Path(name)
        if not path.is_absolute():
            path = root / path
        require(path.is_file() and path.stat().st_size > 0, 'required artifact missing/empty: ' + str(path))
        return {'path': str(path), 'sha256': sha(path)}
    for name in required:
        check('required:' + str(name), lambda name=name: artifact(name))
    check('results_index', lambda: artifact('Results/RESULTS_INDEX.md'))
    failures = [x for x in checks if x['status'] == 'failed']
    return {'schema_version': 1, 'scope': 'full_analysis_delivery', 'run_id': run_id,
            'source_runs': list(source_runs), 'annotation_run': annotation_run, 'requested_routes': list(routes),
            'status': 'incomplete' if failures else 'complete', 'checks': checks,
            'failed_checks': [x['check'] for x in failures], 'grants_biological_approval': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--run-id', required=True, help='Run containing formal comparison and workflow summary')
    parser.add_argument('--routes', nargs='+', choices=ROUTES, required=True)
    parser.add_argument('--source-run', action='append', default=[])
    parser.add_argument('--annotation-run')
    parser.add_argument('--require', action='append', default=[], help='Additional user-requested files; repeatable')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.project, args.run_id, args.routes, args.source_run, args.annotation_run, args.require)
    write_json(args.output, report)
    print(report['status'] + ': ' + ', '.join(report['failed_checks']))
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
