#!/usr/bin/env python3
"""Train MethylVI on raw counts for a signed ALLCools, VMR or VMR+DMR input."""
from __future__ import annotations

import argparse
import json
import os
import warnings
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

import anndata as ad
import mudata
import numpy as np
import scanpy as sc
import scvi
import torch
from scvi.external import METHYLVI


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path(os.environ["SCMO_MVI_INPUT"]))
    parser.add_argument("--output", type=Path, default=Path(os.environ["SCMO_MVI_RESULTS"]))
    parser.add_argument("--batch-key", default=os.environ["SCMO_BATCH_KEY"])
    parser.add_argument("--epochs", type=int, default=int(os.environ["SCMO_EPOCHS"]))
    parser.add_argument("--batch-size", type=int, default=int(os.environ["SCMO_BATCH_SIZE"]))
    parser.add_argument("--threads", type=int, default=int(os.environ["SCMO_THREADS"]))
    parser.add_argument("--seed", type=int, default=int(os.environ["SCMO_SEED"]))
    parser.add_argument('--n-latent', type=int, default=int(os.environ.get('SCMO_MVI_N_LATENT', '20')))
    parser.add_argument('--n-hidden', type=int, default=int(os.environ.get('SCMO_MVI_N_HIDDEN', '128')))
    parser.add_argument('--n-layers', type=int, default=int(os.environ.get('SCMO_MVI_N_LAYERS', '1')))
    # Reads the configured split rather than assuming scvi's default, so methylvi.validation_fraction
    # is a live parameter. Soft default keeps the standalone routes working without the DAG's env.
    parser.add_argument("--validation-fraction", type=float,
                        default=float(os.environ.get("SCMO_VALIDATION_FRACTION", "0.1")))
    parser.add_argument("--accelerator", choices=("auto", "cpu", "gpu"), default="auto")
    args = parser.parse_args()
    if min(args.n_latent, args.n_hidden, args.n_layers) < 1:
        raise ValueError('model dimensions/layers must be positive')
    if not 0 < args.validation_fraction < 1:
        raise ValueError("validation-fraction must be between 0 and 1: %r" % args.validation_fraction)
    args.output.mkdir(parents=True, exist_ok=True)
    scvi.settings.seed = args.seed
    torch.set_num_threads(args.threads)

    mdata = mudata.read_h5mu(args.input)
    adata = mdata["mCG"]
    if args.batch_key not in adata.obs:
        raise KeyError(f"Batch key absent: {args.batch_key}")
    if adata.obs[args.batch_key].nunique() < 2:
        warnings.warn(f"Batch key {args.batch_key!r} has fewer than two levels")
    mc, cov = adata.layers["mc"], adata.layers["cov"]
    if not np.issubdtype(mc.dtype, np.integer) or not np.issubdtype(cov.dtype, np.integer):
        raise ValueError("mc/cov layers must contain integer counts")
    if np.any(mc > cov):
        raise ValueError("Invalid count layers: mc > cov")

    METHYLVI.setup_mudata(
        mdata, mc_layer="mc", cov_layer="cov", batch_key=args.batch_key,
        methylation_contexts=["mCG"], modalities={"batch_key": "mCG"},
    )
    model = METHYLVI(
        mdata, n_latent=args.n_latent, n_hidden=args.n_hidden, n_layers=args.n_layers,
        likelihood="betabinomial", dispersion="region",
    )
    accelerator = args.accelerator
    if accelerator == "auto":
        accelerator = "gpu" if torch.cuda.is_available() else "cpu"
    # MethylVI.train defaults train_size to 0.9 on its own, independently of validation_size, and
    # then rejects train_size + validation_size > 1 -- so passing validation_size alone would fail
    # for any fraction above 0.1. Both come from the configured fraction instead.
    model.train(
        max_epochs=args.epochs, early_stopping=True, batch_size=args.batch_size,
        train_size=1.0 - args.validation_fraction, validation_size=args.validation_fraction,
        accelerator=accelerator, devices=1,
    )
    model.save(args.output / "model", overwrite=True, save_anndata=False)
    # Preserve actual train/validation membership and histories for comparisons;
    # equal split fractions alone do not prove identical held-out observations.
    for split, indices in [('train', model.train_indices), ('validation', model.validation_indices), ('test', model.test_indices)]:
        adata.obs.iloc[np.asarray(indices, dtype=int)].index.to_series().to_csv(
            args.output / ('%s_cell_ids.tsv' % split), sep='\t', index=False, header=['cell_id'])
    history_dir = args.output / 'training_history'
    history_dir.mkdir(exist_ok=True)
    for number, (name, history) in enumerate(model.history.items()):
        history.to_csv(history_dir / ('%02d_%s.tsv' % (number, ''.join(c if c.isalnum() or c == '_' else '_' for c in name))), sep='\t')
    latent = np.asarray(model.get_latent_representation(batch_size=args.batch_size), dtype=np.float32)
    np.save(args.output / "methylvi_latent.npy", latent)
    embedding = ad.AnnData(X=latent, obs=adata.obs.copy())
    embedding.obsm["X_methylVI"] = latent
    sc.pp.neighbors(embedding, use_rep="X_methylVI", n_neighbors=15, random_state=args.seed)
    sc.tl.umap(embedding, random_state=args.seed)
    sc.tl.leiden(
        embedding, resolution=1.0, key_added="methylVI_leiden", random_state=args.seed
    )
    embedding.write_h5ad(args.output / "methylvi_embedding.h5ad", compression="gzip")
    summary = {
        "input": str(args.input), "cells": embedding.n_obs, "features": adata.n_vars,
        "batch_key": args.batch_key, "batch_levels": int(adata.obs[args.batch_key].nunique()),
        "accelerator": accelerator, "epochs_requested": args.epochs,
        "validation_fraction": args.validation_fraction,
        "n_latent": args.n_latent, "n_hidden": args.n_hidden, "n_layers": args.n_layers,
        "seed": args.seed, "batch_size": args.batch_size,
        "training_history": str(history_dir),
    }
    (args.output / "run_summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
