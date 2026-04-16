"""Tests for Gemini share URL extraction and harvest_gemini_share routing."""
from __future__ import annotations

from kuro_backend.tools import base_tools as bt


def test_extract_gemini_share_url_basic():
    u = "https://gemini.google.com/share/AbC-12_x"
    assert bt.extract_gemini_share_url(f"Lihat {u} ya") == u


def test_extract_gemini_share_url_strips_trailing_punct():
    text = "Link: https://gemini.google.com/share/xyz123."
    assert bt.extract_gemini_share_url(text) == "https://gemini.google.com/share/xyz123"


def test_task_suggests_gemini_harvest():
    assert bt.task_suggests_gemini_harvest("pelajari dan masukkan ke library riset")
    assert not bt.task_suggests_gemini_harvest("buka link ini saja tanpa konteks")


def test_resolve_routing_to_harvest():
    task = (
        "Kuro, pelajari materi dari link Gemini share ini dan masukkan ke library riset gue. "
        "https://gemini.google.com/share/abc123"
    )
    skill, params = bt.resolve_harvest_gemini_routing(task, "general_execution", None)
    assert skill == bt.GEMINI_HARVEST_SKILL_NAME
    assert params.get("share_url") == "https://gemini.google.com/share/abc123"


def test_resolve_routing_keeps_general_without_intent():
    task = "https://gemini.google.com/share/onlylink"
    skill, params = bt.resolve_harvest_gemini_routing(task, "general_execution", None)
    assert skill == "general_execution"


def test_resolve_routing_explicit_harvest_sets_share_url():
    task = "Simpan ini https://gemini.google.com/share/zz99"
    skill, params = bt.resolve_harvest_gemini_routing(
        task, "harvest_gemini_share", {}
    )
    assert skill == "harvest_gemini_share"
    assert params.get("share_url") == "https://gemini.google.com/share/zz99"


def test_openclaw_body_implies_blocked():
    assert bt._openclaw_body_implies_blocked_or_timeout(
        {"error_code": "blocked_or_timeout"}, None
    )
    assert bt._openclaw_body_implies_blocked_or_timeout(
        {"detail": "navigation timeout"}, None
    )
