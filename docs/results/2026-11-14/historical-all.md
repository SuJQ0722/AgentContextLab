# 历史全部运行组

58组旧运行分别列出，不合并不同模型/预算/协议。超时NA表示旧导出不足以区分超时和其他缺失；不能以导出条数减有效数代替超时数。原始路径和repeat明细见[来源索引](../2026-11-13/historical-repeat-stats.json)。

|序号|Benchmark|模型|方法|有效/导出条数|repeat mean ± std (%)|超时/导出条数|
|---|---|---|---|---:|---:|---|
|1|AgenticDataBench|gemini-3.5-flash-thinking|Summarize|115/246|31.30 ± NA|NA/246|
|2|AgenticDataBench|gemini-3.5-flash-thinking|VERA|189/246|15.34 ± NA|NA/246|
|3|AgenticDataBench|minimax-m3|Discard|143/246|35.66 ± NA|NA/246|
|4|AgenticDataBench|minimax-m3|No Compression|137/246|32.85 ± NA|NA/246|
|5|AgenticDataBench|minimax-m3|Sliding Window|149/246|33.56 ± NA|NA/246|
|6|AgenticDataBench|minimax-m3|Summarize|141/246|29.08 ± NA|NA/246|
|7|AgenticDataBench|minimax-m3|VERA|143/246|29.37 ± NA|NA/246|
|8|AgenticDataBench|minimax-m3|VERA failed-render variant|136/246|26.47 ± NA|NA/246|
|9|AgenticDataBench|minimax-m3|VERA text-only|140/246|35.71 ± NA|NA/246|
|10|bc|gemini-3.5-flash-thinking|Discard|577/600|62.23 ± 1.26|NA/600|
|11|bc|gemini-3.5-flash-thinking|Discard|457/459|70.96 ± 3.77|NA/459|
|12|bc|gemini-3.5-flash-thinking|No Compression|442/443|62.69 ± 3.73|NA/443|
|13|bc|gemini-3.5-flash-thinking|Sliding Window|439/439|66.08 ± 1.33|NA/439|
|14|bc|gemini-3.5-flash-thinking|Summarize|478/486|68.00 ± 3.04|NA/486|
|15|bc|gemini-3.5-flash-thinking|VERA|393/428|71.03 ± 1.28|NA/428|
|16|bc|gpt-5.4-mini|Sliding Window|4/4|0.00 ± NA|NA/4|
|17|bc|qwen3.5-122b-a10b|scale0|43/297|60.42 ± 5.51|NA/297|
|18|bc|qwen3.5-122b-a10b|scale0125|39/299|77.90 ± 8.95|NA/299|
|19|bc|qwen3.5-122b-a10b|scale025|51/300|64.98 ± 8.75|NA/300|
|20|bc|qwen3.5-122b-a10b|scale050|47/300|39.85 ± 8.19|NA/300|
|21|bc|qwen3.5-122b-a10b|scale100|31/297|50.07 ± 10.91|NA/297|
|22|bc_v3|gemini-3.5-flash-thinking|Discard|292/300|23.29 ± NA|NA/300|
|23|bc_v3|gemini-3.5-flash-thinking|No Compression|288/300|27.78 ± NA|NA/300|
|24|bc_v3|gemini-3.5-flash-thinking|Sliding Window|287/300|23.00 ± NA|NA/300|
|25|bc_v3|gemini-3.5-flash-thinking|Summarize|279/300|22.58 ± NA|NA/300|
|26|bc_v3|gemini-3.5-flash-thinking|VERA|268/300|29.10 ± NA|NA/300|
|27|bc_v3|gemini-3.5-flash-thinking|VERA text-only|434/513|23.80 ± 0.48|NA/513|
|28|bc_v3_debug|gemini-3.5-flash-thinking|Discard|592/600|20.60 ± 0.66|NA/600|
|29|bc_v3_debug|gemini-3.5-flash-thinking|No Compression|596/600|25.18 ± 2.14|NA/600|
|30|bc_v3_debug|gemini-3.5-flash-thinking|Sliding Window|593/600|21.75 ± 0.19|NA/600|
|31|bc_v3_debug|gemini-3.5-flash-thinking|Summarize|579/600|22.98 ± 2.86|NA/600|
|32|bc_zh|gemini-3.5-flash-thinking|Discard|831/867|75.46 ± 0.74|NA/867|
|33|bc_zh|gemini-3.5-flash-thinking|No Compression|834/867|73.26 ± 1.10|NA/867|
|34|bc_zh|gemini-3.5-flash-thinking|Sliding Window|836/867|72.26 ± 1.38|NA/867|
|35|bc_zh|gemini-3.5-flash-thinking|Summarize|770/867|76.50 ± 2.93|NA/867|
|36|bc_zh|gemini-3.5-flash-thinking|VERA|823/867|75.83 ± 1.85|NA/867|
|37|mmbrowsecomp|gemini-3.5-flash-thinking|Discard|389/400|21.59 ± NA|NA/400|
|38|mmbrowsecomp|gemini-3.5-flash-thinking|No Compression|390/400|23.85 ± NA|NA/400|
|39|mmbrowsecomp|gemini-3.5-flash-thinking|Sliding Window|391/400|26.09 ± NA|NA/400|
|40|mmbrowsecomp|gemini-3.5-flash-thinking|Summarize|383/400|20.89 ± NA|NA/400|
|41|mmbrowsecomp|gemini-3.5-flash-thinking|VERA|342/400|23.98 ± NA|NA/400|
|42|mmbrowsecomp|gemini-3.5-flash-thinking|VERA text-only|207/405|44.36 ± 31.54|NA/405|
|43|mmbrowsecomp|gemini-3.5-flash-thinking|VERA text-only|0/400|NA ± NA|NA/400|
|44|seal0|gemini-3.5-flash-thinking|Discard|321/333|54.88 ± 4.64|NA/333|
|45|seal0|gemini-3.5-flash-thinking|No Compression|324/333|56.80 ± 1.45|NA/333|
|46|seal0|gemini-3.5-flash-thinking|Sliding Window|331/333|52.86 ± 3.27|NA/333|
|47|seal0|gemini-3.5-flash-thinking|Summarize|322/333|54.96 ± 2.31|NA/333|
|48|seal0|gemini-3.5-flash-thinking|VERA|330/333|51.83 ± 1.38|NA/333|
|49|seal0-64k|gemini-3.5-flash-thinking|Discard|294/333|57.23 ± 2.72|NA/333|
|50|seal0-64k|gemini-3.5-flash-thinking|No Compression|318/333|60.42 ± 4.50|NA/333|
|51|seal0-64k|gemini-3.5-flash-thinking|Sliding Window|318/333|56.58 ± 2.51|NA/333|
|52|seal0-64k|gemini-3.5-flash-thinking|Summarize|304/333|57.92 ± 1.83|NA/333|
|53|seal0-64k|gemini-3.5-flash-thinking|VERA|262/333|60.61 ± 6.46|NA/333|
|54|xbench_deepsearch|gemini-3.5-flash-thinking|Discard|295/300|68.15 ± 1.77|NA/300|
|55|xbench_deepsearch|gemini-3.5-flash-thinking|No Compression|296/300|68.91 ± 2.25|NA/300|
|56|xbench_deepsearch|gemini-3.5-flash-thinking|Sliding Window|293/300|67.92 ± 0.78|NA/300|
|57|xbench_deepsearch|gemini-3.5-flash-thinking|Summarize|291/300|68.40 ± 1.52|NA/300|
|58|xbench_deepsearch|gemini-3.5-flash-thinking|VERA|288/300|67.00 ± 1.79|NA/300|
