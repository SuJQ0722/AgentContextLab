# AgentContextLab development

This is the research orchestration root. Hermes source and its development guide
live in `hermes-agent/`; DeepSeek Harness is an upstream submodule pinned in
`harness-lock.json`. Follow each harness's own AGENTS.md when changing its code.

- Keep orchestration, experiment definitions, and cross-harness analyses at root.
- Root `.env` contains shared gateway credentials. Harness `.env` files are local
  to their own directories. Never print or commit secrets.
- Use configs/experiment.json for model and experimental settings.
- Do not silently change a pinned harness version or overwrite the customized
  Hermes baseline with an upstream release.
- New experiment results must distinguish measured values from estimates and
  missing instrumentation. Do not equate CLI duration with provider API latency.
- Root checks: `python -m unittest discover -s tests -v`.
- Hermes checks: `cd hermes-agent && scripts/run_tests.sh <test paths>`.
- Do not run paid evaluations unless requested. Dry-run commands make no API calls.
