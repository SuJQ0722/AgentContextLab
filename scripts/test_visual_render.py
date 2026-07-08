"""Test visual rendering with 8 experiment configurations on a real trajectory.

Produces 8 output folders under output/visual_render_test/:
  1. layout_1d_scale075       — 1d layout, history_scale=0.75
  2. layout_plain_scale075    — plain layout, history_scale=0.75
  3. layout_highlight_scale075 — highlight layout, history_scale=0.75
  4. highlight_scale0          — highlight, no history image
  5. highlight_scale025        — highlight, 4x downsample
  6. highlight_scale050        — highlight, 2x downsample
  7. highlight_scale0125       — highlight, 8x downsample
  8. highlight_scale100        — highlight, original (no downsample)
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.context_engine.visual.render import render_visual_compression

TRAJECTORY = "/mnt/afs_agents/sujiaqi/workspace/projects/Browsecomp_eval/output/preds/deepseep-ve-pro-test-rl/browsecomp_subset_final/history/iter1/q_001.json"
OUTPUT_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "visual_render_test")

CONFIGS = [
    # Table 3: Layout ablation (fixed scale=0.75)
    {"name": "plain_no_header",     "layout": "plain_no_header",   "history_scale": 0.75},
    {"name": "plain",               "layout": "plain",             "history_scale": 0.75},
    {"name": "highlight",           "layout": "highlight",         "history_scale": 0.75},
    {"name": "highlight_no_wrap",   "layout": "highlight_no_wrap", "history_scale": 0.75},
    # Table 2: History downsample ablation (fixed layout=highlight)
    {"name": "scale_0_no_history",  "layout": "highlight", "history_scale": 0.0},
    {"name": "scale_0125_8x",       "layout": "highlight", "history_scale": 0.125},
    {"name": "scale_025_4x",        "layout": "highlight", "history_scale": 0.25},
    {"name": "scale_050_2x",        "layout": "highlight", "history_scale": 0.5},
    {"name": "scale_100_original",  "layout": "highlight", "history_scale": 1.0},
]


def main():
    with open(TRAJECTORY) as f:
        data = json.load(f)
    messages = data["history"]
    print(f"Loaded {len(messages)} messages from trajectory")

    os.makedirs(OUTPUT_BASE, exist_ok=True)

    for cfg in CONFIGS:
        name = cfg["name"]
        save_dir = os.path.join(OUTPUT_BASE, name)
        os.makedirs(save_dir, exist_ok=True)

        print(f"\n{'='*60}")
        print(f"Rendering: {name} (layout={cfg['layout']}, history_scale={cfg['history_scale']})")
        print(f"Output dir: {save_dir}")

        result = render_visual_compression(
            messages,
            head_end=1,
            image_width=1024,
            font_size=8,
            max_image_height=4096,
            dpi=72,
            layout=cfg["layout"],
            history_scale=cfg["history_scale"],
            keep_rounds=1,
            recent_rounds=5,
            save_dir=save_dir,
            compact_count=0,
        )

        n_images = 0
        for m in result:
            content = m.get("content")
            if isinstance(content, list):
                n_images += sum(1 for p in content if isinstance(p, dict) and p.get("type") == "image_url")

        print(f"  Result: {len(result)} messages, {n_images} image(s)")
        pngs = [f for f in os.listdir(save_dir) if f.endswith(".png")]
        pdfs = [f for f in os.listdir(save_dir) if f.endswith(".pdf")]
        print(f"  Files: {len(pngs)} PNG, {len(pdfs)} PDF")
        for f in sorted(pngs + pdfs):
            fpath = os.path.join(save_dir, f)
            size_kb = os.path.getsize(fpath) / 1024
            print(f"    {f} ({size_kb:.1f} KB)")

    print(f"\n{'='*60}")
    print(f"All outputs saved to: {OUTPUT_BASE}")


if __name__ == "__main__":
    main()
