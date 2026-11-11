# MMBC 六方法共同完成交集

Earliest completed execution retained irrespective of score; only execution failures replaced by subsequent fixed operational recovery. Answer-selected bounded namespace excluded.

共同 completed 23 题次；共同 completed+scored 23 题次，独立题 15，repeat覆盖 {1: 11, 2: 6, 3: 6}。

| 方法 | 正确/分母 | Accuracy | 三repeat齐全子集 avg3 ± sample std |
|---|---:|---:|---:|
| none | 20/23 | 86.96% | 100.00 ± 0.00% |
| discard | 16/23 | 69.57% | 100.00 ± 0.00% |
| summarize | 20/23 | 86.96% | 83.33 ± 28.87% |
| sliding_window | 19/23 | 82.61% | 100.00 ± 0.00% |
| visual | 20/23 | 86.96% | 100.00 ± 0.00% |
| vanilla_visual | 19/23 | 82.61% | 100.00 ± 0.00% |

严格三repeat齐全子集：2道题，每方法6题次。

Post-execution intersection, mixed protocol recovery. Descriptive paired subset, not full benchmark accuracy or unbiased superiority. Strict avg3/std uses only questions with all three scored repeats common to all six methods.

| 方法（每种300槽） | completed | timeout | failed | running recovery | pending recovery |
|---|---:|---:|---:|---:|---:|
| none | 78 | 212 | 10 | 0 | 0 |
| discard | 107 | 185 | 8 | 0 | 0 |
| summarize | 83 | 209 | 8 | 0 | 0 |
| sliding_window | 103 | 192 | 5 | 0 | 0 |
| visual | 82 | 86 | 6 | 16 | 110 |
| vanilla_visual | 102 | 61 | 1 | 16 | 120 |

One current status per fixed question/repeat slot. Active/pending V7 recovery replaces prior failure state; historical attempt failures are not added to slot totals.

快照时间：2026-11-11T14:55:22.046972+00:00


共同成功集合仅覆盖300个固定题次中的23个，且是按执行结果事后选出的混合恢复协议子集。VERA与No Compression、Summarization在该子集中相同，领先Vanilla仅一个题次；这些结果不能证明完整MMBC总体优越性。严格三个repeat齐全只有2道题，0标准差也不能解释为稳定性证据。

运行状态中的running表示已claim、尚无终态result；pending表示尚未claim。它们替代该槽旧的失败状态，不与旧timeout重复计数。来源计划、结果、评分与脚本SHA以及全部1800条选择行保存在 `outputs/analysis/mmbc-sixmethod-completed-intersection-v3/{report.json,rows.json}`。没有调用模型或更改实验进程。

复现：`python scripts/analyze_mmbc_completed_intersection_v3.py`。
