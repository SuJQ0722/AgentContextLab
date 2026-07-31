from types import SimpleNamespace

from agent.session_storage import (
    get_repo_runtime_root,
    get_session_log_path,
    get_sessions_root,
    get_state_db_path,
    sync_agent_session_storage,
)


def test_sessions_root_groups_by_model_and_task_env(monkeypatch, tmp_path):
    base = tmp_path / "sessions"
    monkeypatch.setenv("HERMES_SESSION_STORAGE_ROOT", str(base))
    monkeypatch.setenv("HERMES_SESSION_MODEL", "claude-opus-4-8-thinking")
    monkeypatch.setenv("HERMES_SESSION_TASK_TYPE", "simple_search_2")

    expected_root = base / "claude-opus-4-8-thinking" / "simple_search_2"
    assert get_sessions_root() == expected_root
    assert (
        get_session_log_path("abc123", "primary")
        == expected_root / "main" / "session_abc123.json"
    )
    assert (
        get_session_log_path("abc123", "subagent")
        == expected_root / "subagents" / "session_abc123.json"
    )
    assert get_repo_runtime_root() == tmp_path
    assert get_state_db_path() == tmp_path / "state.db"


def test_default_sessions_root_uses_hermes_home(monkeypatch, tmp_path):
    hermes_home = tmp_path / ".hermes"
    monkeypatch.delenv("HERMES_SESSION_STORAGE_ROOT", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_SESSION_MODEL", "claude-opus-4-8-thinking")
    monkeypatch.setenv("HERMES_SESSION_TASK_NAME", "simple_deepresearch")

    expected_root = (
        hermes_home
        / "sessions"
        / "claude-opus-4-8-thinking"
        / "simple_deepresearch"
    )
    assert get_repo_runtime_root() == hermes_home
    assert get_state_db_path() == hermes_home / "state.db"
    assert get_sessions_root() == expected_root
    assert (
        get_session_log_path("abc123", "primary")
        == expected_root / "main" / "session_abc123.json"
    )
    assert (
        get_session_log_path("abc123", "subagent")
        == expected_root / "subagents" / "session_abc123.json"
    )


def test_sessions_root_can_group_by_current_model_argument(monkeypatch, tmp_path):
    base = tmp_path / "sessions"
    monkeypatch.setenv("HERMES_SESSION_STORAGE_ROOT", str(base))
    monkeypatch.delenv("HERMES_SESSION_MODEL", raising=False)
    monkeypatch.delenv("HERMES_SESSION_SAVE_NAME", raising=False)
    monkeypatch.setenv("HERMES_SESSION_TASK_NAME", "simple_deepresearch")

    expected_root = base / "claude-opus-4-8-thinking" / "simple_deepresearch"
    assert (
        get_sessions_root(model_name="claude-opus-4-8-thinking")
        == expected_root
    )


def test_sessions_root_groups_by_model_dataset_and_task_env(monkeypatch, tmp_path):
    base = tmp_path / "sessions"
    monkeypatch.setenv("HERMES_SESSION_STORAGE_ROOT", str(base))
    monkeypatch.setenv("HERMES_SESSION_MODEL", "claude-opus-4-8-thinking")
    monkeypatch.setenv("HERMES_SESSION_DATASET", "simple_search_2")
    monkeypatch.setenv("HERMES_SESSION_TASK_ID", "task_001")

    expected_root = base / "claude-opus-4-8-thinking" / "simple_search_2" / "task_001"
    assert get_sessions_root() == expected_root
    assert (
        get_session_log_path("abc123", "primary")
        == expected_root / "main" / "session_abc123.json"
    )
    assert (
        get_session_log_path("abc123", "subagent")
        == expected_root / "subagents" / "session_abc123.json"
    )


def test_sessions_root_keeps_legacy_runtime_override_shape(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("HERMES_SESSION_STORAGE_ROOT", str(runtime_root))
    monkeypatch.setenv("HERMES_SESSION_MODEL", "model-a")
    monkeypatch.setenv("HERMES_SESSION_TASK_TYPE", "task-a")

    assert get_sessions_root() == runtime_root / "sessions" / "model-a" / "task-a"


def test_sessions_root_sanitizes_model_and_task_segments(monkeypatch, tmp_path):
    base = tmp_path / "sessions"
    monkeypatch.setenv("HERMES_SESSION_STORAGE_ROOT", str(base))
    monkeypatch.setenv("HERMES_SESSION_MODEL", "../claude/opus 4")
    monkeypatch.setenv("HERMES_SESSION_DATASET", "simple/search:2")
    monkeypatch.setenv("HERMES_SESSION_TASK_NAME", "../case:001")

    root = get_sessions_root()
    assert root == base / "claude_opus_4" / "simple_search_2" / "case_001"
    assert ".." not in root.relative_to(base).parts


def test_sync_agent_session_storage_sets_namespace_log_dir(monkeypatch, tmp_path):
    base = tmp_path / "sessions"
    monkeypatch.setenv("HERMES_SESSION_STORAGE_ROOT", str(base))
    monkeypatch.setenv("HERMES_SESSION_MODEL", "model-a")
    agent = SimpleNamespace(
        session_id="sid-1",
        session_kind="subagent",
        sessions_root_dir=get_sessions_root(),
    )

    sync_agent_session_storage(agent)

    assert agent.logs_dir == base / "model-a" / "subagents"
    assert agent.session_log_file == agent.logs_dir / "session_sid-1.json"
    assert agent.logs_dir.exists()
