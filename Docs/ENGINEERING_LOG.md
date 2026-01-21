# Engineering Log

## [Bootstrap]
- Goal: Create runnable baseline with deterministic triage and Flask UI.
- Decision: Implement minimal tier-aware config loader, reusable decorators, placeholder services, and deterministic triage engine.
- Verification: `pip install -r requirements.txt`, `pytest -q`, and `python app.py`.

## [Milestone U0 - Brain Versioning]
- Goal: Introduce a versioned "AI Brain" with manual rollback while keeping deterministic triage output unchanged.
- Decision: Added SQLite brain tables + seed data, wired triage to load active brain rules, exposed `/admin/brain/rollback/<version_id>` with audit logging, and created pytest coverage for initialization and rollback safety checks.
- Verification: `pytest -q`

## [Option 1 - Tier Awareness]
- Goal: Add centralized tier selection + feature flags so future Paid/Ultimate work can toggle behavior without refactoring.
- Decision: Introduced tier sanitization + flag matrix in `config.py`, exposed flags through Flask `app.config`, and added pytest coverage for tier fallbacks and LLM assist gating.
- Verification: `pytest -q`

## [Option 2A - Feature Gating]
- Goal: Enforce feature flags consistently so endpoints remain dark until tiers explicitly enable them.
- Decision: Added `feature_enabled()` helper plus `@require_feature` decorator with hide/forbid modes, fail-closed responses, and JSON-vs-HTML handling; created dedicated pytest coverage and documentation updates.
- Verification: `pytest -q`

## [Phase A - Paid Auth Foundation]
- Goal: Prepare Paid/Ultimate tiers with secure-by-default API key parsing and documentation so GitHub push readiness is straightforward.
- Decision: Added JSON-aware API key parsing, stored sanitized keys as sets on app config, upgraded `@require_api_key` to use constant-time comparisons + JSON-aware 401s, introduced auth-focused pytest coverage, and refreshed README with project status/security guidance.
- Verification: `pytest -q`

## [Phase B - Episodes Intake]
- Goal: Stand up a secure “warehouse intake” for Unity QA runs without exposing new surface area to Public tier.
- Decision: Added `FEATURE_EPISODES` to the tier matrix (Paid/Ultimate only), created the `episodes` SQLite table, shipped `services.episodes` for validation/persistence, exposed gated POST/GET `/api/episodes` endpoints, and documented `.env`/README usage patterns.
- Verification: `ruff check .`, `black --check .`, `pytest -q`

## [Phase C1 - Unity Runner MVP]
- Goal: Add a standalone Unity runner that captures execution logs/screenshots and reports AI-E episodes automatically.
- Decision: Created the `runner` module with config validation, artifact management, screenshot capture, subprocess supervision, and AI-E POST + retry logic. Added pytest coverage for status mapping, payload construction, and artifact collection plus README/.env updates documenting required configuration.
- Verification: `ruff check .`, `black --check .`, `pytest -q`
