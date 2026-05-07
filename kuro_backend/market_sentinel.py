"""
--- Header Doc ---
Purpose: Hybrid Market Sentinel (Qualitative Triangulator).
Caller: main.py (scheduler), intelligence_engine.py (fetcher).
Dependencies: google-genai, finance_db, telegram_notifier, openclaw_bridge.
Main Functions: run_triangulation_scan(), get_kuro_recommendation().
Side Effects: DB updates to market_sentinel_stocks, Telegram notifications.
"""
import logging
import json
from datetime import datetime
from typing import List, Dict, Any

from kuro_backend.config import Settings, PRIMARY_MODEL
from kuro_backend.finance_db import (
    get_all_sentinel_stocks, 
    update_sentinel_stock_analysis,
    insert_sentinel_scan
)
from kuro_backend import telegram_notifier
from kuro_backend.execution.openclaw_bridge import execute_openclaw_skill_blocking
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)
genai_client = genai.Client(api_key=Settings().GEMINI_API_KEY)

def fetch_macro_context() -> str:
    """Fetch current macro conditions using Google Grounding."""
    prompt = "Berikan update ringkas kondisi ekonomi makro Indonesia: BI Rate, Inflasi, Kurs USD/IDR, dan sentimen IHSG."
    try:
        resp = genai_client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(tools=[{"google_search": {}}], temperature=0.1)
        )
        return resp.text
    except Exception as e:
        logger.warning("[SENTINEL] Macro fetch failed: %s", e)
        return "Data makro tidak tersedia."

def fetch_prediction_sentiment() -> str:
    """Fetch predictive sentiment via OpenClaw's prediction_market_scan."""
    try:
        # We target sectors relevant to IDX like Finance, Energy, Tech
        skill_input = {"query": "Indonesian stock market sentiment and sector outlook"}
        result = execute_openclaw_skill_blocking("prediction_market_scan", skill_input)
        if result and "analysis" in result:
            return result["analysis"]
        return "Sentimen prediksi pasar global tidak tersedia."
    except Exception as e:
        logger.warning("[SENTINEL] Prediction sentiment fetch failed: %s", e)
        return "Sentimen prediksi tidak tersedia."

def triangulate_analysis(stocks: List[Dict[str, Any]], macro: str, sentiment: str) -> List[Dict[str, Any]]:
    """Synthesize quant data (prices) with qual data (macro/sentiment) via LLM."""
    if not stocks: return []
    
    # Format stock list for prompt
    stock_table = "| Kode | Harga/LOT | Volume | YTD |\n|---|---|---|---|\n"
    for s in stocks:
        stock_table += f"| {s['stock_code']} | Rp{s['current_price_per_lot']:,} | {s['volume_24h']:,} | {s['ytd_performance']}% |\n"

    prompt = f"""Kamu adalah Senior Market Analyst Kuro AI (Hybrid Mode).
Data Kuantitatif Terkini (BEI):
{stock_table}

Konteks Ekonomi Makro:
{macro}

Sentimen Prediktif Pasar:
{sentiment}

TUGAS: Berikan triangulasi analisis untuk setiap saham di atas. 
Fokus pada potensi Return on Investment (ROI) untuk jangka pendek (1 bulan) dan jangka panjang (1 tahun).

INSTRUKSI:
- Hitung projected_roi_1m dan projected_roi_1y (dalam persentase angka).
- Berikan triangulation_summary (narasi singkat kenapa saham ini layak diambil atau tidak).
- Berikan kesimpulan akhir: "WORTH BUYING", "HOLD", atau "AVOID".

FORMAT OUTPUT: JSON array of objects.
SCHEMA:
[{{
  "stock_code": "string",
  "projected_roi_1m": number,
  "projected_roi_1y": number,
  "triangulation_summary": "string",
  "conclusion": "WORTH BUYING" | "HOLD" | "AVOID"
}}]"""

    try:
        resp = genai_client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json"
            )
        )
        return json.loads(resp.text)
    except Exception as e:
        logger.error("[SENTINEL] Triangulation LLM failed: %s", e)
        return []

def format_sentinel_telegram(analysis: List[Dict[str, Any]]) -> str:
    """Format triangulation results for Telegram."""
    if not analysis: return ""
    
    timestamp = datetime.now().strftime("%H:%M")
    msg = f"🛰️ *KURO HYBRID SENTINEL* ({timestamp})\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Top 3 Picks by ROI 1M
    top_picks = sorted([a for a in analysis if a["conclusion"] == "WORTH BUYING"], 
                       key=lambda x: x["projected_roi_1m"], reverse=True)[:3]
    
    if top_picks:
        msg += "🚀 *TOP REKOMENDASI (ROI 1M)*\n"
        for p in top_picks:
            msg += f"▸ *{p['stock_code']}*: +{p['projected_roi_1m']}% ({p['conclusion']})\n"
        msg += "\n"
    
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    msg += "_Analisis lengkap tersedia di Sentinel Hub._"
    return msg

def run_triangulation_scan(username: str = "Pantronux") -> bool:
    """Main entry point for 4-hour triangulation scan."""
    logger.info("[SENTINEL] Starting Hybrid Triangulation scan for %s...", username)
    
    # 1. Get current quantitative data from DB
    stocks = get_all_sentinel_stocks(username=username)
    if not stocks:
        logger.warning("[SENTINEL] No stock data found in DB. Run price update first.")
        return False
        
    # 2. Fetch qualitative contexts
    macro = fetch_macro_context()
    sentiment = fetch_prediction_sentiment()
    
    # 3. LLM Triangulation
    analysis = triangulate_analysis(stocks, macro, sentiment)
    
    if not analysis:
        logger.error("[SENTINEL] Triangulation failed. Falling back to raw quant data.")
        analysis = []
        for stock in stocks:
            analysis.append({
                "stock_code": stock["stock_code"],
                "projected_roi_1m": stock.get("ytd_performance", 0.0), # Fallback estimate
                "projected_roi_1y": stock.get("ytd_performance", 0.0),
                "triangulation_summary": "OpenClaw skill market_analysis failed. Menampilkan data kuantitatif raw.",
                "conclusion": "HOLD"
            })
        
    # 4. Update DB & Send notifications
    for a in analysis:
        update_sentinel_stock_analysis(
            stock_code=a["stock_code"],
            projected_roi_1m=a["projected_roi_1m"],
            projected_roi_1y=a["projected_roi_1y"],
            triangulation_summary=a["triangulation_summary"],
            conclusion=a["conclusion"],
            username=username
        )
        
    # Send Telegram (Filter: Only for Admin)
    import os
    if username == os.getenv("ADMIN_USERNAME", "Pantronux"):
        msg = format_sentinel_telegram(analysis)
        if msg:
            telegram_notifier.send_message(msg)
        
    logger.info("[SENTINEL] Hybrid Triangulation scan complete for %d stocks.", len(analysis))
    return True

# Backward compatibility / Helper functions
def get_latest_for_intelligence_hub(username: str = "Pantronux", hours: int = 12) -> List[Dict[str, Any]]:
    """Helper for Intelligence Hub to fetch latest data from the new table."""
    stocks = get_all_sentinel_stocks(sort_by="roi_1m", username=username)
    # Filter for stocks updated within last N hours
    # (Simplified: just return top 6 by ROI for now)
    return stocks[:6]

def run_sentinel_scan(username: str = "Pantronux") -> bool:
    """Deprecated: redirects to run_triangulation_scan."""
    return run_triangulation_scan(username)
