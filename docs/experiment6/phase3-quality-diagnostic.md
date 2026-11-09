# Phase3 质量暂停与零付费诊断（2026-11-09）

**当前状态：quality_hold，未完成原10题研究，不能报告有效视觉 QA 比较。** 05:53:02 UTC，在最后一条已开始请求自然返回并保存 response.json、确认在途为0后暂停评估。最终41次 started/41次 response，5次旧上传失败 usage 未知；36次有计量请求全部守恒，无新增模型诊断调用。原26次调用证据哈希未变；原科学脚本、manifest、图像和输出预算均未修改。

已知 token 小计：cached input512、non-cache input238,837、output158,108、total397,457。包含失败重建、摘要生成与 judge 等研究开销，缺失5次不可补0，实际美元未知。proxy1 的15次新请求均完整返回HTTP200；这只证明上传恢复，不等于可读性/评测有效性恢复。

## 原始响应对照

以下直接审计 raw response，包含暂停前最后完成、尚未来得及进入逐条件汇总的 q017/1x QA；因此原 `results.json` 只有11个条件，不能用它漏计最后调用。

| 输入/任务 | 已发调用 | HTTP完成且有内容 | 截断/无内容/失败 |
|---|---:|---:|---|
| 完整画布 QA | 7 | 0 | 5次HTTP200，但 output=reasoning=8192、finish=length、final content为空；2次旧上传失败 |
| 完整画布重建 | 7 | 1 | 3次HTTP200同样8192全耗于reasoning且无final；3次旧上传失败；1次正常stop但明确无法可靠读取 |
| 完整原文 QA | 3 | 3 | 全部finish=stop，有最终答案 |
| 摘要 QA | 2 | 2 | 全部finish=stop，有最终答案 |
| 完整原文重建 | 3 | 3 | 均finish=length，但已有较长final content；属于重建截断 |
| 摘要重建 | 2 | 2 | 全部finish=stop，有最终文本 |

这不是 JSON parser 丢掉已有答案：五次完成的视觉 QA 原始 `choices[0].message.content` 就为空，原始 usage 显示8192 reasoning tokens。结构化答案尚未生成，解析器没有可解析内容。

q017/1x 重建原始响应正常stop（output3083，其中reasoning3008），明确表示所给图像的文字分辨率/压缩程度不足，无法可靠还原完整名称、数字、URL和表格，继续生成会需要猜测。这是应保留的**负面可读性证据**，不能仅归为网络或解析故障。模型自述不是独立客观测量，但与先前视觉条件无最终答案一致，足以阻止继续按“正常有效研究”消耗剩余预算。

完整原文重建也有截断，说明重建输出规模本身受预算约束；视觉 QA 无最终输出又比文本 QA 更严重。现有证据不足以分离图像密度、provider内部缩放、detail策略、推理模式、提示和输出预算的贡献，更不能断言把8192调大就修复。

## 图像与本地参数证据

保留实际完整画布及原detail；例如 q004 三页为 low/low/high，q017首画布1015×3393且detail=low。本地原图看得清，不等于 provider 在low detail或内部缩放后看得清。没有为改善结果裁切、替换画布、改变detail或选择更容易的片段。

检查了现有 `configs/tokenhub.dsh.patch.yml`、研究配置以及保存的 TokenHub 模型目录 `outputs/preflight/tokenhub-routes-20261108T110747Z/routes.json`。模型目录只证明相应模型 ID 和 OpenAI endpoint 支持；没有提供该路由关闭thinking的参数定义或已验证配置。本次不能据此臆造 `enable_thinking`、`reasoning_effort` 等参数并试发。

## 后续候选协议，仅待审，不执行

1. 保留现有版本的未完成、上传失败、拒答与截断，不补写成功。当前结果可报告可行性/失败边界，不能给出有意义的跨尺度准确率曲线。
2. 若继续，先冻结一个明确的新协议和同一题五臂小pilot，沿用已冻结事实、完整原文、已有摘要与全部实际画布；五臂统一输出预算、同一提示和模型路由，无择优替换旧记录。先验收最终内容/有效QA，再考虑扩队列。
3. 增大统一输出预算、经文档确认后关闭thinking、提高detail、保持全内容的图像分块都是**不同的候选干预**。不能同时改变后把效果归因于其中之一，也不能把新的布局当原实际压缩策略。提高detail/分块不是当前科学结果的“无影响运维修复”。
4. 当前没有批准或启动新的付费pilot。新入口应在每次尚未开始的调用前检查停止标记；已发请求完成后才暂停，任何旧 unknown/failed 调用都不得自动重发。

## 可复查文件

- `outputs/experiment6/shared-full-canvas-phase3/quality-hold.json`：安全暂停时间、进程身份、41/41调用、在途0。
- `quality-diagnostic.json`：逐调用原始状态、final长度、reasoning/output计量与最终live快照。
- `calls/*/{started,request-manifest,response,raw-response}.json`：原始证据；缺原始响应的上传失败保留unknown。
- `operations/proxy1-20261109/exit.json`：旧调用证据未变，最终41次启动。
- `operations/proxy1-20261109/final-health-20261109.json`：暂停前代理/两harness真实图像与工具抽样。核心队列仍由主控运行，信息损失的暂停不影响核心实验。
- `live-status.json`：只读observer最终更新为quality_hold、worker_alive=false、inflight0。执行器旧 `status.json`/`results.json`保留当时中间状态，不能据旧running字段宣称仍在运行。

未来运维入口 `scripts/info_loss_phase3_ops2.py` 已加入启动前及每次调用前的 quality-hold/STOP gate，存在标记时不会创建 started 或发送请求；两项离线测试通过。它不是新科学协议，未启动；当前暂停标记未移除，不能用此入口自行重开研究。
