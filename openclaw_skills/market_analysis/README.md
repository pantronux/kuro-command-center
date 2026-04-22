# OpenClaw skill: `market_analysis`

Read-only market data for Kuro's Chancellor / Market Sentinel.

## Operations (`op` in JSON payload)

- `get_ticker_price` — `symbol` (e.g. `NVDA`). Uses **Stooq** delayed CSV (no API key) for `.us` symbols by default.
- `get_market_news` — `symbol` for query context. If `NEWSAPI_API_KEY` is set, uses [NewsAPI](https://newsapi.org/) `everything`; otherwise returns an empty `articles` list (no fabricated headlines).

## Optional providers

- `STOCKBIT_API_TOKEN` — If your Stockbit contract allows programmatic access, extend `market_analysis.py` to call their official endpoint (not shipped as default scraping).

## Contract

See module docstring in `market_analysis.py` for success / error JSON shapes consumed by `kuro_backend.execution.openclaw_bridge`.

## Local test

```bash
python3 market_analysis.py '{"op":"get_ticker_price","symbol":"NVDA"}'
```
