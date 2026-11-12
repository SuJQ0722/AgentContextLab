> 历史冻结快照：2026-11-12 10:43 UTC+8。不是当前V12运行状态；本次发布未重算该历史表，也未重新核对价格。最新代次结果见 [当前结果](current-generations.md)，总入口见 [README](README.md)。

# DeepSeek physical-attempt accounting

Fresh read: 2026-11-12T02:35:35.814506+00:00; last transport record 2026-11-12T00:52:38.932135+00:00.

**All token and cost values are known subtotals, not complete totals.** Price is user-specified Gemini standard equivalent ($0.15 cached/$1.50 uncached/$9 output per million), not the actual DeepSeek invoice. Failed, timed-out, replaced-generation and unfinished attempts remain charged.

| Generation | Cell | Harness | Strategy | Cached | Non-cache | Output | Total | Equivalent $ known | Unknown pricing requests | Missing instrumentation attempts |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| transport-v8-one-hour-retry5 | bc_dsh | dsh | visual | 0 | 0 | 0 | 0 | 0.0000 | 0 | 32 |
| transport-v8-one-hour-retry5 | bc_hermes | hermes | visual | 27189760 | 8987193 | 2220795 | 38397748 | 37.5464 | 1104 | 0 |
| transport-v8-one-hour-retry5 | controlled_bc | hermes | visual | 1180288 | 441669 | 116771 | 1738728 | 1.8905 | 1661 | 0 |
| transport-v8-one-hour-retry5 | controlled_mmbc | hermes | visual | 3259392 | 1022974 | 167517 | 4449883 | 3.5310 | 921 | 0 |
| transport-v8-one-hour-retry5 | mmbc_vanilla | hermes | visual | 12267392 | 4525698 | 1019895 | 17812985 | 17.8077 | 1391 | 0 |
| transport-v8-one-hour-retry5 | mmbc_vera | hermes | visual | 9696512 | 3514941 | 910311 | 14121764 | 14.9197 | 1392 | 0 |
| transport-v8-one-hour-retry5 | rq3_scale_0000 | hermes | visual | 43056128 | 15270867 | 3394192 | 61721187 | 59.9124 | 781 | 0 |
| transport-v8-one-hour-retry5 | rq3_scale_0250 | hermes | visual | 43296000 | 15447881 | 3663489 | 62407370 | 62.6376 | 876 | 0 |
| transport-v8-one-hour-retry5 | rq3_scale_0500 | hermes | visual | 34397696 | 12009541 | 3041897 | 49461444 | 50.5510 | 924 | 1 |
| transport-v8-one-hour-retry5 | rq3_scale_0700 | hermes | visual | 28306944 | 10913106 | 1896362 | 41116412 | 37.6830 | 1063 | 0 |
| transport-v8-one-hour-retry5 | rq3_scale_0750 | hermes | visual | 27855360 | 10560285 | 1864433 | 40280078 | 36.7986 | 1115 | 0 |
| transport-v8-one-hour-retry5 | rq3_scale_0800 | hermes | visual | 27728384 | 9677848 | 2069399 | 39485204 | 37.3006 | 1095 | 0 |
| transport-v8-one-hour-retry5 | rq3_scale_1000 | hermes | visual | 41307776 | 14632306 | 3111261 | 59051343 | 56.1460 | 892 | 0 |
| transport-v8-one-hour-retry5 | shared_baselines | dsh | discard | 0 | 0 | 0 | 0 | 0.0000 | 0 | 2 |
| transport-v8-one-hour-retry5 | shared_baselines | dsh | none | 0 | 0 | 0 | 0 | 0.0000 | 0 | 2 |
| transport-v8-one-hour-retry5 | shared_baselines | dsh | sliding_window | 0 | 0 | 0 | 0 | 0.0000 | 0 | 2 |
| transport-v8-one-hour-retry5 | shared_baselines | dsh | summarize | 0 | 0 | 0 | 0 | 0.0000 | 0 | 2 |
| transport-v8-one-hour-retry5 | shared_baselines | hermes | discard | 384 | 2405 | 7049 | 9838 | 0.0671 | 4 | 1 |
| transport-v8-one-hour-retry5 | shared_baselines | hermes | none | 41088 | 19396 | 6481 | 66965 | 0.0936 | 2 | 1 |
| transport-v8-one-hour-retry5 | shared_baselines | hermes | sliding_window | 33408 | 22868 | 1571 | 57847 | 0.0535 | 3 | 1 |
| transport-v8-one-hour-retry5 | shared_baselines | hermes | summarize | 54784 | 37198 | 3533 | 95515 | 0.0958 | 5 | 1 |
| transport-v9-runtime-recovery | bc_dsh | dsh | visual | 27517440 | 8002957 | 1180748 | 36701145 | 26.7588 | 875 | 0 |
| transport-v9-runtime-recovery | shared_baselines | dsh | discard | 2540544 | 552822 | 116366 | 3209732 | 2.2576 | 20 | 0 |
| transport-v9-runtime-recovery | shared_baselines | dsh | none | 6879232 | 865787 | 65765 | 7810784 | 2.9225 | 11 | 0 |
| transport-v9-runtime-recovery | shared_baselines | dsh | sliding_window | 8849280 | 3269033 | 234703 | 12353016 | 8.3433 | 61 | 0 |
| transport-v9-runtime-recovery | shared_baselines | dsh | summarize | 5832960 | 7669401 | 625616 | 14127977 | 18.0096 | 63 | 0 |
| transport-v9-runtime-recovery | shared_baselines | hermes | discard | 2557568 | 966788 | 370593 | 3894949 | 5.1692 | 345 | 0 |
| transport-v9-runtime-recovery | shared_baselines | hermes | none | 33323264 | 3739317 | 750123 | 37812704 | 17.3586 | 395 | 0 |
| transport-v9-runtime-recovery | shared_baselines | hermes | sliding_window | 2807424 | 1848584 | 133926 | 4789934 | 4.3993 | 340 | 0 |
| transport-v9-runtime-recovery | shared_baselines | hermes | summarize | 4354176 | 8248669 | 749517 | 13352362 | 19.7718 | 361 | 0 |

Latency is client-side HTTP duration, not provider-internal processing time. Attempt E2E includes failed tries, may overlap HTTP/render timing, and must not be added to them. Missing result records leave E2E unknown. Compression/render absence is unknown, not zero.

Detailed per-status (completed/timeout/failed/blocked/unfinished), latency and rendering accounting is in `deepseek_cost_prediction.json`. Actual system exclusion must be joined to the reporting subset by the main analysis; status breakdown alone does not infer exclusions.
