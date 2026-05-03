"""Pydantic v2 schemas for finance and market records.

--- Header Doc ---
Purpose: Wire-level data contracts for API routes, services, and Gemini tool outputs.
Caller: main.py FastAPI routes, services/core_service, finance_db helpers, tools/base_tools, tests.
Dependencies: pydantic v2.
Main Functions: BudgetRecord, FinancialGoalRecord, RecurringExpenseRecord, WatchedSymbolRecord, PredictionWatchRecord, MarketHudChip.
Side Effects: None (pure dataclass-like validation).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, field_validator


class MonthlyBudgetRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    month: str
    amount_usd: float
    notes: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class FinancialGoalRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    goal_id: str
    name: str
    target_amount: float
    current_amount: float = 0.0
    deadline: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class RecurringExpenseRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    label: str
    amount_usd: float
    cadence: str = "monthly"
    next_due: str = ""
    category: str = ""
    active: int = 1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ApiUsageDailyRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: str
    model_name: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    updated_at: Optional[str] = None


class WatchedSymbolRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    symbol: str
    label: str = ""
    baseline_price: Optional[float] = None
    baseline_at: Optional[str] = None
    last_price: Optional[float] = None
    last_pct_change: Optional[float] = None
    last_refreshed: Optional[str] = None
    active: int = 1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PredictionWatchRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slug: str
    label: str
    last_probability: float = 0.0
    trend: str = "flat"
    updated_at: Optional[str] = None


class MarketHudChip(BaseModel):
    """One row for dashboard HUD / probability ticker."""

    id: str
    label: str
    prob: Optional[float] = None
    trend: str = "flat"
    sentiment: Optional[str] = None
    kind: str = "prediction"
    last_pct_change: Optional[float] = None


class ChatSessionRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chat_id: str
    username: str
    persona: str
    title: str = "New Chat"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
