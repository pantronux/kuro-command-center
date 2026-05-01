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
                pillar_results.extend(search_result["organic_results"][:3])
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
        # Prediction Markets
        market_data = execute_openclaw_skill_blocking("prediction_market_scan", {"execution_mode": "readonly"})
        if market_data.get("success"):
            results["market_signals"] = market_data.get("result", [])
            
        # Security Vulnerabilities
        vuln_data = execute_openclaw_skill_blocking("vulnerability_scan", {"execution_mode": "readonly"})
        if vuln_data.get("success"):
            results["security_vulnerabilities"] = vuln_data.get("result", [])
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
                "source": "Google Search Grounding"
            }]
        except Exception as e:
            logger.warning(f"[RESEARCH] Google Grounding failed for {pillar}: {e}")
            
    return g_results


def synthesize_intelligence(research_results: Dict[str, Any], username: str = "Pantronux", display_name: str = "Pantronux") -> Dict[str, Any]:
    """
    Use Gemini to synthesize research results into intelligence briefing.
    Returns structured briefing with sections.
    """
    from google import genai
    from google.genai import types
    
    genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    
    # Prepare research data for synthesis
    research_summary = json.dumps(research_results, ensure_ascii=False, indent=2)[:8000]
    
    prompt = f"""Kamu adalah Kuro, AI Sovereign dan Analis Intelijen {display_name}. Tugasmu adalah menganalisis hasil riset dan menyusun Laporan Intelijen Harian yang formal dan profesional.

DATA RISET MENTAH:
{research_summary}

INSTRUKSI LAPORAN:
Gunakan Bahasa Indonesia Formal (Baku). Panggil user dengan nama "{display_name}".

Struktur laporan WAJIB:

I. Laporan Status Pagi
- Salam pembuka formal
- Kondisi sistem Kuro (CPU, RAM, Disk)
- Tanggal dan waktu briefing

II. Intelijen Sektoral (IT Security & Compliance)
- Berita keamanan siber terbaru
- Update regulasi UU PDP dan ISO
- Ancaman siber yang perlu diwaspadai

III. Wawasan Teknologi AI
- Perkembangan Agentic AI dan RAG
- Tools AI baru untuk produktivitas
- Tren adopsi AI enterprise

IV. Wawasan Finansial
- Update pasar saham teknologi BEI
- Peluang bisnis SaaS AI
- Passive income dari infrastruktur IT

V. Rekomendasi Eksperimental
- 2-3 ide bisnis atau teknologi yang bisa langsung dieksekusi
- API baru atau tools menarik
- Peluang yang teridentifikasi dari riset

VI. Catatan Kesehatan
- Tip singkat terkait kebugaran/gym
- Sains body recomposition terbaru

VII. Penutup
- Kalimat penutup formal

FORMAT OUTPUT:
Kembalikan sebagai JSON dengan struktur:
{{
    "date": "YYYY-MM-DD",
    "status_pagi": "...",
    "intelijen_sektoral": "...",
    "wawasan_teknologi": "...",
    "wawasan_finansial": "...",
    "rekomendasi_eksperimental": ["ide1", "ide2", "ide3"],
    "catatan_kesehatan": "...",
    "penutup": "...",
    "full_report": "Laporan lengkap dalam format markdown"
}}

LAPORAN:"""

    try:
        response = genai_client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=4000,
            )
        )
        
        # Parse JSON from response
        response_text = response.text.strip()
        
        # Extract JSON from response (handle markdown code blocks)
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[-1]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
        
        briefing = json.loads(response_text)
        briefing["date"] = datetime.now().strftime("%Y-%m-%d")
        
        return briefing
        
    except Exception as e:
        logger.error(f"[INTELLIGENCE] Synthesis failed for {username}: {e}")
        # Return fallback briefing
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "status_pagi": f"Selamat pagi, {display_name}. Sistem Kuro beroperasi normal.",
            "intelijen_sektoral": "Tidak ada intelijen signifikan hari ini.",
            "wawasan_teknologi": "Tidak ada perkembangan teknologi signifikan.",
            "wawasan_finansial": "Tidak ada update finansial signifikan.",
            "rekomendasi_eksperimental": ["Lanjutkan monitoring tren AI"],
            "catatan_kesehatan": "Pastikan hidrasi yang cukup dan istirahat 7-8 jam.",
            "penutup": "Demikian laporan intelijen hari ini. Hormat saya, Kuro.",
            "full_report": f"# Laporan Intelijen Harian - {datetime.now().strftime('%Y-%m-%d')}\n\nSistem beroperasi normal.",
            "error": str(e)
        }


def format_telegram_message(briefing: Dict[str, Any], display_name: str = "Pantronux") -> str:
    """Format briefing for Telegram message with markdown."""
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
    
    return message


def run_daily_research(username: str = "Pantronux") -> Dict[str, Any]:
    """
    Main function: Execute full research pipeline for a specific user.
    1. Generate queries
    2. Execute research
    3. Synthesize intelligence
    4. Save to database
    5. Save to log file
    6. Return briefing for Telegram delivery
    """
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
    logger.info(f"[INTELLIGENCE] Generated dynamic queries for {len(queries)} pillars")
    
    # Step 2: Execute research
    research_results = execute_research(queries)
    total_results = sum(len(v) for v in research_results.values())
    logger.info(f"[INTELLIGENCE] Collected {total_results} research results")
    
    # Step 3: Synthesize intelligence
    briefing = synthesize_intelligence(research_results, username=username, display_name=display_name)
    
    # Step 4: Save to database
    today = datetime.now().strftime("%Y-%m-%d")
    intelligence_db.save_briefing(
        date=today,
        summary_text=briefing.get("full_report", ""),
        raw_json_data=research_results,
        experimental_signals=briefing.get("rekomendasi_eksperimental", []),
        username=username
    )
    
    # Step 5: Save to log file
    log_file = os.path.join(BRIEFINGS_LOG_DIR, f"briefing_{username}_{today}.json")
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump({
            "briefing": briefing,
            "research_data": research_results,
            "generated_at": datetime.now().isoformat()
        }, f, ensure_ascii=False, indent=2)
    
    logger.info(f"[INTELLIGENCE] Daily research complete. Briefing saved to {log_file}")
    
    return briefing
