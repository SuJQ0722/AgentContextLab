# Rebuttal当前结果（只读统计）

采集完成：2026-11-13T18:07:09.574024+00:00。未调用模型或补判。

保留最早completed，不按答对挑选；RQ3仅合并新七页协议V10/V11/V12，不用旧分辨率结果填空。mean±std是三个repeat有效样本准确率的均值±样本标准差；缺失不补0，明确任务预算耗尽仍记0。分母不满300时不是完整avg3。

|Benchmark|模型/harness|方法|有效/300|各repeat有效N|mean±std (%)|
|---|---|---|---:|---|---:|
|bc100|deepseek-v4.1-flash-1017/dsh|discard|220/300|74/71/75|80.45 ± 5.61|
|bc100|deepseek-v4.1-flash-1017/dsh|none|265/300|92/85/88|80.28 ± 3.63|
|bc100|deepseek-v4.1-flash-1017/dsh|sliding_window|250/300|89/76/85|88.01 ± 0.32|
|bc100|deepseek-v4.1-flash-1017/dsh|summarize|239/300|85/74/80|89.18 ± 1.21|
|bc100|deepseek-v4.1-flash-1017/dsh|visual|223/300|84/71/68|84.71 ± 3.93|
|bc100|deepseek-v4.1-flash-1017/hermes|discard|300/300|100/100/100|63.67 ± 3.06|
|bc100|deepseek-v4.1-flash-1017/hermes|none|300/300|100/100/100|76.00 ± 2.65|
|bc100|deepseek-v4.1-flash-1017/hermes|sliding_window|300/300|100/100/100|73.67 ± 1.53|
|bc100|deepseek-v4.1-flash-1017/hermes|summarize|295/300|99/99/97|80.35 ± 1.39|
|bc100|deepseek-v4.1-flash-1017/hermes|visual|263/300|90/85/88|89.40 ± 3.41|
|bc100|gemini-3.5-flash-thinking/hermes|discard|247/300|83/77/87|72.25 ± 8.29|
|bc100|gemini-3.5-flash-thinking/hermes|none|182/300|64/62/56|67.01 ± 5.34|
|bc100|gemini-3.5-flash-thinking/hermes|sliding_window|188/300|57/70/61|71.16 ± 6.02|
|bc100|gemini-3.5-flash-thinking/hermes|summarize|238/300|78/79/81|70.60 ± 1.51|
|bc100|gemini-3.5-flash-thinking/hermes|visual|218/300|72/74/72|74.30 ± 3.02|
|mmbc100|deepseek-v4.1-flash-1017/hermes|discard|111/300|44/37/30|45.17 ± 6.36|
|mmbc100|deepseek-v4.1-flash-1017/hermes|none|88/300|32/32/24|80.21 ± 4.77|
|mmbc100|deepseek-v4.1-flash-1017/hermes|sliding_window|111/300|45/38/28|79.29 ± 6.88|
|mmbc100|deepseek-v4.1-flash-1017/hermes|summarize|87/300|36/29/22|81.60 ± 8.75|
|mmbc100|deepseek-v4.1-flash-1017/hermes|vanilla_visual|129/300|56/41/32|74.24 ± 3.47|
|mmbc100|deepseek-v4.1-flash-1017/hermes|visual|126/300|58/40/28|80.70 ± 1.99|
|rq3|deepseek-v4.1-flash-1017/hermes|scale_0.0|273/300|90/89/94|78.40 ± 1.39|
|rq3|deepseek-v4.1-flash-1017/hermes|scale_0.25|222/300|75/75/72|79.33 ± 3.71|
|rq3|deepseek-v4.1-flash-1017/hermes|scale_0.5|138/300|42/48/48|89.78 ± 5.41|
|rq3|deepseek-v4.1-flash-1017/hermes|scale_0.7|98/300|37/29/32|90.62 ± 3.93|
|rq3|deepseek-v4.1-flash-1017/hermes|scale_0.75|85/300|23/30/32|92.80 ± 1.31|
|rq3|deepseek-v4.1-flash-1017/hermes|scale_0.8|56/300|21/17/18|90.79 ± 3.87|
|rq3|deepseek-v4.1-flash-1017/hermes|scale_1.0|111/300|39/42/30|75.04 ± 7.24|

## 所有方法共同可评子集

|Benchmark|模型/harness|方法|共同题次N|各repeat N|mean±std (%)|
|---|---|---|---:|---|---:|
|bc100|deepseek-v4.1-flash-1017/dsh|none|173|64/52/57|87.24 ± 2.64|
|bc100|deepseek-v4.1-flash-1017/dsh|summarize|173|64/52/57|91.51 ± 2.60|
|bc100|deepseek-v4.1-flash-1017/dsh|sliding_window|173|64/52/57|88.48 ± 0.99|
|bc100|deepseek-v4.1-flash-1017/dsh|discard|173|64/52/57|85.11 ± 4.13|
|bc100|deepseek-v4.1-flash-1017/dsh|visual|173|64/52/57|87.95 ± 2.24|
|bc100|deepseek-v4.1-flash-1017/hermes|none|261|89/84/88|82.02 ± 1.23|
|bc100|deepseek-v4.1-flash-1017/hermes|summarize|261|89/84/88|84.74 ± 3.09|
|bc100|deepseek-v4.1-flash-1017/hermes|sliding_window|261|89/84/88|82.37 ± 0.51|
|bc100|deepseek-v4.1-flash-1017/hermes|discard|261|89/84/88|72.12 ± 4.56|
|bc100|deepseek-v4.1-flash-1017/hermes|visual|261|89/84/88|89.70 ± 3.74|
|bc100|gemini-3.5-flash-thinking/hermes|none|88|27/32/29|84.49 ± 7.39|
|bc100|gemini-3.5-flash-thinking/hermes|summarize|88|27/32/29|82.85 ± 6.16|
|bc100|gemini-3.5-flash-thinking/hermes|sliding_window|88|27/32/29|82.96 ± 3.18|
|bc100|gemini-3.5-flash-thinking/hermes|visual|88|27/32/29|87.34 ± 2.89|
|bc100|gemini-3.5-flash-thinking/hermes|discard|88|27/32/29|87.70 ± 8.49|
|mmbc100|deepseek-v4.1-flash-1017/hermes|discard|31|14/10/7|66.19 ± 7.87|
|mmbc100|deepseek-v4.1-flash-1017/hermes|none|31|14/10/7|84.76 ± 5.77|
|mmbc100|deepseek-v4.1-flash-1017/hermes|sliding_window|31|14/10/7|79.05 ± 7.19|
|mmbc100|deepseek-v4.1-flash-1017/hermes|summarize|31|14/10/7|83.81 ± 14.66|
|mmbc100|deepseek-v4.1-flash-1017/hermes|vanilla_visual|31|14/10/7|81.43 ± 3.78|
|mmbc100|deepseek-v4.1-flash-1017/hermes|visual|31|14/10/7|86.19 ± 6.44|
|rq3|deepseek-v4.1-flash-1017/hermes|scale_0.0|2|0/1/1|NA|
|rq3|deepseek-v4.1-flash-1017/hermes|scale_0.25|2|0/1/1|NA|
|rq3|deepseek-v4.1-flash-1017/hermes|scale_0.5|2|0/1/1|NA|
|rq3|deepseek-v4.1-flash-1017/hermes|scale_0.7|2|0/1/1|NA|
|rq3|deepseek-v4.1-flash-1017/hermes|scale_0.75|2|0/1/1|NA|
|rq3|deepseek-v4.1-flash-1017/hermes|scale_0.8|2|0/1/1|NA|
|rq3|deepseek-v4.1-flash-1017/hermes|scale_1.0|2|0/1/1|NA|

## 同题簇配对探索统计

只保留两方法三个repeat均有效的题簇；10000次题簇bootstrap与sign-flip，族内Holm校正。不是全300的显著性。

|Benchmark/model/harness|参考−对照|完整题簇|差值pp [95%CI]|Holm p|
|---|---|---:|---|---:|
|bc100/deepseek-v4.1-flash-1017/hermes|visual−none|80|7.08 [2.50, 12.08]|0.0112|
|bc100/deepseek-v4.1-flash-1017/dsh|visual−none|58|0.00 [-3.45, 3.45]|1.0000|
|bc100/deepseek-v4.1-flash-1017/hermes|visual−summarize|79|3.80 [0.00, 7.59]|0.0774|
|bc100/deepseek-v4.1-flash-1017/dsh|visual−summarize|55|-1.82 [-6.67, 3.03]|1.0000|
|bc100/deepseek-v4.1-flash-1017/hermes|visual−sliding_window|80|8.33 [3.33, 13.75]|0.0081|
|bc100/deepseek-v4.1-flash-1017/dsh|visual−sliding_window|55|0.00 [-3.64, 3.64]|1.0000|
|bc100/deepseek-v4.1-flash-1017/hermes|visual−discard|80|16.67 [10.42, 22.92]|0.0004|
|bc100/deepseek-v4.1-flash-1017/dsh|visual−discard|56|0.60 [-2.98, 4.17]|1.0000|
|mmbc100/deepseek-v4.1-flash-1017/hermes|visual−discard|9|14.81 [-3.70, 37.04]|1.0000|
|mmbc100/deepseek-v4.1-flash-1017/hermes|visual−none|10|-6.67 [-23.33, 6.67]|1.0000|
|mmbc100/deepseek-v4.1-flash-1017/hermes|visual−sliding_window|11|6.06 [0.00, 18.18]|1.0000|
|mmbc100/deepseek-v4.1-flash-1017/hermes|visual−summarize|7|-9.52 [-42.86, 14.29]|1.0000|
|mmbc100/deepseek-v4.1-flash-1017/hermes|visual−vanilla_visual|11|-12.12 [-30.30, 0.00]|1.0000|
|bc100/gemini-3.5-flash-thinking/hermes|visual−none|22|3.03 [-3.03, 10.61]|1.0000|
|bc100/gemini-3.5-flash-thinking/hermes|visual−summarize|41|2.44 [-2.44, 7.32]|1.0000|
|bc100/gemini-3.5-flash-thinking/hermes|visual−sliding_window|33|2.02 [-4.04, 8.08]|1.0000|
|bc100/gemini-3.5-flash-thinking/hermes|visual−discard|41|-3.25 [-11.38, 4.88]|1.0000|
|rq3/deepseek-v4.1-flash-1017/hermes|scale_1.0−scale_0.0|5|6.67 [0.00, 20.00]|1.0000|
|rq3/deepseek-v4.1-flash-1017/hermes|scale_1.0−scale_0.25|3|0.00 [0.00, 0.00]|1.0000|
