from __future__ import annotations

import concurrent.futures
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .dataset import RunSpec
from .hermes_client import HermesClient
from .whitelist import find_policy_violations


@dataclass(frozen=True)
class RunnerConfig:
    output_dir: Path
    workspace_dir: Path
    summary_path: Path
    num_workers: int
    max_retries: int
    force: bool
    skip_statuses: set[str]
    allowed_tools: set[str]
    conv_dir: Path | None = None
    log_dir: Path | None = None
    trajectory_dir: Path | None = None


class BrowseCompRunner:
    def __init__(self, client: HermesClient, config: RunnerConfig):
        self.client = client
        self.config = config
        self._summary_lock = threading.Lock()

    def run(self, specs: Iterable[RunSpec]) -> dict[str, int]:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self.config.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.config.summary_path.parent.mkdir(parents=True, exist_ok=True)
        if self.config.conv_dir:
            self.config.conv_dir.mkdir(parents=True, exist_ok=True)
        if self.config.log_dir:
            self.config.log_dir.mkdir(parents=True, exist_ok=True)

        all_specs = list(specs)
        pending = [spec for spec in all_specs if self._should_run(spec)]
        print(f"loaded runs: {len(all_specs)}")
        print(f"pending runs: {len(pending)}")

        stats = {"total": len(all_specs), "pending": len(pending), "success": 0, "failed": 0, "policy_violation": 0, "skipped": len(all_specs) - len(pending)}
        if not pending:
            return stats

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.config.num_workers) as executor:
            future_to_spec = {executor.submit(self._run_one, spec): spec for spec in pending}
            completed = 0
            for future in concurrent.futures.as_completed(future_to_spec):
                spec = future_to_spec[future]
                completed += 1
                try:
                    result = future.result()
                except Exception as exc:
                    result = self._exception_result(spec, exc)
                    self._write_result(spec, result)
                status = result.get("status", "failed")
                stats[status] = stats.get(status, 0) + 1
                print(f"[{completed}/{len(pending)}] {format_run_label(spec)}: {status}")
        return stats

    def _should_run(self, spec: RunSpec) -> bool:
        if self.config.force:
            return True
        path = self._result_path(spec)
        if not path.exists():
            return True
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return True
        return existing.get("status") not in self.config.skip_statuses

    def _run_one(self, spec: RunSpec) -> dict:
        attempts: list[dict] = []
        final_result: dict | None = None
        max_retries = max(1, self.config.max_retries)

        for attempt in range(1, max_retries + 1):
            attempt_workspace = self.config.workspace_dir / f"iter{spec.repeat_index}" / spec.question_id / f"attempt_{attempt}"
            result = self.client.run(spec, attempt_workspace, attempt=attempt)
            result = self._apply_policy(result)
            attempts.append(
                {
                    "attempt": attempt,
                    "status": result.get("status"),
                    "error": result.get("error", ""),
                    "session_id": result.get("session_id"),
                    "profile": result.get("profile"),
                    "duration_seconds": result.get("duration_seconds", 0),
                }
            )
            final_result = result
            final_result["retry_attempts"] = attempts
            final_result["max_retries"] = max_retries
            final_result["completed"] = result.get("status") != "failed"
            self._write_result(spec, final_result)
            if result.get("status") != "failed":
                break

        assert final_result is not None
        final_result["completed"] = final_result.get("status") != "failed"
        return final_result

    def _apply_policy(self, result: dict) -> dict:
        tool_calls = result.get("tool_calls") or {}
        violations = find_policy_violations(tool_calls, self.config.allowed_tools)
        if violations:
            result["status"] = "policy_violation"
            result["policy_violations"] = violations
            result["error"] = "tool call outside whitelist: " + ", ".join(violations)
        else:
            result["policy_violations"] = []
        return result

    def _write_result(self, spec: RunSpec, result: dict) -> None:
        path = self._result_path(spec)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        persisted = dict(result)
        full_agent_log = str(persisted.pop("_agent_log_full", "") or "")
        tmp.write_text(json.dumps(persisted, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

        if self.config.trajectory_dir:
            # Separate files avoid interleaving workers and preserve retry attempts.
            trajectory_path = (self.config.trajectory_dir / f"iter{spec.repeat_index}"
                               / spec.question_id / f"attempt_{result.get('attempt', 1)}.jsonl")
            trajectory_path.parent.mkdir(parents=True, exist_ok=True)
            trajectory = {
                "session_id": result.get("session_id"),
                "question_id": spec.question_id,
                "repeat_index": spec.repeat_index,
                "attempt": result.get("attempt", 1),
                "model": result.get("model"),
                "status": result.get("status"),
                "messages": result.get("history", []),
            }
            trajectory_tmp = trajectory_path.with_suffix(".jsonl.tmp")
            trajectory_tmp.write_text(json.dumps(trajectory, ensure_ascii=False) + "\n", encoding="utf-8")
            trajectory_tmp.replace(trajectory_path)

        if self.config.log_dir:
            log_path = self.config.log_dir / f"iter{spec.repeat_index}" / f"{spec.question_id}.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(full_agent_log, encoding="utf-8")

        if self.config.conv_dir:
            self._write_conv(spec, result)

        summary = {
            "run_id": result.get("run_id"),
            "question_id": result.get("question_id"),
            "repeat_index": result.get("repeat_index"),
            "type": result.get("type"),
            "status": result.get("status"),
            "error": result.get("error", ""),
            "final_assistant_valid": result.get("final_assistant_valid", False),
            "round_limit_reached": result.get("round_limit_reached", False),
            "session_id": result.get("session_id"),
            "profile": result.get("profile"),
            "duration_seconds": result.get("duration_seconds", 0),
            "tool_calls": result.get("tool_calls", {}),
            "token_usage": result.get("token_usage", {}),
            "input_tokens": result.get("input_tokens", 0),
            "output_tokens": result.get("output_tokens", 0),
            "total_tokens": result.get("total_tokens", 0),
            "api_call_count": result.get("api_call_count", 0),
            "compression_stats": result.get("compression_stats", {}),
            "compression_count": result.get("compression_count", 0),
            "compression_aware_tokens": result.get("compression_aware_tokens", 0),
            "context_accounting": result.get("context_accounting", {}),
            "delegate_token_usage": result.get("delegate_token_usage", {}),
            "result_path": str(path),
            "workspace_dir": result.get("workspace_dir"),
            "context_image_dir": result.get("context_image_dir", ""),
        }
        with self._summary_lock:
            with self.config.summary_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(summary, ensure_ascii=False) + "\n")

    def _result_path(self, spec: RunSpec) -> Path:
        return self.config.output_dir / f"iter{spec.repeat_index}" / f"{spec.question_id}.json"

    def _write_conv(self, spec: RunSpec, result: dict) -> None:
        """Write the compressed-session view (what the model last saw)."""
        conv_path = self.config.conv_dir / f"iter{spec.repeat_index}" / f"{spec.question_id}.json"
        conv_path.parent.mkdir(parents=True, exist_ok=True)
        conv_data = {
            "question_id": result.get("question_id"),
            "repeat_index": result.get("repeat_index"),
            "question": result.get("question"),
            "answer": result.get("answer"),
            "type": result.get("type"),
            "image": result.get("image", []),
            "model": result.get("model"),
            "status": result.get("status"),
            "model_response": result.get("model_response"),
            "final_assistant_valid": result.get("final_assistant_valid", False),
            "round_limit_reached": result.get("round_limit_reached", False),
            "session_id": result.get("session_id"),
            "rounds": result.get("rounds", 0),
            "compression_count": result.get("compression_count", 0),
            "compression_stats": result.get("compression_stats", {}),
            "context_accounting": result.get("context_accounting", {}),
            "compression_aware_tokens": result.get("compression_aware_tokens", 0),
            "token_usage": result.get("token_usage", {}),
            "input_tokens": result.get("input_tokens", 0),
            "output_tokens": result.get("output_tokens", 0),
            "total_tokens": result.get("total_tokens", 0),
            "api_call_count": result.get("api_call_count", 0),
            "messages": result.get("compressed_session_messages", []),
            "delegate_sessions": result.get("delegate_sessions", []),
            "delegate_token_usage": result.get("delegate_token_usage", {}),
            "context_image_dir": result.get("context_image_dir", ""),
        }
        tmp = conv_path.with_suffix(conv_path.suffix + ".tmp")
        tmp.write_text(json.dumps(conv_data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(conv_path)

    def _exception_result(self, spec: RunSpec, exc: Exception) -> dict:
        return {
            "question_id": spec.question_id,
            "repeat_index": spec.repeat_index,
            "run_id": spec.run_id,
            "question": spec.item.question,
            "answer": spec.item.answer,
            "type": spec.item.type,
            "status": "failed",
            "error": str(exc),
            "tool_calls": {},
            "policy_violations": [],
            "history": [],
            "compressed_session_messages": [],
            "compression_count": 0,
            "compression_snapshots": [],
            "delegate_token_usage": {},
        }


def format_run_label(spec: RunSpec) -> str:
    return f"iter{spec.repeat_index}/{spec.run_id}"
