> 历史冻结快照：2026-11-12 10:43 UTC+8。不是当前V12运行状态；本次发布未重算该历史表，也未重新核对价格。最新代次结果见 [当前结果](current-generations.md)，总入口见 [README](README.md)。

# 受控 baseline 与信息损失：仅现有日志，2026-11-12

本报告未调用模型、未重试、未补判。未知和未评分不填0；系统超时/网络错误剔除，明确步数耗尽才计0。受控原配置上限60 rounds，不假称100步；本次没有从日志识别出明确步数耗尽终态。旧grader的“任何执行失败=0”不沿用。

## 受控实验

旧v4（包括显式授权ops2/ops3恢复）与新bounded分页协议分开。仅按预先写定的attempt-selection账本选中尝试，不按答案择优；新bounded不拿旧v4成功题填空。两代都是固定两benchmark各10题×3×3臂，未实现三个多模态benchmark完整泛化。

|版本|benchmark|方法|有效已评分|正确/有效|系统剔除|预算匹配失败|未知失败|未运行|已评分且组预算匹配|
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
|controlled-native-v4|browsecomp_v3|visual|5|5/5|20|0|0|5|4/4|
|controlled-native-v4|browsecomp_v3|summary|8|7/8|8|4|0|10|7/8|
|controlled-native-v4|browsecomp_v3|window|11|10/11|9|0|0|10|8/9|
|controlled-native-v4|mmbrowsecomp|visual|1|1/1|13|0|1|15|1/1|
|controlled-native-v4|mmbrowsecomp|summary|4|2/4|3|3|0|20|2/4|
|controlled-native-v4|mmbrowsecomp|window|6|4/6|4|0|0|20|3/5|
|controlled-native-bounded-v1|browsecomp_v3|visual|7|5/7|18|0|0|5|1/1|
|controlled-native-bounded-v1|browsecomp_v3|summary|1|1/1|6|10|0|13|1/1|
|controlled-native-bounded-v1|browsecomp_v3|window|6|6/6|11|0|0|13|1/1|
|controlled-native-bounded-v1|mmbrowsecomp|visual|0|0/0|15|0|0|15|0/0|
|controlled-native-bounded-v1|mmbrowsecomp|summary|3|2/3|4|4|0|19|2/3|
|controlled-native-bounded-v1|mmbrowsecomp|window|3|3/3|8|0|0|19|3/3|

这些正确率只描述各自可用子集，分母不同，不是同题公平排名。

- controlled-native-bounded-v1/browsecomp_v3：三臂全部有效且预算匹配仅 1 组，visual/summary/window 正确数 [1.0, 1.0, 1.0]。
- controlled-native-bounded-v1/mmbrowsecomp：三臂全部有效且预算匹配仅 0 组，visual/summary/window 正确数 [0, 0, 0]。
- controlled-native-v4/browsecomp_v3：三臂全部有效且预算匹配仅 3 组，visual/summary/window 正确数 [3.0, 3.0, 3.0]。
- controlled-native-v4/mmbrowsecomp：三臂全部有效且预算匹配仅 1 组，visual/summary/window 正确数 [1.0, 1.0, 1.0]。

预算证明逐题保存在controlled-results.csv：provider首个真实prompt、目标token、native哈希、prefix哈希和组gate；不能把只满足16384上限当匹配。图像原生证据要求相同，新增分页/编码版本不等同旧版。

预算不匹配是科学控制失败，独立列出；即便conversation带通用“likely upstream timeout”包装字样，明确BudgetInfeasible终态也不偷归网络故障。旧版3个URLError有网络错误类型，另1个VisualEvidenceError无法仅凭现有摘要确定网络成因，列未知。原始无图MMBC的15个prefix不合资格（45臂），不是图传输失败，不重挑题凑样本。

预测成本只取所选attempt的purpose=agent；budget_calibration与compaction分别保留，不能混成正常预测成本。JSON提供按benchmark/方法/purpose已知token与缺失、缓存、SDK时间。校准已预热缓存；即使从成本剔除校准调用，也不能声称剩余命中率是无校准生产缓存效果。历史失败尝试成本仍在原目录，未被删除，本表非全版本累计账单。

## 信息损失V10与成功复用

V10 manifest及33条复用proof全部hash通过；原始返回model与usage保留，仅接受明确canonical alias。最终逐condition共50槽：{'completed': 26, 'timeout': 12, 'no_terminal_result': 12}。coordinator数组38终态不是50完成。completed是流程状态，仍可能reconstruction finish=length；不能把它当成功重建。

下面只含9个holdout；q004开发题单独留在JSON/CSV。未终态condition中已有成功QA按原第一成功物理响应恢复，单独标qa_partial_condition，不发新调用。语义召回仅使用已有有效judge，不把字符串出现率当semantic recall。

|方法|有效QA条件/9|Probe QA 正确/有效事实|有效重建语义评分条件/9|重建支持事实/可评事实|stop重建/9|
|---|---:|---:|---:|---:|---:|
|text_control|9/9|31/32|7/9|13/25|9/9|
|canvas_1|3/9|7/10|0/9|0/0|0/9|
|canvas_0.75|1/9|4/6|0/9|0/0|0/9|
|canvas_0.5|7/9|4/26|0/9|0/0|0/9|
|summary|9/9|7/32|8/9|8/26|9/9|

0/0表示没有可评结果，绝不是0%召回。视觉所有条件目前没有有效语义评分，因此不能画出可信的1/.75/.5重建召回下降曲线。现有负例、length、timeout和未终态仍逐条件保留。

五臂共同可评Probe QA仅1个holdout题、6事实：text 6/6，1x 6/6，.75x 4/6，.5x 2/6，summary 1/6。这是高度筛选的小样本描述，不是9题结论、显著性或时间衰减因果证据。语义重建五臂共同可评事实为0。

按原fact.distance_rounds输出 information-loss-age-curves.csv / PNG。每点给有效/计划事实分母；缺失点不补0，不连推不可观测趋势。相同轨迹内多个事实不能视作独立题做置信区间；本报告不做此伪重复推断。

V8/V9/V10图像协议是最多10张、2048px非重叠cuts；它与早期phase4 URL版7–13张1536px tiles协议不同，因此未把早期成功画布分数并入V10。所有复用仅以manifest明确proof为准。短窗口bounded-window等开发诊断亦不替换完整历史任务。

## 复现和产物

```sh
python /tmp/acl-results-20261112/analyze_controlled_info.py
python /tmp/acl-results-20261112/write_controlled_info_report.py
python /tmp/acl-results-20261112/analyze_controlled_v8_v9.py
```

分析只读AFS，全部写/tmp；可随snapshot变化重新计算。结果文件：controlled-results.json/csv、controlled-summary.csv、controlled-paired.json；information-loss-results.json、conditions/summary/facts/age-curves/paired.csv、age-curves.png。JSON保留精确证据路径/hash，不公开原始题目、答案或请求内容。

## 最新 V8 / V9 当前实验补充

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
