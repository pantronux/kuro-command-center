# KRC Refocus Phase 1 Profile Flags

Phase 1 adds an explicit Kuro Research Center profile without changing legacy
behavior by default.

## Profile

```env
KURO_APP_PROFILE=legacy
```

Supported values:

- `legacy`: current full Kuro app behavior.
- `krc`: Kuro Research Center mode.
- `dev`: all KRC profile features visible for local debugging.

## Public Capability

`GET /api/capabilities` now includes a secret-free `app_profile` field and a
`krc` capability block. This exposes only feature availability and product
labels, not keys, paths, database details, or internal topology.

## Admin Capability

`GET /api/admin/krc/profile` returns the full KRC profile snapshot for admins.
It requires the existing admin cookie auth and includes:

- normalized profile
- workspace label
- effective feature state
- raw flag names, defaults, and raw/effective booleans

## Default Behavior

With no env change, `KURO_APP_PROFILE` resolves to `legacy` and KRC-only feature
helpers return disabled. This keeps the existing UI/API behavior intact until
KRC mode is explicitly enabled.

## Verification

Run after Phase 1:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
```
