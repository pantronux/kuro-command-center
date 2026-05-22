"""FastAPI routes and service boundary for Market Sentinel V2."""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from kuro_backend.config import settings
from kuro_backend.market_v2.alerts import MarketAlertStore
from kuro_backend.market_v2.cache import MarketV2Cache
from kuro_backend.market_v2.collectors import MarketCollectors
from kuro_backend.market_v2.normalizer import normalize_symbol
from kuro_backend.market_v2.schemas import MarketAnalyzeRequest, WatchlistRequest
from kuro_backend.market_v2.source_registry import list_sources
from kuro_backend.market_v2.telemetry import record_market_v2_event, write_market_signal_memory
from kuro_backend.market_v2.triangulator import MarketTriangulator


def is_market_v2_enabled() -> bool:
    return bool(getattr(settings, "KURO_MARKET_SENTINEL_V2_ENABLED", False))


def _success(data: Any = None, **extra: Any) -> Dict[str, Any]:
    payload = {"status": "success", "data": data, "error": None}
    payload.update(extra)
    return payload


class MarketV2Service:
    def __init__(
        self,
        *,
        collectors: Optional[MarketCollectors] = None,
        triangulator: Optional[MarketTriangulator] = None,
        cache: Optional[MarketV2Cache] = None,
        alerts: Optional[MarketAlertStore] = None,
    ) -> None:
        self.collectors = collectors or MarketCollectors()
        self.triangulator = triangulator or MarketTriangulator()
        self.cache = cache or MarketV2Cache()
        self.alerts = alerts or MarketAlertStore(self.cache.db_path)

    def list_watchlist(self, *, username: str) -> list[dict]:
        from kuro_backend import finance_db

        return finance_db.list_watched_symbols(True, username)

    def add_watchlist(self, *, username: str, symbol: str, label: str = "") -> dict:
        from kuro_backend import finance_db

        normalized = normalize_symbol(symbol)
        finance_db.upsert_watched_symbol(normalized, label or "", username)
        return finance_db.get_watched_symbol(normalized, username) or {"symbol": normalized, "label": label or ""}

    def delete_watchlist(self, *, username: str, symbol: str) -> bool:
        from kuro_backend import finance_db

        return finance_db.delete_watched_symbol(normalize_symbol(symbol), username)

    def analyze(
        self,
        *,
        username: str,
        request: MarketAnalyzeRequest,
    ) -> dict:
        symbol = normalize_symbol(request.symbol)
        observations = self.collectors.collect(
            symbol=symbol,
            username=username,
            include_news=request.include_news,
        )
        report = self.triangulator.build_report(
            symbol=symbol,
            username=username,
            workspace_id=request.workspace_id,
            observations=observations,
        )
        self.cache.save_report(report)
        memory_id = write_market_signal_memory(report)
        alert_payload = None
        if request.publish_alert:
            alert = self.alerts.create_or_suppress(
                report=report,
                channel=request.alert_channel,
                ttl_minutes=int(getattr(settings, "KURO_SENTINEL_DEDUP_WINDOW_MIN", 30) or 30),
            )
            if alert.channel in {"telegram", "both"}:
                alert = self.alerts.publish(alert)
            alert_payload = alert.model_dump()
        record_market_v2_event("analyze", symbol=symbol, username=username, detail=f"confidence={report.confidence}")
        return {
            "report": report.model_dump(),
            "memory_id": memory_id,
            "alert": alert_payload,
        }

    def snapshot(self, *, username: str, workspace_id: Optional[str] = None) -> dict:
        return {
            "watchlist": self.list_watchlist(username=username),
            "reports": [report.model_dump() for report in self.cache.list_reports(username=username, workspace_id=workspace_id)],
            "alerts": [alert.model_dump() for alert in self.alerts.list_alerts(username=username)],
        }

    def health(self) -> dict:
        return {
            "enabled": is_market_v2_enabled(),
            "sources": [source.model_dump() for source in list_sources()],
            "cache": self.cache.health(),
            "scheduler_enabled": is_market_v2_enabled(),
        }


def create_market_v2_router(
    *,
    auth_dependency: Callable[..., Dict[str, str]],
    admin_dependency: Callable[..., Dict[str, str]],
    service: Optional[MarketV2Service] = None,
) -> APIRouter:
    router = APIRouter()
    service_instance = service

    def _service() -> MarketV2Service:
        nonlocal service_instance
        if service_instance is None:
            service_instance = MarketV2Service()
        return service_instance

    def _require_enabled() -> None:
        if not is_market_v2_enabled():
            raise HTTPException(status_code=404, detail="Market Sentinel V2 is disabled")

    @router.get("/api/market-v2/watchlist")
    async def list_market_v2_watchlist(user: Dict[str, str] = Depends(auth_dependency)):
        _require_enabled()
        return _success(_service().list_watchlist(username=user["username"]))

    @router.post("/api/market-v2/watchlist")
    async def add_market_v2_watchlist(
        payload: WatchlistRequest,
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        _require_enabled()
        return _success(
            _service().add_watchlist(
                username=user["username"],
                symbol=payload.symbol,
                label=payload.label,
            )
        )

    @router.delete("/api/market-v2/watchlist/{symbol}")
    async def delete_market_v2_watchlist(
        symbol: str,
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        _require_enabled()
        deleted = _service().delete_watchlist(username=user["username"], symbol=symbol)
        return _success({"symbol": normalize_symbol(symbol), "deleted": bool(deleted)})

    @router.post("/api/market-v2/analyze")
    async def analyze_market_v2(
        payload: MarketAnalyzeRequest,
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        _require_enabled()
        return _success(_service().analyze(username=user["username"], request=payload))

    @router.get("/api/market-v2/snapshot")
    async def market_v2_snapshot(
        workspace_id: Optional[str] = Query(default=None),
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        _require_enabled()
        return _success(_service().snapshot(username=user["username"], workspace_id=workspace_id))

    @router.get("/api/market-v2/alerts")
    async def market_v2_alerts(user: Dict[str, str] = Depends(auth_dependency)):
        _require_enabled()
        return _success([alert.model_dump() for alert in _service().alerts.list_alerts(username=user["username"])])

    @router.get("/api/admin/market-v2/health")
    async def market_v2_health(_admin: Dict[str, str] = Depends(admin_dependency)):
        return _success(_service().health())

    return router


def run_market_v2_scheduled_scan() -> dict:
    if not is_market_v2_enabled():
        return {"status": "disabled", "checked": 0}
    from kuro_backend import auth_db

    service = MarketV2Service()
    checked = 0
    reports = 0
    all_users = auth_db.get_all_users() or [os.getenv("ADMIN_USERNAME", "Pantronux")]
    for username in all_users:
        for row in service.list_watchlist(username=username):
            symbol = normalize_symbol(row.get("symbol") or "")
            if not symbol:
                continue
            checked += 1
            try:
                service.analyze(
                    username=username,
                    request=MarketAnalyzeRequest(
                        symbol=symbol,
                        include_news=True,
                        publish_alert=True,
                        alert_channel="dashboard",
                    ),
                )
                reports += 1
            except Exception as exc:
                record_market_v2_event("scheduled_scan_error", symbol=symbol, username=username, detail=str(exc))
    return {"status": "success", "checked": checked, "reports": reports}
