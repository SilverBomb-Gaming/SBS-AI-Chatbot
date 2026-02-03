# TODO

## AI-E App Milestone Checklist (CodeX Handoff)
- [ ] Confirm runner artifact folder structure exists and is populated per run.
- [ ] Validate crash-safe behavior for partial artifacts + diagnostics.
- [ ] Verify version stamp written each run (git hash, build number, config hash).
- [ ] Confirm scene registry discovery + selector behavior.
- [ ] Fix KBM + gamepad parity and log control scheme/action map.
- [ ] Resolve weapon visibility, viewmodel layer, and URP material issues.
- [ ] Verify UI persistence fixes for ver004 and remove menu overlay leaks.
- [ ] Implement observed run input + mic logging guardrails.
- [ ] Validate runtime state model transitions + events.ndjson integrity.
- [ ] Ship Operator UI v0.1 features and last-run summary panel.
- [ ] Run smoke tests in §9 and record results in Logs/.

## Current Blockers (from handoff)
- [ ] KBM disabled (Input System/action map/controls scheme)
- [ ] Rifle viewmodel invisible (renderer/layer/culling/material/prefab)
- [ ] ver004 black screen + menu overlay (Canvas/DDOL leak or ver004 contains blocking UI)
