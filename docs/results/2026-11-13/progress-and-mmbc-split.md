# 进度与MMBC分策略迁移（2026-11-13 UTC）

结果采样：2026-11-13 17:32 UTC（11月14日01:32 UTC+8）。只统计V12补跑空间，不是完整100×3，也不能把新旧恢复代次相加当成独立样本。

|V12补跑队列|计划|正常结束|timeout|其他失败|有效评分|
|---|---:|---:|---:|---:|---:|
|BC Hermes视觉|24|9|14|1|8/9=88.9%|
|MMBC VERA|83|27|41|15|19/25=76.0%|
|MMBC vanilla|63|18|39|6|9/17=52.9%|

VERA补跑有27题恢复为正常结束，但仍有41题超时。此队列选自历史超时题，不能与旧全量超时率直接比较，也不能依据各方法不同有效子集声称准确率显著改善。BC视觉和vanilla有repeat尚无有效评分，不能计算三个repeat的mean±std；VERA有效评分各repeat仅13/10/2，条件mean±std为68.97±16.50%，不是完整avg3。

## 运行状态

17:36 UTC现场查验：RQ3的0.5、0.7、0.75、0.8仍有活动worker。0.25、1.0、BC Hermes视觉与MMBC两视觉队列已经到达终态，但其中有timeout和其他失败。BC DSH视觉仍HOLD，受控baseline和信息损失没有运行。旧云端综合快照停在11月12日16:05 UTC，不能当作实时证据。

RQ3评分存在ConnectError等失败，特别是0.75、1.0的本轮正常完成轨迹没有有效评分；缺失不填0，ready_to_grade=0不意味着全部成功评分。

## 网络故障与迁移

17:39 UTC无模型检查发现历史配置的模型代理拒绝TCP连接。TokenHub直连返回401（接口可达但此次无认证），当前进程已有的替代认证代理也返回401；通过替代代理访问Jina返回200。没有凭该检查宣称模型推理或大图上传已成功。历史失败可能包含网络故障，不能全部归因为视觉压缩。

新部署使用 `scripts/network_entry_v13.py` 显式替换失效代理。实际网络身份写入worker的network-deployment-v13.json；冻结科学代码、模型路由、图像表示、1小时/500轮和累计最多3次不变。代理凭据只存在被Git忽略的私有0600文件，不进入命令参数、文档或提交。历史结果不重写。

## MMBC普通策略独立CCI

旧shared_baselines已停止派发并自然排空在途任务。迁移仅选未领取且工作目录为空的题；已领取164题留在旧空间，845题形成互不重叠的新队列。每份job保留原配置、题目身份与累计尝试账本。旧队列STOP必须保留，不能与新队列共同恢复。

|新队列|剩余题次|部署|并发|
|---|---:|---|---:|
|MMBC Discard-All|159|acl-v13b-mmbc-discard|16|
|MMBC No Compression|185|acl-v13b-mmbc-none|16|
|MMBC Sliding Window|167|acl-v13b-mmbc-sliding-window|16|
|MMBC Summarization|181|acl-v13b-mmbc-summarize|16|
|BC普通策略|153|本机独立控制器|16|

四个CCI均采用8核32GiB、已有私有CPU镜像、afs_agents挂载。已提交并激活；启动后先检查真实search/fetch和依赖，控制器才派发。新队列独立评分及调度观察器已启动。已有V12结果和V13结果必须按题目×repeat×方法合并，不能将旧队列中已迁移的pending重复计入分母。

运行记录：outputs/cloud-runtime/mmbc-strategy-split-v13b/。科学计划保留在seven-page-turns500-v12/cells/*_split_v13b，dispatch_partition_version单独标注迁移。不重新授予失败题尝试额度。

首轮分片V13的配置路径校验在模型调用前失败；四CCI已停，所有claim和日志保留，未启动native worker。V13b物理复制相同字节的config/cohort，重定位路径后重新验证。此操作没有新增科学重试次数。根测试1105项通过（216.027秒）；网络替换和子进程传播的零网络检查通过。
