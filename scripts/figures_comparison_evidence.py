"""Dependency-light evidence for immutable, run-scoped figure deliveries."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMA_VERSION = 1
ROUTES = ('scanpy', 'methscan_vmr', 'methscan_dmr', 'allcools',
          'methylvi_allcools', 'methylvi_vmr', 'methylvi_vmr_dmr')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def plan_digest(path):
    from _common import signed_plan_digest
    plan = read_json(path)
    return signed_plan_digest(plan) if plan.get('plan_identity_version') == 2 else sha(path)


def read_json(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('expected JSON object: %s' % path)
    return value


def safe_artifact(directory, name):
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts or str(relative) in ('', '.'):
        raise ValueError('invalid delivery artifact path: %s' % name)
    path = Path(directory) / relative
    if not path.resolve().is_relative_to(Path(directory).resolve()):
        raise ValueError('delivery artifact escapes directory: %s' % name)
    if path.is_symlink():
        raise ValueError('delivery artifacts must be copies, not links: %s' % name)
    return path


def validate_manifest(path, identity=None):
    path = Path(path)
    data = read_json(path)
    if data.get('schema_version') != SCHEMA_VERSION or data.get('status') != 'rendered_verified':
        raise ValueError('invalid delivery manifest schema/status')
    for key in ('run_id', 'task', 'input_signature', 'code_signature', 'plan_sha256'):
        if not data.get(key):
            raise ValueError('manifest lacks %s' % key)
        if identity and data.get(key) != identity.get(key):
            raise ValueError('delivery identity mismatch: %s' % key)
    if (data['task'] != 'figures_comparison' or data.get('presentation_only') is not True
            or data.get('analysis_rerun') is not False or data.get('coordinates_recomputed') is not False):
        raise ValueError('invalid presentation-only declaration')
    coverage = data.get('route_coverage')
    if not isinstance(coverage, list) or sorted(x['route'] for x in coverage) != sorted(ROUTES):
        raise ValueError('manifest must cover all seven routes exactly once')
    if not isinstance(data.get('sources'), list) or not data['sources']:
        raise ValueError('manifest lacks source evidence')
    names = set()
    for artifact in data.get('artifacts', []):
        name = artifact['path']
        if name in names or name == path.name:
            raise ValueError('duplicate/self-referencing artifact: %s' % name)
        names.add(name)
        item = safe_artifact(path.parent, name)
        if not item.is_file() or item.stat().st_size < 1:
            raise ValueError('delivery artifact absent/empty: %s' % name)
        if item.stat().st_size != artifact['bytes'] or sha(item) != artifact['sha256']:
            raise ValueError('delivery artifact checksum mismatch: %s' % name)
    if not {'README.md', 'route_coverage.tsv', 'panel_composition.tsv', 'source_index.tsv'} <= names:
        raise ValueError('delivery lacks required indexes/documentation')
    for panel in data.get('panels', []):
        if panel['single_png'] not in names:
            raise ValueError('unregistered single panel')
    for figure in data.get('figures', []):
        if not set(figure['files']) <= names:
            raise ValueError('unregistered atlas artifact')
    for source in data['sources']:
        if source.get('kind') == 'task_evidence':
            source_path = Path(source['path'])
            if not source_path.is_file() or sha(source_path) != source['sha256']:
                raise ValueError('source task evidence changed: %s' % source_path)
    return data


def validate_delivery_record(record, record_path=None):
    evidence = record['delivery_evidence']
    if evidence.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('unsupported delivery evidence version')
    manifest = Path(evidence['manifest'])
    if record_path is not None:
        plan_path = Path(record_path).parents[2] / 'plan.json'
        plan = read_json(plan_path)
        expected_identity = {key: plan[key] for key in ('run_id', 'input_signature', 'code_signature')}
        expected_identity.update(task='figures_comparison', plan_sha256=plan_digest(plan_path))
        if evidence.get('identity') != expected_identity:
            raise ValueError('delivery evidence belongs to another signed plan')
        if manifest != Path(plan['result_dir']) / 'figures_comparison/delivery_manifest.json':
            raise ValueError('delivery manifest belongs to another result directory')
    if not manifest.is_absolute() or sha(manifest) != evidence['sha256']:
        raise ValueError('delivery manifest checksum mismatch')
    data = validate_manifest(manifest, evidence['identity'])
    expected = {str((manifest.parent / x['path']).resolve()) for x in data['artifacts']}
    expected.add(str(manifest.resolve()))
    recorded = record.get('artifacts', [])
    if len(recorded) != len(set(recorded)) or set(recorded) != expected:
        raise ValueError('delivery task_outputs artifact set differs from manifest')
    return data


def delivery_record(manifest, identity):
    manifest = Path(manifest).resolve()
    data = validate_manifest(manifest, identity)
    return {'task': 'figures_comparison',
            'artifacts': [str(manifest)] + [str((manifest.parent / x['path']).resolve()) for x in data['artifacts']],
            'delivery_evidence': {'schema_version': SCHEMA_VERSION, 'manifest': str(manifest),
                                  'sha256': sha(manifest), 'identity': identity}}


def task_evidence(run_dir, plan, item):
    # Lazy import prevents the shared output validator importing itself.
    from _common import signature, validate_recorded_outputs
    directory = Path(run_dir) / 'tasks' / item['id']
    path = directory / 'task_status.json'
    if not (directory / 'task.COMPLETE').is_file():
        raise ValueError('source task lacks completion marker: %s' % item['id'])
    status = read_json(path)
    expected = signature({'command': status.get('command', []), 'parameters': item.get('parameters', {})})
    if (status.get('status') != 'complete' or status.get('return_code') != 0
            or status.get('input_signature') != plan.get('input_signature')
            or status.get('code_signature') != plan.get('code_signature')
            or status.get('task_signature') != expected):
        raise ValueError('invalid source task identity/status: %s' % item['id'])
    valid, reason = validate_recorded_outputs(status.get('outputs', []))
    if not valid:
        raise ValueError('invalid source task outputs: %s: %s' % (item['id'], reason))
    if item['id'] == 'figures_comparison':
        expected_output = directory / 'task_outputs.json'
        if status.get('outputs') != [str(expected_output)]:
            raise ValueError('figure task must record its task_outputs.json')
        validate_delivery_record(read_json(expected_output), expected_output)
    return status


def review_state(manifest, review_path):
    manifest, review_path = Path(manifest), Path(review_path)
    if not review_path.exists():
        return 'pending'
    try:
        review = read_json(review_path)
        if review.get('manifest_sha256') != sha(manifest):
            return 'stale'
        if review.get('status') not in ('passed', 'failed') or not review.get('inspected'):
            return 'stale'
        for name, digest in review['inspected'].items():
            if sha(safe_artifact(manifest.parent, name)) != digest:
                return 'stale'
        return review['status']
    except (OSError, ValueError, KeyError, TypeError):
        return 'stale'
