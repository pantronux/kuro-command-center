# Backup And Restore

Kuro has admin-only backup routes:

- `GET /api/backup/status`
- `POST /api/backup/run`
- `GET /api/backup/history`

Backups are written under `KURO_BACKUP_DIR`.

## Manual Backup

```bash
curl -X POST https://<host>/api/backup/run \
  --cookie "kuro_access_token=<admin-token>"
```

Confirm that the result includes a manifest and a non-failed status.

## Restore Verification

Do restore verification on a separate VM or staging directory.

1. Stop the staging Kuro process.
2. Copy the selected backup archive set to a temporary restore directory.
3. Decompress SQLite and JSON artifacts.
4. Point `WORKING_DIR` to the restored copy.
5. Start Kuro with staging secrets.
6. Check `/api/ready`.
7. Log in as admin.
8. Verify chat history, memory, finance, intelligence, and backup history.
9. Run targeted smoke tests if the codebase is available.

Never restore production backups over live production data without a tested
rollback path.
