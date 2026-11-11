# BC 完整100×3：失败与超时计0

不再筛选任何成功子集。每种方法固定100题×3次；每次分母100。执行失败及整题timeout计0，正常完成使用绑定评分。std是三次准确率的样本标准差（ddof=1），单位百分点。采用现有保留完成结果与合法失败恢复后的当前结果，每题次计一次。

此前两条完成轨迹的评分URLError已独立恢复：Hermes none q025r03=1；DSH summary q029r01=0。仅新增2次评分API、2080tokens，无预测重跑；原错误和未知历史成本均保留。

| Harness | 方法 | r1/r2/r3正确数（各100题） | mean ± std (%) | timeout r1/r2/r3 | timeout合计 | 超时涉及独立题 | 其他失败合计 |
|---|---|---|---:|---|---:|---:|---:|
| DeepSeek + hermes | No Compression | 79/75/74 | 76.00 ± 2.65 | 3/0/0 | 3 | 3 | 0 |
| DeepSeek + hermes | Discard-All | 62/67/61 | 63.33 ± 3.21 | 0/0/1 | 1 | 1 | 11 |
| DeepSeek + hermes | Summary | 76/79/77 | 77.33 ± 1.53 | 5/4/5 | 14 | 11 | 3 |
| DeepSeek + hermes | Sliding Window | 75/72/74 | 73.67 ± 1.53 | 2/0/1 | 3 | 3 | 0 |
| DeepSeek + hermes | VERA | 68/66/72 | 68.67 ± 3.06 | 22/28/23 | 73 | 39 | 1 |
| DeepSeek + dsh | No Compression | 74/65/71 | 70.00 ± 4.58 | 18/16/12 | 46 | 27 | 23 |
| DeepSeek + dsh | Discard-All | 52/58/64 | 58.00 ± 6.00 | 36/29/25 | 90 | 40 | 23 |
| DeepSeek + dsh | Summary | 68/67/71 | 68.67 ± 2.08 | 22/25/20 | 67 | 34 | 13 |
| DeepSeek + dsh | Sliding Window | 72/67/75 | 71.33 ± 4.04 | 19/24/15 | 58 | 35 | 14 |
| DeepSeek + dsh | VERA | 62/64/55 | 60.33 ± 4.73 | 15/28/32 | 75 | 42 | 27 |

Gemini同一100题×3的原始归档不能补齐：None/Discard/Summary/Window/VERA分别缺118/52/57/112/61条记录。已核验summary、conv、history、judge；Window另有3个位置实际为gpt-5.4-mini，不能冒充Gemini。完整Gemini mean±std为NA，不能把缺档认定为已失败并补0。已找到Gemini记录的整题timeout均为0，缺失部分是否超时未知。

完整归档审计：`outputs/analysis/gemini-bc-full300-archive-audit-v1/`。本表输入、逐题分数与SHA：`outputs/analysis/bc-full300-mean-std-v1/`。

DSH summary与visual各有一个清理状态未确认标记，原样保留；本表依照最终预测状态和绑定评分统计，不用清理标记筛除题目。

这份表是完整cohort下的运行结果；恢复版本与时限并不完全统一，不能冒称所有方法在同一新协议下重新运行。
