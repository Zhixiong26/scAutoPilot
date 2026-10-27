"""Reject incomplete marker panels and stale/contradictory overview evidence."""
import csv
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from audit_rna_overview import validate_overview
from figures_comparison_evidence import sha
from _common import write_json


def png(width, height):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\0' * (width + 1)) * height)) + chunk(b'IEND', b''))


def fixture(root):
    (root / 'tables').mkdir(); (root / 'single_panels').mkdir()
    (root / 'main.png').write_bytes(png(20, 20))
    (root / 'single_panels/A.png').write_bytes(png(2400, 2400))
    (root / 'input.txt').write_text('immutable input fixture')
    def tsv(name, rows):
        with (root / 'tables' / (name + '.tsv')).open('w', newline='') as stream:
            csv.writer(stream, delimiter='\t').writerows(rows)
    types = ['Type A', 'Type B']; genes = ['A', 'B', 'C', 'D', 'E']
    mapping = {'Type A': ['A', 'B', 'C'], 'Type B': ['C', 'D', 'E']}
    tsv('marker_triplets', [['cell_type', 'marker_1', 'marker_2', 'marker_3', 'marker_count'],
                           ['Type A', 'A', 'B', 'C', 3], ['Type B', 'C', 'D', 'E', 3]])
    for name in ['marker_mean_log_expression', 'marker_fraction_expressing']:
        tsv(name, [[''] + genes, ['Type A', 1, 1, 1, 0, 0], ['Type B', 0, 0, 1, 1, 1]])
    for group in ['sample', 'condition']:
        tsv(group + '_cell_counts', [[''] + types, ['group1', 1, 1]])
        tsv(group + '_cell_percent', [[''] + types, ['group1', 50, 50]])
    tsv('panel_source', [['cell_id'], ['cell1'], ['cell2']])
    manifest = dict(figure_format_policy='png_only', panels=list('ABCDEFGHIJK'), cell_type_order=types,
                    candidate_types=2, cells=2, dpi=300, pixels=[20,20], figure='main.png',
                    dotplot={'color':'mean log-normalized expression','area':'fraction > 0'}, composition='within group',
                    source_sha256={str(root / 'input.txt'):sha(root / 'input.txt')},
                    markers=5, markers_per_annotation=3, marker_triplets=mapping)
    seal(root, manifest)
    return manifest


def seal(root, manifest):
    files = [p for p in root.rglob('*') if p.is_file() and p.suffix in ['.png', '.tsv']]
    manifest['artifacts'] = [dict(path=str(p.relative_to(root)), sha256=sha(p), bytes=p.stat().st_size) for p in files]
    write_json(root / 'delivery_manifest.json', manifest)
    write_json(root / 'visual_review.json', dict(status='passed', reviewer='fixture', notes='fixture only',
        manifest_sha256=sha(root / 'delivery_manifest.json'), inspected={'main.png':sha(root / 'main.png')}))


def full_fixture(root):
    from audit_rna_overview import FULL_ROLES
    manifest = fixture(root)
    manifest.update(delivery_contract='rna_full_v1', panels=list('ABCDEFGHIJKLMNO'),
                    panel_roles=dict(zip(list('ABCDEFGHIJKLMNO'), sorted(FULL_ROLES))))
    manifest['doublet_diagnostics'] = dict(status='performed', method='fixture', before_cells=3, after_cells=2,
        before_table='tables/before.tsv', after_table='tables/after.tsv', class_column='call',score_column='score',
        singlet_label='singlet',doublet_label='doublet',cluster_numbers_are_independent=True,
        same_before_coordinates_for_class_and_score=True)
    (root/'tables/before.tsv').write_text('cell_id\tleiden\tUMAP1\tUMAP2\tcall\tscore\ncell1\t0\t0\t1\tsinglet\t0.1\ncell2\t1\t2\t3\tsinglet\t0.2\ncell3\t1\t3\t4\tdoublet\t0.9\n')
    after='cell_id\tleiden\tUMAP1\tUMAP2\ncell1\t1\t0\t1\ncell2\t0\t2\t3\n'
    (root/'tables/after.tsv').write_text(after); (root/'tables/panel_source.tsv').write_text(after)
    seal(root,manifest)
    return manifest


class OverviewTests(unittest.TestCase):
    def test_full_contract_rejects_legacy_and_accepts_complete_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); fixture(root)
            with self.assertRaisesRegex(ValueError,'doublet diagnostics required'):
                validate_overview(root/'delivery_manifest.json',require_full=True)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); full_fixture(root)
            self.assertEqual(validate_overview(root/'delivery_manifest.json',require_full=True)['cells'],2)

    def test_full_contract_rejects_wrong_retained_cells_coordinates_and_roles(self):
        for change in ['ids','coords','roles','calls','score']:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                root=Path(temp); manifest=full_fixture(root)
                if change=='roles': manifest['panel_roles']['A']='unknown_panel'
                else:
                    name='after.tsv' if change in ['ids','coords'] else 'before.tsv'
                    file=root/'tables'/name; value=file.read_text()
                    pairs={'ids':('cell2','wrong'),'coords':('cell1\t1\t0\t1','cell1\t1\t99\t1'),
                           'calls':('singlet','uncertain'),'score':('0.1','nan')}
                    a,b=pairs[change]; file.write_text(value.replace(a,b,1))
                seal(root,manifest)
                with self.assertRaises(ValueError): validate_overview(root/'delivery_manifest.json',require_full=True)

    def test_shared_genes_are_valid_without_claiming_specificity(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); fixture(root)
            result=validate_overview(root/'delivery_manifest.json')
            self.assertEqual(result['unique_markers'],5)
            self.assertEqual(result['marker_assignments'],6)
            self.assertFalse(result['grants_biological_approval'])

    def test_invalid_manifest_content_fails_even_when_resealed(self):
        for field, value in [('panels',list('ABCDEFGHIJ')), ('markers',6),
                             ('marker_triplets',{'Type A':['A','B'], 'Type B':['C','D','E']}),
                             ('pixels',[100,100])]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                root=Path(temp); manifest=fixture(root); manifest[field]=value; seal(root,manifest)
                with self.assertRaises(ValueError): validate_overview(root/'delivery_manifest.json')

    def test_bad_tables_fail_with_valid_hashes(self):
        changes=[('marker_fraction_expressing.tsv','Type A\t1\t1\t1','Type A\t2\t1\t1'),
                 ('marker_triplets.tsv','Type A\tA\tB\tC','Type A\tA\tB\tE'),
                 ('sample_cell_percent.tsv','group1\t50\t50','group1\t30\t70'),
                 ('panel_source.tsv','cell2','cell1')]
        for name, old, new in changes:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root=Path(temp); manifest=fixture(root); p=root/'tables'/name
                p.write_text(p.read_text().replace(old,new)); seal(root,manifest)
                with self.assertRaises(ValueError): validate_overview(root/'delivery_manifest.json')

    def test_stale_source_image_or_review_fails(self):
        for name in ['input.txt','main.png','visual_review.json']:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root=Path(temp); fixture(root)
                if name.endswith('.json'):
                    review=json.loads((root/name).read_text()); review['manifest_sha256']='old'; write_json(root/name,review)
                else: (root/name).write_bytes(b'changed')
                with self.assertRaises(ValueError): validate_overview(root/'delivery_manifest.json')

    def test_unregistered_pdf_or_preview_fails(self):
        for name in ['extra.pdf','main_preview.png']:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root=Path(temp); fixture(root); (root/name).write_bytes(b'extra')
                with self.assertRaisesRegex(ValueError,'PNG-only'): validate_overview(root/'delivery_manifest.json')


if __name__=='__main__': unittest.main()
