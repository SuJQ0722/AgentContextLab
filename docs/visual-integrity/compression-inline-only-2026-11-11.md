# 压缩画布仅以内联图片发送

2026-11-11。删除压缩上下文上传图床、上传后下载校验、托管 URL 替换和专用上传重试实现。历史入口只保留明确报错的兼容壳，不读取旧图床缓存、不调用上传、不把旧配置静默改成新实验。Hermes 与 DSH 的运行入口继续使用 `inline_visual_transport_v1` / `dsh_inline_transport_bridge_v1`，在最终请求内保留消息顺序最近10张图（原生图和画布合计），图片字节保持原样。信息损失实验使用 `info_loss_phase4.Client` 已有的 SHA 校验和 data URI 编码；原 URL 实验及运维重试入口停用，旧结果与费用不覆盖。

原生反向图片搜索对本地原图/crop 的上传功能独立保留；它不应被用来托管压缩上下文。`scripts/` 中调用 Hermes `_upload_imgbb` 的唯一剩余工具是原生 crop 搜索预检 `check_imgbb_upload.py`。不要据此承诺整个图床账号不会新增搜索图片。

## 运行批次核查

2026-11-11 16:19–16:22 UTC，只读查询项目86个CCI：4个RUNNING，全部确认使用V7 inline bootstrap和 `transport-v7-two-hour` 目录；其余项目实例暂停。4个是 MMBC VERA、MMBC vanilla、RQ3 0.7、RQ3 0.8。旧图床批次没有正在运行的实例。本机没有正在执行的图床预测worker。

13组V7配置均为 `inline-recent-ten-chunked-v1`、`compression_image_upload=false`。每组最近启动3条轨迹共39条，读取到889条允许发送记录，`hosting_calls` 全部为0。这是发送日志抽查，非图床账户后台的完整审计。旧图床缓存确有上传回执，已检查的最近记录为2026-11-10 18:02:38 UTC（北京时间11月11日02:02:38），不能将旧上传混称为V7上传。

原图床13组、v4图床13组、信息损失URL实验1组，共27个旧运行目录均有STOP标记（本次只新增缺少的1个，不覆盖既有标记）。

为避免正在运行的V7对422个源码文件的绑定校验被破坏，删除在独立开发检出完成并提交dev；当前实验检出仍固定在已核验的inline运行版本。旧快照/历史文件不是新版本的可执行入口，不在已启动实验中热替换。

本地证据：`outputs/analysis/compression-inline-removal-audit-20261111/{wire-audit.json,cloud-apps.json,legacy-stop-markers.json}`。

## 最新两小时版本为什么仍超时

分析仅包含V7执行失败补跑：BC Hermes 71条（12完成、58超时、1其他失败），DSH 96条（12完成、62超时、22其他失败）。不代表完整100×3，也不与旧版本混算速度。

| 超时轨迹指标 | Hermes（58条） | DSH（62条） |
|---|---:|---:|
| 每题端到端中位秒 | 7202.3 | 7202.0 |
| 每题累计渲染中位秒 | 25.55 | 16.05 |
| 每题已记录失败请求耗时之和，中位分钟 | 73.87 | 83.49 |
| 单次失败请求耗时中位秒 | 300.02 | 300.00 |
| 单次已完成发送阶段中位秒 | 0.046 | 0.518 |

Hermes发送阶段是请求体写入时间；DSH为request-start到bodySent，含连接准备，不能等同比较。失败请求计时可能漏掉最后被整题期限中断的请求。只计有耗时记录的失败：Hermes922次，另5条失败事件缺该字段；DSH1106次。渲染、SDK、HTTP、工具计时可能嵌套或并发，不把各项简单相加；服务商内部推理时间仍未知。

Hermes 58条超时轨迹有927次route_failed：ReadError600、RemoteProtocolError175、WriteTimeout61、ConnectError43、ConnectTimeout30、ReadTimeout13、其他5。DSH有1100次传输错误和6次HTTP错误；其中AbortError683次。它们说明现版本的大量时间花在请求失败及重试等待，不能简单归因于PDF渲染慢或图床上传。成功发送阶段的中位数也不能掩盖上传失败的长尾。

工程改进优先级：

1. 修复DSH原生图片offload与外层身份校验顺序冲突；确定性本地拒绝不可包装成连接错误后重复尝试。已有q_048_r01连续6次 `request_sent=false` 的直接证据。
2. 统一SSE完成边界：Hermes当前缓冲到HTTP EOF，DSH检测到`[DONE]`即可结束。增加合法结束帧后连接仍保持打开的测试；现有日志不足以认定这就是ReadError主因。
3. 保留用户要求的四渠道轮换，但记录阶段与实际进展，避免已完成的响应被丢弃后重发；对无响应渠道做可恢复的健康状态/冷却处理。单纯缩短时限只能减少等待，不能证明完成率提升。
4. 在图片工具接收时保存并校验原图，渲染复用本地字节，避免压缩阶段再次下载远程缩略图。MMBC已有TLS EOF导致渲染失败的直接证据。
5. 稳定画布及前缀、缓存无变化页面和图片编码，减少重复处理与潜在缓存失效；收益需实测。当前累计渲染通常是几十秒，单靠渲染优化无法消除两小时超时。

结论：有明确的工程缺陷和优化空间，主要在请求完成判断、错误分类与重试、图片生命周期管理。不能把现有超时全归咎于视觉方法本身，也不能承诺修完后全量准确率等于VERA非超时子集准确率。

证据与可重算脚本：`outputs/analysis/compression-inline-removal-audit-20261111/{bc-v7-timeout-durations.json,audit_bc_timeouts.py}`。本次仅离线分析、测试和运行状态查询，新增模型调用0次。

## 验证

根测试981项通过，144.918秒；命令 `NODE_OPTIONS=--preserve-symlinks python -m unittest discover -s tests -v`。该Node选项仅用于独立检出复用已安装DSH依赖时的测试路径解析。新增测试覆盖Hermes最终wire、DSH真实本地桥接、信息损失inline请求、旧URL缓存/上传凭据无法重新启用托管、退休入口在网络调用前拒绝。旧上传实现的测试随功能退休，由inline与拒绝上传测试替代。最初独立检出缺少历史fixture的错误已通过复制只读fixture解决，未修改运行实验或降低断言。`git diff --check`通过。
