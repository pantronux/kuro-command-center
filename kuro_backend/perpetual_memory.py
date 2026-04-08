"""
Kuro AI V4.0 - Perpetual Memory with Mem0 [2026-04-06]
================================================================================
Integrates Mem0 framework for long-term personal memory about Pantronux.
- Memory Extraction: Detects and saves personal info, preferences, habits
- Memory Retrieval: Searches relevant memories based on current query
- Privacy Filters: Only stores Pantronux data, excludes client data
- Habit Sync: Tracks gym/tryhackme/learning patterns for smarter scolding
"""
import logging
import os
import re
import json
from typing import List, Dict, Optional, Any
from datetime import datetime
from mem0 import Memory
from kuro_backend.config import settings

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent double-reporting to root logger


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
        self._client = None
    
    @property
    def client(self) -> Memory:
        """Lazy initialization of Mem0 client with fast fallback on embedding errors."""
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
                # Fast fallback on embedding 404 or API errors - no retry
                if "404" in error_str or "not found" in error_str or "embedding" in error_str:
                    logger.warning(f"[MEM0] Embedding API error (fast bypass): {e}")
                else:
                    logger.error(f"[MEM0] Failed to initialize client: {e}")
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
    
    def store_memories(self, memories: List[Dict]):
        """Store extracted memories in Mem0 with fast fallback on embedding errors."""
        if not self.client or not memories:
            return
        
        for mem in memories:
            try:
                # TYPE VALIDATION: Ensure mem is a dict with 'text' key before accessing
                # This prevents "string indices must be integers" errors
                if not isinstance(mem, dict):
                    logger.warning(f"[MEM0] Skipping invalid memory entry (not a dict): {type(mem)}")
                    continue
                
                mem_text = mem.get("text")
                if not mem_text or not isinstance(mem_text, str):
                    logger.warning(f"[MEM0] Skipping invalid memory entry (missing/invalid text): {mem}")
                    continue
                
                self.client.add(
                    messages=[mem_text],
                    user_id=self.user_id,
                    metadata=mem.get("metadata", {})
                )
                logger.info(f"[MEM0] Stored memory: {mem_text[:60]}...")
            except Exception as e:
                error_str = str(e).lower()
                # Fast bypass on embedding 404 - don't retry, just skip
                if "404" in error_str or "not found" in error_str or "embedding" in error_str:
                    logger.warning(f"[MEM0] Embedding error during store (fast bypass): {e}")
                    self._client = None  # Disable client to prevent further attempts
                    return
                else:
                    logger.error(f"[MEM0] Failed to store memory: {e}")
    
    def retrieve_memories(self, query: str, limit: int = 5) -> List[Dict]:
        """
        Retrieve relevant memories based on query.
        V5.0: Fast bypass on embedding errors - no timeout waiting.
        
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

            # FIX: Guard against non-list return (e.g. None or error string from Mem0)
            if not isinstance(results, list):
                logger.warning(f"[MEM0] Unexpected search result type: {type(results)}")
                return []
            
            memories = []
            for result in results:
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
            return memories
            
        except Exception as e:
            error_str = str(e).lower()
            # Fast bypass on embedding 404 - disable client and return empty
            if "404" in error_str or "not found" in error_str or "embedding" in error_str:
                logger.warning(f"[MEM0] Embedding error during retrieve (fast bypass): {e}")
                self._client = None  # Disable client to prevent further attempts
            else:
                logger.error(f"[MEM0] Failed to retrieve memories: {e}")
            return []
    
    def get_habit_history(self, habit: str, days: int = 30) -> List[Dict]:
        """Get habit completion history for the past N days."""
        if not self.client:
            return []
        
        try:
            results = self.client.search(
                query=f"{habit} completion history",
                user_id=self.user_id,
                limit=50
            )

            # FIX: Guard against non-list return
            if not isinstance(results, list):
                return []
            
            history = []
            for result in results:
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
            return f"Saya belum memiliki catatan konsisten untuk habit '{habit}'."
        
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