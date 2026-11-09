# Fixed recovery of the 15 interrupted 0.7 trajectories

This is an additional paid prediction attempt, not a pre-native repair. The stopped predecessor had 15 native trajectories with observed SDK request starts but no terminal result. The exact set is bound to the validated SUSPENDED/Deleted namespace evidence and the original claim/spec hashes. Previously completed jobs and other failures are excluded.

`run_rq3_scale0700_paid_retry1.py --prepare` creates `outputs/campaigns/rq3-deepseek-bc100-r3-scale0700-paid-retry1/paid-retry-authorization.json`. All model, question, repeat, scale, configuration and deadline values remain identical. The full 2,100-job plan structure is retained for the frozen scientific validator, but only the named 15 jobs are executable; 2,085 placeholders are unauthorized. Each job permits one additional attempt. Existing new claims or unknown outcomes cannot be replayed.

The retry controller shares the successor's `cloud-scale-ops5/slots/scale_0700` directory with the 219 pending predictions. The combined ceiling is **16**, not 16+15. It uses an independently loaded copy of the unchanged slot-accounting module to count the parent's active and unknown reservations. A full parent pool makes the retry queue wait. Successful acquisition still passes the original native trial validator; `run_rq3_paid_retry1_trial.py` adds a strict 15-job and shared-slot guard before invoking the unchanged scientific trial. Errors stop dispatch and drain tracked children; no automatic prediction or grading retry is added.

Live entry after preparation:

```bash
python scripts/run_rq3_scale0700_paid_retry1.py --concurrency 15 --resume --live
python scripts/judge_rq3_scale0700_paid_retry1.py --concurrency 1 --watch --live
python scripts/report_rq3_final_seven_v2.py --watch
```

The isolated judge preserves the existing DeepSeek SFB prompt, parsing, request-marker deduplication and raw usage. Its namespace is `outputs/grading/rq3-scale0700-paid-retry1`, and no gold answer is added to prediction inputs.

The new report in `outputs/grading/rq3-final-seven-v2` always selects each of the 15 new attempts, regardless of its score or success. The other 2,085 selections—including the two pre-native recoveries—remain unchanged. There are still exactly 100 questions × three repeats × seven final resolutions. Existing v1 reports remain available. Final avg@3, standard deviation and paired inference still require complete outcomes under the documented missing-data rule.

`paid-interruption-cumulative-cost.json` retains both original and retry prediction usage, separates retry judgment usage, and exposes unreturned requests and missing original wall time. Unknown gateway prices and unreported charges stay unknown. Recovered accuracy uses conditional additional resources and must not be described as a uniformly single-attempt budget result.

Six offline tests cover exact scope and science preservation, full-parent-pool blocking and shared slot reuse, actual native guard validation, unauthorized placeholder rejection, judgment scope, fixed 15-row report replacement and unknown original costs, and one-spawn natural drain. Tests make no paid model calls.
