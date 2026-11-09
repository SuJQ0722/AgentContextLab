# MMBC-100：独立评分与三轮统计

入口为 `scripts/judge_mmbc100.py`。默认是零 API dry-run；只有 `--live` 才会评分。预测和评分均固定 `deepseek-v4.1-flash-1017/huoshan/huoshan`，不切到 SFB。默认评分并发 2，可设置 1–4。

```bash
python scripts/judge_mmbc100.py --root outputs/campaigns/mmbc100-hermes-deepseek-v1 \
  --gold-root outputs/grading/mmbc100-hermes-deepseek-v1 \
  --output outputs/grading/mmbc100-deepseek-hermes-v1

# 由主调度在核验 dry-run 后启动；这里只记录启动命令。
python scripts/judge_mmbc100.py --watch --live --concurrency 2
```

公共 cohort 只有 question_id、question、image。私有标准答案来自 `--gold-root/private/selected-source.jsonl`，由 `source-map.json` 绑定其 SHA 与公共 cohort SHA；不会复制进预测目录、工具输入或模型工作区。评分 namespace 权限 0700、请求和结果文件 0600；只有评分请求包含标准答案。执行前检查固定 100 题 × 3 repeats × 五方法（none/discard/summarize/sliding_window/visual），模型、问题、原始 image 列表与 plan 一致；每条成绩绑定 result、prediction、question、plan、private-source SHA。任何已绑定内容变化均拒绝继续。

评分复用 `judge_bc_v3_completed.grade` 的 Hermes answer-equivalence 提示、严格 numeric JSON score 0/1 解析、原始 usage 与单次请求日志。空的 completed 答案按预先规定计 0、不发 API。非空答案每条最多一次请求：started 但未返回、HTTP 错误、解析错误都保留 missing，永不自动重试。额外要求 judge finish=stop 且响应 model 为精确版本的已知别名；否则不接受分数。终态 failed/timeout 仅在 slot_released=true 且 unconfirmed_child_termination=[] 时计操作性 0。interrupted/not_started、清理未确认、未知与评分失败都不填零。

`--watch` 只派尚未评分的 completed 结果，SIGTERM 停止新派单并等待已有评分结束。当全部预测有确认清理的终态且没有可评分候选/在途评分时退出；评分错误可以继续显示 missing，不为了凑齐 300 重试。预测工作仍未知或无终态时继续观察。局部评分异常写 `local-error.json` 并保留缺失，避免不断重派。

统计包括全部 100 题、初始有图 69 题、初始无图 31 题三个预先定义范围；无初始图并不代表轨迹中没有检索图。每种方法在该固定范围所有三轮都有分数后才报告三个 repeat accuracy 的 mean ± sample std。置信区间按 question 聚类 bootstrap，每个抽中的问题带上其三个 repeat；视觉方法分别与四个 baseline 做同题同 repeat 配对，检查 question SHA。四项 sign-flip 检验在每个范围内做 Holm；两个子组是探索性分析，未声称对全部 12 项比较同时控制错误率。缺失期间显示已知分母和 accuracy 上下界，不挑全部成功交集，也不发布完整均值。

资源统计从每 attempt 的原始 metrics 重建，并将预测和 judge 分开。`call-starts` 无对应 `calls` 的请求计未知；cached 字段缺失不填 0，按每次响应检查 token 守恒。已知 token 小计、缺失字段次数、完整总数分别输出。cached token 比例仅使用同时观察到 prompt/cache 的请求。压缩次数按事件 count_delta；渲染耗时和 instrumentation coverage、search/fetch 缓存 hits/misses/unknown 分开记录。SDK client 时间包含 SDK 内部重试，绝不是 provider 内部延迟；没有真实价格时美元成本保持 unknown。未记录 compression/render 事件并不自动证明无开销。

输出包括 `protocol.json`、`source-binding.json`、`status.json`、`statistics.json`、`observations.json`、`summary.md` 与每题独立请求/成绩文件。离线统计也不会发送 API。科学运行、受控 native-image baseline 和这个一般 MMBC 泛化队列是不同协议，不能互相冒充。

五项零付费测试通过：固定100题的 gold/hash 隔离、操作性0及未知分数、完整三轮与子组缺失、真实 localhost HTTP 单次评分和结果SHA拒绝、未返回SDK调用及cache缺失统计。尚未启动付费评分，也不预先声称存在可用准确率。
