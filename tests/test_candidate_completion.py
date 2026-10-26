"""Candidate delivery preserves cell identity and does not confuse missing labels with approval."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from complete_scanpy_candidate import align_proposals
from init_project import RUNTIME_TOOLS


class CompletionTests(unittest.TestCase):
    def test_exact_cells_and_clusters_with_shuffled_reference(self):
        obs = pd.DataFrame({'leiden': ['0', '1']}, index=['a', 'b'])
        table = pd.DataFrame({'leiden': ['1', '0'], 'cell_type': ['B cells', 'T cells'],
            'confidence': ['high', 'low'], 'marker_evidence': ['CD79A', 'CD3E'],
            'review_status': ['agent_proposed_unapproved'] * 2}, index=['b', 'a'])
        aligned = align_proposals(obs, table, {'unassigned', ''})
        self.assertEqual(list(aligned.cell_type), ['T cells', 'B cells'])
        for column, value in [('leiden', '9'), ('cell_type', ' Unassigned '),
                              ('confidence', ''), ('marker_evidence', ''),
                              ('review_status', 'approved')]:
            invalid = table.copy(); invalid.loc['a', column] = value
            with self.subTest(column=column), self.assertRaises(ValueError):
                align_proposals(obs, invalid, {'unassigned', ''})
        with self.assertRaises(ValueError):
            align_proposals(obs, table.iloc[:1], {'unassigned'})
        self.assertIn('complete_scanpy_candidate.py', RUNTIME_TOOLS)

    def test_no_reference_notebook_branch_requires_agent_not_user(self):
        notebook = json.loads((ROOT / 'assets/project-template/Scripts/Scanpy/Notebooks/scanpy_workflow.ipynb').read_text())
        source = ''.join(next(c for c in notebook['cells'] if c.get('id') == 'manual-map')['source'])
        # Execute the actual annotation branch with two fake clusters and real TSV output.
        branch = source.split('def draw_marker_dotplot', 1)[0]
        with tempfile.TemporaryDirectory() as folder:
            obj = SimpleNamespace(obs=pd.DataFrame({'leiden': ['0', '1']}), n_obs=2,
                                  raw=SimpleNamespace(var_names=['CD3E', 'CD79A']))
            ns = dict(pd=pd, Path=Path, adata_work=obj, RUN_KIND='candidate',
                PARAMETERS={'cluster_to_cell_type': {}, 'annotation_profile_signature': '',
                            'analysis_signature': 'new', 'candidate_reference_annotation': '',
                            'candidate_top_markers_per_cluster': 1},
                candidate_marker_panels={}, marker_names=pd.DataFrame({'0':['CD3E'], '1':['CD79A']}),
                TABLE_DIR=Path(folder), display=lambda x: None)
            exec(compile(branch, 'actual-notebook-annotation-branch', 'exec'), ns)
            self.assertEqual(ns['ANNOTATION_STATUS'], 'candidate_annotation_incomplete')
            table = pd.read_csv(Path(folder) / 'candidate_annotation_audit.tsv', sep='\t')
            self.assertEqual(set(table.status), {'awaiting_agent_annotation'})
            self.assertEqual(list(table.top10_ranked_markers), ['CD3E', 'CD79A'])


if __name__ == '__main__':
    unittest.main()
