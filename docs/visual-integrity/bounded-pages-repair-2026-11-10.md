# 图像分页、传输和信息损失修复记录

2026-11-10。旧实验、旧模型调用和失败成本保留；以下是独立版本的诊断与修复，**不是旧 MMBC 分数被修复，也不是全量实验已经恢复**。

## 查实的问题

| 实验 | 实际观察 | 判断 |
|---|---|---|
| MMBC VERA / vanilla | 配置 history_scale=1.0；recent 最大分别 1016×21888 / 1019×25278 | 请求里虽然有多图，仍混有多页纵向合并的巨图；并未按 .75 执行 |
| 受控 baseline | canvas 最大 1016×18350；32条有 scale 的控制记录均为1.0 | 同样存在巨图；不能因为代码候选含.75就声称实际用了.75 |
| 信息损失 URL 阶段 | 单 tile 高≤1536；每请求7–13张图，JSON≤2514 bytes | 已经是多图。9次400明确报告服务端下载URL超时，不能归因于巨大内联JSON |
| 信息损失重建 | 原文约6247–11159 words；18个视觉重建耗尽8192 output tokens，reasoning=0 | 还存在全历史重建与输出重复/截断问题；关闭thinking不能解决全部问题 |

受控实验1357条实际HTTP记录中，请求体<1 MB的发送至响应头阶段失败6/575；≥10 MB失败52/63。此关联支持优先修复体积，但不能证明具体哪个代理、网关或服务节点断开，也不能把收到HTTP200响应头等同于完整流成功。

完整审计：`outputs/preflight/image-shape-audit-20261110/README.md`。

## 已实现的修复

`scripts/bounded_multimodal_renderer_v1.py` 保留 Hermes 的 PDF 图文环绕与表格布局，取消 recent 巨页以及后续纵向合并。源页1024×2048，16pt/72dpi；远历史每页真正下采样 .75，最大768×1536；最近历史保持1.0，但每张也≤1024×2048。不会先扩大画布再缩回。两段显式high detail，这是新变体，不能与旧low/high混合协议混为同一设置。

固定页顺序逐张传入。image_search、crop、zoom均进入源图覆盖账本。缺图、缺页、超限或渲染错误时明确失败，不删除历史来满足限额。Vanilla仍只去掉渲染历史中的视觉证据，保留原表格文本；原生任务图不被重新编码。

`scripts/bounded_visual_request_guard_v1.py` 在最终HTTP边界检查**整个实际JSON**：≤8 MiB、≤32张图，canvas最长边≤2048且面积≤2097152。原生图片保留字节，仍计入总请求限额。工程限额不代表供应商公开能力。URL不可绕过核验；账本写入失败也阻止发送。

`scripts/bounded_lossless_transport_v1.py` 提供独立可选无损WebP编码，每张检查RGBA像素完全一致，只改变压缩canvas的文件编码。原PNG、PDF、最终图片、页序、尺寸、源/输出SHA和编码耗时均保留。原生head/tail图片不动。**离线编码通过不等于供应商传输验收通过，已通过小图格式阅读与一次真实10页传输检查，但整条轨迹及受控预算尚未验收，未开启全量使用。**

新MMBC入口：`scripts/hermes_bounded_mmbc_worker_v1.py`。必须使用新协议、新配置和新输出目录；不会替换旧worker或旧attempt。没有静默改变Hermes/DSH pin，未把此版本注入旧DSH/BC/RQ3科学运行。

## 实物与真实调用验收

离线重放 `hermes/visual/mmbc_194_r01` 的第一次 `compression_source_history`，只取当时25条历史消息，不加载最终答案。13/13原始视觉证据通过原字节及像素核验，输出10张图（6张.75远历史、4张1.0最近历史），最大分别765×1526、1016×2022。该真实例子没有结构化表格；另用140行表格fixture检查全部单元格跨页保留，不能把合成表格测试说成真实轨迹结果。

实际图片示例：[检索图与zoom分页](bounded-pages-v1/real-search-zoom.webp)、[跨页表格](bounded-pages-v1/table-continuation.png)。图片多而对应文字短时仍会出现空白；没有为美观删除视觉证据。

真实历史10张PNG合计9,840,168 bytes，base64下界13,120,240 bytes，仍超请求守卫。无损WebP quality80/method4缩至3,993,514 bytes，节省59.4%，编码2.46秒，10/10张逐像素一致。加上旧请求5张原生图后，图片base64下界6,624,244 bytes；**这仍非最终整请求大小**。必须连文本、工具schema等一起重新检查。

第一组5次真实DeepSeek请求全部HTTP200、finish=stop、reasoning=0：

| 诊断 | 图片/实际JSON | 结果 |
|---|---|---|
| 图文混合分页PNG | 2张，1,494,059 bytes | 首尾标记、表格数值、crop/zoom颜色5/5正确 |
| 真实短窗口文本 | 0张，1132 bytes | 正常返回，无截断 |
| 同窗口1.0 / .75 / .5 | 每次1张，69076 / 92480 / 52684 bytes | 均正常返回；URL和数字读出，但破折号发生归一化，并非逐字无损重建 |

5次已知usage合计2852 tokens（cached input=0，non-cache input=2261，output=591）。这是诊断成本，不是benchmark成本。SDK/HTTP耗时分别46.14、3.58、4.34、2.79、3.55秒；provider内部API latency未观测，USD实际计费未知。

第二组原定2次WebP阅读诊断：第一个2页请求84,401 bytes，91.42秒后ReadTimeout，没有usage。当时停止，未立即发送后续真实10页请求，也未重试未知调用。不能由一次超时认定WebP不支持，也不能宣称其线上修复已通过。随后独立微型格式对照两次均通过：同一页PNG 92,158 bytes / 3.94秒，WebP 46,719 bytes / 2.73秒，各2/2字段正确、各267 tokens，证明此路由确实可以读取小WebP；前一次失败仍保留为未知usage。PNG cached=0/non-cache=240/output=27，WebP cached=128/non-cache=112/output=27。证据 `outputs/preflight/bounded-format-microcheck-v1/report.json`。通过小格式对照后才单独恢复原定第二个真实10页诊断，未重试第一次超时。真实10页实际JSON为5,280,233 bytes，HTTP200、8.52秒、finish=stop、reasoning=0，usage为cached=0/non-cache=7213/output=56/total=7269。三个阅读字段严格检查2/3正确：Amazon ASIN和末页crop尺寸正确；首页第一个结果应为“Xbox 360 pad buttons : r/consolerepair”，模型却答“Xbox 360 Controller Repair - iFixit”。这证明该大小请求可以完成，不证明多页阅读无损；必须将失败纳入信息损失诊断，不能用重试替换。

## 受控实验和信息损失的后续边界

受控新入口 `scripts/controlled_native_worker_bounded_v1.py` 保留所有方法原生图相同，并要求重新测量新visual target，文本方法各自匹配±2%、三臂整体spread≤5%。单纯共享16384 ceiling不算预算匹配。基础canvas为.75，预算fit仍可能乘1/.75/.5/.25；账本明确记录最终比例，不能统一宣称.75。原180臂中缺prefix、无原生图和预算不可匹配的问题分别保留，不能靠换题凑齐。详见[受控协议](../experiment3/controlled-native-bounded-v1.md)。尚未启动新受控付费队列。

信息损失准备了固定q004/q009的early/middle/late连续原文窗口，每个≤512 UTF8 bytes且≤96 words，重建上限768 tokens；摘要和事实必须来自同一窗口，不能复用全历史摘要。当前只是6窗口诊断准备与q004 early四种表示的阅读检查，未产生新完整五臂信息损失结论。q004属于开发样本，不能加入holdout。详见[窗口协议](../experiment6/bounded-window-probe-v1.md)。旧失败、输出截断和未知usage仍计入历史账本。

全量恢复条件：传输格式稳定通过、真实完整请求通过尺寸守卫、受控预算与原生图一致性重新验收。当前不把小样例成功外推为MMBC 100×3已恢复。

## 本轮验证

根目录 `python -m unittest discover -s tests -v`：585项通过，100.39秒。包括真实PDF/PNG分页、长表格、source image coverage、像素一致性、最终请求guard、旧namespace拒绝和受控adapter预算契约。未修改冻结Hermes或DSH源码。

本轮合计9次独立模型请求：8次有usage，共10655 tokens（cached input128、non-cache input9826、output701）；另1次超时usage未知，不能填0。全量MMBC、受控和信息损失新五臂队列均未启动，旧成绩不变。
