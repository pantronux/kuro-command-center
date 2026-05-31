# KCC Architecture

KCC is a physical clone scoped by `KURO_APP_ROLE=kcc`.

Runtime boundaries:

- Serves `/command-center`.
- Requires admin access for the Command Center shell.
- Keeps operational data in `/home/kuro/data/command-center`.
- Inspects Knowledge ingest jobs through the Kuro Knowledge HTTP API.
- Does not serve `/research` or `/krc-shell`.

Deferred prune:

The first physical split keeps some monorepo modules present on disk for import compatibility. Runtime route tests enforce the KCC boundary before hard pruning unrelated modules.
