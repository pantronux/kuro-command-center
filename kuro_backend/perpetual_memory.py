"""
Kuro AI V6.0 Sovereign - Perpetual Memory with Mem0 [2026-04-17]
================================================================================
Integrates Mem0 framework for long-term personal memory about Pantronux.
- Memory Extraction: Detects and saves personal info, preferences, habits
- Memory Retrieval: Searches relevant memories based on current query
- Privacy Filters: Only stores Pantronux data, excludes client data
- Habit Sync: Tracks gym/tryhackme/learning patterns for smarter scolding

--- Header Doc ---
Purpose: Mem0-backed perpetual personal-memory layer with cooldown ladder and privacy filter.
Caller: memory_coordinator post-response writer, langgraph_core response_node fastpath.
Dependencies: mem0, google-genai embeddings, kuro_backend.config, file-lock for profile.
Main Functions: extract_and_store(), search_relevant(), sync_habits(), cooldown_backoff().
Side Effects: HTTP calls to Mem0, embedding API calls, persistent mem0 store writes, local cooldown state.
"""
import logging
import os
import re
import json
import time
from typing import List, Dict, Optional, Any
from datetime import datetime
from mem0 import Memory
from kuro_backend.config import settings

# Cooldown ladder (seconds) after embedding/API failure. Keeps client alive but rate-limited
# so a single 404 from gemini-embedding doesn't kill Mem0 until process restart.
_MEM0_COOLDOWN_LADDER = (60.0, 300.0, 900.0)

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent double-reporting to root logger


def _ensure_json_serializable(value: Any) -> Any:
    """Recursively coerce objects into JSON-serializable primitives for Mem0 metadata."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            out[str(k)] = _ensure_json_serializable(v)
        return out
    if isinstance(value, (list, tuple, set)):
        return [_ensure_json_serializable(v) for v in value]
    return str(value)


def coerce_mem0_search_results(raw: Any) -> List[Any]:
    """
    Mem0 `Memory.search` may return a list of hits, a dict wrapper (e.g. results/memories),
    or a single memory dict. Normalize to a list for downstream iteration.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("results", "memories", "data", "items", "search_results", "hits"):
            val = raw.get(key)
            if isinstance(val, list):
                return val
        # Single row: common Mem0 shape
        if isinstance(raw.get("memory"), str) or isinstance(raw.get("text"), str):
            return [raw]
        nested = raw.get("results")
        if isinstance(nested, dict) and isinstance(nested.get("memory"), str):
            return [nested]
    return []


def extract_json_from_text(text: str) -> Optional[Dict]:
    """
    Robust JSON extraction from text that may contain markdown code blocks,
    extra whitespace, or non-JSON content.
    
    Handles:
    - ```json ... ``` markdown blocks
    - ``` ... ``` code blocks without language tag
    - Raw JSON with surrounding text
    - String responses that need to be parsed
    
    Returns dict if successful, None otherwise.
    """
    if not text or not isinstance(text, str):
        return None
    
    text = text.strip()
    
    # Step 1: Try to extract from markdown code block first
    json_block_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if json_block_match:
        text = json_block_match.group(1)
    
    # Step 2: Try to find JSON object in text
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        try:
            result = json.loads(json_match.group())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    
    # Step 3: If text itself is a JSON string, try direct parse
    if text.startswith('{') and text.endswith('}'):
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    
    return None

# Mem0 storage directory
MEM0_STORAGE_DIR = "/home/kuro/kuro_mem0"
os.makedirs(MEM0_STORAGE_DIR, exist_ok=True)

# Pantronux user ID (privacy: only store data for this user)
MASTER_USER_ID = "pantronux"

# Privacy keywords that indicate client/confidential data (should NOT be stored)
CLIENT_DATA_KEYWORDS = [
    "confidential", 
    "rahasia perusahaan", 
    "confidential document",
]

# Habit tracking keywords
HABIT_TRACKING_KEYWORDS = {
    "gym": ["gym", "olahraga", "workout", "fitness", "latihan"],
    "tryhackme": ["tryhackme", "thm", "hack", "ctf", "cyber security"],
    "belajar": ["belajar", "study", "studying", "reading", "membaca", "kursus"],
    "timesheet": ["timesheet", "laporan kerja", "kerja", "working"],
    "ibadah": ["sholat", "salat", "prayer", "mengaji", "dzikir"],
}

# Personal preference indicators
PREFERENCE_INDICATORS = [
    "saya suka", "saya lebih suka", "preferensi saya", "saya tidak suka",
    "saya ingin", "saya butuh", "saya biasa", "saya selalu",
    "i prefer", "i like", "i don't like", "i want",
    "tolong", "please", "buatkan", "generate",
]


class PerpetualMemory:
    """
    Manages long-term personal memory using Mem0 framework.
    
    Features:
    - Memory extraction from conversations
    - Contextual memory retrieval
    - Privacy filtering (no client data)
    - Habit pattern tracking
    """
    
    def __init__(self):
        self.user_id = MASTER_USER_ID
        self._client: Optional[Memory] = None
        self._cooldown_until_ts: float = 0.0
        self._consecutive_failures: int = 0

    def _is_in_cooldown(self) -> bool:
        return time.monotonic() < self._cooldown_until_ts

    def _enter_cooldown(self, reason: str) -> None:
        idx = min(self._consecutive_failures, len(_MEM0_COOLDOWN_LADDER) - 1)
        delay = _MEM0_COOLDOWN_LADDER[idx]
        self._cooldown_until_ts = time.monotonic() + delay
        self._consecutive_failures += 1
        logger.warning(
            "[MEM0] Entering cooldown for %.0fs (failure #%s, reason=%s)",
            delay,
            self._consecutive_failures,
            reason,
        )

    def _reset_cooldown(self) -> None:
        if self._consecutive_failures or self._cooldown_until_ts:
            logger.info("[MEM0] Cooldown reset after successful operation.")
        self._cooldown_until_ts = 0.0
        self._consecutive_failures = 0

    @property
    def client(self) -> Optional[Memory]:
        """Lazy initialization of Mem0 client with cooldown-aware fallback."""
        if self._is_in_cooldown():
            return None
        if self._client is None:
            try:
                from mem0.configs.base import MemoryConfig, VectorStoreConfig, LlmConfig, EmbedderConfig
                
                # Configure Mem0 with Gemini API and local Qdrant storage
                # FIX: Explicit dimension=768 for gemini-embedding-001 model
                config = MemoryConfig(
                    vector_store=VectorStoreConfig(
                        provider="qdrant",
                        config={
                            "collection_name": "kuro_perpetual_memory",
                            "path": MEM0_STORAGE_DIR,
                            "embedding_model_dims": 768,  # gemini-embedding-001 dimension
                        }
                    ),
                    llm=LlmConfig(
                        provider="gemini",
                        config={
                            "model": "gemini-3-flash-preview",
                            "temperature": 0.1,
                            "api_key": settings.GEMINI_API_KEY,
                        }
                    ),
                    embedder=EmbedderConfig(
                        provider="gemini",
                        config={
                            "model": "models/gemini-embedding-001",
                            "api_key": settings.GEMINI_API_KEY,
                        }
                    )
                )
                
                self._client = Memory(config=config)
                logger.info(f"[MEM0] Client initialized with Gemini API and Qdrant storage at {MEM0_STORAGE_DIR}")
            except Exception as e:
                error_str = str(e).lower()
                if "404" in error_str or "not found" in error_str or "embedding" in error_str:
                    logger.warning(f"[MEM0] Embedding API error (cooldown): {e}")
                    self._enter_cooldown("init_embedding_error")
                else:
                    logger.error(f"[MEM0] Failed to initialize client: {e}")
                    self._enter_cooldown("init_generic_error")
                self._client = None
        return self._client
    
    def is_safe_to_store(self, text: str) -> bool:
        """
        Privacy check: Ensure text doesn't contain client/confidential data.
        Returns True if safe to store in Mem0.
        """
        text_lower = text.lower()
        for kw in CLIENT_DATA_KEYWORDS:
            if kw.lower() in text_lower:
                logger.warning(f"[MEM0] Blocked storing data with client keyword: {kw}")
                return False
        return True
    
    def extract_personal_info(self, message: str, response: str = "") -> List[Dict]:
        """
        Extract personal information from conversation for storage.
        
        Returns list of memories to store, or empty list if none found.
        """
        if not self.client:
            return []
        
        memories_to_store = []
        text_to_analyze = f"{message} {response}"
        
        # Check for habit completions
        habit_memories = self._extract_habit_completions(message)
        memories_to_store.extend(habit_memories)
        
        # Check for personal preferences
        preference_memories = self._extract_preferences(message)
        memories_to_store.extend(preference_memories)
        
        # Check for personal facts
        fact_memories = self._extract_personal_facts(message)
        memories_to_store.extend(fact_memories)
        
        # Filter by privacy
        safe_memories = []
        for mem in memories_to_store:
            if self.is_safe_to_store(mem.get("text", "")):
                safe_memories.append(mem)
            else:
                logger.info(f"[MEM0] Filtered out client data: {mem.get('text', '')[:50]}...")
        
        return safe_memories
    
    def _extract_habit_completions(self, message: str) -> List[Dict]:
        """Extract habit completion information."""
        memories = []
        msg_lower = message.lower()
        today = datetime.now().strftime("%A")
        today_date = datetime.now().strftime("%Y-%m-%d")
        
        for habit, keywords in HABIT_TRACKING_KEYWORDS.items():
            for kw in keywords:
                if kw in msg_lower:
                    # Check for completion indicators
                    completion_indicators = ["udah", "sudah", "done", "selesai", "ya", "iya"]
                    is_completion = any(ci in msg_lower for ci in completion_indicators)
                    
                    if is_completion:
                        memory_text = f"Pantronux completed {habit} on {today} ({today_date})"
                        memories.append({
                            "text": memory_text,
                            "metadata": {
                                "type": "habit_completion",
                                "habit": habit,
                                "date": today_date,
                                "day": today,
                            }
                        })
                        logger.info(f"[MEM0] Detected habit completion: {habit}")
                    break
        
        return memories
    
    def _extract_preferences(self, message: str) -> List[Dict]:
        """Extract personal preferences from message."""
        memories = []
        msg_lower = message.lower()
        
        for indicator in PREFERENCE_INDICATORS:
            if indicator in msg_lower:
                # Extract the preference statement
                sentences = re.split(r'[.!?]+', message)
                for sentence in sentences:
                    if indicator in sentence.lower() and len(sentence.strip()) > 15:
                        memories.append({
                            "text": f"Pantronux preference: {sentence.strip()}",
                            "metadata": {
                                "type": "preference",
                                "timestamp": datetime.now().isoformat(),
                            }
                        })
                        logger.info(f"[MEM0] Detected preference: {sentence.strip()[:50]}...")
                        break
                break
        
        return memories
    
    def _extract_personal_facts(self, message: str) -> List[Dict]:
        """Extract personal facts about Pantronux."""
        memories = []
        msg_lower = message.lower()
        
        # Personal fact indicators
        fact_indicators = [
            "saya adalah", "saya seorang", "saya punya", "saya memiliki",
            "saya sedang", "saya akan", "saya ingin", "saya merasa",
            "i am", "i have", "i feel", "i want",
        ]
        
        for indicator in fact_indicators:
            if indicator in msg_lower:
                sentences = re.split(r'[.!?]+', message)
                for sentence in sentences:
                    if indicator in sentence.lower() and len(sentence.strip()) > 15:
                        # Skip if it's a question
                        if '?' not in sentence and 'apakah' not in sentence.lower():
                            memories.append({
                                "text": f"Pantronux fact: {sentence.strip()}",
                                "metadata": {
                                    "type": "personal_fact",
                                    "timestamp": datetime.now().isoformat(),
                                }
                            })
                            logger.info(f"[MEM0] Detected personal fact: {sentence.strip()[:50]}...")
                            break
                break
        
        return memories
    
    def store_memories(self, memories: List[Any]):
        """Store extracted memories in Mem0 with fast fallback on embedding errors."""
        if not self.client or not memories:
            return
        
        for mem in memories:
            try:
                # Normalize all input shapes before .add(), including bare strings.
                # Prevents "string indices must be integers" from downstream dict-style access.
                if isinstance(mem, str):
                    payload = {"data": mem}
                    mem_text = mem
                    metadata = {}
                elif isinstance(mem, dict):
                    mem_text = mem.get("text") or mem.get("data")
                    if isinstance(mem_text, dict):
                        mem_text = json.dumps(_ensure_json_serializable(mem_text), ensure_ascii=False)
                    if not mem_text or not isinstance(mem_text, str):
                        logger.warning(f"[MEM0] Skipping invalid memory entry (missing/invalid text): {mem}")
                        continue
                    payload = {"data": mem_text}
                    metadata = _ensure_json_serializable(mem.get("metadata", {}))
                    if not isinstance(metadata, dict):
                        metadata = {"metadata_raw": str(metadata)}
                else:
                    logger.warning(f"[MEM0] Skipping invalid memory entry (unknown type): {type(mem)}")
                    continue

                self.client.add(
                    messages=[payload],
                    user_id=self.user_id,
                    metadata=metadata
                )
                logger.info("[MEM0] Memory successfully stored.")
                logger.debug(f"[MEM0] Stored memory preview: {mem_text[:60]}...")
                self._reset_cooldown()
            except Exception as e:
                error_str = str(e).lower()
                if "404" in error_str or "not found" in error_str or "embedding" in error_str:
                    logger.warning(f"[MEM0] Embedding error during store (cooldown): {e}")
                    self._enter_cooldown("store_embedding_error")
                    return
                logger.error(f"[MEM0] Failed to store memory: {e}")
                self._enter_cooldown("store_generic_error")
    
    def retrieve_memories(self, query: str, limit: int = 5) -> List[Dict]:
        """
        Retrieve relevant memories based on query.
        V5.5: Fast bypass on embedding errors - no timeout waiting.
        
        Returns list of memories with text and metadata.
        """
        if not self.client:
            return []
        
        try:
            results = self.client.search(
                query=query,
                user_id=self.user_id,
                limit=limit
            )

            coerced = coerce_mem0_search_results(results)
            if not coerced and results is not None:
                logger.debug(
                    "[MEM0] search returned non-iterable shape %s; treating as empty",
                    type(results),
                )

            memories = []
            for result in coerced:
                if isinstance(result, dict):
                    # Normal case: Mem0 returns list of dicts
                    memories.append({
                        "text": result.get("memory", result.get("text", "")),
                        "metadata": result.get("metadata", {}),
                        "score": result.get("score", 0),
                    })
                elif isinstance(result, str):
                    # FIX: Mem0 kadang return plain string — wrap jadi dict agar konsisten
                    # Root cause: 'str' object has no attribute 'get'
                    logger.warning(f"[MEM0] Result is plain string (unexpected format), wrapping: {result[:60]}")
                    memories.append({
                        "text": result,
                        "metadata": {},
                        "score": 0,
                    })
                else:
                    logger.warning(f"[MEM0] Skipping unknown result type: {type(result)}")
            
            logger.info(f"[MEM0] Retrieved {len(memories)} memories for query: {query[:50]}...")
            self._reset_cooldown()
            return memories

        except Exception as e:
            error_str = str(e).lower()
            if "404" in error_str or "not found" in error_str or "embedding" in error_str:
                logger.warning(f"[MEM0] Embedding error during retrieve (cooldown): {e}")
                self._enter_cooldown("retrieve_embedding_error")
            else:
                logger.error(f"[MEM0] Failed to retrieve memories: {e}")
                self._enter_cooldown("retrieve_generic_error")
            return []
    
    def get_habit_history(self, habit: str, days: int = 30) -> List[Dict]:
        """Get habit completion history for the past N days."""
        if not self.client:
            logger.warning(
                "[MEM0] get_habit_history(%r, days=%s): Mem0 client unavailable — returning [] (do not infer habits from this)",
                habit,
                days,
            )
            return []
        
        try:
            results = self.client.search(
                query=f"{habit} completion history",
                user_id=self.user_id,
                limit=50
            )

            coerced = coerce_mem0_search_results(results)
            if not coerced and results is not None:
                logger.debug(
                    "[MEM0] habit search non-list shape %s; no history",
                    type(results),
                )

            history = []
            for result in coerced:
                # FIX: Only process dict results — string results have no metadata to filter on
                if not isinstance(result, dict):
                    continue

                metadata = result.get("metadata", {})
                if metadata.get("type") == "habit_completion" and metadata.get("habit") == habit:
                    history.append({
                        "date": metadata.get("date", ""),
                        "day": metadata.get("day", ""),
                        "memory": result.get("memory", ""),
                    })
            
            if not history:
                logger.info(
                    "[MEM0] get_habit_history(%r, days=%s): 0 entries after filter (raw coerced len=%s)",
                    habit,
                    days,
                    len(coerced),
                )
            else:
                logger.debug(
                    "[MEM0] get_habit_history(%r, days=%s): %s entries",
                    habit,
                    days,
                    len(history),
                )
            return history
            
        except Exception as e:
            logger.error(f"[MEM0] Failed to get habit history: {e}")
            return []
    
    def generate_habit_insight(self, habit: str) -> str:
        """
        Generate insight about habit patterns for smarter scolding.
        
        Example: "Bulan lalu Master bilang suka gym Senin, tapi datanya bolong-bolong."
        """
        history = self.get_habit_history(habit, days=30)
        
        if not history:
            return (
                "Tidak ada catatan aktivitas untuk habit ini dalam memori yang tersedia. "
                "Gunakan data habit SQLite aplikasi jika perlu fakta penyelesaian; jangan mengarang."
            )
        
        # Analyze patterns
        total_completions = len(history)
        days_list = [h.get("day", "") for h in history]
        most_common_day = max(set(days_list), key=days_list.count) if days_list else "tidak diketahui"
        
        insight = f"Pantronux telah menyelesaikan '{habit}' sebanyak {total_completions} kali dalam 30 hari terakhir. "
        insight += f"Hari yang paling konsisten: {most_common_day}. "
        
        if total_completions < 15:
            insight += f"Namun, frekuensi ini masih di bawah target optimal. Disarankan untuk meningkatkan konsistensi."
        else:
            insight += f"Performa yang sangat baik! Pertahankan momentum ini."
        
        return insight
    
    def format_memories_for_context(self, memories: List[Dict]) -> str:
        """Format retrieved memories for injection into system prompt."""
        if not memories:
            return ""
        
        parts = []
        for mem in memories:
            mem_type = mem.get("metadata", {}).get("type", "general")
            text = mem.get("text", "")
            
            if mem_type == "preference":
                parts.append(f"[PREFERENSI] {text}")
            elif mem_type == "habit_completion":
                parts.append(f"[HABIT] {text}")
            elif mem_type == "personal_fact":
                parts.append(f"[FAKTA PRIBADI] {text}")
            else:
                parts.append(f"[MEMORI] {text}")
        
        return "\n".join(parts)
    
    def delete_memory(self, memory_id: str):
        """Delete a specific memory by ID."""
        if not self.client:
            return
        
        try:
            self.client.delete(memory_id)
            logger.info(f"[MEM0] Deleted memory: {memory_id}")
        except Exception as e:
            logger.error(f"[MEM0] Failed to delete memory: {e}")
    
    def get_all_memories(self, limit: int = 50) -> List[Dict]:
        """Get all memories for Pantronux (for debugging/admin)."""
        if not self.client:
            return []
        
        try:
            results = self.client.get_all(user_id=self.user_id, limit=limit)
            return results
        except Exception as e:
            logger.error(f"[MEM0] Failed to get all memories: {e}")
            return []


# Global instance
perpetual_memory = PerpetualMemory()


def get_memory_client() -> PerpetualMemory:
    """Get the global PerpetualMemory instance for testing/debugging."""
    return perpetual_memory