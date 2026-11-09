# Controlled v5 transport repair — reviewed offline, paid validation pending

The two retained BCV3 summary failures expose `APIConnectionError`, but their saved SDK archives do not contain the exception cause chain. The first failed a text-only summary-generation call after8.10s; the second failed the first actual continuation after17.95s, with14 unchanged native images totaling3,753,083bytes. Earlier calls using those same images succeeded. Neither failure establishes an image-size limit or a provider429. Their native logs show attempt1/3 followed by `BudgetInfeasible` at the v4 sticky guard, rather than a recovered second request.

The frozen v4 source, its two results, all unknown costs, and its selected-attempt ledger are unchanged. No third paid trajectory has been run. The following independent files are ready for review:

- `controlled_native_worker_v5.py`: network/provider exceptions propagate to the existing Hermes retry mechanism. Budget, image/template integrity, auxiliary-request caps and local instrumentation failures remain fail-closed. A provider connection failure is not itself labeled a scientific budget violation.
- `controlled_transport_v5.py`: records SDK/HTTP/stream exception types, cause-chain types, errno, safe error categories and stack frame locations. It records request fingerprints, byte counts, status and selected diagnostic response identifiers, without freeform exception bodies, authorization headers, or traceback locals. It does not retry requests.
- `capture_multimodal_prefix_v5.py`: keeps the same native loop, model, five tools, source images, output budget and retry settings. It records transport lineage. Default gateway bypass is unchanged; a separately declared `transport_override={"mode":"known_proxy","url":"http://10.120.0.246:7890"}` can select the previously tested proxy, but that override has not been used for a new paid request.

Successful auxiliary responses are cached **within the same worker** by exact semantic request fingerprint and logical summary slot. A native retry can reuse a completed calibration/summary response without another API call. Failed requests remain in the accounting. The total physical summary-call cap is still4, including failures. There is no new retry loop. The original Hermes configuration has3 outer API attempts and at most one primary-client recovery cycle. Its stream helper separately retains its original default2 stream retries; do not describe6 as a universal upper bound for every type of streaming failure. The persistent *pre-header APIConnectionError* fixture below terminates after exactly6 actual requests:3 outer attempts, then3 after the single primary rebuild. SDK retries remain0.

A failed stream no longer unconditionally invokes budget validation in `finally`, which formerly turned missing usage into a sticky scientific failure. The next fully received continuation must have known provider prompt usage within the unchanged2% visual-target band and16,384 ceiling. Earlier unknown requests remain explicitly counted. An observed budget violation on a failed stream still stops immediately. The initial request template must remain identical: if Hermes preserves a partial plain-text response and changes subsequent history, that changed template cannot silently pass the paired-budget gate. Native safe retry of an unfinished tool call is supported; no tool has executed before that incomplete call is retried.

A successful continuation cannot be labeled completed without its actual control gate. Runtime source hashes and spec/config/prefix hashes are saved in `runtime-maintenance-v5.json`. This is a distinct runtime maintenance version, not a claim that the old implementation behaved this way.

Zero-paid validation:

```sh
python -m unittest discover -s tests -p test_controlled_transport_v5.py -v
python scripts/check_controlled_transport_v5.py
# Optional explicit prerequisite fixture:
python scripts/check_controlled_transport_v5.py --reference PATH_TO_COMPLETED_ZERO_PAID_V4_FIXTURE
```

The check auto-discovers a completed local v4 fixture or creates that prerequisite through localhost only; it no longer depends on a fixed timestamp directory. It runs the real Hermes loop with registered web/image tools, final HTTP image checks and a real localhost web-search result followed by another agent request:

1. A summary connection closes before headers, and a subsequent agent SSE stream closes mid-tool-call. Native recovery completes;7 physical requests are retained,2 with unknown usage. The two successful calibration requests are not repeated, and the initial failed/retried agent HTTP payloads match.
2. Persistent pre-header disconnection makes exactly6 agent requests, then terminates as provider failure with no scientific `fatal_error` manufactured.
3. A returned actual prompt of17,000 tokens triggers the original budget stop after exactly1 agent request.

The final successful fixture artifact, including runtime source hashes, is `outputs/preflight/controlled-transport-v5-1794203502848374360/result.json`. A separate earlier plain-text partial-stream fixture correctly failed the changed-template guard; it is retained as negative evidence rather than described as recovered. Three focused tests additionally verify secret-free cause serialization, cycle bounds and fingerprints that change when scientific inputs change.

`controlled_native_worker_v5.py` defaults to a dry run. Only `--offline-fixture` with loopback enforcement can execute without `--live`. A further real single-case run requires the user's exception to the already-consumed one-rerun limit, an independent output attempt and an explicit selected-attempt amendment; it must not overwrite either retained failure or silently change the existing queue.
