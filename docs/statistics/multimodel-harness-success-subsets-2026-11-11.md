# 多模型 / 多 harness：全部方法正常完成子集

生成时间：2026-11-11T15:00:27.292567+00:00

已有配置为历史 Gemini + Hermes、新 DeepSeek + Hermes / DSH；没有 Gemini + DSH。DeepSeek 版本为 deepseek-v4.1-flash-1017；Gemini 归档别名为 gemini-3.5-flash-thinking。

同一题目内容哈希和同一 repeat 匹配，全部方法正常完成并有有效绑定评分才纳入；答错的完成轨迹保留。恢复只替换执行失败，不使用按答案筛选的 bounded 重跑。零模型调用。

## 每个配置内部的共同子集

每行使用自己的全方法交集，不能跨行直接当作同题比较。N为题次，不是独立题数；不是完整100×3准确率。

| 模态 / 数据集 | 模型 / harness | 共同题次 | 独立题 | No Compression | Discard-All | Summarization | Sliding Window | VERA | Vanilla |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 文本 BC | Gemini / Hermes | 88 | 46 | 84.09% (74/88) | 87.50% (77/88) | 82.95% (73/88) | 82.95% (73/88) | 87.50% (77/88) | — |
| 文本 BC | DeepSeek / Hermes | 212 | 85 | 84.91% (180/212) | 79.25% (168/212) | 88.21% (187/212) | 87.26% (185/212) | 91.98% (195/212) | — |
| 文本 BC | DeepSeek / DSH | 141 | 62 | 92.20% (130/141) | 93.62% (132/141) | 93.62% (132/141) | 93.62% (132/141) | 93.62% (132/141) | — |
| 多模态 MMBC | Gemini / Hermes | 85 | 85 | 24.71% (21/85) | 24.71% (21/85) | 25.88% (22/85) | 31.76% (27/85) | 29.41% (25/85) | — |
| 多模态 MMBC | DeepSeek / Hermes | 23 | 15 | 86.96% (20/23) | 69.57% (16/23) | 86.96% (20/23) | 82.61% (19/23) | 86.96% (20/23) | 82.61% (19/23) |

## BC：三配置15种组合均完成

共同56题次、30道题。同题匹配仍不能消除历史协议、工具和时间差异。

| 配置 | No Compression | Discard-All | Summarization | Sliding Window | VERA | Vanilla |
|---|---:|---:|---:|---:|---:|---:|
| gemini/hermes | 91.07% (51/56) | 96.43% (54/56) | 91.07% (51/56) | 89.29% (50/56) | 94.64% (53/56) | — |
| deepseek/hermes | 92.86% (52/56) | 91.07% (51/56) | 96.43% (54/56) | 96.43% (54/56) | 96.43% (54/56) | — |
| deepseek/dsh | 94.64% (53/56) | 96.43% (54/56) | 94.64% (53/56) | 94.64% (53/56) | 96.43% (54/56) | — |

## MMBC：两模型11种组合均完成

共同11题次、11道题。同题匹配仍不能消除历史协议、工具和时间差异。

| 配置 | No Compression | Discard-All | Summarization | Sliding Window | VERA | Vanilla |
|---|---:|---:|---:|---:|---:|---:|
| gemini/hermes | 9.09% (1/11) | 45.45% (5/11) | 18.18% (2/11) | 27.27% (3/11) | 27.27% (3/11) | — |
| deepseek/hermes | 90.91% (10/11) | 81.82% (9/11) | 100.00% (11/11) | 90.91% (10/11) | 100.00% (11/11) | 90.91% (10/11) |

## 各方法全范围超时 / 其他失败

单元格为超时数 / 其他终态失败数；每槽保留任意已完成结果，否则按最新恢复状态计一次。不是本轮V7-only统计，也不是累计attempt数。BC与DeepSeek MMBC每方法300题次；Gemini MMBC仅100题×repeat1。

| 数据集 / 配置 | No Compression | Discard-All | Summarization | Sliding Window | VERA | Vanilla |
|---|---:|---:|---:|---:|---:|---:|
| BC Gemini/Hermes | 0/0 | 0/1 | 0/5 | 0/0 | 0/21 | — |
| MMBC Gemini/Hermes | 0/2 | 0/3 | 0/3 | 0/1 | 0/11 | — |
| BC DeepSeek/hermes | 3/0 | 1/11 | 14/3 | 3/0 | 73/1 | — |
| BC DeepSeek/dsh | 46/23 | 90/23 | 67/13 | 58/14 | 72/27 | — |
| MMBC DeepSeek/Hermes | 212/10 | 185/8 | 209/8 | 192/5 | 86/6 | 61/1 |

BC Gemini 无记录数（None/Discard/Summary/Window/VERA）：118/52/57/112/61；这些缺失不算作失败。

所有方法的completed、运行/待跑、清理未确认和缺评分计数见对应JSON报告；运行中的恢复不重复算作旧失败。

## 严格同题三repeat统计

| 配置 | 完整三repeat题数 | No Compression | Discard-All | Summarization | Sliding Window | VERA | Vanilla |
|---|---:|---:|---:|---:|---:|---:|---:|
| 文本 BC Gemini / Hermes | 12 | 91.67 ± 8.33 | 94.44 ± 4.81 | 94.44 ± 4.81 | 97.22 ± 4.81 | 100.00 ± 0.00 | — |
| 文本 BC DeepSeek / Hermes | 55 | 93.94 ± 4.58 | 86.67 ± 2.78 | 94.55 ± 0.00 | 93.33 ± 1.05 | 95.76 ± 1.05 | — |
| 文本 BC DeepSeek / DSH | 31 | 92.47 ± 1.86 | 93.55 ± 0.00 | 93.55 ± 3.23 | 93.55 ± 3.23 | 94.62 ± 1.86 | — |
| 多模态 MMBC Gemini / Hermes | 0 | NA | NA | NA | NA | NA | — |
| 多模态 MMBC DeepSeek / Hermes | 2 | 100.00 ± 0.00 | 100.00 ± 0.00 | 83.33 ± 28.87 | 100.00 ± 0.00 | 100.00 ± 0.00 | 100.00 ± 0.00 |

标准差为三次repeat准确率的样本标准差。MMBC DeepSeek完整三repeat只有2题，Gemini只有repeat1，不能用小样本100±0论证稳定性。

解释：DeepSeek Hermes的BC VERA在自身共同子集领先；DSH上与其他压缩基线持平。MMBC VERA仅比vanilla多答对1题次，与None和Summary持平，目前不支持优于所有方法。

## 可复核来源

- `outputs/analysis/multimodel-success-subsets-v1/report.json`
- `outputs/analysis/bc-completion-intersection-v3-snapshot/`
- `outputs/analysis/mmbc-sixmethod-completed-intersection-v3/`
- `outputs/analysis/gemini-matched-completion-v1/`

各分析保留原始结果/评分/plan的SHA和subset成员，不修改、删除或重跑预测。
