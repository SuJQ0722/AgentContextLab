# DeepSeek RQ3 新复现实验：BC-100 × 3

本实验是新的 DeepSeek 分辨率实验，不能标成已确认复现历史 Table 5。模型使用现有冻结配置的 `deepseek-v4.1-flash-1017/huoshan/huoshan`，harness为Hermes；不调用Gemini，不混入历史Gemini/Qwen结果。

七档 `history_scale` 为0、0.125、0.25、0.5、0.7、0.8、1，每档同一100题、三个repeat，共2100条观察。其中1x直接引用正在执行的核心BC campaign中300条Hermes/visual任务，`external_job_dir`保存其实际路径；不复制轨迹、不重复推理、不重复judge或累计费用。其他六档新增1800条任务。

核心BC保持最高优先级与16并发。RQ3新增推理并发上限2；全局可见进程准入阈值<100，为用户要求的<128预留余量。准入、进程身份和resume由独立controller管理。本报告脚本只读结果，不启动或重试推理、评分。

## 参数解释和控制

相同问题内容/hash、repeat、模型和harness保持一致。scale是far历史的线性缩放参数，最近原文tail与最近五轮渲染不受同样缩放影响。0只省略far；1仍有视觉渲染，不能称No Compression。分页、字形密度和实际图像token可能一起变化，不能把scale直接解释为整个上下文token压缩比。详见 [scale-semantics.md](scale-semantics.md)。

每档记录压缩次数、实际render时间、old图像存在情况。`old_*.png`存在可确认far干预发生；不存在不能证明far为空，尤其scale0会故意省略old图片，曝光标unknown。应补充足够的renderer结构化数据才能测完整far生效比例。

当前实现每次压缩重渲染累积历史，不是冻结canvas的cache-aware变体。LLM缓存与工具缓存分开，实际缓存收益需由provider usage测量。

## 统计协议

整个七档100题×3都有终态预测及合法score之前，仅给进度、计费计数、缺失覆盖和instrumentation；不输出headline准确率，不对不断更新的partial结果反复显著性检验。

完成后每档给出三个repeat准确率的mean ± sample std，以及按100道独立题进行10,000次cluster bootstrap的95% CI。每题的三次重复一起采样，避免当成300独立样本。六档分别与预先指定的1x配对，使用题内平均差的question-cluster sign-flip test（10,000次）及六比较Holm校正，并输出差值CI。绘制带CI误差棒的scale–accuracy图。题目文本hash、question ID、repeat和模型必须匹配；未评分或无效评分阻止headline，不自动计错。

评分器预先规定的“在运行预算内没有最终答案”可记0，但须保留明确rule及终态记录；judge自身错误/中断不能自动记0。

## 进度、usage与成本

```bash
python scripts/report_rq3_campaign.py
python scripts/report_rq3_campaign.py --watch
```

`outputs/campaigns/rq3-deepseek-bc100-r3/monitor/status.json`保存每档进度和known usage；`jobs.csv`保存任务身份、匹配hash、score及来源路径。完整就绪后生成`statistics.json`、`accuracy.csv`、`paired-tests.csv`、`accuracy-with-ci.png/pdf`。

新增prediction与grading开销分别统计；复用核心1x的prediction/grading usage只作为对比observations单列，不能再加进新增花费。失败与中断的历史attempt仍计入已知消耗。cached input、non-cache input、output、total和usage守恒由provider计数重建；缺失usage、已开始未返回的请求都标unknown，不当0。没有TokenHub真实费率/账单时实付美元未知。

client stream/HTTP耗时不等于供应商内部API延迟，结果还受共享16路核心任务、网关和缓存影响。不同scale没有同步完成时不能将墙钟耗时简单当作公平的独立吞吐对比。

## 渲染适配验证与首次真实启动

大页PDF转换使用当前RQ3专用适配，详见 [renderer.md](renderer.md)。其七档真实PDF fixture和像素/PNG字节等价结果保存在该文列出的 `outputs/preflight/` 产物中；没有更换已有核心BC实现。

2026-11-07首次live核查：coordinator34179、reporter32978存活；两个新增任务为 `scale_0250/q_001_r01` 与 `scale_0500/q_001_r01`，私有native配置分别是0.25/0.5、font16、keep_rounds1，native policy日志确认visual引擎且已返回真实API usage（含cache counters）。该首次检查时尚未触发压缩，不能仅凭配置声称live图像分辨率干预已经发生。可见进程约76，低于100准入阈值。此为有时间戳的启动快照，不是永久状态保证；后续以monitor/status.json为准。

非敏感启动证据保存在 `outputs/campaigns/rq3-deepseek-bc100-r3/monitor/first-live-evidence.json`。
