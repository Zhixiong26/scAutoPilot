#!/usr/bin/env python3
"""Validate exported RNA overview artifacts; no rendering or biological approval."""
from __future__ import annotations
import argparse
import csv
import math
import struct
from pathlib import Path
from _common import write_json
from figures_comparison_evidence import read_json, sha


def require(condition, message):
    if not condition:
        raise ValueError(message)


def table(path):
    with path.open(newline='') as stream:
        rows = list(csv.reader(stream, delimiter='\t'))
    require(len(rows) > 1 and len(rows[0]) > 1, 'empty table: ' + str(path))
    columns = rows[0][1:]
    labels = [row[0] for row in rows[1:]]
    require(len(columns) == len(set(columns)) and len(labels) == len(set(labels)),
            'duplicate table labels: ' + str(path))
    require(all(len(row) == len(rows[0]) for row in rows[1:]), 'ragged table: ' + str(path))
    values = [[float(x) for x in row[1:]] for row in rows[1:]]
    require(all(math.isfinite(x) and x >= 0 for row in values for x in row),
            'invalid numeric table values: ' + str(path))
    return labels, columns, values


def validate_overview(manifest_path, markers_per_annotation=3, require_full=False):
    path = Path(manifest_path).resolve()
    root, data = path.parent, read_json(path)
    require(markers_per_annotation > 0, 'marker count must be positive')
    require(data['figure_format_policy'] == 'png_only', 'PNG-only policy missing')
    full = data.get('delivery_contract') in ('rna_full_v1', 'rna_full_v2')
    fixed = data.get('delivery_contract') == 'rna_full_v2'
    require(not require_full or fixed, 'full RNA overview with doublet diagnostics required (fixed rna_full_v2 layout)')
    expected = list('ABCDEFGHIJKLMNO') if full and data.get('doublet_diagnostics', {}).get('status') == 'performed' else list('ABCDEFGHIJK')
    require(data['panels'] == expected, 'complete integrated RNA panels required')
    types = data['cell_type_order']
    require(bool(types) and len(types) == len(set(types)) == data['candidate_types'], 'annotation order/count mismatch')
    require(all(str(x).strip() and '\n' not in x and '\r' not in x for x in types), 'blank/wrapped annotation')
    require(data['cells'] > 0 and data['dpi'] == 300, 'invalid cell count or DPI')
    require(bool(data['dotplot']['color']) and bool(data['dotplot']['area']) and bool(data['composition']),
            'expression scale or denominator missing')
    artifacts = {}
    for item in data['artifacts']:
        relative = item['path']
        target = (root / relative).resolve()
        require(not Path(relative).is_absolute() and root in target.parents, 'artifact outside delivery')
        require(relative not in artifacts, 'duplicate artifact: ' + relative)
        require(target.is_file() and target.stat().st_size == item['bytes'] > 0, 'missing/empty artifact: ' + relative)
        require(sha(target) == item['sha256'], 'artifact hash mismatch: ' + relative)
        artifacts[relative] = item['sha256']
    # Also reject unregistered forbidden duplicates within this new delivery.
    for target in root.rglob('*'):
        if not target.is_file():
            continue
        name = target.name.lower()
        require(target.suffix.lower() not in ('.pdf', '.svg') and
                not (name.endswith('.png') and any(x in name for x in ('preview', 'review', 'thumbnail'))),
                'PNG-only: forbidden figure copy ' + name)
        if target.suffix.lower() == '.png':
            require(str(target.relative_to(root)) in artifacts, 'unregistered PNG: ' + name)
    figure = Path(data['figure'])
    figure = figure.resolve() if figure.is_absolute() else (root / figure).resolve()
    require(root in figure.parents, 'main figure outside delivery')
    main = str(figure.relative_to(root))
    require(main in artifacts and figure.suffix.lower() == '.png', 'main PNG missing')
    for name in [x for x in artifacts if x.endswith('.png')]:
        with (root / name).open('rb') as stream:
            header = stream.read(24)
        require(len(header) == 24 and header[:8] == b'\x89PNG\r\n\x1a\n' and header[12:16] == b'IHDR', 'invalid PNG header')
        pixels = list(struct.unpack('>II', header[16:24]))
        require(all(x > 0 for x in pixels), 'empty PNG dimensions')
        if name == main:
            require(pixels == data['pixels'], 'main PNG dimensions mismatch')
            if fixed:
                require(png_dpi(root/name) == 300, 'main PNG must encode 300 DPI')
        if name.startswith('single_panels/'):
            require(pixels == [2400, 2400], 'individual embedding must be 2400x2400')
    require(any(x.startswith('single_panels/') and x.endswith('.png') for x in artifacts), 'individual UMAPs missing')
    require(bool(data['source_sha256']), 'source hashes missing')
    for source, digest in data['source_sha256'].items():
        require(sha(Path(source)) == digest, 'source changed: ' + source)

    def exported(name):
        require(name in artifacts, 'required source table missing: ' + name)
        return root / name

    mapping = data['marker_triplets']
    require(data['markers_per_annotation'] == markers_per_annotation and set(mapping) == set(types),
            'marker count/annotation coverage mismatch')
    for label in types:
        genes = mapping[label]
        require(len(genes) == len(set(genes)) == markers_per_annotation and all(str(g).strip() for g in genes),
                'expected distinct markers per annotation: ' + label)
    genes = list(dict.fromkeys(g for label in types for g in mapping[label]))
    require(data['markers'] == len(genes), 'unique marker count mismatch')
    with exported('tables/marker_triplets.tsv').open(newline='') as stream:
        rows = list(csv.DictReader(stream, delimiter='\t'))
    require([r['cell_type'] for r in rows] == types, 'marker mapping row order mismatch')
    for row in rows:
        require(int(row['marker_count']) == markers_per_annotation and
                [row['marker_' + str(i + 1)] for i in range(markers_per_annotation)] == mapping[row['cell_type']],
                'marker mapping table differs from manifest')
    for name in ('marker_mean_log_expression', 'marker_fraction_expressing'):
        labels, columns, values = table(exported('tables/' + name + '.tsv'))
        require(labels == types and columns == genes, 'marker matrix order/coverage mismatch')
        if name.endswith('expressing'):
            require(all(x <= 1 for row in values for x in row), 'expression fractions exceed one')
        for i, label in enumerate(types):
            require(all(values[i][genes.index(g)] > 0 for g in mapping[label]), 'unsupported own-group marker: ' + label)
    for group in ('sample', 'condition'):
        labels, columns, counts = table(exported('tables/' + group + '_cell_counts.tsv'))
        p_labels, p_columns, percentages = table(exported('tables/' + group + '_cell_percent.tsv'))
        require(columns == p_columns == types and labels == p_labels, 'composition labels mismatch')
        require(all(x.is_integer() for row in counts for x in row) and sum(map(sum, counts)) == data['cells'],
                'composition cell count mismatch')
        for row, percent in zip(counts, percentages):
            require(sum(row) > 0 and math.isclose(sum(percent), 100, abs_tol=1e-6), 'composition denominator mismatch')
            require(all(math.isclose(p, c / sum(row) * 100, abs_tol=1e-6) for c, p in zip(row, percent)),
                    'composition percentage differs from counts')
    with exported('tables/panel_source.tsv').open(newline='') as stream:
        rows = list(csv.DictReader(stream, delimiter='\t'))
    require(len(rows) == data['cells'] and len({r['cell_id'] for r in rows}) == data['cells'], 'panel cell IDs/count mismatch')
    if fixed:
        from rna_overview_layout import validate_layout
        validate_layout(data)
    if full:
        validate_doublets(root, data, artifacts, rows)
    review = read_json(root / 'visual_review.json')
    require(review['status'] == 'passed' and review['manifest_sha256'] == sha(path), 'missing/stale visual review')
    require(bool(review['reviewer']) and bool(review['notes']) and main in review['inspected'], 'main PNG review missing')
    for name, digest in review['inspected'].items():
        require(name in artifacts and name.endswith('.png') and digest == artifacts[name], 'stale image review: ' + name)
    return {'manifest': str(path), 'sha256': sha(path), 'cells': data['cells'], 'annotations': len(types),
            'unique_markers': len(genes), 'marker_assignments': len(types) * markers_per_annotation,
            'grants_biological_approval': False}


FULL_ROLES = {'doublet_before', 'doublet_after', 'doublet_class', 'doublet_score',
              'cell_type', 'leiden', 'sample', 'condition', 'confidence', 'total_counts',
              'detected_genes', 'mitochondrial_percent', 'composition_condition',
              'composition_sample', 'marker_dotplot'}


def validate_doublets(root, data, artifacts, main_rows):
    diagnostic = data['doublet_diagnostics']
    roles = data['panel_roles']
    require(set(roles) == set(data['panels']), 'panel role coverage mismatch')
    if diagnostic['status'] == 'not_applicable':
        require(bool(str(diagnostic.get('reason', '')).strip()) and
                bool(str(diagnostic.get('decision_source', '')).strip()),
                'doublet omission needs an explicit reason and decision source')
        require(diagnostic['decision_source'] in data['source_sha256'], 'doublet decision source must be hash-bound')
        require(len(roles) == 11 and set(roles.values()) == FULL_ROLES -
                {'doublet_before','doublet_after','doublet_class','doublet_score'}, 'core RNA panel roles incomplete')
        return
    require(diagnostic['status'] == 'performed' and bool(diagnostic['method']), 'doublet method/status missing')
    require(len(roles) == 15 and set(roles.values()) == FULL_ROLES, 'doublet/core RNA panel roles incomplete')
    require(diagnostic.get('same_before_coordinates_for_class_and_score') is True and
            diagnostic.get('cluster_numbers_are_independent') is True, 'doublet coordinate semantics missing')
    def rows(key):
        name = diagnostic[key]
        require(name in artifacts, 'registered doublet source table required: ' + name)
        with (root/name).open(newline='') as stream:
            result = list(csv.DictReader(stream, delimiter='\t'))
        require(bool(result) and len({x['cell_id'] for x in result}) == len(result), 'duplicate/empty doublet cell IDs')
        for row in result:
            require(all(math.isfinite(float(row[c])) for c in ['UMAP1','UMAP2']), 'nonfinite doublet coordinates')
            require(bool(row['leiden'].strip()), 'missing doublet cluster')
        return result
    before, after = rows('before_table'), rows('after_table')
    require(len(before) == diagnostic['before_cells'] and len(after) == diagnostic['after_cells'] == data['cells'],
            'doublet cell counts mismatch')
    calls, scores = diagnostic['class_column'], diagnostic['score_column']
    singlet, doublet = diagnostic['singlet_label'], diagnostic['doublet_label']
    require(singlet != doublet, 'singlet/doublet labels must differ')
    require(all(x[calls] in [singlet,doublet] and math.isfinite(float(x[scores])) for x in before),
            'invalid doublet calls/scores')
    retained = {x['cell_id'] for x in before if x[calls] == singlet}
    after_by_id = {x['cell_id']:x for x in after}
    require(retained == set(after_by_id) == {x['cell_id'] for x in main_rows}, 'singlets/after/main cell IDs differ')
    for row in main_rows:
        other = after_by_id[row['cell_id']]
        require(row['leiden'] == other['leiden'] and all(math.isclose(float(row[c]),float(other[c]),rel_tol=0,abs_tol=1e-6)
                for c in ['UMAP1','UMAP2']), 'after/main clusters or coordinates differ')


def png_dpi(path):
    with path.open('rb') as stream:
        stream.read(8)
        while True:
            header = stream.read(8)
            if len(header) != 8:
                return None
            length,kind = struct.unpack('>I4s',header)
            if kind == b'pHYs':
                require(length == 9, 'invalid PNG resolution chunk')
                x,y,unit = struct.unpack('>IIB',stream.read(9))
                return round(x*.0254) if unit == 1 and x == y else None
            if kind in (b'IDAT', b'IEND'):
                return None
            stream.seek(length+4,1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--markers-per-annotation', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-full', action='store_true', help='Require integrated doublet diagnostics and A–O panel coverage')
    args = parser.parse_args()
    try:
        report = dict(status='complete', detail=validate_overview(args.manifest, args.markers_per_annotation, args.require_full))
    except (OSError, ValueError, KeyError, TypeError, AssertionError, struct.error) as error:
        report = dict(status='incomplete', error=str(error))
    write_json(args.output, report)
    print(report['status'])
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
