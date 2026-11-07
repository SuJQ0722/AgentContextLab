# Vision routing audit: rendered canvases are not necessarily transmitted images

Read-only audit of existing frozen runs on 2026-11-07. No implementation was changed and no evaluation was rerun for this audit. A completed agent trajectory is not evidence that rendered visual memory reached the main model.

## Confirmed Hermes main-request problem

Core job `hermes/visual/q_003_r01` recorded one successful PDF rendering (three images) and a compression event at `09:58:41.203164 UTC`. The subsequent main-model SDK request with call ID `f4458a45-5be0-446a-a359-2954bcca7fea` contains **zero image_url parts**. All nine message contents are strings. The user message contains three textual replacements stating that the attached image could not be analyzed because of a connection error, followed by the original visual-memory instructions.

Evidence directory:
`outputs/campaigns/bc100-r3-all-strategies/jobs/hermes/visual/q_003_r01/attempts/attempt_001/native/metrics/`

- `render.jsonl`: three rendered images, render time7.629967s.
- `compression.jsonl`: compression event and no exact post-token budget validation.
- `requests-responses.jsonl.gz`: `type=request`, the call ID above; zero actual SDK image parts and caption-error replacement text.
- `calls.jsonl`: first subsequent main request reports4378 prompt tokens; eight subsequent agent calls include seven tool-call finishes and a final stop.
- Parent attempt `result.json`: completed, final answer803 characters. This completion must **not** be reported as successful visual-memory use.

A second core example, `hermes/visual/q_008_r01`, has the same zero-image main-request condition after compression: call ID `17169e22-f097-491d-87c4-ff37875b295a`. The subsequent [coverage audit](visual-integrity-audit.md) confirms this condition for all 18 observed compressed core attempts and 83 RQ3 attempts; one additional compressed RQ3 attempt has no subsequent request observed. Attempts without logged compression remain a separate category.

## Confirmed RQ3 problem

RQ3 job `hermes/scale_0700/q_001_r01` records two valid compression events and old-image artifacts. Its first subsequent request containing image-analysis replacement text has call ID `501c9f67-a4ed-4f24-83f3-dacb572e2e2f`; it contains **zero image_url parts** and two failed-caption descriptions. One reports an auxiliary401 Invalid token error and the other a connection error. The actual credential value is not reproduced here.

Evidence:
`outputs/campaigns/rq3-deepseek-bc100-r3/jobs/hermes/scale_0700/q_001_r01/attempts/attempt_001/native/metrics/requests-responses.jsonl.gz`

Successful rendering, PNG pixel-equivalence fixtures, successful termination and correct token arithmetic do not repair this model-input problem. These affected runs cannot establish a native-canvas resolution/accuracy comparison. Preserve their costs and failure evidence; any corrected implementation requires a new explicit version rather than silently changing the frozen run.

## DSH: what is and is not proven

Core `dsh/visual/q_001_r01` has one valid compaction, four persisted native image attachments, one subsequent tool-result event, and three subsequent agent API attempts (including a timeout) before a final stop/completed result with1112 answer characters. Its first subsequent API call ID is `dc44dd65-cd39-414a-a21c-9cc78a388cfe`; normalized provider input including cached tokens is11158. The native post-compression token-meter estimate was8389, so that estimate is not the actual provider prompt count. The renderer's separate heuristic image-token estimate47171 is also not provider usage.

Evidence root:
`outputs/campaigns/bc100-r3-all-strategies/jobs/dsh/visual/q_001_r01/attempts/attempt_001/`

- `native/visual_native/q_001/workspace/metrics/compression.jsonl`: compaction ID `41cd563e-bcc7-4016-939c-9a606b79a985`, post estimate8389, budget16384, validtrue.
- Same metrics directory `render.jsonl`: four images, font16, configured history_scale1, render9.977157s.
- Same directory `calls.jsonl`: subsequent measured usage/finish records.
- Native zstd session with ID `session-a7a42458-931f-4b9a-8310-02b3bb83d60d`: `compaction/summary`, `user/message`, `compaction/end` at09:55:44.451 UTC, native image attachments and subsequent tool result.

**No DSH serialized outgoing HTTP body is saved in these artifacts.** The current observer in `plugins/dsh-evaluation/index.mjs` records call starts, normalized usage and finishes, but not `llm/stream` message options or the serialized provider request. Therefore this audit confirms native image state in the DSH session and successful continuation, but cannot certify the final HTTP image payload or exclude an unlogged conversion step. It found no equivalent caption-error evidence in the inspected DSH session; absence of such evidence is not a wire-level proof.

No answer correctness was judged in this audit. Do not pool invalid Hermes visual-routing results with valid visual evidence or infer model visual comprehension from final-answer existence.
