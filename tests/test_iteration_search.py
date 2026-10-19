"""Regression tests for evidence-gated, non-cycling incumbent search."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from scautopilot.review.search import compare, plan_search, next_candidate, validate_selection

GRIDS = {'n_pcs': [20, 30, 40], 'n_neighbors': [10, 15, 20],
         'resolution': [0.4, 0.6, 0.8], 'min_dist': [0.1, 0.3, 0.5]}


def state(name='baseline'):
    return {'run_id': name, 'parameters': {'n_pcs': 30, 'n_neighbors': 15, 'resolution': 0.6, 'min_dist': 0.3},
            'pca_n_comps': 50, 'dataset': {'n_cells': 1000, 'n_genes': 2000},
            'embedding': {'trustworthiness': 0.96, 'knn_preservation': 0.6},
            'clustering': {'silhouette': 0.3, 'davies_bouldin': 1.2, 'small_cluster_cell_fraction': 0.0},
            'biology': {'independent': False}, 'batch': {'ilisi': 0.3}}


class SearchTests(unittest.TestCase):
    def test_one_gain_cannot_hide_regression(self):
        a, b = state(), state('bad')
        b['parameters']['resolution'] = 0.8
        b['clustering']['silhouette'] = 0.4
        b['embedding']['knn_preservation'] = 0.3
        verdict = compare(b, a, {})
        self.assertFalse(verdict['selected'])
        self.assertIn('knn_preservation', verdict['regressions'])

    def test_gain_ignores_global_mixing_and_circular_asw(self):
        a, b = state(), state('circular')
        b['parameters']['resolution'] = 0.8
        b['batch']['ilisi'] = 1.0
        b['biology']['celltype_asw'] = 1.0
        self.assertFalse(compare(b, a, {})['selected'])

    def test_layout_gain_is_not_a_partition_gain(self):
        a, b = state(), state('layout')
        b['parameters']['min_dist'] = 0.1
        b['embedding']['knn_preservation'] = 0.7
        verdict = compare(b, a, {})
        self.assertTrue(verdict['selected'])
        self.assertEqual(verdict['kind'], 'layout_only')
        b['parameters']['n_neighbors'] = 20
        self.assertFalse(compare(b, a, {})['selected'])

    def test_missing_metric_cannot_pass(self):
        a, b = state(), state('missing')
        b['clustering'].update(silhouette=0.5, davies_bouldin=None)
        self.assertFalse(compare(b, a, {})['selected'])

    def test_rare_label_merge_cannot_be_hidden_by_silhouette(self):
        a, b = state(), state('rare-lost')
        a['biology'] = {'independent': True, 'label_best_cluster_f1': {'rare': 0.9}}
        b['biology'] = {'independent': True, 'label_best_cluster_f1': {'rare': 0.3}}
        b['clustering']['silhouette'] = 0.5
        self.assertIn('label_f1:rare', compare(b, a, {})['regressions'])

    def test_boundary_tries_opposite_and_visited_never_repeats(self):
        a = state()
        a['parameters']['n_neighbors'] = 20
        params, diff, _ = next_candidate(a, [a], GRIDS, 'science', 'n_neighbors', 'increase')
        self.assertEqual(params['n_neighbors'], 15)
        b = state('b'); b['parameters'] = params
        params, diff, skipped = next_candidate(a, [a, b], GRIDS, 'science', 'n_neighbors', 'increase')
        self.assertNotEqual(diff['parameter'], 'n_neighbors')
        self.assertTrue(skipped)

    def test_unexecutable_upper_pcs_does_not_invalidate_current_candidate(self):
        a = state(); a['dataset']['n_genes'] = 40
        params, diff, skipped = next_candidate(a, [a], GRIDS, 'science', 'n_pcs', 'increase')
        self.assertEqual(params['n_pcs'], 20)
        self.assertEqual(skipped[0]['reason'], 'not_executable_for_dataset')

    def test_rejected_run_restores_incumbent_and_advances(self):
        a = state()
        search, _, params, diff, reason = plan_search(a, [], GRIDS, {}, {}, 'n_neighbors', 'increase')
        b = state('rejected'); b['parameters'] = params
        b['clustering']['silhouette'] = 0.1
        history = [{'state': a, 'decision': {'search': search, 'selected_parameter': diff['parameter']}}]
        search, best, params, diff, reason = plan_search(b, history, GRIDS, {}, {}, 'n_neighbors', 'increase')
        self.assertEqual(best['run_id'], a['run_id'])
        self.assertEqual(params['n_neighbors'], 10)
        self.assertEqual(search['no_improvement_streak'], 1)

    def test_budget_reports_best_not_latest_and_not_approval(self):
        a = state()
        search, best, params, diff, reason = plan_search(a, [], GRIDS, {}, {'max_iterations': 1}, 'none', 'keep')
        self.assertEqual(reason, 'max_iterations')
        self.assertIsNone(diff)
        self.assertFalse(search['annotation_approved'])
        self.assertTrue(search['finalist_checks_required'])

    def test_model_none_does_not_abort_available_search(self):
        result = plan_search(state(), [], GRIDS, {}, {}, 'none', 'keep')
        self.assertIsNotNone(result[3])

    def test_local_science_frontier_then_layout_then_terminal(self):
        a = state()
        history, current, seen = [], a, set()
        for i in range(20):
            key = json.dumps(current['parameters'], sort_keys=True)
            self.assertNotIn(key, seen)
            seen.add(key)
            search, best, params, diff, reason = plan_search(current, history, GRIDS, {}, {'max_no_improvement': 20}, 'none', 'keep')
            history.append({'state': current, 'decision': {'search': search, 'selected_parameter': diff['parameter'] if diff else None}})
            if not diff:
                self.assertEqual(reason, 'local_frontier_exhausted')
                break
            current = state('run%d' % i); current['parameters'] = params
        else:
            self.fail('finite local frontier did not terminate')
        self.assertEqual(len(seen), 9)  # baseline + two directions * four axes
        self.assertEqual(search['incumbent_run_id'], 'baseline')

    def test_policy_rejects_nan_unknown_and_negative(self):
        for settings in ({'min_improvement': float('nan')}, {'absolute_tolerance': -0.1}, {'anything': 1}):
            with self.assertRaises(ValueError): validate_selection(settings)

    def test_cumulative_small_loss_cannot_escape_baseline_guard(self):
        baseline, inc, candidate = state(), state('inc'), state('candidate')
        inc['parameters']['resolution'] = 0.8
        inc['clustering']['silhouette'] = 0.4
        inc['embedding']['trustworthiness'] = 0.952
        candidate = copy.deepcopy(inc)
        candidate['run_id'] = 'candidate'
        candidate['parameters']['n_neighbors'] = 20
        candidate['clustering']['silhouette'] = 0.5
        candidate['embedding']['trustworthiness'] = 0.944
        first = plan_search(baseline, [], GRIDS, {}, {}, 'resolution', 'increase')[0]
        second = plan_search(inc, [{'state': baseline, 'decision': {'search': first}}], GRIDS, {}, {}, 'n_neighbors', 'increase')[0]
        history = [{'state': baseline, 'decision': {'search': first}}, {'state': inc, 'decision': {'search': second}}]
        result = plan_search(candidate, history, GRIDS, {}, {}, 'none', 'keep')
        self.assertEqual(result[1]['run_id'], 'inc')
        self.assertEqual(result[0]['comparison']['reason'], 'retain_incumbent_baseline_guard')

    def test_small_cluster_inflation_blocks_selection(self):
        a, b = state(), state('fragments')
        b['clustering'].update(silhouette=0.6, small_cluster_cell_fraction=0.2)
        self.assertIn('small_cluster_cell_fraction', compare(b, a, {})['regressions'])


if __name__ == '__main__':
    unittest.main()
