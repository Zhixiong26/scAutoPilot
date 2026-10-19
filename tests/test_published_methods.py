"""Real optional Optuna proposals plus fail-closed protocol tests; synthetic only."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from propose_methylvi_trial import validate, propose, main
from init_project import RUNTIME_TOOLS


def bind(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def fixture(root, sampler='tpe'):
    bindings = {}
    for name in ('counts_manifest', 'cell_ids', 'feature_ids', 'split_manifest', 'fixed_training'):
        path = root / (name + '.json')
        path.write_text(json.dumps({'synthetic_fixture': name}))
        bindings[name] = bind(path)
    return {'protocol': {'schema_version': 1, 'sampler': sampler, 'seed': 7,
            'max_trials': 8, 'n_startup_trials': 2,
            'space': {'n_hidden': [16, 32], 'n_latent': [2, 3]},
            'objective': {'name': 'elbo_validation', 'direction': 'minimize', 'reduction': 'last'},
            'bindings': bindings}, 'trials': []}


def finish(request, root, index=-1, state='complete', value=10.0):
    result = copy.deepcopy(request)
    row = result['trials'][index]
    row['state'] = state
    row['value'] = value if state == 'complete' else None
    path = root / (row['id'] + '.json')
    path.write_text(json.dumps(row))
    row['evidence'] = bind(path)
    return result


class MethodProtocolTests(unittest.TestCase):
    def test_generator_includes_proposal_tool(self):
        self.assertIn('propose_methylvi_trial.py', RUNTIME_TOOLS)

    def test_file_identity_drift_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); request = fixture(root)
            validate(request, root)
            (root / 'cell_ids.json').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'): validate(request, root)

    def test_reject_unregistered_axes_and_bad_objectives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); base = fixture(root)
            cases = [{'space': {'target_weight': [1]}}, {'space': {'n_hidden': [True]}},
                     {'space': {'n_latent': [20, 10]}}, {'max_trials': 0},
                     {'seed': True}, {'sampler': 'custom'}, {'schema_version': True},
                     {'objective': {'name': 'dmr_count', 'direction': 'minimize', 'reduction': 'last'}}]
            for change in cases:
                request = copy.deepcopy(base); request['protocol'].update(change)
                with self.subTest(change=change), self.assertRaises(ValueError): validate(request, root)

    def test_unknown_schema_fields_are_not_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); request = fixture(root); request['execute'] = True
            with self.assertRaises(ValueError): validate(request, root)

    def test_submit_host_is_refused_without_output(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch('_common.host_role', return_value='submit'):
            out = Path(tmp) / 'proposal.json'
            with mock.patch.object(sys, 'argv', ['tool', '--request', str(Path(tmp) / 'missing'), '--output', str(out)]):
                with self.assertRaisesRegex(ValueError, 'compute'): main()
            self.assertFalse(out.exists())


@unittest.skipUnless(importlib.util.find_spec('optuna'), 'optional isolated Optuna environment required')
class RealOptunaTests(unittest.TestCase):
    def test_random_and_tpe_use_official_sampler_and_do_not_mutate_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for sampler in ('random', 'tpe'):
                request = fixture(root, sampler); before = copy.deepcopy(request)
                a, b = propose(request, root), propose(request, root)
                self.assertEqual(a, b)
                self.assertEqual(request, before)
                self.assertFalse(a['submitted']); self.assertIsNone(a['selected_winner'])
                self.assertTrue(a['optuna_version']); self.assertEqual(a['sampler'], sampler)
                self.assertEqual(a['sampling_phase'], 'random' if sampler == 'random' else 'tpe_startup_random')

    def test_tpe_past_startup_and_no_duplicate_pending_complete_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); request = fixture(root)
            for value in (12.0, 8.0):
                result = propose(request, root)
                request = finish(result['next_request'], root, value=value)
            result = propose(request, root)
            self.assertEqual(result['sampling_phase'], 'tpe')
            request = finish(result['next_request'], root, state='failed')
            result = propose(request, root)
            self.assertEqual(len({json.dumps(t['parameters'], sort_keys=True) for t in result['next_request']['trials']}), 4)
            stopped = propose(result['next_request'], root)
            self.assertEqual(stopped['status'], 'space_exhausted')

    def test_pending_consumes_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); request = fixture(root); request['protocol']['max_trials'] = 1
            result = propose(request, root)
            self.assertEqual(propose(result['next_request'], root)['status'], 'budget_exhausted')

    def test_duplicate_draw_fallback_is_bounded_and_disclosed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); request = fixture(root, 'random')
            request, sha = validate(request, root)
            request['trials'] = [{'id': 'occupied', 'state': 'pending',
                'parameters': {'n_hidden': 16, 'n_latent': 2}, 'protocol_sha256': sha}]
            with mock.patch('optuna.samplers.RandomSampler.sample_independent',
                            side_effect=lambda study, trial, name, dist: dist.choices[0]):
                result = propose(request, root)
            self.assertEqual(result['draws'], 64)
            self.assertIn('deterministic_unvisited', result['fallback'])
            self.assertNotEqual(result['proposal']['parameters'], request['trials'][0]['parameters'])

    def test_trial_evidence_value_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = finish(propose(fixture(root), root)['next_request'], root)
            request['trials'][0]['value'] = 0.1
            with self.assertRaisesRegex(ValueError, 'disagrees'): propose(request, root)

    def test_protocol_change_refuses_old_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); request = propose(fixture(root), root)['next_request']
            request['protocol']['objective']['reduction'] = 'min'
            with self.assertRaisesRegex(ValueError, 'incomparable'): propose(request, root)

    def test_duplicate_or_unmeasured_histories_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); base = propose(fixture(root), root)['next_request']
            cases = []
            duplicate = copy.deepcopy(base); duplicate['trials'].append(dict(duplicate['trials'][0], id='new-id')); cases.append(duplicate)
            unmeasured = copy.deepcopy(base); unmeasured['trials'][0]['state'] = 'complete'; cases.append(unmeasured)
            nan = copy.deepcopy(base); nan['trials'][0]['value'] = float('nan'); cases.append(nan)
            pending = copy.deepcopy(base); pending['trials'][0]['value'] = 3.0; cases.append(pending)
            for request in cases:
                with self.assertRaises(ValueError): propose(request, root)

    def test_cli_replay_guard_and_bound_path_resolution(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch('_common.host_role', return_value='compute'):
            root = Path(tmp); request = fixture(root)
            for binding in request['protocol']['bindings'].values(): binding['path'] = Path(binding['path']).name
            src, dst = root / 'request.json', root / 'out/proposal.json'
            src.write_text(json.dumps(request))
            with mock.patch.object(sys, 'argv', ['tool', '--request', str(src), '--output', str(dst)]):
                main(); first = dst.read_bytes()
                with self.assertRaises(FileExistsError): main()
            self.assertEqual(dst.read_bytes(), first)
            result = json.loads(first)
            # Next request remains valid when saved in another directory.
            validate(result['next_request'], dst.parent)
            self.assertFalse(result['submitted'])


if __name__ == '__main__':
    unittest.main()
