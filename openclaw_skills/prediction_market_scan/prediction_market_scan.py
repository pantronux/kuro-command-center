#!/usr/bin/env python3
"""OpenClaw skill: prediction_market_scan.

Inspired by the LLMbase "prediction market sentinel" pattern: structured
probability rows for dashboard chips and Chancellor context.

Success::
  {
    "ok": true,
    "status": "ok",
    "skill_name": "prediction_market_scan",
    "scanned_at": "2026-04-22T12:00:00Z",
    "markets": [
      {
        "topic_id": "ai_act_reg",
        "title": "EU AI Act enforcement stringency",
        "probability": 0.68,
        "unit": "fraction",
        "as_of": "2026-04-22T12:00:00Z",
        "source_url": "https://www.metaculus.com/questions/12345/"
      }
    ]
  }

--- Header Doc ---
Purpose: OpenClaw readonly skill to fetch prediction-market odds (Metaculus) or emit seeded demo rows.
Caller: OpenClaw daemon invoked by Kuro via execution.openclaw_bridge (tools + dreaming_worker).
Dependencies: requests (Metaculus API), stdlib json/argparse; METACULUS_API_TOKEN env; KURO_PREDICTION_MARKET_DEMO toggle.
Main Functions: main(topics) CLI entry, _metaculus_fetch, _demo_markets, _synthesize_trend.
Side Effects: Outbound HTTPS to Metaculus (unless demo); prints JSON to stdout.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

SKILL_NAME = "prediction_market_scan"


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


def _demo_markets(topics: List[str]) -> List[Dict[str, Any]]:
    """Explicit demo seeds — must not be mistaken for live order-book data."""
    seed = [
        ("ai_act_reg", "AI regulation — strict enforcement by 2027", 0.68),
        ("nvda_earnings_bull", "NVDA next earnings — bullish surprise", 0.55),
        ("global_growth", "Global GDP growth above 2.5% (consensus)", 0.42),
    ]
    out: List[Dict[str, Any]] = []
    tjoin = " ".join(topics).lower() if topics else ""
    for tid, title, p in seed:
        if tjoin and not any(tok in title.lower() for tok in tjoin.split() if len(tok) > 3):
            continue
        out.append(
            {
                "topic_id": tid,
                "title": title,
                "probability": p,
                "unit": "fraction",
                "as_of": _now_iso(),
                "source_url": f"demo://prediction/{tid}",
            }
        )
    if not out:
        out = [
            {
                "topic_id": tid,
                "title": title,
                "probability": p,
                "unit": "fraction",
                "as_of": _now_iso(),
                "source_url": f"demo://prediction/{tid}",
            }
            for tid, title, p in seed
        ]
    return out


def _metaculus_fetch(topics: List[str], token: str) -> List[Dict[str, Any]]:
    if not requests:
        return []
    q = " ".join(topics) if topics else "technology artificial intelligence"
    url = "https://www.metaculus.com/api2/questions/"
    try:
        resp = requests.get(
            url,
            params={"search": q[:200], "limit": 6, "order_by": "-activity"},
            headers={
                "Authorization": f"Token {token}",
                "User-Agent": "Kuro-prediction-market-scan/1.0",
            },
            timeout=25,
        )
    except Exception:
        return []
    if resp.status_code != 200:
        return []
    try:
        data = resp.json()
    except Exception:
        return []
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in results[:6]:
        if not isinstance(item, dict):
            continue
        qid = item.get("id")
        title = (item.get("title") or "").strip()[:240]
        prob = item.get("community_prediction")
        p_float: Optional[float] = None
        if isinstance(prob, (int, float)):
            p_float = float(prob)
        elif isinstance(prob, dict):
            full = prob.get("full")
            if isinstance(full, (int, float)):
                p_float = float(full)
        if p_float is None:
            continue
        url_q = f"https://www.metaculus.com/questions/{qid}/"
        out.append(
            {
                "topic_id": f"metaculus_{qid}",
                "title": title or f"Question {qid}",
                "probability": round(p_float, 4),
                "unit": "fraction",
                "as_of": _now_iso(),
                "source_url": url_q,
            }
        )
    return out


def run(params: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(params, dict):
        return _failure("invalid_params", "payload must be a JSON object")
    topics_raw = params.get("topics")
    topics: List[str] = []
    if isinstance(topics_raw, list):
        topics = [str(t).strip() for t in topics_raw if str(t).strip()]
    elif isinstance(topics_raw, str) and topics_raw.strip():
        topics = [topics_raw.strip()]

    token = (os.getenv("METACULUS_API_TOKEN") or "").strip()
    markets: List[Dict[str, Any]] = []

    if token:
        markets = _metaculus_fetch(topics, token)
    elif os.getenv("KURO_PREDICTION_MARKET_DEMO", "").strip().lower() in ("1", "true", "yes", "on"):
        markets = _demo_markets(topics)

    meta: Dict[str, Any] = {}
    if not markets and not token:
        meta["note"] = (
            "No METACULUS_API_TOKEN and demo mode off; returning empty markets. "
            "Set METACULUS_API_TOKEN or KURO_PREDICTION_MARKET_DEMO=1 for sample rows."
        )

    return {
        "ok": True,
        "status": "ok",
        "skill_name": SKILL_NAME,
        "scanned_at": _now_iso(),
        "markets": markets,
        **({"meta": meta} if meta else {}),
    }


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
