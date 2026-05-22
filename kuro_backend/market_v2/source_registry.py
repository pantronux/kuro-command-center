"""Source registry for Market Sentinel V2."""
from __future__ import annotations

import importlib.util
import os
from typing import Dict, List

from kuro_backend.market_v2.schemas import MarketSource


def build_market_source_registry() -> Dict[str, MarketSource]:
    yfinance_present = importlib.util.find_spec("yfinance") is not None
    stooq_present = importlib.util.find_spec("pandas_datareader") is not None
    openclaw_enabled = os.getenv("OPENCLAW_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    serper_configured = bool(os.getenv("SERPER_API_KEY", "").strip())
    gemini_configured = bool(os.getenv("GEMINI_API_KEY", "").strip())
    sources = [
        MarketSource(
            source_id="price_finance_db",
            display_name="Finance DB price snapshot",
            source_type="price",
            enabled=True,
            configured=True,
            reliability_base=0.78,
        ),
        MarketSource(
            source_id="price_yfinance",
            display_name="yfinance price collector",
            source_type="price",
            enabled=yfinance_present,
            configured=yfinance_present,
            reliability_base=0.7,
        ),
        MarketSource(
            source_id="price_stooq",
            display_name="Stooq price collector",
            source_type="price",
            enabled=stooq_present,
            configured=stooq_present,
            reliability_base=0.68,
        ),
        MarketSource(
            source_id="openclaw_market_analysis",
            display_name="OpenClaw market_analysis",
            source_type="grounding",
            enabled=True,
            configured=openclaw_enabled,
            reliability_base=0.72,
        ),
        MarketSource(
            source_id="serper_news",
            display_name="Serper News",
            source_type="news",
            enabled=True,
            configured=serper_configured,
            reliability_base=0.66,
        ),
        MarketSource(
            source_id="gemini_google_grounding",
            display_name="Gemini Google Grounding",
            source_type="macro",
            enabled=True,
            configured=gemini_configured,
            reliability_base=0.64,
        ),
        MarketSource(
            source_id="manual_watchlist",
            display_name="Manual watchlist",
            source_type="watchlist",
            enabled=True,
            configured=True,
            reliability_base=0.55,
        ),
        MarketSource(
            source_id="prediction_watch",
            display_name="Prediction watch cache",
            source_type="prediction",
            enabled=True,
            configured=True,
            reliability_base=0.58,
        ),
    ]
    return {source.source_id: source for source in sources}


def list_sources() -> List[MarketSource]:
    return list(build_market_source_registry().values())
