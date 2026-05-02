import os
import json
import logging
import hashlib
from datetime import datetime
from typing import List, Dict, Optional
from kuro_backend import chat_history, memory_manager, memory_coordinator, tools
from kuro_backend.config import settings

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "uploaded_files")
ARCHIVE_DIR = os.path.join(UPLOAD_DIR, ".archive")

def run_retention_cycle(dry_run: bool = False) -> Dict:
    """Main entry for 180-day retention cycle."""
    logger.info("[RETENTION] Starting cycle (dry_run=%s)", dry_run)
    expiring = chat_history.get_expiring_files(days_ahead=0)
    
    results = {"total": len(expiring), "archived": 0, "failed": 0}
    
    for file_record in expiring:
        try:
            success = analyze_and_archive_file(file_record, dry_run)
            if success:
                results["archived"] += 1
            else:
                results["failed"] += 1
        except Exception as e:
            logger.error("[RETENTION] Failed to process %s: %s", file_record['stored_filename'], e)
            results["failed"] += 1
            
    logger.info("[RETENTION] Cycle complete: %s", results)
    return results

def analyze_and_archive_file(file_record: Dict, dry_run: bool = False) -> bool:
    """Analyze file with AI, create archive metadata, then delete physical file."""
    username = file_record["username"]
    stored_filename = file_record["stored_filename"]
    stored_path = file_record["stored_path"]
    
    if not os.path.exists(stored_path):
        logger.warning("[RETENTION] File not found at %s, marking as archived anyway.", stored_path)
        chat_history.mark_file_archived(stored_filename, "MISSING_FILE")
        return True

    # 1. Read content
    content = ""
    ext = os.path.splitext(stored_filename)[1].lower()
    try:
        if ext == ".pdf":
            read_res = tools.read_pdf_content(stored_path)
            content = read_res.get("content", "")
        else:
            read_res = tools.universal_read(stored_path)
            content = read_res.get("content", "")
    except Exception as e:
        logger.error("[RETENTION] AI Read failed for %s: %s", stored_filename, e)
        # We still want to archive basic metadata if content read fails
        content = f"Read failed: {str(e)}"

    # 2. AI Analysis
    # We use a simple prompt for archival summary
    analysis = _ai_analyze_content(content, file_record)
    
    # 3. Create sidecar JSON
    archive_data = {
        "original_filename": file_record["original_filename"],
        "stored_filename": stored_filename,
        "uploaded_at": file_record["uploaded_at"],
        "archived_at": datetime.now().isoformat(),
        "username": username,
        "content_type": file_record["content_type"],
        "size_bytes": file_record["size_bytes"],
        "sha256": file_record["sha256"],
        **analysis
    }
    
    if dry_run:
        logger.info("[RETENTION][DRY-RUN] Would archive %s", stored_filename)
        return True

    user_archive_dir = os.path.join(ARCHIVE_DIR, username)
    os.makedirs(user_archive_dir, exist_ok=True)
    archive_path = os.path.join(user_archive_dir, f"{stored_filename}_archive.json")
    
    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(archive_data, f, indent=2)

    # 4. Write to Memory
    _write_to_memory(archive_data, username)

    # 5. Delete physical file
    os.remove(stored_path)
    
    # 6. Update DB
    chat_history.mark_file_archived(stored_filename, archive_path)
    
    logger.info("[RETENTION] Successfully archived and deleted %s", stored_filename)
    return True

def _ai_analyze_content(content: str, record: Dict) -> Dict:
    """Use Gemini to summarize the file for archival memory."""
    from kuro_backend.core import client
    from kuro_backend.config import PRIMARY_MODEL
    
    prompt = f"""
    Analyze the following content from an uploaded file that is being archived (deleted to save space).
    Provide a concise summary, key entities, topics, and metadata tags for Kuro's long-term memory.
    
    File: {record['original_filename']}
    Content Snippet (first 4000 chars):
    {content[:4000]}
    
    Return ONLY a JSON object with:
    {{
      "file_summary": "string",
      "key_entities": ["list"],
      "topics": ["list"],
      "metadata_tags": ["list"]
    }}
    """
    
    try:
        response = client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=prompt,
        )
        resp_text = response.text
        # Extract JSON
        import re
        match = re.search(r'\{.*\}', resp_text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        logger.error("[RETENTION] AI Analysis failed: %s", e)
    
    return {
        "file_summary": "AI summary failed.",
        "key_entities": [],
        "topics": [],
        "metadata_tags": []
    }

def _write_to_memory(archive_data: Dict, username: str):
    """Integrate archive summary into Kuro's memory layers."""
    narrative = (
        f"[ARCHIVED FILE] User {username} uploaded '{archive_data['original_filename']}' "
        f"on {archive_data['uploaded_at']}. "
        f"Summary: {archive_data['file_summary']} "
        f"Topics: {', '.join(archive_data['topics'])}."
    )
    
    # 1. Research Ledger
    memory_manager.append_research_ledger(
        persona_scope="consultant",
        kind="archived_file_memory",
        content=narrative,
        username=username
    )
    
    # 2. Mem0 (Long-term semantic)
    try:
        from kuro_backend import perpetual_memory
        perpetual_memory.perpetual_memory.store_memories([{"text": narrative}], username)
    except Exception as e:
        logger.error("[RETENTION] Mem0 storage failed: %s", e)
