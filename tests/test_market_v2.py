"""Market Sentinel V2 tests."""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("WORKING_DIR", str(PROJECT_ROOT))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "mem0" not in sys.modules:
    fake_mem0 = types.ModuleType("mem0")

    class _FakeMemory:
        def __init__(self, *args, **kwargs):
            pass

    fake_mem0.Memory = _FakeMemory
    sys.modules["mem0"] = fake_mem0

if "phoenix" not in sys.modules:
    fake_phoenix = types.ModuleType("phoenix")

    class _FakePhoenixApp:
        url = "http://localhost:6006"

        def close(self):
            return None

    fake_phoenix.launch_app = lambda *args, **kwargs: _FakePhoenixApp()
    sys.modules["phoenix"] = fake_phoenix

from kuro_backend.config import settings
from kuro_backend.market_v2.alerts import MarketAlertStore
from kuro_backend.market_v2.cache import MarketV2Cache
from kuro_backend.market_v2.collectors import MarketCollectors
from kuro_backend.market_v2.freshness import utc_now_iso
from kuro_backend.market_v2.routes import MarketV2Service, create_market_v2_router
from kuro_backend.market_v2.schemas import MarketAnalyzeRequest
from kuro_backend.market_v2.triangulator import MarketTriangulator


def _positive_news(query: str, num_results: int):
    return [
        {
            "title": "BBCA profit growth beats expectations",
            "link": "https://example.com/bbca-profit",
            "snippet": "Strong earnings and dividend catalyst lift sentiment.",
            "date": utc_now_iso(),
        }
    ][:num_results]


def _negative_news(query: str, num_results: int):
    return [
        {
            "title": "BBCA downgraded after weak outlook",
            "link": "https://example.com/bbca-weak",
            "snippet": "Analysts cite loss risk and negative guidance.",
            "date": utc_now_iso(),
        }
    ][:num_results]


def _openclaw_ok(skill_name: str, payload=None):
    assert skill_name == "market_analysis"
    assert payload["execution_mode"] == "readonly"
    return {
        "success": True,
        "result": {
            "summary": "OpenClaw readonly market analysis completed.",
            "source": "mock",
        },
    }


def _openclaw_down(skill_name: str, payload=None):
    raise RuntimeError("openclaw unavailable")


@pytest.fixture
def isolated_market(tmp_path, monkeypatch):
    from kuro_backend import finance_db, intelligence_db

    monkeypatch.setenv("KURO_FINANCE_DB_PATH", str(tmp_path / "finance.db"))
    monkeypatch.setenv("KURO_MARKET_V2_DB_PATH", str(tmp_path / "market_v2.db"))
    monkeypatch.setattr(intelligence_db, "DB_PATH", str(tmp_path / "intelligence.db"), raising=False)
    intelligence_db._reset_schema_ready_for_tests()
    finance_db._reset_schema_ready_for_tests()
    finance_db.init_db()
    for flag in ("KURO_MARKET_SENTINEL_V2_ENABLED", "KURO_MEMORY_V3_ENABLED"):
        monkeypatch.setattr(settings, flag, False, raising=False)
    return tmp_path


def _seed_price(username: str = "Pantronux", symbol: str = "BBCA"):
    from kuro_backend import finance_db

    finance_db.upsert_watched_symbol(symbol, "Bank Central Asia", username)
    finance_db.apply_watched_price(symbol, 100.0, username)
    finance_db.apply_watched_price(symbol, 105.0, username)


def _service(tmp_path, *, news_callable=_positive_news, openclaw_callable=_openclaw_ok):
    db_path = tmp_path / "market_v2.db"
    collectors = MarketCollectors(
        news_callable=news_callable,
        openclaw_callable=openclaw_callable,
    )
    cache = MarketV2Cache(db_path)
    return MarketV2Service(
        collectors=collectors,
        triangulator=MarketTriangulator(stale_threshold_seconds=3600),
        cache=cache,
        alerts=MarketAlertStore(db_path),
    )


def test_market_v2_disabled_by_default(isolated_market):
    def auth_dep():
        return {"username": "Pantronux"}

    app = FastAPI()
    app.include_router(
        create_market_v2_router(
            auth_dependency=auth_dep,
            admin_dependency=auth_dep,
            service=_service(isolated_market),
        )
    )

    response = TestClient(app).get("/api/market-v2/watchlist")

    assert response.status_code == 404
    assert "disabled" in response.text.lower()


def test_mocked_source_collection_produces_grounded_report(isolated_market, monkeypatch):
    monkeypatch.setattr(settings, "KURO_MARKET_SENTINEL_V2_ENABLED", True, raising=False)
    _seed_price()
    service = _service(isolated_market)

    result = service.analyze(
        username="Pantronux",
        request=MarketAnalyzeRequest(symbol="BBCA", include_news=True),
    )
    report = result["report"]

    assert report["symbol"] == "BBCA"
    assert report["evidence_table"]
    assert {row["source_id"] for row in report["evidence_table"]} >= {
        "price_finance_db",
        "serper_news",
        "openclaw_market_analysis",
    }
    assert report["disclaimer"].startswith("Not financial advice")
    assert "buy" not in report["signal"]["direction"].lower()


def test_openclaw_failure_falls_back_to_other_sources(isolated_market, monkeypatch):
    monkeypatch.setattr(settings, "KURO_MARKET_SENTINEL_V2_ENABLED", True, raising=False)
    _seed_price()
    service = _service(isolated_market, openclaw_callable=_openclaw_down)

    report = service.analyze(
        username="Pantronux",
        request=MarketAnalyzeRequest(symbol="BBCA", include_news=True),
    )["report"]

    assert report["confidence"] > 0
    assert any(row["source_id"] == "openclaw_market_analysis" for row in report["evidence_table"])
    assert report["summary"]


def test_stale_source_downgrades_confidence(isolated_market):
    from kuro_backend.market_v2.schemas import PriceObservation

    fresh = PriceObservation(
        symbol="BBCA",
        observed_at=utc_now_iso(),
        source_id="price_finance_db",
        confidence_score=0.8,
        freshness_seconds=10,
        pct_change=2.0,
    )
    stale = fresh.model_copy(update={"freshness_seconds": 999999, "confidence_score": 0.8})
    triangulator = MarketTriangulator(stale_threshold_seconds=3600)

    fresh_score = triangulator.score_reliability([fresh])[0]
    stale_score = triangulator.score_reliability([stale])[0]

    assert stale_score.stale is True
    assert stale_score.score < fresh_score.score


def test_contradictory_signals_produce_low_confidence(isolated_market, monkeypatch):
    monkeypatch.setattr(settings, "KURO_MARKET_SENTINEL_V2_ENABLED", True, raising=False)
    _seed_price()
    service = _service(isolated_market, news_callable=_negative_news)

    report = service.analyze(
        username="Pantronux",
        request=MarketAnalyzeRequest(symbol="BBCA", include_news=True),
    )["report"]

    assert report["signal"]["contradiction_detected"] is True
    assert report["confidence"] <= 0.45


def test_no_trade_execution_api_exists(isolated_market, monkeypatch):
    monkeypatch.setattr(settings, "KURO_MARKET_SENTINEL_V2_ENABLED", True, raising=False)

    def auth_dep():
        return {"username": "Pantronux"}

    app = FastAPI()
    app.include_router(
        create_market_v2_router(
            auth_dependency=auth_dep,
            admin_dependency=auth_dep,
            service=_service(isolated_market),
        )
    )
    client = TestClient(app)

    assert client.post("/api/market-v2/trade", json={"symbol": "BBCA"}).status_code == 404
    assert client.post("/api/market-v2/orders", json={"symbol": "BBCA"}).status_code == 404


def test_alert_dedup_works(isolated_market, monkeypatch):
    monkeypatch.setattr(settings, "KURO_MARKET_SENTINEL_V2_ENABLED", True, raising=False)
    _seed_price()
    service = _service(isolated_market)
    report = service.analyze(
        username="Pantronux",
        request=MarketAnalyzeRequest(symbol="BBCA", include_news=True),
    )["report"]
    report_model = service.cache.latest_report(username="Pantronux", symbol="BBCA")
    assert report_model is not None

    first = service.alerts.create_or_suppress(report=report_model)
    second = service.alerts.create_or_suppress(report=report_model)

    assert first.status == "active"
    assert second.status == "suppressed"


def test_telegram_dlq_works_with_market_alert(isolated_market, monkeypatch):
    from kuro_backend import intelligence_db

    monkeypatch.setattr(settings, "KURO_MARKET_SENTINEL_V2_ENABLED", True, raising=False)
    _seed_price()
    service = _service(isolated_market)
    service.analyze(
        username="Pantronux",
        request=MarketAnalyzeRequest(symbol="BBCA", include_news=True),
    )
    report = service.cache.latest_report(username="Pantronux", symbol="BBCA")
    alert = service.alerts.create_or_suppress(report=report, channel="telegram")

    failed = service.alerts.publish(alert, telegram_sender=lambda text, chat_id=None: False)

    assert failed.status == "failed"
    pending = intelligence_db.get_pending_failed_notifications(max_attempts=5)
    assert len(pending) == 1
    assert "market_v2" in pending[0]["payload_json"]


def test_no_cross_user_watchlist_access(isolated_market, monkeypatch):
    monkeypatch.setattr(settings, "KURO_MARKET_SENTINEL_V2_ENABLED", True, raising=False)
    service = _service(isolated_market)

    service.add_watchlist(username="Pantronux", symbol="BBCA", label="Admin symbol")

    assert service.list_watchlist(username="Pantronux")
    assert service.list_watchlist(username="Faikhira") == []
    assert service.delete_watchlist(username="Faikhira", symbol="BBCA") is False


def test_market_signal_memory_ttl_when_memory_v3_enabled(isolated_market, tmp_path, monkeypatch):
    from kuro_backend.memory_v3.store import MemoryV3Store

    memory_db = tmp_path / "memory_v3.db"
    monkeypatch.setenv("KURO_MEMORY_V3_DB_PATH", str(memory_db))
    monkeypatch.setattr(settings, "KURO_MARKET_SENTINEL_V2_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KURO_MEMORY_V3_ENABLED", True, raising=False)
    _seed_price()

    service = _service(isolated_market)
    result = service.analyze(
        username="Pantronux",
        request=MarketAnalyzeRequest(symbol="BBCA", include_news=True),
    )

    memory_id = result["memory_id"]
    item = MemoryV3Store(memory_db).get_memory_item(memory_id)

    assert item is not None
    assert item.memory_type == "market_signal_memory"
    assert item.expires_at is not None
