> 历史冻结快照：2026-11-12 10:43 UTC+8。不是当前V12运行状态；本次发布未重算该历史表，也未重新核对价格。最新代次结果见 [当前结果](current-generations.md)，总入口见 [README](README.md)。

# 历史模型成本、缓存和延迟重建（无新调用）

价格已于2026-11-12复核：[Google Cloud标准Global Gemini 3.5 Flash](https://cloud.google.com/model-garden/pricing)：cached $0.15/M、non-cache $1.50/M、output（含reasoning）$9/M。按相同单价重估用于比较，不是TokenHub实际账单；其他模型亦仅为Gemini等价价。未包含搜索/Reader、缓存存储、算力或未返回usage的费用。

原始重建22949条轨迹、57独立运行组。全部运行组保留，debug/消融不能合并进主对照。缓存命中率为cached/input的token加权比，非请求缓存命中率。压缩次数存在仅下界的trace和缺失，不能把缺失当0。API列是具备完整编号调用日志的客户端耗时，不是provider内部时间；不能用E2E减API推断渲染时间。渲染时间未记录时为NA。

系统排除只依据已记录provider/网络/存储错误；失败且有实际步数/API调用预算耗尽或force-final已使用证据记0；不因rounds>=100直接认定耗尽（部分历史任务上限200），未知timeout和未评分单列。成本全量表保留被剔除轨迹的已知消耗。Pareto和下列主表使用各benchmark所有方法共同可评分且token完整的题目×repeat交集，为条件比较，不是完整benchmark分数；缺失会产生选择偏差。

|Benchmark / model|方法|N|有评分N|Cached K|Non-cache K|Output K|Total K|Gemini等价$/题次|E2E秒|API客户端秒(覆盖N)|渲染秒|Cache hit%|压缩次数(覆盖N)|Acc%|
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---|---:|
|bc / gemini-3.5-flash-thinking|No Compression [bc paired]|164|164|1,210.7|926.9|9.3|2,146.8|1.655|458.0|34.7 (12)|NA|56.6|0.0 (164)|77.4|
|bc / gemini-3.5-flash-thinking|Summarize [bc paired]|164|164|373.9|542.5|9.2|925.6|0.953|416.1|37.3 (16)|NA|40.8|4.2 (9)|75.6|
|bc / gemini-3.5-flash-thinking|Sliding Window [bc paired]|164|164|581.6|677.3|10.0|1,268.9|1.193|497.1|41.4 (14)|NA|46.2|1.9 (17)|76.8|
|bc / gemini-3.5-flash-thinking|VERA [bc paired]|164|164|353.5|489.0|10.5|853.0|0.881|563.3|65.5 (15)|NA|42.0|2.5 (64)|82.3|
|bc / gemini-3.5-flash-thinking|Discard [bc paired]|164|164|339.5|532.5|9.3|881.3|0.934|428.8|39.6 (20)|NA|38.9|1.5 (4)|79.3|
|bc_zh / gemini-3.5-flash-thinking|Discard [bc_zh paired]|689|689|435.7|574.4|11.4|1,021.5|1.030|443.7|36.0 (115)|NA|43.1|NA (0)|82.9|
|bc_zh / gemini-3.5-flash-thinking|No Compression [bc_zh paired]|689|689|1,246.4|1,052.1|8.9|2,307.4|1.845|408.7|40.1 (114)|NA|54.2|0.0 (689)|80.3|
|bc_zh / gemini-3.5-flash-thinking|Summarize [bc_zh paired]|689|689|419.5|586.2|7.9|1,013.6|1.014|363.1|36.5 (114)|NA|41.7|NA (0)|81.6|
|bc_zh / gemini-3.5-flash-thinking|Sliding Window [bc_zh paired]|689|689|540.5|670.0|8.3|1,218.8|1.161|419.1|41.7 (134)|NA|44.6|NA (0)|79.8|
|bc_zh / gemini-3.5-flash-thinking|VERA [bc_zh paired]|689|689|364.7|477.9|9.8|852.3|0.859|400.5|37.5 (121)|NA|43.3|2.8 (239)|82.4|
|seal0 / gemini-3.5-flash-thinking|Discard [seal0 paired]|302|302|808.7|987.2|12.6|1,808.5|1.715|717.6|33.3 (16)|NA|45.0|NA (0)|57.0|
|seal0 / gemini-3.5-flash-thinking|No Compression [seal0 paired]|302|302|2,135.9|1,253.3|12.6|3,401.8|2.314|685.1|36.0 (21)|NA|63.0|0.0 (302)|57.3|
|seal0 / gemini-3.5-flash-thinking|Summarize [seal0 paired]|302|302|962.3|1,229.3|12.4|2,204.0|2.100|737.5|79.4 (19)|NA|43.9|NA (0)|57.0|
|seal0 / gemini-3.5-flash-thinking|Sliding Window [seal0 paired]|302|302|1,029.8|1,047.6|12.1|2,089.5|1.834|708.8|39.5 (19)|NA|49.6|NA (0)|55.0|
|seal0 / gemini-3.5-flash-thinking|VERA [seal0 paired]|302|302|861.7|856.7|14.0|1,732.4|1.540|806.2|42.2 (16)|NA|50.1|2.3 (185)|54.0|
|seal0-64k / gemini-3.5-flash-thinking|Discard [seal0-64k paired]|223|223|697.8|858.3|11.7|1,567.9|1.498|744.5|55.1 (18)|NA|44.8|NA (0)|65.9|
|seal0-64k / gemini-3.5-flash-thinking|No Compression [seal0-64k paired]|223|223|1,371.5|934.3|10.2|2,316.0|1.699|596.1|40.9 (22)|NA|59.5|0.0 (223)|68.6|
|seal0-64k / gemini-3.5-flash-thinking|Summarize [seal0-64k paired]|223|223|694.0|954.3|9.5|1,657.8|1.621|684.3|44.4 (21)|NA|42.1|NA (0)|64.6|
|seal0-64k / gemini-3.5-flash-thinking|Sliding Window [seal0-64k paired]|223|223|812.7|826.0|10.3|1,649.0|1.454|673.3|35.8 (17)|NA|49.6|NA (0)|65.5|
|seal0-64k / gemini-3.5-flash-thinking|VERA [seal0-64k paired]|223|223|577.1|723.7|13.1|1,313.9|1.290|761.3|46.6 (24)|NA|44.4|2.0 (111)|65.9|
|bc_v3 / gemini-3.5-flash-thinking|Discard [bc_v3 paired]|238|238|1,398.2|1,106.3|23.7|2,528.3|2.083|1,723.2|27.9 (3)|NA|55.8|NA (0)|24.8|
|bc_v3 / gemini-3.5-flash-thinking|No Compression [bc_v3 paired]|238|238|3,559.4|2,636.6|18.1|6,214.1|4.652|1,423.0|24.9 (2)|NA|57.4|0.0 (238)|28.6|
|bc_v3 / gemini-3.5-flash-thinking|Summarize [bc_v3 paired]|238|238|1,494.0|1,604.7|17.8|3,116.5|2.792|1,496.7|27.2 (4)|NA|48.2|NA (0)|24.8|
|bc_v3 / gemini-3.5-flash-thinking|Sliding Window [bc_v3 paired]|238|238|1,496.7|1,284.3|17.4|2,798.4|2.308|1,490.1|22.5 (3)|NA|53.8|NA (0)|23.5|
|bc_v3 / gemini-3.5-flash-thinking|VERA [bc_v3 paired]|238|238|1,079.5|1,164.2|17.3|2,261.0|2.064|1,000.6|28.7 (3)|NA|48.1|3.1 (174)|30.7|
|mmbrowsecomp / gemini-3.5-flash-thinking|Discard [mmbrowsecomp paired]|322|322|1,703.3|1,570.3|17.2|3,290.9|2.766|1,723.1|19.1 (1)|NA|52.0|NA (0)|22.4|
|mmbrowsecomp / gemini-3.5-flash-thinking|No Compression [mmbrowsecomp paired]|322|322|5,280.8|3,793.5|23.3|9,097.7|6.692|1,621.7|32.7 (1)|NA|58.2|0.0 (322)|23.9|
|mmbrowsecomp / gemini-3.5-flash-thinking|Summarize [mmbrowsecomp paired]|322|322|2,692.3|2,402.7|19.5|5,114.5|4.183|1,646.5|NA (0)|NA|52.8|NA (0)|21.1|
|mmbrowsecomp / gemini-3.5-flash-thinking|Sliding Window [mmbrowsecomp paired]|322|322|2,729.2|1,919.1|20.5|4,668.8|3.473|1,661.4|34.7 (1)|NA|58.7|NA (0)|26.1|
|mmbrowsecomp / gemini-3.5-flash-thinking|VERA [mmbrowsecomp paired]|322|322|1,561.8|1,427.6|17.0|3,006.4|2.529|1,197.6|50.6 (3)|NA|52.2|3.5 (288)|24.2|
|xbench_deepsearch / gemini-3.5-flash-thinking|Discard [xbench_deepsearch paired]|275|275|645.7|996.9|12.1|1,654.8|1.701|746.4|36.9 (23)|NA|39.3|NA (0)|70.9|
|xbench_deepsearch / gemini-3.5-flash-thinking|No Compression [xbench_deepsearch paired]|275|275|1,943.6|1,642.7|10.9|3,597.1|2.853|700.5|36.3 (19)|NA|54.2|0.0 (275)|72.4|
|xbench_deepsearch / gemini-3.5-flash-thinking|Summarize [xbench_deepsearch paired]|275|275|653.5|1,038.8|10.3|1,702.6|1.749|647.3|45.2 (23)|NA|38.6|NA (0)|70.9|
|xbench_deepsearch / gemini-3.5-flash-thinking|Sliding Window [xbench_deepsearch paired]|275|275|688.8|979.4|10.2|1,678.3|1.664|678.7|43.8 (27)|NA|41.3|NA (0)|69.8|
|xbench_deepsearch / gemini-3.5-flash-thinking|VERA [xbench_deepsearch paired]|275|275|597.4|778.1|12.8|1,388.3|1.372|743.3|42.2 (27)|NA|43.4|3.0 (137)|68.4|

## 全部运行组

|Benchmark / model|方法|N|有评分N|Cached K|Non-cache K|Output K|Total K|Gemini等价$/题次|E2E秒|API客户端秒(覆盖N)|渲染秒|Cache hit%|压缩次数(覆盖N)|Acc%|
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---|---:|
|bc / gemini-3.5-flash-thinking|Discard [gemini-3.5-flash-thinking-discard]|600|577|786.8|933.8|14.5|1,735.1|1.649|966.6|27.6 (28)|NA|45.7|NA (0)|62.2|
|bc / gemini-3.5-flash-thinking|No Compression [browsecomp_subset_200]|443|442|2,031.2|1,252.1|12.7|3,296.0|2.298|594.9|31.3 (27)|NA|61.9|0.0 (443)|62.7|
|bc / gemini-3.5-flash-thinking|Summarize [browsecomp_subset_200]|486|478|513.3|849.7|11.2|1,374.2|1.453|578.4|41.6 (41)|NA|37.7|4.9 (31)|68.0|
|bc / gemini-3.5-flash-thinking|Sliding Window [browsecomp_subset_200]|443|443|849.1|886.0|12.4|1,747.4|1.568|621.8|35.0 (34)|NA|48.9|4.3 (33)|65.5|
|bc / gemini-3.5-flash-thinking|VERA [browsecomp_subset_200]|428|393|502.2|663.5|12.3|1,178.1|1.182|691.8|51.6 (28)|NA|43.1|2.6 (229)|71.0|
|bc_v3_debug / gemini-3.5-flash-thinking|Discard [gemini-3.5-flash-thinking-discard]|600|592|1,135.6|1,447.1|24.3|2,607.0|2.560|1,089.8|79.4 (7)|NA|44.0|NA (0)|20.6|
|bc_v3_debug / gemini-3.5-flash-thinking|No Compression [gemini-3.5-flash-thinking-no_cc]|600|596|4,648.3|2,563.1|24.3|7,235.7|4.761|1,060.1|46.3 (7)|NA|64.5|0.0 (600)|25.2|
|bc_v3_debug / gemini-3.5-flash-thinking|Summarize [gemini-3.5-flash-thinking-sm]|600|579|1,493.6|1,982.5|21.9|3,498.1|3.395|1,133.2|61.8 (11)|NA|43.0|NA (0)|23.0|
|bc_v3_debug / gemini-3.5-flash-thinking|Sliding Window [gemini-3.5-flash-thinking-sw]|600|593|1,635.9|1,743.9|21.5|3,401.3|3.055|1,039.4|62.3 (3)|NA|48.4|NA (0)|21.8|
|bc_zh / gemini-3.5-flash-thinking|Discard [gemini-3.5-flash-thinking-discard]|867|831|568.5|742.0|14.2|1,324.7|1.326|565.5|36.1 (117)|NA|43.4|NA (0)|75.5|
|bc_zh / gemini-3.5-flash-thinking|No Compression [gemini-3.5-flash-thinking-no_cc]|867|834|1,742.9|1,453.2|10.7|3,206.8|2.538|513.9|39.6 (117)|NA|54.5|0.0 (867)|73.3|
|bc_zh / gemini-3.5-flash-thinking|Summarize [gemini-3.5-flash-thinking-sm]|867|770|541.1|759.5|9.0|1,309.6|1.302|440.7|35.8 (120)|NA|41.6|NA (0)|76.5|
|bc_zh / gemini-3.5-flash-thinking|Sliding Window [gemini-3.5-flash-thinking-sw]|867|836|709.8|896.2|9.9|1,615.8|1.540|537.1|41.6 (137)|NA|44.2|NA (0)|72.2|
|bc_zh / gemini-3.5-flash-thinking|VERA [gemini-3.5-flash-thinking-vis]|867|823|480.0|624.0|12.4|1,116.4|1.120|509.1|37.5 (122)|NA|43.5|3.2 (401)|75.8|
|bc / gemini-3.5-flash-thinking|Discard [browsecomp_subset_200]|459|457|509.1|707.8|13.0|1,229.9|1.255|558.6|42.0 (42)|NA|41.8|2.5 (11)|70.9|
|bc / qwen3.5-122b-a10b|scale0 [browsecomp_subset_200]|297|43|0.0|134.3|1.7|136.1|0.217|105.4|10.6 (19)|NA|0.0|1.2 (36)|60.5|
|bc / qwen3.5-122b-a10b|scale0125 [browsecomp_subset_200]|299|39|0.0|142.7|1.8|144.5|0.230|128.1|8.4 (25)|NA|0.0|1.2 (52)|79.5|
|bc / qwen3.5-122b-a10b|scale025 [browsecomp_subset_200]|300|51|0.0|158.8|2.2|161.0|0.258|138.4|13.5 (24)|NA|0.0|1.5 (55)|64.7|
|bc / qwen3.5-122b-a10b|scale050 [browsecomp_subset_200]|300|47|0.0|252.6|2.7|255.3|0.404|201.4|8.3 (29)|NA|0.0|2.3 (45)|40.4|
|bc / qwen3.5-122b-a10b|scale100 [browsecomp_subset_200]|297|31|0.0|237.3|2.7|240.0|0.380|196.1|10.1 (17)|NA|0.0|1.9 (56)|51.6|
|seal0 / gemini-3.5-flash-thinking|Discard [gemini-3.5-flash-thinking-discard]|333|321|812.1|985.7|12.3|1,810.1|1.711|722.3|32.3 (18)|NA|45.2|NA (0)|54.8|
|seal0 / gemini-3.5-flash-thinking|No Compression [gemini-3.5-flash-thinking-no_cc]|333|324|2,128.1|1,309.4|12.3|3,449.8|2.394|698.7|35.4 (22)|NA|61.9|0.0 (333)|56.8|
|seal0 / gemini-3.5-flash-thinking|Summarize [gemini-3.5-flash-thinking-sm]|333|322|939.5|1,262.2|12.3|2,214.1|2.145|740.7|79.4 (19)|NA|42.7|NA (0)|55.0|
|seal0 / gemini-3.5-flash-thinking|Sliding Window [gemini-3.5-flash-thinking-sw]|333|331|1,014.8|1,103.2|12.2|2,130.2|1.917|726.2|39.5 (19)|NA|47.9|NA (0)|52.9|
|seal0 / gemini-3.5-flash-thinking|VERA [gemini-3.5-flash-thinking-vis]|333|330|863.9|875.4|14.2|1,753.5|1.570|813.7|42.2 (16)|NA|49.7|2.3 (209)|51.8|
|seal0-64k / gemini-3.5-flash-thinking|Discard [gemini-3.5-flash-thinking-discard]|333|294|775.4|952.9|11.8|1,740.1|1.651|828.1|48.7 (22)|NA|44.9|NA (0)|57.1|
|seal0-64k / gemini-3.5-flash-thinking|No Compression [gemini-3.5-flash-thinking-no_cc]|333|318|2,244.2|1,103.3|11.0|3,358.4|2.090|729.7|40.2 (25)|NA|67.0|0.0 (333)|60.4|
|seal0-64k / gemini-3.5-flash-thinking|Summarize [gemini-3.5-flash-thinking-sm]|333|304|842.1|1,101.7|10.2|1,954.1|1.871|777.0|43.8 (23)|NA|43.3|NA (0)|57.9|
|seal0-64k / gemini-3.5-flash-thinking|Sliding Window [gemini-3.5-flash-thinking-sw]|333|318|1,127.3|1,050.0|11.6|2,188.9|1.848|847.8|33.0 (19)|NA|51.8|NA (0)|56.6|
|seal0-64k / gemini-3.5-flash-thinking|VERA [gemini-3.5-flash-thinking-vis]|333|262|630.3|728.5|12.1|1,371.0|1.297|829.4|42.0 (29)|NA|46.4|2.5 (186)|60.7|
|bc_v3 / gemini-3.5-flash-thinking|Discard [gemini-3.5-flash-thinking-discard]|300|292|1,411.6|1,161.7|23.3|2,596.6|2.164|1,769.6|27.9 (3)|NA|54.9|NA (0)|23.3|
|bc_v3 / gemini-3.5-flash-thinking|No Compression [gemini-3.5-flash-thinking-no_cc]|300|288|3,666.4|3,033.8|19.3|6,719.5|5.274|1,529.5|24.9 (2)|NA|54.7|0.0 (300)|27.8|
|bc_v3 / gemini-3.5-flash-thinking|Summarize [gemini-3.5-flash-thinking-sm]|300|279|1,515.1|1,747.3|18.1|3,280.6|3.011|1,592.3|27.2 (4)|NA|46.4|NA (0)|22.6|
|bc_v3 / gemini-3.5-flash-thinking|Sliding Window [gemini-3.5-flash-thinking-sw]|300|287|1,511.5|1,392.2|17.9|2,921.6|2.476|1,569.6|22.5 (3)|NA|52.1|NA (0)|23.0|
|bc_v3 / gemini-3.5-flash-thinking|VERA [gemini-3.5-flash-thinking-vis]|300|268|1,111.8|1,217.6|17.4|2,346.7|2.149|1,039.7|32.9 (4)|NA|47.7|3.1 (234)|29.1|
|bc_v3 / gemini-3.5-flash-thinking|VERA text-only [gemini-3.5-flash-thinking-vis_text]|513|434|1,268.6|973.6|19.0|2,261.2|1.821|1,306.4|30.3 (7)|NA|56.6|3.1 (397)|23.7|
|mmbrowsecomp / gemini-3.5-flash-thinking|Discard [gemini-3.5-flash-thinking-discard]|400|389|1,664.7|1,569.1|16.8|3,250.6|2.754|1,665.1|19.1 (1)|NA|51.5|NA (0)|21.6|
|mmbrowsecomp / gemini-3.5-flash-thinking|No Compression [gemini-3.5-flash-thinking-no_cc]|400|390|5,355.4|3,763.4|23.2|9,141.9|6.657|1,586.6|32.7 (1)|NA|58.7|0.0 (400)|23.8|
|mmbrowsecomp / gemini-3.5-flash-thinking|Summarize [gemini-3.5-flash-thinking-sm]|400|383|2,930.0|2,343.4|19.8|5,293.2|4.133|1,550.0|7.7 (1)|NA|55.6|NA (0)|20.9|
|mmbrowsecomp / gemini-3.5-flash-thinking|Sliding Window [gemini-3.5-flash-thinking-sw]|400|391|3,031.9|1,898.4|21.6|4,951.9|3.497|1,625.2|34.7 (1)|NA|61.5|NA (0)|26.1|
|mmbrowsecomp / gemini-3.5-flash-thinking|VERA [gemini-3.5-flash-thinking-vis]|400|342|1,455.2|1,367.7|16.1|2,838.9|2.414|1,115.6|50.6 (3)|NA|51.6|3.4 (366)|24.0|
|mmbrowsecomp / gemini-3.5-flash-thinking|VERA text-only [gemini-3.5-flash-thinking-vis-text]|405|207|1,202.6|1,088.9|12.9|2,304.3|1.930|1,324.0|31.0 (4)|NA|52.5|3.1 (339)|22.7|
|mmbrowsecomp / gemini-3.5-flash-thinking|VERA text-only [gemini3.5-flash-thinking-vis-text]|400|0|342.5|305.4|3.7|651.6|0.543|322.0|NA (0)|NA|52.9|3.0 (85)|NA|
|xbench_deepsearch / gemini-3.5-flash-thinking|Discard [gemini-3.5-flash-thinking-discard]|300|295|675.4|1,064.3|12.7|1,752.4|1.812|777.6|36.9 (23)|NA|38.8|NA (0)|68.1|
|xbench_deepsearch / gemini-3.5-flash-thinking|No Compression [gemini-3.5-flash-thinking-no_cc]|300|296|2,040.9|1,827.8|11.5|3,880.2|3.151|749.3|36.3 (19)|NA|52.8|0.0 (300)|68.9|
|xbench_deepsearch / gemini-3.5-flash-thinking|Summarize [gemini-3.5-flash-thinking-sm]|300|291|696.4|1,131.4|10.8|1,838.5|1.899|672.3|43.5 (24)|NA|38.1|NA (0)|68.4|
|xbench_deepsearch / gemini-3.5-flash-thinking|Sliding Window [gemini-3.5-flash-thinking-sw]|300|293|738.5|1,036.6|10.4|1,785.5|1.759|707.2|44.3 (28)|NA|41.6|NA (0)|67.9|
|xbench_deepsearch / gemini-3.5-flash-thinking|VERA [gemini-3.5-flash-thinking-vis]|300|288|600.8|809.5|13.3|1,423.5|1.424|783.9|42.2 (27)|NA|42.6|3.1 (160)|67.0|
|AgenticDataBench / minimax-m3|Discard [hermes-minimax-m3-discard-7ce54b6f]|246|239|NA|NA|NA|NA|NA|346.3|NA (0)|NA|NA|2.3 (45)|41.7|
|AgenticDataBench / minimax-m3|No Compression [hermes-minimax-m3-none-b45bad21]|246|235|NA|NA|NA|NA|NA|368.4|NA (0)|NA|NA|0.0 (246)|39.4|
|AgenticDataBench / minimax-m3|Summarize [hermes-minimax-m3-sm-c0938cc6]|246|242|NA|NA|NA|NA|NA|282.4|NA (0)|NA|NA|2.3 (52)|38.1|
|AgenticDataBench / minimax-m3|Sliding Window [hermes-minimax-m3-sw-6e800105]|246|241|NA|NA|NA|NA|NA|550.0|NA (0)|NA|NA|9.6 (50)|38.7|
|AgenticDataBench / minimax-m3|VERA [hermes-minimax-m3-vis-e50b478c]|246|243|NA|NA|NA|NA|NA|330.4|NA (0)|NA|NA|1.6 (50)|37.8|
|AgenticDataBench / minimax-m3|VERA text-only [hermes-minimax-m3-vis-text-only-7b239f63]|246|243|NA|NA|NA|NA|NA|299.4|NA (0)|NA|NA|1.4 (52)|41.5|
|AgenticDataBench / gemini-3.5-flash-thinking|Summarize [hermes-gemini-3.5-flash-thinking-sm-ad680718]|246|152|NA|NA|NA|NA|NA|2,093.8|NA (0)|NA|NA|8.9 (139)|36.6|
|AgenticDataBench / gemini-3.5-flash-thinking|VERA [hermes-gemini-3.5-flash-thinking-vis-ff34b202]|246|199|NA|NA|NA|NA|NA|1,169.9|NA (0)|NA|NA|2.5 (202)|17.2|
|AgenticDataBench / minimax-m3|VERA failed-render variant [hermes-minimax-m3-vis-v2-f4828793]|246|222|NA|NA|NA|NA|NA|409.9|NA (0)|NA|NA|1.4 (41)|35.8|
