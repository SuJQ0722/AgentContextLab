# MMBC vanilla：独立评分与六方法报告

用户定义的 `vanilla_visual` 是“被压缩历史只渲染文本，移除其中的视觉证据”。它仍使用 visual 引擎，保留原始表格文本，不生成 caption；初始原图及受保护头尾的 native images 均与父 VERA 相同。它不是完全无图的 agent，也不是图像 token 匹配的受控 baseline。

新预测根为 `outputs/campaigns/mmbc100-hermes-vanilla-v1`，同一 100 题 × 3 repeats，300 条 job_id 与父 visual 对应。实际 strategy 仍为 `visual`，独立方法标签为 `vanilla_visual`。父五方法的运行、成绩和评分协议没有修改。

评分入口：

```bash
python scripts/judge_mmbc_vanilla.py                 # 零 API 检查
python scripts/judge_mmbc_vanilla.py --watch --live --concurrency 2
python scripts/report_mmbc_sixmethods.py             # 只读六方法报告
```

独立 grader 根 `outputs/grading/mmbc100-hermes-vanilla-v1`，复用父私有标准答案 `outputs/grading/mmbc100-hermes-deepseek-v1/private/`，不把答案写入任何预测目录。固定 judge 为 `deepseek-v4.1-flash-1017/huoshan/huoshan`，相同 answer-equivalence 提示、8192 输出上限、strict numeric score、finish=stop 和返回模型别名校验。只有 completed 且清理确认的结果进入评分；已确认 failed/timeout 为操作性0，其他终态/未知/评分错误保留 missing。每个结果最多一次 judge POST，已started未返回不重发。后台在全部300条预测终态且无候选/在途评分后退出，缺失不凑满。

启动核验包含父plan/config/manifest SHA、新plan/config/lineage SHA、相同公共cohort和初始图片manifest SHA、同一private gold SHA，以及300条问题/图片/repeat/jobid的精确映射。配置须严格等于父配置加三类获准差异：`visual.text_only=true`、新campaign版本、显式vanilla协议；任何额外科学设置变化拒绝加载。

六方法报告写 `outputs/grading/mmbc100-sixmethod-report-v1/`，只读父/new observations和source binding，不向父成绩写入。展示完整1800规划分母，分别报告全部100题、初始有图69题、初始无图31题。每个方法的固定范围三轮完整后才计算mean、sample std和question-cluster bootstrap CI。新增visual−vanilla比较按同question SHA与同repeat配对，bootstrap始终保留三个repeat；未齐300不得替换为成功交集。

父四项baseline配对检验及其Holm定义保留；visual−vanilla是单独新增的预定义比较。两个图像子组属于探索性分析，未声称同时控制所有五项或所有子组比较的错误率。预测与judge成本按两个独立namespace列出，不把父视觉运行复用成vanilla，也不双算同一个namespace。cached/noncache缺失继续unknown；美元定价未知。

五项零付费测试通过：300条原cohort/repeat/label隔离、额外科学差异拒绝、同job_id独立成绩不重发且不修改父成绩、完整三轮配对/缺失/重复检测、1800条六方法合并与父文件不变。

正式plan SHA `e580bb74da7676e4ea95a974a4f3b633c22fcb07351bfc97f0b010f51cbd485d` 的actual dry已通过（300 planned、0终态、0评分调用）。随后按授权启动grader PID344107，并发2；`service.json`保存身份与protocolSHA，`status.json`是实际运行状态。该PID是部署时快照，不代表所有题目成功；结果需等待真实终态和评分。
