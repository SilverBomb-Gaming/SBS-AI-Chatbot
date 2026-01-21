# SBS AI Chatbot (AI Environment)

The SBS AI Environment (AI-E) is a governed execution space for support-triage experiments. It keeps deterministic logic in charge, versions every “brain” change, and layers in Paid/Ultimate capabilities only when feature flags allow it.

## What AI-E Delivers Today

- Deterministic-first triage engine powered by versioned keyword rules (“brains”).
- Manual rollback button for the active brain so risky changes can be undone instantly.
- Tier awareness via `APP_TIER` plus feature flags that fail closed when unset.
- Feature gating and API-key authentication decorators to keep future work safe by default.
- Comprehensive pytest suite + lint hooks to keep iterations honest.

## Project Status

**✅ Implemented now**
- Brain versioning + rollback + audit trail
- Tier config + feature flag matrix
- `@require_feature` + `feature_enabled` fail-closed gating
- API key parsing + `@require_api_key` decorator (ready for Paid/Ultimate routes)
- Episodes ingestion + listing endpoints (Paid/Ultimate, metadata-only)
- Tests + CI for everything above

**🚧 Planned next**
- Paid tier: ticket persistence, exports, richer rate limiting
- Ultimate tier: RBAC, deeper audit, webhooks, rules editor, LLM assist toggle
- AI Eyes Phase C: Unity “AI eyes” runner + automated QA playback

## Quickstart

```
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
cp .env.example .env
python app.py
```

Visit http://127.0.0.1:8000 for the UI, or POST to `/api/triage` for JSON output. Run tests at any time with `python -m pytest -q`.

### Option B — Unattended runs ("while I sleep")

Option B automates Unity playback so overnight smoke tours keep creating AI-E episodes with the logs, screenshots, and scenario metadata needed for human review. The runner can operate in `freestyle`, `instructed`, or `breaker` mode without touching the public UI; it boots the Windows standalone build, streams stdout/stderr into artifacts, optionally captures desktop screenshots, and posts a structured `/api/episodes` payload.

#### Required configuration

Environment variables (override with CLI flags when needed):

- `UNITY_EXE_PATH` – absolute path to the built player executable.
- `AI_E_BASE_URL` / `AI_E_API_KEY` – Paid/Ultimate ingestion endpoint + API key.
- `PROJECT_NAME` / `BUILD_ID` – labels that surface in the Episodes list.
- `RUN_MODE` – `freestyle`, `instructed`, `breaker`, or legacy `c1`.
- `RUN_DURATION_SECONDS` – soft runtime cap (breaker clamps to ≤90s automatically).
- `SCENARIO_ID` / `SCENARIOS_FILE` – select a scenario from `runner/scenarios.json` (required for instructed + breaker).
- `RUNNER_SCREENSHOTS` – `1` enables desktop capture, `0` disables (defaults to off unless a scenario/mode turns it on).
- `RUNNER_SCREENSHOT_INTERVAL` – optional override for capture cadence in seconds (falls back to scenario defaults or `5s`).
- `RUNNER_SCREENSHOT_MAX_CAPTURES` – optional hard limit on screenshots per run (`0` keeps capture disabled).
- Legacy aliases (`SCREENSHOT_INTERVAL_SECONDS`, `SCREENSHOT_MAX_CAPTURES`) are still honored for backwards compatibility.

#### Artifact layout

Every execution stores evidence inside `runner_artifacts/<run_id>/`:

```
runner_artifacts/<run_id>/
  logs/
	stdout.log
	stderr.log
  screenshots/            # only populated when desktop capture is enabled and running on Windows
  episode_pending.json    # written only if posting to /api/episodes fails
```

The runner logs the artifact path at startup, and these files are referenced directly inside the emitted episode payload for traceability.

#### Screenshot controls

- Desktop capture is only attempted on Windows hosts that are not running under `CI`; other platforms skip it automatically.
- Export `RUNNER_SCREENSHOTS=1` (or pass `--screenshots <count>` and `--screenshot-interval <seconds>`) to opt in; `RUNNER_SCREENSHOTS=0` guarantees screenshots stay off even if a scenario tries to override them.
- Breaker mode tightens the interval to ≤2s and caps screenshots at 20 unless you provide stricter values.

#### Episode posting and retries

- Successful runs call `/api/episodes` with metrics (`duration_seconds`, `exit_code`, `screenshots_captured`), the artifact paths shown above, scenario contracts, and auto-applied labels per mode.
- If the POST fails, the exact JSON payload is saved as `episode_pending.json` inside the artifact folder so it can be replayed later once connectivity is restored.

#### Example unattended commands

```
# Freestyle smoke (no screenshots)
python -m runner.run_unity --mode freestyle --scenario freestyle-smoke --screenshots 0

# Instructed guided tour (enable screenshots every 5s)
$env:RUNNER_SCREENSHOTS='1'
python -m runner.run_unity --mode instructed --scenario guided-tour --duration 60 `
	--screenshots 6 --screenshot-interval 5

# Breaker sprint (auto 45s cap + 2s screenshots)
$env:RUNNER_SCREENSHOTS='1'
python -m runner.run_unity --mode breaker --scenario breaker-sprint --screenshots 10 `
	--screenshot-interval 2
```

Status rules remain the same: exit code `0` → `pass`, non-zero exit → `fail`, runner-side exceptions → `error`. Every payload reports runtime metrics, artifact paths, and (when provided) the scenario contract inside both `metrics.scenario` and top-level `scenario` so `/api/episodes` echoes the entire contract back for auditing.

### Environment presets

```
# Public demo (default)
APP_TIER=public

# Paid staging (enables auth + persistence flags + episode intake)
APP_TIER=paid
X_API_KEYS=alpha-paid,beta-paid

# Ultimate staging (turns on all flags, LLM assist still off by default)
APP_TIER=ultimate
X_API_KEYS=ops-admin
OPENAI_API_KEY= # optional, only flips FEATURE_LLM_ASSIST when set
```

> Never commit real API keys. Keep them in your private `.env` and share through your organization’s secret manager.

### Curl example (future Paid endpoints)
### Episodes API (Paid/Ultimate)

Episodes capture QA or playtest runs as metadata (no binaries) so Unity “AI eyes” can report outcomes safely. Required fields: `source`, `mode` (`freestyle|instructed|breaker|c1`), and `status` (`pass|fail|error`). Optional context includes `project`, `build_id`, `seed`, `summary`, JSON `metrics`, link-based `artifacts`, `labels`, and a structured `scenario` contract describing how the run was orchestrated (`scenario_id`, `scenario_name`, `scenario_steps`, optional `scenario_seed`, expected vs. observed objects).

POST example:

```
curl -X POST http://localhost:8000/api/episodes \
	-H "X-API-Key: <paid-key>" \
	-H "Content-Type: application/json" \
	-d '{
			"source": "unity-runner",
			"mode": "instructed",
			"status": "pass",
			"project": "Babylon",
			"build_id": "build-123",
			"metrics": {"duration_seconds": 47.8, "exit_code": 0},
			"artifacts": ["s3://logs/run-123/output.txt"],
			"labels": ["paid", "tour"],
			"scenario": {
				"scenario_id": "guided-tour",
				"scenario_name": "Guided Site Tour",
				"scenario_steps": ["load", "walk", "capture screenshot", "exit"],
				"expected": {"no_crash": true},
				"observed": {"runtime_seconds": 47.8, "exit_code": 0}
			}
		}'
```

Listing example:

```
curl -H "X-API-Key: <paid-key>" \
	"http://localhost:8000/api/episodes?project=Babylon&status=pass&limit=25"
```

Use `/api/episodes/<id>` for single-record lookups. These endpoints are hidden entirely when `FEATURE_EPISODES` is off so Public tier remains unchanged.

## Feature & Tier Matrix

| Capability | Public | Paid | Ultimate |
| --- | --- | --- | --- |
| Rate limiting | ON (implemented) | ON (implemented) | ON (implemented) |
| API key auth | OFF | ON (infra implemented, feature roll-out pending) | ON (infra implemented, feature roll-out pending) |
| Persistence / exports | OFF | ON (planned) | ON (planned) |
| Episodes metadata intake | OFF | ON (implemented) | ON (implemented) |
| RBAC | OFF | OFF | ON (planned) |
| Audit log | Minimal (implemented) | Expanded (planned) | Extended + admin dashboards (planned) |
| Webhooks | OFF | OFF | ON (planned) |
| Rules editor | OFF | OFF | ON (planned) |
| LLM assist | OFF | OFF | CONDITIONAL (requires Ultimate tier + `OPENAI_API_KEY`) |

### Feature gating helpers

- `@require_feature("FEATURE_NAME", behavior="hide|forbid")` → 404 (hide) or 403 (forbid) with JSON-aware errors when a feature is disabled.
- `@require_api_key` → validates `X-API-Key` headers using constant-time comparison, returns `401` + `WWW-Authenticate: ApiKey` when missing or invalid.
- `feature_enabled("FEATURE_NAME")` / `auth_required()` → utility helpers for services that need to branch on flags.

## Security Model

- **Brains are immutable snapshots.** New rule sets ship as new versions; rollbacks are one DB update away.
- **No auto-learning yet.** Every change is intentional, reviewable, and logged in `Docs/ENGINEERING_LOG.md`.
- **Tier flags fail closed.** Missing env vars never enable features accidentally.
- **Auth is API-key based.** Only tiers that explicitly opt in (Paid/Ultimate) can reach future protected routes.
- **Decorators guard everything.** Routes compose `@require_feature`, `@require_api_key`, `@require_role`, and `@json_endpoint` so defenses stay consistent.

## Developer Commands

Helper commands live in `scripts/dev.py` and run via `python -m scripts.dev <command>`.

- `install` — install dependencies
- `run` — start the Flask dev server
- `test` — run `pytest -q`
- `lint` — run `ruff check .`
- `format` — run `black .`

## Repo Structure

```
app.py                # Flask entrypoint
config.py             # Runtime config loader + feature flags
core/                 # Deterministic triage engine
services/             # Decorators, rate limiter, persistence stubs
web/                  # Routes and blueprints
templates/ + static/  # UI assets
tests/                # Pytest suites (triage, auth, gating, etc.)
Docs/                 # AI guardrails and engineering log
scripts/dev.py        # Developer helper commands
```

## Roadmap to “polished”

- Ship Paid-tier persistence + CSV exports backed by SQLite.
- Add Ultimate RBAC, richer auditing, and webhook dispatch.
- Build safe rules editor + LLM assist plug-in that never overrides deterministic output.
- Stand up AI Eyes episode ingestion + Unity runner to replay escalations.
- Maintain green CI (pytest + ruff + black) and audit-friendly documentation for every milestone.
