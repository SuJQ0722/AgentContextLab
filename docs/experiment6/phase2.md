# 实验6第二阶段：多条真实轨迹的完整canvas

第二阶段已启动，固定7道不同问题的真实首次压缩历史：q001、q003、q004、q006、q007、q009、q011。按核心DSH visual目录的qid/source顺序选择，不查看预测正确性；准备时可用且通过gate的7条即冻结，不继续扩规模。它仍不是100题×3的完整benchmark。

## 精确来源gate

DSH原生 `compaction/summary` 保存 `shadowedSeqs`。逐事件恢复实际压缩的message，遵循原插件的system/checkpoint过滤与原renderer的text/reasoning转化。所有7条的 `messages_rendered` 和 `text_chars` 都与原render日志精确相等。原配置全部font16/history_scale1，且没有另行保留的native image evidence；第一压缩无需推测旧canvas的累计历史。

例如q001为33条message/113250计数字符，q003为42条/104731。manifest记录精确序号、compaction ID、原trace快照hash、完整源文本hash、原始attachment SHA256及实际尺寸；后续的未压缩tail没有混入参考原文。3项单测确认：未选tail不进入原文；缺seq/计数不符阻断；native image不能静默当文本。

原始canvas直接读取实际附件，不重新渲染。0.75x和0.5x是同一完整canvas的确定性Lanczos降采样，控制像素分辨率，不冒充原引擎far-only scale策略。DSH附件本身可能经过图像大小处理，保存实际收到的尺寸和媒体类型，不能假设全部仍是原PDF分辨率。

## 配对评估

每条完整历史比较：原文文本control、新生成摘要、原实际canvas、0.75x canvas、0.5x canvas。参考原文采用整个被渲染span，不裁成简单片段。

在实际进入canvas的tool结果中按早/中/晚位置各生成最多两条事实/probe，总计最多六条；必须验证evidence quote是原文子串、答案是quote子串，且问题不直接包含答案。所有表示复用同一事实和问题，记录source step和距压缩时的step数。age是描述性位置变量，不表示因果时间衰减。

每种表示分别重建、Probe QA，并对非空重建做judge。重建和QA输入不含参考答案；judge才看到源文和事实。原图若超时、达到8192输出预算而没有最终内容，保留实际失败，不改用简单片段或自动重试。摘要失败也不以原文代替。完全匹配QA与重建答案子串覆盖率、模型judge结果分别保存；同模型生成和评判的偏差仍存在。

## 预算、并发与恢复

只使用指定DeepSeek模型。单路case/API，给核心16路与RQ3留优先级；可见进程达到100则等候。主编排将它计入辅助并发预算1路，总辅助上限6路。正常路径最多7×19=133请求（3 facts + 1 summary + 5×3 evaluation），代码硬上限200；没有重建文本会跳过judge。

每请求max8192输出tokens、socket timeout180秒，另设360秒墙钟截止。已开始而无返回的调用保留unknown且不重试；返回错误同样不静默重试。启动后实施代码hash检查，source文本也校验hash；单进程锁防重复。每次API返回更新usage小计，每个条件完成更新结果，单case完成写case-status。

```bash
# 已冻结manifest；只读检查无需live
python scripts/info_loss_campaign.py --resume
# 显式live恢复：保留未知请求，不重付费
python scripts/info_loss_campaign.py --live --resume
```

运行目录 `outputs/experiment6/full-canvas-phase2/`：`manifest.json`、`running.json`、`results.json`、`usage-summary.json`、`report.md`、`case-status/`、`calls/`。返回usage缺失仍未知，不能把known subtotal称完整支出；没有网关账单单价时美元未知。

正式论文结论仍需承认可用轨迹筛选、问题数有限、同模型judge偏差、不同表示预算未匹配等限制。七条是独立question来源，不能把每条内部六个probe当作独立benchmark题做显著性放大。

补充解释：完整源历史常有约9–11万计数字符，而重建输出限制8192 tokens，因此重建可能因输出预算而截断；该现象必须与视觉辨识损失分开。Probe QA不要求逐字输出整个历史，作为互补指标。JSON字段 `reconstruction_exact_fact_recall` 实际是忽略大小写的 answer-substring coverage（答案子串覆盖率），不是语义 key-fact recall，数字可能偶然出现，不能单独当作语义事实完整保留的证明；需结合逐事实judge与独立QA，并在正式结果中人工复核。

更准确地说，该重建指标只用 `answer.casefold() in reconstructed_text.casefold()` 判断字符串是否出现，不检查token边界、对应实体、关系或否定。短数字可能嵌在另一个数字中被误计；意译又可能被漏计。所有报告应使用“答案子串覆盖率”标签，保留原JSON字段仅为溯源；不得把它重命名为已完成的semantic key-fact recall测试。正式语义保留判断仍依赖逐事实judge并需人工复核。
