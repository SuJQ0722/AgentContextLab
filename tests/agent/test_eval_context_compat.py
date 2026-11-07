"""Real engine loading, legacy argument resolution, and trajectory file I/O."""
import json
import sqlite3
from pathlib import Path

import pytest

from Browsecomp_eval.browsecomp_eval.dataset import DatasetItem, RunSpec
from Browsecomp_eval.browsecomp_eval.hermes_client import HermesClient, HermesConfig
from Browsecomp_eval.browsecomp_eval.run import build_parser
from Browsecomp_eval.browsecomp_eval.runner import BrowseCompRunner, RunnerConfig
from Browsecomp_eval.browsecomp_eval.session_reader import load_session
from plugins.context_engine import load_context_engine


@pytest.mark.parametrize("name", ["discard", "discard_all", "discard-all"])
def test_full_reset_has_no_replacement_history(name):
    engine = load_context_engine(name)
    engine.configure({"strategy_config": {"keep_rounds": 0}})
    initial = [{"role": "system", "content": "instructions"},
               {"role": "user", "content": [{"type": "text", "text": "original task"}]}]
    messages = initial + [
        {"role": "assistant", "content": "old reasoning", "tool_calls": [{"id": "t"}]},
        {"role": "tool", "tool_call_id": "t", "content": "old evidence"},
        {"role": "user", "content": "old intermediate context"},
    ]
    assert engine.compress(messages) == initial
    assert engine.compress(engine.compress(messages)) == initial
    assert len(messages) == 5  # input is not mutated
    assert engine.compress(initial + [{"role": "user", "content": "old summary"}]) == initial


def test_legacy_env_and_explicit_cli_precedence(monkeypatch, tmp_path):
    monkeypatch.delenv("CM", raising=False)
    monkeypatch.delenv("CONTEXT_ENGINE", raising=False)
    monkeypatch.setenv("COMPRESS_STRATEGY", "discard-all")
    monkeypatch.setenv("SAVE_TRAJECTORIES", "1")
    monkeypatch.setenv("TRAJECTORY_DIR", str(tmp_path))
    parser = build_parser()
    args = parser.parse_args(["--dataset", "example", "--model", "test"])
    assert args.context_engine == "discard-all"
    assert args.save_trajectories and args.trajectory_dir == tmp_path
    args = parser.parse_args(["--dataset", "example", "--model", "test",
                              "--context-engine", "visual", "--no-save-trajectories"])
    assert args.context_engine == "visual" and not args.save_trajectories


def test_eval_environment_cannot_override_explicit_strategy(monkeypatch, tmp_path):
    monkeypatch.setenv("CM", "visual")
    monkeypatch.setenv("HERMES_DISCARD_KEEP_ROUNDS", "5")
    client = HermesClient(HermesConfig(
        hermes_bin="hermes", api_key="", base_url="", model="test", provider="custom",
        save_name="test", dataset="example", max_rounds=2, timeout_seconds=20,
        toolsets=[], skills=[], context_engine="discard-all"))
    spec = RunSpec("q1", "q1", 1, DatasetItem("q1", "task", "answer", "text", 1))
    env = client._build_env(spec, tmp_path)
    assert "CM" not in env
    assert env["HERMES_DISCARD_KEEP_ROUNDS"] == "0"


def test_sqlite_history_export_preserves_ancestors_and_attempts(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    with sqlite3.connect(tmp_path / "state.db") as db:
        db.executescript('''
            CREATE TABLE sessions (id TEXT, model TEXT, started_at REAL, ended_at REAL,
                system_prompt TEXT, message_count INTEGER, parent_session_id TEXT, source TEXT);
            CREATE TABLE messages (id INTEGER, session_id TEXT, role TEXT, content TEXT, timestamp REAL);
            INSERT INTO sessions VALUES ('root','test',1,2,'',1,NULL,'cli');
            INSERT INTO sessions VALUES ('child','test',3,4,'',1,'root','cli');
            INSERT INTO messages VALUES (1,'root','user','original evidence',1);
            INSERT INTO messages VALUES (2,'child','assistant','final answer',4);
        ''')
    history = load_session("child", include_ancestors=True)["messages"]
    runner = BrowseCompRunner(None, RunnerConfig(
        output_dir=tmp_path / "results", workspace_dir=tmp_path / "workspace",
        summary_path=tmp_path / "summary.jsonl", num_workers=1, max_retries=2,
        force=False, skip_statuses=set(), allowed_tools=set(), trajectory_dir=tmp_path / "export"))
    spec = RunSpec("q1", "q1", 1, DatasetItem("q1", "task", "answer", "text", 1))
    for attempt in (1, 2):
        runner._write_result(spec, {"attempt": attempt, "history": history, "status": "success"})
    for attempt in (1, 2):
        path = tmp_path / "export" / "iter1" / "q1" / f"attempt_{attempt}.jsonl"
        lines = path.read_text().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert [m["content"] for m in record["messages"]] == ["original evidence", "final answer"]
        assert record["attempt"] == attempt
