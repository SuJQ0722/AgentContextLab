# One-hour attempts with five timeout retries

User-authorized operational recovery, 2026-11-11. The active source version includes the SSE completion, pre-SDK last-ten retention, image encoding cache, and single retry-owner repairs.

Each question-repeat gets one initial attempt and at most five additional attempts, each with a 3600-second end-to-end deadline. Attempts for one question run sequentially within one slot. Individual HTTP attempts retain the existing 300-second limit and four approved DeepSeek routes. Normal completion, including a wrong answer, ends recovery; ordinary execution errors, explicit interruption, and unconfirmed process cleanup do not trigger automatic retries. Worker route-deadline ledger events can explicitly establish an attempt timeout. A full six-attempt timeout chain can consume about six hours plus cleanup.

The outer question slot remains occupied across all retries. Every attempt has an immutable directory, native traces, raw usage, render metrics and HTTP route records. Resumption never overwrites a started attempt without terminal proof. The aggregate prediction comes from the final execution; retries are not extra seeds. Accounting expands every child attempt and does not count the outer aggregate again. Missing usage is unknown, including attempts with no SDK or HTTP ledger; only explicit `api_calls: 0` proves zero calls.

The mixed nonvisual queue has one controller identity and one physical pool of sixteen slots across both harnesses and all text strategies. VERA/visual experiment cells have separate sixteen-slot containers. There is no global 128-worker cap. AFS, private CPU image, 8 vCPU and 32 GiB per CCI remain the approved settings.

All historical results are preserved. Recovery includes pending jobs and execution failures in already-finished experiments, with externally verified termination for user-stopped jobs. Any completed historical execution is retained independently of its grade. New controlled visual calibration tasks are explicitly excluded from accuracy/seed replacement: their purpose is to supply a measured target for text controls with the same prefix and native evidence. Summary/window arms wait for a valid target; an exhausted visual task without a valid target blocks its dependents without a model call.

Controlled V8 places original native images after the text representation in every arm. It admits only the most recent rendered text pages that fit alongside all native images within ten total images, recording removed page ordinals. Native evidence is never silently removed. Prefixes with more than ten native images or missing frozen evidence are separately blocked, not scored as valid comparisons. Information-loss V8 instead tiles the complete source without overlap or pixel loss, maintaining at most ten independently transmitted tiles at each scale.

Configuration: `configs/experiment.json:visual_inline_one_hour_retry_v8`.

Primary frozen root: `outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v8-one-hour-retry5`.

Information-loss root: `outputs/experiment6/inline-retry5-v8`.

Old-run termination evidence: `outputs/cloud-runtime/retry5-stop-20261111`.

No new Gemini calls are included unless the earlier no-Gemini instruction is explicitly revised. Historical Gemini results remain available. AgenticDataBench is excluded as requested.

For ETA, the shared sixteen-slot nonvisual queue is the likely bottleneck. Its 1,198 original BC/MMBC recovery jobs have a historical-duration work proxy of 35.51 hours at sixteen slots after capping each prior duration at one hour. This is an estimate for the first pass, not a deadline: it excludes controlled arms and new timeout retries, and historical successful-run medians are biased for this failure-heavy cohort. First-pass all-timeout bound is about 75 hours; six all-timeout attempts about 450 hours. Replace this proxy with measured new-version throughput once available.
