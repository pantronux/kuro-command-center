# Incident Response

Use this lightweight runbook for small enterprise pilots.

## First Five Minutes

1. Identify whether the issue affects availability, data, security, or billing.
2. Check `/api/live` and `/api/ready`.
3. Check admin observability and backup status.
4. Pause risky automation if needed by disabling feature flags in `.env`.
5. Preserve logs and backup manifests.

## Security Event

For prompt injection, tool misuse, cross-user access, or secret leakage:

1. Disable affected feature flags.
2. Rotate exposed secrets.
3. Review `/api/admin/observability/security-events`.
4. Preserve trace IDs and audit event IDs.
5. Document timeline, scope, containment, and recovery.

## Restore Event

Do not restore directly into production until a staging restore has passed.
Follow `backup_restore.md` and record the selected manifest.
