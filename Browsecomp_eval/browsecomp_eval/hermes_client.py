from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .dataset import RunSpec
from .session_reader import (
    _TOKEN_COLUMNS,
    _empty_token_usage,
    extract_final_assistant_message,
    extract_trace,
    load_child_sessions,
    load_compression_snapshots,
    load_session,
    load_token_usage,
)

_API_ERROR_RE = re.compile(r"Error code:\s*(\d+)\s*-\s*(.+?)(?:\n\s*\n|\Z)", re.DOTALL)
_FAIL_REASON_PATTERNS = [
    re.compile(r"API call failed after \d+ retries[.:]\s*(.+)", re.IGNORECASE),
    re.compile(r"Error code:\s*\d+\s*-\s*\{[^}]*'message':\s*'([^']+)'", re.DOTALL),
    re.compile(r"(insufficient_quota|rate_limit_exceeded|context_length_exceeded|Connection error)", re.IGNORECASE),
    re.compile(r"(BadRequestError|AuthenticationError|APIConnectionError|RateLimitError)[:\s]+(.+?)(?:\n|$)"),
]


def _extract_fail_reason(stdout: str, stderr: str, agent_log: str) -> str:
    """Best-effort extraction of a human-readable failure reason from output."""
    combined = f"{stderr}\n{stdout}\n{agent_log}"
    for pat in _FAIL_REASON_PATTERNS:
        m = pat.search(combined)
        if m:
            reason = m.group(m.lastindex).strip()
            if len(reason) > 200:
                reason = reason[:200] + "..."
            return reason
    return ""


def parse_api_error(stderr: str) -> tuple[int | None, str]:
    """从 stderr 中提取 HTTP 状态码和错误消息。"""
    m = _API_ERROR_RE.search(stderr)
    if not m:
        return None, ""
    code = int(m.group(1))
    raw = m.group(2).strip()
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        try:
            body = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return code, raw[:200]
    if isinstance(body, dict):
        err = body.get("error", {})
        if isinstance(err, dict):
            msg = err.get("message", "")
            err_type = err.get("type", "")
            if err_type:
                msg = f"[{err_type}] {msg}" if msg else err_type
            return code, msg or raw[:200]
    return code, raw[:200]


@dataclass(frozen=True)
class HermesConfig:
    hermes_bin: str
    api_key: str
    base_url: str
    model: str
    provider: str
    save_name: str
    dataset: str
    max_rounds: int
    timeout_seconds: int
    toolsets: list[str]
    skills: list[str]
    context_length: int | None = None
    quiet: bool = True
    accept_hooks: bool = False
    ignore_rules: bool = False
    reasoning_effort: str | None = None
    max_tool_response_tokens: int | None = None
    api_mode: str | None = None
    compression_threshold: float | None = None
    context_engine: str | None = None


class HermesClient:
    def __init__(self, config: HermesConfig):
        self.config = config

    def run(self, spec: RunSpec, workspace_dir: Path, attempt: int) -> dict[str, Any]:
        workspace_dir.mkdir(parents=True, exist_ok=True)
        profile = profile_name(self.config.save_name, spec.question_id, spec.repeat_index, attempt)
        self._setup_profile(profile, workspace_dir)

        query = build_query(spec, enable_delegate=has_delegation_tool(self.config.toolsets))
        cmd = self._build_chat_command(profile, query)
        env = self._build_env(spec)

        started = time.time()
        stdout = ""
        stderr = ""
        returncode: int | None = None
        timed_out = False
        error = ""

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(workspace_dir),
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
                env=env,
            )
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            returncode = proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            error = f"hermes timed out after {self.config.timeout_seconds}s"
        except Exception as exc:
            error = str(exc)

        wall_seconds = round(time.time() - started, 2)
        session_id = extract_session_id(stdout, stderr) or find_session_id_from_storage(
            self.config.save_name,
            self.config.dataset,
            spec.question_id,
            started,
        )
        session = load_session(session_id, profile)
        session_full = load_session(session_id, profile, include_ancestors=True)
        trace = extract_trace(session_full or session)
        token_usage = load_token_usage(session_id, profile)
        delegate_sessions = load_child_sessions(session_id, profile) if session_id else []
        model_response, final_assistant_error = extract_final_assistant_message(session)
        compression_stats = _load_compression_stats(workspace_dir.parent)
        compression_snapshots = load_compression_snapshots(session_id, profile) if session_id else []

        delegate_token_usage = _empty_token_usage()
        delegate_compression_snapshots: dict[str, list] = {}
        for ds in delegate_sessions:
            child_id = ds.get("session_id")
            if child_id:
                child_usage = load_token_usage(child_id, profile)
                for col in _TOKEN_COLUMNS:
                    delegate_token_usage[col] += child_usage.get(col, 0)
                delegate_token_usage["total_tokens"] += child_usage.get("total_tokens", 0)
                delegate_token_usage["session_count"] += child_usage.get("session_count", 0)
                child_snaps = load_compression_snapshots(child_id, profile)
                if child_snaps:
                    delegate_compression_snapshots[child_id] = child_snaps

        status = "success"
        api_code, api_msg = parse_api_error(stderr)
        if api_code is not None:
            status = "failed"
            error = f"HTTP {api_code}: {api_msg}"
        elif timed_out or error or (returncode not in (0, None)):
            status = "failed"
            if not error:
                error = f"hermes exited with code {returncode}"
            agent_log_text = read_profile_agent_log_tail(profile)
            reason = _extract_fail_reason(stdout, stderr, agent_log_text)
            if reason and reason not in error:
                error = f"{error} | {reason}"
        if not model_response and status == "success":
            status = "failed"
            error = final_assistant_error or "empty final assistant response"

        return {
            "question_id": spec.question_id,
            "repeat_index": spec.repeat_index,
            "run_id": spec.run_id,
            "attempt": attempt,
            "question": spec.item.question,
            "answer": spec.item.answer,
            "type": spec.item.type,
            "model": self.config.model,
            "provider": self.config.provider,
            "save_name": self.config.save_name,
            "status": status,
            "error": error,
            "error_code": api_code,
            "returncode": returncode,
            "timed_out": timed_out,
            "model_response": model_response,
            "final_assistant_valid": bool(model_response),
            "final_assistant_error": final_assistant_error,
            "session_id": session_id,
            "profile": profile,
            "workspace_dir": str(workspace_dir),
            "output_files": list_workspace_files(workspace_dir),
            "tool_calls": trace["tool_calls"],
            "rounds": trace["rounds"],
            "total_tokens_estimate": trace["total_tokens_estimate"],
            "token_usage": token_usage,
            "input_tokens": token_usage["input_tokens"],
            "output_tokens": token_usage["output_tokens"],
            "total_tokens": token_usage["total_tokens"],
            "api_call_count": token_usage["api_call_count"],
            "duration_seconds": trace["duration_seconds"] or wall_seconds,
            "wall_seconds": wall_seconds,
            "stdout_tail": tail(stdout),
            "stderr_tail": tail(stderr),
            "agent_log_tail": read_profile_agent_log_tail(profile),
            "history": (session_full or session or {}).get("messages", []),
            "compressed_session_messages": (session or {}).get("messages", []),
            "compression_count": (session_full or {}).get("compression_count", 0),
            "compression_stats": compression_stats,
            "compression_snapshots": compression_snapshots,
            "delegate_sessions": delegate_sessions,
            "delegate_token_usage": delegate_token_usage,
            "delegate_compression_snapshots": delegate_compression_snapshots,
        }

    def _setup_profile(self, profile: str, workspace_dir: Path) -> None:
        self._run_hermes(["profile", "create", profile, "--no-alias"], check=False)
        self._copy_default_profile_config(profile)

        effective_url = self.config.base_url
        if self.config.provider != "custom" and effective_url:
            effective_url = effective_url.rstrip("/")
            if effective_url.endswith("/v1"):
                effective_url = effective_url[:-3]

        configs = [
            ("model.default", self.config.model),
            ("model.provider", self.config.provider),
            ("model.api_key", self.config.api_key),
            ("terminal.timeout", str(max(120, self.config.timeout_seconds))),
            ("terminal.cwd", "."),
            # Pin visual-compression image/PDF output to the per-question workspace
            # (one level above attempt_N) so artifacts survive retries and sit at
            # the level a human inspector expects.
            ("context.strategy_config.save_dir", str(workspace_dir.parent)),
            # Eval isolation: keep every run hermetic. Disable cross-session
            # memory (no reading or writing a persistent profile/user store)
            # and the curator (background skill auto-evolution / archiving) so
            # one question's run can neither pollute nor be polluted by another.
            ("memory.memory_enabled", "false"),
            ("memory.user_profile_enabled", "false"),
            ("curator.enabled", "false"),
        ]
        if self.config.context_length:
            configs.append(("model.context_length", str(self.config.context_length)))
        if self.config.reasoning_effort:
            configs.append(("model.reasoning", self.config.reasoning_effort))
        if effective_url:
            configs.append(("model.base_url", effective_url))
        if self.config.max_tool_response_tokens is not None:
            configs.append(("tool_output.max_bytes", str(self.config.max_tool_response_tokens)))
        if self.config.api_mode:
            configs.append(("model.api_mode", self.config.api_mode))
        if self.config.compression_threshold is not None:
            threshold = self.config.compression_threshold
            if threshold >= 1.0:
                ctx_len = self.config.context_length or 262144
                threshold = threshold / ctx_len
            configs.append(("compression.enabled", "true"))
            configs.append(("compression.threshold", str(threshold)))
        if self.config.context_engine:
            configs.append(("context.engine", self.config.context_engine))

        for key, value in configs:
            self._run_hermes(["--profile", profile, "config", "set", key, value])

    def _copy_default_profile_config(self, profile: str) -> None:
        default_home = Path.home() / ".hermes"
        profile_home = default_home / "profiles" / profile
        profile_home.mkdir(parents=True, exist_ok=True)
        for filename in ("config.yaml", ".env"):
            src = default_home / filename
            if src.exists():
                shutil.copy2(src, profile_home / filename)
        self._merge_profile_env(profile_home / ".env")

    def _run_hermes(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            [self.config.hermes_bin] + args,
            capture_output=True,
            text=True,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"hermes command failed: {' '.join(args)}\n{tail(proc.stderr or proc.stdout)}"
            )
        return proc

    def _build_chat_command(self, profile: str, query: str) -> list[str]:
        cmd = [
            self.config.hermes_bin,
            "--profile",
            profile,
            "chat",
            "--query",
            query,
            "--yolo",
            "--max-turns",
            str(self.config.max_rounds),
            "--model",
            self.config.model,
            "--provider",
            self.config.provider,
            "--source",
            "browse_comp_eval",
        ]
        if self.config.quiet:
            cmd.append("--quiet")
        if self.config.toolsets:
            cmd.extend(["--toolsets", ",".join(self.config.toolsets)])
        else:
            cmd.extend(["--toolsets", "none"])
        if self.config.skills:
            cmd.extend(["--skills", ",".join(self.config.skills)])
        if self.config.accept_hooks:
            cmd.append("--accept-hooks")
        if self.config.ignore_rules:
            cmd.append("--ignore-rules")
        return cmd

    def _build_env(self, spec: RunSpec) -> dict[str, str]:
        env = os.environ.copy()
        env["ANTHROPIC_API_KEY"] = self.config.api_key
        env["OPENAI_API_KEY"] = self.config.api_key
        if self.config.base_url:
            env["ANTHROPIC_BASE_URL"] = self.config.base_url
            env["OPENAI_BASE_URL"] = self.config.base_url
        no_proxy = merge_no_proxy(env.get("NO_PROXY") or env.get("no_proxy") or "", self._no_proxy_additions())
        if no_proxy:
            env["NO_PROXY"] = no_proxy
            env["no_proxy"] = no_proxy
        env["HERMES_SESSION_MODEL"] = self.config.save_name
        env["HERMES_SESSION_DATASET"] = self.config.dataset
        env.setdefault("HERMES_SESSION_STORAGE_ROOT", str(Path.home() / ".hermes" / "sessions"))
        env["HERMES_SESSION_TASK_TYPE"] = spec.item.type
        env["HERMES_SESSION_TASK_ID"] = spec.question_id
        env["HERMES_SESSION_TASK_NAME"] = spec.question_id
        env.pop("HERMES_TASK_ID", None)
        env["BROWSE_COMP_RUN_ID"] = f"iter{spec.repeat_index}/{spec.question_id}"
        return env

    def _merge_profile_env(self, env_path: Path) -> None:
        additions = self._no_proxy_additions()
        if not env_path.exists():
            lines: list[str] = []
        else:
            lines = env_path.read_text(encoding="utf-8").splitlines()

        if not additions:
            return

        seen_keys: set[str] = set()
        updated: list[str] = []
        for line in lines:
            key, sep, value = line.partition("=")
            if sep and key in {"NO_PROXY", "no_proxy"}:
                updated.append(f"{key}={merge_no_proxy(value, additions)}")
                seen_keys.add(key)
            else:
                updated.append(line)

        merged = merge_no_proxy(os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or "", additions)
        if "NO_PROXY" not in seen_keys:
            updated.append(f"NO_PROXY={merged}")
        if "no_proxy" not in seen_keys:
            updated.append(f"no_proxy={merged}")

        env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")

    def _no_proxy_additions(self) -> list[str]:
        additions = ["localhost", "127.0.0.1", "::1"]
        host = endpoint_host(self.config.base_url)
        if host:
            additions.append(host)
        return additions

def has_delegation_tool(toolsets: list[str]) -> bool:
    return any(toolset.strip() == "delegation" for toolset in toolsets)


def build_query(spec: RunSpec, enable_delegate: bool = False) -> str:
    base = (
        "You are running one browse-comparison evaluation task.\n"
        "Use only the tools made available in this Hermes session.\n"
        "Do not use or mention the reference answer. It is reserved for offline evaluation.\n"
        "If the task asks you to create a file, save it in the current working directory.\n\n"
    )
    delegate_prompt = (
        "STRATEGY:\n"
        "This task requires tracing a chain of connections. You should use the delegate_task "
        "tool to parallelize independent research subtasks. For example, if the question "
        "describes a multi-step chain (A→B→C→D→E), delegate parallel searches for "
        "different segments of the chain to subagents, then synthesize their findings.\n"
        "Each delegate receives its own context and tools — use batch mode (the 'tasks' "
        "array) to spawn multiple subagents simultaneously when segments are independent.\n\n"
    )
    task = (
        f"Task type: {spec.item.type}\n"
        f"Question:\n{spec.item.question}\n\n"
        "Return the final answer clearly."
    )
    return base + (delegate_prompt if enable_delegate else "") + task


def profile_name(save_name: str, question_id: str, repeat_index: int, attempt: int) -> str:
    raw = f"{save_name}_iter{repeat_index}_{question_id}_a{attempt}".lower()
    cleaned = re.sub(r"[^a-z0-9_-]", "-", raw).strip("-")
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    base = cleaned[:55].strip("-") or "browse-comp"
    return f"{base}-{digest}"[:64]


def endpoint_host(base_url: str) -> str:
    if not base_url:
        return ""
    try:
        return urlparse(base_url).hostname or ""
    except Exception:
        return ""


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


def read_profile_agent_log_tail(profile: str, limit: int = 8000) -> str:
    log_path = Path.home() / ".hermes" / "profiles" / profile / "logs" / "agent.log"
    if not log_path.exists():
        return ""
    try:
        return tail(log_path.read_text(encoding="utf-8", errors="replace"), limit)
    except Exception:
        return ""


def find_session_id_from_storage(save_name: str, dataset: str, question_id: str, started: float) -> str | None:
    root = Path(os.environ.get("HERMES_SESSION_STORAGE_ROOT", str(Path.home() / ".hermes" / "sessions")))
    if root.name != "sessions":
        root = root / "sessions"
    session_dir = root / save_name / dataset / question_id / "main"
    if not session_dir.exists():
        return None

    newest: Path | None = None
    newest_mtime = 0.0
    for path in session_dir.glob("session_*.json"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < started - 5:
            continue
        if mtime > newest_mtime:
            newest = path
            newest_mtime = mtime

    if newest is None:
        return None
    name = newest.name
    if not name.startswith("session_") or not name.endswith(".json"):
        return None
    return name[len("session_") : -len(".json")]


def extract_session_id(stdout: str, stderr: str) -> str | None:
    combined = f"{stderr}\n{stdout}"
    for pattern in (r"session_id:\s*(\S+)", r"\bsession=([0-9A-Za-z_-]+)\b"):
        match = re.search(pattern, combined)
        if match:
            return match.group(1)
    return None


def tail(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def list_workspace_files(workspace_dir: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    if not workspace_dir.exists():
        return files
    for path in sorted(workspace_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(workspace_dir).as_posix()
        files.append({"path": rel, "size": path.stat().st_size})
    return files


def _load_compression_stats(save_dir: Path) -> dict[str, Any]:
    """Read the visual engine's compression_stats.json sidecar from save_dir.

    Returns an empty dict when the file is absent (non-visual runs or no
    compression occurred).
    """
    path = save_dir / "compression_stats.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
