#!/usr/bin/env python3
"""Read-only capability check before copying, planning or submitting a runtime.

Checks deployed wiring, not scientific correctness. Never edits historical runs.
"""
import argparse
import ast
import json
from pathlib import Path


def audit(project):
    root = Path(project).resolve()
    errors = []
    calls = set()
    executor = root / 'Scripts/Common/run_task.py'
    try:
        tree = ast.parse(executor.read_text(encoding='utf-8'))
        calls = {n.func.id for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    except (OSError, SyntaxError) as exc:
        errors.append('Cannot inspect deployed executor: %s' % exc)
    for name in ('runtime_identity', 'seal_recorded_outputs', 'update_results_index', 'validate_plan_result'):
        if name not in calls:
            errors.append('Deployed run_task.py lacks %s; freeze a maintained runtime in a NEW run' % name)
    if not (root / 'tools/result_paths.py').is_file():
        errors.append('Categorized result_paths.py is missing; freeze a maintained runtime')
    if not (root / 'Scripts/Common/embedding_plot.py').is_file():
        errors.append('Shared embedding_plot.py is missing')
    # Inspect explicit adapters as well as the common runner: a maintained
    # executor cannot repair a custom script that bypasses embedding geometry.
    try:
        from _common import load_project
        cfg = load_project(root)
        scripts = set()
        for command in (cfg.get('analysis', {}).get('task_commands') or {}).values():
            if not isinstance(command, list):
                continue
            for token in command:
                candidate = Path(str(token).replace('{project}', str(root)))
                if candidate.suffix == '.py':
                    candidate = candidate if candidate.is_absolute() else root / candidate
                    if candidate.is_file():
                        scripts.add(candidate.resolve())
        for script in scripts:
            tree = ast.parse(script.read_text(encoding='utf-8'))
            embedding_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                               and isinstance(n.func, ast.Attribute) and n.func.attr in {'umap', 'embedding', 'pca'}
                               and isinstance(n.func.value, ast.Attribute) and n.func.value.attr == 'pl']
            shared_saves = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                            and ((isinstance(n.func, ast.Name) and n.func.id == 'save_embedding')
                                 or (isinstance(n.func, ast.Attribute) and n.func.attr == 'save_embedding'))]
            if embedding_calls and not shared_saves:
                errors.append('Custom embedding renderer bypasses save_embedding: %s' % script)
    except (OSError, ValueError, SyntaxError) as exc:
        errors.append('Cannot inspect custom adapters: %s' % exc)
    results = (root / 'Results').resolve()
    config = results / 'index_targets.json'
    targets = [results]
    if config.exists():
        try:
            values = json.loads(config.read_text(encoding='utf-8'))['additional_results_roots']
            if not isinstance(values, list) or any(not isinstance(x, str) or not Path(x).is_absolute() for x in values):
                raise ValueError('additional_results_roots must be a list of absolute paths')
            targets += [Path(x).resolve() for x in values]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append('Invalid index routing: %s' % exc)
    return {'status': 'invalid' if errors else 'valid', 'project': str(root),
            'results_root': str(results), 'index_targets': list(dict.fromkeys(map(str, targets))),
            'errors': errors, 'scope': 'Static capability wiring; not a scientific or visual pass'}


def require_contract(project):
    from _common import WorkflowError
    result = audit(project)
    if result['errors']:
        raise WorkflowError('Runtime contract failed: ' + '; '.join(result['errors']))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--json-out', type=Path)
    args = parser.parse_args()
    result = audit(args.project)
    if args.json_out:
        from _common import write_json
        write_json(args.json_out, result)
    print(json.dumps(result, indent=2))
    return int(bool(result['errors']))


if __name__ == '__main__':
    raise SystemExit(main())
