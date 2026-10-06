#!/usr/bin/env python3
"""Render existing Scanpy coordinates with shipped helpers; never rerun analysis.

Use a compute allocation on a Slurm system. Input is read-only and the output
directory must be new so this check cannot overwrite scientific run artifacts.
"""
import argparse
import ast
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np
import scanpy as sc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "assets/project-template/Scripts/Common"))
from embedding_plot import save_embedding


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = sc.read_h5ad(args.input)
    coordinates = {key: np.asarray(data.obsm[key]).copy() for key in data.obsm}
    notebook = ROOT / "assets/project-template/Scripts/Scanpy/Notebooks/scanpy_workflow.ipynb"
    cells = json.loads(notebook.read_text())["cells"]
    source = "\n".join("".join(cell["source"]) for cell in cells if cell["cell_type"] == "code")
    source = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("%"))
    names = {"save_figure"}
    tree = ast.parse(source)
    selected = [node for node in tree.body
                if (isinstance(node, ast.FunctionDef) and node.name in names)
                or (isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and (t.id.startswith("PANEL_") or t.id.startswith("COLORBAR_")
                                                or t.id == "LEGEND_INCHES") for t in node.targets))]
    args.output.mkdir(parents=True, exist_ok=False)
    namespace = {"plt": plt, "save_embedding": save_embedding,
                 "FIGURE_DIR": args.output, "SAVED_FIGURES": []}
    standard_cell = next(cell for cell in cells if cell.get("id") == "figure-standard")
    exec("".join(standard_cell["source"]), namespace)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(notebook), "exec"), namespace)
    results = []

    def check(figure, filename):
        namespace["save_figure"](filename, figure)
        image = mpimg.imread(args.output / filename)
        assert image.shape[:2] == (2400, 2400), image.shape
        figure.canvas.draw()
        panels = [ax for ax in figure.axes if not getattr(ax, "_colorbar", None)]
        for ax in panels:
            box = ax.get_window_extent()
            assert abs(box.width - box.height) < 0.01
            legend = ax.get_legend()
            if legend:
                assert getattr(legend, "_ncols", getattr(legend, "_ncol", 1)) == 1
                box = legend.get_window_extent(figure.canvas.get_renderer())
                assert box.x1 <= figure.bbox.width and box.y0 >= 0 and box.y1 <= figure.bbox.height
        results.append({"file": filename, "pixels": list(image.shape[:2]), "panels": len(panels)})

    for key in ("candidate_cell_type", "sample", "leiden"):
        figure, axes = namespace["embedding_figure"](npanels=1)
        sc.pl.umap(data, color=key, ax=axes[0], show=False, colorbar_loc=None,
                   legend_loc="right margin", frameon=False)
        namespace["square_panels"](axes)
        check(figure, "umap_%s.png" % key)
        if key == "candidate_cell_type":
            save_embedding(figure, args.output / "umap_candidate_cell_type.pdf")
        plt.close(figure)

    figure, axes = namespace["embedding_figure"](npanels=2)
    for ax, basis, legend in zip(axes, ["umap_before_harmony", "umap_after_harmony"],
                                [None, "right margin"]):
        sc.pl.embedding(data, basis=basis, color="sample", ax=ax, show=False,
                        legend_loc=legend, colorbar_loc=None, frameon=False)
    namespace["square_panels"](axes)
    check(figure, "umap_before_after_harmony_by_sample.png")
    plt.close(figure)

    figure, axes = namespace["embedding_figure"](npanels=2)
    for ax, key in zip(axes, ["total_counts", "pct_counts_mt"]):
        sc.pl.umap(data, color=key, ax=ax, show=False, colorbar_loc=None, frameon=False)
    namespace["square_panels"](axes)
    for ax, key in zip(axes, ["total_counts", "pct_counts_mt"]):
        namespace["side_colorbar"](figure, ax, namespace["panel_mappable"](ax), key)
    check(figure, "umap_harmony_qc.png")
    plt.close(figure)

    for key, original in coordinates.items():
        np.testing.assert_array_equal(original, data.obsm[key])
    print(json.dumps({"status": "passed", "cells": data.n_obs,
                      "coordinates_unchanged": True, "figures": results}, indent=2))


if __name__ == "__main__":
    main()
