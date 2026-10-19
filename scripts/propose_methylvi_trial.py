#!/usr/bin/env python3
"""Optional Optuna proposal bridge; never trains, submits, edits config or selects a winner.

See references/published-methods.md. Input is a frozen protocol plus a complete
trial ledger, not a live Optuna database. One coordinator owns that ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                    separators=(',', ':')).encode()).hexdigest()


def checked_file(item, root):
    if not isinstance(item, dict) or set(item) != {'path', 'sha256'}:
        raise ValueError('file binding requires path and sha256')
    path = Path(item['path'])
    path = (root / path).resolve()
    # Control-plane metadata only, never full count matrices or arbitrary inputs.
    if not path.is_file() or path.stat().st_size > 20 * 1024**2:
        raise ValueError('binding must be an existing metadata file <= 20 MiB')
    content = path.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    if sha != item['sha256']:
        raise ValueError('evidence hash mismatch: ' + str(path))
    return {'path': str(path), 'sha256': sha}, content


def validate(request, root):
    request = json.loads(json.dumps(request, allow_nan=False))
    if set(request) != {'protocol', 'trials'}:
        raise ValueError('request requires exactly protocol and trials')
    p = request['protocol']
    fields = {'schema_version', 'sampler', 'seed', 'max_trials', 'n_startup_trials',
              'space', 'objective', 'bindings'}
    if set(p) != fields or type(p['schema_version']) is not int or p['schema_version'] != 1:
        raise ValueError('unknown protocol fields/version')
    if p['sampler'] not in {'random', 'tpe'}:
        raise ValueError('sampler must be random or tpe')
    for name, low, high in [('seed', 0, 2**31-1), ('max_trials', 1, 100), ('n_startup_trials', 1, 100)]:
        if type(p[name]) is not int or not low <= p[name] <= high:
            raise ValueError('invalid ' + name)
    if not isinstance(p['space'], dict) or not p['space'] or set(p['space']) - {'n_latent', 'n_hidden', 'n_layers'}:
        raise ValueError('only the registered MethylVI capacity family is supported')
    for values in p['space'].values():
        if not isinstance(values, list) or not values or any(type(v) is not int or v <= 0 for v in values) or values != sorted(set(values)):
            raise ValueError('capacity grids must be sorted unique positive integers')
    if math.prod(len(v) for v in p['space'].values()) > 10000:
        raise ValueError('search space exceeds bounded 10000-point capacity grid')
    objective = p['objective']
    if set(objective) != {'name', 'direction', 'reduction'} or objective['name'] not in {'elbo_validation', 'validation_loss'} or objective['direction'] != 'minimize' or objective['reduction'] not in {'last', 'min'}:
        raise ValueError('declare a lower-is-better validation loss and frozen reduction')
    roles = {'counts_manifest', 'cell_ids', 'feature_ids', 'split_manifest', 'fixed_training'}
    if set(p['bindings']) != roles:
        raise ValueError('all five comparable-experiment bindings are required')
    for role, item in p['bindings'].items():
        p['bindings'][role], _ = checked_file(item, root)
    protocol_sha = digest(p)
    if not isinstance(request['trials'], list) or len(request['trials']) > p['max_trials']:
        raise ValueError('invalid trial ledger or budget exceeded')
    seen_ids, seen_params = set(), set()
    for t in request['trials']:
        required = {'id', 'parameters', 'state', 'protocol_sha256'}
        if not isinstance(t, dict) or not required <= set(t) or set(t) - required - {'value', 'evidence'}:
            raise ValueError('invalid trial fields')
        if not isinstance(t['id'], str) or not t['id'] or t['id'] in seen_ids:
            raise ValueError('trial IDs must be nonempty and unique')
        if t['protocol_sha256'] != protocol_sha:
            raise ValueError('incomparable trial protocol; start a separate experiment')
        params = t['parameters']
        if set(params) != set(p['space']) or any(type(v) is not int or v not in p['space'][k] for k, v in params.items()):
            raise ValueError('trial outside declared capacity grid')
        if digest(params) in seen_params:
            raise ValueError('duplicate configuration; confirmation seeds belong in a separate experiment')
        seen_ids.add(t['id']); seen_params.add(digest(params))
        if t['state'] not in {'complete', 'failed', 'pending'}:
            raise ValueError('unknown state (pruning is not implemented)')
        if t['state'] == 'complete':
            value = t.get('value')
            if type(value) not in (float, int) or not math.isfinite(value):
                raise ValueError('completed trial needs a finite validation loss')
        elif t.get('value') is not None:
            raise ValueError('pending/failed trial cannot supply an objective')
        if t['state'] != 'pending':
            t['evidence'], content = checked_file(t.get('evidence'), root)
            evidence = json.loads(content)
            for key in ('id', 'parameters', 'state', 'protocol_sha256', 'value'):
                if evidence.get(key) != t.get(key):
                    raise ValueError('trial disagrees with metric/failure evidence: ' + key)
    return request, protocol_sha


def propose(request, root):
    request, protocol_sha = validate(request, root)
    p, trials = request['protocol'], request['trials']
    seen = {digest(t['parameters']) for t in trials}
    result = {'protocol_sha256': protocol_sha, 'status': 'proposal_only',
              'selected_winner': None, 'submitted': False,
              'evidence_scope': 'hash-bound caller-reduced metrics, not DAG completion or biological approval',
              'next_request': request}
    if len(trials) >= p['max_trials'] or len(seen) >= math.prod(len(v) for v in p['space'].values()):
        result['status'] = 'budget_exhausted' if len(trials) >= p['max_trials'] else 'space_exhausted'
        return result
    # Optional dependency; importing the CLI or validating a protocol needs no Optuna.
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    # A deterministic seed per ledger snapshot; this is not a resumed persistent study.
    seed = int(digest({'seed': p['seed'], 'trials': trials})[:8], 16)
    sampler = (optuna.samplers.RandomSampler(seed=seed) if p['sampler'] == 'random' else
               optuna.samplers.TPESampler(seed=seed, n_startup_trials=p['n_startup_trials'], constant_liar=True))
    study = optuna.create_study(direction='minimize', sampler=sampler,
                                pruner=optuna.pruners.NopPruner())
    distributions = {k: optuna.distributions.CategoricalDistribution(v) for k, v in sorted(p['space'].items())}
    states = {'complete': optuna.trial.TrialState.COMPLETE,
              'failed': optuna.trial.TrialState.FAIL, 'pending': optuna.trial.TrialState.RUNNING}
    for t in trials:
        study.add_trial(optuna.trial.create_trial(params=t['parameters'], distributions=distributions,
                        state=states[t['state']], value=t.get('value')))
    draws = 0
    for draws in range(1, 65):
        trial = study.ask(fixed_distributions=distributions)
        parameters = trial.params
        if digest(parameters) not in seen:
            break
        study.tell(trial, state=optuna.trial.TrialState.FAIL)
    else:
        # Finite grids near exhaustion can repeat. Explicit fallback, never labelled TPE.
        keys = sorted(p['space'])
        parameters = next(dict(zip(keys, vals)) for vals in itertools.product(*(p['space'][k] for k in keys))
                          if digest(dict(zip(keys, vals))) not in seen)
        result['fallback'] = 'deterministic_unvisited_grid_point_after_64_duplicate_draws'
    existing_ids = {t['id'] for t in trials}
    number = len(trials)
    while 'proposal_%03d' % number in existing_ids:
        number += 1
    pending = {'id': 'proposal_%03d' % number, 'parameters': parameters, 'state': 'pending',
               'protocol_sha256': protocol_sha}
    request['trials'].append(pending)
    result.update(proposal=pending, sampler=p['sampler'], optuna_version=optuna.__version__,
                  draws=draws, sampler_seed=seed,
                  sampling_phase=('random' if p['sampler'] == 'random' else
                    'tpe_startup_random' if sum(t['state'] == 'complete' for t in trials) < p['n_startup_trials'] else 'tpe'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from _common import host_role
    if host_role() == 'submit':
        raise ValueError('run optional method proposals in a small compute allocation')
    if args.output.exists():
        raise FileExistsError('preserve prior proposal; choose a new output')
    result = propose(json.loads(args.request.read_text()), args.request.resolve().parent)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status': result['status'], 'output': str(args.output.resolve()), 'submitted': False}))


if __name__ == '__main__':
    main()
