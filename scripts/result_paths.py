#!/usr/bin/env python3
"""One categorized result-root contract for planned and exploratory analyses."""
from pathlib import Path
import re

from _common import WorkflowError

CATEGORIES = ('scanpy', 'methscan', 'vmrseq', 'allcools', 'methylvi',
              'multiomics', 'benchmark', 'methylation_qc')


def validate_run_id(run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', run_id):
        raise WorkflowError('run-id must be a path-safe identifier (1–128 characters)')


def infer_category(routes, analysis=None):
    """Classify the final analysis, not prerequisites or the run-name prefix."""
    enabled = {key for key, value in routes.items() if value}
    owners = set()
    if 'scanpy' in enabled:
        owners.add('scanpy')
    if any(key.startswith('methylvi_') for key in enabled):
        owners.add('methylvi')
    elif 'allcools' in enabled:
        owners.add('allcools')
    elif enabled & {'methscan_vmr', 'methscan_dmr'}:
        owners.add('methscan')
    if 'methylation_iteration' in enabled:
        modes = {row['mode'] for row in (analysis or {}).get('methylation_iteration', [])}
        if not modes or not modes <= {'methscan', 'methylvi'}:
            raise WorkflowError('Iteration category requires explicit source modes')
        owners.update(modes)
    if not owners:
        raise WorkflowError('Cannot infer result category; provide an explicit --category')
    return next(iter(owners)) if len(owners) == 1 else 'multiomics'


def result_path(project, run_id, category):
    validate_run_id(run_id)
    if category not in CATEGORIES:
        raise WorkflowError('Unknown result category: %s; choose %s' % (category, ', '.join(CATEGORIES)))
    runs = (Path(project).resolve() / 'Results').resolve() / 'runs'
    path = runs / category / run_id
    # Category/run symlinks must not redirect new writes outside their category.
    if (runs / category).is_symlink() or path.is_symlink():
        raise WorkflowError('New result category/run must be a real directory: %s' % path)
    return path


def require_unused_result(project, run_id, category):
    path = result_path(project, run_id, category)
    runs = path.parent.parent
    conflicts = [runs / run_id] + list(runs.glob('*/' + run_id))
    if any(p.exists() or p.is_symlink() for p in conflicts):
        raise WorkflowError('Result run ID already exists; preserve it and choose a new ID: ' + run_id)
    return path


def validate_plan_result(project, plan):
    """Legacy plans retain recorded paths; new plans must match the frozen category."""
    if plan.get('result_layout_version') != 2:
        return
    expected = result_path(project, plan['run_id'], plan.get('result_category'))
    if Path(plan['result_dir']).resolve() != expected:
        raise WorkflowError('Plan result_dir does not match its frozen category')


def validate_output_commands(commands):
    """Reject the common custom-adapter bypass before a new plan is written."""
    flags = {'--output', '--out', '--outdir', '--output-dir', '--results-dir', '--result-dir'}
    for task_id, command in commands.items():
        if not isinstance(command, list):
            continue
        for index, token in enumerate(command):
            value = str(token)
            output_argument = index > 0 and command[index - 1] in flags
            output_assignment = any(value.startswith(flag + '=') for flag in flags)
            if (output_argument or output_assignment) and 'Results/runs' in value:
                raise WorkflowError('Custom output for %s must use {result_dir}, not a hardcoded Results/runs path' % task_id)
