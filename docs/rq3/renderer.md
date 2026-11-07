# RQ3 大页 PDF 转换适配

`rq3_pdf_renderer.install()` 仅替换当前 RQ3 worker 内的 PDF 转 PNG 函数；Hermes 源码与既有 BC 冻结实现保持不变。DPI、字体、布局、history scale、图像 detail 和 crop 边距不变。

先由 `pdfinfo` 检查每页实际几何尺寸。任一页超过 500,000,000 pixels 则失败，禁止 fallback。所有页不超过 100,000,000 pixels 时调用原函数；典型 1x 约 31M pixels 继续使用原转换。大页路径每次只 raster 一页，以临时磁盘 PPM 避免巨型 stdout 字节副本。在已验证、自生成 PDF 的转换作用域内将 Pillow 像素上限设为 500M，并在正常或异常退出时恢复原值。

大页 crop 用 1024 行 stripe 计算原谓词 `abs(gray - median(top_left_2x2)) > 5`。灰度为 uint8，最多 4 个像素的 median 只能为整数或半整数，因此 int16 谓词 `abs(2*gray - 2*median) > 10` 精确等价。跨 stripe 汇总相同 bounding box，保留原 1px 边距、PNG `optimize=True`、文件命名和页顺序。没有整页 float64 阵列，也不批量读取 20 张大页。

验证全部零 API 调用：

- 5 个单测：半整数 median 与跨 stripe bbox 等价；Pillow 异常恢复；普通路径原函数；31M/100M+1 路由；超 500M 预拒绝。
- 小 PDF 两页原/适配转换的解码像素、尺寸、mode 和 base64 PNG 字节完全一致：`outputs/preflight/rq3-pixel-equivalence-1794049832061892516/result.json`。
- 最终 100M 阈值下七档真实 PDF fixture（0/.125/.25/.5/.7/.8/1）全部通过，无 fallback；不同档位 canvas hash 不同，0 档不生成 old image，其余档位均包含 old image，recent image 保持相同：`outputs/preflight/rq3-scales-1794049917748597099/result.json`。
- 与先前 16M 路由阈值的验证产物相比，七档 PNG hash 全部完全一致；保留两份不同 artifact，不覆盖旧失败/旧实现结果。

这是新的 RQ3 运行实现，不是对历史结果的重命名。额外几何检查及大页内存优化可能改变渲染延迟；像素等价不等于延迟等价。记录 implementation metadata 和代码 hash，并继续将 provider usage、端到端、客户端 API 与渲染计时分开统计。
