#!/usr/bin/env python3
"""OpenClaw skill: market_analysis.

Contract (JSON printed to stdout for the Kuro bridge):

  Success (price)::
    {
      "ok": true,
      "status": "ok",
      "skill_name": "market_analysis",
      "op": "get_ticker_price",
      "symbol": "NVDA",
      "price": 199.88,
      "currency": "USD",
      "as_of": "2026-04-21T22:00:19Z",
      "source": "stooq_csv",
      "change_pct": null
    }

  Success (news, possibly empty)::
    {
      "ok": true,
      "status": "ok",
      "skill_name": "market_analysis",
      "op": "get_market_news",
      "symbol": "NVDA",
      "articles": [{"title": "...", "url": "...", "published_at": "...", "sentiment_hint": "neutral"}],
      "source": "newsapi" | "none"
    }

  Failure::
    {"ok": false, "status": "error", "skill_name": "market_analysis",
     "error_code": "invalid_params" | "provider_error" | "internal",
     "user_message": "..."}

--- Header Doc ---
Purpose: OpenClaw readonly skill — ticker price via Stooq CSV + optional NewsAPI news lookup.
Caller: OpenClaw daemon (invoked by Kuro tools + dreaming_worker market sentinel).
Dependencies: requests (HTTP), stdlib csv/json/argparse; NEWSAPI_API_KEY for news op.
Main Functions: main(op, symbol) CLI entry, _get_ticker_price, _get_market_news.
Side Effects: Outbound HTTPS (stooq.com, newsapi.org); prints JSON to stdout.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

SKILL_NAME = "market_analysis"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _failure(code: str, msg: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "status": "error",
        "skill_name": SKILL_NAME,
        "error_code": code,
        "user_message": msg,
    }


def _stooq_ticker(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not s:
        return ""
    return f"{s.lower()}.us"


def _get_ticker_price(symbol: str) -> Dict[str, Any]:
    if not requests:
        return _failure("internal", "requests library not installed on OpenClaw host")
    sym = (symbol or "").strip().upper()
    if not sym or len(sym) > 12:
        return _failure("invalid_params", "symbol is required (e.g. NVDA)")
    q = _stooq_ticker(sym)
    url = f"https://stooq.com/q/l/?s={q}&f=sd2t2ohlcv&h&e=csv"
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": "Kuro-market-analysis/1.0"})
    except Exception as exc:
        return _failure("provider_error", f"upstream network error: {exc}")
    if resp.status_code != 200:
        return _failure("provider_error", f"stooq HTTP {resp.status_code}")
    text = (resp.text or "").strip()
    if not text or "No data" in text:
        return _failure("provider_error", f"No price data for symbol {sym}")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return _failure("provider_error", "empty CSV from provider")
    row = rows[-1]
    close_raw = (row.get("Close") or row.get("close") or "").strip()
    try:
        price = float(close_raw)
    except (TypeError, ValueError):
        return _failure("provider_error", "could not parse close price")
    dt = (row.get("Date") or "").strip()
    tm = (row.get("Time") or "").strip()
    as_of = _now_iso()
    if dt and tm:
        try:
            as_of = datetime.strptime(f"{dt} {tm}", "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc,
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    return {
        "ok": True,
        "status": "ok",
        "skill_name": SKILL_NAME,
        "op": "get_ticker_price",
        "symbol": sym,
        "price": round(price, 6),
        "currency": "USD",
        "as_of": as_of,
        "source": "stooq_csv",
        "change_pct": None,
    }


def _get_market_news(symbol: str) -> Dict[str, Any]:
    sym = (symbol or "").strip().upper()
    if not sym:
        return _failure("invalid_params", "symbol is required for news query")
    key = (os.getenv("NEWSAPI_API_KEY") or "").strip()
    articles: List[Dict[str, Any]] = []
    src = "none"
    if not key or not requests:
        return {
            "ok": True,
            "status": "ok",
            "skill_name": SKILL_NAME,
            "op": "get_market_news",
            "symbol": sym,
            "articles": articles,
            "source": src,
            "meta": {"note": "NEWSAPI_API_KEY not set; no headlines fetched."},
        }
    try:
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": sym,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 8,
            },
            headers={"X-Api-Key": key},
            timeout=20,
        )
        data = resp.json() if resp.text else {}
    except Exception as exc:
        return _failure("provider_error", str(exc))
    if resp.status_code != 200:
        return _failure("provider_error", data.get("message") or f"newsapi HTTP {resp.status_code}")
    src = "newsapi"
    for a in (data.get("articles") or [])[:8]:
        if not isinstance(a, dict):
            continue
        articles.append(
            {
                "title": (a.get("title") or "")[:300],
                "url": a.get("url") or "",
                "published_at": a.get("publishedAt") or "",
                "sentiment_hint": "neutral",
            }
        )
    return {
        "ok": True,
        "status": "ok",
        "skill_name": SKILL_NAME,
        "op": "get_market_news",
        "symbol": sym,
        "articles": articles,
        "source": src,
    }


def run(params: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(params, dict):
        return _failure("invalid_params", "payload must be a JSON object")
    op = str(params.get("op") or "").strip().lower()
    symbol = str(params.get("symbol") or "")
    if op == "get_ticker_price":
        return _get_ticker_price(symbol)
    if op == "get_market_news":
        return _get_market_news(symbol)
    return _failure("invalid_params", f"unknown op {op!r}; use get_ticker_price or get_market_news")


def _cli() -> int:
    raw = sys.argv[1] if len(sys.argv) > 1 else "{}"
    try:
        params = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps(_failure("invalid_params", str(exc)), ensure_ascii=False))
        return 2
    out = run(params if isinstance(params, dict) else {})
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(_cli())
