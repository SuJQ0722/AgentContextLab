# BC-100 当前评分快照

快照：2026-11-09T06:13:40.913335+00:00（北京时间14:13）。每组100题×3repeat＝300条。模型DeepSeek，比较DSH与Hermes。

## 固定补跑选用后的已知结果

以下准确率仅为答对数/已知结果数；已确认终态失败或超时计0，未完成、未评分与未知请求不补0。各组覆盖不同，不能据此确定方法排名。完整avg3、跨三轮std、CI和配对检验尚未就绪。

| Harness | 策略 | 答对/已知 | 已知部分准确率 | 覆盖/300 | 最终准确率可能范围 |
|---|---|---:|---:|---:|---:|
| dsh | Discard-All | 133/176 | 75.57% | 176/300 | 44.33–85.67% |
| dsh | No Compression | 148/197 | 75.13% | 197/300 | 49.33–83.67% |
| dsh | Sliding Window | 158/204 | 77.45% | 204/300 | 52.67–84.67% |
| dsh | Summarization | 162/205 | 79.02% | 205/300 | 54.00–85.67% |
| dsh | VERA / Visual | 134/185 | 72.43% | 185/300 | 44.67–83.00% |
| hermes | Discard-All | 162/236 | 68.64% | 236/300 | 54.00–75.33% |
| hermes | No Compression | 189/243 | 77.78% | 243/300 | 63.00–82.00% |
| hermes | Sliding Window | 181/245 | 73.88% | 245/300 | 60.33–78.67% |
| hermes | Summarization | 181/226 | 80.09% | 226/300 | 60.33–85.00% |
| hermes | VERA / Visual | 151/197 | 76.65% | 197/300 | 50.33–84.67% |

可能范围是假设所有未知结果分别全错/全对所得的确定性界，不是95%置信区间。补跑固定替换原失败；尚未完成的补跑变为unknown，从已知分母中移除旧失败，会机械抬高已知样本准确率。因此不能把下表首轮与上表的差异声称为恢复带来的提升，也不能把补跑当第四个repeat。费用必须累计原尝试与补跑。

## 原始首轮结果单独保留

| Harness | 策略 | 答对/已知 | 全300条最终可能范围 |
|---|---|---:|---:|
| dsh | Discard-All | 133/285 | 44.33–49.33% |
| dsh | No Compression | 148/276 | 49.33–57.33% |
| dsh | Sliding Window | 158/285 | 52.67–57.67% |
| dsh | Summarization | 162/288 | 54.00–58.00% |
| dsh | VERA / Visual | 134/285 | 44.67–49.67% |
| hermes | Discard-All | 161/279 | 53.67–60.67% |
| hermes | No Compression | 189/282 | 63.00–69.00% |
| hermes | Sliding Window | 181/280 | 60.33–67.00% |
| hermes | Summarization | 181/280 | 60.33–67.00% |
| hermes | VERA / Visual | 151/285 | 50.33–55.33% |

来源：`outputs/grading/bc100-v3-deepseek-sfb-v1/progress-snapshot-20261109T0613/statistics.json` 与 `selected-observations.jsonl`；统计JSON SHA256：`b6ae2b5f153b4b39488d392ba712d9f74d49ef3efbe4f1b3b9b73d936cbef715`。这是时间点快照，不会随实时watch覆盖。
