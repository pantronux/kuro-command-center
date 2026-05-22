"""Typed schemas for Market Sentinel V2."""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


MarketSourceType = Literal[
    "price",
    "news",
    "grounding",
    "watchlist",
    "prediction",
    "macro",
]
MarketDirection = Literal[
    "watchlist_signal_up",
    "watchlist_signal_down",
    "watchlist_signal_neutral",
    "insufficient_evidence",
]


def market_v2_db_path() -> Path:
    configured = os.getenv("KURO_MARKET_V2_DB_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    working_dir = os.getenv("WORKING_DIR", "").strip()
    root = Path(working_dir).expanduser() if working_dir else Path(__file__).resolve().parents[2]
    return root / "kuro_market_v2.db"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class MarketSource(BaseModel):
    source_id: str
    display_name: str
    source_type: MarketSourceType
    enabled: bool = True
    configured: bool = True
    reliability_base: float = Field(default=0.65, ge=0.0, le=1.0)
    details: Dict[str, Any] = Field(default_factory=dict)


class MarketObservation(BaseModel):
    observation_id: str = Field(default_factory=lambda: new_id("mobs"))
    symbol: str
    exchange: str = ""
    observed_at: str
    source_id: str
    source_url: Optional[str] = None
    value_json: Dict[str, Any] = Field(default_factory=dict)
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0)
    freshness_seconds: Optional[float] = None
    retrieval_latency_ms: float = 0.0
    observation_type: MarketSourceType = "grounding"

    @field_validator("symbol", "exchange", "source_id")
    @classmethod
    def _clean_short(cls, value: str) -> str:
        return str(value or "").strip()[:128]


class PriceObservation(MarketObservation):
    observation_type: MarketSourceType = "price"
    price: Optional[float] = None
    currency: str = ""
    pct_change: Optional[float] = None
    volume: Optional[float] = None


class NewsObservation(MarketObservation):
    observation_type: MarketSourceType = "news"
    title: str = ""
    url: str = ""
    snippet: str = ""
    published_at: Optional[str] = None
    sentiment_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    catalyst_keywords: List[str] = Field(default_factory=list)


class GroundingObservation(MarketObservation):
    observation_type: MarketSourceType = "grounding"
    claim: str = ""
    grounding_type: str = "generic"


class SourceReliabilityScore(BaseModel):
    source_id: str
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    stale: bool = False


class MarketSignal(BaseModel):
    symbol: str
    direction: MarketDirection
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    source_agreement_score: float = Field(default=0.0, ge=0.0, le=1.0)
    contradiction_detected: bool = False
    stale_data_detected: bool = False
    insufficient_evidence: bool = False
    reasons: List[str] = Field(default_factory=list)
    catalyst_keywords: List[str] = Field(default_factory=list)


class MarketAlert(BaseModel):
    alert_id: str = Field(default_factory=lambda: new_id("malt"))
    username: str
    workspace_id: str = "default"
    symbol: str
    fingerprint: str
    severity: Literal["info", "warning", "critical"] = "info"
    channel: Literal["dashboard", "telegram", "both"] = "dashboard"
    title: str
    message: str
    status: Literal["active", "suppressed", "sent", "failed", "expired"] = "active"
    created_at: str
    expires_at: str
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class MarketSentinelReport(BaseModel):
    report_id: str = Field(default_factory=lambda: new_id("mrpt"))
    username: str
    workspace_id: str = "default"
    symbol: str
    generated_at: str
    summary: str
    evidence_table: List[Dict[str, Any]] = Field(default_factory=list)
    source_list: List[Dict[str, Any]] = Field(default_factory=list)
    freshness_warnings: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    signal: MarketSignal
    observations: List[MarketObservation] = Field(default_factory=list)
    reliability_scores: List[SourceReliabilityScore] = Field(default_factory=list)
    insufficient_evidence: bool = False
    disclaimer: str = "Not financial advice. This is a watchlist signal with uncertainty."
    report_markdown: str = ""
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class WatchlistRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    label: str = ""


class MarketAnalyzeRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    workspace_id: str = "default"
    include_news: bool = True
    publish_alert: bool = False
    alert_channel: Literal["dashboard", "telegram", "both"] = "dashboard"

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, value: str) -> str:
        return str(value or "").strip().upper().replace(".JK", "")[:32]
