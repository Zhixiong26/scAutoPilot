"""Default selection, sparse R boundary and native call/filtering contracts."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / 'assets/project-template/Scripts/Scanpy'
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(STAGE))
from run_scanpy_notebook import build_parameters, RunnerError
from scdblfinder import run_scdblfinder


class DefaultSelectionTests(unittest.TestCase):
    def parameters(self, analysis=None):
        return build_parameters(ROOT, {'analysis': {'scanpy': analysis or {}}},
                                [{'include': True, 'rna_path': 'Data/counts',
                                  'rna_format': '10x_mtx', 'cell_id_prefix': 'capture'}],
                                Path('/tmp/output'), 'test', None)

    def test_default_and_explicit_alternative_have_different_signatures(self):
        default = self.parameters()
        legacy = self.parameters({'doublets': {'method': 'scrublet'}})
        self.assertEqual(default['doublet_method'], 'scDblFinder')
        self.assertIsNone(default['scdblfinder']['dbr'])
        self.assertIsNone(default['scdblfinder']['dbr_per1k'])
        self.assertEqual(legacy['doublet_method'], 'scrublet')
        self.assertNotEqual(default['analysis_signature'], legacy['analysis_signature'])

    def test_old_scrublet_options_do_not_select_scrublet(self):
        p = self.parameters({'scrublet': {'doublet_rate_per_1000': 0.02}})
        self.assertEqual(p['doublet_method'], 'scDblFinder')
        self.assertIsNone(p['scdblfinder']['dbr_per1k'])

    def test_configured_r_path_and_partial_options(self):
        p = self.parameters({'scdblfinder': {'rscript': '.environments/r/bin/Rscript', 'dbr': 0.05}})
        self.assertEqual(p['scdblfinder']['rscript'], str(ROOT / '.environments/r/bin/Rscript'))
        self.assertFalse(p['scdblfinder']['clusters'])
        self.assertEqual(p['scdblfinder']['dbr'], 0.05)

    def test_unknown_detector_fails(self):
        with self.assertRaises(RunnerError):
            self.parameters({'doublets': {'method': 'typo'}})


@unittest.skipUnless(importlib.util.find_spec('scipy') and importlib.util.find_spec('pandas'),
                     'sparse bridge tests require scipy and pandas')
class SparseBridgeTests(unittest.TestCase):
    def fake_r(self, command, **kwargs):
        from scipy.io import mmread
        work = Path(command[3])
        self.assertEqual(mmread(work / 'counts.mtx').shape, (3, 2))
        self.assertEqual((work / 'cells.tsv').read_text().splitlines(), ['NA', 'cell_b'])
        self.assertEqual(command[-3:], ['auto', 'auto', 'FALSE'])
        (work / 'calls.tsv').write_text(
            'cell_id\tscDblFinder.score\tscDblFinder.class\n'
            'cell_b\t0.1\tdoublet\nNA\t0.9\tsinglet\n')
        for name in ('metadata.rds', 'R_session.txt', 'parameters.tsv'):
            (work / name).write_text('fixture R boundary evidence\n')

    def test_sparse_orientation_id_join_and_native_calls(self):
        from scipy import sparse
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch('scdblfinder.shutil.which', return_value='/fake/Rscript'), \
                mock.patch('scdblfinder.subprocess.run', side_effect=self.fake_r):
            calls = run_scdblfinder(sparse.csr_matrix([[1, 0, 2], [0, 3, 0]]),
                                    ['NA', 'cell_b'], tmp)
            self.assertEqual(list(calls.index), ['NA', 'cell_b'])
            # Native calls are authoritative even when scores suggest a different cutoff.
            self.assertEqual(list(calls['scDblFinder.class']), ['singlet', 'doublet'])
            self.assertTrue((Path(tmp) / 'provenance.json').is_file())
            self.assertFalse(list(Path(tmp).glob('.scdblfinder-*')))

    def test_invalid_counts_and_ids_fail_before_r(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch('scdblfinder.subprocess.run') as run:
            for counts, ids in [([[0.5]], ['a']), ([[-1]], ['a']), ([[0]], ['a']),
                                ([[1], [2]], ['a', 'a']), ([[float('nan')]], ['a'])]:
                with self.subTest(counts=counts, ids=ids), self.assertRaises(ValueError):
                    run_scdblfinder(counts, ids, tmp)
            run.assert_not_called()

    def test_missing_r_fails_without_fallback(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch('scdblfinder.shutil.which', return_value=None), \
                mock.patch('scdblfinder.subprocess.run') as run:
            with self.assertRaisesRegex(RuntimeError, 'never an automatic fallback'):
                run_scdblfinder([[1]], ['a'], tmp)
            run.assert_not_called()

    def test_bad_returned_ids_rejected(self):
        def bad_r(command, **kwargs):
            self.fake_r(command, **kwargs)
            p = Path(command[3]) / 'calls.tsv'
            p.write_text(p.read_text().replace('cell_b', 'unknown_cell'))
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch('scdblfinder.shutil.which', return_value='/fake/Rscript'), \
                mock.patch('scdblfinder.subprocess.run', side_effect=bad_r):
            with self.assertRaisesRegex(RuntimeError, 'mismatched'):
                run_scdblfinder([[1, 0, 2], [0, 3, 0]], ['NA', 'cell_b'], tmp)


@unittest.skipUnless(importlib.util.find_spec('anndata'), 'notebook boundary requires anndata')
class NotebookFilterTests(unittest.TestCase):
    def test_default_filters_native_calls_and_keeps_all_evidence(self):
        import anndata as ad
        import numpy as np
        import pandas as pd
        from scipy import sparse
        nb = json.loads((STAGE / 'Notebooks/scanpy_workflow.ipynb').read_text())
        code = next(''.join(c['source']) for c in nb['cells']
                    if 'all_doublet_calls = []' in ''.join(c['source']))
        sample = ad.AnnData(sparse.csr_matrix([[1, 0, 2], [0, 3, 0]]),
                           obs=pd.DataFrame({'pass_basic_qc': [True, True]}, index=['a', 'b']))
        sample.layers['counts'] = sample.X.copy()
        sample.obs['cohort'] = 'capture'
        def detector(counts, ids, *args):
            self.assertEqual(counts.shape, (2, 3))  # Full genes, before filtering/HVG.
            return pd.DataFrame({'scDblFinder.score': [0.9, 0.1],
                                 'scDblFinder.class': ['singlet', 'doublet']}, index=ids)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch('scdblfinder.run_scdblfinder', side_effect=detector) as detect:
            state = dict(samples={'capture': sample}, DOUBLET_LIBRARY_IDS={'capture': 'lib_1'},
                         DOUBLET_METHOD='scDblFinder', DOUBLET_MIN_CELLS=1, SCDBLFINDER={},
                         RANDOM_SEED=0, TABLE_DIR=Path(tmp), MIN_CELLS_PER_GENE=1,
                         plt=mock.Mock(), sc=mock.Mock(), pd=pd, np=np, ad=ad,
                         display=lambda x: None, save_figure=lambda x: None)
            exec(compile(code, 'doublet-cell', 'exec'), state)
            self.assertEqual(list(state['adata_qc'].obs_names), ['a'])
            evidence = pd.read_csv(Path(tmp) / 'doublet_calls.tsv', sep='\t')
            self.assertEqual(list(evidence['cell_id']), ['a', 'b'])
            self.assertEqual(list(evidence['doublet_class']), ['singlet', 'doublet'])
            self.assertEqual(sample.n_obs, 2)
            detect.assert_called_once()
            state['DOUBLET_LIBRARY_IDS'] = {}
            with self.assertRaisesRegex(ValueError, 'capture metadata'):
                exec(compile(code, 'doublet-cell', 'exec'), state)
            detect.assert_called_once()


if __name__ == '__main__':
    unittest.main()
