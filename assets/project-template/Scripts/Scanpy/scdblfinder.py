"""Sparse counts bridge to official Bioconductor scDblFinder; no fallback detector."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run_scdblfinder(counts, cell_ids, output_dir, options=None, seed=0):
    import numpy as np
    import pandas as pd
    from scipy import sparse
    from scipy.io import mmwrite

    options = dict(options or {})
    matrix = sparse.csr_matrix(counts)
    ids = pd.Index([str(value) for value in cell_ids], name='cell_id')
    if (matrix.shape[0] != len(ids) or not len(ids) or not matrix.shape[1]
            or ids.has_duplicates or any(not x or any(c in x for c in '\t\r\n') for x in ids)):
        raise ValueError('scDblFinder requires nonempty counts and unique, aligned cell IDs')
    if (not np.isfinite(matrix.data).all() or (matrix.data < 0).any()
            or not np.equal(matrix.data, np.floor(matrix.data)).all()):
        raise ValueError('scDblFinder requires original nonnegative integer counts')
    if (np.asarray(matrix.sum(axis=1)).ravel() <= 0).any():
        raise ValueError('scDblFinder cannot score zero-count cells')
    for key in ('dbr', 'dbr_per1k'):
        value = options.get(key)
        if value is not None and (isinstance(value, bool) or not np.isfinite(float(value))
                                  or not 0 < float(value) < 1):
            raise ValueError('%s must be null or a fraction strictly between 0 and 1' % key)
    clusters = options.get('clusters', False)
    if not isinstance(clusters, bool):
        raise ValueError('scdblfinder.clusters must be true or false')
    rscript = options.get('rscript') or str(Path(sys.executable).parent / 'Rscript')
    resolved = shutil.which(str(rscript))
    if resolved is None:
        raise RuntimeError('scDblFinder Rscript is unavailable; provision the analysis-core '
                           'environment or set analysis.scanpy.scdblfinder.rscript. '
                           'Scrublet is never an automatic fallback.')
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.scdblfinder-', dir=output) as tmp:
        work = Path(tmp)
        mmwrite(str(work / 'counts.mtx'), matrix.T.tocoo())
        (work / 'cells.tsv').write_text('\n'.join(ids) + '\n', encoding='utf-8')
        def digest(path):
            h = hashlib.sha256()
            with path.open('rb') as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b''):
                    h.update(block)
            return h.hexdigest()
        identity = {name: digest(work / name) for name in ('counts.mtx', 'cells.tsv')}
        command = [resolved, '--vanilla', str(Path(__file__).with_name('run_scdblfinder.R')),
                   str(work), str(int(seed)),
                   str(options['dbr']) if options.get('dbr') is not None else 'auto',
                   str(options['dbr_per1k']) if options.get('dbr_per1k') is not None else 'auto',
                   'TRUE' if clusters else 'FALSE']
        with (output / 'scdblfinder.log').open('w', encoding='utf-8') as log:
            subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
        calls = pd.read_csv(work / 'calls.tsv', sep='\t', dtype={'cell_id': str},
                            keep_default_na=False).set_index('cell_id')
        if calls.index.has_duplicates or set(calls.index) != set(ids):
            raise RuntimeError('scDblFinder returned mismatched or duplicate cell IDs')
        calls = calls.loc[ids]
        scores = calls['scDblFinder.score'].to_numpy(dtype=float)
        classes = calls['scDblFinder.class']
        if not np.isfinite(scores).all() or not classes.isin(['singlet', 'doublet']).all():
            raise RuntimeError('scDblFinder returned missing/invalid scores or classes')
        for name in ('calls.tsv', 'metadata.rds', 'R_session.txt', 'parameters.tsv'):
            shutil.copyfile(work / name, output / name)
        record = {'method': 'scDblFinder', 'seed': int(seed), 'clusters': clusters,
                  'dbr': options.get('dbr'), 'dbr_per1k': options.get('dbr_per1k'),
                  'rscript': resolved, 'n_cells': matrix.shape[0], 'n_genes': matrix.shape[1],
                  'input_sha256': identity, 'native_classification': True}
        (output / 'provenance.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    return calls
