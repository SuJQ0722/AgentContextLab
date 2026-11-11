# BC：VERA完成子集的三重复 mean ± std

沿用上一份快照，零模型调用。只将timeout计0，不把非超时失败、缺评分或缺归档静默记0。

为计算可比较的三重复标准差，每个配置先取VERA三次都正常完成的题目，再成组排除任一方法任一repeat没有可计分结果的题目。每一行五个方法、三次repeat均使用完全相同的题集；各配置题集仍不同。这个范围比上一份按题次选出的VERA完成子集更小，不能直接混用数值。

标准差是三个repeat准确率的样本标准差（ddof=1），单位百分点；不是未知评分上下界，也不是置信区间。

| 配置 | 题数 × repeat | No Compression | Discard-All | Summary | Sliding Window | VERA |
|---|---:|---:|---:|---:|---:|---:|
| Gemini + Hermes | 12 × 3 | 91.67 ± 8.33 | 94.44 ± 4.81 | 94.44 ± 4.81 | 97.22 ± 4.81 | 100.00 ± 0.00 |
| DeepSeek + Hermes | 58 × 3 | 93.10 ± 3.45 | 86.78 ± 3.59 | 93.10 ± 1.72 | 93.68 ± 1.00 | 95.98 ± 1.00 |
| DeepSeek + DSH | 39 × 3 | 92.31 ± 2.56 | 88.89 ± 3.92 | 93.16 ± 5.34 | 90.60 ± 5.34 | 95.73 ± 1.48 |

## 样本覆盖

| 配置 | 原VERA完成题次 | VERA三次均完成题数 | 排除不可计分题 | 最终同题数 |
|---|---:|---:|---:|---:|
| Gemini + Hermes | 218 | 53 | 41 | 12 |
| DeepSeek + Hermes | 226 | 61 | 3 | 58 |
| DeepSeek + DSH | 198 | 48 | 9 | 39 |

Gemini大量原始归档缺失，最终仅12题；100±0只表示这12题的三次记录均答对，不代表总体没有方差。按VERA是否完成筛题仍有选择偏差。

## 三配置同一题集的补充结果

跨三配置再取交集，仅剩8道题，每道题3次。

| 配置 | No Compression | Discard-All | Summary | Sliding Window | VERA |
|---|---:|---:|---:|---:|---:|
| Gemini + Hermes | 95.83 ± 7.22 | 100.00 ± 0.00 | 100.00 ± 0.00 | 100.00 ± 0.00 | 100.00 ± 0.00 |
| DeepSeek + Hermes | 91.67 ± 14.43 | 95.83 ± 7.22 | 95.83 ± 7.22 | 100.00 ± 0.00 | 100.00 ± 0.00 |
| DeepSeek + DSH | 95.83 ± 7.22 | 100.00 ± 0.00 | 91.67 ± 7.22 | 95.83 ± 7.22 | 100.00 ± 0.00 |

## 每个repeat的原始正确数

- Gemini + Hermes / none: [12.0, 10.0, 11.0] / 每次12题；timeout计零数0。
- Gemini + Hermes / discard: [12.0, 11.0, 11.0] / 每次12题；timeout计零数0。
- Gemini + Hermes / summarize: [11.0, 11.0, 12.0] / 每次12题；timeout计零数0。
- Gemini + Hermes / sliding_window: [11.0, 12.0, 12.0] / 每次12题；timeout计零数0。
- Gemini + Hermes / visual: [12.0, 12.0, 12.0] / 每次12题；timeout计零数0。
- DeepSeek + Hermes / none: [56.0, 54.0, 52.0] / 每次58题；timeout计零数0。
- DeepSeek + Hermes / discard: [52.0, 51.0, 48.0] / 每次58题；timeout计零数1。
- DeepSeek + Hermes / summarize: [54.0, 55.0, 53.0] / 每次58题；timeout计零数2。
- DeepSeek + Hermes / sliding_window: [54.0, 54.0, 55.0] / 每次58题；timeout计零数0。
- DeepSeek + Hermes / visual: [56.0, 55.0, 56.0] / 每次58题；timeout计零数0。
- DeepSeek + DSH / none: [37.0, 36.0, 35.0] / 每次39题；timeout计零数2。
- DeepSeek + DSH / discard: [33.0, 35.0, 36.0] / 每次39题；timeout计零数7。
- DeepSeek + DSH / summarize: [34.0, 38.0, 37.0] / 每次39题；timeout计零数2。
- DeepSeek + DSH / sliding_window: [37.0, 33.0, 36.0] / 每次39题；timeout计零数5。
- DeepSeek + DSH / visual: [38.0, 37.0, 37.0] / 每次39题；timeout计零数0。

完整成员哈希、排除理由、各repeat准确率及源文件SHA：`outputs/analysis/bc-vera-success-avg3-v1/report.json`。

## 保持上一表原始VERA完成题次集合

以下仅VERA自身评分齐全，可在原集合上直接计算三次repeat准确率的mean±std。各repeat题集不同，std同时包含题集组成变化；其他方法存在缺日志、缺评分或非超时失败，按仅timeout=0的规则无法给出原集合上的唯一数值。

| 配置 | repeat 1/2/3 分母 | VERA mean ± std (%) |
|---|---|---:|
| Gemini + Hermes | 72/74/72 | 74.30 ± 3.02 |
| DeepSeek + Hermes | 77/72/77 | 91.16 ± 2.63 |
| DeepSeek + DSH | 69/69/60 | 91.43 ± 1.46 |
