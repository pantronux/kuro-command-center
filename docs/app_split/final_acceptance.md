# App Split Final Acceptance

Accepted behavior:

- KRC is research-only by default.
- KRC forces `phd_advisor`.
- KRC `/krc-shell` remains available and `/research` is the alias.
- KCC is admin-only and owns operational modules.
- Kuro Knowledge owns approved search, candidate review, audit, redaction, and ingest jobs.
- Kuro Stack remains separate for daily chat and uses HTTP APIs only.
- Candidate write is disabled by default.
- QA, market, Telegram, daily tasks, and proactive surfaces are disabled or hidden from KRC defaults.
- Legacy mode remains available through `KURO_APP_ROLE=legacy`.

Verified by focused tests:

```text
tests/test_app_roles.py
tests/test_krc_phd_advisor_lock.py
tests/test_krc_research_routes.py
tests/test_krc_shell_officialization.py
tests/test_kcc_role_routes.py
tests/test_knowledge_service_role.py
tests/test_ingestion_boundary.py
tests/test_scheduler_role_split.py
tests/test_stack_knowledge_contract.py
tests/test_app_split_security.py
```
