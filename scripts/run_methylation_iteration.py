#!/usr/bin/env python3
"""Execute a planned retained-representation MethSCAn/MethylVI iteration task."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent.parent)]
from _common import host_role, write_json
from scautopilot.review.methylation import execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--task', required=True)
    args = parser.parse_args()
    if host_role() == 'submit':
        raise ValueError('submit this task through the DAG on a compute node')
    if os.environ.get('SLURM_CPUS_PER_TASK'):
        for name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMBA_NUM_THREADS'):
            os.environ[name] = os.environ['SLURM_CPUS_PER_TASK']
    root = args.project.resolve()
    for value in (args.run_id, args.task):
        if not value or Path(value).name != value or value in {'.', '..'}:
            raise ValueError('invalid run/task identifier')
    directory = root / '.workflow/runs' / args.run_id
    plan = json.loads((directory / 'plan.json').read_text())
    task = next(x for x in plan['tasks'] if x['id'] == args.task)
    if not args.task.startswith('methylation_iter_'):
        raise ValueError('not an iteration task')
    from _common import runtime_identity
    if plan.get('runtime_identity') is None or runtime_identity(root) != plan['runtime_identity']:
        raise ValueError('iteration requires a new plan matching the current runtime')
    output = Path(plan['result_dir']) / 'methylation_iteration' / task['parameters']['spec']['id']
    summary = execute(root, task['parameters']['spec'], output, task['parameters']['source_evidence'])
    write_json(directory / 'tasks' / args.task / 'task_outputs.json', {
        'task': args.task, 'artifacts': [str(p.resolve()) for p in sorted(output.rglob('*')) if p.is_file()],
        'iteration_summary': summary})
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
