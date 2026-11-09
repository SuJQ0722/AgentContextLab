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

## Deployment observation (2026-11-09 12:31 UTC)

The sixth CCI `acl-mmbc100-hermes-vanilla-v1` was submitted with 8 CPU,
32 GiB and a 16-worker controller. UID: `99958a8ed12748e086a7b9bc45f8ac6a`.
Its launch marker is published, so the validated bootstrap will start when the
platform allocates the node. The current state is PROGRESSING / ready 0, with
FailedScheduling 4300 waiting for a higher-priority job. There are zero native
workers and zero model calls from this arm so far; target 16 is not measured
active concurrency. Other compatible pools show the same priority blockage,
so no speculative stop/recreate or priority escalation was performed.

Independent lifecycle observer PID 343566 and private grader PID 344107 are
running. The original five methods continue separately. The six-method report
keeps all 1,800 planned observations, including the 300 currently missing vanilla
observations, and never fills those missing scores with zero.

Offline end-to-end rendering proof is stored in
`outputs/preflight/mmbc-vanilla-split-proof/audit.json`: both conditions preserve
the original head/tail image pixels; VERA renders both compressed-region images,
whereas vanilla renders zero of those two. A separate real-PDF test confirms
textual table facts survive while source image objects are absent. These are
synthetic offline checks, not a claim of completed paid vanilla trajectories.
