#!/usr/bin/env python3
"""
OpenClaw skill: harvest_gemini_share

Scrape public Gemini share pages and save conversation text as Markdown.
Intended to be invoked by the OpenClaw daemon (not imported by Kuro directly).

Contract (JSON body returned to Kuro bridge):
  Success: ok=true, skill_name, saved_path, data_mutation=true
  Failure: ok=false, error_code, user_message (optional)

Env:
  HARVEST_GEMINI_TIMEOUT_MS  Navigation timeout (default 60000)
  HARVEST_GEMINI_HEADLESS  "0" to show browser (default "1")

--- Header Doc ---
Purpose: OpenClaw skill — scrape public Gemini share URLs and persist as Markdown.
Caller: OpenClaw daemon invoked by Kuro memory ingestion workflow.
Dependencies: playwright/chromium, stdlib pathlib/json/argparse.
Main Functions: main(url) CLI entry, _render_page, _save_markdown.
Side Effects: Launches headless Chromium, writes harvested .md under media/harvest/, prints JSON.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Message must match Kuro advanced_execution_tool mapping expectations
USER_MESSAGE_BLOCKED = (
    "Master, akses ke link Gemini ini tersumbat (Timeout/Bot Protection). "
    "Mohon cek kembali atau berikan file PDF-nya saja."
)

GEMINI_SHARE_RE = re.compile(
    r"^https://gemini\.google\.com/share/[a-zA-Z0-9_-]+/?.*$", re.IGNORECASE
)

DEFAULT_OUTPUT_DIR = "/home/kuro/research_library/scraped_sources"

SELECTORS_PRIMARY = ".message-content"
SELECTORS_FALLBACK = [
    "[data-message-author-role]",
    "div[class*='message']",
    "main article",
]


def _failure(error_code: str, detail: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": False,
        "skill_name": "harvest_gemini_share",
        "error_code": error_code,
        "user_message": USER_MESSAGE_BLOCKED,
    }
    if detail:
        out["detail"] = detail[:500]
    return out


def _success(saved_path: str, char_count: int) -> Dict[str, Any]:
    return {
        "ok": True,
        "skill_name": "harvest_gemini_share",
        "saved_path": saved_path,
        "data_mutation": True,
        "chars_written": char_count,
    }


def _validate_url(url: Optional[str]) -> Tuple[bool, str]:
    if not url or not isinstance(url, str):
        return False, "missing_share_url"
    u = url.strip()
    if not GEMINI_SHARE_RE.match(u.split("?")[0].rstrip("/")):
        return False, "invalid_share_url"
    return True, u


def _clean_lines(lines: List[str]) -> str:
    seen: set = set()
    out: List[str] = []
    for raw in lines:
        s = " ".join((raw or "").split())
        if not s or len(s) < 2:
            continue
        if s.startswith("http://") or s.startswith("https://"):
            if len(s) < 80:
                continue
        key = s[:200]
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return "\n\n".join(out)


def _extract_text_from_page(page) -> str:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    lines: List[str] = []
    try:
        page.wait_for_selector(SELECTORS_PRIMARY, timeout=45_000)
        for el in page.locator(SELECTORS_PRIMARY).all():
            t = el.inner_text(timeout=5_000)
            if t and t.strip():
                lines.extend(t.splitlines())
    except PlaywrightTimeout:
        for sel in SELECTORS_FALLBACK:
            try:
                page.wait_for_selector(sel, timeout=8_000)
                for el in page.locator(sel).all():
                    t = el.inner_text(timeout=3_000)
                    if t and t.strip():
                        lines.extend(t.splitlines())
                if lines:
                    break
            except Exception:
                continue
    return _clean_lines(lines)


def run(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    params = params or {}
    share_url = params.get("share_url") or params.get("url")
    ok, url = _validate_url(share_url if isinstance(share_url, str) else None)
    if not ok:
        return _failure("invalid_url", url if url else "missing_share_url")

    output_dir = str(params.get("output_dir") or os.environ.get("HARVEST_GEMINI_OUTPUT_DIR") or DEFAULT_OUTPUT_DIR)
    out_path = Path(output_dir).expanduser().resolve()
    try:
        out_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return _failure("io_error", str(e))

    timeout_ms = int(os.environ.get("HARVEST_GEMINI_TIMEOUT_MS", "60000"))
    headless = os.environ.get("HARVEST_GEMINI_HEADLESS", "1").strip() != "0"

    try:
        from playwright.sync_api import sync_playwright
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
    except ImportError:
        return _failure(
            "missing_playwright",
            "Install: pip install playwright && playwright install chromium",
        )

    text_body = ""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            try:
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                    locale="en-US",
                )
                page = context.new_page()
                page.set_default_timeout(timeout_ms)
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                text_body = _extract_text_from_page(page)
                context.close()
            finally:
                browser.close()
    except PlaywrightTimeout:
        return _failure("blocked_or_timeout", "navigation_or_selector_timeout")
    except Exception as e:
        err_s = str(e).lower()
        if "timeout" in err_s or "navigation" in err_s:
            return _failure("blocked_or_timeout", str(e))
        return _failure("blocked_or_timeout", str(e))

    if not text_body or len(text_body.strip()) < 20:
        return _failure("blocked_or_timeout", "no_message_content_extracted")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"gemini-share_{ts}.md"
    file_path = out_path / filename

    md = (
        f"# Gemini share harvest\n\n"
        f"- **Source:** {url}\n"
        f"- **Harvested (UTC):** {datetime.now(timezone.utc).isoformat()}\n\n"
        f"---\n\n{text_body}\n"
    )
    try:
        file_path.write_text(md, encoding="utf-8")
    except OSError as e:
        return _failure("io_error", str(e))

    return _success(str(file_path), len(md))


def main(argv: Optional[List[str]] = None) -> int:
    """CLI: python harvest_gemini_share.py <share_url>"""
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("Usage: harvest_gemini_share.py <https://gemini.google.com/share/...>", file=sys.stderr)
        return 2
    result = run({"share_url": argv[0]})
    import json

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
