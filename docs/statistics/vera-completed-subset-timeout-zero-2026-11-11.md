# VERA 完成子集：timeout 计零

沿用上一份报告的同一快照（北京时间2026-11-11 22:55–23:00），仅改变subset与计分口径，不混入后续新完成轨迹。

VERA正常完成即纳入，包括答错；不要求其他方法完成。所有方法在同一题目内容和repeat上配对。timeout按用户要求计0。其他执行失败、缺评分、缺归档和仍在补跑的样本不擅自计0；固定分母下给出全部未知计0至全部未知计1的范围。

| 配置 | N / 独立题 | No Compression | Discard-All | Summary | Sliding Window | VERA | Vanilla |
|---|---:|---:|---:|---:|---:|---:|---:|
| BC Gemini/Hermes | 218 / 90 | 46.79–85.32% [84未知] | 69.27–81.65% [27未知] | 64.22–78.90% [32未知] | 52.29–85.32% [72未知] | 74.31% (162/218) | — |
| BC DeepSeek/Hermes | 226 / 90 | 83.63–84.07% [1未知] | 75.66–77.88% [5未知] | 84.51–85.40% [2未知] | 85.84% (194/226) | 91.15% (206/226) | — |
| BC DeepSeek/DSH | 198 / 80 | 84.85–88.38% [7未知] | 77.78–82.32% [9未知] | 83.33–87.37% [8未知] | 84.34–86.87% [5未知] | 91.41% (181/198) | — |
| MMBC Gemini/Hermes | 89 / 89 | 23.60% (21/89) | 23.60–25.84% [2未知] | 24.72–25.84% [1未知] | 31.46–32.58% [1未知] | 28.09% (25/89) | — |
| MMBC DeepSeek/Hermes | 82 / 50 | 51.22–53.66% [2未知] | 34.15–35.37% [1未知] | 51.22–54.88% [3未知] | 53.66–54.88% [1未知] | 82.93% (68/82) | 52.44–70.73% [15未知] |

## 子集内超时 / 其他失败

以下每格为timeout/failed，均仅限当前VERA完成子集，不是全部cohort的计数。

| 配置 | No Compression | Discard-All | Summary | Sliding Window | VERA | Vanilla |
|---|---:|---:|---:|---:|---:|---:|
| BC Gemini/Hermes | 0/0 | 0/1 | 0/4 | 0/0 | 0/0 | — |
| BC DeepSeek/Hermes | 0/0 | 1/5 | 5/2 | 2/0 | 0/0 | — |
| BC DeepSeek/DSH | 8/7 | 25/9 | 14/7 | 14/5 | 0/0 | — |
| MMBC Gemini/Hermes | 0/0 | 0/2 | 0/1 | 0/1 | 0/0 | — |
| MMBC DeepSeek/Hermes | 33/2 | 34/1 | 31/3 | 31/1 | 0/0 | 12/0 |

## 未知数据明细

- BC Gemini/Hermes / none: 84，{"missing_archive_record": 84}
- BC Gemini/Hermes / summarize: 32，{"missing_archive_record": 28, "failed": 4}
- BC Gemini/Hermes / sliding_window: 72，{"missing_archive_record": 72}
- BC Gemini/Hermes / discard: 27，{"missing_archive_record": 26, "failed": 1}
- BC DeepSeek/Hermes / none: 1，{"completed_grade_or_cleanup_unknown": 1}
- BC DeepSeek/Hermes / summarize: 2，{"failed": 2}
- BC DeepSeek/Hermes / discard: 5，{"failed": 5}
- BC DeepSeek/DSH / none: 7，{"failed": 7}
- BC DeepSeek/DSH / summarize: 8，{"failed": 7, "completed_grade_or_cleanup_unknown": 1}
- BC DeepSeek/DSH / sliding_window: 5，{"failed": 5}
- BC DeepSeek/DSH / discard: 9，{"failed": 9}
- MMBC Gemini/Hermes / discard: 2，{"failed": 2}
- MMBC Gemini/Hermes / summarize: 1，{"failed": 1}
- MMBC Gemini/Hermes / sliding_window: 1，{"failed": 1}
- MMBC DeepSeek/Hermes / discard: 1，{"failed": 1}
- MMBC DeepSeek/Hermes / none: 2，{"failed": 2}
- MMBC DeepSeek/Hermes / sliding_window: 1，{"failed": 1}
- MMBC DeepSeek/Hermes / summarize: 3，{"failed": 3}
- MMBC DeepSeek/Hermes / vanilla_visual: 15，{"pending": 14, "running": 1}

解释：VERA在这个子集不会因自身执行失败扣分，其他方法则会；这是针对VERA能完成题目的条件表现，不是总体公平比较，也不能替代全cohort准确率。已完成错误答案保留。历史Gemini协议与DeepSeek不同，且Gemini BC存在较多缺失记录。

DeepSeek MMBC：VERA68/82=82.93%；vanilla已有43个正确、12个timeout、15个运行/待跑，固定82分母下为52.44–70.73%。即使15个未完成全部正确，也不能据此消除VERA筛选子集带来的偏差。

零模型调用，不修改原始结果或运行实验。可复核数据：`outputs/analysis/vera-completed-subset-v1/{report.json,membership.jsonl}`。
