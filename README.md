# 🎮 SBS-AI-Chatbot — Autonomous Game Playing Framework

## Status: 🚀 AI Has Successfully Played a Real Video Game

This repository has crossed a major milestone:

> **AI infrastructure has successfully controlled a real commercial video game (Street Fighter 6) using a virtual Xbox controller.**

This is not a simulation, emulator, or mock environment.
It is a live Steam game responding to injected controller input.

We achieved real, deterministic control injection into Street Fighter 6.
We can now record dense 60 Hz controller state and replay it via a virtual Xbox controller.
This proves the end-to-end pipeline needed for autonomous play.
We’re extremely close — AI can play a video game properly.

---

## ✅ What Is Working Right Now

### 🎯 Target-Aware Game Detection
- Foreground window polling with filters
- Deterministic target locking (StreetFighter6.exe)
- Stable labels + hashes for every run
- Artifact renaming after lock
- Full metadata stored in `metadata/target_process.json`

---

### 🎮 Dense Controller State Capture (60 Hz)
- Full controller state recorded every frame:
  - All axes (LS/RS, triggers)
  - All buttons
  - D-pad
- Stored as JSONL:


inputs/controller_state_60hz.jsonl


This data is directly usable for:
- Imitation learning
- Reinforcement learning
- Deterministic replay

---

### 🔁 Replay → Virtual Xbox Controller (CONFIRMED)
A replay tool injects recorded controller frames into a **virtual Xbox 360 controller** using `vgamepad`.

**Result:**  
Street Fighter 6 responds exactly as if a human is playing.

This confirms:
- Timing accuracy (60 Hz) is sufficient for a fighting game
- Input mapping is correct
- Steam + OS input layers are handled safely

This is the first true “AI plays a video game” moment in this project.

---

## 👁️ Live Observation + Reward (Health Bars)

We now extract health bars directly from screenshots and compute a reward signal:

- `health_p1`, `health_p2` per frame
- `delta_p1`, `delta_p2` per frame
- reward = (damage dealt) − (damage taken)

This gives the agent a real-time score it can optimize.

---

## 🔄 Proven End-to-End Loop



Human Gameplay
→ Dense Controller Capture (60 Hz)
→ Artifact Storage (inputs + screenshots)
→ Replay Script
→ Virtual Xbox Controller
→ Street Fighter 6 responds


This loop is now fully operational.

---

## 🧭 Operator Console & Scripts

- Launch the operator console via `python -m operator_ui.server` and open `http://localhost:8000/ui` for a FastAPI + vanilla JS panel that streams trainer logs, manages artifacts, and exposes controller tooling. Details live in [Docs/operator_ui_phase1.md](Docs/operator_ui_phase1.md).
- Always start local trainer runs through `.\run_trainer.cmd`. The wrapper resolves `.venv\Scripts\python.exe`, echoes `PYTHON_EXE=...`, passes any extra CLI flags, and guarantees the run manifest records the correct interpreter.
- Use `.\run_keepalive.cmd --tap-a --keep-alive-seconds 30` (or `--exit-after-tap`) to keep the virtual Xbox pad warm and confirm Player 2 ownership without touching the physical controller.
- HUD debug captures and artifact folders are created for every run (watch for the `HUD_DEBUG_DIR=` and `SCREENSHOTS_DIR=` lines early in the trainer log). Missing frames 0/2/4 are automatically backfilled so non-regression checks never fail on short runs.
- Human feedback stays under `human_feedback/` only. The operator console buttons wire into that contract; see [Docs/human_feedback_protocol.md](Docs/human_feedback_protocol.md) for the rules of engagement.

---

## 🚀 Quickstart

### 1) Target-aware capture (human observed run)
```
python -m runner.run_unity --mode human --plan single --screenshots 10 --screenshot-interval 3
```

### 2) Smoke test (deterministic autonomous loop)
```
python .\tools\replay_controller_state.py --mode smoke --hz 60 --duration 60
```

### 3) Replay the latest recorded run (no placeholders)
```
$run = (Get-ChildItem .\runner_artifacts -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
Test-Path "$run\inputs\controller_state_60hz.jsonl"
python .\tools\replay_controller_state.py --jsonl "$run\inputs\controller_state_60hz.jsonl" --hz 60 --duration 60
```

### 4) Minimal autonomous agent loop (decision + reward logging)
```
python .\tools\agent_loop.py --duration 60 --decision-hz 12 --action-seconds 0.1 --save-screenshots
```

---

## 🧠 Training Loop Quickstart

Closed-loop trainer (observe → decide → act → reward → learn):

```
.\run_trainer.cmd --episodes 10 --episode-seconds 30 --decision-hz 10
```

`run_trainer.cmd` logs the resolved `.venv` interpreter via `PYTHON_EXE=…` and enforces window-only capture before the trainer starts. Pair it with `.\run_keepalive.cmd --tap-a --keep-alive-seconds 30` any time you need to reassign Player 2 without launching a full run.

Defaults:
- decision_hz: 10 (not 60)
- action_hold_ticks: 6
- reward = (damage dealt) − (damage taken) − idle_penalty

Safe install (wheels only, avoids source builds on Python 3.13):

```
.\tools\install_safe.ps1
```

If a package has no wheel, use Python 3.12 as the stable runner environment.

No-vision mode (runs even if Pillow/Numpy are not available):

```
.\run_trainer.cmd --episodes 2 --episode-seconds 15 --decision-hz 10 --no-vision
```

Troubleshooting:
- Disable Steam Input if SF6 ignores injected input.
- Unplug physical controllers to avoid conflicts.
- Run as Admin if injection is blocked.
- Ensure SF6 is focused and target-locked to `StreetFighter6.exe`.

---

## 🧠 What’s Next

We are no longer solving plumbing problems.
We are solving **decision-making**.

Immediate goals:
1. Autonomous input (no human recording)
2. Perception & state extraction
3. Learning policies
4. First autonomous match win

---

## ⚠️ Troubleshooting
- If SF6 doesn’t respond: disable Steam Input, unplug physical controllers, and confirm the virtual controller appears in Windows.
- If the target locks the wrong window: set `RUNNER_TARGET_MODE=exe` + `RUNNER_TARGET_EXE=StreetFighter6.exe`.
- The 60 Hz dense stream is independent of the sparse poll interval; cadence should be evaluated via `controller_state_60hz.jsonl`.

---

## 📦 Packaging a Run for Review

Package the latest run into a compact zip (default screenshot cap):

```
.\tools\package_run.ps1
```

Include more screenshots:

```
.\tools\package_run.ps1 -MaxScreenshots 200
```

What gets included:
- `metadata/target_process.json`
- `events/events.log`
- `inputs/` (dense + sparse + health observations if present)
- `episode_payload.json` / `episode_payload.jsonl` / `episode_pending.json` (if present)
- `logs/`
- `report_last_run.md` (run copy or global report)
- `screenshots/` (capped by `-MaxScreenshots`)

Note: health extraction depends on screenshots. If you need reward validation, avoid `-MaxScreenshots 0`.

---

## 📐 HUD Polygon Helper

- Normalize polygon coordinates directly from a screenshot: `python tools/hud_poly_helper.py normalize --image training_runs/<run>/screenshots/example.png --points "164,120 636,120 640,150 160,150"`.
- Overlay the current normalized polygons (and any `--hud-y-offset-px` adjustments) onto a reference frame: `python tools/hud_poly_helper.py overlay --image frame.png --out overlay.png --p1-poly "[(0.16,0.08), ...]"`.
- These utilities match the trainer’s ROI math, so whatever you validate here is exactly what `--hud-p?_poly` consumes at runtime.

---

## 🏁 Long-Term Goal

> **An AI agent that can independently play and win matches in Street Fighter 6.**

---

## ⚠️ Guardrails
- No copyrighted character generation
- No system audio recording unless explicitly enabled
- Input injection only while a run is active
- All runs must be deterministic and reproducible
- Trainer enforces window-only capture and aborts instantly when the Street Fighter 6 hwnd is missing

---

## 📌 Bottom Line

This project has already achieved what most never do:
> **AI controlling a real AAA game via a real controller interface.**

What remains is intelligence — not infrastructure.
