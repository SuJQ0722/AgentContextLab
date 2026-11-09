# 实验 6 phase4：配对质量修复协议

新入口 `scripts/info_loss_phase4.py`，独立输出 `outputs/experiment6/paired-repair-phase4`。旧 phase3 的41次调用、拒读、8192 reasoning 耗尽及所有费用保持原样，不被此版本替换。

## 已知问题与修复边界

旧视觉 QA 的原始 response 没有最终答案，不能归咎解析器；密集画布/low detail 另有模型明确拒读。旧完整原文重建也截断，故仅提高 token 上限不足以分离原因。

[DeepSeek 官方说明](https://api-docs.deepseek.com/guides/thinking_mode/)提供 `thinking: {type: disabled}`；[腾讯 TokenHub 指南](https://cloud.tencent.com/document/product/1823/132248)列出 exact 1017 支持开关。这是参数依据，不代表本研究的自建 SFB 路由已经验证透传。每次记录实际 reasoning token 和 reasoning content 长度，不能把请求字段当作关闭成功的证据。

## 预先固定的两层 gate

固定原10题、原事实/摘要（已存在且可验证者复用）、完整源历史；模型 `deepseek-v4.1-flash-1017/zijian/sfb`。全部方法统一 `max_tokens=8192`、显式禁 thinking、温度0。单并发，全部阶段共最多190次新调用，不因失败重置额度，不启动 Gemini。

1. 固定第一题 q004 的五臂：完整原文、实际1x全画布、全画布0.75x、0.5x、摘要。原画布 bytes/detail 不变；只检查禁 thinking 的效果。五臂都必须 stop 且输出规定的短答案 JSON；原文及1x视觉各至少正确恢复一个已冻结事实。空输出、拒读或1x全 null不能算成功。低尺度有效 null保留为信息损失，不以低尺度准确率选择更容易的题。
2. 若原画布 gate失败，保存全部证据后检查第二个预定义版本：相同 q004、同五臂，所有画布完整分块且 high detail。以1x画布1536行、32行重叠切分，在0.75/0.5画布用对应比例坐标切分，保持各尺度图片数量/顺序一致。所有原页面覆盖完整，逐像素重组与各自输入图完全相等，无重新渲染、无裁掉历史、无选择事实区域。这是**新图像输入布局和 detail 干预**，不能当作原生产画布策略的无影响修复。

第二层仍失败则质量暂停，不扩大队列。gate使用同一题导致协议选择依赖该题：q004保留作开发验收，不能当独立验证。正式解释须优先看余下9题，并同时展示包含gate题的完整透明结果。失败gate仍计入新增费用；禁止选择更有利的一版替换旧结果。

## 配对主队列

通过 gate 后选定同一版本跑全部10题五臂。QA问题完全配对，评估请求无参考答案。重建只见相应表示、看不到事实答案；统一要求**最多1200词的有界事实重建**，不再承诺输出整个历史逐字转录。输出仍8192上限，超词数、length截断、拒答保留。语义judge单独看到参考事实，要求提供重建文本中的逐字证据；同模型judge偏差必须披露，不把词串覆盖称为语义召回。

原始历史距离仅是观察性位置，非因果时间衰减；按分辨率、事实类型、距离报告真实分母和缺失。事实同属题目，不当独立样本；这10题来自文本历史，不是新的多模态benchmark泛化结果，也不是完整 BC100×3。

每个调用有独占 started标记及原始响应，未知/失败不自动重发。请求字节数、全部图SHA/尺寸/detail、客户端HTTP耗时、原始usage与缺失分别保存；实际美元及provider内部延迟没有数据时为空。STOP/SIGTERM让在途响应自然保存后停止新请求。单题三视觉臂中两个以上无法产生有效QA则再暂停，避免把格式失败当正常研究继续消耗。

## 零付费验收

`python -m unittest discover -s tests -p 'test_info_loss_phase4.py' -v`：5项通过，包括实际localhost HTTP请求参数/图片字节、同调用resume不重发、缺缓存字段保留unknown、STOP和未知请求不发送、跨尺度完整像素覆盖、拒读不能通过gate、低尺度null不择优排除。

准备/验收命令：

```bash
python scripts/info_loss_phase4.py --prepare
python scripts/info_loss_phase4.py --resume --live --gate-only
# 仅在gate成功后，沿用同一ledger与manifest：
python scripts/info_loss_phase4.py --resume --live
```

实际状态以独立输出内 `live-status.json`、`gates/*.json`、`selected-protocol.json`、`results.json` 为准。本文不预先声称 gate成功或可读性已修复。

独立只读观察器 `scripts/report_info_loss_phase4.py --watch` 生成 `holdout-analysis/{report.json,README.md,resolution-age.png,pdf}`（有真实观测才画图）。主分析排除 q004，固定其余9题；所有gate费用仍在统一usage中。6项相关测试通过，包括排除开发题但保留其成本、缺失分母上下界。

原厂[视觉输入文档](https://api-docs.deepseek.com/guides/vision/)进一步说明：`low`会先降为512×512；一般视觉编码还会按约1300×1300像素总量缩放大图。约1015×6118的长画布存在内部降采样风险。1536行切块约1.56百万像素，因此选择该尺寸有可读性依据，仍需真实gate验证。此处是原厂规格说明，不是自建SFB网关内部处理的直接观测。

## 2026-11-09 真实验收中的传输隔离

首条原文QA已返回HTTP200、stop、reasoning_tokens=0（3.13秒）。随后原完整1x读取超时、0.75x上传超时，无返回usage。这不能判为视觉不可读。旧phase3曾验证代理上传，但当前核心/RQ3的SFB大图通过gateway NO_PROXY直连，不能沿用旧代理成功经验推断当前可用。

新增独立 `scripts/info_loss_phase4_direct_ops.py` 仅在旧进程完全退出、所有started已有持久response后切换未来未开始请求到直连。原 payload、图像、detail、prompt、model、预算和timeout不变，原失败未知计量和190统一上限保留。运维记录绑定旧每call证据SHA，并检查结束后未变。旧hold归档到operations后才显式恢复；模型身份错误或未决请求拒绝恢复。2项零API测试验证直连移除proxy但保持body/timeout，且原失败响应被篡改会被拒绝。此运维入口不证明质量gate已经通过。

## 精确图片 URL 资格阶段

本机大图在代理和直连都出现上传/读取超时，已于安全边界暂停，旧phase4共7次请求：3次HTTP成功，4次usage未知。没有将这些超时当作视觉能力失败。

独立入口 `scripts/info_loss_phase4_url.py`，输出 `outputs/experiment6/paired-repair-phase4-url1`。沿用已授权Hermes `_upload_imgbb` helper，模型只接收短URL而非大base64 body；图片内容、高detail、prompt、model和8192预算完全相同。每张图片上传后下载，文件SHA和decoded RGBA像素SHA必须同时相等，任一不等便在模型请求前拒绝。首张真实1019×1536 tile已实测通过（9.2秒，零模型调用）。上传/下载时延不计作模型API耗时。

这是显式的新URL资格阶段，固定q004五臂再次测量，作为传输协议比较单独计量；不覆盖或择优替换旧unknown。gate成功后才自动执行固定完整队列。新manifest记录旧7次的证据SHA和剩余183次上限，整个运行持有父root独占锁；总新增研究上限仍190。旧phase3的41次是更早历史，另列成本，不能误以为此次190包括那些历史调用。

主报告以 `holdout-analysis/report.json` 为准：`all_new_usage_including_failed_gates` 是URL阶段，`cumulative_usage_including_local_delivery_failures` 合并旧phase4七次与URL阶段各一次，不重复计费。q004始终从主要九题描述分析中排除。图片URL服务的模型侧下载过程不能被客户端拦截，因此只有真实事实恢复gate成功才可支持最终可读性。

URL准备期间有一次imgbb GET发生SSL EOF，尚未发送图像模型请求。新增 `info_loss_phase4_url_ops.py` 只对非模型上传/下载最多尝试3次，并将成功上传URL写receipt，防止下载重试导致重复上传。模型POST保持单次发送；已有response直接复用，未知推理请求不重发。2项独立测试确认零模型GET可恢复，而模型WriteTimeout不会重试。此恢复不修改冻结URL协议或原科学入口。

进一步零模型诊断确认同图代理上传SSL EOF（3.05秒），直连imgbb上传HTTP200（2.13秒）。采用独立 `info_loss_phase4_url_ops2.py` 后，imgbb上传和下载都走直连；冻结科学入口不改。零模型维护的每图attempt与下次重试时间持久保存，最多12次、2小时，基础退避30/60/120秒，若服务端Retry-After更长则遵守更长时间，超过期限暂停而非提前重试。已有成功上传receipt跨维护部署复用；模型POST依然单次发送。3项测试覆盖跨进程累计次数、Retry-After不被120秒缩短、模型POST不进入恢复循环。

实际URL版1x gate已返回HTTP200/stop、reasoning_tokens=0、4个固定事实答对3个，10张图的模型请求体降至2019字节，耗时10.04秒。这证明该条件存在真实事实恢复；尚不能由此提前声称五臂gate或九题holdout已经全部完成。
