# 当前调度快照

归档：2026-11-12 19:42:13 UTC+8。PROGRESSING表示平台仍在准备/排队，不算已开始推理；RUNNING同样需结合worker/usage。此页不是实时看板。

|队列|平台/状态|已观测活动worker|
|---|---|---:|
|rq3_scale_0250|PROGRESSING|0|
|rq3_scale_0500|PROGRESSING|0|
|rq3_scale_0700|PROGRESSING|0|
|rq3_scale_0750|PROGRESSING|0|
|rq3_scale_0800|PROGRESSING|0|
|rq3_scale_1000|PROGRESSING|0|
|bc_hermes|RUNNING|16|
|mmbc_vera|RUNNING|16|
|shared_baselines|local|16|
|mmbc_vanilla|local|16|
|bc_dsh|HOLD: inline_preparation_failure|0|
|rq3_scale_0000|no eligible V12 jobs; retained V10/V11 results|0|

每个可运行队列上限16；V12每次3600秒、500个原生agent轮次、累计最多3次尝试（包括V10/V11本轮已用次数）。仅timeout可自动重试，普通failed不重派。当前BC DSH视觉独立故障未修复，继续HOLD；RQ3零档没有可续跑任务，不开空实例。

受控baseline、信息损失、cache-aware变体及AST/GUI不在本轮V12派发范围。历史Gemini不重跑。
