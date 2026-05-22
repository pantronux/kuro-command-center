"""Market Sentinel V2 source collectors."""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional

from kuro_backend.config import settings
from kuro_backend.market_v2 import normalizer
from kuro_backend.market_v2.schemas import MarketObservation


NewsCallable = Callable[[str, int], List[Dict[str, Any]]]
OpenClawCallable = Callable[[str, Dict[str, Any]], Dict[str, Any]]


class MarketCollectors:
    def __init__(
        self,
        *,
        news_callable: Optional[NewsCallable] = None,
        openclaw_callable: Optional[OpenClawCallable] = None,
    ) -> None:
        self.news_callable = news_callable
        self.openclaw_callable = openclaw_callable

    def collect(
        self,
        *,
        symbol: str,
        username: str,
        include_news: bool = True,
    ) -> List[MarketObservation]:
        symbol = normalizer.normalize_symbol(symbol)
        observations: List[MarketObservation] = []
        observations.extend(self.collect_local(symbol=symbol, username=username))

        price_move = 0.0
        for obs in observations:
            if getattr(obs, "pct_change", None) is not None:
                price_move = max(price_move, abs(float(getattr(obs, "pct_change") or 0.0)))

        threshold = float(getattr(settings, "KURO_MARKET_MOVE_PCT", 3.0) or 3.0)
        if include_news or price_move >= threshold:
            observations.extend(self.collect_news(symbol=symbol))
        observations.extend(self.collect_openclaw(symbol=symbol))
        return observations

    def collect_local(self, *, symbol: str, username: str) -> List[MarketObservation]:
        from kuro_backend import finance_db

        observations: List[MarketObservation] = []
        detail, latency = normalizer.timed(finance_db.get_sentinel_stock_detail, symbol, username)
        if detail:
            observations.append(normalizer.price_from_finance_detail(symbol, detail, latency_ms=latency))

        watched, latency = normalizer.timed(finance_db.get_watched_symbol, symbol, username)
        if watched:
            observations.append(normalizer.watchlist_observation(symbol, watched, latency_ms=latency))
            if watched.get("last_price") is not None and not detail:
                observations.append(normalizer.price_from_finance_detail(symbol, watched, latency_ms=latency))

        predictions, latency = normalizer.timed(finance_db.list_prediction_watch, username)
        for row in predictions:
            haystack = f"{row.get('slug', '')} {row.get('label', '')}".upper()
            if symbol in haystack:
                observations.append(normalizer.prediction_observation(symbol, row, latency_ms=latency))
        return observations

    def collect_news(self, *, symbol: str, max_results: int = 5) -> List[MarketObservation]:
        callable_obj = self.news_callable
        if callable_obj is None:
            if not os.getenv("SERPER_API_KEY", "").strip():
                return []
            from kuro_backend.serper_tool import serper_news

            callable_obj = serper_news
        try:
            items, latency = normalizer.timed(callable_obj, f"{symbol} market news", max_results)
            return normalizer.normalize_news_items(symbol, items, latency_ms=latency)
        except Exception:
            return []

    def collect_openclaw(self, *, symbol: str) -> List[MarketObservation]:
        callable_obj = self.openclaw_callable
        if callable_obj is None:
            from kuro_backend.execution.service import execute_openclaw_skill_sync

            callable_obj = execute_openclaw_skill_sync
        payload = {
            "op": "market_analysis",
            "symbol": symbol,
            "execution_mode": "readonly",
        }
        try:
            result, latency = normalizer.timed(callable_obj, "market_analysis", payload)
        except Exception as exc:
            result = {"success": False, "error": str(exc)}
            latency = 0.0
        return [normalizer.openclaw_observation(symbol, result, latency_ms=latency)]
