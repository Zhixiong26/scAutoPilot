#!/usr/bin/env python3
"""Build a read-only MethSCAn scan view that excludes unusable chromosomes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def link(source: Path, destination: Path) -> None:
    """Use a relative symlink so the view is cheap and its origin stays visible."""
    destination.symlink_to(os.path.relpath(source, destination.parent))


def build_view(source: Path, output: Path) -> dict:
    source = source.resolve()
    output = output.absolute()
    if not source.is_dir():
        raise FileNotFoundError(source)
    if output.exists():
        raise FileExistsError("VMR input view already exists; use a new run directory: %s" % output)
    header = source / "column_header.txt"
    if not header.is_file() or header.stat().st_size == 0:
        raise FileNotFoundError(header)

    matrices = sorted(source.glob("*.npz"))
    if not matrices:
        raise ValueError("No MethSCAn chromosome matrices found in %s" % source)

    output.mkdir(parents=True)
    (output / "smoothed").mkdir()
    link(header, output / header.name)
    for optional in ("cell_stats.csv", "run_info.txt"):
        candidate = source / optional
        if candidate.is_file():
            link(candidate, output / optional)

    included = []
    excluded = []
    for matrix in matrices:
        smoothed = source / "smoothed" / (matrix.stem + ".csv")
        if not smoothed.is_file():
            raise FileNotFoundError("Missing smoothed chromosome paired with %s: %s" % (matrix, smoothed))
        if matrix.stat().st_size == 0:
            raise ValueError("Empty MethSCAn sparse matrix: %s" % matrix)
        if smoothed.stat().st_size == 0:
            excluded.append({"chromosome": matrix.stem, "reason": "empty_smoothed_values"})
            continue
        link(matrix, output / matrix.name)
        link(smoothed, output / "smoothed" / smoothed.name)
        included.append(matrix.stem)

    if not included:
        raise ValueError("Every chromosome has an empty smoothed-value file")
    manifest = {
        "schema_version": 1,
        "source_data_dir": str(source),
        "view_data_dir": str(output),
        "link_type": "relative_symlink_no_copy",
        "included_chromosomes": included,
        "excluded_chromosomes": excluded,
    }
    (output / "vmr_input_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (output / "excluded_chromosomes.tsv").open("w", encoding="utf-8") as handle:
        handle.write("chromosome\treason\n")
        for row in excluded:
            handle.write("%s\t%s\n" % (row["chromosome"], row["reason"]))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = build_view(args.source, args.output)
    print(json.dumps({
        "included": len(manifest["included_chromosomes"]),
        "excluded": len(manifest["excluded_chromosomes"]),
        "output": manifest["view_data_dir"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
