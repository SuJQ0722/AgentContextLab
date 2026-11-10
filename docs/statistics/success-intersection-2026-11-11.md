# 所有方法成功交集：离线配对统计

固定同一题目内容和同一repeat，先取全部方法 completed 的交集，再删除任一方法缺评分的整组。没有按答案正误筛选。BC沿用原有固定失败恢复选择；不混入后续按答案筛选的VERA-only补跑。

**口径A：全部方法完成且有评分**。这不证明过程中没有恢复过的API错误。

| Scope | 配对题次 | 独立题数 | repeat 1/2/3数量 | No Compression | Discard | Summary | Window | VERA | Vanilla |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|
| BC hermes five methods | 192 | 80 | 60/64/68 | 85.94% (165/192) | 82.29% (158/192) | 90.10% (173/192) | 89.06% (171/192) | 92.71% (178/192) | NA |
| BC dsh five methods | 136 | 59 | 44/45/47 | 91.91% (125/136) | 93.38% (127/136) | 93.38% (127/136) | 93.38% (127/136) | 93.38% (127/136) | NA |
| MMBC hermes six methods | 14 | 8 | 7/5/2 | 85.71% (12/14) | 92.86% (13/14) | 85.71% (12/14) | 92.86% (13/14) | 92.86% (13/14) | 92.86% (13/14) |
| MMBC hermes five methods sensitivity | 17 | 11 | 10/5/2 | 88.24% (15/17) | 88.24% (15/17) | 88.24% (15/17) | 88.24% (15/17) | 94.12% (16/17) | NA |

**口径B：全部方法完成、有评分，且所检查日志中没有已记录错误**。要求calls/call-starts/web日志存在、模型调用ID闭合，并剔除结构化API/工具失败及日志中明确的连接/超时/重试标记。SDK内部重试未必逐HTTP记录，因此这里是“未观察到错误”，不能冒称严格零错误。

| Scope | 配对题次 | 独立题数 | repeat 1/2/3数量 | No Compression | Discard | Summary | Window | VERA | Vanilla |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|
| BC hermes five methods | 75 | 54 | 5/32/38 | 86.67% (65/75) | 85.33% (64/75) | 93.33% (70/75) | 92.00% (69/75) | 90.67% (68/75) | NA |
| BC dsh five methods | 80 | 47 | 15/35/30 | 90.00% (72/80) | 92.50% (74/80) | 95.00% (76/80) | 91.25% (73/80) | 93.75% (75/80) | NA |
| MMBC hermes six methods | 4 | 3 | 3/1/0 | 100.00% (4/4) | 100.00% (4/4) | 100.00% (4/4) | 100.00% (4/4) | 100.00% (4/4) | 100.00% (4/4) |
| MMBC hermes five methods sensitivity | 9 | 8 | 8/1/0 | 88.89% (8/9) | 88.89% (8/9) | 100.00% (9/9) | 88.89% (8/9) | 100.00% (9/9) | NA |

## 覆盖与解释

成功交集是运行结果之后的筛选，容易保留较容易的题目。不能取代完整cohort的成功率、超时率和准确率，也不能用来证明总体优越性。各repeat覆盖不相同，以上是题次等权准确率，不标作完整avg@3 ± std。MMBC六方法和五方法交集不同，不能跨行直接归因vanilla带来的效果。

- BC hermes five methods: completed交集193，因缺评分整组排除1；审计轨迹状态{'no_observed_error': 731, 'observed_error': 233, 'coverage_unknown': 1}；口径A具有完整三个repeat的题数47。
- BC dsh five methods: completed交集137，因缺评分整组排除1；审计轨迹状态{'observed_error': 100, 'no_observed_error': 585}；口径A具有完整三个repeat的题数31。
- MMBC hermes six methods: completed交集14，因缺评分整组排除0；审计轨迹状态{'no_observed_error': 66, 'observed_error': 18}；口径A具有完整三个repeat的题数1。
- MMBC hermes five methods sensitivity: completed交集17，因缺评分整组排除0；审计轨迹状态{'no_observed_error': 71, 'observed_error': 14}；口径A具有完整三个repeat的题数1。

原始输入SHA、纳入题目/repeat清单、逐attempt错误与覆盖记录：`outputs/analysis/success-intersection-v1/report.json`。

复现：`python scripts/analyze_success_intersection_v1.py`。零模型调用，不修改原始日志或冻结实验。

## RQ3补充：七档全部完成交集

原 `rq3-final-seven-v3`（不混入后续bounded补跑）七档全部completed有35题次，排除1个缺评分配对后为34题次、17道题，repeat分布11/11/12。同题内容哈希一致。0x、0.25x、0.7x、0.8x、1x各33/34（97.06%）；0.5x、0.75x各34/34（100%）。这是口径A，尚未逐轨迹排除中途恢复错误，不应写成“无报错交集”，也不能用此筛选后的小样本证明最优分辨率。
