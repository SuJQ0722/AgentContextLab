#!/usr/bin/env python3
"""Plot token consumption and turn distribution across eval runs.

Usage:
    python scripts/plot_distributions.py --metrics-dirs DIR1 DIR2 ...
    python scripts/plot_distributions.py --metrics-files FILE1 FILE2 ...

Each directory should be a pred_root (e.g. output/preds/model_name/dataset)
containing judge_metrics.json.  Alternatively, pass metrics JSON files directly.

Generates two plots:
  - tokens_distribution.png  — per-question total_tokens box/violin plot
  - turns_distribution.png   — per-question turns (rounds) box/violin plot

Both plots overlay all specified runs for comparison.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np


def load_metrics(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_label(path: Path) -> str:
    """Derive a human-readable label from the metrics file path."""
    # Expect: .../output/preds/<save_name>/<dataset>/judge_metrics.json
    parts = path.resolve().parts
    try:
        idx = parts.index("preds")
        return f"{parts[idx+1]}/{parts[idx+2]}"
    except (ValueError, IndexError):
        return path.parent.name


def plot_box(ax: Any, data: list[list[int]], labels: list[str], title: str, ylabel: str) -> None:
    """Draw a combined box + strip plot."""
    positions = list(range(1, len(data) + 1))
    bp = ax.boxplot(data, positions=positions, widths=0.5, patch_artist=True,
                    showfliers=False, medianprops=dict(color="black", linewidth=1.5))
    colors = plt.cm.Set2(np.linspace(0, 1, len(data)))
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)

    # Strip (jittered scatter)
    for i, (vals, color) in enumerate(zip(data, colors)):
        jitter = np.random.default_rng(42).uniform(-0.15, 0.15, size=len(vals))
        ax.scatter(np.full(len(vals), i + 1) + jitter, vals,
                   alpha=0.4, s=12, color=color, edgecolors="none", zorder=3)

    ax.set_xticks(positions)
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.3)
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plot token/turn distributions across eval runs")
    parser.add_argument("--metrics-dirs", nargs="+", help="Pred root directories containing judge_metrics.json")
    parser.add_argument("--metrics-files", nargs="+", help="Direct paths to judge_metrics.json files")
    parser.add_argument("--output-dir", default=".", help="Where to save the plots")
    parser.add_argument("--format", default="png", choices=["png", "pdf", "svg"], help="Output image format")
    args = parser.parse_args(argv)

    metrics_paths: list[Path] = []
    if args.metrics_files:
        metrics_paths = [Path(f) for f in args.metrics_files]
    elif args.metrics_dirs:
        for d in args.metrics_dirs:
            p = Path(d) / "judge_metrics.json"
            if p.exists():
                metrics_paths.append(p)
            else:
                print(f"WARNING: {p} not found, skipping", file=sys.stderr)
    else:
        # Auto-discover all judge_metrics.json under output/preds
        root = Path("output/preds")
        if root.exists():
            metrics_paths = sorted(root.rglob("judge_metrics.json"))
        if not metrics_paths:
            print("No metrics files found. Use --metrics-dirs or --metrics-files.", file=sys.stderr)
            return 1

    if not metrics_paths:
        print("No valid metrics files to plot.", file=sys.stderr)
        return 1

    all_tokens: list[list[int]] = []
    all_turns: list[list[int]] = []
    labels: list[str] = []

    for mp in metrics_paths:
        metrics = load_metrics(mp)
        pqs = metrics.get("per_question_stats", [])
        if not pqs:
            # Fallback: use distribution values
            td = metrics.get("turns_distribution", {})
            tkd = metrics.get("tokens_distribution", {})
            turns_vals = td.get("values", [])
            tokens_vals = tkd.get("values", [])
        else:
            turns_vals = [q["turns"] for q in pqs]
            tokens_vals = [q["total_tokens"] for q in pqs]

        if not turns_vals and not tokens_vals:
            print(f"WARNING: no per-question data in {mp}, skipping", file=sys.stderr)
            continue

        all_turns.append(turns_vals)
        all_tokens.append(tokens_vals)
        labels.append(extract_label(mp))

    if not labels:
        print("No data to plot.", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fmt = args.format

    # --- Tokens distribution ---
    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 2), 5))
    plot_box(ax, all_tokens, labels, "Token Consumption Distribution", "Total Tokens")
    fig.tight_layout()
    tokens_path = output_dir / f"tokens_distribution.{fmt}"
    fig.savefig(tokens_path, dpi=150)
    plt.close(fig)
    print(f"Saved: {tokens_path}")

    # --- Turns distribution ---
    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 2), 5))
    plot_box(ax, all_turns, labels, "Turns (Rounds) Distribution", "Turns")
    fig.tight_layout()
    turns_path = output_dir / f"turns_distribution.{fmt}"
    fig.savefig(turns_path, dpi=150)
    plt.close(fig)
    print(f"Saved: {turns_path}")

    # Print summary table
    print("\n--- Summary ---")
    print(f"{'Run':<40} {'Turns(med/mean)':<20} {'Tokens(med/mean)':<25}")
    for label, turns, tokens in zip(labels, all_turns, all_tokens):
        t_med = int(np.median(turns)) if turns else 0
        t_mean = round(np.mean(turns), 1) if turns else 0
        tk_med = int(np.median(tokens)) if tokens else 0
        tk_mean = round(np.mean(tokens), 0) if tokens else 0
        print(f"{label:<40} {t_med}/{t_mean:<18} {tk_med}/{tk_mean:<23}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
