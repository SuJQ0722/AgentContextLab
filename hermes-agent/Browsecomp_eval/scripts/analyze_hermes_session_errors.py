#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_SESSION_ROOT = Path("/root/.hermes/sessions/Qwen3-5-9B/browsecomp_subset_first5")


def main() -> None:
    args = parse_args()
    records, stats = analyze(args.session_root)

    print_summary(args.session_root, records, stats)

    if args.details_json:
        args.details_json.parent.mkdir(parents=True, exist_ok=True)
        args.details_json.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nwrote JSON details: {args.details_json}")

    if args.details_csv:
        args.details_csv.parent.mkdir(parents=True, exist_ok=True)
        write_csv(args.details_csv, records)
        print(f"wrote CSV details: {args.details_csv}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze Hermes session JSON/JSONL files for search_server, fetch_server, and browser-server errors."
    )
    parser.add_argument(
        "session_root",
        nargs="?",
        type=Path,
        default=DEFAULT_SESSION_ROOT,
        help=f"Session root to scan. Default: {DEFAULT_SESSION_ROOT}",
    )
    parser.add_argument("--details-json", type=Path, help="Optional path to write detailed error records as JSON.")
    parser.add_argument("--details-csv", type=Path, help="Optional path to write detailed error records as CSV.")
    return parser.parse_args()


def analyze(session_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not session_root.exists():
        raise SystemExit(f"session root not found: {session_root}")

    records: list[dict[str, Any]] = []
    stats: dict[str, Any] = {
        "sessions": 0,
        "messages": 0,
        "tool_calls": Counter(),
        "search_empty_results": 0,
        "search_success_false": 0,
        "fetch_url_attempts": 0,
        "fetch_result_errors": 0,
        "fetch_soft_failures": 0,
        "tool_success_false": Counter(),
        "tool_loop_warnings": 0,
        "parse_failures": 0,
    }

    for session_path, session in iter_sessions(session_root):
        stats["sessions"] += 1
        question_id = question_id_from_path(session_path)
        session_id = session.get("session_id") or session_path.stem.removeprefix("session_")

        for msg_index, message in enumerate(session.get("messages", []) or []):
            stats["messages"] += 1
            if not isinstance(message, dict) or message.get("role") != "tool":
                continue

            tool_name = str(message.get("name") or message.get("tool_name") or "unknown")
            stats["tool_calls"][tool_name] += 1

            content = message.get("content")
            content_text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            if "[Tool loop warning:" in content_text:
                stats["tool_loop_warnings"] += 1

            parsed = parse_json_prefix(content)
            if parsed is None:
                stats["parse_failures"] += 1
                continue

            base = {
                "question_id": question_id,
                "session_id": session_id,
                "session_file": str(session_path),
                "message_index": msg_index,
                "tool": tool_name,
                "tool_call_id": message.get("tool_call_id") or "",
            }

            if isinstance(parsed, dict) and parsed.get("success") is False:
                error_text = stringify(parsed.get("error") or parsed)
                stats["tool_success_false"][tool_name] += 1
                if tool_name == "web_search":
                    stats["search_success_false"] += 1
                records.append(
                    {
                        **base,
                        "component": component_for_tool(tool_name),
                        "kind": "tool_success_false",
                        "error_class": classify_error(error_text),
                        "error": error_text,
                        "url": "",
                    }
                )
                continue

            if tool_name == "web_search":
                web_results = dig(parsed, "data", "web")
                if isinstance(web_results, list) and not web_results:
                    stats["search_empty_results"] += 1
                continue

            if tool_name == "web_extract":
                for result_index, result in enumerate(extract_results(parsed)):
                    if not isinstance(result, dict):
                        continue
                    stats["fetch_url_attempts"] += 1
                    url = stringify(result.get("url"))
                    if result.get("error"):
                        error_text = stringify(result.get("error"))
                        stats["fetch_result_errors"] += 1
                        records.append(
                            {
                                **base,
                                "component": "fetch_server",
                                "kind": "result_error",
                                "error_class": classify_error(error_text),
                                "error": error_text,
                                "url": url,
                                "result_index": result_index,
                            }
                        )
                        continue

                    content_body = stringify(result.get("content"))
                    if looks_like_soft_fetch_failure(content_body):
                        stats["fetch_soft_failures"] += 1
                        records.append(
                            {
                                **base,
                                "component": "fetch_server",
                                "kind": "content_failure_summary",
                                "error_class": "extract_empty_summary",
                                "error": "content summary indicates unavailable/failed extraction",
                                "url": url,
                                "result_index": result_index,
                            }
                        )

    return records, stats


def iter_sessions(session_root: Path):
    paths = sorted(session_root.rglob("session_*.json")) + sorted(session_root.rglob("*.jsonl"))
    for path in paths:
        if path.suffix == ".jsonl":
            with path.open("r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, start=1):
                    if not line.strip():
                        continue
                    try:
                        yield path, json.loads(line)
                    except Exception as exc:
                        print(f"warning: failed to parse {path}:{line_no}: {exc}")
            continue

        try:
            yield path, json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"warning: failed to parse {path}: {exc}")


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


def extract_results(parsed: Any) -> list[Any]:
    if isinstance(parsed, dict) and isinstance(parsed.get("results"), list):
        return parsed["results"]
    return []


def dig(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def question_id_from_path(path: Path) -> str:
    for parent in path.parents:
        if re.fullmatch(r"q\d{6}", parent.name):
            return parent.name
    return ""


def component_for_tool(tool_name: str) -> str:
    if tool_name == "web_search":
        return "search_server"
    if tool_name == "web_extract":
        return "fetch_server"
    if tool_name.startswith("browser_"):
        return "browser_server"
    return "other_tool"


def classify_error(error_text: str) -> str:
    text = error_text.lower()
    if "http error" in text:
        match = re.search(r"http error\s+(\d+)", text)
        return f"http_error_{match.group(1)}" if match else "http_error"
    if "page not found" in text or "http 404" in text:
        return "http_error_404"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if "connection refused" in text:
        return "connection_refused"
    if "cdp" in text:
        return "cdp_failure"
    if "failed to connect" in text:
        return "connect_failure"
    if "failed to retrieve substantive" in text or "no useful information found" in text:
        return "extract_empty_summary"
    return "other"


def looks_like_soft_fetch_failure(content: str) -> bool:
    return bool(
        re.search(
            r"Failed to retrieve substantive data|No useful information found|Availability:\*\*\s+Unavailable",
            content,
            re.IGNORECASE,
        )
    )


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def print_summary(session_root: Path, records: list[dict[str, Any]], stats: dict[str, Any]) -> None:
    tool_calls = Counter(stats["tool_calls"])
    tool_success_false = Counter(stats["tool_success_false"])
    by_component = Counter(record["component"] for record in records)
    by_tool = Counter(record["tool"] for record in records)
    by_kind = Counter(record["kind"] for record in records)
    by_class = Counter(record["error_class"] for record in records)
    by_question = Counter(record["question_id"] for record in records)

    print(f"session_root: {session_root}")
    print(f"sessions: {stats['sessions']}")
    print(f"messages: {stats['messages']}")
    print(f"tool_calls: {dict(sorted(tool_calls.items()))}")
    print()
    print("search_server / web_search")
    print(f"  calls: {tool_calls.get('web_search', 0)}")
    print(f"  success_false_errors: {stats['search_success_false']}")
    print(f"  empty_result_calls: {stats['search_empty_results']}")
    print()
    print("fetch_server / web_extract")
    print(f"  calls: {tool_calls.get('web_extract', 0)}")
    print(f"  url_attempts: {stats['fetch_url_attempts']}")
    print(f"  explicit_result_errors: {stats['fetch_result_errors']}")
    print(f"  soft_failure_summaries: {stats['fetch_soft_failures']}")
    print()
    print("all recorded error-like events")
    print(f"  total: {len(records)}")
    print(f"  by_component: {dict(sorted(by_component.items()))}")
    print(f"  by_tool: {dict(sorted(by_tool.items()))}")
    print(f"  by_kind: {dict(sorted(by_kind.items()))}")
    print(f"  by_class: {dict(sorted(by_class.items()))}")
    print(f"  by_question: {dict(sorted(by_question.items()))}")
    print(f"  tool_success_false_by_tool: {dict(sorted(tool_success_false.items()))}")
    print(f"  tool_loop_warnings: {stats['tool_loop_warnings']}")
    print(f"  unparsed_tool_contents: {stats['parse_failures']}")

    if records:
        print()
        print("examples:")
        for record in records[:20]:
            error = record["error"].replace("\n", " ")[:220]
            print(
                "  - "
                f"{record['question_id']} {Path(record['session_file']).name} "
                f"msg={record['message_index']} component={record['component']} "
                f"tool={record['tool']} class={record['error_class']} "
                f"url={record.get('url', '')} error={error}"
            )


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fieldnames = [
        "question_id",
        "session_id",
        "component",
        "tool",
        "kind",
        "error_class",
        "error",
        "url",
        "session_file",
        "message_index",
        "tool_call_id",
        "result_index",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({key: record.get(key, "") for key in fieldnames})


if __name__ == "__main__":
    main()
