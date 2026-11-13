# 历史所有运行组：准确率与repeat方差

只重算11月12日冻结的分类导出，不新增推理/评分。按benchmark、日志model、方法、原运行目录分组，不能把不同run或模型混在一起。共58组；原成本run表57组中有一个SW目录含4条不同model标签，本表已拆开。模型名是日志标签，不是provider权重独立验证。

各方法有效子集不同；缺失不补0。只有一个有记录的repeat时std=NA，不虚构avg3。debug、failed-render、不同预算和消融均独立列示，不能合并到主结果。

|Benchmark|模型|方法|有效/导出N|repeat有效分母|repeat mean±std (%)|run索引|
|---|---|---|---:|---|---:|---:|
|AgenticDataBench|gemini-3.5-flash-thinking|Summarize|115/246|115|31.30 ± NA|1|
|AgenticDataBench|gemini-3.5-flash-thinking|VERA|189/246|189|15.34 ± NA|2|
|AgenticDataBench|minimax-m3|Discard|143/246|143|35.66 ± NA|3|
|AgenticDataBench|minimax-m3|No Compression|137/246|137|32.85 ± NA|4|
|AgenticDataBench|minimax-m3|Sliding Window|149/246|149|33.56 ± NA|5|
|AgenticDataBench|minimax-m3|Summarize|141/246|141|29.08 ± NA|6|
|AgenticDataBench|minimax-m3|VERA|143/246|143|29.37 ± NA|7|
|AgenticDataBench|minimax-m3|VERA failed-render variant|136/246|136|26.47 ± NA|8|
|AgenticDataBench|minimax-m3|VERA text-only|140/246|140|35.71 ± NA|9|
|bc|gemini-3.5-flash-thinking|Discard|577/600|192/195/190|62.23 ± 1.26|10|
|bc|gemini-3.5-flash-thinking|Discard|457/459|151/147/159|70.96 ± 3.77|11|
|bc|gemini-3.5-flash-thinking|No Compression|442/443|151/149/142|62.69 ± 3.73|12|
|bc|gemini-3.5-flash-thinking|Sliding Window|439/439|142/152/145|66.08 ± 1.33|13|
|bc|gemini-3.5-flash-thinking|Summarize|478/486|159/160/159|68.00 ± 3.04|14|
|bc|gemini-3.5-flash-thinking|VERA|393/428|132/138/123|71.03 ± 1.28|15|
|bc|gpt-5.4-mini|Sliding Window|4/4|4|0.00 ± NA|16|
|bc|qwen3.5-122b-a10b|scale0|43/297|16/12/15|60.42 ± 5.51|17|
|bc|qwen3.5-122b-a10b|scale0125|39/299|11/11/17|77.90 ± 8.95|18|
|bc|qwen3.5-122b-a10b|scale025|51/300|18/17/16|64.98 ± 8.75|19|
|bc|qwen3.5-122b-a10b|scale050|47/300|15/13/19|39.85 ± 8.19|20|
|bc|qwen3.5-122b-a10b|scale100|31/297|9/14/8|50.07 ± 10.91|21|
|bc_v3|gemini-3.5-flash-thinking|Discard|292/300|292|23.29 ± NA|22|
|bc_v3|gemini-3.5-flash-thinking|No Compression|288/300|288|27.78 ± NA|23|
|bc_v3|gemini-3.5-flash-thinking|Sliding Window|287/300|287|23.00 ± NA|24|
|bc_v3|gemini-3.5-flash-thinking|Summarize|279/300|279|22.58 ± NA|25|
|bc_v3|gemini-3.5-flash-thinking|VERA|268/300|268|29.10 ± NA|26|
|bc_v3|gemini-3.5-flash-thinking|VERA text-only|434/513|260/174|23.80 ± 0.48|27|
|bc_v3_debug|gemini-3.5-flash-thinking|Discard|592/600|293/299|20.60 ± 0.66|28|
|bc_v3_debug|gemini-3.5-flash-thinking|No Compression|596/600|296/300|25.18 ± 2.14|29|
|bc_v3_debug|gemini-3.5-flash-thinking|Sliding Window|593/600|296/297|21.75 ± 0.19|30|
|bc_v3_debug|gemini-3.5-flash-thinking|Summarize|579/600|288/291|22.98 ± 2.86|31|
|bc_zh|gemini-3.5-flash-thinking|Discard|831/867|270/279/282|75.46 ± 0.74|32|
|bc_zh|gemini-3.5-flash-thinking|No Compression|834/867|278/278/278|73.26 ± 1.10|33|
|bc_zh|gemini-3.5-flash-thinking|Sliding Window|836/867|283/275/278|72.26 ± 1.38|34|
|bc_zh|gemini-3.5-flash-thinking|Summarize|770/867|256/257/257|76.50 ± 2.93|35|
|bc_zh|gemini-3.5-flash-thinking|VERA|823/867|278/273/272|75.83 ± 1.85|36|
|mmbrowsecomp|gemini-3.5-flash-thinking|Discard|389/400|389|21.59 ± NA|37|
|mmbrowsecomp|gemini-3.5-flash-thinking|No Compression|390/400|390|23.85 ± NA|38|
|mmbrowsecomp|gemini-3.5-flash-thinking|Sliding Window|391/400|391|26.09 ± NA|39|
|mmbrowsecomp|gemini-3.5-flash-thinking|Summarize|383/400|383|20.89 ± NA|40|
|mmbrowsecomp|gemini-3.5-flash-thinking|VERA|342/400|342|23.98 ± NA|41|
|mmbrowsecomp|gemini-3.5-flash-thinking|VERA text-only|207/405|204/3|44.36 ± 31.54|42|
|mmbrowsecomp|gemini-3.5-flash-thinking|VERA text-only|0/400|0|NA ± NA|43|
|seal0|gemini-3.5-flash-thinking|Discard|321/333|109/105/107|54.88 ± 4.64|44|
|seal0|gemini-3.5-flash-thinking|No Compression|324/333|108/106/110|56.80 ± 1.45|45|
|seal0|gemini-3.5-flash-thinking|Sliding Window|331/333|111/110/110|52.86 ± 3.27|46|
|seal0|gemini-3.5-flash-thinking|Summarize|322/333|108/108/106|54.96 ± 2.31|47|
|seal0|gemini-3.5-flash-thinking|VERA|330/333|109/111/110|51.83 ± 1.38|48|
|seal0-64k|gemini-3.5-flash-thinking|Discard|294/333|99/93/102|57.23 ± 2.72|49|
|seal0-64k|gemini-3.5-flash-thinking|No Compression|318/333|106/108/104|60.42 ± 4.50|50|
|seal0-64k|gemini-3.5-flash-thinking|Sliding Window|318/333|105/108/105|56.58 ± 2.51|51|
|seal0-64k|gemini-3.5-flash-thinking|Summarize|304/333|98/106/100|57.92 ± 1.83|52|
|seal0-64k|gemini-3.5-flash-thinking|VERA|262/333|89/88/85|60.61 ± 6.46|53|
|xbench_deepsearch|gemini-3.5-flash-thinking|Discard|295/300|99/97/99|68.15 ± 1.77|54|
|xbench_deepsearch|gemini-3.5-flash-thinking|No Compression|296/300|98/100/98|68.91 ± 2.25|55|
|xbench_deepsearch|gemini-3.5-flash-thinking|Sliding Window|293/300|97/98/98|67.92 ± 0.78|56|
|xbench_deepsearch|gemini-3.5-flash-thinking|Summarize|291/300|99/97/95|68.40 ± 1.52|57|
|xbench_deepsearch|gemini-3.5-flash-thinking|VERA|288/300|97/94/97|67.00 ± 1.79|58|
