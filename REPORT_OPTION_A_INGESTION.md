# Option A Ingestion Report

Date: 20 Jan 2026

## Absolute Paths Verified
- Repository root: `E:/Documents old and new/Documents 2026/SBS-AI-Chatbot`
- Unity project metadata: `E:/Documents old and new/Documents 2026/SBS-AI-Chatbot/AIE-TestHarness/TestHarness/ProjectSettings/ProjectVersion.txt`
- External build root (kept outside git): `E:/AI projects 2025/AIE-TestHarness/Builds/`
- Runner executable used for this proof: `E:/AI projects 2025/AIE-TestHarness/Builds/Win64/TestHarness.exe`
- Runner artifacts: `E:/Documents old and new/Documents 2026/SBS-AI-Chatbot/unity_runner_artifacts/20260120_233835/`
- Flask API base: `http://127.0.0.1:8000` (paid tier)

## Unity Harness Summary
- Unity editor version: `2022.3.10f1` (per ProjectVersion.txt)
- Scene baked into build: `Assets/Scenes/TestHarness.unity`
- Expected build drop location: `E:/AI projects 2025/AIE-TestHarness/Builds/Win64/`
- For this Option A proof, a placeholder heartbeat player was produced at the same location via `dotnet publish` so the runner could exercise the ingestion contract until the real Unity build is exported.

### Build Command Used
```powershell
cd "E:/AI projects 2025/AIE-TestHarness/StubHarness"
dotnet publish -c Release -o "E:/AI projects 2025/AIE-TestHarness/Builds/Win64"
Rename-Item "E:/AI projects 2025/AIE-TestHarness/Builds/Win64/StubHarness.exe" "TestHarness.exe"
```

## Runner Execution
PowerShell session (venv interpreter) executed with APP_TIER=paid Flask server already running:

```powershell
$env:UNITY_EXE_PATH='E:/AI projects 2025/AIE-TestHarness/Builds/Win64/TestHarness.exe'
$env:RUN_DURATION_SECONDS='60'
$env:AI_E_BASE_URL='http://127.0.0.1:8000'
$env:AI_E_API_KEY='runner-key-paid'
$env:PROJECT_NAME='AIE-TestHarness'
$env:RUN_MODE='c1'
$env:BUILD_ID="AIE-TestHarness-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
& "E:/Documents old and new/Documents 2026/SBS-AI-Chatbot/.venv/Scripts/python.exe" -m runner.run_unity
```

Key runner log lines:
- `Artifacts stored in ... \unity_runner_artifacts\20260120_233835`
- `Episode posted successfully (status 201)`

## Episode Payload Example
Posted JSON (echoed from `/api/episodes` query after ingestion):

```json
{
  "source": "unity-runner",
  "mode": "c1",
  "status": "pass",
  "project": "AIE-TestHarness",
  "build_id": "AIE-TestHarness-20260120-183834",
  "metrics": {
    "duration_seconds": 5.18,
    "exit_code": 0
  },
  "artifacts": {
    "logs": [
      "E:/Documents old and new/Documents 2026/SBS-AI-Chatbot/unity_runner_artifacts/20260120_233835/logs/stdout.log",
      "E:/Documents old and new/Documents 2026/SBS-AI-Chatbot/unity_runner_artifacts/20260120_233835/logs/stderr.log"
    ],
    "screenshots": []
  },
  "labels": ["harness", "option-a"]
}
```

## API Verification
`curl.exe -s -H "X-API-Key: runner-key-paid" http://127.0.0.1:8000/api/episodes`

Response (abridged) confirming persistence:

```json
{
  "episodes": [
    {
      "id": 1,
      "created_at": "2026-01-20T23:38:40.474112+00:00",
      "created_by": "key:runn",
      "source": "unity-runner",
      "mode": "c1",
      "project": "AIE-TestHarness",
      "status": "pass",
      "metrics": {
        "duration_seconds": 5.18,
        "exit_code": 0
      },
      "labels": ["harness", "option-a"]
    }
  ]
}
```

## Harness Output Artifacts
- `stdout.log` snapshot:
  - `[HARNESS] boot 2026-01-20T23:38:35.302Z`
  - Heartbeats 1–5 emitted once per second
  - `[HARNESS] shutdown after 5.07s`
- `stderr.log`: empty (no runtime warnings)

## Warnings / Errors Encountered
1. Initial runner attempts hit `404 Resource not found` because an older public-tier Flask process (Microsoft Store Python) was already bound to `:8000`. Resolved by terminating PID 4180 and relaunching the paid-tier server from the project virtual environment via a PowerShell background job.
2. First paid-tier post failed with `{"error":"Invalid mode: c1"}` because the ingestion service only allowed `freestyle|instructed|breaker`. Updated `services/episodes.ALLOWED_MODES` to include `c1` and restarted the server.
3. Screenshot capture intentionally disabled for this run (no `SCREENSHOT_INTERVAL_SECONDS`) to keep option A focused on ingestion plumbing; logs confirmed recorder skipped as expected.

With the above corrections, external builds located outside the repo successfully produced a structured "episode" without touching the public UI, satisfying Option A.
