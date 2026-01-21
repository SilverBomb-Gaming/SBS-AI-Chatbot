# AIE Test Harness

## Quick facts
- **Purpose**: deterministic Unity project used to validate the AI-E runner without touching the public UI.
- **Unity version**: `2022.3.10f1` (mirrors [TestHarness/ProjectSettings/ProjectVersion.txt](TestHarness/ProjectSettings/ProjectVersion.txt)).
- **Primary scene**: `Assets/Scenes/TestHarness.unity` (always included in builds).
- **Build output**: place Windows builds under `E:/AI projects 2025/AIE-TestHarness/Builds/` (outside this repo) such as `.../Builds/Win64/TestHarness.exe`.

A lightweight Unity scene used to validate the AI-E C1 Unity Runner end to end without relying on Babylon. The scene boots instantly, renders a simple environment (floor, cubes, player capsule), and logs a steady heartbeat that AI-E ingests through `/api/episodes`.

## Unity Project Overview
- **Project**: `TestHarness` (matches Babylon's Unity version—update `ProjectSettings/ProjectVersion.txt` if required).
- **Scene**: `Assets/Scenes/TestHarness.unity`.
- **Runtime behavior**:
  - `HarnessSceneBootstrapper` ensures a plane, cubes, a camera tagged `MainCamera`, a directional light, and a player capsule with `SimplePlayerController` exist every time the scene loads.
  - `HarnessHeartbeat` logs:
    - Start timestamp.
    - Every 2 seconds: cumulative frame count plus FPS estimate.
    - On quit (manual or auto after 45 seconds by default): final summary.
  - The heartbeat can optionally auto-quit between 20–60 seconds (default 45 s) so each episode stays bounded.

## Build Output Path
1. Open the Unity project located in `TestHarness/` with the same Unity version Babylon used.
2. In **File → Build Settings…**
   - Target Platform: **Windows**.
   - Architecture: **x86_64**.
   - Scenes In Build: ensure `Assets/Scenes/TestHarness.unity` is the first entry.
   - **Build Location**: `E:/AI projects 2025/AIE-TestHarness/Builds/` (create a subfolder such as `Win64`) and name the player `TestHarness.exe`.
3. Click **Build** to produce `E:/AI projects 2025/AIE-TestHarness/Builds/Win64/TestHarness.exe` (path can vary, but keep it inside `Builds/`).

## Runner Configuration
The `runner/` package replaces Babylon-specific logic and always posts deterministic metadata.

### Environment file
Create `.env` in the repo root (or copy from `.env.example`) and set:

```
UNITY_EXE_PATH=E:/AI projects 2025/AIE-TestHarness/Builds/Win64/TestHarness.exe
AIE_API_URL=http://127.0.0.1:8000
AIE_API_KEY=<paid key>
RUN_DURATION_SECONDS=60
SCREENSHOT_EVERY_SECONDS=5
ARTIFACT_ROOT=artifacts
```

Environment variables:
- `UNITY_EXE_PATH` – absolute path to the built `TestHarness.exe`.
- `AIE_API_URL` – base URL for the Flask service (use `http://127.0.0.1:8000` or `5000`).
- `AIE_API_KEY` – bearer token used by the runner.
- `RUN_DURATION_SECONDS` – hard cap for each launch (set 20–60 to mirror the heartbeat auto-quit).
- `SCREENSHOT_EVERY_SECONDS` (optional) – captures desktop screenshots using `mss`; omit or set to `0` to disable.
- `ARTIFACT_ROOT` (optional) – folder for per-episode logs (`artifacts/` by default).

Install Python requirements (3.10+ recommended):

```
python -m pip install -r requirements.txt
```

## Running C1 Validation with TestHarness
1. **Start AI-E (Flask)**
   ```
   python -m api.app  # or your existing startup command
   ```

2. **Set environment** (PowerShell example):
   ```powershell
   Copy-Item .env.example .env  # if needed
   notepad .env                 # fill in values
   ```

3. **Launch the Unity runner**
   ```
   python -m runner.run_unity
   ```

   What happens:
   - The runner spawns `TestHarness.exe`, streams stdout/stderr to `artifacts/<timestamp>/stdout.log` and `stderr.log`, and (optionally) captures screenshots.
   - After the Unity player exits (auto-quit or duration cap), the runner zips all artifacts, posts an episode to `/api/episodes`, and logs the returned `episode_id`.

4. **Confirm ingestion**
   ```
   curl -H "Authorization: Bearer $AIE_API_KEY" http://127.0.0.1:8000/api/episodes | jq '.items[0]'
   ```
   Expected:
   - A new episode with `source="unity-runner"`, `project="AIE-TestHarness"`, `mode="freestyle"`, `build_id` containing the timestamp, `labels=["c1","harness"]`, and `metrics` including `duration_seconds` + `exit_code`.
   - Artifacts (stdout/stderr and optional screenshots) saved locally under `artifacts/` and referenced in the episode payload.

5. **Repeat / soak**
   - Re-running `python -m runner.run_unity` continuously will append episodes; the harness is deterministic so it can loop overnight without Babylon lockups.

## Episode Payload (server POST)
Example body the runner sends:

```json
{
  "source": "unity-runner",
  "mode": "freestyle",
  "project": "AIE-TestHarness",
  "build_id": "AIE-TestHarness-20260120-153015",
  "labels": ["c1", "harness"],
  "metrics": {
    "duration_seconds": 47.8,
    "exit_code": 0,
    "timed_out": false,
    "artifact_bytes": 183204
  },
  "artifacts": [
    {"name": "stdout.log", "path": "artifacts/20260120-153015/stdout.log"},
    {"name": "stderr.log", "path": "artifacts/20260120-153015/stderr.log"},
    {"name": "screenshots", "path": "artifacts/20260120-153015/screenshots"},
    {"name": "bundle", "path": "artifacts/20260120-153015/episode-bundle.zip"}
  ]
}
```

If `/api/episodes` requires multipart uploads, the runner already posts `payload` + a zipped artifact bundle; no Babylon hooks remain.

## Notes & Next Steps
- Update `ProjectVersion.txt` if Babylon used a different Unity editor build; Unity regenerates the rest of the ProjectSettings automatically on first import.
- To tweak heartbeat timing or auto-quit window, edit `HarnessHeartbeat` in `Assets/Scripts/`.
- The runner is self-contained—drop it into automation (GitHub Actions, scheduled task, etc.) to keep `/api/episodes` warm until Babylon stabilizes again.
