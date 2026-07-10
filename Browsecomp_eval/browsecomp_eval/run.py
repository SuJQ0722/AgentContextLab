from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .dataset import expand_repeats, load_dataset, safe_id
from .hermes_client import HermesClient, HermesConfig
from .runner import BrowseCompRunner, RunnerConfig
from .whitelist import (
    DEFAULT_TOOL_WHITELIST,
    normalize_skill_whitelist,
    parse_csv,
    resolve_toolsets,
    validate_tool_whitelist,
)


def _env_float(name: str):
    val = os.getenv(name)
    if val is None or not val.strip():
        return None
    try:
        return float(val)
    except ValueError:
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone parallel Hermes runner for Browse Comp evals")
    parser.add_argument("--dataset", required=True, help="Dataset name used for data/output organization")
    parser.add_argument("--data-path", help="JSONL or JSON data file. Defaults to data/{dataset}/questions.jsonl")
    parser.add_argument("--model", required=True, help="Hermes model name")
    parser.add_argument("--provider", default=os.getenv("HERMES_PROVIDER", "custom"), help="Hermes provider")
    parser.add_argument("--base-url", default=os.getenv("HERMES_BASE_URL", ""), help="Model API base URL")
    parser.add_argument("--api-key-env", default="HERMES_API_KEY", help="Environment variable containing the API key")
    parser.add_argument("--api-key", default=None, help="API key override. Prefer --api-key-env for scripts.")
    parser.add_argument("--save-name", help="Output run name. Defaults to a filesystem-safe model name")
    parser.add_argument("--repeats", type=int, default=1, help="How many times to run each question")
    parser.add_argument("--num-workers", type=int, default=4, help="Parallel Hermes subprocesses")
    parser.add_argument("--max-rounds", type=int, default=60, help="Hermes max turns per run")
    parser.add_argument("--max-retries", type=int, default=3, help="Retries per run when Hermes fails")
    parser.add_argument("--timeout-seconds", type=int, help="Per-attempt subprocess timeout. Defaults to max_rounds * 120")
    parser.add_argument("--context-length", type=int, help="Explicit model context length to write into each Hermes profile")
    parser.add_argument("--tool-whitelist", default=DEFAULT_TOOL_WHITELIST, help="Comma-separated Hermes toolsets to enable")
    parser.add_argument("--skill-whitelist", default="", help="Comma-separated Hermes skills to preload")
    parser.add_argument("--output-root", default="output/preds", help="Root output directory")
    parser.add_argument("--data-root", default="data", help="Root data directory")
    parser.add_argument("--hermes-bin", default=os.getenv("HERMES_BIN", "hermes"), help="Hermes executable")
    parser.add_argument("--skip-statuses", default="success,policy_violation", help="Existing statuses to skip on resume")
    parser.add_argument("--force", action="store_true", help="Rerun even if a result file already exists")
    parser.add_argument("--dry-run", action="store_true", help="Print planned run count and exit")
    parser.add_argument("--no-quiet", action="store_true", help="Do not pass --quiet to Hermes chat")
    parser.add_argument("--accept-hooks", action="store_true", help="Pass --accept-hooks to Hermes")
    parser.add_argument("--ignore-rules", action="store_true", help="Pass --ignore-rules to Hermes")
    parser.add_argument("--reasoning-effort", default=os.getenv("REASONING_EFFORT", ""), help="Hermes reasoning effort: none|minimal|low|medium|high|xhigh")
    parser.add_argument("--max-tool-response", type=int, default=None, help="Max tool response size in bytes (hermes tool_output.max_bytes)")
    parser.add_argument("--api-mode", default=os.getenv("API_MODE", ""), help="Hermes API mode: chat_completions|codex_responses|anthropic_messages")
    parser.add_argument("--compression-threshold", type=float, default=_env_float("COMPRESS_THRESHOLD"), help="Compression trigger threshold: absolute token count (>=1, e.g. 32768) or fraction of context (0.0-1.0)")
    parser.add_argument("--context-engine", default=os.getenv("CONTEXT_ENGINE", ""), help="Hermes context engine: compressor|visual|summarize|sliding_window|discard_all")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = Path.cwd()

    data_path = Path(args.data_path) if args.data_path else Path(args.data_root) / args.dataset / "questions.jsonl"
    if not data_path.is_absolute():
        data_path = project_root / data_path

    save_name = args.save_name or safe_id(args.model)
    output_base = Path(args.output_root) / save_name / args.dataset
    if not output_base.is_absolute():
        output_base = project_root / output_base

    toolsets = validate_tool_whitelist(parse_csv(args.tool_whitelist))
    skills = normalize_skill_whitelist(parse_csv(args.skill_whitelist))
    allowed_tools = resolve_toolsets(toolsets)
    skip_statuses = set(parse_csv(args.skip_statuses))

    api_key = args.api_key or os.getenv(args.api_key_env, "")
    if not api_key:
        print(f"missing API key: set {args.api_key_env} or pass --api-key", file=sys.stderr)
        return 2

    items = load_dataset(data_path)
    runs = expand_repeats(items, args.repeats)

    print("Browse Comp Eval")
    print(f"  data: {data_path}")
    print(f"  dataset: {args.dataset}")
    print(f"  model: {args.model}")
    print(f"  provider: {args.provider}")
    print(f"  save_name: {save_name}")
    print(f"  questions: {len(items)}")
    print(f"  repeats: {args.repeats}")
    print(f"  runs: {len(runs)}")
    print(f"  workers: {args.num_workers}")
    print(f"  retries: {args.max_retries}")
    print(f"  max_rounds: {args.max_rounds}")
    print(f"  timeout_seconds: {args.timeout_seconds or args.max_rounds * 120}")
    print(f"  context_length: {args.context_length if args.context_length else '(auto)'}")
    print(f"  reasoning_effort: {args.reasoning_effort or '(off)'}")
    print(f"  api_mode: {args.api_mode or '(auto)'}")
    print(f"  max_tool_response: {args.max_tool_response if args.max_tool_response else '(default)'}")
    print(f"  compression_threshold: {args.compression_threshold if args.compression_threshold is not None else '(default)'}")
    print(f"  context_engine: {args.context_engine or '(default)'}")
    print(f"  hermes_quiet: {not args.no_quiet}")
    print(f"  tool_whitelist: {','.join(toolsets) if toolsets else '(none)'}")
    print(f"  skill_whitelist: {','.join(skills) if skills else '(none)'}")
    print(f"  output: {output_base}")

    if args.dry_run:
        return 0

    timeout_seconds = args.timeout_seconds or args.max_rounds * 120
    client = HermesClient(
        HermesConfig(
            hermes_bin=args.hermes_bin,
            api_key=api_key,
            base_url=args.base_url,
            model=args.model,
            provider=args.provider,
            save_name=save_name,
            dataset=args.dataset,
            max_rounds=args.max_rounds,
            timeout_seconds=timeout_seconds,
            toolsets=toolsets,
            skills=skills,
            context_length=args.context_length,
            quiet=not args.no_quiet,
            accept_hooks=args.accept_hooks,
            ignore_rules=args.ignore_rules,
            reasoning_effort=args.reasoning_effort or None,
            max_tool_response_tokens=args.max_tool_response,
            api_mode=args.api_mode or None,
            compression_threshold=args.compression_threshold,
            context_engine=args.context_engine or None,
        )
    )
    runner = BrowseCompRunner(
        client=client,
        config=RunnerConfig(
            output_dir=output_base / "history",
            workspace_dir=output_base / "workspace",
            summary_path=output_base / "summary.jsonl",
            num_workers=args.num_workers,
            max_retries=args.max_retries,
            force=args.force,
            skip_statuses=skip_statuses,
            allowed_tools=allowed_tools,
            conv_dir=output_base / "conv",
            compress_trace_dir=output_base / "compress_trace",
        ),
    )
    stats = runner.run(runs)
    print("done")
    print("  " + " ".join(f"{key}={value}" for key, value in sorted(stats.items())))
    bad = stats.get("failed", 0) + stats.get("policy_violation", 0)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
