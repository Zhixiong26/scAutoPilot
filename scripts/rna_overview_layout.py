#!/usr/bin/env python3
"""Approved compact RNA overview geometry, shared by renderers and delivery audit.

Only presentation geometry lives here: no cohort names, markers or annotations.
"""
from __future__ import annotations
import math

PROFILE = 'scanpy_compact_v1'
CORE = ['cell_type', 'leiden', 'sample', 'condition', 'confidence', 'total_counts',
        'detected_genes', 'mitochondrial_percent']
DOUBLETS = ['doublet_before', 'doublet_after', 'doublet_class', 'doublet_score']
TAIL = ['composition_condition', 'composition_sample', 'marker_dotplot']


def geometry(annotations, genes, samples, longest_label=0, doublets=True):
    """Return inches; grow for crowded inputs while preserving panel order."""
    for value in (annotations, genes, samples):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError('positive integer annotation/gene/sample counts required')
    if not isinstance(longest_label, int) or longest_label < 0:
        raise ValueError('invalid label length')
    width = max(32., 8. + .5 * genes, 32. + max(0, longest_label - 36) * .12)
    dot = max(4.05, annotations * .25)
    composition = max(3.9, annotations * .24, samples * .4)
    extra_dot, extra_composition = dot - 4.05, composition - 3.9
    extra = extra_dot + extra_composition
    height = 27. + extra - (0 if doublets else 4.9)
    sx = width / 32.
    roles = CORE + (DOUBLETS if doublets else []) + TAIL
    positions = {}
    for i, role in enumerate(roles[:12 if doublets else 8]):
        y = [21.1, 16.2, 11.3][i // 4] + extra - (0 if doublets else 4.9)
        positions[role] = [(.6 + 8 * (i % 4)) * sx, y, 4.3, 4.3]
    positions['composition_condition'] = [4.3*sx, 6.7+extra_dot, 8.*sx, composition]
    positions['composition_sample'] = [16.*sx, 6.7+extra_dot, 12.*sx, composition]
    positions['marker_dotplot'] = [4.3*sx, 1., 24.*sx, dot]
    return {'profile': PROFILE, 'canvas_inches': [width, height], 'dpi': 300,
            'panel_roles': dict(zip('ABCDEFGHIJKLMNO', roles)),
            'axes_inches': {letter: positions[role] for letter, role in zip('ABCDEFGHIJKLMNO', roles)},
            'inputs': dict(annotations=annotations, genes=genes, samples=samples,
                           longest_label=longest_label, doublets=doublets)}


def create_canvas(annotations, genes, samples, longest_label=0, doublets=True):
    """Use in a compute-side renderer; render existing data into returned axes."""
    import matplotlib.pyplot as plt
    spec = geometry(annotations, genes, samples, longest_label, doublets)
    width, height = spec['canvas_inches']
    figure = plt.figure(figsize=(width,height), dpi=300, facecolor='white')
    axes = {}
    for letter, (x,y,w,h) in spec['axes_inches'].items():
        axes[letter] = figure.add_axes([x/width,y/height,w/width,h/height])
        if spec['panel_roles'][letter] in CORE + DOUBLETS:
            axes[letter].set_aspect('equal', adjustable='box')
    return figure, axes, spec


def record_layout(figure, axes, spec):
    """Call after drawing; records actual axes, not only desired positions."""
    figure.canvas.draw()
    return {**spec, 'canvas_inches': list(map(float, figure.get_size_inches())),
            'dpi': float(figure.dpi),
            'axes_bounds': {letter: list(map(float, ax.get_position().bounds)) for letter,ax in axes.items()}}


def validate_layout(data):
    record = data['layout']
    expected = geometry(data['candidate_types'], data['markers'], data['samples'],
                        max(map(len, data['cell_type_order'])),
                        data['doublet_diagnostics']['status'] == 'performed')
    if record['profile'] != PROFILE or data['panel_roles'] != expected['panel_roles']:
        raise ValueError('fixed RNA panel order mismatch; doublets belong in row three')
    for key in ['canvas_inches', 'dpi']:
        if record[key] != expected[key]:
            raise ValueError('RNA layout ' + key + ' mismatch')
    width, height = expected['canvas_inches']
    if data['pixels'] != [round(width*300), round(height*300)]:
        raise ValueError('canvas pixels do not match fixed layout and 300 DPI')
    if set(record['axes_bounds']) != set(expected['axes_inches']):
        raise ValueError('record all RNA panel axes')
    for letter,(x,y,w,h) in expected['axes_inches'].items():
        target = [x/width,y/height,w/width,h/height]
        actual = record['axes_bounds'][letter]
        if len(actual) != 4 or not all(math.isfinite(float(a)) and math.isclose(float(a),b,abs_tol=1e-5,rel_tol=0) for a,b in zip(actual,target)):
            raise ValueError('RNA panel position/size differs from fixed layout: ' + letter)
    return expected
