"""Critical path bugfix and performance sweep tests."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("WORKING_DIR", str(PROJECT_ROOT))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_price_ticker_degrades_when_yfinance_missing(monkeypatch):
    from kuro_backend import price_ticker_worker

    monkeypatch.setattr(price_ticker_worker, "yf", None)

    result = price_ticker_worker.run_price_update(watchlist=["BBCA.JK"])

    assert result == {"error": "yfinance dependency unavailable"}


def test_price_ticker_timeout_and_deduplicated_watchlist(monkeypatch):
    from kuro_backend import price_ticker_worker

    calls = {}
    touched = []
    upserts = []

    def fake_downloader(symbols, timeout_s):
        calls["symbols"] = tuple(symbols)
        calls["timeout_s"] = timeout_s
        now = pd.Timestamp.now(tz="Asia/Jakarta")
        return {
            symbol: pd.DataFrame(
                {"Close": [100.0], "Volume": [12345]},
                index=[now],
            )
            for symbol in set(symbols)
        }

    def fake_upsert(**kwargs):
        upserts.append(kwargs)
        return True

    monkeypatch.setenv("KURO_PRICE_TICKER_TIMEOUT_S", "7")
    monkeypatch.setattr(price_ticker_worker, "upsert_sentinel_stock_price", fake_upsert)
    monkeypatch.setattr(price_ticker_worker, "touch_market_snapshot_fetched_at", lambda username: touched.append(username))

    result = price_ticker_worker.run_price_update(
        username="Pantronux",
        watchlist=["BBCA.JK", "BBCA.JK", "ADRO.JK"],
        downloader=fake_downloader,
    )

    assert result == {"updated": 2, "failed": 0}
    assert calls["symbols"] == ("BBCA.JK", "ADRO.JK")
    assert calls["timeout_s"] == 7.0
    assert [row["stock_code"] for row in upserts] == ["BBCA", "ADRO"]
    assert touched == ["Pantronux"]


def test_runtime_loader_replaces_stub_entrypoint():
    import kuro_backend.runtime as runtime
    from kuro_backend.runtime import runtime_loader

    assert not hasattr(runtime, "KURO_STUB")
    assert not hasattr(runtime, "stub_entrypoint")
    configs = runtime_loader.load_runtime_configs()
    assert "sovereign" in configs
    assert runtime_loader.get_runtime_config("unknown-runtime").runtime_id == "sovereign"


def test_output_normalizer_replaces_stub_entrypoint():
    from kuro_backend.output.output_normalizer import normalize_json_object, normalize_output

    assert json.loads(normalize_output({"b": 2, "a": 1})) == {"a": 1, "b": 2}
    assert normalize_json_object('{"task_type":"demo"}') == {"task_type": "demo"}


def test_removed_production_stub_markers_from_fixed_files():
    files = [
        PROJECT_ROOT / "kuro_backend" / "runtime" / "__init__.py",
        PROJECT_ROOT / "kuro_backend" / "runtime" / "runtime_loader.py",
        PROJECT_ROOT / "kuro_backend" / "output" / "output_normalizer.py",
    ]

    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "NotImplementedError" not in text
        assert "STUB" not in text
