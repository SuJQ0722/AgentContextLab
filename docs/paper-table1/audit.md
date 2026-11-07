# Table 1 candidate: archived four-compression-method success cohort

Offline reconstruction; no new inference or judging. BC-EN No Compression 59.836% exactly matches the reviewer’s 59.8% fingerprint. The full paper mapping remains unverified: the reported overall 69.0% is not reproduced. Do not relabel this as confirmed Table 1.

The fixed cohort comes from `_gemini_4way_success_ids.csv`: Discard, Summary, Sliding Window, and VERA all succeeded. No Compression was not part of this selection. This outcome-dependent cohort favors the compression methods and is a limitation of the original selection, not a fair prespecified full-benchmark estimate.

| Benchmark | Method | N | Scored | Legacy pooled % | Legacy repeat mean ± std % | Unknown upper % |
|---|---|---:|---:|---:|---:|---:|
| bc | No Compression | 244 | 203 | 59.836 | 59.775 ± 1.669 | 76.639 |
| bc | Discard | 244 | 244 | 71.311 | 71.537 ± 4.935 | 71.311 |
| bc | Sliding Window | 244 | 244 | 73.770 | 73.843 ± 1.710 | 73.770 |
| bc | Summarize | 244 | 244 | 71.721 | 71.695 ± 2.603 | 71.721 |
| bc | VERA | 244 | 244 | 75.820 | 75.985 ± 4.089 | 75.820 |
| bc-zh | No Compression | 700 | 689 | 79.000 | 78.991 ± 1.314 | 80.571 |
| bc-zh | Discard | 700 | 700 | 82.571 | 82.565 ± 1.187 | 82.571 |
| bc-zh | Sliding Window | 700 | 700 | 79.571 | 79.575 ± 1.199 | 79.571 |
| bc-zh | Summarize | 700 | 700 | 81.000 | 80.991 ± 2.143 | 81.000 |
| bc-zh | VERA | 700 | 700 | 82.286 | 82.276 ± 2.250 | 82.286 |
| xbench | No Compression | 277 | 275 | 71.841 | 71.844 ± 2.821 | 72.563 |
| xbench | Discard | 277 | 277 | 70.758 | 70.757 ± 1.102 | 70.758 |
| xbench | Sliding Window | 277 | 277 | 69.675 | 69.670 ± 2.940 | 69.675 |
| xbench | Summarize | 277 | 277 | 70.758 | 70.757 ± 1.102 | 70.758 |
| xbench | VERA | 277 | 277 | 67.870 | 67.871 ± 1.634 | 67.870 |
| seal0 | No Compression | 308 | 302 | 56.169 | 56.159 ± 1.416 | 58.117 |
| seal0 | Discard | 308 | 308 | 56.494 | 56.530 ± 4.847 | 56.494 |
| seal0 | Sliding Window | 308 | 308 | 54.545 | 54.544 ± 2.462 | 54.545 |
| seal0 | Summarize | 308 | 308 | 56.494 | 56.498 ± 2.060 | 56.494 |
| seal0 | VERA | 308 | 308 | 53.247 | 53.243 ± 1.111 | 53.247 |

Repeat means use the original per-repeat denominators, which differ. Their std mixes random-run variation with cohort composition. This is not a balanced same-question avg@3 estimate.

Legacy reconstruction counts absent/unscored outcomes as zero only to reproduce the old table, not as newly established incorrect answers. BC No Compression has 41 absent records out of 244; neither summary.jsonl nor judge_summary.jsonl contains those 41. They cannot be assigned a failure cause or a true zero score from available evidence. Unknown lower/upper bounds are supplied.

Paired tests retain the fixed cohort, then require matching question ID, repeat and exact question content hash plus two observed scores. No five-method complete-case intersection is imposed. Deltas are averaged within question and then across independent question clusters; bootstrap uses 10,000 question-cluster resamples, and paired sign flips use 10,000 draws, with Holm correction over 16 comparisons. These conditional observed-pair estimates have a different estimand from legacy pooled accuracy and do not repair the original outcome-based cohort selection.

BC Discard source is `preds_archive/bc/gemini-3.5-flash-thinking-discard`; the other canonical `preds_archive/gemini35_flash_discard` run is a different run and must not be substituted. See `summary.csv` for exact groups and `membership.csv` for per-row paths/hashes.

Archive No Compression BC-ZH=79.0%, XBench=71.841%, SEAL-0=56.169%; combined trajectory-weighted=70.046%, four-benchmark macro=66.711%. Neither reproduces overall69.0%. Locate the submitted table/aggregation definition before replacing paper numbers.
