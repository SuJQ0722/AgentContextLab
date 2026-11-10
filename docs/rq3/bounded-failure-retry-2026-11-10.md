# RQ3：最新版分页实现下的失败/超时恢复

用户授权使用最新版实现，将原RQ3所有失败/超时各重跑一次。选择依据实际execution status，不依据答案正确性；正常完成的873条全部保留，包括61条答错及9条缺评分。

|scale|旧timeout|旧failed|新增一次尝试|正常完成保留|
|---|---:|---:|---:|---:|
|0|155|4|159|141|
|.25|157|6|163|137|
|.5|174|3|177|123|
|.7|186|6|192|108|
|.75|170|6|176|124|
|.8|176|2|178|122|
|1|177|5|182|118|
|合计|1195|32|1227|873|

## 故障证据与因果边界

逐条核验来源result、身份、清理状态和SHA后发现：1195条timeout仅1条没有成功compression记录；1227失败/超时中1213条发生在成功压缩之后。1211条发送过最长边>2048的压缩后图片，656条>8192；最大单图1016×31397、PNG14,354,134 bytes。最大请求的图片base64合计下界28,702,228 bytes，不含文本、schema或JSON开销。

SDK观测的3136次错误中3024次发生首次成功压缩后，主要2927次APIConnectionError，另有APITimeout、RateLimit、PermissionDenied等。压缩后的集中失败及巨图共同出现，是修复图像管线的强证据；仍不能证明每次超时都由图像引起，也不能把SDK错误次数说成provider物理请求数。完整审计`outputs/preflight/rq3-failure-retry-audit-v1/{report.json,records.jsonl,failure-details.jsonl}`。

## 独立新协议

新root：`outputs/campaigns/rq3-bounded-failure-retry-v1`。
Plan SHA256：`50c2c8b2babc26e2d8d7b9da32ce6ad61767a86b889cf2258b54bf1f9baa0d5a`。

`rq3-bounded-pages-v1`保留0/.25/.5/.7/.75/.8/1各档，先以1024×2048、16pt/72dpi固定源页排版，再对far逐页真实缩放；不先放大再缩回。recent保持1.0，但同样独立分页、禁止纵向拼接，所有页high detail。0×只显式省far，省略消息/图像数量与SHA另记；不能将retained-region coverage误称全历史保留。

每页以lossless WebP传输，逐像素核验；原PDF、PNG、最终WebP、页序和编码耗时有完整来源链。原生head/tail图不改字节。最终精确JSON≤8MiB、≤32图，canvas边长≤2048、面积≤2097152，超限失败而非静默删除。工具仍只有search/fetch/image_search/crop/zoom，无模型文件读取或shell工具。新公开cohort只含id/question，旧cohort里的参考答案复制到隔离评分目录，不进入新worker输入。

新调用使用当前配置`deepseek-v4.1-flash-1017/huoshan/huoshan`；旧RQ3是`deepseek-v4.1-flash-1017/zijian/sfb`。因此新旧除了renderer还有显式渠道变化。报告分别列原300/档、失败子集的新结果、按固定执行状态替换的恢复结果。恢复结果混合协议，不能冒充“仅分辨率不同”的完整新实验；不以成绩好坏选择旧/新attempt，也不循环重跑至正确。

## 并发、恢复与评分

每档单独一个8核32GiB CCI、16预测worker，指定原私有镜像和`afs_agents`挂载，七档合计112容量。与在跑MMBC共用128推理容量预算，预留4个评分槽。release watcher按MMBC未确认终态任务数计算保守上界，先放行可容纳的分辨率，之后自动放行其余独立markers；不会依据瞬时active数错误超售容量。112/128指模型任务容量，不是OS进程数。

每条只有一个新编排attempt；永久claim不会自动回收，native/SDK既有有限API重试仍逐次记账。SIGTERM/STOP停止派发并自然等待；只在确认对应UID、镜像/命令、计划、controller退出、所有任务清理且无残余slot后暂停本次CCI。

评分器最多2并发，独立结果与判断账本；失败且清理确认计0，unknown保持缺失。新raw token计量包括cached/non-cache/output、缺失usage、渲染/编码耗时；SDK/HTTP耗时不当成provider latency。旧成本报告及15条历史paid-interruption的原/重试记录保留，不重复相加；在完整去重重聚合前不声称有已知的新旧总费用。USD仍未知。

旧RQ3成绩和显著性报告不覆盖；9条原已完成但评分缺失的预测不在这1227条重跑清单内。

本轮根目录643项测试通过（116.12秒）；新评分器另7项测试通过。新计划的gold隔离、失败状态选择、七档配置、scale0语义、source/page/codec校验、CCI容量放行与安全收尾均有测试覆盖。
