from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from .dataset import expand_repeats, load_dataset, safe_id
from .hermes_client import (
    HermesClient,
    HermesConfig,
    configured_web_backend_hosts,
    source_hermes_home,
)
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


def _resolve_provider(provider: str, model: str) -> str:
    raw = (provider or "").strip()
    if raw:
        return raw
    if "gemini" in (model or "").lower():
        return "gemini"
    return "custom"


def _read_global_config() -> dict[str, Any]:
    path = source_hermes_home() / "config.yaml"
    try:
        import yaml
    except ImportError:
        return {"_path": str(path), "_error": "missing PyYAML"}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception as exc:
        return {"_path": str(path), "_error": str(exc)}
    if not isinstance(data, dict):
        data = {}
    data["_path"] = str(path)
    return data


def print_web_backend_diagnostics() -> None:
    cfg = _read_global_config()
    web = cfg.get("web") if isinstance(cfg.get("web"), dict) else {}
    plugins = cfg.get("plugins") if isinstance(cfg.get("plugins"), dict) else {}
    enabled = plugins.get("enabled", []) if isinstance(plugins, dict) else []
    if isinstance(enabled, str):
        enabled = [enabled]
    enabled = [str(item) for item in enabled] if isinstance(enabled, list) else []
    local_web = web.get("local_web", {}) if isinstance(web, dict) else {}

    print("  web_config:")
    print(f"    config_path: {cfg.get('_path', '')}")
    print(f"    HERMES_HOME: {os.getenv('HERMES_HOME', '')}")
    if cfg.get("_error"):
        print(f"    config_error: {cfg.get('_error')}")
        return
    print(f"    backend: {web.get('backend', '')}")
    print(f"    search_backend: {web.get('search_backend', '')}")
    print(f"    extract_backend: {web.get('extract_backend', '')}")
    print(f"    plugins.enabled: {','.join(enabled) if enabled else '(none)'}")
    print(f"    local-web plugin enabled: {'yes' if 'local-web' in enabled else 'no'}")
    print(f"    web.local_web configured: {'yes' if bool(local_web) else 'no'}")
    if isinstance(local_web, dict):
        search = local_web.get("search", {}) if isinstance(local_web.get("search"), dict) else {}
        fetch = local_web.get("fetch", {}) if isinstance(local_web.get("fetch"), dict) else {}
        fetch_server = fetch.get("fetch_server", {}) if isinstance(fetch.get("fetch_server"), dict) else {}
        if search.get("url"):
            print(f"    local_web.search.url: {search.get('url')}")
        if fetch_server.get("base_url"):
            print(f"    local_web.fetch.base_url: {fetch_server.get('base_url')}")
            print(f"    local_web.fetch.extract_mode: {fetch_server.get('extract_mode', '')}")
    web_hosts = configured_web_backend_hosts()
    if web_hosts:
        no_proxy = os.getenv("NO_PROXY") or os.getenv("no_proxy") or ""
        covered = [host for host in web_hosts if _no_proxy_covers(no_proxy, host)]
        missing = [host for host in web_hosts if host not in covered]
        print(f"    web backend NO_PROXY covered: {','.join(covered) if covered else '(none)'}")
        if missing and (os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("http_proxy") or os.getenv("https_proxy")):
            print(f"    warning: web backend hosts missing from NO_PROXY: {','.join(missing)}")
    if str(web.get("search_backend", "")).startswith("mcp-tools") or str(web.get("extract_backend", "")).startswith("mcp-tools"):
        print("    note: mcp-tools-* is not provided by the bundled local-web override plugin.")
    if "local-web" not in enabled:
        print("    note: enable plugins.enabled=local-web to use the bundled local web_search/web_extract overrides.")


def resolve_output_base(output_root: str | Path, save_name: str, dataset: str, project_root: Path) -> Path:
    """Resolve prediction output layout.

    Plain save names keep the historical layout:
        output/preds/{save_name}/{dataset}

    Save names containing a path separator are treated as an explicit layout,
    so scripts can group by benchmark first:
        output/preds/{bench}/{model}-{strategy}
    """
    save_path = Path(save_name)
    if len(save_path.parts) > 1:
        output_base = Path(output_root) / save_path
    else:
        output_base = Path(output_root) / save_name / dataset
    if not output_base.is_absolute():
        output_base = project_root / output_base
    return output_base


def _no_proxy_covers(no_proxy: str, host: str) -> bool:
    entries = [part.strip() for part in no_proxy.split(",") if part.strip()]
    return "*" in entries or host in entries


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
    parser.add_argument("--skip-statuses", default="success", help="Existing statuses to skip on resume")
    parser.add_argument("--force", action="store_true", help="Rerun even if a result file already exists")
    parser.add_argument("--dry-run", action="store_true", help="Print planned run count and exit")
    parser.add_argument("--no-quiet", action="store_true", help="Do not pass --quiet to Hermes chat")
    parser.add_argument("--accept-hooks", action="store_true", help="Pass --accept-hooks to Hermes")
    parser.add_argument("--ignore-rules", action="store_true", help="Pass --ignore-rules to Hermes")
    parser.add_argument("--reasoning-effort", default=os.getenv("REASONING_EFFORT", ""), help="Hermes reasoning effort: none|minimal|low|medium|high|xhigh")
    parser.add_argument("--max-tool-response", type=int, default=None, help="Max tool response size in bytes (hermes tool_output.max_bytes)")
    parser.add_argument("--api-mode", default=os.getenv("API_MODE", ""), help="Hermes API mode: chat_completions|codex_responses|anthropic_messages")
    parser.add_argument("--compression-threshold", type=float, default=_env_float("COMPRESS_THRESHOLD"), help="Compression trigger threshold: absolute token count (>=1, e.g. 65536) or fraction of context (0.0-1.0)")
    parser.add_argument("--context-engine", default=os.getenv("CONTEXT_ENGINE") or os.getenv("CM") or os.getenv("COMPRESS_STRATEGY", ""), help="Hermes context engine: compressor|visual|summarize|sliding_window|discard (discard_all is an alias)")
    parser.add_argument("--save-trajectories", action=argparse.BooleanOptionalAction,
                        default=os.getenv("SAVE_TRAJECTORIES", "").lower() in {"1", "true", "yes", "on"},
                        help="Export per-attempt JSONL histories, including pre-compression sessions")
    parser.add_argument("--trajectory-dir", type=Path, default=os.getenv("TRAJECTORY_DIR") or None,
                        help="Trajectory export directory (default: output run directory / trajectories)")
    parser.add_argument("--local-workspace-root", default="/root", help="Local root for isolated scratch workspace outside /mnt. Set to empty string to disable.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.provider = _resolve_provider(args.provider, args.model)
    project_root = Path.cwd()

    data_path = Path(args.data_path) if args.data_path else Path(args.data_root) / args.dataset / "questions.jsonl"
    if not data_path.is_absolute():
        data_path = project_root / data_path

    save_name = args.save_name or safe_id(args.model)
    output_base = resolve_output_base(args.output_root, save_name, args.dataset, project_root)

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
    print_web_backend_diagnostics()

    local_ws_root = args.local_workspace_root.strip() if args.local_workspace_root else ""
    if local_ws_root:
        local_workspace = resolve_output_base(
            Path(local_ws_root) / "Browsecomp_eval" / "output" / "preds",
            save_name,
            args.dataset,
            Path("/"),
        ) / "workspace"
        remote_workspace = output_base / "workspace"
    else:
        local_workspace = output_base / "workspace"
        remote_workspace = None

    print(f"  workspace: {local_workspace}")
    if remote_workspace:
        print(f"  workspace_sync_to: {remote_workspace}")
    print(f"  context_image: {output_base / 'context_image'}")

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
            context_image_dir=output_base / "context_image",
        )
    )
    runner = BrowseCompRunner(
        client=client,
        config=RunnerConfig(
            output_dir=output_base / "history",
            workspace_dir=local_workspace,
            summary_path=output_base / "summary.jsonl",
            num_workers=args.num_workers,
            max_retries=args.max_retries,
            force=args.force,
            skip_statuses=skip_statuses,
            allowed_tools=allowed_tools,
            conv_dir=output_base / "conv",
            log_dir=output_base / "logs",
            trajectory_dir=(args.trajectory_dir or output_base / "trajectories").resolve()
            if args.save_trajectories else None,
        ),
    )
    stats = runner.run(runs)
    if remote_workspace and local_workspace.exists():
        print(f"syncing workspace: {local_workspace} -> {remote_workspace}")
        remote_workspace.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(local_workspace), str(remote_workspace), dirs_exist_ok=True)

    print("done")
    print("  " + " ".join(f"{key}={value}" for key, value in sorted(stats.items())))
    bad = stats.get("failed", 0) + stats.get("policy_violation", 0)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
