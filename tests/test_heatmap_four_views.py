"""Numerical and artifact regression for the four-view methylation contract."""
import gzip
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('heatmap_four',ROOT/'assets/project-template/Scripts/Methscan/08_hypo_dmr_heatmaps.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)

class FourViews(unittest.TestCase):
    def test_support_nan_and_no_restandardization(self):
        z=np.array([[2,np.nan],[4,1],[6,3],[10,8],[20,9],[30,10]],float)
        labels,means,counts=m.celltype_zscore_means(z,['A']*3+['B']*3)
        self.assertEqual(labels,['A','B'])
        np.testing.assert_allclose(means,[[4,np.nan],[20,9]],equal_nan=True)
        np.testing.assert_array_equal(counts,[[3,2],[3,3]])
        with self.assertRaises(ValueError):m.celltype_zscore_means(z,['A'])

    def test_stage_emits_all_four_and_support(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);matrix=p/'matrix.tsv.gz';cells=[f'c{i}' for i in range(6)]
            with gzip.open(matrix,'wt') as f:
                f.write('chrom\tstart\tend\tdmr_id\t'+'\t'.join(cells)+'\n')
                f.write('chr1\t0\t10\td1\t0\t0.1\t0.2\t0.7\t0.8\t0.9\n')
                f.write('chr1\t20\t30\td2\t0.9\t0.8\t0.7\t0.2\t0.1\t0\n')
            ann=p/'cells.tsv';ann.write_text('cell_id\tcell_type\n'+''.join(f'{c}\t'+('A' if i<3 else 'B')+'\n' for i,c in enumerate(cells)))
            dmr=p/'dmr.tsv';dmr.write_text('dmr_id\thypo_cell_types\nd1\tA\nd2\tB\n')
            a=SimpleNamespace(run_dir=p,zscore_min_observed_cells=3,zscore_clip=3,compressed_colorbar_limit=1,dpi=25)
            summary=m.stage_plots(a,{'samples':[{'sample_id':'synthetic','dmrs':2,'single_cells':6,
                'matrix_file':str(matrix),'cell_annotations':str(ann),'dmr_annotations':str(dmr)}]})
            row=summary['samples'][0]
            for key in ['mean_ratio_plot','zscore_plot','zscore_compressed_colorbar_plot','zscore_mean_plot','zscore_mean_table','zscore_mean_support']:
                self.assertGreater(Path(row[key]).stat().st_size,0)
            with np.load(row['zscore_mean_matrices']) as s:
                self.assertEqual(s['zscore_mean'].shape,(2,2))
                self.assertTrue((s['observed_cells']==3).all())
                self.assertLess(s['zscore_mean'][0,0],0)
            self.assertEqual(summary['zscore_mean_min_observed_cells'],3)

if __name__=='__main__':unittest.main()
