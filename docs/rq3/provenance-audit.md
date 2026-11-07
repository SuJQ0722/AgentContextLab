# RQ3 / Table 5 provenance audit

本审计完全离线，无新增推理、评分或 Gemini 请求。尚未找到投稿论文的 Table 5 与原始运行一一对应的 manifest，以下数据不能直接标成已复现 Table 5。

## 已发现的七档聚合数据

原始来源：`../hermes-agent/preds_archive/visual_setting_recovered_common_success_7scale_metrics.csv`，本目录保存原样副本。其七档为 0x、0.125x、0.25x、0.5x、0.7x、0.8x、1x，各档共同成功子集 N=187，原始准确率为 62.032%、68.449%、64.171%、67.380%、70.053%、70.053%、63.102%。

该 CSV 只有聚合数据，没有共同187条样本的 question / repeat / content hash 或源路径。N=187 是记录数，不能默认是187独立题，也不能把它当成完整100题×3。因此目前只能忠实重绘点估计，无法可靠恢复逐repeat std、配对检验或 question-cluster CI。共同成功筛选本身还可能引入选择偏差。

读取现有研究目录和明确相关归档子目录后，尚未定位这七档的原始 per-run 来源；现有低分辨率Qwen五档不能凭目录名充当该七档来源。需要原始run manifest或导出脚本中的输入路径才能继续对应。

## 现有作图脚本与原值不一致

明确相关脚本 `../visual_setting_figure.py` 写有：

```python
RAW_ACCURACY = np.array([62.0, 68.4, 64.2, 67.4, 70.1, 70.1, 63.1])
ACCURACY_SHIFT = 71.0 - RAW_ACCURACY.max()
ACCURACY = RAW_ACCURACY + ACCURACY_SHIFT
```

即对全部显示准确率加0.9个百分点，且把原始0.125x标签写成0.1x。该偏移不来自原始测量，不能用于实测结果。现存 `../downsample_*.png/pdf` 应在核对后替换为从原CSV重建的版本。本次没有改动或覆盖旧脚本、旧图。

本目录 `raw-aggregate-accuracy.png/pdf` 直接采用原始CSV未偏移的数值和原始scale标签，明确无CI，且不声称已经映射至Table5。重建命令：

```bash
python scripts/analyze_paper_tables.py
```

## 另一组五档Qwen日志

`preds_archive/qwen35-122b-visual-scale{0,0125,025,050,100}/browsecomp_subset_200/judge_metrics.json` 属于另一批模型为Qwen的运行。仅看文件数量不能认为已有有效100×3答案。各档已有大量 `skipped_infer_failed`，并有 `judge_failed`。推理失败没有可评分答案，不能仅补judge修复完整实验。

这些五档的 metadata 尚不能证明它们对应 Table 5，不能与七档聚合数据混用。若以后使用DeepSeek重跑，应单列新模型复现实验，不能将其输出补进历史Gemini或Qwen的重复实验池。

五档元数据摘要（prediction_total / scored / skipped_infer_failed / judge_failed）：

| Scale | Records | Scored | Inference failed | Judge failed |
|---|---:|---:|---:|---:|
| 0 | 297 | 43 | 254 | 0 |
| .125 | 299 | 39 | 260 | 0 |
| .25 | 300 | 51 | 249 | 0 |
| .5 | 300 | 47 | 253 | 0 |
| 1 | 297 | 31 | 239 | 27 |

源文件绝对路径和SHA256保存于 `provenance.json`。
