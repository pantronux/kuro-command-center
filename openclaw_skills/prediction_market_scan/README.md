# OpenClaw skill: `prediction_market_scan`

Returns **probability-style** market rows for HUD / Chancellor (informational only).

## Behaviour

1. If `METACULUS_API_TOKEN` is set, calls Metaculus `api2` (Bearer token) with `topics` as search string join.
2. Else if `KURO_PREDICTION_MARKET_DEMO=1`, returns a small **explicitly labeled demo** set (`source_url` uses `demo://` scheme) for UI wiring — never present as live exchange data.
3. Else returns `ok: true` with `markets: []` and `meta.note` explaining that no provider is configured.

## Contract

See `prediction_market_scan.py` docstring for the JSON schema (`topic_id`, `title`, `probability`, `unit`, `as_of`, `source_url`).

## Local test

```bash
python3 prediction_market_scan.py '{}'
KURO_PREDICTION_MARKET_DEMO=1 python3 prediction_market_scan.py '{"topics":["AI regulation"]}'
```
