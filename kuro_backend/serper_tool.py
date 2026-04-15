"""
Kuro AI V5.0 - Serper.dev Search Tool for Autonomous Research
================================================================================
Web search integration using Serper.dev API for proactive intelligence gathering.
"""
import os
import logging
import requests
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent double-reporting to root logger

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
SERPER_API_URL = "https://google.serper.dev"

def serper_search(query: str, search_type: str = "search", num_results: int = 10) -> Dict[str, Any]:
    """
    Search the web using Serper.dev API with Indonesia-focused parameters.
    
    Args:
        query: Search query string
        search_type: Type of search - "search", "news", "scholar"
        num_results: Number of results to return (default: 10)
    
    Returns:
        Dict containing search results with organic results, knowledge graph, etc.
    """
    if not SERPER_API_KEY:
        logger.error("[SERPER] API key not configured")
        return {"error": "SERPER_API_KEY not configured", "results": []}
    
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json"
    }
    
    # Indonesia-focused parameters
    payload = {
        "q": query,
        "gl": "id",  # Geographic location: Indonesia
        "hl": "id",  # Language: Indonesian
        "num": num_results,
    }
    
    # Determine endpoint based on search type
    if search_type == "news":
        url = f"{SERPER_API_URL}/news"
    elif search_type == "scholar":
        url = f"{SERPER_API_URL}/scholar"
    else:
        url = f"{SERPER_API_URL}/search"
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        # Extract organic results
        results = []
        for item in data.get("organic", []):
            results.append({
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "date": item.get("date", ""),
                "source": item.get("source", ""),
            })
        
        # Extract knowledge graph if available
        knowledge_graph = data.get("knowledgeGraph", {})
        
        # Extract "People Also Ask" for additional context
        people_also_ask = data.get("peopleAlsoAsk", [])
        
        logger.info(f"[SERPER] Search '{query}' returned {len(results)} results")
        
        return {
            "query": query,
            "search_type": search_type,
            "organic_results": results,
            "knowledge_graph": knowledge_graph,
            "people_also_ask": people_also_ask,
            "total_results": len(results),
        }
        
    except requests.exceptions.RequestException as e:
        logger.error(f"[SERPER] Search failed for '{query}': {e}")
        return {"error": str(e), "query": query, "results": []}
    except Exception as e:
        logger.error(f"[SERPER] Unexpected error for '{query}': {e}")
        return {"error": str(e), "query": query, "results": []}


def serper_news(query: str, num_results: int = 10) -> Dict[str, Any]:
    """Search for news articles using Serper.dev."""
    return serper_search(query, search_type="news", num_results=num_results)


def serper_scholar(query: str, num_results: int = 10) -> Dict[str, Any]:
    """Search for academic papers using Serper.dev Scholar."""
    return serper_search(query, search_type="scholar", num_results=num_results)


# Research pillars for daily intelligence briefing
RESEARCH_PILLARS = {
    "it_security_compliance": [
        "Update regulasi UU PDP Indonesia 2026",
        "ISO 27001:2022 implementation trends",
        "AI Security OWASP Top 10 for LLM 2026",
        "Cybersecurity threats Indonesia latest",
        "Zero trust architecture best practices",
    ],
    "ai_technology": [
        "Agentic AI frameworks 2026",
        "Autonomous RAG developments latest",
        "New AI tools for productivity 2026",
        "LangGraph vs LangChain comparison",
        "Enterprise AI adoption trends",
    ],
    "finance_business": [
        "Saham teknologi dividen tinggi BEI 2026",
        "Peluang bisnis SaaS AI Indonesia",
        "Passive income dari infrastruktur IT",
        "Investasi AI startup trends",
        "Cloud computing market Indonesia",
    ],
    "lifestyle_fitness": [
        "Sains body recomposition terbaru 2026",
        "Optimasi nutrisi untuk massa otot",
        "Science-based training program",
        "Recovery optimization techniques",
        "Supplement research latest",
    ],
}
