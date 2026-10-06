"""Shared presentation-only geometry for candidate and publication embeddings.

The exported canvas is always 8 x 8 inches. Single panels remain 4 x 4 inches;
comparisons use smaller square panels in a grid. Never change embedding values,
colours, category order or analysis parameters here.
"""
import math
import textwrap

import matplotlib as mpl

CANVAS_INCHES = 8.0
EMBEDDING_DPI = 300
PANEL_INCHES = 4.0
PANEL_PAD = 0.04


def panel_positions(npanels):
    """The sole layout rule, used both at construction and at export."""
    if not isinstance(npanels, int) or npanels < 1:
        raise ValueError("npanels must be a positive integer")
    columns = 1 if npanels <= 2 else math.ceil(math.sqrt(npanels))
    rows = math.ceil(npanels / columns)
    positions = []
    for index in range(npanels):
        row, column = divmod(index, columns)
        tile_width, tile_height = 1.0 / columns, 1.0 / rows
        side = min(PANEL_INCHES / CANVAS_INCHES, tile_width * 0.53, tile_height * 0.76)
        left = column * tile_width + tile_width * 0.08
        bottom = 1 - (row + 1) * tile_height + (tile_height - side) / 2
        positions.append((left, bottom, side, side))
    return positions


def embedding_figure(npanels=1):
    """Create square axes on the final square canvas, before any data are plotted."""
    import matplotlib.pyplot as plt
    figure = plt.figure(figsize=(CANVAS_INCHES, CANVAS_INCHES))
    axes = [figure.add_axes(position) for position in panel_positions(npanels)]
    figure._scautopilot_embedding = True
    return figure, axes


def square_panels(axes, pad=PANEL_PAD):
    """Give comparable views a shared square window, without changing data."""
    x0 = min(ax.get_xlim()[0] for ax in axes)
    x1 = max(ax.get_xlim()[1] for ax in axes)
    y0 = min(ax.get_ylim()[0] for ax in axes)
    y1 = max(ax.get_ylim()[1] for ax in axes)
    half = max(x1 - x0, y1 - y0) / 2 * (1 + pad) or 0.5
    for ax in axes:
        ax.set_xlim((x0 + x1) / 2 - half, (x0 + x1) / 2 + half)
        ax.set_ylim((y0 + y1) / 2 - half, (y0 + y1) / 2 + half)
        ax.set_aspect("equal", adjustable="box")
    return axes


def panel_mappable(ax):
    return ax.collections[-1]


def side_colorbar(figure, ax, mappable, label):
    """One external vertical bar; a dedicated cax never shrinks the panel."""
    position = ax.get_position()
    cax = figure.add_axes([position.x1 + 0.025, position.y0, 0.018, position.height])
    bar = figure.colorbar(mappable, cax=cax, orientation="vertical")
    bar.set_label(textwrap.fill(label, width=24), fontsize=8)
    bar.ax.tick_params(labelsize=8)
    return bar


def standardize_embedding(figure):
    """Fit Scanpy or manually drawn embeddings and their keys into a square canvas."""
    bars = [ax._colorbar for ax in figure.axes if getattr(ax, "_colorbar", None) is not None]
    panels = [ax for ax in figure.axes if getattr(ax, "_colorbar", None) is None]
    if not panels:
        raise ValueError("An embedding figure must contain a plotting panel")
    # Disable layout engines: tight/constrained layout would steal space from panels.
    if hasattr(figure, "set_layout_engine"):
        figure.set_layout_engine(None)
    else:
        figure.set_tight_layout(False)
        figure.set_constrained_layout(False)
    figure.set_size_inches(CANVAS_INCHES, CANVAS_INCHES, forward=True)
    columns = 1 if len(panels) <= 2 else math.ceil(math.sqrt(len(panels)))
    rows = math.ceil(len(panels) / columns)
    for index, (ax, position) in enumerate(zip(panels, panel_positions(len(panels)))):
        row, column = divmod(index, columns)
        tile_width, tile_height = 1.0 / columns, 1.0 / rows
        ax.set_position(position)
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        half = max(abs(x1 - x0), abs(y1 - y0)) / 2 or 0.5
        # Equal windows prevent aspect='equal' from shrinking the square box.
        ax.set_xlim((x0 + x1) / 2 - half, (x0 + x1) / 2 + half)
        ax.set_ylim((y0 + y1) / 2 - half, (y0 + y1) / 2 + half)
        ax.set_aspect("equal", adjustable="box")
        ax.set_title(textwrap.fill(ax.get_title(), width=42 if columns == 1 else 24), fontsize=10)
        ax.tick_params(labelsize=8)
        legend = ax.get_legend()
        if legend is not None:
            handles = getattr(legend, "legend_handles", None)
            if handles is None:  # Matplotlib < 3.7
                handles = legend.legendHandles
            labels = [textwrap.fill(t.get_text(), width=26 if columns == 1 else 14)
                      for t in legend.get_texts()]
            title = legend.get_title().get_text()
            legend.remove()
            legend = ax.legend(handles, labels, title=title, ncol=1, frameon=False,
                               loc="center left", bbox_to_anchor=(1.04, 0.5),
                               borderaxespad=0, fontsize=8, title_fontsize=8,
                               handletextpad=0.4, labelspacing=0.35)
            # Fit unusually numerous categories without silently making a second column.
            for font_size in (8, 7, 6, 5, 4):
                for text in legend.get_texts():
                    text.set_fontsize(font_size)
                figure.canvas.draw()
                box = legend.get_window_extent(figure.canvas.get_renderer())
                limit = figure.bbox
                if (box.height <= tile_height * 0.90 * limit.height
                        and box.x1 <= (column + 1) * tile_width * limit.width - 8):
                    break
            else:
                raise ValueError("Single-column embedding legend cannot fit; shorten display labels "
                                 "or split this comparison into single-panel figures")
    # Preserve each mappable, its limits and label; only relocate/orient its colour bar.
    for bar in bars:
        ax = bar.mappable.axes
        if ax not in panels:
            raise ValueError("Embedding colour bar has no matching panel")
        position = ax.get_position()
        label = bar.ax.get_ylabel() or bar.ax.get_xlabel()
        mappable = bar.mappable
        bar.remove()
        # Colorbar.remove() may restore a previous axes box; pin it again.
        ax.set_position(position)
        side_colorbar(figure, ax, mappable, label)
    figure._scautopilot_embedding = True
    return figure


def save_embedding(figure, path):
    """Export PNG/PDF/SVG without a tight crop that would undo the square canvas."""
    standardize_embedding(figure)
    with mpl.rc_context({"savefig.bbox": None}):
        figure.savefig(path, dpi=EMBEDDING_DPI, bbox_inches=None, facecolor="white")
    return path
