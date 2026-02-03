# AI-E App Milestone Checklist (CodeX Handoff)

Date: 2026-02-03
Source: User request in this session

## 0) Ground Rules
- No regressions: every change must pass the smoke tests in §9 before merge.
- One source of truth: log everything into Logs/ + update TODO.md.
- Guardrails: mic-only by default; record only while run is active; optional push-to-talk; never record system audio unless explicitly enabled.

## 1) Project “Spine” Audit (must be green before features)
Goal: ensure the runner can execute end-to-end reliably.
- Confirm folder structure exists:
  - runner_artifacts/YYYYMMDD_HHMMSS/
  - runner_artifacts/latest/ (symlink or copy)
  - Logs/
- Confirm artifact outputs are produced per run:
  - episode_payload.json
  - report_last_run.md
  - events.ndjson (or equivalent event log)
  - summary.json (key metrics)
- Confirm crash-safe behavior:
  - run writes partial artifacts on failure
  - error includes stack + last known state
- Confirm version stamp written each run (git hash, build number, config hash)
Acceptance: Start run → produces artifacts → exits cleanly OR fails with usable diagnostics.

## 2) Scene/Map Discovery + Selection (Unity side)
Goal: no hardcoded scene list; maps auto-discover.
- Keep GameplaySceneRegistry.asset generation working (EditorBuildSettings scan)
- Runtime loads registry and builds selector UI from it
- Selector buttons enable only when HasSceneInBuild && CanStreamedLevelBeLoaded
- MapProbe runs on scene load and logs:
  - root name + active state
  - renderer count
  - key layers visibility
Acceptance: Adding a new Babylon FPS game ver ### to Build Settings automatically shows in the menu after registry rebuild.

## 3) Input System Fix (KBM + Gamepad parity)
Goal: both KBM and Gamepad work without manual toggles.
- Ensure Player has PlayerInput with correct InputActionAsset
- On gameplay scene load:
  - force action map "Gameplay" (or correct map name)
  - log: currentControlScheme, currentActionMap
- Validate bindings exist:
  - Move (WASD), Look (Mouse delta), Fire (LMB)
- Add a one-time runtime check:
  - if map not active, attempt SwitchCurrentActionMap(), log warning
Acceptance: In ver001, WASD + mouse look + LMB fire works; gamepad still works.

## 4) Weapons & Viewmodels (Pistol + Rifle)
Goal: weapons visible + firing + correct audio.
- Verify weapon prefabs instantiate under correct weapon socket
- For rifle invisibility:
  - log instance name, parent, layer, renderer count, renderer.enabled states
  - confirm camera culling includes viewmodel layer
- If URP material issues:
  - implement “pink-material remediation” path (swap/upgrade shader or fallback material)
- Ensure weapon ScriptableObject bindings are valid or runtime-created consistently
Acceptance: Rifle mesh visible and firing in ver001; audio and visuals aligned.

## 5) UI Persistence + ver004 Black Screen Investigation
Goal: menu/UI does not leak into gameplay scenes.
- Keep Canvas/DDOL diagnostics enabled:
  - list canvases + active state + scene
  - list DDOL objects
- On gameplay load, enforce:
  - no MainMenu canvas remains
  - no stray EventSystem remains
- ver004 should be a control scene:
  - confirm Root=<missing> is expected
  - ensure it does not contain a blocking canvas or fade overlay
Acceptance: Loading ver004 shows intended visuals (or intentional emptiness) without menu overlay.

## 6) AI-E “Human Observed Run” Recording Layer
Goal: capture training data safely.
- Input logging:
  - record controller buttons/joysticks + KBM inputs (depending on control scheme)
  - store as timestamped events
- Audio logging:
  - mic-only by default
  - only while run active
  - optional push-to-talk mode
  - explicitly require opt-in for system audio
Acceptance: A run produces input+mic logs in artifacts folder and respects guardrails.

## 7) AI-E Runtime State Model
Goal: deterministic state transitions (no spaghetti).
- Define states:
  - Idle → Launching → InMenu → Loading → InGameplay → Paused → Ending → Complete/Failed
- Each state emits:
  - entry/exit events
  - key counters (time, attempts, scene name)
- Ensure state machine survives scene loads
Acceptance: events.ndjson shows clean state progression for a full session.

## 8) Operator UI / App v0.1 (the milestone deliverable)
Goal: minimal usable “AI-E app” that runs the pipeline.
- “Start Observed Run” button
- Map selector (registry-driven)
- Toggle: KBM vs Gamepad logging mode (auto-detect if possible)
- Toggle: mic logging on/off (mic-only default)
- “Stop Run” + “Write Report” buttons
- Last run summary panel:
  - scene name
  - duration
  - renderer count from MapProbe
  - inputs recorded count
  - mic recorded duration
  - any warnings/errors
Acceptance: A non-dev operator can run it without opening Unity logs.

## 9) Smoke Tests (must pass every time)
Run these before marking anything complete:
- Launch app → MainMenu loads
- Registry log shows scenes discovered
- Load ver001:
  - MapProbe root + renderer count present
  - KBM works
  - gamepad works
  - pistol visible/fires
  - rifle visible/fires (if equipped)
- Load ver004:
  - no menu canvas persists
  - DDOL list is sane (no UI canvases)
- Run “Observed Run” for 60s:
  - input events logged
  - mic logs if enabled
  - report written

## 10) Deliverables / Files CodeX must update
- TODO.md updated with completed items + next blockers
- Logs/WatchdogReport.txt updated if watchdog runs
- report_last_run.md includes:
  - scene name, control scheme, action map
  - weapon status
  - MapProbe summary
  - UI canvas/DDOL summary when loading ver004
- Current blockers to tag immediately:
  - KBM disabled (Input System/action map/controls scheme)
  - Rifle viewmodel invisible (renderer/layer/culling/material/prefab)
  - ver004 black screen + menu overlay (Canvas/DDOL leak or ver004 contains blocking UI)
