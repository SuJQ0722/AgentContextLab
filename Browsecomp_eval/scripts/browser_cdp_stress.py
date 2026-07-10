#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, build_opener


@dataclass(frozen=True)
class StressConfig:
    hermes_bin: Path
    model: str
    provider: str
    base_url: str
    api_key: str
    save_name: str
    dataset: str
    urls: list[str]
    runs_per_url: int
    concurrency: int
    timeout_seconds: int
    max_turns: int
    output_dir: Path
    session_storage_root: Path
    no_proxy: str
    browser_ports: list[int]
    start_browsers: bool
    browser_bin: str
    browser_startup_timeout: int
    keep_browsers: bool


@dataclass
class BrowserProcess:
    port: int
    cdp_url: str
    user_data_dir: Path
    stdout_log: Path
    stderr_log: Path
    process: subprocess.Popen[str]


def main() -> None:
    args = parse_args()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dataset = args.dataset or f"browser_cdp_stress_{stamp}"
    save_name = args.save_name or args.model.replace("/", "_")
    output_dir = args.output_dir or Path("output/diagnostics") / dataset

    config = StressConfig(
        hermes_bin=args.hermes_bin,
        model=args.model,
        provider=args.provider,
        base_url=args.base_url,
        api_key=args.api_key,
        save_name=save_name,
        dataset=dataset,
        urls=parse_urls(args.urls),
        runs_per_url=args.runs_per_url,
        concurrency=args.concurrency,
        timeout_seconds=args.timeout_seconds,
        max_turns=args.max_turns,
        output_dir=output_dir,
        session_storage_root=args.session_storage_root,
        no_proxy=args.no_proxy,
        browser_ports=parse_ports(args.browser_ports),
        start_browsers=args.start_browsers,
        browser_bin=args.browser_bin,
        browser_startup_timeout=args.browser_startup_timeout,
        keep_browsers=args.keep_browsers,
    )

    config.output_dir.mkdir(parents=True, exist_ok=True)
    (config.output_dir / "runs").mkdir(parents=True, exist_ok=True)

    print("Browser CDP stress")
    specs = run_specs(config)
    print(f"  urls: {config.urls}")
    print(f"  runs_per_url: {config.runs_per_url}")
    print(f"  total_runs: {len(specs)}")
    print(f"  concurrency: {config.concurrency}")
    print(f"  browser_ports: {config.browser_ports}")
    print(f"  start_browsers: {config.start_browsers}")
    print(f"  model: {config.model}")
    print(f"  provider: {config.provider}")
    print(f"  dataset: {config.dataset}")
    print(f"  output_dir: {config.output_dir.resolve()}")
    print(f"  session_root: {config.session_storage_root / config.save_name / config.dataset}")

    browser_processes: list[BrowserProcess] = []
    try:
        if config.start_browsers:
            browser_processes = start_browser_pool(config)
        setup_profiles(config, specs)

        started = time.time()
        details: list[dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=config.concurrency) as executor:
            futures = {executor.submit(run_one, config, spec): spec for spec in specs}
            for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                spec = futures[future]
                try:
                    detail = future.result()
                except Exception as exc:
                    detail = {
                        "run_id": spec["run_id"],
                        "url": spec["url"],
                        "cdp_port": spec["cdp_port"],
                        "cdp_url": spec["cdp_url"],
                        "status": "exception",
                        "error": str(exc),
                        "browser_navigate_calls": 0,
                        "cdp_connection_refused": False,
                        "browser_timeout": False,
                    }
                details.append(detail)
                print(
                    f"[{index}/{len(specs)}] {detail.get('run_id')} port={detail.get('cdp_port')} "
                    f"{detail.get('url')}: {detail.get('status')} "
                    f"browser_calls={detail.get('browser_navigate_calls')} "
                    f"cdp_refused={detail.get('cdp_connection_refused')} "
                    f"timeout={detail.get('browser_timeout')}",
                    flush=True,
                )

        summary = summarize(details, round(time.time() - started, 2), config)
        details_sorted = sorted(details, key=lambda item: item["run_id"])
        write_json(config.output_dir / "details.json", details_sorted)
        write_json(config.output_dir / "summary.json", summary)
        print_summary(summary)
    finally:
        if browser_processes and not config.keep_browsers:
            stop_browser_pool(browser_processes)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run many Hermes browser_navigate calls concurrently and measure CDP errors.")
    parser.add_argument("--urls", default=os.environ.get("URLS", "https://example.com"))
    parser.add_argument("--runs-per-url", type=int, default=int(os.environ.get("RUNS_PER_URL", "50")))
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--timeout-seconds", type=int, default=240)
    parser.add_argument("--max-turns", type=int, default=4)
    parser.add_argument("--model", default=os.environ.get("MODEL", "Qwen3-5-9B"))
    parser.add_argument("--provider", default=os.environ.get("PROVIDER", "custom"))
    parser.add_argument("--base-url", default=os.environ.get("HERMES_BASE_URL", "http://10.120.5.36:8000/v1"))
    parser.add_argument("--api-key", default=os.environ.get("HERMES_API_KEY", "EMPTY"))
    parser.add_argument("--save-name", default=os.environ.get("SAVE_NAME", ""))
    parser.add_argument("--dataset", default=os.environ.get("DATASET", ""))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--hermes-bin", type=Path, default=Path(os.environ.get("HERMES_BIN", "/root/hermes-agent/.venv/bin/hermes")))
    parser.add_argument("--session-storage-root", type=Path, default=Path(os.environ.get("HERMES_SESSION_STORAGE_ROOT", "/root/.hermes/sessions")))
    parser.add_argument(
        "--no-proxy",
        default=os.environ.get("QWEN_NO_PROXY") or os.environ.get("NO_PROXY") or "10.120.5.36,localhost,127.0.0.1,::1",
    )
    parser.add_argument("--browser-ports", default=os.environ.get("BROWSER_PORTS", "9222,9223,9224,9225"))
    parser.add_argument("--browser-bin", default=os.environ.get("BROWSER_BIN") or os.environ.get("AGENT_BROWSER_EXECUTABLE_PATH", ""))
    parser.add_argument("--browser-startup-timeout", type=int, default=int(os.environ.get("BROWSER_STARTUP_TIMEOUT", "30")))
    parser.add_argument("--keep-browsers", action="store_true", default=parse_bool(os.environ.get("KEEP_BROWSERS", ""), False))
    parser.add_argument("--no-start-browsers", dest="start_browsers", action="store_false")
    parser.set_defaults(start_browsers=parse_bool(os.environ.get("START_BROWSERS", ""), True))
    return parser.parse_args()


def setup_profiles(config: StressConfig, specs: list[dict[str, Any]]) -> None:
    if not config.hermes_bin.exists():
        raise SystemExit(f"Hermes executable not found: {config.hermes_bin}")
    print("preparing profiles...")
    for index, spec in enumerate(specs, start=1):
        run_id = spec["run_id"]
        profile = profile_name(config.dataset, run_id)
        run_hermes(config.hermes_bin, ["profile", "create", profile, "--no-alias"], check=False)
        copy_profile_config(profile, config, spec)
        set_profile_config(profile, config, spec)
        if index % 10 == 0 or index == len(specs):
            print(f"  prepared {index}/{len(specs)}", flush=True)


def copy_profile_config(profile: str, config: StressConfig, spec: dict[str, Any]) -> None:
    default_home = Path.home() / ".hermes"
    profile_home = default_home / "profiles" / profile
    profile_home.mkdir(parents=True, exist_ok=True)
    for filename in ("config.yaml", ".env"):
        src = default_home / filename
        if src.exists():
            shutil.copy2(src, profile_home / filename)
    update_profile_env(profile_home / ".env", config, spec)


def set_profile_config(profile: str, config: StressConfig, spec: dict[str, Any]) -> None:
    values = [
        ("model.default", config.model),
        ("model.provider", config.provider),
        ("model.api_key", config.api_key),
        ("model.base_url", config.base_url),
        ("browser.cdp_url", str(spec["cdp_url"])),
        ("terminal.timeout", str(max(120, config.timeout_seconds))),
        ("terminal.cwd", "."),
        # Eval isolation: disable cross-session memory and the curator
        # (background skill auto-evolution) so each run stays hermetic.
        ("memory.memory_enabled", "false"),
        ("memory.user_profile_enabled", "false"),
        ("curator.enabled", "false"),
    ]
    for key, value in values:
        run_hermes(config.hermes_bin, ["--profile", profile, "config", "set", key, value])


def run_one(config: StressConfig, spec: dict[str, Any]) -> dict[str, Any]:
    run_id = spec["run_id"]
    url = spec["url"]
    cdp_port = int(spec["cdp_port"])
    cdp_url = str(spec["cdp_url"])
    profile = profile_name(config.dataset, run_id)
    run_dir = config.output_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(config.hermes_bin),
        "--profile",
        profile,
        "chat",
        "--query",
        build_query(url),
        "--yolo",
        "--max-turns",
        str(config.max_turns),
        "--model",
        config.model,
        "--provider",
        config.provider,
        "--source",
        "browser_cdp_stress",
        "--quiet",
        "--toolsets",
        "browser",
        "--ignore-rules",
    ]
    env = build_env(config, spec)

    started = time.time()
    timed_out = False
    stdout = ""
    stderr = ""
    returncode: int | None = None
    error = ""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(run_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=config.timeout_seconds,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        returncode = proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = decode_timeout_output(exc.stdout)
        stderr = decode_timeout_output(exc.stderr)
        error = f"hermes timed out after {config.timeout_seconds}s"
    except Exception as exc:
        error = str(exc)

    (run_dir / "stdout.txt").write_text(stdout, encoding="utf-8", errors="replace")
    (run_dir / "stderr.txt").write_text(stderr, encoding="utf-8", errors="replace")

    session_files = find_session_files(config, run_id)
    analysis = analyze_run_session(session_files)
    log_analysis = analyze_agent_log(profile)

    status = "success"
    if timed_out or error or (returncode not in (0, None)):
        status = "failed"
    if analysis["browser_navigate_calls"] == 0:
        status = "no_browser_call"

    detail = {
        "run_id": run_id,
        "url": url,
        "cdp_port": cdp_port,
        "cdp_url": cdp_url,
        "profile": profile,
        "status": status,
        "returncode": returncode,
        "timed_out": timed_out,
        "error": error,
        "wall_seconds": round(time.time() - started, 2),
        "session_files": [str(path) for path in session_files],
        "stdout_tail": tail(stdout),
        "stderr_tail": tail(stderr),
        **analysis,
        **log_analysis,
    }
    write_json(run_dir / "result.json", detail)
    return detail


def build_env(config: StressConfig, spec: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    run_id = str(spec["run_id"])
    cdp_url = str(spec["cdp_url"])
    env["ANTHROPIC_API_KEY"] = config.api_key
    env["OPENAI_API_KEY"] = config.api_key
    env["ANTHROPIC_BASE_URL"] = config.base_url
    env["OPENAI_BASE_URL"] = config.base_url
    env["BROWSER_CDP_URL"] = cdp_url
    merged_no_proxy = merge_no_proxy(config.no_proxy, ["localhost", "127.0.0.1", "::1", endpoint_host(config.base_url)])
    env["NO_PROXY"] = merged_no_proxy
    env["no_proxy"] = merged_no_proxy
    env["HERMES_SESSION_MODEL"] = config.save_name
    env["HERMES_SESSION_DATASET"] = config.dataset
    env["HERMES_SESSION_STORAGE_ROOT"] = str(config.session_storage_root)
    env["HERMES_SESSION_TASK_TYPE"] = "browser_cdp_stress"
    env["HERMES_SESSION_TASK_ID"] = run_id
    env["HERMES_SESSION_TASK_NAME"] = run_id
    return env


def start_browser_pool(config: StressConfig) -> list[BrowserProcess]:
    browser_bin = find_browser_binary(config.browser_bin)
    if not browser_bin:
        install_hint = (
            "No Chrome/Chromium binary found for CDP stress test. Set BROWSER_BIN=/path/to/chrome, "
            "or install one with: npx playwright install chromium"
        )
        raise SystemExit(install_hint)

    browser_dir = config.output_dir / "browsers"
    browser_dir.mkdir(parents=True, exist_ok=True)

    processes: list[BrowserProcess] = []
    print("starting browser pool...")
    try:
        for port in config.browser_ports:
            if cdp_ready(port, timeout=0.5):
                raise SystemExit(
                    f"CDP port {port} is already reachable. Stop that browser first or choose another BROWSER_PORTS value."
                )
            user_data_dir = browser_dir / f"profile_{port}"
            user_data_dir.mkdir(parents=True, exist_ok=True)
            stdout_log = browser_dir / f"browser_{port}.stdout.log"
            stderr_log = browser_dir / f"browser_{port}.stderr.log"
            stdout_handle = stdout_log.open("w", encoding="utf-8")
            stderr_handle = stderr_log.open("w", encoding="utf-8")
            cmd = [
                browser_bin,
                f"--remote-debugging-port={port}",
                "--remote-debugging-address=127.0.0.1",
                f"--user-data-dir={user_data_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-sandbox",
                "--headless=new",
                "about:blank",
            ]
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    text=True,
                    start_new_session=True,
                )
            finally:
                stdout_handle.close()
                stderr_handle.close()
            try:
                wait_for_cdp(port, config.browser_startup_timeout)
            except Exception:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise
            browser = BrowserProcess(
                port=port,
                cdp_url=f"http://127.0.0.1:{port}",
                user_data_dir=user_data_dir,
                stdout_log=stdout_log,
                stderr_log=stderr_log,
                process=process,
            )
            processes.append(browser)
            print(f"  browser port {port} ready pid={process.pid}", flush=True)
    except BaseException:
        if processes:
            stop_browser_pool(processes)
        raise

    write_json(
        config.output_dir / "browser_pool.json",
        [
            {
                "port": browser.port,
                "cdp_url": browser.cdp_url,
                "pid": browser.process.pid,
                "user_data_dir": str(browser.user_data_dir),
                "stdout_log": str(browser.stdout_log),
                "stderr_log": str(browser.stderr_log),
            }
            for browser in processes
        ],
    )
    return processes


def stop_browser_pool(processes: list[BrowserProcess]) -> None:
    print("stopping browser pool...")
    for browser in processes:
        if browser.process.poll() is None:
            browser.process.terminate()
    deadline = time.time() + 8
    for browser in processes:
        if browser.process.poll() is not None:
            continue
        remaining = max(0.1, deadline - time.time())
        try:
            browser.process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            browser.process.kill()
            browser.process.wait(timeout=5)


def find_browser_binary(explicit: str) -> str:
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    env_path = os.environ.get("AGENT_BROWSER_EXECUTABLE_PATH", "").strip()
    if env_path:
        candidates.append(env_path)
    candidates.extend(["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"])

    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        path = Path(candidate).expanduser()
        if path.is_file():
            return str(path)

    for root in playwright_browser_roots():
        if not root.is_dir():
            continue
        matches = list(root.glob("chromium-*/chrome-linux/chrome"))
        matches.extend(root.glob("chromium_headless_shell-*/chrome-linux/headless_shell"))
        matches.extend(root.glob("chrome-linux*/chrome"))
        for match in matches:
            if match.is_file():
                return str(match)
    return ""


def playwright_browser_roots() -> list[Path]:
    roots: list[Path] = []
    env_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if env_root and env_root != "0":
        roots.append(Path(env_root).expanduser())
    roots.extend(
        [
            Path.home() / ".cache" / "ms-playwright",
            Path("/opt/hermes/.playwright"),
        ]
    )
    return roots


def wait_for_cdp(port: int, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            if cdp_ready(port, timeout=1.0):
                return
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise RuntimeError(f"Browser CDP port {port} did not become ready within {timeout_seconds}s. {last_error}")


def cdp_ready(port: int, timeout: float = 1.0) -> bool:
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
            return bool(payload.get("webSocketDebuggerUrl"))
    except (OSError, URLError, json.JSONDecodeError):
        return False


def build_query(url: str) -> str:
    return (
        "You are testing the browser tool.\n\n"
        "Call browser_navigate exactly once with this URL:\n"
        f"{url}\n\n"
        "After the tool returns, answer exactly one short line:\n"
        "browser_ok if browser_navigate succeeded, otherwise browser_failed.\n"
        "Do not use any other tools."
    )


def run_specs(config: StressConfig) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    if not config.browser_ports:
        raise SystemExit("--browser-ports must contain at least one port")
    for url_index, url in enumerate(config.urls, start=1):
        for run_index in range(1, config.runs_per_url + 1):
            flat_index = len(specs)
            port = config.browser_ports[flat_index % len(config.browser_ports)]
            specs.append(
                {
                    "run_id": f"u{url_index:02d}_r{run_index:05d}",
                    "url": url,
                    "cdp_port": port,
                    "cdp_url": f"http://127.0.0.1:{port}",
                }
            )
    return specs


def parse_urls(raw: str) -> list[str]:
    urls = [part.strip() for part in raw.split(",") if part.strip()]
    if not urls:
        raise SystemExit("--urls must contain at least one URL")
    return urls


def parse_ports(raw: str) -> list[int]:
    ports: list[int] = []
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        try:
            port = int(value)
        except ValueError as exc:
            raise SystemExit(f"Invalid browser port {value!r}") from exc
        if port <= 0 or port > 65535:
            raise SystemExit(f"Invalid browser port {port}; expected 1-65535")
        if port not in ports:
            ports.append(port)
    if not ports:
        raise SystemExit("--browser-ports must contain at least one port")
    return ports


def parse_bool(raw: str, default: bool) -> bool:
    value = raw.strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def find_session_files(config: StressConfig, run_id: str) -> list[Path]:
    root = config.session_storage_root
    if root.name != "sessions":
        root = root / "sessions"
    session_dir = root / config.save_name / config.dataset / run_id / "main"
    if not session_dir.exists():
        return []
    return sorted(session_dir.glob("session_*.json"), key=lambda path: path.stat().st_mtime)


def analyze_run_session(session_files: list[Path]) -> dict[str, Any]:
    browser_calls = 0
    success_calls = 0
    failure_calls = 0
    cdp_refused = 0
    cdp_discovery_failed = 0
    browser_timeout = 0
    other_errors: list[str] = []
    tool_errors: list[dict[str, Any]] = []

    for session_file in session_files:
        try:
            session = json.loads(session_file.read_text(encoding="utf-8"))
        except Exception as exc:
            other_errors.append(f"failed to parse {session_file}: {exc}")
            continue
        for index, message in enumerate(session.get("messages", []) or []):
            if not isinstance(message, dict) or message.get("role") != "tool":
                continue
            if (message.get("name") or message.get("tool_name")) != "browser_navigate":
                continue
            browser_calls += 1
            parsed = parse_json_prefix(message.get("content"))
            error_text = ""
            if isinstance(parsed, dict):
                if parsed.get("success") is False:
                    failure_calls += 1
                    error_text = stringify(parsed.get("error") or parsed)
                else:
                    success_calls += 1
            else:
                raw = stringify(message.get("content"))
                if raw:
                    error_text = raw
                    failure_calls += 1

            if error_text:
                lowered = error_text.lower()
                if "cdp discovery methods failed" in lowered:
                    cdp_discovery_failed += 1
                if "connection refused" in lowered or "os error 111" in lowered:
                    cdp_refused += 1
                if "timed out" in lowered or "timeout" in lowered:
                    browser_timeout += 1
                tool_errors.append(
                    {
                        "session_file": str(session_file),
                        "message_index": index,
                        "error_class": classify_browser_error(error_text),
                        "error": error_text,
                    }
                )

    return {
        "browser_navigate_calls": browser_calls,
        "browser_success_calls": success_calls,
        "browser_failure_calls": failure_calls,
        "cdp_discovery_failed_calls": cdp_discovery_failed,
        "cdp_connection_refused_calls": cdp_refused,
        "browser_timeout_calls": browser_timeout,
        "cdp_connection_refused": cdp_refused > 0,
        "browser_timeout": browser_timeout > 0,
        "browser_tool_errors": tool_errors,
        "other_analysis_errors": other_errors,
    }


def analyze_agent_log(profile: str) -> dict[str, Any]:
    log_path = Path.home() / ".hermes" / "profiles" / profile / "logs" / "agent.log"
    if not log_path.exists():
        return {"agent_log_path": str(log_path), "agent_log_cdp_mentions": 0, "agent_log_tail": ""}
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return {
        "agent_log_path": str(log_path),
        "agent_log_cdp_mentions": text.lower().count("cdp discovery methods failed"),
        "agent_log_tail": tail(text, 3000),
    }


def summarize(details: list[dict[str, Any]], wall_seconds: float, config: StressConfig) -> dict[str, Any]:
    total = len(details)
    runs_with_browser = sum(1 for item in details if item.get("browser_navigate_calls", 0) > 0)
    runs_with_cdp_refused = sum(1 for item in details if item.get("cdp_connection_refused"))
    runs_with_timeout = sum(1 for item in details if item.get("browser_timeout"))
    browser_calls = sum(int(item.get("browser_navigate_calls", 0)) for item in details)
    cdp_refused_calls = sum(int(item.get("cdp_connection_refused_calls", 0)) for item in details)
    browser_timeout_calls = sum(int(item.get("browser_timeout_calls", 0)) for item in details)
    by_url: dict[str, Any] = {}
    by_port: dict[str, Any] = {}
    for url in config.urls:
        subset = [item for item in details if item.get("url") == url]
        subset_total = len(subset)
        subset_browser_runs = sum(1 for item in subset if item.get("browser_navigate_calls", 0) > 0)
        subset_cdp_runs = sum(1 for item in subset if item.get("cdp_connection_refused"))
        subset_timeout_runs = sum(1 for item in subset if item.get("browser_timeout"))
        subset_browser_calls = sum(int(item.get("browser_navigate_calls", 0)) for item in subset)
        subset_cdp_calls = sum(int(item.get("cdp_connection_refused_calls", 0)) for item in subset)
        subset_timeout_calls = sum(int(item.get("browser_timeout_calls", 0)) for item in subset)
        by_url[url] = {
            "total_runs": subset_total,
            "status_counts": dict(sorted(counts(item.get("status", "unknown") for item in subset).items())),
            "runs_with_browser_navigate": subset_browser_runs,
            "browser_navigate_calls": subset_browser_calls,
            "runs_with_cdp_connection_refused": subset_cdp_runs,
            "cdp_connection_refused_calls": subset_cdp_calls,
            "runs_with_browser_timeout": subset_timeout_runs,
            "browser_timeout_calls": subset_timeout_calls,
            "run_error_rate_cdp_refused_over_all": safe_rate(subset_cdp_runs, subset_total),
            "run_error_rate_cdp_refused_over_browser_runs": safe_rate(subset_cdp_runs, subset_browser_runs),
            "call_error_rate_cdp_refused": safe_rate(subset_cdp_calls, subset_browser_calls),
            "run_error_rate_timeout_over_browser_runs": safe_rate(subset_timeout_runs, subset_browser_runs),
        }
    for port in config.browser_ports:
        subset = [item for item in details if item.get("cdp_port") == port]
        subset_total = len(subset)
        subset_browser_runs = sum(1 for item in subset if item.get("browser_navigate_calls", 0) > 0)
        subset_cdp_runs = sum(1 for item in subset if item.get("cdp_connection_refused"))
        subset_timeout_runs = sum(1 for item in subset if item.get("browser_timeout"))
        subset_browser_calls = sum(int(item.get("browser_navigate_calls", 0)) for item in subset)
        subset_cdp_calls = sum(int(item.get("cdp_connection_refused_calls", 0)) for item in subset)
        subset_timeout_calls = sum(int(item.get("browser_timeout_calls", 0)) for item in subset)
        by_port[str(port)] = {
            "total_runs": subset_total,
            "status_counts": dict(sorted(counts(item.get("status", "unknown") for item in subset).items())),
            "runs_with_browser_navigate": subset_browser_runs,
            "browser_navigate_calls": subset_browser_calls,
            "runs_with_cdp_connection_refused": subset_cdp_runs,
            "cdp_connection_refused_calls": subset_cdp_calls,
            "runs_with_browser_timeout": subset_timeout_runs,
            "browser_timeout_calls": subset_timeout_calls,
            "run_error_rate_cdp_refused_over_all": safe_rate(subset_cdp_runs, subset_total),
            "run_error_rate_cdp_refused_over_browser_runs": safe_rate(subset_cdp_runs, subset_browser_runs),
            "call_error_rate_cdp_refused": safe_rate(subset_cdp_calls, subset_browser_calls),
            "run_error_rate_timeout_over_browser_runs": safe_rate(subset_timeout_runs, subset_browser_runs),
        }
    return {
        "dataset": config.dataset,
        "model": config.model,
        "provider": config.provider,
        "urls": config.urls,
        "runs_per_url": config.runs_per_url,
        "total_runs": total,
        "concurrency": config.concurrency,
        "browser_ports": config.browser_ports,
        "start_browsers": config.start_browsers,
        "keep_browsers": config.keep_browsers,
        "wall_seconds": wall_seconds,
        "status_counts": dict(sorted(counts(item.get("status", "unknown") for item in details).items())),
        "runs_with_browser_navigate": runs_with_browser,
        "browser_navigate_calls": browser_calls,
        "runs_with_cdp_connection_refused": runs_with_cdp_refused,
        "cdp_connection_refused_calls": cdp_refused_calls,
        "runs_with_browser_timeout": runs_with_timeout,
        "browser_timeout_calls": browser_timeout_calls,
        "run_error_rate_cdp_refused_over_all": safe_rate(runs_with_cdp_refused, total),
        "run_error_rate_cdp_refused_over_browser_runs": safe_rate(runs_with_cdp_refused, runs_with_browser),
        "call_error_rate_cdp_refused": safe_rate(cdp_refused_calls, browser_calls),
        "run_error_rate_timeout_over_browser_runs": safe_rate(runs_with_timeout, runs_with_browser),
        "by_url": by_url,
        "by_port": by_port,
    }


def print_summary(summary: dict[str, Any]) -> None:
    print("\nsummary")
    for key, value in summary.items():
        print(f"  {key}: {value}")


def parse_json_prefix(content: Any) -> Any | None:
    if isinstance(content, (dict, list)):
        return content
    if not isinstance(content, str):
        return None
    text = content.strip()
    if not text:
        return None
    try:
        parsed, _ = json.JSONDecoder().raw_decode(text)
        return parsed
    except Exception:
        return None


def classify_browser_error(error_text: str) -> str:
    lowered = error_text.lower()
    if "connection refused" in lowered or "os error 111" in lowered:
        return "connection_refused"
    if "cdp discovery methods failed" in lowered:
        return "cdp_discovery_failed"
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    return "other"


def run_hermes(hermes_bin: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run([str(hermes_bin)] + args, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"hermes command failed: {' '.join(args)}\n{tail(proc.stderr or proc.stdout)}")
    return proc


def profile_name(dataset: str, run_id: str) -> str:
    raw = f"browser-stress_{dataset}_{run_id}".lower()
    cleaned = re.sub(r"[^a-z0-9_-]", "-", raw).strip("-")
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    base = cleaned[:55].strip("-") or "browser-stress"
    return f"{base}-{digest}"[:64]


def update_profile_env(env_path: Path, config: StressConfig, spec: dict[str, Any]) -> None:
    values = merge_no_proxy(config.no_proxy, ["localhost", "127.0.0.1", "::1", endpoint_host(config.base_url)])
    cdp_url = str(spec["cdp_url"])
    if not env_path.exists():
        env_path.write_text(f"NO_PROXY={values}\nno_proxy={values}\nBROWSER_CDP_URL={cdp_url}\n", encoding="utf-8")
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    updated: list[str] = []
    for line in lines:
        key, sep, value = line.partition("=")
        if sep and key in {"NO_PROXY", "no_proxy"}:
            updated.append(f"{key}={merge_no_proxy(value, values.split(','))}")
            seen.add(key)
        elif sep and key == "BROWSER_CDP_URL":
            updated.append(f"BROWSER_CDP_URL={cdp_url}")
            seen.add(key)
        else:
            updated.append(line)
    if "NO_PROXY" not in seen:
        updated.append(f"NO_PROXY={values}")
    if "no_proxy" not in seen:
        updated.append(f"no_proxy={values}")
    if "BROWSER_CDP_URL" not in seen:
        updated.append(f"BROWSER_CDP_URL={cdp_url}")
    env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def merge_no_proxy(existing: str, additions: list[str]) -> str:
    values: list[str] = []
    seen: set[str] = set()
    for raw in [existing, ",".join(additions)]:
        for part in raw.split(","):
            value = part.strip()
            if not value:
                continue
            if value == "*":
                return "*"
            if value not in seen:
                seen.add(value)
                values.append(value)
    return ",".join(values)


def endpoint_host(base_url: str) -> str:
    try:
        return urlparse(base_url).hostname or ""
    except Exception:
        return ""


def decode_timeout_output(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def tail(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else text[-limit:]


def counts(values) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[str(value)] = result.get(str(value), 0) + 1
    return result


def safe_rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
