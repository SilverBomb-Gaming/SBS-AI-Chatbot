# Option B Mode Report — 21 Jan 2026 (PASS)

This refresh records the full unattended “Runs While I Sleep” validation executed locally on 21 Jan 2026 with screenshots enabled. Repo root is `E:/Documents old and new/Documents 2026/SBS-AI-Chatbot` and the Paid tier API server ran on `http://127.0.0.1:8000`.

## 1. Preconditions satisfied
- `APP_TIER=paid`, `X_API_KEYS=["runner-test-key-paid"]`, SQLite at `sqlite:///tickets.db`.
- Unity build present at `E:/AI projects 2025/AIE-TestHarness/Builds/Win64/TestHarness.exe`.
- `mss 10.1.0` installed so Windows screenshot capture works (requirement: desktop session, not CI).
- Flask server started via `python app.py` inside a PowerShell `Start-Job` with the env vars above.
- Runner env baseline:
  - `UNITY_EXE_PATH`, `AI_E_BASE_URL`, `AI_E_API_KEY`, `PROJECT_NAME`, `RUNNER_SCREENSHOTS=1`, `RUNNER_SCREENSHOT_INTERVAL=2`, `RUNNER_SCREENSHOT_MAX_CAPTURES=10`, `RUN_DURATION_SECONDS=120`.

## 2. Commands executed (breaker-sprint)
```powershell
# Install missing screenshot dependency
.venv\Scripts\pip.exe install mss>=9.0.1

# One-off BUILD_ID per run
$env:BUILD_ID="OptionB-$(Get-Date -Format 'yyyyMMdd_HHmmss')"

# Breaker sprint validation (screenshots ON, 2s cadence)
.venv\Scripts\python.exe -m runner.run_unity `
    --mode breaker `
    --scenario breaker-sprint `
    --screenshots 10 `
    --screenshot-interval 2
```
Screenshots were requested both via env vars and CLI overrides as shown above to satisfy the “always on” requirement. Earlier in the day a dry-run without `mss` logged a warning and produced no screenshots; installing `mss` resolved the gap.

## 3. Captured artifacts
- Run folder: `runner_artifacts/20260121_142352/`
- Logs: `logs/stdout.log` (Unity heartbeats, 5 lines), `logs/stderr.log` (empty)
- Screenshots (4 captures @ 2s cadence):
  1. `screenshot_20260121_142352_247649.png`
  2. `screenshot_20260121_142353_950183.png`
  3. `screenshot_20260121_142355_656824.png`
  4. `screenshot_20260121_142357_273864.png`
- No `episode_pending.json` was produced for this validated run. The only pending payload on disk is from an earlier misconfigured attempt (`runner_artifacts/20260121_141636/episode_pending.json`) when the API server was still on the public tier (404). It can be replayed manually if ever needed.

## 4. Episode verification
API call:
```powershell
curl -s -H "X-API-Key: runner-test-key-paid" `
  "http://127.0.0.1:8000/api/episodes?project=AIE-TestHarness&limit=5"
```
Relevant response excerpt (ID 6):
```json
{
  "source": "unity-runner",
  "mode": "breaker",
  "project": "AIE-TestHarness",
  "build_id": "OptionB-20260121_092351",
  "status": "pass",
  "metrics": {
    "duration_seconds": 5.76,
    "exit_code": 0,
    "screenshots_captured": 4
  },
  "artifacts": {
    "logs": [
      "E:/Documents old and new/Documents 2026/SBS-AI-Chatbot/runner_artifacts/20260121_142352/logs/stdout.log",
      "E:/Documents old and new/Documents 2026/SBS-AI-Chatbot/runner_artifacts/20260121_142352/logs/stderr.log"
    ],
    "screenshots": [
      "E:/Documents old and new/Documents 2026/SBS-AI-Chatbot/runner_artifacts/20260121_142352/screenshots/screenshot_20260121_142352_247649.png",
      "E:/Documents old and new/Documents 2026/SBS-AI-Chatbot/runner_artifacts/20260121_142352/screenshots/screenshot_20260121_142353_950183.png",
      "E:/Documents old and new/Documents 2026/SBS-AI-Chatbot/runner_artifacts/20260121_142352/screenshots/screenshot_20260121_142355_656824.png",
      "E:/Documents old and new/Documents 2026/SBS-AI-Chatbot/runner_artifacts/20260121_142352/screenshots/screenshot_20260121_142357_273864.png"
    ]
  },
  "labels": ["harness", "option-a", "breaker", "stress"],
  "scenario": {
    "scenario_id": "breaker-sprint",
    "scenario_name": "Breaker Sprint",
    "scenario_steps": ["Spawn player", "Trigger stress objects", "Force recover"],
    "expected": {"detect_crash": false, "max_recovery_time": 10},
    "observed": {
      "runtime_seconds": 5.76,
      "exit_code": 0,
      "status": "pass"
    }
  }
}
```

## 5. PASS conclusion
- Unity harness launched unattended, emitted heartbeats, and shut down cleanly.
- AI-E `/api/episodes` accepted the breaker payload (201) and persisted it in SQLite; records are retrievable with the Paid-tier API key.
- Runner artifacts contain logs + screenshots under the canonical `runner_artifacts/` root, satisfying the screenshots-on requirement for Option B.
- Failure handling confirmed: when the API tier was misconfigured the runner automatically wrote `episode_pending.json`, keeping evidence for manual replay.

Next unattended verification should reuse these steps, ensuring only the BUILD_ID and run folder differ per execution.
