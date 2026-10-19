"""Bounded incumbent-centred search. Model votes are proposals, not acceptance."""
from __future__ import annotations

import json
import math


AXES = ('resolution', 'n_neighbors', 'n_pcs', 'min_dist')
DEFAULT_SELECTION = {
    'absolute_tolerance': 0.01,
    'relative_db_tolerance': 0.05,
    'min_improvement': 0.005,
    'max_small_cluster_fraction_increase': 0.02,
    'rare_label_f1_tolerance': 0.05,
}


def fingerprint(parameters):
    return json.dumps(parameters, sort_keys=True, separators=(',', ':'))


def validate_selection(settings):
    result = dict(DEFAULT_SELECTION)
    unknown = set(settings) - set(result)
    if unknown:
        raise ValueError('unknown selection settings: %s' % sorted(unknown))
    result.update(settings)
    for key, value in result.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value < 1:
            raise ValueError('selection.%s must be a finite fraction in [0,1)' % key)
    if result['min_improvement'] <= 0:
        raise ValueError('selection.min_improvement must be positive')
    return result


def compare(candidate, incumbent, settings):
    """Conservative non-inferiority gate; not a calibrated statistical test."""
    settings = validate_selection(settings)
    axes = [key for key in AXES if candidate['parameters'][key] != incumbent['parameters'][key]]
    layout_only = bool(axes) and set(axes) == {'min_dist'}
    metrics = [('embedding', 'trustworthiness', 1), ('embedding', 'knn_preservation', 1),
               ('clustering', 'silhouette', 1), ('clustering', 'davies_bouldin', -1)]
    regressions, gains, missing, deltas = [], [], [], {}
    for section, key, direction in metrics:
        old, new = incumbent[section].get(key), candidate[section].get(key)
        if old is None or new is None or not math.isfinite(old) or not math.isfinite(new):
            missing.append(key)
            continue
        delta = direction * (new - old)
        # DB has a different, unbounded scale. Compare its relative change.
        if key == 'davies_bouldin':
            delta /= max(abs(old), 1e-12)
        deltas[key] = delta
        tolerance = settings['relative_db_tolerance'] if key == 'davies_bouldin' else settings['absolute_tolerance']
        if delta < -tolerance:
            regressions.append(key)
        if delta > settings['min_improvement'] and (not layout_only or section == 'embedding'):
            gains.append(key)
    # A layout-only win must not be reported as a scientific/partition win.
    science_gains = [key for key in gains if key in {'silhouette', 'davies_bouldin'}]
    if not layout_only:
        gains = science_gains
    old = incumbent['clustering'].get('small_cluster_cell_fraction')
    new = candidate['clustering'].get('small_cluster_cell_fraction')
    if old is not None and new is not None and new - old > settings['max_small_cluster_fraction_increase']:
        regressions.append('small_cluster_cell_fraction')
    if incumbent['biology'].get('independent'):
        if not candidate['biology'].get('independent'):
            missing.append('independent_reference')
        for label, old in incumbent['biology'].get('label_best_cluster_f1', {}).items():
            new = candidate['biology'].get('label_best_cluster_f1', {}).get(label)
            if new is None:
                missing.append('label:' + label)
            elif new < old - settings['rare_label_f1_tolerance']:
                regressions.append('label_f1:' + label)
    selected = not missing and not regressions and bool(gains)
    return {'selected': selected, 'kind': 'layout_only' if layout_only else 'partition_screen',
            'improvements': gains, 'regressions': regressions, 'missing_metrics': missing,
            'direction_corrected_deltas': deltas,
            'reason': 'select_candidate' if selected else 'incomplete_evidence' if missing else
                      'retain_incumbent_regression' if regressions else 'retain_incumbent_no_material_gain'}


def next_candidate(incumbent, evaluated, grids, phase, preferred_axis, preferred_direction):
    """One adjacent axis relative to the incumbent; never revisit a setting."""
    axes = list(AXES[:3] if phase == 'science' else AXES[3:])
    if preferred_axis in axes:
        axes.remove(preferred_axis)
        axes.insert(0, preferred_axis)
    visited = {fingerprint(item['parameters']) for item in evaluated}
    base = incumbent['parameters']
    rejected = []
    for axis in axes:
        index = grids[axis].index(base[axis])
        directions = ('increase', 'decrease') if preferred_direction == 'increase' else ('decrease', 'increase')
        for direction in directions:
            target = index + (1 if direction == 'increase' else -1)
            if not 0 <= target < len(grids[axis]):
                continue
            params = dict(base, **{axis: grids[axis][target]})
            if fingerprint(params) in visited:
                rejected.append({'parameters': params, 'reason': 'already_evaluated'})
                continue
            dimension = min(incumbent['dataset']['n_cells'], incumbent['dataset']['n_genes'])
            if params['n_pcs'] >= dimension or params['n_neighbors'] >= incumbent['dataset']['n_cells']:
                rejected.append({'parameters': params, 'reason': 'not_executable_for_dataset'})
                continue
            return params, {'parameter': axis, 'direction': direction,
                            'old_value': base[axis], 'new_value': params[axis]}, rejected
    return None, None, rejected


def plan_search(current, history, grids, selection, stopping, preferred_axis, preferred_direction):
    """History is frozen state/decision pairs, not model-generated memory."""
    validate_selection(selection)
    max_rounds = int(stopping.get('max_iterations', 20))
    patience = int(stopping.get('max_no_improvement', 5))
    if max_rounds < 1 or patience < 1:
        raise ValueError('iteration budget and patience must be positive')
    states = [item['state'] for item in history]
    previous = history[-1]['decision'].get('search') if history else None
    if history and not previous:
        raise ValueError('legacy search history requires a new session')
    incumbent = next(item for item in states if item['run_id'] == previous['incumbent_run_id']) if previous else current
    phase = previous['phase'] if previous else 'science'
    science_stop = previous.get('science_stop_reason') if previous else None
    result = compare(current, incumbent, selection) if previous else {
        'selected': True, 'kind': 'baseline', 'reason': 'initial_reference',
        'improvements': [], 'regressions': [], 'missing_metrics': []}
    if states:
        baseline_gate = compare(current, states[0], selection)
        result['baseline_guard'] = baseline_gate
        if baseline_gate['regressions'] or baseline_gate['missing_metrics']:
            result['selected'] = False
            result['reason'] = 'retain_incumbent_baseline_guard'
    if result['selected']:
        incumbent = current
    streak = 0 if result['selected'] else (previous['no_improvement_streak'] if previous else 0) + 1
    evaluated = states + [current]
    params, diff, skipped = next_candidate(incumbent, evaluated, grids, phase, preferred_axis, preferred_direction)
    transition = None
    # Patience is a budget stop, not proof of convergence. Complete at least one
    # trial of each feasible scientific axis before using this early transition.
    tried = {item['decision'].get('selected_parameter') for item in history}
    feasible = {key for key in AXES[:3] if next_candidate(
        incumbent, [incumbent], {name: (values if name == key else [incumbent['parameters'][name]])
                                 for name, values in grids.items()}, 'science', key, 'increase')[1] is not None}
    if phase == 'science' and (diff is None or (streak >= patience and feasible <= tried)):
        transition = 'science_frontier_exhausted' if diff is None else 'science_patience_budget'
        science_stop = transition
        phase, streak = 'layout', 0
        params, diff, more = next_candidate(incumbent, evaluated, grids, phase, preferred_axis, preferred_direction)
        skipped.extend(more)
    reason = None
    if len(evaluated) >= max_rounds:
        reason = 'max_iterations'
    elif diff is None:
        reason = 'staged_budget_complete' if science_stop == 'science_patience_budget' else 'local_frontier_exhausted'
    elif phase == 'layout' and streak >= patience:
        reason = 'layout_patience_budget'
    if reason:
        params, diff = dict(current['parameters']), None
    search = {'schema_version': 1, 'phase': phase, 'phase_transition': transition,
              'science_stop_reason': science_stop,
              'incumbent_run_id': incumbent['run_id'], 'incumbent_parameters': incumbent['parameters'],
              'incumbent_h5ad': incumbent.get('evidence', {}).get('candidate_h5ad'),
              'comparison': result, 'no_improvement_streak': streak,
              'evaluated_count': len(evaluated), 'skipped_candidates': skipped,
              'annotation_approved': False, 'global_optimum_claimed': False,
              'finalist_checks_required': ['marker_and_rare_population_review', 'sample_and_QC_review',
                                           'seed_stability', 'final_annotation_and_figure_review']}
    return search, incumbent, params, diff, reason


def rerun_scope(axis):
    scope = {
        'n_pcs': ['pca', 'harmony', 'neighbors', 'umap', 'leiden', 'markers', 'annotation_review'],
        'n_neighbors': ['neighbors', 'umap', 'leiden', 'markers', 'annotation_review'],
        'resolution': ['leiden', 'markers', 'annotation_review'],
        'min_dist': ['umap', 'figure_review'],
    }
    return {'minimum_affected_steps': scope.get(axis, []),
            'executor_mode': 'full_notebook_replay',
            'automatic_checkpoint_reuse': False,
            'note': 'Stage scope is an audit hint, not implemented checkpoint reuse. No old output is relabelled.'}
