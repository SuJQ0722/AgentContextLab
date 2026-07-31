"""Tests for execute_code's opt-in host-filesystem denial policy."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from tools.code_execution_tool import (
    DEFAULT_NETWORK_ACCESS,
    DEFAULT_TOOL_ACCESS,
    DEFAULT_FILESYSTEM_ACCESS,
    FILESYSTEM_ACCESS_MODES,
    NETWORK_ACCESS_MODES,
    TOOL_ACCESS_MODES,
    _build_filesystem_isolation_command,
    _get_filesystem_access,
    _get_network_access,
    _get_tool_access,
    build_execute_code_schema,
    execute_code,
)


def test_filesystem_access_defaults_to_full():
    with patch("tools.code_execution_tool._load_config", return_value={}):
        assert DEFAULT_FILESYSTEM_ACCESS == "full"
        assert _get_filesystem_access() == "full"


def test_filesystem_access_none_is_configurable():
    with patch(
        "tools.code_execution_tool._load_config",
        return_value={"filesystem_access": " NoNe "},
    ):
        assert _get_filesystem_access() == "none"


def test_invalid_filesystem_access_falls_back_to_full():
    with patch(
        "tools.code_execution_tool._load_config",
        return_value={"filesystem_access": "bogus"},
    ):
        assert set(FILESYSTEM_ACCESS_MODES) == {"full", "none"}
        assert _get_filesystem_access() == "full"


def test_network_and_tool_access_are_configurable():
    with patch(
        "tools.code_execution_tool._load_config",
        return_value={"network_access": "none", "tool_access": "none"},
    ):
        assert set(NETWORK_ACCESS_MODES) == {"full", "none"}
        assert set(TOOL_ACCESS_MODES) == {"full", "none"}
        assert DEFAULT_NETWORK_ACCESS == "full"
        assert DEFAULT_TOOL_ACCESS == "full"
        assert _get_network_access() == "none"
        assert _get_tool_access() == "none"


def test_none_schema_tells_model_filesystem_is_disabled():
    description = build_execute_code_schema(
        enabled_sandbox_tools={"web_search", "web_extract"},
        mode="strict",
        filesystem_access="none",
    )["description"]
    assert "Local host filesystem access is disabled" in description
    assert "filesystem writes fail" in description


def test_pure_compute_schema_hides_rpc_tools_and_describes_network_denial():
    description = build_execute_code_schema(
        enabled_sandbox_tools={"web_search", "web_extract"},
        mode="strict",
        filesystem_access="none",
        network_access="none",
        tool_access="none",
    )["description"]
    assert "pure-compute sandbox" in description
    assert "outbound networking" in description
    assert "No Hermes tools are available" in description
    assert "web_search(query" not in description


def test_isolation_command_uses_namespaces_but_shares_loopback(tmp_path):
    command = _build_filesystem_isolation_command(str(tmp_path))
    assert "--user" in command
    assert "--mount" in command
    assert "--pid" in command
    assert "--net" not in command
    assert command[-2:] == ["--staging", str(tmp_path)]


def test_pure_compute_isolation_adds_network_namespace(tmp_path):
    command = _build_filesystem_isolation_command(
        str(tmp_path),
        network_access="none",
    )
    assert "--net" in command


def test_none_policy_fails_closed_on_remote_backend(monkeypatch):
    monkeypatch.setenv("TERMINAL_ENV", "ssh")
    with patch(
        "tools.code_execution_tool._load_config",
        return_value={"filesystem_access": "none"},
    ), patch(
        "tools.terminal_tool._get_env_config",
        return_value={"env_type": "ssh"},
    ):
        result = json.loads(execute_code("print(1)", task_id="remote-denied"))
    assert result["status"] == "error"
    assert "cannot guarantee host-file isolation" in result["error"]


def test_network_none_requires_filesystem_and_tool_denial(monkeypatch):
    monkeypatch.setenv("TERMINAL_ENV", "local")
    with patch(
        "tools.terminal_tool._get_env_config",
        return_value={"env_type": "local"},
    ), patch(
        "tools.code_execution_tool._load_config",
        return_value={
            "filesystem_access": "full",
            "network_access": "none",
            "tool_access": "none",
        },
    ):
        result = json.loads(execute_code("print(1)"))
    assert result["status"] == "error"
    assert "requires code_execution.filesystem_access=none" in result["error"]

    with patch(
        "tools.terminal_tool._get_env_config",
        return_value={"env_type": "local"},
    ), patch(
        "tools.code_execution_tool._load_config",
        return_value={
            "filesystem_access": "none",
            "network_access": "none",
            "tool_access": "full",
        },
    ):
        result = json.loads(execute_code("print(1)"))
    assert result["status"] == "error"
    assert "requires code_execution.tool_access=none" in result["error"]


@pytest.mark.skipif(
    os.environ.get("HERMES_RUN_FS_ISOLATION_E2E") != "1",
    reason="requires host user/mount namespace support",
)
def test_none_policy_e2e_blocks_host_files_and_keeps_compute_rpc(tmp_path, monkeypatch):
    monkeypatch.setenv("TERMINAL_ENV", "local")
    secret = tmp_path / "host-secret.txt"
    secret.write_text("must-not-be-readable", encoding="utf-8")
    host_write_target = tmp_path / "must-not-be-created.txt"

    config = {
        "mode": "strict",
        "filesystem_access": "none",
        "timeout": 30,
        "max_tool_calls": 10,
    }
    rpc_result = json.dumps({"data": {"web": [{"title": "ok"}]}})

    def run(code: str) -> dict:
        with patch("tools.code_execution_tool._load_config", return_value=config), patch(
            "tools.approval.check_execute_code_guard",
            return_value={"approved": True},
        ), patch("model_tools.handle_function_call", return_value=rpc_result):
            return json.loads(
                execute_code(
                    code,
                    task_id="filesystem-e2e",
                    enabled_tools=["web_search", "web_extract"],
                )
            )

    compute = run("print(sum(range(10)))")
    assert compute["status"] == "success"
    assert compute["output"].strip() == "45"

    rpc = run("from hermes_tools import web_search; print(web_search('x'))")
    assert rpc["status"] == "success"
    assert rpc["tool_calls_made"] == 1
    assert "'title': 'ok'" in rpc["output"]

    read = run(f"print(open({str(secret)!r}).read())")
    assert read["status"] == "error"
    assert "FileNotFoundError" in read["error"]

    pathlib_read = run(
        f"from pathlib import Path; print(Path({str(secret)!r}).read_text())"
    )
    assert pathlib_read["status"] == "error"
    assert "FileNotFoundError" in pathlib_read["error"]

    write = run(f"open({str(host_write_target)!r}, 'w').write('bad')")
    assert write["status"] == "error"
    assert "PermissionError" in write["error"]
    assert not host_write_target.exists()

    os_write = run(
        "import os; "
        "os.close(os.open('/tmp/os-escape', os.O_WRONLY | os.O_CREAT, 0o600))"
    )
    assert os_write["status"] == "error"
    assert "PermissionError" in os_write["error"]

    # seccomp is inherited across execve/subprocess. This target lives only in
    # the private tmpfs, so even a future regression cannot touch host data.
    child_write = run(
        "import subprocess; "
        "subprocess.run(['/usr/bin/python3', '-c', "
        "\"open('/tmp/child-escape', 'w').write('bad')\"], check=True)"
    )
    assert child_write["status"] == "error"
    assert "Permission denied" in child_write["error"]


@pytest.mark.skipif(
    os.environ.get("HERMES_RUN_FS_ISOLATION_E2E") != "1",
    reason="requires host user/mount/network namespace support",
)
def test_pure_compute_e2e_denies_files_network_and_rpc(tmp_path, monkeypatch):
    monkeypatch.setenv("TERMINAL_ENV", "local")
    secret = tmp_path / "host-secret.txt"
    secret.write_text("must-not-be-readable", encoding="utf-8")
    config = {
        "mode": "strict",
        "filesystem_access": "none",
        "network_access": "none",
        "tool_access": "none",
        "timeout": 30,
        "max_tool_calls": 0,
    }

    def run(code: str) -> dict:
        with patch(
            "tools.code_execution_tool._load_config", return_value=config
        ), patch(
            "tools.approval.check_execute_code_guard",
            return_value={"approved": True},
        ):
            return json.loads(
                execute_code(
                    code,
                    task_id="pure-compute-e2e",
                    enabled_tools=["web_search", "web_extract"],
                )
            )

    compute = run("print(sum(i * i for i in range(10)))")
    assert compute["status"] == "success"
    assert compute["output"].strip() == "285"
    assert compute["tool_calls_made"] == 0

    read = run(f"print(open({str(secret)!r}).read())")
    assert read["status"] == "error"
    assert "FileNotFoundError" in read["error"]

    rpc = run("from hermes_tools import web_search; print(web_search('x'))")
    assert rpc["status"] == "error"
    assert "ImportError" in rpc["error"]

    network = run(
        "import socket; "
        "socket.create_connection(('1.1.1.1', 80), timeout=1)"
    )
    assert network["status"] == "error"
    assert any(
        text in network["error"]
        for text in ("Network is unreachable", "Temporary failure", "Name or service")
    )
