# Kuro App Split Baseline

Captured before implementing the KRC/KCC/Kuro Knowledge logical split.

## Git

- Branch: `krc-kcc-knowledge-split`
- Rollback tag: `before-krc-kcc-knowledge-split`
- Baseline commit: `857c9d648c2a2bd424609a12495522fd788840a8`
- Previous working branch: `codex/krc-shell-prototype`
- Working tree note: the repo already had local modifications in `main.py`, `kuro_backend/chat_history.py`, exporter files, and `test_grand_auditor.py` before this split pass.

## Runtime

- Repo root: `/home/kuro/projects/kuro-command-center`
- Python: `Python 3.10.12` via `python3`
- `python` executable: not available in the shell PATH
- Existing KRC route: `GET /krc-shell`
- Existing KRC shell files:
  - `web_interface/templates/krc_shell.html`
  - `web_interface/static/js/krc_shell.js`
  - `web_interface/static/css/krc_shell.css`

## Runtime Backup

Runtime DB/env/JSON files were copied into:

```text
backups/pre-app-split/
├── root/
├── kuro_backend/
└── phoenix_data/
```

Primary copied files include:

```text
.env
.env.example
.env.production.example
benchmark_health.json
finance_data.db
kuro_auth.db
kuro_chat_history.db
kuro_compliance.db
kuro_enterprise_observability.db
kuro_finances.db
kuro_ingestion.db
kuro_intelligence.db
kuro_market_v2.db
kuro_memory.json
kuro_memory_v3.db
kuro_playground.db
kuro_short_term.db
kuro_telegram_v2.db
kuro_tools_v2.db
master_profile.json
kuro_backend/kuro_short_term.db
phoenix_data/phoenix.db
```

## Existing App-Profile State

The repo already had partial KRC profile support before this pass:

- `kuro_backend/krc_profile.py`
- `KURO_APP_PROFILE=legacy|krc|dev`
- KRC shell gated by `KURO_KRC_SHELL_ENABLED`
- Existing Advisor persona lock implemented as `advisor`
- Existing tests around KRC shell/profile/persona/scheduler behavior

## Split Direction

The new implementation adds explicit product roles:

```text
legacy
krc
kcc
knowledge
dev
```

`KURO_APP_ROLE` is the new product-level switch. `KURO_APP_PROFILE` remains as a compatibility input where existing tests and deployments still use it.
