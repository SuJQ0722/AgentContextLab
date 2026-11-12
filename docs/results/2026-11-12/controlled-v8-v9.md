> 历史冻结快照：2026-11-12 10:43 UTC+8。不是当前V12运行状态；本次发布未重算该历史表，也未重新核对价格。最新代次结果见 [当前结果](current-generations.md)，总入口见 [README](README.md)。

# 最新受控 V8 / V9 补充（2026-11-12）

全部只读，未请求模型、未评分、未修复/重试。当前最新实验必须与旧v4/bounded分开列示。

|版本|数据集|方法|计划|校准排除|非校准计划|当前类别|可评正确/有效|
|---|---|---|---:|---:|---:|---|---|
|transport-v8-one-hour-retry5|browsecomp_v3|visual|16|11|5|{'system_timeout_excluded': 5, 'calibration_excluded': 11}|无有效已评分|
|transport-v8-one-hour-retry5|mmbrowsecomp|visual|11|2|9|{'system_timeout_excluded': 9, 'calibration_excluded': 2}|无有效已评分|
|transport-v9-runtime-recovery|browsecomp_v3|summary|15|0|15|{'control_dependency_blocked': 4, 'not_started': 11}|无有效已评分|
|transport-v9-runtime-recovery|browsecomp_v3|window|12|0|12|{'control_dependency_blocked': 4, 'not_started': 8}|无有效已评分|
|transport-v9-runtime-recovery|mmbrowsecomp|summary|11|0|11|{'control_dependency_blocked': 4, 'not_started': 7}|无有效已评分|
|transport-v9-runtime-recovery|mmbrowsecomp|window|9|0|9|{'control_dependency_blocked': 4, 'not_started': 5}|无有效已评分|

V8 27条视觉运行中13条从计划开始就标calibration_not_scored。4条completed全部属于校准，不得重新列作有效accuracy，也不补判；余23条timeout（其中9条校准、14条正式槽）。V9 controlled文本47条：16条blocked，31条没有attempt目录即尚未启动。没有新可评分正式终态，因此本代accuracy为未知而非0。

已检查V8/V9各自alias grader observations及逐job grade文件；本74条无实际grade.json。旧observations给timeout的操作性0不沿用，本次按要求系统剔除。

所有27个V8视觉和47个V9文本指向的control_target_path都未见发布目标文件。部分视觉最后尝试compression-control保存passed/native identity与真实prompt，4条completed校准prompt分别5497、5826、6178、6764；但局部控制通过不等于已发布共享目标，更不等于三臂预算匹配。无V9实际文本continuation，不能据此形成新配对组。缺失原因未进一步推定；本次不生成缺失target、不重派任务。

最新协议明确recent_rendered_text_pages_then_all_native，最多10张图：原生图不得删，必要时明确删掉较旧文字canvas。因此即使引用相同原始prefix，也不能将本代结果与旧完整bounded canvas臂随意合并。各job保存controlled_spec SHA、原parent job/plan、prefix SHA、target路径、最终native control和timeout重试链hash；V9是预先声明的V8 runtime recovery，不是按结果择优。重试不是新seed。

详见 controlled-v8-v9.json/csv、controlled-v8-v9-summary.csv。可复现：`python /tmp/acl-results-20261112/analyze_controlled_v8_v9.py`。本文件是 controlled-information-loss.md 当前受控版本的必要补充。
