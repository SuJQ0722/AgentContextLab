from __future__ import annotations

import json

from plugins import browsecomp_guard as guard


def _activate(monkeypatch) -> None:
    monkeypatch.setenv("BROWSE_COMP_RUN_ID", "q000064__r2")
    guard._quarantined_browser_sessions.clear()


def test_guard_is_inert_outside_browsecomp(monkeypatch):
    monkeypatch.delenv("BROWSE_COMP_RUN_ID", raising=False)
    assert guard._on_pre_tool_call(
        tool_name="web_search",
        args={"query": "BrowseComp answers"},
    ) is None


def test_pre_hook_blocks_observed_query_url_and_console_variants(monkeypatch):
    _activate(monkeypatch)
    attempts = [
        (
            "web_search",
            {"query": "FineVerify BrowseComp-Plus dataset answers"},
        ),
        (
            "web_extract",
            {
                "urls": [
                    "https://openaipublic.blob.core.windows.net/simple-evals/"
                    "browse_comp_test_set.csv"
                ]
            },
        ),
        (
            "browser_navigate",
            {
                "url": "https://huggingface.co/datasets/openai/"
                "BrowseComp%252DPlus"
            },
        ),
        (
            "browser_console",
            {
                "expression": "fetch('/demo/api/gallery/samples?dataset="
                "BrowseComp-Plus')"
            },
        ),
    ]
    for tool_name, args in attempts:
        blocked = guard._on_pre_tool_call(tool_name=tool_name, args=args)
        assert blocked and blocked["action"] == "block"

    # Simple JavaScript string construction must not bypass the marker.
    assert guard._on_pre_tool_call(
        tool_name="browser_console",
        args={"expression": "'Browse' + 'Comp'"},
    )


def test_pre_hook_blocks_related_benchmark_leak_variants(monkeypatch):
    _activate(monkeypatch)
    attempts = [
        (
            "web_search",
            {"query": "xbench_deepsearch ground truth answers"},
        ),
        (
            "web_search",
            {"query": "xds deepsearch answer key"},
        ),
        (
            "web_search",
            {"query": "seal-0 dataset answer key"},
        ),
        (
            "web_extract",
            {"urls": ["https://huggingface.co/datasets/vtllms/sealqa"]},
        ),
        (
            "browser_navigate",
            {"url": "https://huggingface.co/datasets/gaia-benchmark/GAIA"},
        ),
        (
            "browser_console",
            {"expression": "location.href = '/?dataset=GAIA%20benchmark'"},
        ),
    ]
    for tool_name, args in attempts:
        blocked = guard._on_pre_tool_call(tool_name=tool_name, args=args)
        assert blocked and blocked["action"] == "block"


def test_console_and_cdp_cannot_become_unfiltered_network_clients(monkeypatch):
    _activate(monkeypatch)
    assert guard._on_pre_tool_call(
        tool_name="browser_console",
        args={"expression": "fetch('/answer.json').then(r => r.text())"},
    )
    assert guard._on_pre_tool_call(
        tool_name="browser_cdp",
        args={"method": "Runtime.evaluate", "params": {"expression": "1 + 1"}},
    )
    assert guard._on_pre_tool_call(
        tool_name="browser_cdp",
        args={"method": "Page.navigate", "params": {"url": "https://example.com"}},
    )
    assert guard._on_pre_tool_call(
        tool_name="browser_cdp",
        args={"method": "Network.getResponseBody", "params": {"requestId": "1"}},
    )
    assert guard._on_pre_tool_call(
        tool_name="browser_console",
        args={"expression": "document.title"},
    ) is None
    assert guard._on_pre_tool_call(
        tool_name="browser_cdp",
        args={"method": "DOM.getDocument", "params": {}},
    ) is None


def test_execute_code_file_access_is_blocked_but_compute_is_allowed(monkeypatch):
    _activate(monkeypatch)
    attempts = [
        "print(open('/tmp/secret.txt').read())",
        "from pathlib import Path\nprint(Path('/tmp/secret.txt').read_text())",
        "import os\nprint(os.listdir('/tmp'))",
        "import subprocess\nsubprocess.run(['cat', '/tmp/secret.txt'])",
        "from hermes_tools import read_file\nprint(read_file('/tmp/secret.txt'))",
        "import hermes_tools\nprint(hermes_tools.search_files('/tmp', 'secret'))",
    ]
    for code in attempts:
        blocked = guard._on_pre_tool_call(
            tool_name="execute_code",
            args={"code": code},
        )
        assert blocked and blocked["action"] == "block"

    assert guard._on_pre_tool_call(
        tool_name="execute_code",
        args={"code": "print(sum(i * i for i in range(10)))"},
    ) is None


def test_path_guard_preserves_unrelated_hosting_content(monkeypatch):
    _activate(monkeypatch)
    assert guard._on_pre_tool_call(
        tool_name="browser_navigate",
        args={"url": "https://github.com/python/cpython/blob/main/README.rst"},
    ) is None
    assert guard._on_pre_tool_call(
        tool_name="web_search",
        args={"query": "Gaia spacecraft ESA mission timeline"},
    ) is None


def test_huggingface_is_always_blocked_when_active(monkeypatch):
    _activate(monkeypatch)
    for tool_name, args in [
        (
            "web_extract",
            {"urls": ["https://huggingface.co/datasets/squad"]},
        ),
        (
            "browser_navigate",
            {"url": "https://hf.co/datasets/squad"},
        ),
        (
            "web_search",
            {"query": "Hugging Face datasets squad"},
        ),
    ]:
        blocked = guard._on_pre_tool_call(tool_name=tool_name, args=args)
        assert blocked and blocked["action"] == "block"


def test_search_results_remove_leaks_but_keep_safe_results(monkeypatch):
    _activate(monkeypatch)
    raw = json.dumps(
        {
            "success": True,
            "data": {
                "web": [
                    {
                        "title": "Leaked benchmark data",
                        "url": "https://github.com/texttron/BrowseComp-Plus",
                        "description": "answers",
                    },
                    {
                        "title": "Independent source",
                        "url": "https://example.com/research",
                        "description": "ordinary evidence",
                    },
                ]
            },
        }
    )
    transformed = guard._on_transform_tool_result(
        tool_name="web_search",
        result=raw,
    )
    parsed = json.loads(transformed)
    assert parsed["success"] is True
    assert parsed["data"]["web"] == [
        {
            "title": "Independent source",
            "url": "https://example.com/research",
            "description": "ordinary evidence",
        }
    ]


def test_search_results_remove_related_benchmark_leaks(monkeypatch):
    _activate(monkeypatch)
    raw = json.dumps(
        {
            "success": True,
            "data": {
                "web": [
                    {
                        "title": "XBench DeepSearch predictions",
                        "url": "https://example.com/xbench_deepsearch.jsonl",
                        "description": "answer rows",
                    },
                    {
                        "title": "SealQA dataset",
                        "url": "https://huggingface.co/datasets/vtllms/sealqa",
                        "description": "contains seal-0 answers",
                    },
                    {
                        "title": "SQuAD dataset",
                        "url": "https://huggingface.co/datasets/squad",
                        "description": "unrelated Hugging Face content",
                    },
                    {
                        "title": "XDS answer key",
                        "url": "https://example.com/xds.jsonl",
                        "description": "deepsearch benchmark answers",
                    },
                    {
                        "title": "Independent source",
                        "url": "https://example.com/research",
                        "description": "ordinary evidence",
                    },
                ]
            },
        }
    )
    transformed = guard._on_transform_tool_result(
        tool_name="web_search",
        result=raw,
    )
    parsed = json.loads(transformed)
    assert parsed["success"] is True
    assert parsed["data"]["web"] == [
        {
            "title": "Independent source",
            "url": "https://example.com/research",
            "description": "ordinary evidence",
        }
    ]


def test_all_blocked_or_unstructured_web_results_fail(monkeypatch):
    _activate(monkeypatch)
    only_leak = json.dumps(
        {
            "success": True,
            "documents": [
                {
                    "url": "https://huggingface.co/datasets/openai/browsecomp",
                    "content": "ground truth",
                }
            ],
        }
    )
    for result in (only_leak, "wrapped BrowseComp benchmark output"):
        transformed = guard._on_transform_tool_result(
            tool_name="web_extract",
            result=result,
        )
        parsed = json.loads(transformed)
        assert parsed["success"] is False


def test_browser_result_quarantine_hides_followup_page_tools(monkeypatch):
    _activate(monkeypatch)
    monkeypatch.setattr(guard, "_current_browser_url", lambda _task_id: "")
    leaked_page = json.dumps(
        {
            "success": True,
            "url": "https://huggingface.co/datasets/openai/browsecomp",
            "snapshot": "answer rows",
        }
    )
    transformed = guard._on_transform_tool_result(
        tool_name="browser_click",
        result=leaked_page,
        session_id="session-1",
        task_id="task-1",
    )
    assert json.loads(transformed)["success"] is False

    blocked = guard._on_pre_tool_call(
        tool_name="browser_snapshot",
        args={},
        session_id="session-1",
        task_id="task-1",
    )
    assert blocked and blocked["action"] == "block"

    # Navigation to an unrelated page is the explicit recovery path.
    assert guard._on_pre_tool_call(
        tool_name="browser_navigate",
        args={"url": "https://example.com"},
        session_id="session-1",
        task_id="task-1",
    ) is None
    assert guard._on_transform_tool_result(
        tool_name="browser_navigate",
        result='{"success": true, "url": "https://example.com"}',
        session_id="session-1",
        task_id="task-1",
    ) is None
    assert guard._on_pre_tool_call(
        tool_name="browser_snapshot",
        args={},
        session_id="session-1",
        task_id="task-1",
    ) is None


def test_browser_click_checks_final_url_even_when_result_omits_it(monkeypatch):
    _activate(monkeypatch)
    monkeypatch.setattr(
        guard,
        "_current_browser_url",
        lambda _task_id: "https://github.com/texttron/BrowseComp-Plus/runs",
    )
    transformed = guard._on_transform_tool_result(
        tool_name="browser_click",
        result='{"success": true, "clicked": "@e5"}',
        session_id="session-click",
        task_id="task-click",
    )
    assert json.loads(transformed)["success"] is False
    assert guard._on_pre_tool_call(
        tool_name="browser_snapshot",
        args={},
        session_id="session-click",
        task_id="task-click",
    )


def test_real_plugin_loader_blocks_before_dispatch(monkeypatch, tmp_path):
    import yaml

    import hermes_cli.plugins as plugins_mod
    import model_tools
    from tools.registry import registry

    _activate(monkeypatch)
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text(
            yaml.safe_dump({"plugins": {"enabled": ["browsecomp_guard"]}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    plugins_mod._plugin_manager = plugins_mod.PluginManager()
    plugins_mod.discover_plugins()

    dispatched = []
    monkeypatch.setattr(
        registry,
        "dispatch",
        lambda *args, **kwargs: dispatched.append((args, kwargs)) or '{"success": true}',
    )
    monkeypatch.setattr(model_tools, "_READ_SEARCH_TOOLS", frozenset())

    result = model_tools.handle_function_call(
        "web_search",
        {"query": "BrowseComp ground truth answers"},
        task_id="q000064__r2",
        session_id="session-real",
    )
    assert "anti-cheat guard" in json.loads(result)["error"]
    assert dispatched == []
