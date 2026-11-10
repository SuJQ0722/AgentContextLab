# Fixed-window five-arm diagnostic

This new queue uses the six unchanged windows in `bounded-window-probe-v1`: q004 development and q009 holdout, each early/middle/late. It does not replace or erase the earlier whole-history runs. Two source questions cannot support population inference. Original message indices, rounds, distances, and source byte offsets are preserved; these are observed positions rather than a causal forgetting intervention.

Run offline preparation with:

```bash
hermes-agent/.venv/bin/python scripts/run_bounded_window_five_arm_v1.py --prepare
```

After global capacity allocation, the authorized live command is:

```bash
hermes-agent/.venv/bin/python scripts/run_bounded_window_five_arm_v1.py --live
```

The process lock enforces one local worker. Each physical request has an immutable started record, request, wire ledger, raw response, parsed usage, and response. Restart resumes completed stages without repeating them. An interrupted request with no response stops rather than silently paying again. Completed transport/provider failures are retained without retry, and invalid prerequisites block dependent work. A `STOP` file in the new output root stops dispatch after the current window.

The five representations are exact text, canvas 1x/.75x/.5x, and a newly generated summary of the identical window. Rendering uses unchanged Hermes layout with bounded 1024×1536 pages, then one scale reduction; pages are individual images, with no vertical merge. Each image has a lossless WebP RGBA identity proof. All resolutions preserve the same normalized page cuts. The original window contains at most 512 UTF-8 bytes and 96 whitespace words.

For each window, one shared fact extraction and one summary generation precede five reconstruction calls, five ProbeQA calls, and five semantic grading calls: at most **102 physical calls** in total. Empty facts are retained, with QA and fact grading marked unavailable rather than replacing the window. All requests use the frozen DeepSeek route, temperature zero, thinking disabled, and at most 768 output tokens. Summaries target 40 words and reconstruction 100 words; overlong or length-truncated responses remain invalid. There are no automatic retries.

Probe prediction receives only question IDs/questions and its representation. Reference answers and quotes remain local or go to the separate grading stage. A single generated fact set is reused across all five arms. Reconstruction exact recovery, literal key-fact recall, exact QA matching, and semantic grading are distinct fields. Invalid or missing responses are excluded from observed-value denominators and retained explicitly as missing; a valid wrong answer is false. The semantic judge receives no arm label. Development and holdout aggregates are separate, and each available denominator is reported.

Every stage, including preprocessing and judging, retains raw provider usage and derived cached/non-cache input, output, and total tokens. Missing cache fields remain null. `client_http_seconds` measures observed client HTTP wall time; provider API time and dollar cost remain null without provider instrumentation/pricing. Offline render wall time is recorded separately. The diagnostic does not assert matched input token budgets.

The manifest freezes code and every prepared source/image artifact. Outputs are under `outputs/experiment6/bounded-window-five-arm-v1-release1`; `report.json` contains measured metrics, complete call accounting, denominators, and limitations. Old frozen artifacts remain read-only.

The release1 manifest references the original offline prepared image artifacts without modifying them. It freezes the final prediction wording, which distinguishes outer rendering chrome from message headers present in the actual source. Reuse is offline and validates all renderer dependencies and artifact hashes.
