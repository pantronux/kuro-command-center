"""
Kuro AI V6.0 Sovereign - Proactive Intelligence Research Engine
================================================================================
Autonomous research system using Serper.dev for daily intelligence gathering.
Synthesizes findings into formal briefing reports for Pantronux.

--- Header Doc ---
Purpose: Nightly autonomous intelligence gathering + Gemini synthesis -> intelligence_db.
Caller: dreaming_worker._run_intelligence, CLI manual briefing generator.
Dependencies: serper_tool (HTTP), google-genai (synthesis), intelligence_db.
Main Functions: run_daily_briefing(), generate_synthesis(), schedule_topics().
Side Effects: Serper HTTP calls, Gemini LLM calls, intelligence_db writes.
"""
import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

from kuro_backend.config import settings, PRIMARY_MODEL
from kuro_backend.serper_tool import serper_search, serper_news, RESEARCH_PILLARS
from kuro_backend import intelligence_db
from kuro_backend.execution.openclaw_bridge import execute_openclaw_skill_blocking

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent double-reporting to root logger

# Briefings log directory
BRIEFINGS_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "briefings")
os.makedirs(BRIEFINGS_LOG_DIR, exist_ok=True)

def generate_daily_queries(username: str = "Pantronux") -> Dict[str, List[str]]:
    """
    Generate dynamic search queries based on research pillars using Gemini.
    """
    from google import genai
    from google.genai import types
    
    genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    
    pillars_context = json.dumps(RESEARCH_PILLARS, indent=2)
    today = datetime.now().strftime("%A, %Y-%m-%d")
    
    prompt = f"""Kamu adalah Research Coordinator untuk Kuro AI. 
Hari ini adalah {today}. 
Tugasmu adalah memodifikasi dan memperluas keyword pencarian untuk Intelligence Hub agar hasil laporan harian selalu variatif dan up-to-date, namun tetap relevan dengan pilar riset utama.

PILAR RISET & TEMPLATE AWAL:
{pillars_context}

INSTRUKSI:
1. Untuk setiap pilar, berikan 3-4 query pencarian yang spesifik untuk HARI INI.
2. Gunakan konteks tren terbaru di Indonesia (jika relevan).
3. Pastikan query bervariasi dari hari kemarin (misal: fokus ke sub-topik yang berbeda).
4. Hasil HARUS dalam format JSON: {{"pilar_name": ["query1", "query2", ...]}}

OUTPUT JSON:"""

    try:
        response = genai_client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                response_mime_type="application/json"
            )
        )
        
        dynamic_queries = json.loads(response.text)
        # Validate that all pillars are present, fallback to defaults if missing
        for pillar in RESEARCH_PILLARS:
            if pillar not in dynamic_queries:
                dynamic_queries[pillar] = RESEARCH_PILLARS[pillar][:3]
        
        return dynamic_queries
        
    except Exception as e:
        logger.warning(f"[INTELLIGENCE] Dynamic query generation failed: {e}. Falling back to defaults.")
        queries = {}
        for pillar, base_queries in RESEARCH_PILLARS.items():
            queries[pillar] = base_queries[:3]
        return queries


def execute_research(queries: Dict[str, List[str]]) -> Dict[str, Any]:
    """
    Execute search queries using Serper, Google Grounding, and OpenClaw.
    """
    results = {}
    
    # 1. Traditional Search (Serper)
    for pillar, pillar_queries in queries.items():
        pillar_results = []
        for query in pillar_queries:
            search_result = serper_search(query, num_results=5)
            if search_result.get("organic_results"):
                for res in search_result["organic_results"][:3]:
                    res["_source"] = "serper"
                    pillar_results.append(res)
        results[pillar] = pillar_results
        logger.info(f"[RESEARCH] Serper: {pillar} collected")

    # 2. Google Grounding (Gemini Native Search)
    logger.info("[RESEARCH] Starting Google Grounding search...")
    google_grounding_results = execute_google_grounding_research(queries)
    for pillar, g_results in google_grounding_results.items():
        if pillar in results:
            results[pillar].extend(g_results)
        else:
            results[pillar] = g_results

    # 3. OpenClaw Specialized Skills
    logger.info("[RESEARCH] Invoking OpenClaw skills...")
    try:
        # Prediction Markets -> Merge into finance_business
        market_data = execute_openclaw_skill_blocking("prediction_market_scan", {"execution_mode": "readonly"})
        if market_data.get("success"):
            m_res = market_data.get("result", [])
            if isinstance(m_res, list):
                for res in m_res:
                    res["_source"] = "openclaw"
                if "finance_business" not in results:
                    results["finance_business"] = []
                results["finance_business"].extend(m_res)
            
        # Security Vulnerabilities -> Merge into it_security_compliance
        vuln_data = execute_openclaw_skill_blocking("vulnerability_scan", {"execution_mode": "readonly"})
        if vuln_data.get("success"):
            v_res = vuln_data.get("result", [])
            if isinstance(v_res, list):
                for res in v_res:
                    res["_source"] = "openclaw"
                if "it_security_compliance" not in results:
                    results["it_security_compliance"] = []
                results["it_security_compliance"].extend(v_res)
    except Exception as e:
        logger.warning(f"[RESEARCH] OpenClaw research failed: {e}")
    
    return results


def execute_google_grounding_research(queries: Dict[str, List[str]]) -> Dict[str, Any]:
    """Use Gemini with Google Search tool to get high-fidelity information."""
    from google import genai
    from google.genai import types
    
    genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    g_results = {}
    
    # Focus grounding on the most critical pillars to save tokens/time
    critical_pillars = ["it_security_compliance", "ai_technology", "finance_business"]
    
    for pillar in critical_pillars:
        if pillar not in queries: continue
        
        combined_query = " DAN ".join(queries[pillar][:2])
        prompt = f"Berikan analisis mendalam dan fakta terbaru mengenai topik berikut di Indonesia: {combined_query}. Fokus pada akurasi data."
        
        try:
            response = genai_client.models.generate_content(
                model=PRIMARY_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[{"google_search": {}}],
                    temperature=0.2
                )
            )
            
            g_results[pillar] = [{
                "title": f"Google Grounding: {pillar}",
                "snippet": response.text,
                "source": "Google Search Grounding",
                "_source": "grounding"
            }]
        except Exception as e:
            logger.warning(f"[RESEARCH] Google Grounding failed for {pillar}: {e}")
            
    return g_results


def execute_stock_analysis(username: str = "Pantronux") -> List[Dict[str, Any]]:
    """
    Fetch latest stock recommendations from Market Sentinel history.
    This replaces the old on-demand research with persistent scanning results.
    """
    from kuro_backend.market_sentinel import get_latest_for_intelligence_hub
    
    logger.info(f"[INTELLIGENCE] Fetching stock data from Sentinel DB for {username}...")
    # Fetch scans from the last 12 hours
    stocks = get_latest_for_intelligence_hub(username=username, hours=12)
    
    if not stocks:
        logger.warning("[INTELLIGENCE] No recent Sentinel scans found. Stock section will be empty.")
        
    return stocks


def synthesize_intelligence(research_results: Dict[str, Any], stock_recommendations: List[Dict[str, Any]], username: str = "Pantronux", display_name: str = "Pantronux") -> Dict[str, Any]:
    """
    Use Gemini to synthesize research results into intelligence briefing.
    Triangulates information from all sources.
    """
    from google import genai
    from google.genai import types
    
    genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    
    # Prepare research data for synthesis
    research_summary = json.dumps(research_results, ensure_ascii=False, indent=2)[:8000]
    stock_summary = json.dumps(stock_recommendations, ensure_ascii=False, indent=2)[:4000]
    
    prompt = f"""Kamu adalah Kuro, AI Sovereign dan Analis Intelijen {display_name}.
Tugasmu: Sintesis hasil riset menjadi Laporan Intelijen Harian yang formal.

DATA RISET (Tagged by source: serper, grounding, openclaw):
{research_summary}

REKOMENDASI SAHAM (Pre-analyzed):
{stock_summary}

INSTRUKSI TRIANGULASI:
1. Bandingkan data dari berbagai sumber. Gunakan 'grounding' sebagai validasi akurasi jika ada perbedaan.
2. Jangan biarkan ada bagian yang "N/A" jika ada setidaknya satu sumber yang memberikan data.
3. Berikan analisis yang tajam dan berwibawa.

Struktur laporan:
I. Laporan Status Pagi (Salam, Status CPU/RAM/Disk, Waktu)
II. Intelijen Sektoral (Cybersecurity & UU PDP)
III. Wawasan Teknologi AI (Agentic AI, RAG, Enterprise trends)
IV. Wawasan Finansial (Overview pasar, peluang bisnis, tren makro)
V. Rekomendasi Eksperimental (3 ide taktis)
VI. Catatan Kesehatan (Gym & Body Recomposition)
VII. Penutup (Formal)

FORMAT OUTPUT JSON:
{{
    "date": "YYYY-MM-DD",
    "status_pagi": "...",
    "intelijen_sektoral": "...",
    "wawasan_teknologi": "...",
    "wawasan_finansial": "...",
    "rekomendasi_eksperimental": ["ide1", "ide2", "ide3"],
    "catatan_kesehatan": "...",
    "penutup": "...",
    "full_report": "markdown text",
    "stock_recommendations": [...]
}}"""

    try:
        response = genai_client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=4000,
                response_mime_type="application/json"
            )
        )
        
        # Strip markdown fences if present
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0].strip()
        
        briefing = json.loads(raw)
        briefing["date"] = datetime.now().strftime("%Y-%m-%d")
        # Ensure stock recommendations are passed through
        if not briefing.get("stock_recommendations"):
            briefing["stock_recommendations"] = stock_recommendations
        
        return briefing
        
    except Exception as e:
        logger.error(f"[INTELLIGENCE] Synthesis failed: {e}")
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "status_pagi": f"Sistem Kuro beroperasi normal.",
            "intelijen_sektoral": "Data tidak tersedia.",
            "wawasan_teknologi": "Data tidak tersedia.",
            "wawasan_finansial": "Data tidak tersedia.",
            "rekomendasi_eksperimental": [],
            "catatan_kesehatan": "Jaga hidrasi dan istirahat cukup.",
            "penutup": "Demikian laporan harian. Hormat saya, Kuro.",
            "full_report": f"# Laporan Intelijen - {datetime.now().strftime('%Y-%m-%d')}\n\nSintesis gagal: {e}",
            "stock_recommendations": stock_recommendations,
            "error": str(e)
        }


def format_telegram_message(briefing: Dict[str, Any], display_name: str = "Pantronux") -> str:
    """Format main briefing for Telegram."""
    date = briefing.get("date", datetime.now().strftime("%Y-%m-%d"))
    message = f"""📋 *LAPORAN INTELJEN HARIAN*
📅 {date}

━━━━━━━━━━━━━━━━━━━━

🌅 *I. Laporan Status Pagi*
{briefing.get('status_pagi', 'N/A')}

🔒 *II. Intelijen Sektoral*
{briefing.get('intelijen_sektoral', 'N/A')}

🤖 *III. Wawasan Teknologi AI*
{briefing.get('wawasan_teknologi', 'N/A')}

💰 *IV. Wawasan Finansial*
{briefing.get('wawasan_finansial', 'N/A')}

🧪 *V. Rekomendasi Eksperimental*
"""
    for i, rec in enumerate(briefing.get("rekomendasi_eksperimental", []), 1):
        message += f"{i}. {rec}\n"
    
    message += f"""
💪 *VI. Catatan Kesehatan*
{briefing.get('catatan_kesehatan', 'N/A')}

📝 *VII. Penutup*
{briefing.get('penutup', 'N/A')}

━━━━━━━━━━━━━━━━━━━━
_Dikirim otomatis oleh Kuro AI Sovereign_"""
    original_len = len(message)
    if original_len > 4096:
        suffix = "\n\n📊 <i>Lihat laporan lengkap di Dashboard Kuro.</i>"
        message = message[:4000] + suffix
        logger.warning(
            f"Telegram message truncated from {original_len} to {len(message)} chars"
        )
    return message


def format_stock_telegram_message(briefing: Dict[str, Any]) -> str:
    """Format follow-up stock recommendations for Telegram."""
    stocks = briefing.get("stock_recommendations", [])
    if not stocks:
        return ""
        
    date = briefing.get("date", datetime.now().strftime("%Y-%m-%d"))
    message = f"""📈 *REKOMENDASI SAHAM HARIAN*
📅 {date}

━━━━━━━━━━━━━━━━━━━━\n\n"""

    has_content = False

    categories = {
        "below_100k": "💸 *Kategori: < Rp100.000 / LOT*",
        "below_500k": "💰 *Kategori: Rp100rb – Rp500rb / LOT*",
        "above_500k": "💎 *Kategori: > Rp500.000 / LOT*"
    }

    for cat_id, cat_title in categories.items():
        cat_stocks = [s for s in stocks if s.get("price_category") == cat_id]
        if not cat_stocks: continue
        
        has_content = True
        message += f"{cat_title}\n"
        for s in cat_stocks:
            conclusion_emoji = "✅" if s.get("conclusion") == "WORTH BUYING" else "⚠️" if s.get("conclusion") == "HOLD" else "❌"
            message += f"▸ *{s.get('stock_code')}* ({s.get('company_name')})\n"
            message += f"  Harga: Rp {s.get('current_price_per_share', 0):,}/lembar (Rp {s.get('current_price_per_lot', 0):,}/LOT)\n"
            message += f"  Proyeksi: 1bln {'▲' if 'bull' in s.get('projections', {}).get('1m', '').lower() else '▼' if 'bear' in s.get('projections', {}).get('1m', '').lower() else '→'} | 6bln {'▲' if 'bull' in s.get('projections', {}).get('6m', '').lower() else '▼' if 'bear' in s.get('projections', {}).get('6m', '').lower() else '→'} | 1thn {'▲' if 'bull' in s.get('projections', {}).get('1y', '').lower() else '▼' if 'bear' in s.get('projections', {}).get('1y', '').lower() else '→'}\n"
            message += f"  📌 Kesimpulan: {conclusion_emoji} *{s.get('conclusion')}*\n\n"
        message += "━━━━━━━━━━━━━━━━━━━━\n\n"

    if not has_content:
        return ""

    message += "_Analisis otomatis Kuro | Bukan saran investasi resmi_"
    return message


def run_daily_research(username: str = "Pantronux", force: bool = False) -> Dict[str, Any]:
    """
    Main function with Run-Once protection and Stock Analysis.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Run-Once Protection
    if not force:
        existing = intelligence_db.get_briefing_by_date(today, username)
        if existing:
            logger.info(f"[INTELLIGENCE] Briefing already exists for {username} on {today}. Skipping re-run.")
            # Construct a briefing dict from DB row for the caller
            return {
                "date": existing["date"],
                "full_report": existing["summary_text"],
                "rekomendasi_eksperimental": existing["experimental_signals"],
                "stock_recommendations": existing.get("stock_recommendations", []), # Handled by db helper
                "_already_exists": True
            }

    logger.info(f"[INTELLIGENCE] Starting daily research pipeline for {username}...")
    
    from kuro_backend import memory_manager
    display_name = "Pantronux"
    try:
        profile = memory_manager.load_master_profile(username)
        display_name = profile.get("master_name", username)
    except:
        pass

    # Step 1: Generate queries
    queries = generate_daily_queries(username=username)
    
    # Step 2: Execute core research
    research_results = execute_research(queries)
    
    # Step 3: Execute deep stock analysis
    stock_recommendations = execute_stock_analysis(username=username)
    
    # Step 4: Synthesize intelligence
    briefing = synthesize_intelligence(research_results, stock_recommendations, username=username, display_name=display_name)
    
    # Step 5: Save to database
    intelligence_db.save_briefing(
        date=today,
        summary_text=briefing.get("full_report", ""),
        raw_json_data=research_results,
        experimental_signals=briefing.get("rekomendasi_eksperimental", []),
        stock_recommendations=stock_recommendations,
        username=username
    )
    
    # Step 6: Save to log file
    log_file = os.path.join(BRIEFINGS_LOG_DIR, f"briefing_{username}_{today}.json")
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump({
            "briefing": briefing,
            "research_data": research_results,
            "stock_data": stock_recommendations,
            "generated_at": datetime.now().isoformat()
        }, f, ensure_ascii=False, indent=2)
    
    return briefing
