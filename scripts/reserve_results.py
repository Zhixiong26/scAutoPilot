#!/usr/bin/env python3
"""Reserve a categorized result root for standalone exploration; never submit jobs."""
import argparse
from datetime import datetime, timezone
from pathlib import Path

from _common import WorkflowError, write_json
from result_paths import CATEGORIES, require_unused_result


def reserve(project, run_id, category, source_runs=()):
    root = Path(project).resolve()
    if (root / '.workflow/runs' / run_id).exists():
        raise WorkflowError('Run already has workflow evidence; read its recorded plan')
    path = require_unused_result(root, run_id, category)
    path.mkdir(parents=True, exist_ok=False)
    write_json(path / 'result_manifest.json', {
        'result_layout_version': 2, 'result_category': category,
        'run_id': run_id, 'result_dir': str(path), 'source_runs': list(source_runs),
        'kind': 'exploration', 'status': 'reserved',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'scope': 'Directory reservation only; no execution, completion or visual-review evidence',
    })
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--category', choices=CATEGORIES, required=True)
    parser.add_argument('--source-run', action='append', default=[])
    args = parser.parse_args()
    print(reserve(args.project, args.run_id, args.category, args.source_run))
