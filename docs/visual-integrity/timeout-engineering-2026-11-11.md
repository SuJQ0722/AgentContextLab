# 视觉超时：版本核对、全量审计和工程修复

本页审计的是已结束的 MMBC `mmbc-vera-bounded-retry-v1`，不是最近10图版本的评测结果。原始失败、费用、评分及冻结源码未被覆盖。

## 哪次修复已经补跑

274条补跑已使用 `bounded-multimodal-pages-v1`：独立分页、远历史0.75x、近期1x、禁止纵向拼接、画布最长边2048、lossless WebP、整包8MiB限制。仍使用32图上限，历史实际最多21图。后来“只发最近10图”的实现只做过离线验证，未部署到这批补跑，因此不能说这批结果证明最近10图无效。

## 224条超时的实测

| 指标 | 观测值 |
|---|---:|
| 没有产生 bounded 画布的超时轨迹 | 78/224，34.8% |
| 出现请求 guard 拒绝的超时轨迹 | 0/224 |
| 已结束 SDK 调用记录 | 2,994 |
| 其中 APIConnectionError / APITimeoutError / ReadTimeout | 461 / 23 / 2 |
| 每轨迹已结束 SDK 调用耗时之和，中位数 / p90 | 1,559.42 / 1,679.57秒 |
| 未压缩的78条轨迹，上述耗时中位数 | 1,588.29秒 |
| 486次出错调用耗时，中位数 / p90 | 299.93 / 300.02秒 |
| 2,508次成功调用耗时，中位数 / p90 | 58.47 / 215.44秒 |

每题上限1800秒，已结束SDK调用耗时不含最后被总期限终止的调用。上述是客户端SDK耗时，不能当作provider内部计算时延。已知成功调用output共2,398,865 tokens，其中reasoning2,047,589（85.4%）。这些观测说明网络/API等待及成功推理耗时占主要部分；无法从旧日志精确拆出上传、等待响应头、模型内部计算各自占比。

另有16种超8MiB请求各被重复拒绝6次，最终属于failed，不在224条timeout内。它们是确定性本地失败，旧通用错误恢复逻辑不应重试。不能把6次都解释成OpenAI SDK默认重试；Hermes恢复路径也参与。

## 独立工程版本

入口 `scripts/hermes_mmbc_transport_worker_v2.py`，配置 `configs/experiment.mmbc-transport-v2.json`，不修改冻结 harness 或旧 worker。

- 在最终发送处保留messages/content顺序最后10个图像块，原生图与画布一起计数；保留图片字节不变，不再拼接。
- 在保留后继续执行8MiB和画布几何/来源检查。确定性guard拒绝以明确失败退出，不经过通用重试循环。
- SDK内部重试设0；同一请求体最多允许2次失败发送，成功后清除该请求的失败计数。上层可以重试，但超过限额即明确失败，未另加重试循环。
- 显式连接10秒、上传45秒、读取120秒、连接池10秒。stream预算300秒在收到chunk时检查，阻塞读取仍受120秒限制，所以不是精确的300秒硬墙；外层任务期限继续有效。缩短等待不能当成成功率提升证据。
- 添加客户端连接、上传、响应头、首响应字节、stream完成/错误日志；不输出凭据、URL或请求内容，缺usage记未知。
- 复用已验证画布注册表；任一依赖新增、移除、文件身份或时间戳变化均重新验证。文件时间戳的2秒更新窗口内不使用缓存，以兼容粗粒度时间戳。校验失败不会返回旧缓存，禁止symlink绕过。

同一真实案例 `mmbc_195_r01` 的44个图片哈希，完整首次校验3.399秒，缓存后0.0956秒、0.0071秒，集合一致。这是局部校验加速，不是整题吞吐测量。证据：`outputs/preflight/visual-transport-engineering-v2/registry-profile.json`。

## 验证与适用边界

真实localhost HTTP + OpenAI SSE测试覆盖usage保留、3次相同成功请求不误触失败预算、断流失败预算、SDK重试禁用、确定性guard只执行一次、其他endpoint和web请求不受影响。worker组合入口也有测试。缓存测试覆盖同尺寸修改并恢复mtime、依赖新增/删除、验证中突变和验证失败。

`scripts/visual_transport_diagnostic_v2.py` 默认仅离线准备；`--live`最多2次真实调用、每个固定probe只发一次。先短文本连通性，再使用旧冻结读图诊断的10页真实历史，输入加一张较早的重复图，检查最终11→10。关闭thinking、降低输出预算仅用于这项读图诊断，不改变正式实验模型参数，也不能用于比较正式任务速度或准确率。

诊断结果入口：`outputs/preflight/visual-transport-engineering-v2/live-diagnostic/`。工程版没有启动整批新评测；旧批结果不能被重新标记为此版本结果。

实际两次诊断：短文本2.103秒完成，input9/output1/total10；10页读图最终wire确认11→10、5,280,272 bytes，47.019秒后APITimeoutError。底层trace明确为 `http11.send_request_body.failed / WriteTimeout`，上传阶段45.003秒；没有收到响应头，usage未知。这个案例已定位到上传请求体，不能归因于模型看不懂图。测试没有证明缩短超时改善完成率。随后独立验证保留原图片字节的imgBB URL传输，结果单列，不覆盖此失败。

此阶段根测试787项通过（134.057秒），不包含后续新增URL传输测试。

## URL传输：同图实测

新增可选入口 `scripts/hermes_mmbc_hosted_worker_v3.py` / `configs/experiment.mmbc-hosted-v3.json`，根 `configs/experiment.json` 登记该工程版本。先保留最近10图并执行原有内嵌字节/几何检查，再通过现有授权的Hermes imgBB上传；下载逐图验证原字节SHA及解码像素一致，才把URL放到请求。图片不重编码、不缩放、不拼接。上传回执先持久化；下载验证失败不会自动重复上传，也不静默回退到大内嵌请求。每次使用记录来源SHA、下载SHA、URL哈希以及最终请求SHA；原始URL只存在本地托管缓存中。

10张图全部上传并下载验证通过。复用已验证托管缓存后，实际模型请求从 **5,280,272 bytes缩至1,708 bytes**，最终仍为10图。模型API调用客户端墙钟 **8.592秒**，其中请求体上传 **0.00139秒**，等待响应头 **7.580秒**；返回stop及原始usage：cached0、non-cache7213、output56、total7269。此8.592秒不包含提前上传/验证的成本；托管开始到全部验证完毕的71.417秒跨度还包含主代理调度间隔，不作纯网络耗时。

三个阅读字段中ASIN和zoom crop尺寸正确，第一条搜索结果标题不符，即 **2/3字段匹配**。不能说事实读取全部通过，更不能把这个小诊断当作整题成功或吞吐提升倍数。它证明这次5.28MB上传失败可以通过字节相同的托管URL路径完成请求和读图。

三次模型诊断合计：短文本成功1次、内嵌10图上传超时1次、URL10图成功1次，无自动模型重试；两个有usage响应合计7279 tokens，上传超时那次usage未知。缓存和上传失败处理均有独立测试。新入口仍未启动整批benchmark补跑，历史统计没有换版本。

URL原始记录：`outputs/preflight/visual-transport-engineering-v2/hosted-diagnostic/{uploads-result.json,model-probe/result.json,model-probe/hosted-images-wire-v3.jsonl,model-probe/transport-phases-v2.jsonl}`。可复查入口 `scripts/visual_hosted_diagnostic_v3.py` 默认只检查本地已验证缓存；已尝试的付费诊断不会被脚本自动重放。

最终检查：根 `python -m unittest discover -s tests -v` 793项通过（137.341秒），随后新增v3 worker来源标记及组合路径2项测试通过（0.510秒）。真实诊断上传10图全部字节验证通过，API三次尝试及缺失usage完整保留。

原始审计依据：`outputs/campaigns/mmbc-vera-bounded-retry-v1/jobs/hermes/visual/*/attempts/attempt_001/native/metrics/{calls.jsonl,bounded-request-guard.jsonl}`，以及 `outputs/preflight/bc-dsh-bounded-audit-v1/{mmbc-timeout-sample.json,mmbc-failed-guard-summary.json}`。
