#!/usr/bin/env python3
"""Create a deterministic, paired RNA/ALLC smoke fixture.

This is a data-fixture builder, not an analysis task.  It never modifies the
source project: RNA columns are copied into new 10x matrices and ALLC files plus
their tabix indexes are linked read-only into a new directory.  Selection is
from the intersection of RNA barcodes, ALLC filenames, and (when supplied) the
approved annotation table, so every recorded cell is usable by both modalities.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import random
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from scipy import io as scipy_io


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_barcodes(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [line.rstrip("\n").split("\t", 1)[0] for line in handle if line.strip()]


def allc_barcodes(path: Path):
    suffix = "_allc.gz"
    return {item.name[: -len(suffix)]: item for item in path.glob("*" + suffix) if item.is_file()}


def write_matrix(source: Path, destination: Path, columns):
    matrix = scipy_io.mmread(str(source)).tocsr()
    if max(columns, default=-1) >= matrix.shape[1]:
        raise ValueError("selected RNA column exceeds matrix width")
    subset = matrix[:, columns]
    with gzip.open(destination, "wb") as handle:
        scipy_io.mmwrite(handle, subset, field="integer", symmetry="general")
    return list(subset.shape), int(subset.nnz)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cells-per-sample", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260925)
    parser.add_argument("--annotation", type=Path)
    args = parser.parse_args()

    source = args.source_project.resolve()
    output = args.output.resolve()
    if args.cells_per_sample < 1:
        raise ValueError("cells-per-sample must be positive")
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing non-empty output directory: %s" % output)
    output.mkdir(parents=True, exist_ok=True)

    annotation_path = args.annotation.resolve() if args.annotation else None
    annotation = None
    if annotation_path:
        annotation = pd.read_csv(annotation_path, sep="\t", dtype=str)
        required = {"cell_id", "cell_type"}
        if not required.issubset(annotation.columns):
            raise ValueError("annotation is missing columns: %s" % ", ".join(sorted(required - set(annotation.columns))))
        annotation = annotation.set_index("cell_id", drop=False)

    sample_rows = []
    with (source / "config" / "samples.tsv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if str(row.get("include", "")).lower() in {"true", "1", "yes"}:
                sample_rows.append(row)

    manifest_rows = []
    matrix_records = {}
    selected_annotation = []
    for row in sample_rows:
        sample = row["sample_id"]
        rna_dir = (source / row["rna_path"]).resolve()
        allc_dir = (source / row["allc_root"]).resolve()
        barcodes = read_barcodes(rna_dir / "barcodes.tsv.gz")
        barcode_to_column = {barcode: index for index, barcode in enumerate(barcodes)}
        allc = allc_barcodes(allc_dir)
        eligible = set(barcode_to_column) & set(allc)
        if annotation is not None:
            eligible &= {
                cell_id[len(sample) + 1 :]
                for cell_id in annotation.index
                if cell_id.startswith(sample + "_")
            }
        if len(eligible) < args.cells_per_sample:
            raise ValueError(
                "%s has only %d paired eligible cells; requested %d"
                % (sample, len(eligible), args.cells_per_sample)
            )
        rng = random.Random("%s:%s:%s" % (args.seed, sample, args.cells_per_sample))
        chosen = sorted(rng.sample(sorted(eligible), args.cells_per_sample))
        columns = [barcode_to_column[cell] for cell in chosen]

        rna_out = output / "RNA" / sample
        allc_out = output / "ALLC" / sample
        rna_out.mkdir(parents=True)
        allc_out.mkdir(parents=True)
        shutil.copy2(rna_dir / "features.tsv.gz", rna_out / "features.tsv.gz")
        with gzip.open(rna_out / "barcodes.tsv.gz", "wt", encoding="utf-8", newline="") as handle:
            handle.writelines(cell + "\n" for cell in chosen)
        shape, nnz = write_matrix(rna_dir / "matrix.mtx.gz", rna_out / "matrix.mtx.gz", columns)

        for cell in chosen:
            allc_source = allc[cell].resolve()
            index_source = Path(str(allc_source) + ".tbi")
            if not index_source.is_file():
                # The source project's link can point at a file whose index uses
                # the link basename. Resolve that sibling as the authoritative index.
                index_source = Path(str(allc[cell]) + ".tbi").resolve()
            if not index_source.is_file():
                raise ValueError("missing ALLC index for %s" % allc_source)
            os.symlink(str(allc_source), str(allc_out / (cell + "_allc.gz")))
            os.symlink(str(index_source), str(allc_out / (cell + "_allc.gz.tbi")))
            cell_id = sample + "_" + cell
            item = {
                "sample_id": sample,
                "barcode": cell,
                "cell_id": cell_id,
                "rna_column": barcode_to_column[cell],
                "allc_source": str(allc_source),
            }
            if annotation is not None:
                item["cell_type"] = str(annotation.loc[cell_id, "cell_type"])
                selected_annotation.append(annotation.loc[cell_id].to_dict())
            manifest_rows.append(item)
        matrix_records[sample] = {
            "source": str(rna_dir),
            "source_matrix_sha256": sha256_file(rna_dir / "matrix.mtx.gz"),
            "output_shape": shape,
            "output_nnz": nnz,
            "selected_cells": len(chosen),
        }

    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_project": str(source),
        "annotation": str(annotation_path) if annotation_path else None,
        "annotation_sha256": sha256_file(annotation_path) if annotation_path else None,
        "seed": args.seed,
        "cells_per_sample": args.cells_per_sample,
        "samples": matrix_records,
        "total_cells": len(manifest_rows),
    }
    (output / "subset_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    pd.DataFrame(manifest_rows).to_csv(output / "selected_cells.tsv", sep="\t", index=False)
    if selected_annotation:
        pd.DataFrame(selected_annotation).to_csv(output / "annotation.tsv", sep="\t", index=False)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
