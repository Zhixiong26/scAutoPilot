#!/usr/bin/env python3
"""Plan explicitly implemented custom tasks using the ordinary signed DAG contract."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from _common import WorkflowError, load_project, runtime_identity, task_is_implemented, write_json
from audit_runtime import require_contract
from plan_workflow import task, validate_dag, required_environment_stages
from validate_project import validate
from result_paths import CATEGORIES, require_unused_result, validate_output_commands, validate_run_id


def plan_custom(project, spec, run_id, category=None):
    root = Path(project).resolve(); spec = Path(spec).resolve()
    require_contract(root)
    if not spec.is_relative_to(root / 'config'):
        raise WorkflowError('Custom task specification must be frozen under project/config')
    if not run_id.strip() or '/' in run_id or run_id in {'.', '..'}:
        raise WorkflowError('Invalid run ID')
    validate_run_id(run_id)
    cfg = load_project(root)
    entries = json.loads(spec.read_text(encoding='utf-8'))
    if not isinstance(entries, list) or not entries:
        raise WorkflowError('Custom task specification must be a non-empty list')
    tasks = [task(**entry) for entry in entries]
    validate_dag(tasks)
    for item in tasks:
        if not task_is_implemented(item['id'], cfg['analysis'].get('task_commands') or {}):
            raise WorkflowError('Missing custom command for ' + item['id'])
        if item['profile'] not in cfg['scheduler']['profiles']:
            raise WorkflowError('Missing explicit resource profile for ' + item['id'])
    validate_output_commands(cfg["analysis"].get("task_commands") or {})
    pre = validate(root, selected_routes=set(), required_stages=required_environment_stages(tasks))
    if pre['status'] != 'valid':
        raise WorkflowError('; '.join(pre['errors']))
    run = root / '.workflow/runs' / run_id
    if run.exists() and any(run.iterdir()):
        raise WorkflowError('Preserve existing run; choose a new ID')
    result_dir = require_unused_result(root, run_id, category)
    payload = dict(schema_version=1, run_id=run_id, project=str(root), status='planned',
                   created_at=datetime.now(timezone.utc).isoformat(), routes={},
                   input_signature=pre['input_signature'], code_signature=pre['code_signature'],
                   runtime_identity=runtime_identity(root), plan_identity_version=2,
                   result_layout_version=2, result_category=category,
                   delivery_contract="rna_full_v2" if category == "scanpy" else None,
                   result_dir=str(result_dir), tasks=tasks,
                   custom_task_spec=str(spec))
    write_json(run / 'preflight.json', pre); write_json(run / 'plan.json', payload)
    return payload


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--category', choices=CATEGORIES, required=True)
    args = parser.parse_args()
    print(json.dumps(plan_custom(args.project, args.spec, args.run_id, args.category), indent=2))
