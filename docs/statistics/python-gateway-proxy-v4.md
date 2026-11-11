# Python gateway proxy diagnosis and V4 repair

Two authorized live diagnostic calls used the exact same 5,280,272-byte request (SHA256 `f87293ab665a36249d326d486e75b8a66f95e740809bf6bfe67a422528555e3e`), ten separate original images, and `deepseek-v4.1-flash-1017/huoshan/huoshan`. Each made one HTTP model attempt with no retry. Both returned HTTP200, 7,213 input tokens, 56 output tokens, 7,269 total tokens, and the same 2/3 reading checks. These are transport diagnostics, not benchmark accuracy observations.

| Current-window path | Client POST body-send phase | End-to-end client time | Cached input | Non-cache input |
|---|---:|---:|---:|---:|
| Explicit configured proxy, first | 0.00499 s | 103.30 s | 0 | 7,213 |
| Direct, second | 239.74 s | 247.93 s | 7,168 | 45 |

The proxy also produced a separate 0.00153-second empty CONNECT-body phase. That tunnel handshake is not a model-body upload. The earlier historical direct call took 74.21 seconds to send and 79.51 seconds end to end; it is not a contemporaneous control. The two new calls were sequential, not randomized repeated trials, and their cache states differed. They support a significant path-dependent client transmission problem; they do not isolate all network/TLS/gateway causes or establish fleet-wide speedup. A proxy accepting bytes quickly does not prove that the model server has received them.

Source inspection found that the Hermes V3 worker explicitly added the TokenHub hostname to `NO_PROXY`, while DSH installed its configured proxy dispatcher without adding that hostname to the bypass list. The proxy endpoint observed in the shared environment is `http://10.120.0.246:7890`. HTTPcore body-send trace encloses stream iteration and socket writes, with response-header waiting measured separately; client trace/logging overhead remains inside wall measurements.

The independent `visual_transport_runtime_v4.py` requires an explicit gateway proxy and creates a dedicated HTTPX proxy client with `trust_env=False`. It ignores accidental harness bypass settings only for the approved model endpoint. Web tools retain their original clients. Existing four-route policy, successful-route affinity, ten-image retention, pixel bytes, 64KiB writes, model/context/output budgets and outer trial deadline remain unchanged.

Proxy buffering shifts some waiting from local writes into response-header waiting. V4 therefore replaces the static read timeout with the remaining per-request wall budget. A targeted socket watchdog covers header and response-body consumption until `response.close`: the bound is the smaller of the existing 300-second HTTP wall budget and the remaining worker deadline. It is cancelled on successful consumption or send failure. Connection reuse is disabled for this dedicated pool, avoiding a watchdog closing a socket belonging to a later request. These transport policy changes are explicit in the returned runtime metadata and `gateway-proxy-v4.jsonl`; no provider-internal latency is inferred. CONNECT traces are recorded separately from model upload traces.

Eight local tests cover actual HTTP proxy routing despite `NO_PROXY=*`, route/body preservation and 64KiB chunks, slow headers, slow response body, successful cancellation, immediate send-failure cancellation, CONNECT-phase exclusion, invalid proxy settings, unaffected tool requests, late socket arrival and expired clean EOF. No model call is made by these tests.

Evidence:

- `outputs/preflight/python-gateway-proxy-v1/result.json`, `response.bin`, `response.json`, `transport-phases-v3.jsonl`: new proxy call and raw usage.
- `outputs/preflight/python-gateway-proxy-v1/direct-current/result.json` and sibling response/trace files: contemporaneous direct call.
- `outputs/preflight/python-gateway-proxy-v1/comparison.json`: frozen request identity and historical reference.
- `scripts/diagnose_python_gateway_proxy_v1.py`: single-attempt probe; the started marker prohibits implicit replay.

No frozen V5 execution source was modified. Production recovery deployment and matched canary evaluation are separate orchestration steps.
