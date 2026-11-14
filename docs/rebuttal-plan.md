> **当前结果与运行状态（2026-11-14）：[全部实验、超时及rebuttal缺口](results/2026-11-14/README.md)。以下新增补充计划仅为方案，未启动付费评测；后半部分为历史规划。**

# 2026年11月14日补充实验计划

目标是获得公平、可复核的结论，不以恢复VERA第一名为验收条件。当前完成子集不能代表全300题次；按全部固定槽位计算的交付成功率仍有意义，但不能解释成与基础设施无关的模型能力。旧数据、超时、失败及成本完整保留，新协议不覆盖旧结果。

## 对点评的核对与修正

- 支持核心判断：不均衡超时使完成子集存在选择偏差，现有数据不能支持总体准确率全面领先。已知正确数除以300如下；尚未评分结果按未交付正确答案处理，不冒称模型答错。

|实验|VERA|Summary|Window|No Compression|
|---|---:|---:|---:|---:|
|BC Hermes|237/300 = 79.00%|241/300 = 80.33%|221/300 = 73.67%|228/300 = 76.00%|
|BC DSH|196/300 = 65.33%|223/300 = 74.33%|229/300 = 76.33%|218/300 = 72.67%|
|MMBC Hermes|148/300 = 49.33%|139/300 = 46.33%|164/300 = 54.67%|146/300 = 48.67%|

- 响应头前等待、SDK耗时是客户端观测，不能直接定位为provider内部计算，也不能断言完全与视觉阅读能力无关。上传、代理/网关排队、服务端图像处理和网络均可能参与；SDK还包含重试。MMBC最新VERA超时104/300，并非高于所有方法。
- 受控Window的88.01%来自132个含共享参考的题次，不能直接与VERA在38个共同干预题次的82.15%比较。同一38题次上VERA/Summary/Window分别31/38、31/38、33/38；对应repeat均值为82.15%、84.01%、89.56%。当前未证明VERA优于受控baseline，也未证明Window显著更优。
- 109个真实干预中，两baseline均未超时88个、均完成41个、均已评分39个、加VERA有效参考后38个（26道不同题）。都未超时却失败的47个中43个涉及预算匹配；主要缺口不能全部归因于超时。
- 旧重建提示要求1200词以内的事实记录，明确不是逐字转录。`reconstruction_complete`仅表示非空输出以stop结束；1/9不能写成“仅1/9完整正确还原”。新计划弃用该项作为主信息损失指标，旧失败记录保留。
- “保留视觉证据有帮助”“同预算canvas损失小于摘要”“多模态成本相近/最低”均为待检验假设。Discard同时丢文字与图片，不能单独识别丢图效应；不显著也不等于相当。旧Gemini Table2需要先核实来源和统计口径，不能默认其全面领先已得到当前审计确认。

## P0 统一执行协议与并发诊断

先完成离线实现与独立开发样本预检，再启动正式固定cohort。开发题不进入正式准确率或信息损失holdout；只按技术指标冻结协议，不按正确率选择参数。

1. 所有策略统一500个agent决策轮，另计摘要、校准和HTTP发送。取消1小时作为科学任务停止条件，保留单次请求超时、统一工具上限和紧急停止机制。运行中持续落盘；被外部停止的任务标为删失，不当作正常500轮失败。
2. 每个逻辑模型请求至多**3次物理发送，包含首次发送，即最多2次重试**。现有候选仅适配MMBC Hermes视觉入口，必须扩展并验证所有策略、摘要辅助调用和DSH入口，防止SDK、路由及harness嵌套重试绕过总上限。单次请求上限也需预检，延长任务墙钟不会自动解决一次300秒请求超时。
3. 三次失败仍可能导致基础设施终止，因此两种统计口径不会自动合一。冻结任务级恢复规则和上限，所有方法相同；不对模型答错或正常达到500轮的结果择优重跑。能否从检查点恢复需分别验证harness状态、工具结果和请求边界；未验证时不宣称无损续跑。
4. 以固定、不含答案的开发请求包做4/16并发交叉对照，包覆盖文本、小图、大图。先固定网关总在途请求数、比较集中/分散到8核CCI的布局以检测本地争抢；再固定机器布局、改变网关总并发以检测服务链路拥塞。每条件预注册相同重复次数、交错执行、记录缓存状态与实际路由，不通过不同日期两个均值推因果。保持三次发送规则相同。
5. 记录排队、连接/TLS、序列化/编码、上传、响应头前等待、首token、正文流、重试退避、网页/工具、渲染及完整E2E；缺少埋点保留NA。CPU/cgroup限流、内存峰值/OOM、网络吞吐与网关全局在途请求另记。现有受控窗口/新版摘要累计CPU配额限流仅0/2.79秒，不能据“8核16并发”认定CPU不足。
6. 正式运行跨方法按题目×repeat分块随机交错，均衡路由/时段/并发；不同CCI也共享总请求限流，避免各自16并发叠加。模型版本、输出token上限、温度、工具版本和数据SHA固定，缓存/动态网页的不可控部分披露。

P0验收：无协议逃逸、没有成功轨迹被静默覆盖、计时分区可核查、图像载荷校验通过；通过预注册延迟/失败率标准确定正式并发。当前没有已测量的低并发收益，不承诺改成4并发必然解决超时。

## P1 MMBC全轨迹受控比较

**900题次：原固定100题×3次×3臂（VERA、Summary+Native、Window+Native），全部从头执行。** 不按旧VERA是否成功/超时/触发压缩选题；没有触发压缩的题次仍在总体中，另报实际压缩覆盖，不能冒充已检验压缩机制。

- 各臂从第一步起使用固定方法，所有后续压缩均遵循该方法，不再只替换首次压缩。相同阈值、近期原文保留规则、工具权限和原生图像准入政策；方法导致的轨迹分岔是全策略效果的一部分。
- 匹配的是**压缩后总输入token预算上限**及相同预算规则，不强迫整条轨迹累计token相同：累计token与轮数本身是待测成本。候选触发32768、压缩后上限16384，须先在独立开发集验证图像最低占用是否可行，冻结后才能进入正式实验。
- 不再用旧VERA某条成功轨迹的token数作为baseline目标。少用token不作失败，不填充无意义文字或复制原文凑数。超限按预注册的摘要压缩/窗口裁剪/图像表示规则处理，校准次数封顶；无法满足预算的正式题次留在全集，报告原因，不能剔除后只比较成功者。该设计应称“相同预算上限”，不冒称实际token严格相同。
- 各臂使用相同已验证的wire图像上限（现有为10，是否适用须预检）和相同原生证据保留规则。源证据数量、最终wire图片数、像素/detail及provider图像token分别记录。拼入canvas与独立图的wire张数、图像token通常不可能同时完全相同；不填空白图、不只为某臂删图以凑数。无法在上限内保留证据时必须先重新设计共同策略，不能把方法特异性丢图隐藏成公平控制。
- 全轨迹三臂比较识别整体策略效果，不能单独证明“一起渲染”这个因素。若仍要维持该因果主张，需另设固定历史的机制对照：相同文字canvas与相同原生图像，唯一干预为嵌入/独立传入；不能用Summary/Window两个文字压缩方法的差异代替这一对照。

输出：全300交付成功率、有效覆盖、失败分类、全程成本、同题配对CI；完成子集作为补充。结果不支持优势时如实收缩主张，不能预先写成“渲染成本最低”。

## P2 MMBC主表与VERA对Vanilla

**六策略×100题×3次=1800题次。** 为得到干净的新协议主表，建议全方法从头跑，而非把旧成功与新协议补跑混成单次评测。若P1的VERA在全部科学/执行设置和cohort上完全一致，可共享其300题次，两个实验合计**2400个独立题次**；若预算、图像规则或压缩算法不同，禁止共享，合计2700。Summary+Native/Window+Native与主表旧baseline保持独立标签。

VERA与Vanilla除“压缩历史是否保留视觉证据”外，保持图像cap、近期/初始证据、路由、轮数、请求重试等相同；特别审计近期十图策略不能造成额外方法差异。Discard只作为激进丢弃对照，不作为单独丢图因果证据。

覆盖目标为每法≥250/300有效、VERA–Vanilla≥80个三repeat完整配对题簇（240题次）。这是报告质量目标，不是“反复重跑直到达到目标”的停止规则；固定cohort、固定授权尝试上限先冻结，正常答错也算有效。达不到则保留缺失及结论限制。即使达到250/300，仍有最多16.7%缺失，选择偏差不会因此自动消失。

除点估计外，报告题簇bootstrap、预注册主对比的Holm校正和最小重要差异/可检测效应；80题簇不保证能检出很小差异。若要声称“相当”，需预注册等效或非劣界限并用CI判断，不能用p>0.05代替。

## P3 Probe QA信息损失

固定**40条独立holdout历史、每条6个事实，共240事实**。开发集另置，不与旧9条反复用于调试的历史混合。按历史长度、事实类型和证据位置预先分层；事实与答案须能定位原始证据，选择在制作各压缩表示之前完成，不按方法回答情况筛题。所有事实按历史聚类统计，不能当240个独立题。

主任务仅为关键事实Probe QA；取消完整重建作为主指标。摘要生成不能看到probe问题/参考答案，防止定向保留答案。分别报告答对、答错、弃答、传输失败和无可评分输出，保留全事实分母及相同可评事实的配对补充。

**七臂设计**：完整原文；canvas 1.0/0.75/0.5；与三档canvas分别匹配输入预算的三份摘要。每条历史各臂均回答同6事实。这样既保持原canvas内容相同来比较分辨率，又避免拿同一份600词摘要当所有尺度的“同预算”对照。

- 预算按相同reader模型、相同问题包装后的provider输入token计量，事实探测输出上限一致。匹配生成过程与容差在开发集冻结，记录实际差值；不可匹配/摘要生成失败不从holdout删除。另报按同一输入上限而非严格相等的可部署比较，不冒称预算相同。
- 客观短答案用冻结的别名、单位/数值规范及确定性评分；语义歧义项由**不同于DeepSeek系列**的judge盲评，随机化方法标签，不凭judge改写ground truth。具体模型ID和可用路线尚未冻结，现阶段不启动新模型调用。
- 人工复核须由人类进行：预抽至少50个事实，对其全部方法回答盲审，并另看所有争议项，随机审计与争议审计分别报告。事实本身240个的证据/答案也需审核；LLM复核不能写成人工复核。人类尚未参与的阶段不得宣称完成。
- 按每条历史批量问6题，基础Probe请求为40×7=280次，产生1680个事实回答；另有至少120份摘要生成及计量、独立judge调用，不能把280当总API预算。模型选择/报价未定前不报虚构美元预算。
- 1.0→0.75→0.5只检验分辨率因素。若要支持“近期保原文、远期降分辨率”，另需同一历史/同一事实的等预算均匀分辨率对照与分层表示对照，控制位置与内容；不能由跨题的距离曲线推导时间衰减因果结论。

待检验：canvas相对原文损失多少、相对同预算摘要是否更好、分辨率是否影响检索；不预设“远小于摘要”或单调关系必然成立。不同系列judge不等于不同reader模型的泛化实验；视觉阅读能力依赖需另做reader×表示交互对照才可声称。

## P4 成本与缓存重算

在P1/P2中同步收集，结束后离线重算，不另启动任务预测。所有方法相同固定cohort上报告cached/non-cache/output/total、渲染/编码CPU与E2E、压缩次数、原生图/历史canvas占用；若provider不返回图像token，不按文件大小伪造。

分别报告：固定cohort的全部实际支出（包括失败、重试和摘要生成）、每个交付正确答案的成本、成功轨迹效率。校准是独立实验开销，不能当作摘要固有效率劣势；其缓存预热影响也需披露。旧失败支出另外保留，不因新协议清零。

成本Pareto两轴使用相同cohort，不再用9个共同成功样本代替总体。缺usage给出已知小计与缺失请求数，不填0。实际账单不可得时仅给token和标明价格来源的参考重估。按预先定义的输入图像占比分层，检验成本优势是否主要来自文字历史；不能看结果后再挑有利分层。

## P5 BC与RQ3覆盖修复

所有方法/尺度遵循同一新执行规则。当前需诊断的历史超时槽位：BC Hermes39、BC DSH297、MMBC733、RQ3七档439（含0.7一个未发布终态），合计1508。另有主表7个、受控3个完成未评分，先恢复评分而非重跑预测；其他失败须区分正常任务预算耗尽与基础设施失败，不全盘重跑。

只补历史超时可做恢复/敏感性分析，但换了请求重试规则后与旧成功合并，不能直接标为“统一新协议单次100×3”；若无法验证检查点等价恢复，独立新协议主表需要全量BC两harness3000题次、RQ3七档2100题次。RQ3优先完成1.0与预注册的主比较尺度，再决定是否需要全七档，不能按结果选择最优尺度来报告。

与可共享VERA的P1/P2合计，完整新协议三大块为2400+3000+2100=7500题次，不含预检、信息损失和judge。不能把1508个历史超时补跑量当作这套干净重做的全部成本。

## 统计、结论与执行顺序

主报告同时给出固定cohort交付成功率、任务正常完成覆盖、运输/系统失败率、轮数/输出预算耗尽率、时间与成本。模型能力未观测部分保留缺失，并给最坏/最好界限；模型填补只作为敏感性分析，不能替代实测。只有几乎无未决基础设施失败且评分齐全时，完成子集与固定全集口径才可能接近。

顺序：P0技术门禁→P1三臂→P2其余主表；P3可在全局流量隔离后开展；P4随数据累积离线生成；P5按rebuttal范围和资源安排。当前全部是待执行计划，无新付费调用、无新云队列、无承诺结束时间。预检后依据实际吞吐、P95耗时和可用全局请求配额估算排期；取消任务墙钟上限后不能继续套用“批次数×1小时”的旧ETA。

可接受的结果包括VERA没有优势。只有数据支持时才能写：在指定模型/benchmark上保留视觉证据有益、某种表示具有更优准确率–成本折中、或模型视觉阅读能力影响效果。不把Gemini领先、DeepSeek等效、最低成本、近乎无损当作既定结论。

---

以下为历史计划，不代表新队列已启动。

# Rebuttal experiments

This branch contains experimental native-image baselines, an external DSH
adapter, and pilot launch tools. Capability probes are not scored benchmark results.

## Execution status (2026-11-07)

The subsequent parallel work is tracked in [the current rebuttal status](rebuttal-status.md):
core BC remains at 16 workers; fresh multimodal prefix capture and the independent
DeepSeek RQ3 campaign run at lower concurrency. Text-table statistics and failure
analysis are offline; the first information-loss pilot is complete. A prepared
policy or captured prefix is not a completed controlled-baseline result.

- The user stopped the serial pilot and requested a 100 × 3 run of all five
  main policies on both harnesses, with 16 total concurrent jobs. The new
  [campaign protocol and resume instructions](bc100-campaign.md) distinguish
  this 3,000-job campaign from the serial pilot and the controlled multimodal
  baseline. The frozen configuration currently obeys the standing no-new-Gemini
  instruction and selects DeepSeek for both new harness runs.
- The reviewer-facing historical cost/cache table and Pareto plots are saved
  on the `dev` worktree in [the Experiment 1 Markdown report](experiment1/experiment1.md),
  with [all 57 archived groups](experiment1/experiment1_all_runs.md) kept separately.
- The controlled native-image baseline campaign has **not** been launched.
  Implemented Hermes strategies and frozen cohorts are preparation, not results;
  matched post-compression budgets and provider image-token matching are still
  unvalidated. The BC-100 summary/visual pair is the separate DeepSeek + DSH
  transfer campaign, not completion of that controlled-baseline experiment.
- At 08:24 UTC, the corrected DSH campaign stopped after five completed attempts
  and one 1,800-second timeout (`visual_native/q_003`). The timed-out run did
  render and commit a visual compression. The monitor kept recording the stop,
  but did not autonomously recover it. The runner now treats the predeclared
  timeout as a retained budget-limited observation and advances without retrying
  that question. Grading includes deadline failures (no final answer scores 0);
  missing provider usage on interrupted streams stays unknown.
- Selected `deepseek-v4.1-flash-1017/huoshan/huoshan` from TokenHub discovery.
  Direct text, red/blue image probes, and a tool-call round trip passed. Native
  DSH headless text and image admission passed with recorded usage. Configured
  context capacity has not been stress-tested.
- Isolated Node v24.11.0 and pnpm 11.28.5 are installed. The pinned DSH build
  passed all 10 gates. The launcher invokes the built dsh CLI so task cwd is
  preserved; `pnpm --dir` would change cwd to the harness checkout.
- Audited 20,735 conversation exports; all contain harness token/cache fields,
  and 17,992 have a score. Exact session-ID joins to `summary.jsonl` recovered
  20,708 session spans. These are **not** CLI wall-clock durations: the corrected
  experiment-1 reconstruction reads `history/*.json:wall_seconds` separately.
  Legacy audit column labels have been corrected. See the reconstruction below.
- Froze 10 IDs each for BrowseComp, XBench, BrowseComp-V3, MM-BrowseComp, and
  AgenticDataBench, with seed 20261107 and dataset/content hashes. Selection is
  independent of model outcomes. Outputs: `outputs/cohorts/`.
- Hermes exposes `summarize_native` and `sliding_window_native` through its real
  loader. DSH policies live outside the pinned submodule in `plugins/dsh-context/`.
  Durable compaction tests cover summary, native window retention, and discard.
  `visual_native` renders text with the customized Hermes renderer and retains
  native attachments separately. Identify this variant explicitly; it is not a
  byte-identical rerun of historical VERA.
- DSH post-compression limits use its token meter, an estimate. Exact provider
  image-token matching is not validated. Failed compaction or an exceeded budget
  blocks the next step. Hermes native engines retain images but do not enforce
  matched post-compression budgets yet.
- BC-100 is frozen separately, in historical source order, from
  `../hermes-agent/Browsecomp_eval/data/browsecomp_subset_200/questions_100.jsonl`
  (source SHA256 `0461d4226d7bc33393abb06f6cca403234c8c6ed492626b4eb25ff513d598de7`).
  The intended paired run is 100 questions × `summarize` / `visual_native`.
- The external DSH web adapter follows Hermes `plugins/local_web`: Serper cache
  proxy and Reader server, with the configured text extraction and Jina fallback.
  Runtime secrets are read from `hermes-agent/config.yaml` (or
  `ACL_HERMES_WEB_CONFIG`) into the child environment only. Explicit DSH provider
  patches override the upstream default routing. Search cache headers and HTTP
  wall time are recorded in `web.jsonl`; missing cache headers remain null.
  Reader does not return the origin HTTP status: the DSH status field represents
  the Reader proxy status, while instrumentation marks origin status unavailable.
- The initial BC-100 launch was attempted but stopped before model inference:
  Serper `10.120.3.169:80` returned `EHOSTUNREACH`; Reader `10.120.0.246:8080`
  returned `ECONNREFUSED`. Proxy attempts returned HTTP 502. Evidence:
  initial probe logs. The user subsequently supplied replacement endpoints:
  Serper `10.120.4.249:80` works, with `X-Cached=false` then `true` for a repeat
  query (about 1.90 s then 0.006 s client-observed). Reader `10.13.64.17:8080`
  returns real page text. Preferred Reader `10.120.7.221:8080` refused both
  connection attempts, so the working alternate is selected explicitly in
  `configs/experiment.json`. Evidence: `outputs/preflight/web-new-endpoints/`.
  The 100-question paired campaign has now been launched; see
  `outputs/pilot/bc100/campaign.log` for execution status and per-run `result.json`
  for completed attempts. No benchmark score is implied by a completed turn.
  The first visual attempt exhausted its output budget before any compression.
  It remains a failed observation; the runner now continues after bounded output
  or step exhaustion without retrying it, and still stops on execution failures.
  A resumed campaign preserves all previously written attempts.
  BC-100 exposes only `web_search` / `web_fetch`, so it does not need shell
  sandbox execution. AgenticDataBench still requires a working process sandbox.
- Poppler was missing, causing the historical renderer's automatic PIL fallback.
  Earlier history-image probes are retained with `validity.json` excluding them
  from PDF-rendering claims. A local Poppler runtime is now installed; the DSH
  bridge rejects PIL fallback and partial history render failures.
- The corrected PDF synthetic probe contains 12 tool rounds and six exact recall
  fields. At font size 8 / history scale 0.75, text control returned 6/6; the image
  request consumed 8192 reasoning/output tokens with `finish_reason=length` and
  no final answer. This is an unsuccessful bounded probe, not proof that the
  route lacks image input. Native DSH also failed to finish the dense-image probe
  within its one-step bound after requesting an unavailable OCR helper tool.
  Color recognition alone is insufficient evidence of usable visual compression.
  Artifacts: `outputs/preflight/visual-history-pdf-8192/` and
  `outputs/preflight/native-visual-history-pdf/`.
- A separate legibility calibration on the same synthetic history, with font 16
  and history scale 1.0, returned 6/6 for both text and image. Provider-reported
  prompt tokens were 3732 for text and 2020 for images, for this probe only;
  they do not establish benchmark cost savings. `configs/experiment.json`
  now selects this readable DSH rendering variant, with settings preserved in
  each run manifest and render metric. Do not conflate it with historical VERA
  settings or claim independent font/scale effects from this joint change.
  Artifacts: `outputs/preflight/visual-history-pdf-8192-font16-scale1.0/`.
  The same images also passed native DSH admission and final-answer generation,
  with 6/6 exact fields and no helper tools. Its `native-dsh/result.json` records
  the completed turn, and `native-dsh/metrics/calls.jsonl` records usage.
- Native DSH successfully completed a synthetic Serper search → Reader fetch →
  final answer protocol test, using only the two web tools. This validates the
  adapter and explicit provider routing; it is not a real-backend health result.
  Artifact: `outputs/preflight/dsh-web-fixture/result.json`.

## Reproduction

```bash
bash scripts/setup.sh runtime
bash scripts/setup.sh dsh
bash scripts/setup.sh renderer  # local Ubuntu 22.04 Poppler runtime
python scripts/lab.py doctor
python scripts/probe_gateway.py  # no API calls without --live
python scripts/prepare_cohorts.py
python scripts/prepare_cohorts.py --bc100
python scripts/run_dsh_eval.py --dataset bc100 \
  --strategies summarize visual_native --limit 100 --timeout 1800
python scripts/probe_visual_history.py --font-size 16 --history-scale 1
# Add --live for paid capability probes; native DSH probe:
python scripts/probe_dsh_history.py \
  --probe-dir outputs/preflight/visual-history-pdf-8192-font16-scale1.0
python scripts/run_dsh_eval.py --dataset mmbrowsecomp \
  --strategies summarize_native sliding_window_native visual_native --limit 10
python scripts/audit_records.py --root ../hermes-agent/preds_archive \
  --output outputs/audit/archive
```

`--live` enables paid inference. BC-100 checks both real web backends before
any model request and checks the process sandbox before data tasks.
It never silently repeats an existing attempt. Completed DSH turns remain
unscored until benchmark-specific grading succeeds. `calls.jsonl` records
client-observed adapter stream time, including retries and auxiliary calls;
it is not provider-internal latency. Render and end-to-end time are separate.
Fresh sessions are supported; interrupted-session resumption and exact
cross-harness budget equivalence have not been validated.

## Continuous BC-100 supervision

On 2026-11-07 the first seven attempts were invalidated after discovering that
the loader's patch `name` is a match guard, not a plugin replacement. The old
research patch was skipped, leaving native default compaction active. Those
attempts are preserved under `outputs/invalid/bc100-policy-not-mounted-20261107T0732/`
and excluded from method comparisons. Their 2,764,249 observed tokens are reported
as invalid-configuration overhead; the interrupted request may have unreported
usage. A new cohort is necessary for valid policy comparisons, not a selective
retry based on answers. The corrected patch disables the old entry and inserts
the research subclass. Per-step and pre-request checks reject a missing/wrong
policy. Local synthetic API startup tests exercise both complete CLI boots;
the visual transaction test exercises the real PDF renderer without model calls.

`scripts/monitor_dsh.py --root outputs/pilot/bc100 --watch` checks every 30 seconds.
It verifies worker liveness, metric activity, duplicate call IDs, and token
conservation, research-policy identity, unexpected textual summarization in a
visual run, and post-compression budget validity. It records issues in `monitor/alerts.jsonl` and current state in
`monitor/status.json`. A monitor read failure is explicitly written to
`monitor/read-error.json`, never silently interpreted as zero usage. No monitor
checks make model requests, and failed experimental attempts are never replaced
with selectively successful retries. Unexpected execution failures stop the
runner for diagnosis; the monitor remains alive and reports the stopped state.
Output, step, and predeclared wall-clock limits are retained failed observations;
these advance to the next scheduled attempt without a paid retry. This policy
does not increase any per-attempt budget.

Per-call `calls.jsonl` and `monitor/calls.csv` preserve cached input, non-cache
input, cache writes, output including reasoning, totals, purpose, finish reason,
and client-observed timing. The pinned pi-ai adapter omits *zero* cache fields;
this documented convention is not applied to a missing usage object. Cache hit
rates also exclude zero-initialized usage placeholders on failed requests;
these are reported as unknown provider usage, not free calls. Cache hit
rate is the token-weighted ratio `sum(cache reads) / sum(all input)`.
Serper response-cache hits are separate from model prefix-cache hits.
Per-run `conv.json` exports Hermes-style aggregate keys and references the full
native `session.v4.jsonl.zstd` trajectory and headless event log. `records.csv`
also records observed compression counts and rendering time, with missing timing
left null. Auxiliary calls are included in overall consumption and separated by
purpose for analysis. Provider-internal latency, raw provider request IDs for
agent streams, and actual invoices are not available at this instrumentation seam.

`scripts/judge_dsh.py --live --watch` is scheduled locally to wait until all
predictions finish, then uses the existing Hermes judgment prompt with the
configured **DeepSeek** route. Empty responses score zero without an API call.
Judge requests and returned usage live in separate `judge.json` files; monitoring
reports judge consumption separately and also provides an inclusive total.
Grading does not run concurrently with predictions and is not included in agent
latency. Transport/parse failures remain unscored and are reported, not retried
silently. No new Gemini inference or judging runs are authorized or scheduled.

The current BC-100 campaign uses fixed within-question order (summary then
visual), so shared gateway cache warmth can be order-dependent. Record this
limitation rather than attributing every cache/cost difference to compression.
The invalid initial campaign may also have warmed shared cache entries for its
first four questions; no control over gateway cache eviction is assumed.
The configured seed governs cohort selection; a provider generation seed was
not set. This is a paired transfer experiment across configurations, not a
factorial isolation of model, harness, decoding, or cache-order effects.

## Experiment 1 reconstructed artifacts

Run `python scripts/rebuild_experiment1.py` (read-only inputs, no model calls),
or `--reuse` to regenerate tables/figures from its reconstruction cache.
Artifacts under `outputs/experiment1/`:

- `method_benchmark_table.csv`: 57 separate archived run groups, including
  debug/updated/ablation runs as separate rows, with token components, current
  official-price cost estimates, wall/API/render timing coverage, cache hit
  rates, compression evidence, accuracy bounds and observed score coverage.
- `per_trajectory.csv`: 22,949 archived observations including AgenticDataBench.
  All 19,238 Gemini BrowseComp-family observations have usable recorded token
  counters and can be repriced. The separate AgenticDataBench exports lack API
  token usage; tokenizer counts of saved transcripts are not substituted.
- `paired_scored_table.csv` and `paired_membership.csv`: comparisons matched on
  question-content hash and repeat, using available judged observations across
  the selected five main methods. Missing grades are not assumed incorrect.
  The full table reports coverage/bounds; paired figures condition on this
  scored intersection and are descriptive, not evidence of significance.
- `pareto_text.{png,pdf}` and `pareto_multimodal.{png,pdf}`: separate benchmark
  panels; do not pool unlike benchmarks or different models into one frontier.
- `audit.json`: provenance, coverage, and limitations. Actual CLI wall-clock was
  recovered for 22,922 observations. Complete rounded API-log timing exists for
  1,322 (1,207 Gemini); 18,752 more have only partial tail timing. Rendering
  latency is not reconstructed from unrelated timestamps. Compression counts
  have usable evidence for 7,378 records, including disabled-method zeros and
  explicitly labeled lower bounds; unreliable zero exports remain unknown.

Pricing is versioned in `configs/gemini-pricing-2026-11-07.json`, with a local
source snapshot under `outputs/audit/pricing/`. The
[Google Cloud official Standard Global table](https://cloud.google.com/model-garden/pricing)
lists Gemini 3.5 Flash at $1.50/M non-cache input, $0.15/M cached input, and
$9/M output including reasoning. The recorded gateway alias is mapped by name
for a **current-price counterfactual**, not a claim about actual historical
TokenHub bills. Tool charges and cache storage are excluded; unknown actual
costs remain null. AgenticDataBench fractional mean scores are retained separately
from exact-task accuracy. Its completed SW evaluation supersedes the partial one.

The initial matched figures place VERA below No Compression in estimated token
cost for these seven benchmarks, but accuracy tradeoffs remain (e.g., XBench
and SEAL). This supports reporting a frontier, not a universal dominance claim.
Cache-aware frozen canvases/discrete resolution levels remain an optional,
separately versioned follow-up; no unrequested Gemini rerun is needed for this
historical reconstruction.

## Priority and controls

1. **Experiment 3 first:** Summarization + Native Images and Sliding Window +
   Native Images against VERA on the three multimodal tasks. Match retained
   image tokens and post-compression total budgets. Record caption producer,
   prompt, crop description and table serialization. Implement DSH methods as
   harness plugins; preserve each native harness's execution loop.
2. **Experiment 1 in parallel using existing records:** recover provider cached
   input, non-cached input and output counts separately; report total tokens,
   per-question cost, cache hit rate and compression count. Do not substitute
   live-context estimates for billed token usage. Version the pricing source,
   billing mode, model version and date; TokenHub billed cost and hypothetical
   official Gemini prices are separate columns. Missing API/render timings are
   missing, not inferred from total latency. Only rerun missing measurements.
3. **Experiment 2:** Compare DeepSeek v4.1 Flash 1017 × DSH with the existing
   Gemini 3.5 × Hermes results. These are the two model/harness combinations
   selected for this rebuttal; no third model is planned. Match task IDs, seeds,
   tools, budgets and strategy implementation. Use two text and two multimodal
   datasets initially. Because model and harness change together, this design
   measures transfer across configurations, not either factor's isolated effect.
4. **Experiments 4–6:** paired per-question repeats and bootstrap CIs; stratified
   failure/length analysis; historical fact reconstruction and probe QA at
   multiple resolutions and distances. Predefine seeds and cohorts. Describe
   observed trends without assuming significance or lower cost in advance.

## Common run manifest

Every run should record harness tag/commit, strategy/version, exact gateway model
ID, dataset revision, question ID, repeat/seed, context and post-compression
budgets, retained image IDs/tokens, compression trigger/count, and timestamps.
Keep full provider usage and request IDs when available; never store API keys.
End-to-end time, summed API time and render time must be separately measured;
concurrent operations mean component times need not add up to elapsed time.
Token cache hit rate = cached input / total input, with zero-input cases missing.

## Existing assets

The earlier local checkout still contains the historical `preds_archive/` and
`Browsecomp_eval/output/` records. It is deliberately retained during this
migration. Configure analysis input paths explicitly; the new repository does
not upload private trajectories, datasets or environment files.

## Current boundaries

- Hermes remains the customized paper implementation, based on v0.18.0.
- DSH is pinned to `dsh-v0.2.2-rc.1`; upstream has no stable release as of
  2026-11-07. See `harness-lock.json` and `.gitmodules`.
- The shared TokenHub endpoint uses a custom OpenAI-completions provider, not
  the DSH official DeepSeek Messages provider.
- Confirm the gateway's exact Flash model ID, image support and context limits
  before treating it as a VLM experiment. Configuration is not a capability test.
