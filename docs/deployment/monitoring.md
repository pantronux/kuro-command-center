# Monitoring

Use public-safe health endpoints for load balancers and VM monitors:

- `/api/live`
- `/api/ready`
- `/api/health`

Use admin-only endpoints for details:

- `/api/admin/observability/summary`
- `/api/admin/observability/security-events`
- `/api/admin/observability/market`
- `/api/admin/observability/memory`
- `/api/backup/status`
- `/api/system-status`

## Alert Suggestions

- `/api/ready` returns non-200
- backup status is `failed`
- no recent successful backup
- provider errors spike
- tool denials spike
- Telegram DLQ grows
- memory conflict count spikes
- SSE disconnects spike

Phoenix/OpenTelemetry remains available for trace analysis when enabled and
restricted to trusted users.
