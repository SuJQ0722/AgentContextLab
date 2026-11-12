> 历史冻结快照：2026-11-12 10:43 UTC+8。不是当前V12运行状态；本次发布未重算该历史表，也未重新核对价格。最新代次结果见 [当前结果](current-generations.md)，总入口见 [README](README.md)。

# 停跑后的现有日志统计（零API调用）

每组固定科学题次300；保留任何既有completed，不按答对挑选，不将retry当seed。system/provider/network/storage有明确证据才排除；明确轮次/输出/context预算耗尽记0。未知timeout、未评分、缺日志不默认记0，单列。mean±std为三个repeat各自有效样本准确率的均值与样本标准差（ddof=1），**是有效样本条件结果，分母不齐时不是完整100×3准确率**。完整300缺失则full300_mean=null。

| 数据集 | 模型/harness | 策略 | 有效/300 | 系统排除 | 预算0 | 未知timeout | 未评分 | 其他未知/缺失 | 超时题次/300 | 条件mean±std (%) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| bc100 | deepseek-v4.1-flash-1017/dsh | discard | 213/300 | 0 | 25 | 86 | 1 | 0 | 86/300 (28.7%) | 82.04 ± 3.13 |
| bc100 | deepseek-v4.1-flash-1017/dsh | none | 258/300 | 0 | 24 | 42 | 0 | 0 | 43/300 (14.3%) | 81.80 ± 5.96 |
| bc100 | deepseek-v4.1-flash-1017/dsh | sliding_window | 245/300 | 0 | 16 | 55 | 0 | 0 | 55/300 (18.3%) | 87.77 ± 0.75 |
| bc100 | deepseek-v4.1-flash-1017/dsh | summarize | 234/300 | 0 | 11 | 65 | 0 | 1 | 65/300 (21.7%) | 89.35 ± 1.03 |
| bc100 | deepseek-v4.1-flash-1017/dsh | visual | 223/300 | 0 | 17 | 76 | 1 | 0 | 76/300 (25.3%) | 84.71 ± 3.93 |
| bc100 | deepseek-v4.1-flash-1017/hermes | discard | 299/300 | 0 | 8 | 1 | 0 | 0 | 1/300 (0.3%) | 63.87 ± 2.80 |
| bc100 | deepseek-v4.1-flash-1017/hermes | none | 300/300 | 0 | 1 | 0 | 0 | 0 | 0/300 (0.0%) | 76.00 ± 2.65 |
| bc100 | deepseek-v4.1-flash-1017/hermes | sliding_window | 300/300 | 0 | 1 | 0 | 0 | 0 | 0/300 (0.0%) | 73.67 ± 1.53 |
| bc100 | deepseek-v4.1-flash-1017/hermes | summarize | 289/300 | 0 | 3 | 10 | 1 | 0 | 10/300 (3.3%) | 80.64 ± 1.89 |
| bc100 | deepseek-v4.1-flash-1017/hermes | visual | 236/300 | 26 | 2 | 38 | 0 | 0 | 64/300 (21.3%) | 90.37 ± 3.23 |
| bc100 | gemini-3.5-flash-thinking/hermes | discard | 247/300 | 0 | 0 | 0 | 0 | 53 | 0/300 (0.0%) | 72.25 ± 8.29 |
| bc100 | gemini-3.5-flash-thinking/hermes | none | 182/300 | 0 | 0 | 0 | 0 | 118 | 0/300 (0.0%) | 67.01 ± 5.34 |
| bc100 | gemini-3.5-flash-thinking/hermes | sliding_window | 188/300 | 0 | 0 | 0 | 0 | 112 | 0/300 (0.0%) | 71.16 ± 6.02 |
| bc100 | gemini-3.5-flash-thinking/hermes | summarize | 238/300 | 0 | 0 | 0 | 0 | 62 | 0/300 (0.0%) | 70.60 ± 1.51 |
| bc100 | gemini-3.5-flash-thinking/hermes | visual | 218/300 | 0 | 0 | 0 | 0 | 82 | 0/300 (0.0%) | 74.30 ± 3.02 |
| mmbc100 | deepseek-v4.1-flash-1017/hermes | discard | 109/300 | 22 | 1 | 169 | 0 | 0 | 184/300 (61.3%) | 43.96 ± 7.44 |
| mmbc100 | deepseek-v4.1-flash-1017/hermes | none | 81/300 | 43 | 3 | 176 | 0 | 0 | 212/300 (70.7%) | 81.16 ± 4.58 |
| mmbc100 | deepseek-v4.1-flash-1017/hermes | sliding_window | 104/300 | 22 | 1 | 174 | 0 | 0 | 192/300 (64.0%) | 79.12 ± 5.37 |
| mmbc100 | deepseek-v4.1-flash-1017/hermes | summarize | 82/300 | 33 | 0 | 184 | 1 | 0 | 209/300 (69.7%) | 80.51 ± 9.47 |
| mmbc100 | deepseek-v4.1-flash-1017/hermes | vanilla_visual | 101/300 | 58 | 1 | 43 | 5 | 93 | 94/300 (31.3%) | 76.27 ± 1.64 |
| mmbc100 | deepseek-v4.1-flash-1017/hermes | visual | 84/300 | 69 | 0 | 54 | 1 | 92 | 118/300 (39.3%) | 81.63 ± 3.56 |
| rq3 | deepseek-v4.1-flash-1017/hermes | scale_0.0 | 293/300 | 0 | 6 | 3 | 4 | 0 | 3/300 (1.0%) | 76.46 ± 4.36 |
| rq3 | deepseek-v4.1-flash-1017/hermes | scale_0.25 | 250/300 | 3 | 5 | 44 | 3 | 0 | 47/300 (15.7%) | 81.26 ± 3.00 |
| rq3 | deepseek-v4.1-flash-1017/hermes | scale_0.5 | 222/300 | 28 | 3 | 46 | 4 | 0 | 73/300 (24.3%) | 86.89 ± 1.40 |
| rq3 | deepseek-v4.1-flash-1017/hermes | scale_0.7 | 195/300 | 47 | 1 | 52 | 6 | 0 | 98/300 (32.7%) | 89.31 ± 3.67 |
| rq3 | deepseek-v4.1-flash-1017/hermes | scale_0.75 | 204/300 | 50 | 0 | 44 | 2 | 0 | 93/300 (31.0%) | 92.11 ± 1.96 |
| rq3 | deepseek-v4.1-flash-1017/hermes | scale_0.8 | 211/300 | 47 | 1 | 41 | 1 | 0 | 88/300 (29.3%) | 90.07 ± 1.10 |
| rq3 | deepseek-v4.1-flash-1017/hermes | scale_1.0 | 236/300 | 10 | 7 | 48 | 5 | 1 | 57/300 (19.0%) | 82.58 ± 2.47 |

## 配对探索统计

下表只在两方法共同且三个repeat都有有效结果的题簇上配对；bootstrap以题而非题次为单位，10000次。p为题簇sign-flip双侧检验，并在同benchmark/model/harness的参考对照族内做Holm校正，不代表完整队列显著性。

| 数据集/模型/harness | 参考−对照 | 完整题簇 | 差值百分点 [95%CI] | raw p / Holm p |
|---|---|---:|---|---:|
| bc100/deepseek-v4.1-flash-1017/hermes | visual−none | 65 | 3.59 [0.00, 7.18] | 0.0947 / 0.2841 |
| bc100/deepseek-v4.1-flash-1017/dsh | visual−none | 58 | 0.00 [-3.45, 3.45] | 1.0000 / 1.0000 |
| bc100/deepseek-v4.1-flash-1017/hermes | visual−summarize | 63 | 2.65 [-1.06, 6.88] | 0.3114 / 0.3114 |
| bc100/deepseek-v4.1-flash-1017/dsh | visual−summarize | 52 | -0.64 [-5.13, 3.85] | 1.0000 / 1.0000 |
| bc100/deepseek-v4.1-flash-1017/hermes | visual−sliding_window | 65 | 3.59 [0.00, 7.18] | 0.1202 / 0.2841 |
| bc100/deepseek-v4.1-flash-1017/dsh | visual−sliding_window | 54 | 0.00 [-3.70, 3.70] | 1.0000 / 1.0000 |
| bc100/deepseek-v4.1-flash-1017/hermes | visual−discard | 64 | 11.46 [6.25, 17.71] | 0.0003 / 0.0012 |
| bc100/deepseek-v4.1-flash-1017/dsh | visual−discard | 54 | 0.62 [-3.09, 4.32] | 1.0000 / 1.0000 |
| mmbc100/deepseek-v4.1-flash-1017/hermes | visual−discard | 4 | 8.33 [-25.00, 50.00] | 1.0000 / 1.0000 |
| mmbc100/deepseek-v4.1-flash-1017/hermes | visual−none | 6 | 5.56 [0.00, 16.67] | 1.0000 / 1.0000 |
| mmbc100/deepseek-v4.1-flash-1017/hermes | visual−sliding_window | 5 | 0.00 [0.00, 0.00] | 1.0000 / 1.0000 |
| mmbc100/deepseek-v4.1-flash-1017/hermes | visual−summarize | 3 | 11.11 [0.00, 33.33] | 1.0000 / 1.0000 |
| mmbc100/deepseek-v4.1-flash-1017/hermes | visual−vanilla_visual | 5 | -6.67 [-20.00, 0.00] | 1.0000 / 1.0000 |
| rq3/deepseek-v4.1-flash-1017/hermes | scale_1.0−scale_0.0 | 60 | -3.89 [-8.89, 1.11] | 0.2123 / 1.0000 |
| rq3/deepseek-v4.1-flash-1017/hermes | scale_1.0−scale_0.25 | 55 | -3.03 [-7.88, 1.21] | 0.3165 / 1.0000 |
| rq3/deepseek-v4.1-flash-1017/hermes | scale_1.0−scale_0.5 | 47 | -3.55 [-7.80, 0.00] | 0.1865 / 1.0000 |
| rq3/deepseek-v4.1-flash-1017/hermes | scale_1.0−scale_0.7 | 38 | -0.88 [-3.51, 1.75] | 1.0000 / 1.0000 |
| rq3/deepseek-v4.1-flash-1017/hermes | scale_1.0−scale_0.75 | 45 | -2.96 [-8.89, 2.96] | 0.4751 / 1.0000 |
| rq3/deepseek-v4.1-flash-1017/hermes | scale_1.0−scale_0.8 | 45 | -2.22 [-6.67, 1.48] | 0.5334 / 1.0000 |
| bc100/gemini-3.5-flash-thinking/hermes | visual−none | 22 | 3.03 [-3.03, 10.61] | 0.7506 / 1.0000 |
| bc100/gemini-3.5-flash-thinking/hermes | visual−summarize | 41 | 2.44 [-2.44, 7.32] | 0.5131 / 1.0000 |
| bc100/gemini-3.5-flash-thinking/hermes | visual−sliding_window | 33 | 2.02 [-4.04, 8.08] | 0.7529 / 1.0000 |
| bc100/gemini-3.5-flash-thinking/hermes | visual−discard | 41 | -3.25 [-11.38, 4.88] | 0.5707 / 1.0000 |

历史Gemini为归档alias，非独立provider权重证明；400个缺档科学题次不得当超时。当前统计不含额外付费评分，已有completed但judge错误/缺失保留ungraded。分类根据终态错误字段和native错误字段；没有明确来源的失败保留unclassified。所有记录含source/attempt_path便于成本join。
