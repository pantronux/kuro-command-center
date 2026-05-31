# App Split Rollback

Environment rollback:

```env
KURO_APP_ROLE=legacy
KURO_APP_PROFILE=legacy
KURO_KRC_SHELL_ENABLED=false
```

Git rollback anchors:

```bash
git switch main
git reset --hard before-krc-kcc-knowledge-split
```

Runtime backup:

```text
backups/pre-app-split/
```

Route rollback:

- Disable `/research` by leaving KRC role.
- Disable `/command-center` by leaving KCC role.
- Keep `/krc-shell` only when `KURO_KRC_SHELL_ENABLED=true` or KRC role is active.
