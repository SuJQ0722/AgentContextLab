# Rebuttal experiments

This development branch prepares independent Hermes and DeepSeek Harness roots.
It does not claim that new experiments, DSH strategy adapters, native-image
baselines, or runtime instrumentation have already been implemented.

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
3. **Experiment 2:** DeepSeek Flash × DSH supplies one additional model/harness
   combination, not the requested two-model generalization by itself. Add the
   second model separately, and match task IDs, seeds, tools, budgets and strategy
   implementation. Use two text and two multimodal datasets initially.
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
