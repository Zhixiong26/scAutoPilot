"""Render and measure exported embeddings, not just their subplot specifications."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec("matplotlib"), "requires matplotlib")
class EmbeddingExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
        sys.path.insert(0, str(ROOT / "assets/project-template/Scripts/Common"))
        import embedding_plot
        cls.plt = plt
        cls.helper = embedding_plot

    def tearDown(self):
        self.plt.close("all")

    def check_square(self, figure, panels):
        self.assertEqual(tuple(figure.get_size_inches()), (8, 8))
        figure.canvas.draw()
        for ax in panels:
            box = ax.get_window_extent()
            self.assertAlmostEqual(box.width, box.height, places=6)
            self.assertAlmostEqual(abs(ax.get_xlim()[1] - ax.get_xlim()[0]),
                                   abs(ax.get_ylim()[1] - ax.get_ylim()[0]), places=6)

    def check_legend(self, figure, ax):
        legend = ax.get_legend()
        self.assertEqual(legend._ncols if hasattr(legend, "_ncols") else legend._ncol, 1)
        box = legend.get_window_extent(figure.canvas.get_renderer())
        self.assertGreater(box.x0, ax.get_window_extent().x1)
        self.assertGreaterEqual(box.y0, 0)
        self.assertLessEqual(box.y1, figure.bbox.height)
        self.assertLessEqual(box.x1, figure.bbox.width)

    def test_categorical_export_is_square_even_with_global_tight_crop(self):
        import matplotlib as mpl
        import matplotlib.image as mpimg
        figure, ax = self.plt.subplots(figsize=(7, 5))
        for index in range(12):
            ax.scatter([index], [index / 4], label="Cell type %d" % index)
        ax.legend(ncol=2)
        offsets = ax.collections[0].get_offsets().copy()
        with tempfile.TemporaryDirectory() as temp, mpl.rc_context({"savefig.bbox": "tight"}):
            path = Path(temp) / "umap.png"
            self.helper.save_embedding(figure, path)
            self.assertEqual(mpimg.imread(path).shape[:2], (2400, 2400))
            pdf = Path(temp) / "umap.pdf"
            self.helper.save_embedding(figure, pdf)
            self.assertRegex(pdf.read_bytes(), rb"/MediaBox\s*\[\s*0\s+0\s+576\s+576\s*\]")
        self.check_square(figure, [ax])
        self.assertAlmostEqual(ax.get_window_extent().width / figure.dpi, 4)
        self.check_legend(figure, ax)
        self.assertTrue((offsets == ax.collections[0].get_offsets()).all())

    def test_horizontal_colorbar_becomes_one_vertical_bar_without_changing_values(self):
        figure, ax = self.plt.subplots()
        cloud = ax.scatter([0, 10], [0, 2], c=[1, 9], vmin=0, vmax=10)
        figure.colorbar(cloud, ax=ax, orientation="horizontal", label="total counts")
        self.helper.standardize_embedding(figure)
        self.helper.standardize_embedding(figure)  # repeated saves must not add axes/bars
        self.check_square(figure, [ax])
        bars = [a._colorbar for a in figure.axes if getattr(a, "_colorbar", None)]
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].orientation, "vertical")
        self.assertEqual(bars[0].ax.get_ylabel(), "total counts")
        self.assertIs(bars[0].mappable, cloud)
        self.assertEqual((cloud.norm.vmin, cloud.norm.vmax), (0, 10))
        self.assertGreater(bars[0].ax.get_position().x0, ax.get_position().x1)

    def test_two_panel_comparison_retains_shared_limits_and_single_column_key(self):
        figure, axes = self.plt.subplots(1, 2, figsize=(13, 4))
        for ax in axes:
            ax.scatter([0, 10], [0, 2], label="Sample A")
            ax.set_xlim(-1, 11)
            ax.set_ylim(-5, 7)
        axes[1].legend(ncol=2)
        self.helper.standardize_embedding(figure)
        self.check_square(figure, axes)
        self.assertEqual(axes[0].get_xlim(), axes[1].get_xlim())
        self.assertEqual(axes[0].get_ylim(), axes[1].get_ylim())
        self.assertGreater(axes[0].get_position().y0, axes[1].get_position().y1)
        self.check_legend(figure, axes[1])

    def test_four_panel_mixed_overview(self):
        figure, axes = self.plt.subplots(1, 4, figsize=(20, 5))
        for ax in axes[[0, 2, 3]]:
            for index in range(10):
                ax.scatter([index], [index / 3], label="population_%d" % index)
            ax.legend(ncol=2)
        cloud = axes[1].scatter([0, 10], [0, 2], c=[0, 1])
        figure.colorbar(cloud, ax=axes[1], label="probability")
        self.helper.standardize_embedding(figure)
        self.check_square(figure, axes)
        for ax in axes[[0, 2, 3]]:
            self.check_legend(figure, ax)
        self.assertEqual(len(figure.axes), 5)

    def test_many_categories_do_not_silently_add_columns(self):
        figure, ax = self.plt.subplots()
        for index in range(36):
            ax.scatter([index], [index], label="Population %d" % index)
        ax.legend(ncol=3)
        self.helper.standardize_embedding(figure)
        self.check_square(figure, [ax])
        self.check_legend(figure, ax)

    @unittest.skipUnless(importlib.util.find_spec("scanpy"), "requires scanpy")
    def test_real_scanpy_legend_and_colorbar(self):
        import anndata as ad
        import numpy as np
        import pandas as pd
        import scanpy as sc
        data = ad.AnnData(np.ones((30, 2)))
        data.obs["cell_type"] = pd.Categorical(["AT1", "AT2", "Macrophage"] * 10)
        data.obs["coverage"] = np.arange(30)
        data.obsm["X_umap"] = np.random.RandomState(0).normal(size=(30, 2))
        coordinates = data.obsm["X_umap"].copy()
        for keys in ("cell_type", "coverage", ["cell_type", "coverage"]):
            figure = sc.pl.umap(data, color=keys, show=False, return_fig=True)
            self.helper.standardize_embedding(figure)
            panels = [ax for ax in figure.axes if not getattr(ax, "_colorbar", None)]
            self.check_square(figure, panels)
            for ax in panels:
                if ax.get_legend():
                    self.check_legend(figure, ax)
        np.testing.assert_array_equal(coordinates, data.obsm["X_umap"])


if __name__ == "__main__":
    unittest.main()
