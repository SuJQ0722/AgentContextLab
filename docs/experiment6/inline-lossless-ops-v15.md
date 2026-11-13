# V15: lossless inline transport for never-started V14 stages

The first V14 CCI stopped new dispatch and drained after repeated large-body
`WriteTimeout` errors. This was **not** an oversized single-image or >10-image
failure: observed requests contained 7–8 ordered high-detail images. At 1×,
pages were approximately 1015×2048; at 0.75×, approximately 762×1536. Request
bodies were about 9.1–13.9 MB. The actual write timeout was 90 seconds, and
failures generally occurred around 90.15 seconds. Some large-image calls did
succeed, so these observations do not establish a universal provider limit.

This independent operational overlay keeps the model, prompts, original PNG
files and SHA, pixel dimensions, scale, page ordering and detail unchanged.
It replaces only inline wire encoding with lossless WebP. Every encoded image
is decoded and compared against the original RGBA pixels before use; both byte
SHAs and a pixel SHA are retained. There is no URL or image-hosting service.

Zero-model evidence: q009/0.75's eight images shrink from 10,424,494 PNG bytes
to 4,069,436 WebP bytes (61.0% reduction), with identical RGBA pixels. Encoding
took 2.45 seconds. This reduces the corresponding base64 image body from about
13.9 MB to 5.43 MB without downsampling or cropping. Future-use preparation
verified 129 images. Encoding cost is separate from model/API latency.

The original CCI exited normally and was reaped before freezing the old stage
ledger. **All 25 old stages remain consumed**, including successes, failures
and unknown acceptance. Matching uses `(case, method, scientific stage)` before
encoding or calculating a new payload fingerprint; a changed WebP fingerprint
cannot create another attempt for an old failed request. Previously completed
responses, including truncated reconstruction, are reused unchanged. The
remaining allowance is **at most 65 new requests**, within the original combined
90-call V14 allowance. This is not a new retry allowance.

Only future requests use write timeout 300 seconds; read timeout remains 300.
Each HTTP call runs in an isolated child with a 630-second hard wall timeout.
If it fails to finish, it is terminated, acceptance and usage remain unknown,
and no retry is made. No new request starts unless at least 630 seconds remain
before **2026-11-14 18:20:06 UTC**. Four condition workers are supported on the
single replacement CCI. The scientific scoring remains V14's uniform span-ID
judge; V15 is a separately recorded transport version, not a new quality metric.

Artifacts: `outputs/experiment6/single-pass-inline-lossless-v15/plan.json`
contains parent-plan/retirement SHA, old stage ledger, original/new image hashes,
pixel proofs, timeout settings and remaining request ceiling. `reused-v14/`
records reuse; `calls/` contains only new attempts. Old V14 raw usage must be
added separately to new usage, not counted twice or silently omitted.

```bash
python scripts/network_entry_v13.py --target scripts/info_loss_lossless_ops_v15.py \
  --root outputs/experiment6/single-pass-inline-lossless-v15 --live --concurrency 4
```

Four offline tests pass, including a real localhost HTTP upload through the
same HTTPX path: lossless pixels/high detail, write timeout 300, completed-stage
reuse without a second send, and rejection of an old failure/unknown before
encoding or model invocation. No paid diagnostic request was used.

The independent read-only `scripts/report_info_loss_single_pass_v15.py --watch`
generates `analysis/report.md`, cost coverage, and resolution/age figures.
Resolution comparisons use common holdout facts across all five methods;
if none are available the figure explicitly states that instead of drawing
invented points. Age plots retain observed per-method denominators in CSV and
make no causal decay claim. q004 development observations are excluded.
