# 实验 4：历史日志的重复方差与配对统计

按用户最新决定，采用 avg@3，不追加第四 repeat。本报告离线重建，无新增模型调用。模型、benchmark 分开统计；历史 Gemini 不能与新 DeepSeek 混成 avg@3。论文源码/表格映射尚未核实，以下为归档 canonical 实验，不能直接宣称完整复现 Table 1/2/5。

mean ± std：在所有方法、所有已观察 repeat 标签均有评分的相同题集上，先算各 repeat 的平均得分，再算均值及样本标准差。单 repeat 的 std 为 NA。repeat 标签不等于已验证的随机 seed。缺失评分不当作 0；完整案例分析可能存在选择偏差。

95% CI：以题为 cluster 重采样 10000 次，保留同一题的所有重复；覆盖题目抽样不确定性，不代表新增 seed 的不确定性。配对检验对同题同 repeat 求差，先按题平均，再进行双侧 sign-flip 随机化检验；跨本报告全部比较做 Holm 校正。p 不显著不能写“统计等价”，除非预先给定等价界值并做等价检验。

| Model / Harness | Benchmark | Method | Balanced Q | Repeats | Mean ± std (%) | 95% CI (%) |
|---|---|---|---:|---:|---|---|
| deepseek-v4.1-flash-1017/huoshan/huoshan / dsh | bc100-new | No Compression | 0 | 3 | NA ± NA | [NA, NA] |
| deepseek-v4.1-flash-1017/huoshan/huoshan / dsh | bc100-new | Discard | 0 | 3 | NA ± NA | [NA, NA] |
| deepseek-v4.1-flash-1017/huoshan/huoshan / dsh | bc100-new | Sliding Window | 0 | 3 | NA ± NA | [NA, NA] |
| deepseek-v4.1-flash-1017/huoshan/huoshan / dsh | bc100-new | Summarize | 0 | 3 | NA ± NA | [NA, NA] |
| deepseek-v4.1-flash-1017/huoshan/huoshan / dsh | bc100-new | VERA | 0 | 3 | NA ± NA | [NA, NA] |
| deepseek-v4.1-flash-1017/huoshan/huoshan / hermes | bc100-new | No Compression | 0 | 3 | NA ± NA | [NA, NA] |
| deepseek-v4.1-flash-1017/huoshan/huoshan / hermes | bc100-new | Discard | 0 | 3 | NA ± NA | [NA, NA] |
| deepseek-v4.1-flash-1017/huoshan/huoshan / hermes | bc100-new | Sliding Window | 0 | 3 | NA ± NA | [NA, NA] |
| deepseek-v4.1-flash-1017/huoshan/huoshan / hermes | bc100-new | Summarize | 0 | 3 | NA ± NA | [NA, NA] |
| deepseek-v4.1-flash-1017/huoshan/huoshan / hermes | bc100-new | VERA | 0 | 3 | NA ± NA | [NA, NA] |
| gemini-3.5-flash-thinking / hermes | bc | No Compression | 19 | 3 | 89.47 ± 9.12 | [78.95, 98.25] |
| gemini-3.5-flash-thinking / hermes | bc | Discard | 19 | 3 | 89.47 ± 5.26 | [77.19, 100.00] |
| gemini-3.5-flash-thinking / hermes | bc | Sliding Window | 19 | 3 | 89.47 ± 5.26 | [78.95, 98.25] |
| gemini-3.5-flash-thinking / hermes | bc | Summarize | 19 | 3 | 84.21 ± 5.26 | [70.18, 94.74] |
| gemini-3.5-flash-thinking / hermes | bc | VERA | 19 | 3 | 100.00 ± 0.00 | [100.00, 100.00] |
| gemini-3.5-flash-thinking / hermes | bc_v3 | No Compression | 238 | 1 | 28.57 ± NA | [23.11, 34.45] |
| gemini-3.5-flash-thinking / hermes | bc_v3 | Discard | 238 | 1 | 24.79 ± NA | [19.33, 30.67] |
| gemini-3.5-flash-thinking / hermes | bc_v3 | Sliding Window | 238 | 1 | 23.53 ± NA | [18.07, 28.99] |
| gemini-3.5-flash-thinking / hermes | bc_v3 | Summarize | 238 | 1 | 24.79 ± NA | [19.33, 30.25] |
| gemini-3.5-flash-thinking / hermes | bc_v3 | VERA | 238 | 1 | 30.67 ± NA | [24.79, 36.55] |
| gemini-3.5-flash-thinking / hermes | bc_zh | No Compression | 188 | 3 | 86.52 ± 1.54 | [81.91, 90.78] |
| gemini-3.5-flash-thinking / hermes | bc_zh | Discard | 188 | 3 | 89.54 ± 0.81 | [85.28, 93.26] |
| gemini-3.5-flash-thinking / hermes | bc_zh | Sliding Window | 188 | 3 | 86.17 ± 1.41 | [81.74, 90.25] |
| gemini-3.5-flash-thinking / hermes | bc_zh | Summarize | 188 | 3 | 87.59 ± 2.68 | [83.33, 91.49] |
| gemini-3.5-flash-thinking / hermes | bc_zh | VERA | 188 | 3 | 89.01 ± 0.81 | [84.75, 92.91] |
| gemini-3.5-flash-thinking / hermes | mmbrowsecomp | No Compression | 322 | 1 | 23.91 ± NA | [19.25, 28.88] |
| gemini-3.5-flash-thinking / hermes | mmbrowsecomp | Discard | 322 | 1 | 22.36 ± NA | [17.70, 27.02] |
| gemini-3.5-flash-thinking / hermes | mmbrowsecomp | Sliding Window | 322 | 1 | 26.09 ± NA | [21.43, 31.06] |
| gemini-3.5-flash-thinking / hermes | mmbrowsecomp | Summarize | 322 | 1 | 21.12 ± NA | [16.77, 25.78] |
| gemini-3.5-flash-thinking / hermes | mmbrowsecomp | VERA | 322 | 1 | 24.22 ± NA | [19.57, 28.88] |
| gemini-3.5-flash-thinking / hermes | seal0 | No Compression | 92 | 3 | 58.70 ± 3.92 | [50.00, 67.39] |
| gemini-3.5-flash-thinking / hermes | seal0 | Discard | 92 | 3 | 59.78 ± 3.26 | [51.09, 68.48] |
| gemini-3.5-flash-thinking / hermes | seal0 | Sliding Window | 92 | 3 | 56.52 ± 1.88 | [47.46, 65.22] |
| gemini-3.5-flash-thinking / hermes | seal0 | Summarize | 92 | 3 | 59.42 ± 2.51 | [50.72, 68.12] |
| gemini-3.5-flash-thinking / hermes | seal0 | VERA | 92 | 3 | 55.43 ± 2.17 | [46.38, 64.13] |
| gemini-3.5-flash-thinking / hermes | seal0-64k | No Compression | 53 | 3 | 76.10 ± 3.93 | [65.41, 85.53] |
| gemini-3.5-flash-thinking / hermes | seal0-64k | Discard | 53 | 3 | 72.96 ± 4.75 | [61.01, 83.65] |
| gemini-3.5-flash-thinking / hermes | seal0-64k | Sliding Window | 53 | 3 | 74.84 ± 4.75 | [64.15, 84.91] |
| gemini-3.5-flash-thinking / hermes | seal0-64k | Summarize | 53 | 3 | 72.96 ± 1.09 | [61.62, 83.02] |
| gemini-3.5-flash-thinking / hermes | seal0-64k | VERA | 53 | 3 | 75.47 ± 5.66 | [64.78, 84.91] |
| gemini-3.5-flash-thinking / hermes | xbench_deepsearch | No Compression | 86 | 3 | 75.19 ± 1.34 | [67.44, 82.56] |
| gemini-3.5-flash-thinking / hermes | xbench_deepsearch | Discard | 86 | 3 | 72.48 ± 0.67 | [63.95, 80.62] |
| gemini-3.5-flash-thinking / hermes | xbench_deepsearch | Sliding Window | 86 | 3 | 72.87 ± 2.69 | [64.34, 81.01] |
| gemini-3.5-flash-thinking / hermes | xbench_deepsearch | Summarize | 86 | 3 | 73.26 ± 2.01 | [64.73, 81.78] |
| gemini-3.5-flash-thinking / hermes | xbench_deepsearch | VERA | 86 | 3 | 70.16 ± 2.42 | [61.63, 78.29] |
| gpt-5.4-mini / hermes | bc | Sliding Window | 4 | 1 | 0.00 ± NA | [0.00, 0.00] |

| Model / Harness | Benchmark | Baseline | Paired Q | Δ VERA (pp) | 95% CI (pp) | p (Holm) |
|---|---|---|---:|---:|---|---:|
| gemini-3.5-flash-thinking / hermes | bc | No Compression | 146 | 3.31 | [-2.17, 8.79] | 1 |
| gemini-3.5-flash-thinking / hermes | bc | Discard | 153 | -0.11 | [-5.66, 5.67] | 1 |
| gemini-3.5-flash-thinking / hermes | bc | Sliding Window | 142 | 3.05 | [-2.35, 8.57] | 1 |
| gemini-3.5-flash-thinking / hermes | bc | Summarize | 156 | 3.21 | [-2.14, 8.76] | 1 |
| gemini-3.5-flash-thinking / hermes | bc_v3 | No Compression | 259 | -0.77 | [-5.79, 4.25] | 1 |
| gemini-3.5-flash-thinking / hermes | bc_v3 | Discard | 261 | 4.98 | [0.00, 9.96] | 1 |
| gemini-3.5-flash-thinking / hermes | bc_v3 | Sliding Window | 260 | 6.15 | [1.15, 11.15] | 0.8315 |
| gemini-3.5-flash-thinking / hermes | bc_v3 | Summarize | 252 | 5.95 | [0.40, 11.51] | 1 |
| gemini-3.5-flash-thinking / hermes | bc_zh | No Compression | 284 | 0.59 | [-2.29, 3.46] | 1 |
| gemini-3.5-flash-thinking / hermes | bc_zh | Discard | 284 | 0.23 | [-2.58, 3.11] | 1 |
| gemini-3.5-flash-thinking / hermes | bc_zh | Sliding Window | 286 | 1.92 | [-0.93, 4.78] | 1 |
| gemini-3.5-flash-thinking / hermes | bc_zh | Summarize | 279 | 1.02 | [-1.79, 3.88] | 1 |
| gemini-3.5-flash-thinking / hermes | mmbrowsecomp | No Compression | 337 | 0.89 | [-3.56, 5.34] | 1 |
| gemini-3.5-flash-thinking / hermes | mmbrowsecomp | Discard | 338 | 1.78 | [-2.66, 6.51] | 1 |
| gemini-3.5-flash-thinking / hermes | mmbrowsecomp | Sliding Window | 335 | -2.69 | [-7.46, 1.79] | 1 |
| gemini-3.5-flash-thinking / hermes | mmbrowsecomp | Summarize | 335 | 2.99 | [-1.49, 7.46] | 1 |
| gemini-3.5-flash-thinking / hermes | seal0 | No Compression | 111 | -4.35 | [-9.76, 1.20] | 1 |
| gemini-3.5-flash-thinking / hermes | seal0 | Discard | 111 | -1.50 | [-6.76, 3.90] | 1 |
| gemini-3.5-flash-thinking / hermes | seal0 | Sliding Window | 111 | -1.80 | [-7.66, 4.20] | 1 |
| gemini-3.5-flash-thinking / hermes | seal0 | Summarize | 111 | -3.15 | [-9.31, 2.70] | 1 |
| gemini-3.5-flash-thinking / hermes | seal0-64k | No Compression | 102 | -4.58 | [-10.62, 1.31] | 1 |
| gemini-3.5-flash-thinking / hermes | seal0-64k | Discard | 98 | -1.19 | [-5.61, 3.23] | 1 |
| gemini-3.5-flash-thinking / hermes | seal0-64k | Sliding Window | 102 | -1.47 | [-5.56, 2.78] | 1 |
| gemini-3.5-flash-thinking / hermes | seal0-64k | Summarize | 101 | 0.17 | [-5.12, 5.61] | 1 |
| gemini-3.5-flash-thinking / hermes | xbench_deepsearch | No Compression | 99 | -1.85 | [-7.74, 4.21] | 1 |
| gemini-3.5-flash-thinking / hermes | xbench_deepsearch | Discard | 99 | -0.84 | [-6.23, 4.71] | 1 |
| gemini-3.5-flash-thinking / hermes | xbench_deepsearch | Sliding Window | 98 | -1.70 | [-7.31, 3.91] | 1 |
| gemini-3.5-flash-thinking / hermes | xbench_deepsearch | Summarize | 99 | -1.01 | [-6.40, 4.55] | 1 |

avg@3 缺口：缺轨迹 7753，历史已有轨迹缺评分 721，新 campaign 待评分 3000；详细到题/方法/repeat 的清单在 outputs/experiment4/avg3-gaps.jsonl。禁止新 Gemini 的当前约束下，历史 Gemini 的缺口不能直接补跑。新 DeepSeek 三个 repeat 应作为独立模型实验统计。

当前 BC 跨五方法、三个 repeat 的完整评分交集非常小（见 Balanced Q），选择偏差严重，不代表全体题目准确率。新 DeepSeek 在 judge.json 产生后自动按 harness 单独纳入；未评分时均为 NA。

RQ3：发现 Qwen 分辨率 scale 归档，但评分覆盖很低，Table 5 对应关系未验证。rq3-exploratory.csv 仅给已评分子集的题级 bootstrap；不得据此宣称平滑衰减、画未评分的点或当作完整 Table 5。

建议 Finding 3 改为：“在本实验配置及已观测样本中，我们观察到……趋势；其稳定性仍需更多独立重复验证。”文本任务应按 benchmark 报差异和 CI；当前不能统一写成“统计上持平，且成本更低”。成本方向必须引用独立的配对成本数据。

复现：`python scripts/analyze_significance.py`。不调用 API。新增评分后重跑即可更新；缺口清单仅为审计，不会自动触发付费任务。
