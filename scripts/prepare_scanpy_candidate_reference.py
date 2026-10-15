#!/usr/bin/env python3
"""Export this run's cluster proposals as an unapproved exact-cell-ID reference."""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import tempfile

from _common import WorkflowError, write_json
from figures_comparison_evidence import sha, task_evidence
from record_annotation_review import handoff_directory, load_json, read_annotation_table


def prepare(project: Path, run_id: str, worksheet: Path, output_dir: Path) -> Path:
    root = project.resolve()
    if not run_id or Path(run_id).name != run_id or run_id in {'.', '..'}:
        raise WorkflowError('run-id must be a single nonempty path component')
    relative = Path(output_dir)
    if relative.is_absolute() or '..' in relative.parts or len(relative.parts) < 2 or relative.parts[0] != 'Data':
        raise WorkflowError('output-dir must be a new project-relative directory below Data/')
    destination = root / relative
    # Inputs may be symlinked under Data, but do not publish into external inputs.
    if root not in destination.resolve().parents:
        raise WorkflowError('output-dir resolves outside the project; use a local Data/ directory')
    if destination.exists() or destination.is_symlink():
        raise WorkflowError('output directory already exists; choose a new annotation revision')

    run_dir = root / '.workflow/runs' / run_id
    plan_path = run_dir / 'plan.json'
    plan = load_json(plan_path, 'source plan')
    if plan.get('run_id') != run_id:
        raise WorkflowError('source plan run-id mismatch')
    tasks = [item for item in plan.get('tasks', []) if item.get('id') == 'scanpy']
    if len(tasks) != 1:
        raise WorkflowError('source plan must contain one Scanpy task')
    task_evidence(run_dir, plan, tasks[0])
    result = handoff_directory(root, run_id)
    status_path, table_path = result / 'annotation_status.json', result / 'annotation.tsv'
    worksheet = worksheet.resolve()
    sources = [plan_path, run_dir / 'tasks/scanpy/task_status.json', status_path, table_path, worksheet]
    source_hashes = {str(path): sha(path) for path in sources}
    status = load_json(status_path, 'annotation status')
    analysis_signature = status.get('analysis_signature')
    if not isinstance(analysis_signature, str) or not analysis_signature.strip():
        raise WorkflowError('source annotation has no analysis_signature')
    rows = read_annotation_table(table_path, 'leiden')
    ids = [row['cell_id'] for row in rows]
    if any(not value.strip() for value in ids) or len(ids) != len(set(ids)):
        raise WorkflowError('source annotation has empty or duplicate cell IDs')
    observed = {row['leiden'] for row in rows}
    if '' in observed or any(not cluster.strip() for cluster in observed):
        raise WorkflowError('source annotation has empty clusters')
    if status.get('n_cells') != len(rows) or status.get('n_clusters') != len(observed):
        raise WorkflowError('source annotation counts disagree with its status')

    # Use the same placeholder vocabulary as the generated project's review guard.
    import sys
    sys.path.insert(0, str(root / 'Scripts/Common'))
    from annotation import PLACEHOLDER_LABELS
    with worksheet.open(newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle, delimiter='\t')
        required = {'cluster', 'cell_type', 'confidence', 'alternatives', 'evidence'}
        if not required <= set(reader.fieldnames or []):
            raise WorkflowError('worksheet needs columns: %s' % ', '.join(sorted(required)))
        mapping = {}
        for row in reader:
            cluster = (row.get('cluster') or '').strip()
            if not cluster or cluster in mapping:
                raise WorkflowError('worksheet contains an empty or duplicate cluster')
            proposal = {key: (row.get(key) or '').strip() for key in required}
            if proposal['cell_type'].lower() in PLACEHOLDER_LABELS:
                raise WorkflowError('cluster %s needs a biological label, not a placeholder' % cluster)
            if not proposal['confidence'] or not proposal['evidence']:
                raise WorkflowError('cluster %s needs confidence and marker evidence' % cluster)
            # Optional identity columns let independently prepared worksheets bind
            # themselves to a run; they must agree when supplied.
            for key, expected in [('source_run', run_id), ('analysis_signature', analysis_signature)]:
                if key in row and row[key] != expected:
                    raise WorkflowError('worksheet %s differs from the source run' % key)
            mapping[cluster] = proposal
    if set(mapping) != observed:
        raise WorkflowError('worksheet cluster set differs from this run: missing=%s extra=%s' %
                            (sorted(observed - set(mapping)), sorted(set(mapping) - observed)))

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.' + destination.name + '-', dir=destination.parent))
    try:
        output = staging / 'cell_annotations.tsv'
        columns = ['cell_id', 'leiden', 'cell_type', 'confidence', 'alternatives', 'marker_evidence',
                   'source_run', 'analysis_signature', 'review_status']
        with output.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, delimiter='\t', lineterminator='\n')
            writer.writeheader()
            for row in rows:
                proposal = mapping[row['leiden']]
                writer.writerow(dict(cell_id=row['cell_id'], leiden=row['leiden'],
                    cell_type=proposal['cell_type'], confidence=proposal['confidence'],
                    alternatives=proposal['alternatives'], marker_evidence=proposal['evidence'],
                    source_run=run_id, analysis_signature=analysis_signature,
                    review_status='agent_proposed_unapproved'))
        write_json(staging / 'provenance.json', {
            'schema_version': 1, 'source_run': run_id, 'analysis_signature': analysis_signature,
            'source_input_signature': plan['input_signature'], 'source_code_signature': plan['code_signature'],
            'n_cells': len(rows), 'n_clusters': len(observed), 'expected_clusters': sorted(observed),
            'review_status': 'agent_proposed_unapproved', 'independent_reference': False,
            'sources': source_hashes, 'artifacts': [{'path': output.name, 'sha256': sha(output)}],
        })
        if source_hashes != {str(path): sha(path) for path in sources}:
            raise WorkflowError('source files changed during annotation export')
        # mkdir is exclusive even when concurrent exporters choose the same name.
        destination.mkdir()
        try:
            for name in ('cell_annotations.tsv', 'provenance.json'):
                os.replace(staging / name, destination / name)
        except Exception:
            shutil.rmtree(destination)
            raise
    finally:
        shutil.rmtree(staging)
    return destination / 'cell_annotations.tsv'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--worksheet', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        output = prepare(args.project, args.run_id, args.worksheet, args.output_dir)
    except (WorkflowError, ValueError, OSError) as exc:
        parser.exit(1, 'candidate reference export failed: %s\n' % exc)
    print(json.dumps({'annotation_table': str(output), 'review_status': 'agent_proposed_unapproved'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
