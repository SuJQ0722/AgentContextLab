> 本诊断为当天早先固定样本与V11阶段观察，文末运行计数不是当前计数；当前计数见 current-generations.md。

# MMBC ordinary baselines: 797 retained timeout lineages

793来自原始1800秒/60轮协议，4来自后继V9。不是797个当前新版失败。

固定每种策略取原始队列按question_id/repeat排序的前2条，共8条诊断样本；非随机抽样，不将比例外推到797。

| 策略 | 题次 | Wall秒 | API成功/记录 | 连续末尾API错误 | 错误类型 | 失败调用中位秒 |
|---|---|---:|---:|---:|---|---:|
| none | mmbc_001/r2 | 1802.5 | 0/5 | 5 | {'APIConnectionError': 5} | 300.09015352651477 |
| none | mmbc_001/r3 | 1802.0 | 0/5 | 5 | {'APIConnectionError': 5} | 300.08642879873514 |
| discard | mmbc_001/r2 | 1804.9 | 0/5 | 5 | {'APIConnectionError': 5} | 300.0926812440157 |
| discard | mmbc_008/r2 | 1802.8 | 9/10 | 1 | {'APIConnectionError': 1} | 300.0894492343068 |
| summarize | mmbc_001/r2 | 1801.7 | 0/5 | 5 | {'APIConnectionError': 5} | 300.07778849825263 |
| summarize | mmbc_001/r3 | 1800.2 | 0/5 | 5 | {'APIConnectionError': 5} | 300.08061968907714 |
| sliding_window | mmbc_001/r2 | 1803.1 | 0/5 | 5 | {'APIConnectionError': 5} | 300.0879869312048 |
| sliding_window | mmbc_008/r1 | 1811.3 | 6/8 | 0 | {'APIConnectionError': 2} | 300.08397174440324 |

其中6条都是同一道mmbc_001的跨策略/重复：连续5次约300秒连接错误且无成功响应，支持API连接等待消耗30分钟期限；另2条mmbc_008有成功响应和失败混合，不能把整条超时都归连接错误。8条样本仅2道独立题，不外推故障比例。APIConnectionError没有底层Write/Read/429细分证据，不能断言原图太大上传造成。旧样本未记录工具耗时和实际round数，不能说100轮耗尽；max_rounds配置为60。完整证据路径和末尾3条调用在JSON中，零付费调用。

当前V11轻量状态核对（仅普通MMBC）：797题次中1 completed、14 started无终态、782 pending。抽3条已启动轨迹（discard/none/window的mmbc_001_r01）共20条模型响应、0已记录错误；最后单次调用约194–222秒。因此连接已可用但仍慢，不能说797都验证正常。
