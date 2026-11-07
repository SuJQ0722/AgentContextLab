#!/usr/bin/env python3
"""Redraw cumulative correct-rate curves with a publication-oriented style."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd


DEFAULT_INPUT = Path(
    "output/preds/bc/gemini35_flash_vis/"
    "bc_vis_basis_cumulative_correct_rate_by_turn.csv"
)

LABELS = {
    "vis": "Vis",
    "discard": "Discard",
    "summarize": "Summarize",
    "sw": "SW",
    "no_cc": "No CC",
}

# Okabe-Ito colorblind-safe palette, with the focal method kept in blue.
COLORS = {
    "vis": "#0072B2",
    "discard": "#D55E00",
    "summarize": "#E69F00",
    "sw": "#009E73",
    "no_cc": "#CC79A7",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="CSV with columns: strategy, turn, cumulative_correct_rate.",
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=None,
        help="Output prefix without extension. Defaults to INPUT stem + '_journal'.",
    )
    return parser.parse_args()


def apply_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Helvetica", "Liberation Sans", "DejaVu Sans"],
            "font.size": 7.6,
            "axes.labelsize": 8.0,
            "axes.linewidth": 0.7,
            "xtick.labelsize": 7.0,
            "ytick.labelsize": 7.0,
            "xtick.major.size": 3,
            "ytick.major.size": 3,
            "xtick.major.width": 0.7,
            "ytick.major.width": 0.7,
            "legend.fontsize": 7.0,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.03,
        }
    )


def redraw(input_path: Path, output_prefix: Path) -> None:
    df = pd.read_csv(input_path)
    required = {"strategy", "turn", "cumulative_correct_rate"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in {input_path}: {sorted(missing)}")

    apply_style()

    final_rate = (
        df.sort_values("turn")
        .groupby("strategy", sort=False)
        .tail(1)
        .set_index("strategy")["cumulative_correct_rate"]
    )
    order = final_rate.sort_values(ascending=False).index.tolist()

    fig, ax = plt.subplots(figsize=(4.15, 2.55))

    for strategy in order:
        sub = df[df["strategy"] == strategy].sort_values("turn")
        is_focus = strategy == "vis"
        ax.plot(
            sub["turn"],
            sub["cumulative_correct_rate"],
            color=COLORS.get(strategy, "#4D4D4D"),
            linewidth=2.1 if is_focus else 1.35,
            alpha=0.98 if is_focus else 0.72,
            solid_capstyle="round",
            zorder=3 if is_focus else 2,
        )

        x_end = float(sub["turn"].iloc[-1])
        y_end = float(sub["cumulative_correct_rate"].iloc[-1])
        ax.scatter(
            [x_end],
            [y_end],
            s=18 if is_focus else 12,
            color=COLORS.get(strategy, "#4D4D4D"),
            edgecolor="white",
            linewidth=0.45,
            zorder=4,
        )

    # Direct labels read better than an in-plot legend for dense journal figures.
    label_offsets = {
        "vis": 0.000,
        "discard": 0.010,
        "summarize": -0.006,
        "sw": 0.004,
        "no_cc": -0.007,
    }
    for strategy in order:
        y = float(final_rate.loc[strategy]) + label_offsets.get(strategy, 0.0)
        color = COLORS.get(strategy, "#4D4D4D")
        ax.text(
            202.0,
            y,
            f"{LABELS.get(strategy, strategy)}  {final_rate.loc[strategy]:.1%}",
            color=color,
            fontsize=6.9,
            fontweight="bold" if strategy == "vis" else "normal",
            va="center",
            ha="left",
        )

    ax.set_xlabel("API call / turn budget")
    ax.set_ylabel("Cumulative correct rate")
    ax.set_xlim(1, 225)
    ax.set_ylim(0, 0.75)
    ax.xaxis.set_major_locator(mticker.FixedLocator([1, 50, 100, 150, 200]))
    ax.yaxis.set_major_locator(mticker.MultipleLocator(0.1))
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1, decimals=0))

    ax.grid(axis="y", color="#D9D9D9", linewidth=0.45, alpha=0.8)
    ax.grid(axis="x", visible=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#333333")
    ax.spines["bottom"].set_color("#333333")
    ax.tick_params(colors="#333333")

    # Keep the panel title out of the figure; captions usually handle it better.
    fig.savefig(output_prefix.with_suffix(".pdf"))
    fig.savefig(output_prefix.with_suffix(".png"), dpi=450)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    input_path = args.input.resolve()
    output_prefix = (
        args.output_prefix.resolve()
        if args.output_prefix
        else input_path.with_name(f"{input_path.stem}_journal")
    )
    redraw(input_path, output_prefix)
    print(f"Wrote {output_prefix.with_suffix('.pdf')}")
    print(f"Wrote {output_prefix.with_suffix('.png')}")


if __name__ == "__main__":
    main()
