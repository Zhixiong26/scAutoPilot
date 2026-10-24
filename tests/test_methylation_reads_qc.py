"""Compute-node smoke checks for numeric, identity and missing-data behavior."""
import argparse
import json
from pathlib import Path
import sys
import unittest
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_methylation_reads_qc import ranked_counts, classify, unique
class ReadsChecks(unittest.TestCase):
    def test_ties_zero_and_terminal(self):
        d=ranked_counts(pd.DataFrame({'cell_id':['b','a','c','d'],'reads_counts':[10,10,0,0]}))
        self.assertEqual(d.cell_id.tolist(),['a','b','c','d'])
        self.assertEqual(d.adjacent_relative_drop.iloc[:2].tolist(),[0,1])
        self.assertTrue(d.adjacent_relative_drop.iloc[2:].isna().all())
    def test_invalid_counts(self):
        for v in [-1,np.inf,np.nan,1.5]:
            with self.assertRaises(ValueError): ranked_counts(pd.DataFrame({'cell_id':['a'],'reads_counts':[v]}))
    def test_duplicate_identity(self):
        with self.assertRaises(ValueError): unique(pd.DataFrame({'cell_id':['a','a']}),'cell_id')
    def test_review_is_opt_in_and_missing_not_singlet(self):
        x=pd.Series([0,10,20,np.nan]); self.assertEqual(set(classify(x,{})),{'not_assessed'})
        self.assertEqual(classify(x,{'low_reads':0,'high_reads':20}).tolist(),['low_reads_review','within_configured_bounds','high_reads_review','not_assessed'])
        with self.assertRaises(ValueError): classify(x,{'low_reads':20,'high_reads':10})
    def test_single_and_empty(self):
        self.assertTrue(ranked_counts(pd.DataFrame({'cell_id':['a'],'reads_counts':[1]})).adjacent_relative_drop.isna().all())
        self.assertEqual(len(ranked_counts(pd.DataFrame({'cell_id':[],'reads_counts':[]}))),0)
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--task-dir',type=Path); a=p.parse_args()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReadsChecks))
    if not result.wasSuccessful(): sys.exit(1)
    if a.task_dir:
        a.task_dir.mkdir(parents=True,exist_ok=True); report=a.task_dir/'smoke_results.json'
        report.write_text(json.dumps({'passed':result.testsRun,'failures':0,'errors':0},indent=2))
        (a.task_dir/'task_outputs.json').write_text(json.dumps({'artifacts':[str(report)]},indent=2))
