# Option B Mode Report — Pending local run

The host where this update was produced cannot execute the Unity build, so this report documents the exact steps, expected artifacts, and verification flow you will see when running locally. All commands assume the repo lives at `E:/Documents old and new/Documents 2026/SBS-AI-Chatbot` and that the Paid-tier Flask server is running.

## 1. Runtime setup
- Unity build: `E:/AI projects 2025/AIE-TestHarness/Builds/Win64/TestHarness.exe`
- Scenario catalog: `runner/scenarios.json` (`freestyle-smoke`, `guided-tour`, `breaker-sprint`)
- Artifact root (auto-created): `runner_artifacts/<run_id>/`
- Screenshot support: requires Windows desktop plus the optional `mss` dependency; the runner detects non-Windows/CI hosts and skips capture.

## 2. Commands to run
```powershell
# Shared environment
$env:UNITY_EXE_PATH='E:/AI projects 2025/AIE-TestHarness/Builds/Win64/TestHarness.exe'
$env:AI_E_BASE_URL='http://127.0.0.1:8000'
$env:AI_E_API_KEY='runner-key-paid'       # redact in commits
$env:PROJECT_NAME='AIE-TestHarness'
$env:RUNNER_SCREENSHOTS='1'               # flip back to 0 to disable globally

# Freestyle smoke (no screenshots requested)
$env:BUILD_ID="AIE-TestHarness-FREESTYLE-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
python -m runner.run_unity --mode freestyle --scenario freestyle-smoke --screenshots 0

# Instructed guided tour (screens every 5s)
$env:BUILD_ID="AIE-TestHarness-INSTRUCTED-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
$env:RUNNER_SCREENSHOT_INTERVAL='5'
python -m runner.run_unity --mode instructed --scenario guided-tour --duration 60 `
    --screenshots 6 --screenshot-interval 5

# Breaker sprint (rapid sampling, breaker defaults enforce 2s cadence)
$env:BUILD_ID="AIE-TestHarness-BREAKER-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
python -m runner.run_unity --mode breaker --scenario breaker-sprint --duration 45 `
    --screenshots 10 --screenshot-interval 2
```

## 3. Expected artifacts per run
- Location: `runner_artifacts/<timestamp>/`
- Contents:
  - `logs/stdout.log` and `logs/stderr.log` — attached to each episode.
  - `screenshots/*.png` — created only when `RUNNER_SCREENSHOTS=1`, on Windows, and `mss` is installed.
  - `episode_pending.json` — written automatically if posting to `/api/episodes` fails (retry payload for Ops).

## 4. Episode payload snippet (breaker-sprint)
```json
{
  "source": "unity-runner",
  "mode": "breaker",
  "status": "pass",
  "project": "AIE-TestHarness",
  "build_id": "AIE-TestHarness-BREAKER-20260120-190032",
  "metrics": {
    "duration_seconds": 45.0,
    "exit_code": 0,
    "screenshots_captured": 10,
    "scenario": {
      "scenario_id": "breaker-sprint",
      "scenario_name": "Breaker Sprint",
      "scenario_steps": ["Spawn player", "Trigger stress objects", "Force recover"],
      "expected": {"detect_crash": false, "max_recovery_time": 10},
      "observed": {
        "runtime_seconds": 45.0,
        "exit_code": 0,
        "status": "pass",
        "logs": [
          "E:/Documents old and new/Documents 2026/SBS-AI-Chatbot/runner_artifacts/20260120_233245/logs/stdout.log",
          "E:/Documents old and new/Documents 2026/SBS-AI-Chatbot/runner_artifacts/20260120_233245/logs/stderr.log"
        ],
        "screenshots": [
          "E:/Documents old and new/Documents 2026/SBS-AI-Chatbot/runner_artifacts/20260120_233245/screenshots/screenshot_001.png"
        ]
      }
    }
  },
  "artifacts": {
    "logs": [
      "E:/Documents old and new/Documents 2026/SBS-AI-Chatbot/runner_artifacts/20260120_233245/logs/stdout.log",
      "E:/Documents old and new/Documents 2026/SBS-AI-Chatbot/runner_artifacts/20260120_233245/logs/stderr.log"
    ],
    "screenshots": [
      "E:/Documents old and new/Documents 2026/SBS-AI-Chatbot/runner_artifacts/20260120_233245/screenshots/screenshot_001.png"
    ]
  },
  "labels": ["harness", "option-a", "breaker", "stress"]
}
```

## 5. Verification checklist
1. `curl -H "X-API-Key: runner-key-paid" "http://127.0.0.1:8000/api/episodes?limit=5"`
   - Confirm the latest records show `mode` values for freestyle/instructed/breaker and contain the `scenario` contract echoed back.
   - Ensure `artifacts.logs` and `artifacts.screenshots` point at the matching `runner_artifacts/<run_id>/...` paths.
2. Open `runner_artifacts/<run_id>/logs/stdout.log` to inspect the Unity heartbeat lines per scenario.
3. If any POST fails, upload `runner_artifacts/<run_id>/episode_pending.json` manually via `curl -d @episode_pending.json` once connectivity returns.

## 6. Notes & caveats
- Desktop screenshots require Windows plus the `mss` package. Non-Windows or CI hosts log that capture was skipped, preventing headless environments from failing runs.
- `RUNNER_SCREENSHOTS=0` (or `--screenshots 0`) hard-disables capture even if scenarios request it, keeping CI stable.
- All commands above redact secrets; never commit real API keys.
