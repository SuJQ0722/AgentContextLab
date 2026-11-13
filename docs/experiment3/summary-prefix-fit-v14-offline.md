# Summary prefix fitting: offline proposal, 2026-11-13

This is a new, **offline-only** calibration helper, not a change to the frozen
V13 continuation queue. It makes no model requests and does not authorize
another trajectory for exhausted jobs. Original generation and calibration
costs remain charged to their original attempts.

`scripts/summary_prefix_fit_v14.py` reads archived generation responses and
joins them to provider-measured calibration requests by call ID and exact
summary text. Only stop-finished, strict JSON summaries accepted by the existing
parser are candidates. It never reads reference answers or adds original
history, padding, repeated text, or invented facts to a summary.

For an existing oversized summary, the proposed deterministic search takes
successively shorter **exact prefixes** at Unicode-safe whitespace/punctuation
or CJK boundaries. Native images, request template, visual target, and the ±2%
acceptance interval must remain fixed. An eventual integration would need at
most ten separately metered provider measurements. Unknown usage stops the
search without retry. Token monotonicity is only a candidate-selection
heuristic: acceptance requires an actual measured token count in the interval.
An oversized full summary does not prove a valid shorter prefix exists.

The current zero-API replay at `/tmp/summary-prefix-fit-v14-audit.json` found:

| Dataset / question-repeat | Target | Existing measured summary prompt counts | Offline classification |
|---|---:|---|---|
| BC q004 r01 | 7035 | 5540, 4968, 4928 | All valid candidates below target |
| BC q004 r02 | 6060 | 4496, 4966, 4437 | All valid candidates below target |
| BC q007 r03 | 5497 | 4391, 3920, 4837 | All valid candidates below target |
| MMBC q008 r01 | 5912 | 4578, 5523, 4972, 3767 | All valid candidates below target |
| MMBC q007 r03 | 6240 | 6505, 6051, 6500, 5830 | Oversized candidate exists; no shorter match measured |
| MMBC q002 r02 | 5505 | 4559, 6529, 5197, 5697 | Oversized candidate exists; no shorter match measured |
| MMBC q003 r01 | 5942 | 4837, 6372, 6580 | Oversized candidate exists; no shorter match measured |

Four undersized cases cannot be fixed by truncation. They would require a
separately authorized new generation protocol and quota; this helper leaves
them blocked. The three oversized cases are possible future calibration work,
not recovered experimental results.

At the associated V13 queue snapshot, 32 text arms covered 19 target groups;
13 groups had both summary and window jobs. Seven summaries had failed budget
matching, 16 arms were running, and 9 remained pending. There were **zero
completed valid two-text groups**, eight still potentially completable, and
four of those overlapped the nine formal visual extra-attempt candidates:
BC q004 r03; MMBC q002 r03, q003 r02, q008 r02. These are prospective counts,
not accuracy denominators. No formal extra visual attempt was launched by this
work, and no new complete three-arm result is claimed.

Validation: `python -m unittest discover -s tests -p test_summary_prefix_fit_v14.py -v`
passes four tests covering exact-prefix preservation, undershoot rejection,
unknown-usage halt, and Unicode boundaries. Reproduce a source audit using
`python scripts/summary_prefix_fit_v14.py --attempt PATH --out /tmp/audit.json`;
repeat `--attempt` for additional completed attempts.
