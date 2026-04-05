"""
Memory Manager for Kuro AI - Persistent, RAM-efficient storage.

Features:
- JSON file persistence (survives restarts)
- LRU eviction (max 100 entries to protect 4GB RAM)
- Thread-safe operations
- Keyword-based search (upgrade path to chromadb vector search)
"""
import json
import logging
import os
import threading
from typing import List, Dict
from kuro_backend.config import settings

logger = logging.getLogger(__name__)

# --- Configuration ---
MAX_MEMORY_ENTRIES = 100  # LRU limit to prevent RAM exhaustion
MEMORY_FILE_PATH = os.path.join(settings.WORKING_DIR, "kuro_memory.json")

# --- Thread-safe memory storage ---
_lock = threading.Lock()
_memory_storage: List[Dict[str, str]] = []


def _load_memory():
    """Loads memory from JSON file on startup."""
    global _memory_storage
    try:
        if os.path.exists(MEMORY_FILE_PATH):
            with open(MEMORY_FILE_PATH, 'r', encoding='utf-8') as f:
                _memory_storage = json.load(f)
            logger.info(f"Loaded {len(_memory_storage)} memory entries from {MEMORY_FILE_PATH}")
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to load memory file, starting fresh: {e}")
        _memory_storage = []


def _save_memory():
    """Saves current memory state to JSON file."""
    try:
        with open(MEMORY_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(_memory_storage, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error(f"Failed to save memory file: {e}")


def _evict_oldest():
    """Removes oldest entries if memory exceeds MAX_MEMORY_ENTRIES (LRU eviction)."""
    global _memory_storage
    if len(_memory_storage) > MAX_MEMORY_ENTRIES:
        removed_count = len(_memory_storage) - MAX_MEMORY_ENTRIES
        _memory_storage = _memory_storage[removed_count:]  # Keep newest entries
        logger.info(f"Evicted {removed_count} oldest memory entries (limit: {MAX_MEMORY_ENTRIES})")


# Load memory on module import
_load_memory()


def add_memory(fact: str):
    """Adds a new fact to the memory with thread safety and persistence."""
    with _lock:
        _memory_storage.append({"fact": fact})
        _evict_oldest()
        _save_memory()
        logger.info(f"Added memory entry. Total entries: {len(_memory_storage)}")


def search_memory(query: str, top_k: int = 5) -> List[str]:
    """Searches memory for relevant facts based on a query (keyword-based).
    
    Future upgrade: Replace with chromadb vector similarity search.
    """
    with _lock:
        query_words = set(query.lower().split())
        relevant_facts = []

        for entry in _memory_storage:
            fact_words = set(entry['fact'].lower().split())
            # Calculate overlap score
            overlap = len(query_words.intersection(fact_words))
            if overlap > 0:
                relevant_facts.append((overlap, entry['fact']))

        # Sort by relevance (highest overlap first) and return top_k
        relevant_facts.sort(key=lambda x: x[0], reverse=True)
        return [fact for _, fact in relevant_facts[:top_k]]


def clear_memory():
    """Clears all memory entries (use with caution)."""
    with _lock:
        _memory_storage.clear()
        _save_memory()
        logger.info("All memory entries cleared.")


def get_memory_stats() -> Dict:
    """Returns statistics about the memory system."""
    with _lock:
        return {
            "total_entries": len(_memory_storage),
            "max_entries": MAX_MEMORY_ENTRIES,
            "storage_file": MEMORY_FILE_PATH,
            "file_exists": os.path.exists(MEMORY_FILE_PATH)
        }
