"""Narrow runtime compatibility fixes for ALLCools 1.1.1."""
from __future__ import annotations

import warnings

import leidenalg
import numpy as np
import pandas as pd
from natsort import natsorted


def leiden_runner_cells_by_runs(g, random_states, partition_type, **partition_kwargs):
    """Return one column per Leiden run and one row per cell.

    ALLCools 1.1.1 constructs ``DataFrame(results, columns=random_states)``.
    Each result is a cell-length vector, so Pandas correctly rejects that
    runs-by-cells matrix when the number of cells differs from the number of
    seeds. ConsensusClustering concatenates worker results column-wise and
    later transposes them, confirming that cells-by-runs is the intended form.
    """
    columns = {}
    for seed in random_states:
        part = leidenalg.find_partition(g, partition_type, seed=seed, **partition_kwargs)
        groups = np.asarray(part.membership).astype("U")
        columns[int(seed)] = pd.Categorical(
            values=groups,
            categories=natsorted(np.unique(groups).astype("U")),
        )
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore")
        return pd.DataFrame(columns)
