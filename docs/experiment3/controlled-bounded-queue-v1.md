# Independent bounded native continuation queue

The new queue retains the original 60 fixed prefixes / 180 arms from the two existing datasets. Forty original prefixes are available and source-validated: 25 BrowseComp-v3 and 15 MMBrowseComp, yielding 120 eligible arms. The other 20 groups remain unavailable; no replacement questions are selected. This is **not coverage of all three proposed multimodal benchmarks**, nor a full benchmark accuracy estimate.

All three methods start a fresh attempt under the bounded page / lossless WebP protocol and exact `deepseek-v4.1-flash-1017/huoshan/huoshan` route. The new visual attempt establishes the actual provider token target. Summary and window then target ±2% of that measurement, retaining identical original native payloads/detail. An independent report requires the realized three-arm spread to be ≤5%, identical prefix/native identities, and all three control gates. Continuation accuracy is separate from that control check: a valid intervention whose later answer is wrong remains a valid intervention. No old visual targets or scores are used to choose eligible groups.

Preparation and validation are offline:

```sh
python scripts/prepare_controlled_bounded_v1.py --prepare
python scripts/run_controlled_bounded_v1.py --pilot-only
```

The first paid stage is explicitly limited to the two original pilot groups (six sequential arms), using one local worker reserved by the main scheduler:

```sh
python -u scripts/run_controlled_bounded_v1.py --live --pilot-only
```

After checking both pilot group gates in `outputs/experiment3/controlled-native-bounded-v1/status.json`, the main scheduler can resume the remaining eligible groups with:

```sh
python -u scripts/run_controlled_bounded_v1.py --live
```

Concurrency remains hard-limited to **one** worker. Increasing it requires a separately reviewed scheduling change; this coordinator cannot consume the other global reservations. Existing attempts are never automatically replayed. An interrupted controller adopts an identity-matched supervisor/child; a durable dispatch without a live process is reported `interrupted_unknown_no_replay`. Missing prefixes and failed visual gates remain explicitly visible. Source/config/spec hashes are checked before every paid dispatch; original evidence and results remain untouched.

Each attempt preserves worker output separately from supervisor `trial-status.json`, including wall timeout and exit status. `status.json` records per-purpose provider usage, cache/non-cache/input/output/total subtotals and missing fields, failed/inflight usage, web-cache evidence, per-arm rendering and encoding time, and actual fitted scales. SDK time is not provider internal latency. Original spending remains in its original source root and is referenced without claiming that an overlapping old ledger has been reaggregated; combined old/new dollar totals remain unknown. Calibration warms the cache and is included in cost, so its cache rate is not an untreated production cache estimate.
