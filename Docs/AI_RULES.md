# AI Contribution Rules

AI assistants working on this repository must follow these guidelines:

1. Allowed paths: `core/`, `services/`, `web/`, `templates/`, `static/`, `tests/`, `Docs/`.
2. Never commit secrets or credentials. All configurable values belong in `.env` or `.env.example`.
3. Lockfiles (e.g., `poetry.lock`, `package-lock.json`) should only change when dependency updates require it. Provide justification in commit messages.
4. Every change must document intent, implementation, and verification steps.
5. Prefer deterministic, explainable logic. LLM features are optional add-ons and must never override deterministic outputs.
6. The "AI Brain" (rules, weights, templates) is immutable once approved. Revisions must follow propose → evaluate → promote and be recorded as new versions.
7. Never edit the active brain blob directly in the database; only update it via approved version promotion or the manual rollback endpoint.
