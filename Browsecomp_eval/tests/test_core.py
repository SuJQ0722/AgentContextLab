import json
import tempfile
import unittest
from pathlib import Path

from browsecomp_eval.dataset import DatasetItem, RunSpec, expand_repeats, load_dataset
from browsecomp_eval.hermes_client import build_query, has_delegation_tool
from browsecomp_eval.judge import (
    BrowseCompJudge,
    JudgeRunConfig,
    analyse_judgemodel_res,
    compute_metrics,
)
from browsecomp_eval.runner import BrowseCompRunner, RunnerConfig
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

    def test_build_query_omits_delegate_prompt_without_delegation_tool(self):
        query = build_query(self._spec(), enable_delegate=False)

        self.assertIn("You are running one browse-comparison evaluation task.", query)
        self.assertIn("Return the final answer clearly.", query)
        self.assertNotIn("delegate_task", query)
        self.assertNotIn("parallelize independent research subtasks", query)

    def test_build_query_includes_delegate_prompt_when_delegation_tool_enabled(self):
        query = build_query(self._spec(), enable_delegate=True)

        self.assertIn("delegate_task", query)
        self.assertIn("parallelize independent research subtasks", query)

    def test_has_delegation_tool_only_for_delegation_whitelist(self):
        self.assertFalse(has_delegation_tool(["web", "browser", "file"]))
        self.assertTrue(has_delegation_tool(["web", "delegation"]))

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
                skip_statuses={"success", "policy_violation"},
                allowed_tools={"web_search"},
            )
            runner = BrowseCompRunner(DummyClient(), config)
            stats = runner.run(runs)
            self.assertEqual(stats["success"], 2)
            self.assertEqual(len(list((out / "conv").rglob("*.json"))), 2)
            self.assertEqual(len((out / "summary.jsonl").read_text(encoding="utf-8").splitlines()), 2)

            stats = runner.run(runs)
            self.assertEqual(stats["skipped"], 2)

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
