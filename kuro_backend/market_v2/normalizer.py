"""Normalize raw market data into V2 observations."""
from __future__ import annotations

import time
from typing import Any, Dict, List

from kuro_backend.market_v2.freshness import freshness_seconds, utc_now_iso
from kuro_backend.market_v2.schemas import GroundingObservation, NewsObservation, PriceObservation


POSITIVE_WORDS = {
    "beat",
    "growth",
    "profit",
    "surge",
    "upgrade",
    "bullish",
    "gain",
    "strong",
    "positive",
    "rekor",
    "naik",
}
NEGATIVE_WORDS = {
    "miss",
    "loss",
    "drop",
    "downgrade",
    "bearish",
    "fall",
    "weak",
    "negative",
    "turun",
    "rugi",
}
CATALYST_WORDS = {
    "earnings",
    "dividend",
    "merger",
    "acquisition",
    "regulation",
    "rate",
    "inflation",
    "buyback",
    "guidance",
    "profit",
    "loss",
}


def normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper().replace(".JK", "")[:32]


def news_sentiment(text: str) -> float:
    lowered = (text or "").lower()
    pos = sum(1 for word in POSITIVE_WORDS if word in lowered)
    neg = sum(1 for word in NEGATIVE_WORDS if word in lowered)
    if pos == neg:
        return 0.0
    return max(-1.0, min(1.0, (pos - neg) / max(1, pos + neg)))


def catalyst_keywords(text: str) -> List[str]:
    lowered = (text or "").lower()
    return sorted(word for word in CATALYST_WORDS if word in lowered)


def price_from_finance_detail(symbol: str, row: Dict[str, Any], *, latency_ms: float = 0.0) -> PriceObservation:
    observed_at = str(row.get("price_updated_at") or row.get("last_refreshed") or utc_now_iso())
    price = row.get("current_price_per_share", row.get("last_price"))
    pct_change = row.get("last_pct_change", row.get("ytd_performance"))
    volume = row.get("volume_24h")
    return PriceObservation(
        symbol=normalize_symbol(symbol),
        exchange="IDX" if row.get("stock_code") else "",
        observed_at=observed_at,
        source_id="price_finance_db",
        value_json=dict(row),
        confidence_score=0.78,
        freshness_seconds=freshness_seconds(observed_at),
        retrieval_latency_ms=latency_ms,
        price=float(price) if price is not None else None,
        currency="IDR" if row.get("stock_code") else "",
        pct_change=float(pct_change) if pct_change is not None else None,
        volume=float(volume) if volume is not None else None,
    )


def watchlist_observation(symbol: str, row: Dict[str, Any], *, latency_ms: float = 0.0) -> GroundingObservation:
    observed_at = str(row.get("updated_at") or row.get("created_at") or utc_now_iso())
    return GroundingObservation(
        symbol=normalize_symbol(symbol),
        observed_at=observed_at,
        source_id="manual_watchlist",
        value_json=dict(row),
        confidence_score=0.55,
        freshness_seconds=freshness_seconds(observed_at),
        retrieval_latency_ms=latency_ms,
        claim=f"{normalize_symbol(symbol)} is present in the user's local watchlist.",
        grounding_type="watchlist",
    )


def prediction_observation(symbol: str, row: Dict[str, Any], *, latency_ms: float = 0.0) -> GroundingObservation:
    observed_at = str(row.get("updated_at") or utc_now_iso())
    return GroundingObservation(
        symbol=normalize_symbol(symbol),
        observed_at=observed_at,
        source_id="prediction_watch",
        value_json=dict(row),
        confidence_score=0.58,
        freshness_seconds=freshness_seconds(observed_at),
        retrieval_latency_ms=latency_ms,
        claim=str(row.get("label") or row.get("slug") or ""),
        grounding_type="prediction",
    )


def normalize_news_items(symbol: str, items: Any, *, latency_ms: float = 0.0) -> List[NewsObservation]:
    if not isinstance(items, list):
        return []
    now = utc_now_iso()
    observations: List[NewsObservation] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("link") or item.get("url") or "").strip()
        snippet = str(item.get("snippet") or item.get("summary") or "").strip()
        if not title and not url:
            continue
        key = url or title
        if key in seen:
            continue
        seen.add(key)
        text = f"{title} {snippet}"
        observations.append(
            NewsObservation(
                symbol=normalize_symbol(symbol),
                observed_at=str(item.get("date") or item.get("published_at") or now),
                source_id="serper_news",
                source_url=url or None,
                value_json=dict(item),
                confidence_score=0.66 if url else 0.48,
                freshness_seconds=freshness_seconds(item.get("date") or now),
                retrieval_latency_ms=latency_ms,
                title=title,
                url=url,
                snippet=snippet,
                published_at=str(item.get("date") or item.get("published_at") or "") or None,
                sentiment_score=news_sentiment(text),
                catalyst_keywords=catalyst_keywords(text),
            )
        )
    return observations


def openclaw_observation(symbol: str, result: Dict[str, Any], *, latency_ms: float = 0.0) -> GroundingObservation:
    success = bool(result.get("success"))
    payload = result.get("result") if isinstance(result.get("result"), dict) else result
    return GroundingObservation(
        symbol=normalize_symbol(symbol),
        observed_at=utc_now_iso(),
        source_id="openclaw_market_analysis",
        value_json=payload if isinstance(payload, dict) else {"raw": payload},
        confidence_score=0.7 if success else 0.18,
        freshness_seconds=0.0,
        retrieval_latency_ms=latency_ms,
        claim=str((payload or {}).get("analysis") or (payload or {}).get("summary") or result.get("error") or ""),
        grounding_type="openclaw_market_analysis",
    )


def timed(callable_obj, *args, **kwargs):
    start = time.monotonic()
    result = callable_obj(*args, **kwargs)
    return result, round((time.monotonic() - start) * 1000.0, 3)
