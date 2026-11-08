# Repaired BC-100 campaign and resume

The user approved revision `3ba562f10` and requested resume/start on 2026-11-08.
The approval record is `outputs/authorization/resume-v3.json`. The previous global
pause marker is archived there; legacy campaign STOP files remain in place.

The new root is `outputs/campaigns/bc100-r3-hermes-parity-v3`. Its full frozen
plan contains 100 questions × 3 repeats × 5 methods × 2 harnesses = 3,000 trials.
Both harnesses use `deepseek-v4.1-flash-1017/huoshan/huoshan`. A controller's
selection and launch limit do not change that scientific plan.

Historical core outcomes (212 completed, 112 timeout, 16 failed, 16 interrupted)
and their incurred usage remain in the original directory. They are not counted
as completed v3 trials because the shared policy, visual evidence path, web
tools and accounting changed. Existing historical analysis remains available.

## Initial dispatch and cloud deployment

The first dispatch consists of two local visual trials, one per harness, using
the same plan and immutable attempt directories intended for the cloud run.
The user subsequently confirmed that the current machine should also run the study.
A persistent local pool now advances pending jobs across both harnesses and all
five methods, ramping toward 32 workers while monitoring memory and process
counts. Cloud workers are not yet active. Actual activity is reported in
`monitor/status.json`; do not confuse configured pool capacity with measured
in-flight requests.

```bash
python scripts/run_bc_campaign_v3.py --harness hermes --strategy visual --concurrency 1 --limit 1 --resume --live
python scripts/run_bc_campaign_v3.py --harness dsh --strategy visual --concurrency 1 --limit 1 --resume --live
python scripts/monitor_bc_campaign_v3.py --watch
# Fresh web readiness on each future host, before starting its controller:
python scripts/preflight_bc_v3_web.py --root outputs/campaigns/bc100-r3-hermes-parity-v3
```

Each future SCO instance owns one harness/method selection and a controller
pool of 32. Atomic job claims prevent a cloud controller from repeating a trial
already claimed on the initial machine. Each harness/method also has 32 shared
slots. A local process ID is never used to establish a remote worker's liveness.
Cross-instance AFS behavior and each instance's web access must be validated
before cloud dispatch; localhost Reader readiness is host-specific and expires.

SCO launch is authorized. It is currently blocked on the missing account profile
and resource discovery. Requested choices are `afs_agents`, private image
`ccr-zuhu2026 / sjq-dev-cpu`, and the current AFS project directory. No tag or
cloud resource ID is inferred from these display names.

## Resume and measurement

`--resume` dispatches pending jobs. Matching terminal results are skipped.
Permanent claims and exclusive worker-start records prevent duplicate launches;
unknown/interrupted attempts are retained for inspection and never silently
resent. Controller SIGTERM/STOP stops new dispatch and drains active trials.
Stopping a trial itself records interruption and preserves its artifacts.

Only the five reviewed web/image tools are model-visible. Neither file-reading
tools, terminal tools, nor automatic workspace instructions are enabled. DSH
reads the frozen campaign cohort; the model receives the question and admitted
images, not the answer field.

The read-only v3 monitor uses raw provider counters, not normalized DSH cache-zero
defaults. It distinguishes request starts, in-flight/unknown calls, terminal
usage, cached/non-cache/output tokens, compression and rendering, and web-cache
observations. Judge costs remain separate. Missing counters and actual USD are
unknown; client elapsed time is not provider-internal latency. A completed
trajectory is not an accuracy measurement until graded.

Implementation details and exact ownership rules: [scheduler and resume](bc-campaign-v3-resume.md).

The first real Hermes trial demonstrated native output-limit recovery: after an
8,192-token reasoning-only length stop, its next request used 16,384 max_tokens,
then returned to 8,192. This was native behavior within the same trial, not a
manual retry or configuration edit. The configured output value must not be
reported as a hard per-request cap for both harnesses. Evidence is preserved in
`monitor/hermes-native-output-budget.json`; charge actual returned usage.
