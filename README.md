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
- Tests + CI for everything above

**🚧 Planned next**
- Paid tier: ticket persistence, exports, richer rate limiting
- Ultimate tier: RBAC, deeper audit, webhooks, rules editor, LLM assist toggle
- AI Eyes: episode ingestion + Unity/runner integrations

## Quickstart

```
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
cp .env.example .env
python app.py
```

Visit http://127.0.0.1:8000 for the UI, or POST to `/api/triage` for JSON output. Run tests at any time with `python -m pytest -q`.

### Environment presets

```
# Public demo (default)
APP_TIER=public

# Paid staging (enables auth + persistence flags)
APP_TIER=paid
X_API_KEYS=alpha-paid,beta-paid

# Ultimate staging (turns on all flags, LLM assist still off by default)
APP_TIER=ultimate
X_API_KEYS=ops-admin
OPENAI_API_KEY= # optional, only flips FEATURE_LLM_ASSIST when set
```

> Never commit real API keys. Keep them in your private `.env` and share through your organization’s secret manager.

### Curl example (future Paid endpoints)

A future Paid-only endpoint (e.g., `/api/export`) will combine `@require_feature("FEATURE_AUTH")` with `@require_api_key`. When that lands, calls will look like:

```
curl -H "X-API-Key: <your-paid-key>" \
	-H "Accept: application/json" \
	http://localhost:8000/api/export
```

Until then, no production endpoints require the header—the infrastructure simply ensures we can switch it on without refactors.

## Feature & Tier Matrix

| Capability | Public | Paid | Ultimate |
| --- | --- | --- | --- |
| Rate limiting | ON (implemented) | ON (implemented) | ON (implemented) |
| API key auth | OFF | ON (infra implemented, feature roll-out pending) | ON (infra implemented, feature roll-out pending) |
| Persistence / exports | OFF | ON (planned) | ON (planned) |
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
