#!/usr/bin/env python3
"""Verify named producer artifacts and read H5AD in the actual consumer environment.

This is a fail-closed gate, not a scheduler, retry daemon, format converter, or
permission to ignore failed ancestors. Unrelated sibling tasks are not inputs.
"""
import argparse
import importlib.metadata
import json
from pathlib import Path
import sys

from _common import WorkflowError, host_role, sha256_file, write_json
from figures_comparison_evidence import task_evidence


def producer_closure(plan, task_id):
    tasks = {item['id']: item for item in plan['tasks']}
    active, seen, ordered = set(), set(), []

    def visit(name):
        if name in active:
            raise WorkflowError('Cycle in source dependencies: ' + name)
        if name not in tasks:
            raise WorkflowError('Missing source dependency: ' + name)
        if name in seen:
            return
        active.add(name)
        for dependency in tasks[name].get('dependencies', []):
            visit(dependency)
        active.remove(name)
        seen.add(name)
        ordered.append(tasks[name])

    visit(task_id)
    return ordered


def verify_producer_artifact(source):
    path = Path(source['path']).resolve()
    if not path.is_file() or sha256_file(path) != source['sha256']:
        raise WorkflowError('Source artifact missing or SHA-256 mismatch: ' + str(path))
    state = Path(source['run_dir'])
    plan = json.loads((state / 'plan.json').read_text())
    proof, producer = [], None
    for item in producer_closure(plan, source['task_id']):
        status = task_evidence(state, plan, item)
        proof.append({'task_id': item['id'], 'status_sha256': sha256_file(state / 'tasks' / item['id'] / 'task_status.json')})
        if item['id'] == source['task_id']:
            producer = status
    declared = []
    for record in producer['outputs']:
        p = Path(record)
        if p.name == 'task_outputs.json':
            declared.extend(json.loads(p.read_text())['artifacts'])
        else:
            declared.append(str(p))
    if path not in {Path(p).resolve() for p in declared}:
        raise WorkflowError('Source artifact is not declared by producer: ' + str(path))
    return {'path': str(path), 'sha256': source['sha256'], 'checked_tasks': proof,
            'input_signature': plan['input_signature'], 'code_signature': plan['code_signature']}


def read_h5ad_for_consumer(path):
    if host_role() == 'submit':
        raise WorkflowError('H5AD consumer compatibility must be checked on a compute allocation')
    import anndata
    try:
        return anndata.read_h5ad(path)
    except Exception as exc:
        # Preserve the original exception; give an actionable, non-mutating fix.
        raise WorkflowError(
            'H5AD consumer read failed: %s; consumer Python=%s, anndata=%s. '
            'Validate with the producer-compatible environment or a separately verified '
            'conversion. Do not retrain the model or upgrade a shared environment merely '
            'to fix serialization. Original error: %s' %
            (path, sys.executable, anndata.__version__, exc)) from exc


def verify_spec(spec):
    records = []
    for source in spec['sources']:
        proof = verify_producer_artifact(source)
        if source.get('format') == 'h5ad':
            data = read_h5ad_for_consumer(source['path'])
            if not data.obs_names.is_unique or not data.var_names.is_unique:
                raise WorkflowError('Duplicate cell/feature IDs in derived H5AD')
            if 'expected_cells' in source and data.n_obs != source['expected_cells']:
                raise WorkflowError('Derived H5AD cell count mismatch')
            import numpy as np
            for key in source.get('required_obsm', []):
                if key not in data.obsm or not np.isfinite(data.obsm[key]).all():
                    raise WorkflowError('Missing or nonfinite embedding: ' + key)
            proof.update(cells=data.n_obs, features=data.n_vars,
                         consumer_python=sys.executable,
                         anndata_version=importlib.metadata.version('anndata'))
        if sha256_file(source['path']) != source['sha256']:
            raise WorkflowError('Source changed during verification')
        records.append(proof)
    if not records:
        raise WorkflowError('At least one source is required')
    return {'status': 'passed', 'sources': records,
            'scope': 'Declared producers and transitive dependencies only; no unrelated sibling gate'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--task-dir', type=Path, required=True)
    args = parser.parse_args()
    if host_role() == 'submit':
        raise WorkflowError('Run this gate through a planned compute task')
    result = verify_spec(json.loads(args.spec.read_text()))
    write_json(args.output, result)
    write_json(args.task_dir / 'task_outputs.json', {'artifacts': [str(args.output.resolve())]})


if __name__ == '__main__':
    main()
