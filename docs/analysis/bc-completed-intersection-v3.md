# BC DeepSeek：共同完成且已评分子集

快照时间：2026-11-11T14:58:08.421370+00:00

数据集：文本 BC100；visual 指上下文表达方式。
保留任何历史 completed（包括答错）；仅执行失败可由后继终态替代。排除按答案挑选的 bounded retry。零模型调用。
avg3 ± std 仅使用所有比较方法、全部三个重复均完成且评分的问题；std 为三次准确率的样本标准差，单位为百分点。此为条件子集准确率，不代表完整100题。

## hermes

共同已完成槽 213；共同完成且已评分槽 212；缺任一评分排除 1 槽；严格三重复问题 55。

| 方法 | 三次正确数 / 每次题数 | avg3 ± std |
|---|---|---|
| none | [54.0, 52.0, 49.0] / 55 | 93.94 ± 4.58% |
| discard | [49.0, 48.0, 46.0] / 55 | 86.67 ± 2.78% |
| summarize | [52.0, 52.0, 52.0] / 55 | 94.55 ± 0.00% |
| sliding_window | [51.0, 51.0, 52.0] / 55 | 93.33 ± 1.05% |
| visual | [53.0, 52.0, 53.0] / 55 | 95.76 ± 1.05% |

## dsh

共同已完成槽 142；共同完成且已评分槽 141；缺任一评分排除 1 槽；严格三重复问题 31。

| 方法 | 三次正确数 / 每次题数 | avg3 ± std |
|---|---|---|
| none | [29.0, 29.0, 28.0] / 31 | 92.47 ± 1.86% |
| discard | [29.0, 29.0, 29.0] / 31 | 93.55 ± 0.00% |
| summarize | [28.0, 30.0, 29.0] / 31 | 93.55 ± 3.23% |
| sliding_window | [30.0, 28.0, 29.0] / 31 | 93.55 ± 3.23% |
| visual | [30.0, 29.0, 29.0] / 31 | 94.62 ± 1.86% |

## cross_harness_all10

共同已完成槽 136；共同完成且已评分槽 136；缺任一评分排除 0 槽；严格三重复问题 31。

| 方法 | 三次正确数 / 每次题数 | avg3 ± std |
|---|---|---|
| hermes/none | [30.0, 29.0, 28.0] / 31 | 93.55 ± 3.23% |
| hermes/discard | [28.0, 29.0, 27.0] / 31 | 90.32 ± 3.23% |
| hermes/summarize | [30.0, 29.0, 30.0] / 31 | 95.70 ± 1.86% |
| hermes/sliding_window | [29.0, 29.0, 28.0] / 31 | 92.47 ± 1.86% |
| hermes/visual | [30.0, 29.0, 30.0] / 31 | 95.70 ± 1.86% |
| dsh/none | [29.0, 29.0, 28.0] / 31 | 92.47 ± 1.86% |
| dsh/discard | [29.0, 29.0, 29.0] / 31 | 93.55 ± 0.00% |
| dsh/summarize | [28.0, 30.0, 29.0] / 31 | 93.55 ± 3.23% |
| dsh/sliding_window | [30.0, 28.0, 29.0] / 31 | 93.55 ± 3.23% |
| dsh/visual | [30.0, 29.0, 29.0] / 31 | 94.62 ± 1.86% |

## 每方法300槽当前状态

| Harness/方法 | completed | timeout | failed | interrupted/not_started | recovery运行 | recovery待运行 | recovery状态未核实 | completed且已评分 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hermes/none | 297 | 3 | 0 | 0 | 0 | 0 | 0 | 296 |
| hermes/discard | 288 | 1 | 11 | 0 | 0 | 0 | 0 | 288 |
| hermes/summarize | 283 | 14 | 3 | 0 | 0 | 0 | 0 | 283 |
| hermes/sliding_window | 297 | 3 | 0 | 0 | 0 | 0 | 0 | 297 |
| hermes/visual | 226 | 73 | 1 | 0 | 0 | 0 | 0 | 226 |
| dsh/none | 231 | 46 | 23 | 0 | 0 | 0 | 0 | 231 |
| dsh/discard | 187 | 90 | 23 | 0 | 0 | 0 | 0 | 187 |
| dsh/summarize | 220 | 67 | 13 | 0 | 0 | 0 | 0 | 219 |
| dsh/sliding_window | 228 | 58 | 14 | 0 | 0 | 0 | 0 | 228 |
| dsh/visual | 198 | 72 | 27 | 0 | 3 | 0 | 0 | 198 |

清理状态未确认（是上述状态的附加标记，不另计槽）：{"dsh/summarize": 1, "dsh/visual": 1}

复现：`python scripts/analyze_bc_completed_intersection_v3.py --output <新的输出目录>`。

原始快照：`outputs/analysis/bc-completion-intersection-v3-snapshot/`，包括 report.json、selected-observations.jsonl、overlay-decisions.json 和源文件 SHA。按文件读取期间采样，非事务性全目录快照；详见 JSON 的起止时间。
