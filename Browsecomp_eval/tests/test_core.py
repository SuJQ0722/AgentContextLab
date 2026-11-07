import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from browsecomp_eval.dataset import DatasetItem, RunSpec, expand_repeats, load_dataset
import browsecomp_eval.hermes_client as hermes_client_module
from browsecomp_eval.hermes_client import (
    HermesClient,
    HermesConfig,
    _compression_count_from_stats,
    _extract_fail_reason,
    _reached_round_limit,
    build_query,
    configured_web_backend_hosts,
    has_delegation_tool,
    merge_no_proxy,
    parse_context_accounting,
)
from browsecomp_eval.judge import (
    BrowseCompJudge,
    JudgeRunConfig,
    PredictionRecord,
    analyse_judgemodel_res,
    compute_metrics,
    format_record_label,
)
from browsecomp_eval.run import _resolve_provider, resolve_output_base
from browsecomp_eval.runner import BrowseCompRunner, RunnerConfig, format_run_label
from browsecomp_eval.session_reader import extract_final_assistant_message, text_from_content
from browsecomp_eval.whitelist import parse_csv, resolve_toolsets


class DummyClient:
    def run(self, spec, workspace_dir, attempt):
        workspace_dir.mkdir(parents=True, exist_ok=True)
        return {
            "question_id": spec.question_id,
            "repeat_index": spec.repeat_index,
            "run_id": spec.run_id,
            "question": spec.item.question,
            "answer": spec.item.answer,
            "type": spec.item.type,
            "status": "success",
            "error": "",
            "session_id": "dummy",
            "profile": "dummy-profile",
            "workspace_dir": str(workspace_dir),
            "tool_calls": {"web_search": 1},
            "duration_seconds": 0.1,
            "history": [],
        }


class DummyJudgeClient:
    def judge(self, record):
        return {
            "score": 1 if record.answer in record.pred else 0,
            "judge_reason": "dummy",
            "judge_raw_response": '{"reason":"dummy","score":1}',
            "judge_response": {"choices": [{"message": {"content": '{"reason":"dummy","score":1}'}}]},
        }


class CoreTests(unittest.TestCase):
    def _spec(self) -> RunSpec:
        item = DatasetItem(
            question_id="q_001",
            question="What is the answer?",
            answer="Paris",
            type="simple",
            source_line=1,
        )
        return RunSpec(question_id="q_001", run_id="q_001", repeat_index=1, item=item)

    def test_build_query_contains_task_and_question(self):
        query = build_query(self._spec(), enable_delegate=False)

        self.assertIn("You are running one browse-comparison evaluation task.", query)
        self.assertIn("What is the answer?", query)
        self.assertIn("Return the final answer clearly.", query)
        self.assertNotIn("delegate_task", query)

    def test_build_query_includes_images_when_present(self):
        item = DatasetItem(
            question_id="q_001",
            question="What is shown?",
            answer="Paris",
            type="visual",
            source_line=1,
            image=("https://example.test/a.png", "/tmp/b.jpg"),
        )
        query = build_query(RunSpec("q_001", "q_001", 1, item), enable_delegate=False)

        self.assertIn("Images:", query)
        self.assertIn("https://example.test/a.png", query)
        self.assertIn("/tmp/b.jpg", query)

    def test_build_query_includes_delegate_prompt_when_enabled(self):
        query = build_query(self._spec(), enable_delegate=True)

        self.assertIn("delegate_task", query)
        self.assertIn("parallelize independent research subtasks", query)

    def test_has_delegation_tool_only_for_delegation_whitelist(self):
        self.assertFalse(has_delegation_tool(["web", "browser", "file"]))
        self.assertTrue(has_delegation_tool(["web", "delegation"]))

    def test_content_filter_reason_is_extracted(self):
        reason = _extract_fail_reason(
            "⚠️  The model declined to respond to this request (safety refusal — not a Hermes/gateway failure).\n\n"
            'Model\'s explanation: call:default_api:web_search{query:"example"}\n\n'
            "Try rephrasing the request.\n",
            "",
            "",
        )

        self.assertIn("web_search", reason)
        self.assertIn("example", reason)

    def test_max_rounds_with_final_answer_is_success(self):
        spec = self._spec()
        client = HermesClient(
            HermesConfig(
                hermes_bin="hermes",
                api_key="test-key",
                base_url="https://example.test/v1",
                model="gemini-3.5-flash-thinking",
                provider="custom",
                save_name="save",
                dataset="data",
                max_rounds=2,
                timeout_seconds=120,
                toolsets=[],
                skills=[],
            )
        )
        client._setup_profile = lambda profile, workspace_dir, context_image_dir=None: None
        client._build_chat_command = lambda profile, query: ["hermes", "chat"]
        client._build_env = lambda spec, workspace_dir: {}

        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            hermes_client_module.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(["hermes", "chat"], 0, stdout="session_id: sid\n", stderr=""),
        ), mock.patch.object(hermes_client_module, "load_session") as load_session, mock.patch.object(
            hermes_client_module, "extract_final_assistant_message", return_value=("final answer", "")
        ), mock.patch.object(
            hermes_client_module, "extract_trace",
            return_value={"tool_calls": {}, "rounds": 2, "total_tokens_estimate": 0, "duration_seconds": 1.0},
        ), mock.patch.object(
            hermes_client_module, "load_child_sessions", return_value=[]
        ), mock.patch.object(
            hermes_client_module, "load_compression_snapshots", return_value=[]
        ), mock.patch.object(
            hermes_client_module, "load_token_usage",
            return_value={
                "input_tokens": 10,
                "output_tokens": 2,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "reasoning_tokens": 0,
                "api_call_count": 2,
                "total_tokens": 12,
                "cache_total_tokens": 0,
                "noncached_total_tokens": 12,
                "prompt_tokens_including_cache": 10,
                "total_tokens_including_cache": 12,
                "session_count": 1,
            },
        ), mock.patch.object(
            hermes_client_module, "read_profile_agent_log_tail", return_value=""
        ):
            load_session.return_value = {"messages": []}
            result = client.run(spec, Path(td), attempt=1)

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["round_limit_reached"])
        self.assertEqual(result["model_response"], "final answer")

    def test_progress_log_labels_include_iter(self):
        spec = self._spec()
        self.assertEqual(format_run_label(spec), "iter1/q_001")

        record = PredictionRecord(
            path=Path("conv/iter1/q_001.json"),
            question_id="q_001",
            run_id="q_001",
            repeat_index=1,
            question="What is the answer?",
            answer="Paris",
            pred="Paris",
            pred_status="success",
            type="simple",
            token_usage={},
            raw={},
        )
        self.assertEqual(format_record_label(record), "iter1/q_001")

    def test_token_usage_keeps_cache_out_of_headline_total(self):
        metrics = compute_metrics(
            [
                {
                    "question_id": "q_001",
                    "status": "judged",
                    "score": 1,
                    "type": "simple",
                    "token_usage": {
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "cache_read_tokens": 300,
                        "cache_write_tokens": 40,
                        "api_call_count": 2,
                    },
                }
            ]
        )

        totals = metrics["token_usage"]["total"]
        self.assertEqual(totals["total_tokens"], 120)
        self.assertEqual(totals["noncached_total_tokens"], 120)
        self.assertEqual(totals["cache_total_tokens"], 340)
        self.assertEqual(totals["prompt_tokens_including_cache"], 440)
        self.assertEqual(totals["total_tokens_including_cache"], 460)

    def test_context_tokens_only_include_successful_predictions(self):
        metrics = compute_metrics(
            [
                {
                    "question_id": "q_success",
                    "status": "judged",
                    "pred_status": "success",
                    "score": 1,
                    "type": "simple",
                    "compression_aware_tokens": 100,
                },
                {
                    "question_id": "q_failed",
                    "status": "judged",
                    "pred_status": "failed",
                    "score": 0,
                    "type": "simple",
                    "compression_aware_tokens": 900,
                },
            ]
        )

        context = metrics["context_tokens"]
        self.assertEqual(context["runs_with_usage"], 1)
        self.assertEqual(context["total_tokens"], 100)
        self.assertEqual(context["avg_tokens"], 100.0)
        self.assertEqual(metrics["tokens_distribution"]["values"], [100])

    def test_visual_compression_count_comes_from_stats_sidecar(self):
        self.assertEqual(_compression_count_from_stats({"compressions": 2}), 2)
        self.assertEqual(_compression_count_from_stats({"compressions": "3"}), 3)
        self.assertEqual(_compression_count_from_stats({}), 0)

    def test_context_accounting_counts_only_completed_compressions(self):
        log = """
API call #1: model=x provider=custom in=100 out=10 total=110
[ContextEngine] tokens=110 | strategy=discard | compressing...
[ContextEngine] compression done | strategy=discard | messages=3->2 | tokens=110->20
API call #2: model=x provider=custom in=40 out=5 total=45
[ContextEngine] tokens=45 | strategy=discard | compressing...
[ContextEngine] compression done | strategy=discard | messages=4->2 | tokens=45->20
API call #3: model=x provider=custom in=30 out=7 total=37
"""
        accounting = parse_context_accounting(log)

        self.assertEqual(accounting["compression_count"], 2)
        self.assertEqual(accounting["pre_compression_tokens_sum"], 155)
        self.assertEqual(accounting["final_prompt_tokens"], 30)
        self.assertEqual(accounting["final_response_tokens"], 7)
        self.assertEqual(accounting["effective_tokens"], 192)

    def test_context_accounting_counts_system_prompt_once(self):
        log = """
API call #1: model=x provider=custom in=100 out=10 total=110 system=20 latency=1.0s
[ContextEngine] compression done | strategy=summarize | messages=3->2 | tokens=100->25 | accounting_tokens=120 | system_tokens=20
API call #2: model=x provider=custom in=70 out=5 total=75 system=20 latency=1.0s
[ContextEngine] compression done | strategy=summarize | messages=4->2 | tokens=70->30 | accounting_tokens=80 | system_tokens=20
API call #3: model=x provider=custom in=50 out=7 total=57 system=20 latency=1.0s
"""
        accounting = parse_context_accounting(log)

        self.assertEqual(accounting["completed_context_segments"], [120, 80])
        self.assertEqual(accounting["terminal_active_context_segment_tokens"], 57)
        self.assertEqual(accounting["repeated_system_tokens_removed"], 40)
        self.assertEqual(accounting["effective_tokens"], 217)

    def test_configured_web_backend_hosts_are_added_to_no_proxy(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "config.yaml"
            config_path.write_text(
                """
web:
  local_web:
    search:
      url: 10.120.6.133
    fetch:
      fetch_server:
        base_url: http://10.120.0.246:8080
""",
                encoding="utf-8",
            )

            hosts = configured_web_backend_hosts(config_path)

        self.assertEqual(hosts, ["10.120.6.133", "10.120.0.246"])
        self.assertEqual(
            merge_no_proxy("localhost,10.120.6.133", hosts),
            "localhost,10.120.6.133,10.120.0.246",
        )

    def test_profile_visual_artifacts_use_context_image_dir(self):
        with tempfile.TemporaryDirectory() as td:
            context_root = Path(td) / "context_image"
            workspace = Path(td) / "workspace" / "iter1" / "q_001" / "attempt_1"
            client = HermesClient(
                HermesConfig(
                    hermes_bin="hermes",
                    api_key="test-key",
                    base_url="https://example.test/v1",
                    model="test-model",
                    provider="custom",
                    save_name="save",
                    dataset="data",
                    max_rounds=1,
                    timeout_seconds=120,
                    toolsets=[],
                    skills=[],
                    context_length=262144,
                    compression_threshold=32768,
                    context_engine="visual",
                    context_image_dir=context_root,
                )
            )
            calls = []
            client._copy_default_profile_config = lambda profile: None
            client._run_hermes = lambda args, check=True: calls.append(args)

            context_dir = client._context_image_dir(self._spec(), 1)
            client._setup_profile("profile-a", workspace, context_dir)

        expected = context_root / "iter1" / "q_001" / "attempt_1"
        self.assertEqual(context_dir, expected)
        self.assertIn(
            ["--profile", "profile-a", "config", "set", "context.strategy_config.save_dir", str(expected)],
            calls,
        )
        self.assertNotIn(
            ["--profile", "profile-a", "config", "set", "context.strategy_config.save_dir", str(workspace.parent)],
            calls,
        )

    def test_profile_context_engine_and_absolute_threshold_are_isolated(self):
        with tempfile.TemporaryDirectory() as td:
            client = HermesClient(
                HermesConfig(
                    hermes_bin="hermes",
                    api_key="test-key",
                    base_url="https://example.test/v1",
                    model="test-model",
                    provider="custom",
                    save_name="save",
                    dataset="data",
                    max_rounds=1,
                    timeout_seconds=120,
                    toolsets=[],
                    skills=[],
                    context_length=262144,
                    compression_threshold=32768,
                    context_engine="visual",
                )
            )
            calls = []
            client._copy_default_profile_config = lambda profile: None
            client._run_hermes = lambda args, check=True: calls.append(args)

            client._setup_profile("profile-a", Path(td))

        self.assertIn(["--profile", "profile-a", "config", "set", "context.engine", "visual"], calls)
        self.assertIn(["--profile", "profile-a", "config", "set", "compression.enabled", "true"], calls)
        self.assertIn(["--profile", "profile-a", "config", "set", "compression.threshold", "0.125"], calls)
        self.assertNotIn(["config", "set", "context.engine", "visual"], calls)

    def test_profile_context_engine_none_disables_compression(self):
        with tempfile.TemporaryDirectory() as td:
            client = HermesClient(
                HermesConfig(
                    hermes_bin="hermes",
                    api_key="test-key",
                    base_url="https://example.test/v1",
                    model="test-model",
                    provider="custom",
                    save_name="save",
                    dataset="data",
                    max_rounds=1,
                    timeout_seconds=120,
                    toolsets=[],
                    skills=[],
                    context_length=262144,
                    compression_threshold=32768,
                    context_engine="none",
                )
            )
            calls = []
            client._copy_default_profile_config = lambda profile: None
            client._run_hermes = lambda args, check=True: calls.append(args)

            client._setup_profile("profile-a", Path(td))

        self.assertIn(["--profile", "profile-a", "config", "set", "compression.enabled", "false"], calls)
        self.assertIn(["--profile", "profile-a", "config", "set", "context.engine", "compressor"], calls)
        self.assertNotIn(["--profile", "profile-a", "config", "set", "context.engine", "none"], calls)
        self.assertFalse(
            any(call[-2:] == ["compression.threshold", "0.125"] for call in calls),
            "CM=none should not leave profile compression enabled at the 32k threshold",
        )

    def test_load_dataset_and_expand_repeats(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "questions.jsonl"
            path.write_text(
                json.dumps({"question": "q1", "answer": "a1", "type": "t"}, ensure_ascii=False) + "\n"
                + json.dumps({"question": "q2", "answer": "a2", "type": "t"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            items = load_dataset(path)
            runs = expand_repeats(items, 2)
            self.assertEqual([item.question_id for item in items], ["q_001", "q_002"])
            self.assertEqual([run.run_id for run in runs], ["q_001", "q_001", "q_002", "q_002"])

    def test_save_name_with_benchmark_prefix_controls_output_layout(self):
        root = Path("/tmp/project")

        self.assertEqual(
            resolve_output_base("output/preds", "model-vis", "seal0", root),
            root / "output" / "preds" / "model-vis" / "seal0",
        )
        self.assertEqual(
            resolve_output_base("output/preds", "seal0/model-vis", "seal0", root),
            root / "output" / "preds" / "seal0" / "model-vis",
        )

    def test_explicit_provider_takes_precedence_over_model_name(self):
        self.assertEqual(_resolve_provider("custom", "gemini-3.5-flash-thinking"), "custom")
        self.assertEqual(_resolve_provider("", "google/gemini-2.5-flash"), "gemini")
        self.assertEqual(_resolve_provider("custom", "qwen3.5-72b"), "custom")
        self.assertEqual(_resolve_provider("openrouter", "gemini-3.5-flash-thinking"), "openrouter")

    def test_resolve_toolsets(self):
        allowed = resolve_toolsets(parse_csv("web,browser"))
        self.assertIn("web_search", allowed)
        self.assertIn("browser_navigate", allowed)

    def test_runner_writes_and_skips_success(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "questions.jsonl"
            data.write_text(
                json.dumps({"question": "q", "answer": "a", "type": "t"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            runs = expand_repeats(load_dataset(data), 2)
            out = Path(td) / "out"
            config = RunnerConfig(
                output_dir=out / "conv",
                workspace_dir=out / "workspace",
                summary_path=out / "summary.jsonl",
                num_workers=2,
                max_retries=1,
                force=False,
                skip_statuses={"success"},
                allowed_tools={"web_search"},
            )
            runner = BrowseCompRunner(DummyClient(), config)
            stats = runner.run(runs)
            self.assertEqual(stats["success"], 2)
            self.assertEqual(len(list((out / "conv").rglob("*.json"))), 2)
            self.assertEqual(len((out / "summary.jsonl").read_text(encoding="utf-8").splitlines()), 2)

            stats = runner.run(runs)
            self.assertEqual(stats["skipped"], 2)

    def test_runner_retries_existing_policy_violation_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            spec = self._spec()
            out = Path(td) / "out"
            existing = out / "conv" / "iter1" / "q_001.json"
            existing.parent.mkdir(parents=True, exist_ok=True)
            existing.write_text(
                json.dumps({"status": "policy_violation"}, ensure_ascii=False),
                encoding="utf-8",
            )
            config = RunnerConfig(
                output_dir=out / "conv",
                workspace_dir=out / "workspace",
                summary_path=out / "summary.jsonl",
                num_workers=1,
                max_retries=1,
                force=False,
                skip_statuses={"success"},
                allowed_tools={"web_search"},
            )
            stats = BrowseCompRunner(DummyClient(), config).run([spec])

            self.assertEqual(stats["pending"], 1)
            self.assertEqual(stats["success"], 1)

    def test_judge_response_parser(self):
        score = analyse_judgemodel_res('{"reason":"same","score":1}')
        self.assertEqual(score, 1.0)

        score = analyse_judgemodel_res('```json\n{"reason":"different","score":0}\n```')
        self.assertEqual(score, 0.0)

    def test_final_assistant_message_validation(self):
        self.assertEqual(
            text_from_content([{"text": " hello "}, {"content": {"value": "world"}}]),
            "hello\nworld",
        )

        text, error = extract_final_assistant_message(
            {"messages": [{"role": "assistant", "content": " final answer ", "finish_reason": "stop"}]}
        )
        self.assertEqual(text, "final answer")
        self.assertEqual(error, "")

        text, error = extract_final_assistant_message(
            {
                "messages": [
                    {"role": "assistant", "content": "thinking"},
                    {"role": "tool", "content": "{}"},
                ]
            }
        )
        self.assertEqual(text, "")
        self.assertIn("not assistant", error)

        text, error = extract_final_assistant_message(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": "<function=web_search><parameter=query>x</parameter>",
                        "finish_reason": "stop",
                    }
                ]
            }
        )
        self.assertEqual(text, "")
        self.assertIn("raw tool call", error)

    def test_round_limit_is_inclusive_and_configurable(self):
        self.assertFalse(_reached_round_limit(199, 200))
        self.assertTrue(_reached_round_limit(200, 200))
        self.assertTrue(_reached_round_limit(201, 200))
        self.assertFalse(_reached_round_limit(200, 0))

    def test_judge_writes_results_and_metrics(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conv = root / "conv"
            success_path = conv / "iter1" / "q_001.json"
            failed_path = conv / "iter1" / "q_002.json"
            success_path.parent.mkdir(parents=True, exist_ok=True)
            failed_path.parent.mkdir(parents=True, exist_ok=True)
            success_path.write_text(
                json.dumps(
                    {
                        "question_id": "q_001",
                        "run_id": "q_001",
                        "repeat_index": 1,
                        "question": "What is the answer?",
                        "answer": "Paris",
                        "model_response": "The answer is Paris.",
                        "status": "success",
                        "type": "simple",
                    }
                ),
                encoding="utf-8",
            )
            failed_path.write_text(
                json.dumps(
                    {
                        "question_id": "q_002",
                        "run_id": "q_002",
                        "repeat_index": 1,
                        "question": "What is the answer?",
                        "answer": "Rome",
                        "model_response": "API failed",
                        "status": "failed",
                        "type": "simple",
                    }
                ),
                encoding="utf-8",
            )

            judge = BrowseCompJudge(
                client=DummyJudgeClient(),
                config=JudgeRunConfig(
                    conv_dir=conv,
                    output_dir=root / "judge",
                    summary_path=root / "judge_summary.jsonl",
                    metrics_path=root / "judge_metrics.json",
                    num_workers=2,
                    force=False,
                    include_failed=False,
                ),
            )
            metrics = judge.run()
            self.assertEqual(metrics["prediction_total"], 2)
            self.assertEqual(metrics["scored"], 1)
            self.assertEqual(metrics["correct"], 1)
            self.assertEqual(metrics["accuracy"], 1.0)
            self.assertEqual(metrics["skipped_infer_failed"], 1)
            self.assertTrue((root / "judge" / "iter1" / "q_001.json").is_file())
            self.assertTrue((root / "judge" / "iter1" / "q_002.json").is_file())
            skipped = json.loads((root / "judge" / "iter1" / "q_002.json").read_text(encoding="utf-8"))
            self.assertIsNone(skipped["score"])

            recomputed = compute_metrics(
                [
                    json.loads(path.read_text(encoding="utf-8"))
                    for path in (root / "judge").rglob("*.json")
                ]
            )
            self.assertEqual(recomputed["accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
