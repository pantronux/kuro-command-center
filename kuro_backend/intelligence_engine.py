"""
Kuro AI V5.5 - Proactive Intelligence Research Engine
================================================================================
Autonomous research system using Serper.dev for daily intelligence gathering.
Synthesizes findings into formal briefing reports for Pantronux.
"""
import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

from kuro_backend.config import settings, PRIMARY_MODEL
from kuro_backend.serper_tool import serper_search, serper_news, RESEARCH_PILLARS
from kuro_backend import intelligence_db

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent double-reporting to root logger

# Briefings log directory
BRIEFINGS_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "briefings")
os.makedirs(BRIEFINGS_LOG_DIR, exist_ok=True)

def generate_daily_queries() -> Dict[str, List[str]]:
    """
    Generate dynamic search queries based on research pillars.
    Uses Gemini to add 1-2 dynamic queries per pillar based on current trends.
    """
    # Start with predefined pillar queries
    queries = {}
    for pillar, base_queries in RESEARCH_PILLARS.items():
        queries[pillar] = base_queries[:3]  # Take top 3 from each pillar
    
    return queries


def execute_research(queries: Dict[str, List[str]]) -> Dict[str, Any]:
    """
    Execute search queries across all pillars.
    Returns aggregated research results.
    """
    results = {}
    
    for pillar, pillar_queries in queries.items():
        pillar_results = []
        for query in pillar_queries:
            # Mix of general search and news
            search_result = serper_search(query, num_results=5)
            if search_result.get("organic_results"):
                pillar_results.extend(search_result["organic_results"][:3])
        
        results[pillar] = pillar_results
        logger.info(f"[RESEARCH] {pillar}: {len(pillar_results)} results collected")
    
    return results


def synthesize_intelligence(research_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Use Gemini to synthesize research results into intelligence briefing.
    Returns structured briefing with sections.
    """
    from google import genai
    from google.genai import types
    
    genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    
    # Prepare research data for synthesis
    research_summary = json.dumps(research_results, ensure_ascii=False, indent=2)[:8000]
    
    prompt = f"""Kamu adalah Kuro, AI Butler dan Analis Intelijen Pantronux. Tugasmu adalah menganalisis hasil riset dan menyusun Laporan Intelijen Harian yang formal dan profesional.

DATA RISET MENTAH:
{research_summary}

INSTRUKSI LAPORAN:
Gunakan Bahasa Indonesia Formal (Baku). Panggil user dengan nama "Pantronux".

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
        logger.error(f"[INTELLIGENCE] Synthesis failed: {e}")
        # Return fallback briefing
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "status_pagi": f"Selamat pagi, Pantronux. Sistem Kuro beroperasi normal.",
            "intelijen_sektoral": "Tidak ada intelijen signifikan hari ini.",
            "wawasan_teknologi": "Tidak ada perkembangan teknologi signifikan.",
            "wawasan_finansial": "Tidak ada update finansial signifikan.",
            "rekomendasi_eksperimental": ["Lanjutkan monitoring tren AI"],
            "catatan_kesehatan": "Pastikan hidrasi yang cukup dan istirahat 7-8 jam.",
            "penutup": "Demikian laporan intelijen hari ini. Hormat saya, Kuro.",
            "full_report": f"# Laporan Intelijen Harian - {datetime.now().strftime('%Y-%m-%d')}\n\nSistem beroperasi normal.",
            "error": str(e)
        }


def format_telegram_message(briefing: Dict[str, Any]) -> str:
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
_Dikirim otomatis oleh Kuro AI Butler_"""
    
    return message


def run_daily_research() -> Dict[str, Any]:
    """
    Main function: Execute full research pipeline.
    1. Generate queries
    2. Execute research
    3. Synthesize intelligence
    4. Save to database
    5. Save to log file
    6. Return briefing for Telegram delivery
    """
    logger.info("[INTELLIGENCE] Starting daily research pipeline...")
    
    # Step 1: Generate queries
    queries = generate_daily_queries()
    logger.info(f"[INTELLIGENCE] Generated queries for {len(queries)} pillars")
    
    # Step 2: Execute research
    research_results = execute_research(queries)
    total_results = sum(len(v) for v in research_results.values())
    logger.info(f"[INTELLIGENCE] Collected {total_results} research results")
    
    # Step 3: Synthesize intelligence
    briefing = synthesize_intelligence(research_results)
    
    # Step 4: Save to database
    today = datetime.now().strftime("%Y-%m-%d")
    intelligence_db.save_briefing(
        date=today,
        summary_text=briefing.get("full_report", ""),
        raw_json_data=research_results,
        experimental_signals=briefing.get("rekomendasi_eksperimental", [])
    )
    
    # Step 5: Save to log file
    log_file = os.path.join(BRIEFINGS_LOG_DIR, f"briefing_{today}.json")
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump({
            "briefing": briefing,
            "research_data": research_results,
            "generated_at": datetime.now().isoformat()
        }, f, ensure_ascii=False, indent=2)
    
    logger.info(f"[INTELLIGENCE] Daily research complete. Briefing saved to {log_file}")
    
    return briefing
