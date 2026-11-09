# MMBC vanilla visual-rendering addon

The user defined vanilla as **rendering without visual evidence**. This is a
separate sixth method, `vanilla_visual`, with one CCI targeting 16 concurrent
trajectories. It contains exactly the same 100 questions and three paired repeat
identifiers as the running five-method MMBC campaign: **300 additional
trajectories**, making 1,800 observations across the six methods. The original
five-method plan, configuration, claims, and results remain unchanged.

The new root is `outputs/campaigns/mmbc100-hermes-vanilla-v1`. Its actual native
engine and job `strategy` remain `visual`; every job and report must also carry
`method_label=vanilla_visual`. Root identity and method label distinguish this
arm from VERA. Do not merge the two simply because their internal engine matches.

## Exact intervention

The new configuration copies the frozen parent and changes only:

1. `shared_policy.strategy_configs.visual.text_only = true`;
2. `campaign_version`, to identify this independent campaign;
3. the explicit `vanilla_visual_protocol` metadata.

The per-process renderer adapter suppresses structured table extraction so that
the original table text remains in the text body. The normal text-only renderer
omits images from the **compressed region** and renders the retained text. It does
not generate captions. Head/tail native images, original input images, all five
web/image tools, the protected message range, trigger, kept rounds, font16,
highlight layout, far-history scale1.0, model route, and trajectory budgets remain
the same as VERA. Thus this is an ablation of visual evidence inside the compressed
history, not a text-only agent, a caption baseline, or a no-highlighting layout.

Image token usage is **not matched** by construction: removing compressed-region
images can change canvas dimensions and image token cost. Report actual costs and
compression exposure instead of claiming otherwise. A trajectory which never
compresses has not received the intervention. The earlier audited bug in which
table text was removed together with its table object is specifically avoided;
offline rendering tests must establish retained table text before dispatch.

## Fixed inputs and lineage

`prepare_mmbc_vanilla.py --prepare-inputs` verifies the parent plan and copies its
public cohort, cohort manifest, all74 original input-image files, and image
manifest byte-for-byte into the new root. Files are independent copies, not
writable hard-link aliases into the parent. No network or model request is made.
The population remains69 initial-image and31 no-initial-image questions, with no
selection by result or image availability. The private standard answers stay in
the original isolated grader namespace; no gold or reference checklist enters the
new prediction root.

After the new native adapter, trial, controller, and bootstrap are stable,
`--prepare` freezes300 jobs, the exact parent plan/config/manifest hashes,
`vanilla-lineage.json`, and the inherited plus additional implementation hashes.
The binding also explicitly includes `render_dsh_history.py`, whose
`RenderFailures` helper is imported by the inherited Recorder. `--validate`
checks the parent lineage, exact allowed config differences, identical
question/repeat identities and assets, and the complete source bindings.

Native execution retains the reviewed `execution_version=hermes-parity-v3`
configuration contract. The independent plan uses the new campaign version;
the controller strictly allows only its300 `visual`/`vanilla_visual` observations.
The parent configuration's other campaign metadata remains preserved as lineage
and does not authorize launching its other four methods in this addon.

Existing claims/attempts are never automatically retried. Use a separate grader
namespace with the same isolated answer-equivalence protocol and explicit parent
source binding. Compare VERA and vanilla on paired question/repeat observations;
report missing outcomes, per-repeat coverage, actual token/caching/timing data,
and cost uncertainty. A lower score for vanilla is a hypothesis, not a condition
for selecting attempts or reporting the arm.
