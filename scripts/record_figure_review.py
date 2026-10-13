#!/usr/bin/env python3
"""Record an explicit visual inspection of an existing valid figure delivery."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path
from _common import write_json
from figures_comparison_evidence import read_json, sha, safe_artifact, validate_manifest, task_evidence


def record(project, run_id, status, reviewer, notes, inspected):
    root = Path(project).resolve()
    if '/' in run_id or run_id in ('', '.', '..'):
        raise ValueError('invalid run ID')
    run_dir = root / '.workflow/runs' / run_id
    plan = read_json(run_dir / 'plan.json')
    item = next(x for x in plan['tasks'] if x['id'] == 'figures_comparison')
    task_evidence(run_dir, plan, item)
    path = Path(plan['result_dir']) / 'figures_comparison/delivery_manifest.json'
    manifest = validate_manifest(path)
    if status not in ('passed', 'failed') or not reviewer.strip() or not notes.strip() or not inspected:
        raise ValueError('explicit status, reviewer, notes, and inspected files are required')
    allowed = {x['path'] for x in manifest['artifacts'] if x['path'].endswith('.png')}
    names = set(inspected)
    if not names <= allowed:
        raise ValueError('inspected files must be PNGs in the current delivery')
    required_previews = {name for name in allowed if name.endswith('_preview.png') or name.startswith('dmr/')}
    if status == 'passed' and (not required_previews <= names or
            (manifest.get('panels') and not any(x.startswith('single_panels/') for x in names))):
        raise ValueError('passing review requires all previews/DMR plots and at least one single panel')
    payload = {'schema_version': 1, 'run_id': run_id, 'status': status, 'reviewer': reviewer,
               'notes': notes, 'at': datetime.now(timezone.utc).isoformat(), 'manifest_sha256': sha(path),
               'inspected': {name: sha(safe_artifact(path.parent, name)) for name in sorted(names)}}
    write_json(run_dir / 'figure_review.json', payload)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--status', choices=('passed', 'failed'), required=True)
    parser.add_argument('--reviewer', required=True)
    parser.add_argument('--notes', required=True)
    parser.add_argument('--inspected', nargs='+', required=True, help='Paths relative to figures_comparison/')
    args = parser.parse_args()
    record(args.project, args.run_id, args.status, args.reviewer, args.notes, args.inspected)
    from inspect_run import inspect
    inspect(args.project, args.run_id)


if __name__ == '__main__':
    main()
