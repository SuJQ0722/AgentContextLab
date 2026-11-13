# Formal controlled comparison: V14 review plan

**No paid controlled trajectory is authorized by preparation alone.** The new
entry requires a separate authorization bound to the exact plan SHA and job
IDs, with `attempts_per_slot: 1`. Old V13 dispatch has stopped; its in-flight
trajectories drain without another timeout attempt.

The smallest complete formal comparison plan covers 14 fixed question-repeat
groups and at most 42 arms (visual, summary plus native images, and window plus
native images). It is not a 100×3 benchmark and does not cover AgenticDataBench.

| Benchmark | Existing real visual target, pinned | Must establish a new visual target | Maximum arms |
|---|---:|---:|---:|
| BrowseComp-v3 | 2 groups | 3 groups | 15 |
| MultiModalBrowseComp | 7 groups | 2 groups | 27 |

The five groups lacking targets are BC q008 repeats 1–3 and MMBC q007 repeats
1–2. Their visual arm must actually return provider input usage and pass native
identity and final-wire checks before its text arms become runnable. There is
no estimated or fabricated target. The first valid target is immutable and is
selected independently of final answer accuracy. The old target-publication
ordering bug is fixed in the new adapter: publication happens **after** bounded
and wire metadata have been attached.

The nine pinned groups replay the original V8 representation and encoded image
bytes, order and detail; both calibration and first actual visual continuation
must be within ±2% of the old measured target. Native evidence remains exact.
V8 presentation is retained: 1024×1536 base pages, font 16, base scale 0.75,
declared visual fit scales, recent text-page retention under ten total images,
native images last, inline transport and a 32 MiB body ceiling. This is not the
new seven-page RQ3 protocol. Dropped older rendered pages remain explicitly
documented; no native image is discarded.

Summary fitting is a new scientific variant. The first request targets 1.35×
the estimated remaining text budget (capped at 6500 requested tokens), requests
thinking disabled, and has the same 8192 output ceiling. Up to four substantive
summary generations are allowed. An oversized valid summary is shortened only
by taking exact Unicode-safe prefixes, with **at most ten additional actual
provider calibration SDK invocations per arm**, not ten per generation. No padding,
original-history insertion, answer access or invented text is allowed.
Unknown measurement stops; an undersized set cannot be expanded by truncation.
The four-generation cap also counts SDK invocations. Existing four-route HTTP
error failover is retained; physical HTTP attempts can exceed SDK calls and
must be counted from the raw transport ledger. All generation/calibration costs
are recorded separately from continuation.
The actual first continuation must still meet the target ±2%; group spread
must independently be ≤5%. Matching is not guaranteed.

Every new trajectory gets 500 turns and 3600 seconds, one launch only. No
timeout retry or unknown-claim reset is supported. Two CCI containers (one per
benchmark), each capped at 16 native workers, are sufficient for this initial
42-arm upper bound. New launches stop by **2026-11-14 17:20:06 UTC**, leaving
one hour for the final trajectory before the overall 24-hour deadline. A
controller exception drains already launched children within their original
deadline rather than abandoning them.

The new operational sidecar raises write timeout from 45 to 300 seconds and
the per-HTTP wall ceiling from 300 to 630 seconds, bounded by the remaining
3600-second trajectory deadline. It retains the prior four-route explicit HTTP
error failover. “No timeout retry” here means no second trajectory after its
one-hour budget expires; it does not silently remove the user's existing
HTTP error-routing policy. Frozen old configs are not edited.

Before authorization, reconcile the draining V13 queue: preserve any newly
completed valid arm and do not launch the same slot concurrently. Old complete
comparisons stay in their original protocol table. If an old successful
summary is reused, its older fitting algorithm must be labeled; it cannot be
silently pooled as a uniform V14 group. Calibration-only completions never
become formal accuracy observations.

The broader original 60-group design has 40 available native-image prefixes
(BC 25, MMBC 15). Three BC prefixes contain 12–14 original images, exceeding
the unchanged ten-image limit; they cannot run without changing the protocol.
Twenty groups lack eligible original prefixes (including originally imageless
MMBC questions). They must not be replaced with easier questions. Among the
remaining 37 groups, three already have complete matched old comparisons,
leaving a maximum 34-group supplemental design, not automatically authorized
by this 14-group review plan.

Preparation and zero-model checks:

```bash
python scripts/controlled_single_pass_v14.py --prepare
hermes-agent/.venv/bin/python scripts/controlled_single_pass_v14.py --offline-preflight
python -m unittest discover -s tests -p test_controlled_engine_v14.py -v
python -m unittest discover -s tests -p test_controlled_single_pass_v14.py -v
```

Tests: `test_controlled_engine_v14.py` exercises real localhost HTTP/SDK
generation, overshoot, deterministic fitting and actual continuation while
checking unchanged native bytes. `test_controlled_single_pass_v14.py` verifies
post-annotation target publication, immutability, and the authorization gate.
The generic fitter has four additional tests in `test_summary_prefix_fit_v14.py`.
Offline render artifacts live under the independent campaign's
`offline-preflight/`; they do not establish a provider token budget.

The independent pending-only scorer is `scripts/judge_controlled_single_pass_v14.py`
(`--watch --live --concurrency 2`, only after prediction authorization). It
binds source/result/control/target hashes and private gold, excludes calibration,
and reports three-arm groups only after all three are scored and pass native,
prefix and measured-budget matching. Missing grades remain NA. Per-purpose SDK
usage separates compaction/calibration from continuation; a distinct deduplicated
physical-route view captures extra attempts. These overlapping accounting views
must never be added together. The scorer was prepared offline and not launched.
