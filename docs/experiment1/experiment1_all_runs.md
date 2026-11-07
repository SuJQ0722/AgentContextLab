全量运行分组附表（57 行）

本表保留各组全部已导出的运行，样本不一定匹配，不能直接据此比较方法优劣。成本、token 和 E2E 为有记录样本的均值；Acc 仅基于已评分记录。NA 是缺失，不是零。题目选择、定价和缺失项说明见 [主报告](experiment1.md)。

| ID | Benchmark | 方法 | 模型 | N | 评分覆盖 (%) | Cached (K) | Non-cache (K) | Output (K) | Total (K) | 估算 $ / 题次 | E2E s (n) | Acc (%) |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R01 | bc | Discard | gemini-3.5-flash-thinking | 600 | 96.2 | 786.8 | 933.8 | 14.5 | 1,735.1 | 1.649 | 966.6 (600) | 62.22 |
| R02 | bc | No Compression | gemini-3.5-flash-thinking | 443 | 99.8 | 2,031.2 | 1,252.1 | 12.7 | 3,296.0 | 2.298 | 594.9 (443) | 62.67 |
| R03 | bc | Summarize | gemini-3.5-flash-thinking | 486 | 98.4 | 513.3 | 849.7 | 11.2 | 1,374.2 | 1.453 | 578.4 (486) | 67.99 |
| R04 | bc | Sliding Window | gemini-3.5-flash-thinking | 443 | 100.0 | 849.1 | 886.0 | 12.4 | 1,747.4 | 1.582 | 621.8 (443) | 65.46 |
| R05 | bc | VERA | gemini-3.5-flash-thinking | 428 | 91.8 | 502.2 | 663.5 | 12.3 | 1,178.1 | 1.182 | 691.8 (428) | 70.99 |
| R06 | bc_v3_debug | Discard | gemini-3.5-flash-thinking | 600 | 98.7 | 1,135.6 | 1,447.1 | 24.3 | 2,607.0 | 2.560 | 1,089.8 (600) | 20.61 |
| R07 | bc_v3_debug | No Compression | gemini-3.5-flash-thinking | 600 | 99.3 | 4,648.3 | 2,563.1 | 24.3 | 7,235.7 | 4.761 | 1,060.1 (600) | 25.17 |
| R08 | bc_v3_debug | Summarize | gemini-3.5-flash-thinking | 600 | 96.5 | 1,493.6 | 1,982.5 | 21.9 | 3,498.1 | 3.395 | 1,133.2 (598) | 22.97 |
| R09 | bc_v3_debug | Sliding Window | gemini-3.5-flash-thinking | 600 | 98.8 | 1,635.9 | 1,743.9 | 21.5 | 3,401.3 | 3.055 | 1,039.4 (600) | 21.75 |
| R10 | bc_zh | Discard | gemini-3.5-flash-thinking | 867 | 95.8 | 568.5 | 742.0 | 14.2 | 1,324.7 | 1.326 | 565.5 (867) | 75.45 |
| R11 | bc_zh | No Compression | gemini-3.5-flash-thinking | 867 | 96.2 | 1,742.9 | 1,453.2 | 10.7 | 3,206.8 | 2.538 | 513.9 (867) | 73.26 |
| R12 | bc_zh | Summarize | gemini-3.5-flash-thinking | 867 | 88.8 | 541.1 | 759.5 | 9.0 | 1,309.6 | 1.302 | 440.7 (867) | 76.49 |
| R13 | bc_zh | Sliding Window | gemini-3.5-flash-thinking | 867 | 96.4 | 709.8 | 896.2 | 9.9 | 1,615.8 | 1.540 | 537.1 (867) | 72.25 |
| R14 | bc_zh | VERA | gemini-3.5-flash-thinking | 867 | 94.9 | 480.0 | 624.0 | 12.4 | 1,116.4 | 1.120 | 509.1 (867) | 75.82 |
| R15 | bc | Discard | gemini-3.5-flash-thinking | 459 | 99.6 | 509.1 | 707.8 | 13.0 | 1,229.9 | 1.255 | 558.6 (459) | 70.90 |
| R16 | bc | scale0 | qwen3.5-122b-a10b | 297 | 14.5 | 0.0 | 134.3 | 1.7 | 136.1 | NA | 105.4 (297) | 60.47 |
| R17 | bc | scale0125 | qwen3.5-122b-a10b | 299 | 13.0 | 0.0 | 142.7 | 1.8 | 144.5 | NA | 128.1 (299) | 79.49 |
| R18 | bc | scale025 | qwen3.5-122b-a10b | 300 | 17.0 | 0.0 | 158.8 | 2.2 | 161.0 | NA | 138.4 (299) | 64.71 |
| R19 | bc | scale050 | qwen3.5-122b-a10b | 300 | 15.7 | 0.0 | 252.6 | 2.7 | 255.3 | NA | 201.4 (300) | 40.43 |
| R20 | bc | scale100 | qwen3.5-122b-a10b | 297 | 10.4 | 0.0 | 237.3 | 2.7 | 240.0 | NA | 196.1 (297) | 51.61 |
| R21 | seal0 | Discard | gemini-3.5-flash-thinking | 333 | 96.4 | 812.1 | 985.7 | 12.3 | 1,810.1 | 1.711 | 722.3 (333) | 54.83 |
| R22 | seal0 | No Compression | gemini-3.5-flash-thinking | 333 | 97.3 | 2,128.1 | 1,309.4 | 12.3 | 3,449.8 | 2.394 | 698.7 (333) | 56.79 |
| R23 | seal0 | Summarize | gemini-3.5-flash-thinking | 333 | 96.7 | 939.5 | 1,262.2 | 12.3 | 2,214.1 | 2.145 | 740.7 (333) | 54.97 |
| R24 | seal0 | Sliding Window | gemini-3.5-flash-thinking | 333 | 99.4 | 1,014.8 | 1,103.2 | 12.2 | 2,130.2 | 1.917 | 726.2 (333) | 52.87 |
| R25 | seal0 | VERA | gemini-3.5-flash-thinking | 333 | 99.1 | 863.9 | 875.4 | 14.2 | 1,753.5 | 1.570 | 813.7 (333) | 51.82 |
| R26 | seal0-64k | Discard | gemini-3.5-flash-thinking | 333 | 88.3 | 775.4 | 952.9 | 11.8 | 1,740.1 | 1.651 | 828.1 (333) | 57.14 |
| R27 | seal0-64k | No Compression | gemini-3.5-flash-thinking | 333 | 95.5 | 2,244.2 | 1,103.3 | 11.0 | 3,358.4 | 2.090 | 729.7 (333) | 60.38 |
| R28 | seal0-64k | Summarize | gemini-3.5-flash-thinking | 333 | 91.3 | 842.1 | 1,101.7 | 10.2 | 1,954.1 | 1.871 | 777.0 (333) | 57.89 |
| R29 | seal0-64k | Sliding Window | gemini-3.5-flash-thinking | 333 | 95.5 | 1,127.3 | 1,050.0 | 11.6 | 2,188.9 | 1.848 | 847.8 (333) | 56.60 |
| R30 | seal0-64k | VERA | gemini-3.5-flash-thinking | 333 | 78.7 | 630.3 | 728.5 | 12.1 | 1,371.0 | 1.297 | 829.4 (329) | 60.69 |
| R31 | bc_v3 | Discard | gemini-3.5-flash-thinking | 300 | 97.3 | 1,411.6 | 1,161.7 | 23.3 | 2,596.6 | 2.164 | 1,769.6 (298) | 23.29 |
| R32 | bc_v3 | No Compression | gemini-3.5-flash-thinking | 300 | 96.0 | 3,666.4 | 3,033.8 | 19.3 | 6,719.5 | 5.274 | 1,529.5 (298) | 27.78 |
| R33 | bc_v3 | Summarize | gemini-3.5-flash-thinking | 300 | 93.0 | 1,515.1 | 1,747.3 | 18.1 | 3,280.6 | 3.011 | 1,592.3 (296) | 22.58 |
| R34 | bc_v3 | Sliding Window | gemini-3.5-flash-thinking | 300 | 95.7 | 1,511.5 | 1,392.2 | 17.9 | 2,921.6 | 2.476 | 1,569.6 (297) | 23.00 |
| R35 | bc_v3 | VERA | gemini-3.5-flash-thinking | 300 | 89.3 | 1,111.8 | 1,217.6 | 17.4 | 2,346.7 | 2.149 | 1,039.7 (300) | 29.10 |
| R36 | bc_v3 | VERA text-only | gemini-3.5-flash-thinking | 513 | 84.6 | 1,268.6 | 973.6 | 19.0 | 2,261.2 | 1.821 | 1,306.4 (511) | 23.73 |
| R37 | mmbrowsecomp | Discard | gemini-3.5-flash-thinking | 400 | 97.2 | 1,664.7 | 1,569.1 | 16.8 | 3,250.6 | 2.754 | 1,665.1 (400) | 21.59 |
| R38 | mmbrowsecomp | No Compression | gemini-3.5-flash-thinking | 400 | 97.5 | 5,355.4 | 3,763.4 | 23.2 | 9,141.9 | 6.657 | 1,586.6 (400) | 23.85 |
| R39 | mmbrowsecomp | Summarize | gemini-3.5-flash-thinking | 400 | 95.8 | 2,930.0 | 2,343.4 | 19.8 | 5,293.2 | 4.133 | 1,550.0 (400) | 20.89 |
| R40 | mmbrowsecomp | Sliding Window | gemini-3.5-flash-thinking | 400 | 97.8 | 3,031.9 | 1,898.4 | 21.6 | 4,951.9 | 3.497 | 1,625.2 (400) | 26.09 |
| R41 | mmbrowsecomp | VERA | gemini-3.5-flash-thinking | 400 | 85.5 | 1,455.2 | 1,367.7 | 16.1 | 2,838.9 | 2.414 | 1,115.6 (400) | 23.98 |
| R42 | mmbrowsecomp | VERA text-only | gemini-3.5-flash-thinking | 405 | 51.1 | 1,202.6 | 1,088.9 | 12.9 | 2,304.3 | 1.930 | 1,324.0 (402) | 22.71 |
| R43 | mmbrowsecomp | VERA text-only | gemini-3.5-flash-thinking | 400 | 0.0 | 342.5 | 305.4 | 3.7 | 651.6 | 0.543 | 322.0 (400) | NA |
| R44 | xbench_deepsearch | Discard | gemini-3.5-flash-thinking | 300 | 98.3 | 675.4 | 1,064.3 | 12.7 | 1,752.4 | 1.812 | 777.6 (300) | 68.14 |
| R45 | xbench_deepsearch | No Compression | gemini-3.5-flash-thinking | 300 | 98.7 | 2,040.9 | 1,827.8 | 11.5 | 3,880.2 | 3.151 | 749.3 (296) | 68.92 |
| R46 | xbench_deepsearch | Summarize | gemini-3.5-flash-thinking | 300 | 97.0 | 696.4 | 1,131.4 | 10.8 | 1,838.5 | 1.899 | 672.3 (300) | 68.38 |
| R47 | xbench_deepsearch | Sliding Window | gemini-3.5-flash-thinking | 300 | 97.7 | 738.5 | 1,036.6 | 10.4 | 1,785.5 | 1.759 | 707.2 (300) | 67.92 |
| R48 | xbench_deepsearch | VERA | gemini-3.5-flash-thinking | 300 | 96.0 | 600.8 | 809.5 | 13.3 | 1,423.5 | 1.424 | 783.9 (300) | 67.01 |
| R49 | AgenticDataBench | Discard | minimax-m3 | 246 | 100.0 | NA | NA | NA | NA | NA | 346.3 (246) | 20.73 |
| R50 | AgenticDataBench | No Compression | minimax-m3 | 246 | 100.0 | NA | NA | NA | NA | NA | 368.4 (246) | 18.29 |
| R51 | AgenticDataBench | Summarize | minimax-m3 | 246 | 100.0 | NA | NA | NA | NA | NA | 282.4 (246) | 16.67 |
| R52 | AgenticDataBench | Sliding Window | minimax-m3 | 246 | 100.0 | NA | NA | NA | NA | NA | 550.0 (246) | 20.33 |
| R53 | AgenticDataBench | VERA | minimax-m3 | 246 | 100.0 | NA | NA | NA | NA | NA | 330.4 (246) | 17.07 |
| R54 | AgenticDataBench | VERA text-only | minimax-m3 | 246 | 100.0 | NA | NA | NA | NA | NA | 299.4 (246) | 20.33 |
| R55 | AgenticDataBench | Summarize | gemini-3.5-flash-thinking | 246 | 100.0 | NA | NA | NA | NA | NA | 2,093.8 (246) | 15.45 |
| R56 | AgenticDataBench | VERA | gemini-3.5-flash-thinking | 246 | 100.0 | NA | NA | NA | NA | NA | 1,169.9 (246) | 11.79 |
| R57 | AgenticDataBench | VERA failed-render variant | minimax-m3 | 246 | 100.0 | NA | NA | NA | NA | NA | 409.9 (246) | 14.63 |

分组来源与成本数据覆盖：

| ID | 价格可用 n | 输入/输出计数可用 n | 主比较候选 | 原始分组 |
|---|---:|---:|---|---|
| R01 | 600 | 600 | False | `../hermes-agent/preds_archive/bc/gemini-3.5-flash-thinking-discard` |
| R02 | 443 | 443 | True | `../hermes-agent/preds_archive/bc/gemini35_flash_no_cc/browsecomp_subset_200` |
| R03 | 486 | 486 | True | `../hermes-agent/preds_archive/bc/gemini35_flash_summarize/browsecomp_subset_200` |
| R04 | 439 | 443 | True | `../hermes-agent/preds_archive/bc/gemini35_flash_sw/browsecomp_subset_200` |
| R05 | 428 | 428 | True | `../hermes-agent/preds_archive/bc/gemini35_flash_vis/browsecomp_subset_200` |
| R06 | 600 | 600 | False | `../hermes-agent/preds_archive/bc_v3_debug/gemini-3.5-flash-thinking-discard` |
| R07 | 600 | 600 | False | `../hermes-agent/preds_archive/bc_v3_debug/gemini-3.5-flash-thinking-no_cc` |
| R08 | 600 | 600 | False | `../hermes-agent/preds_archive/bc_v3_debug/gemini-3.5-flash-thinking-sm` |
| R09 | 600 | 600 | False | `../hermes-agent/preds_archive/bc_v3_debug/gemini-3.5-flash-thinking-sw` |
| R10 | 867 | 867 | True | `../hermes-agent/preds_archive/bc_zh/gemini-3.5-flash-thinking-discard` |
| R11 | 867 | 867 | True | `../hermes-agent/preds_archive/bc_zh/gemini-3.5-flash-thinking-no_cc` |
| R12 | 867 | 867 | True | `../hermes-agent/preds_archive/bc_zh/gemini-3.5-flash-thinking-sm` |
| R13 | 867 | 867 | True | `../hermes-agent/preds_archive/bc_zh/gemini-3.5-flash-thinking-sw` |
| R14 | 867 | 867 | True | `../hermes-agent/preds_archive/bc_zh/gemini-3.5-flash-thinking-vis` |
| R15 | 459 | 459 | True | `../hermes-agent/preds_archive/gemini35_flash_discard/browsecomp_subset_200` |
| R16 | 0 | 297 | False | `../hermes-agent/preds_archive/qwen35-122b-visual-scale0/browsecomp_subset_200` |
| R17 | 0 | 299 | False | `../hermes-agent/preds_archive/qwen35-122b-visual-scale0125/browsecomp_subset_200` |
| R18 | 0 | 300 | False | `../hermes-agent/preds_archive/qwen35-122b-visual-scale025/browsecomp_subset_200` |
| R19 | 0 | 300 | False | `../hermes-agent/preds_archive/qwen35-122b-visual-scale050/browsecomp_subset_200` |
| R20 | 0 | 297 | False | `../hermes-agent/preds_archive/qwen35-122b-visual-scale100/browsecomp_subset_200` |
| R21 | 333 | 333 | True | `../hermes-agent/preds_archive/seal0/gemini-3.5-flash-thinking-discard` |
| R22 | 333 | 333 | True | `../hermes-agent/preds_archive/seal0/gemini-3.5-flash-thinking-no_cc` |
| R23 | 333 | 333 | True | `../hermes-agent/preds_archive/seal0/gemini-3.5-flash-thinking-sm` |
| R24 | 333 | 333 | True | `../hermes-agent/preds_archive/seal0/gemini-3.5-flash-thinking-sw` |
| R25 | 333 | 333 | True | `../hermes-agent/preds_archive/seal0/gemini-3.5-flash-thinking-vis` |
| R26 | 333 | 333 | True | `../hermes-agent/preds_archive/seal0-64k/gemini-3.5-flash-thinking-discard` |
| R27 | 333 | 333 | True | `../hermes-agent/preds_archive/seal0-64k/gemini-3.5-flash-thinking-no_cc` |
| R28 | 333 | 333 | True | `../hermes-agent/preds_archive/seal0-64k/gemini-3.5-flash-thinking-sm` |
| R29 | 333 | 333 | True | `../hermes-agent/preds_archive/seal0-64k/gemini-3.5-flash-thinking-sw` |
| R30 | 333 | 333 | True | `../hermes-agent/preds_archive/seal0-64k/gemini-3.5-flash-thinking-vis` |
| R31 | 300 | 300 | True | `../hermes-agent/preds_archive/to_upload/bc_v3/gemini-3.5-flash-thinking-discard` |
| R32 | 300 | 300 | True | `../hermes-agent/preds_archive/to_upload/bc_v3/gemini-3.5-flash-thinking-no_cc` |
| R33 | 300 | 300 | True | `../hermes-agent/preds_archive/to_upload/bc_v3/gemini-3.5-flash-thinking-sm` |
| R34 | 300 | 300 | True | `../hermes-agent/preds_archive/to_upload/bc_v3/gemini-3.5-flash-thinking-sw` |
| R35 | 300 | 300 | True | `../hermes-agent/preds_archive/to_upload/bc_v3/gemini-3.5-flash-thinking-vis` |
| R36 | 513 | 513 | False | `../hermes-agent/preds_archive/to_upload/bc_v3/gemini-3.5-flash-thinking-vis_text` |
| R37 | 400 | 400 | True | `../hermes-agent/preds_archive/to_upload/mmbrowsecomp/gemini-3.5-flash-thinking-discard` |
| R38 | 400 | 400 | True | `../hermes-agent/preds_archive/to_upload/mmbrowsecomp/gemini-3.5-flash-thinking-no_cc` |
| R39 | 400 | 400 | True | `../hermes-agent/preds_archive/to_upload/mmbrowsecomp/gemini-3.5-flash-thinking-sm` |
| R40 | 400 | 400 | True | `../hermes-agent/preds_archive/to_upload/mmbrowsecomp/gemini-3.5-flash-thinking-sw` |
| R41 | 400 | 400 | True | `../hermes-agent/preds_archive/to_upload/mmbrowsecomp/gemini-3.5-flash-thinking-vis` |
| R42 | 405 | 405 | False | `../hermes-agent/preds_archive/to_upload/mmbrowsecomp/gemini-3.5-flash-thinking-vis-text` |
| R43 | 400 | 400 | False | `../hermes-agent/preds_archive/to_upload/mmbrowsecomp/gemini3.5-flash-thinking-vis-text` |
| R44 | 300 | 300 | True | `../hermes-agent/preds_archive/xbench_deepsearch/gemini-3.5-flash-thinking-discard` |
| R45 | 300 | 300 | True | `../hermes-agent/preds_archive/xbench_deepsearch/gemini-3.5-flash-thinking-no_cc` |
| R46 | 300 | 300 | True | `../hermes-agent/preds_archive/xbench_deepsearch/gemini-3.5-flash-thinking-sm` |
| R47 | 300 | 300 | True | `../hermes-agent/preds_archive/xbench_deepsearch/gemini-3.5-flash-thinking-sw` |
| R48 | 300 | 300 | True | `../hermes-agent/preds_archive/xbench_deepsearch/gemini-3.5-flash-thinking-vis` |
| R49 | 0 | 0 | False | `/mnt/afs_agents/sujiaqi/workspace/projects/databench/sources/AgenticDataBench/output/hermes-minimax-m3-discard-7ce54b6f` |
| R50 | 0 | 0 | False | `/mnt/afs_agents/sujiaqi/workspace/projects/databench/sources/AgenticDataBench/output/hermes-minimax-m3-none-b45bad21` |
| R51 | 0 | 0 | False | `/mnt/afs_agents/sujiaqi/workspace/projects/databench/sources/AgenticDataBench/output/hermes-minimax-m3-sm-c0938cc6` |
| R52 | 0 | 0 | False | `/mnt/afs_agents/sujiaqi/workspace/projects/databench/sources/AgenticDataBench/output/hermes-minimax-m3-sw-6e800105` |
| R53 | 0 | 0 | False | `/mnt/afs_agents/sujiaqi/workspace/projects/databench/sources/AgenticDataBench/output/hermes-minimax-m3-vis-e50b478c` |
| R54 | 0 | 0 | False | `/mnt/afs_agents/sujiaqi/workspace/projects/databench/sources/AgenticDataBench/output/hermes-minimax-m3-vis-text-only-7b239f63` |
| R55 | 0 | 0 | False | `/mnt/afs_agents/sujiaqi/workspace/projects/databench/sources/AgenticDataBench/output_archive_20260810_070633/hermes-gemini-3.5-flash-thinking-sm-ad680718` |
| R56 | 0 | 0 | False | `/mnt/afs_agents/sujiaqi/workspace/projects/databench/sources/AgenticDataBench/output_archive_20260810_070633/hermes-gemini-3.5-flash-thinking-vis-ff34b202` |
| R57 | 0 | 0 | False | `/mnt/afs_agents/sujiaqi/workspace/projects/databench/sources/AgenticDataBench/output_archive_failed_render_20260810_152529/hermes-minimax-m3-vis-v2-f4828793` |
