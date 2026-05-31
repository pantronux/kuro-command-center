# Kuro App Split

This split is logical first and physical later.

Roles:

```text
legacy     existing default behavior
krc        Kuro Research Center, PhD research cockpit
kcc        Kuro Command Center, operational control room
knowledge  Kuro Knowledge, approved knowledge and ingest service
dev        all role surfaces for local development
```

`KURO_APP_ROLE` is the product-level switch. `KURO_APP_PROFILE` remains for
compatibility, and maps `krc`/`dev` to the matching role when `KURO_APP_ROLE`
is unset.

Primary routes:

```text
/krc-shell       KRC compatibility route
/research        KRC future-facing alias
/command-center  KCC admin shell
/api/knowledge/* Kuro Knowledge APIs
/api/research/*  KRC research artifact APIs
```

Supporting docs:

- `00_baseline.md`
- `implementation_report.md`
- `final_acceptance.md`
- `rollback.md`
- `known_risks.md`
- `../deployment/app_split_same_vm.md`
- `../integrations/kuro_stack_contract.md`
