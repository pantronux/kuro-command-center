"""
Kuro Compliance Database - SQLite-based storage for audit & compliance data.
Supports ISO 27001, NIST 800-53, GDPR compliance tracking.
"""
import sqlite3
import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Optional
from kuro_backend.config import settings

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(settings.WORKING_DIR, "kuro_compliance.db")

def _get_connection():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrency
    return conn

def init_db():
    """Initialize the compliance database schema."""
    conn = _get_connection()
    cursor = conn.cursor()
    
    # Evidence Matrix table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS evidence_matrix (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT NOT NULL,
            file_path TEXT,
            category TEXT,
            standard TEXT,
            clause_id TEXT,
            status TEXT DEFAULT 'pending',
            finding TEXT,
            recommendation TEXT,
            analyzed_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Audit Trail table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_trail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            user TEXT DEFAULT 'Master Irfan',
            details TEXT,
            standard TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Compliance Standards Knowledge Base
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS standards_kb (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            standard TEXT NOT NULL,
            clause_id TEXT NOT NULL,
            title TEXT,
            description TEXT,
            category TEXT,
            cross_map TEXT,
            UNIQUE(standard, clause_id)
        )
    """)
    
    # Gap Analysis Results
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gap_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_name TEXT,
            standard TEXT,
            clause_id TEXT,
            status TEXT,
            finding TEXT,
            recommendation TEXT,
            confidence REAL,
            analyzed_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()
    logger.info(f"Compliance database initialized at {DB_PATH}")

def add_evidence(file_name: str, file_path: str, category: str, standard: str, clause_id: str = ""):
    """Add a file to the evidence matrix."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO evidence_matrix (file_name, file_path, category, standard, clause_id, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
    """, (file_name, file_path, category, standard, clause_id))
    conn.commit()
    conn.close()
    logger.info(f"Added evidence: {file_name} for {standard}")

def update_evidence_status(evidence_id: int, status: str, finding: str = "", recommendation: str = ""):
    """Update evidence analysis status."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE evidence_matrix 
        SET status = ?, finding = ?, recommendation = ?, analyzed_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (status, finding, recommendation, evidence_id))
    conn.commit()
    conn.close()

def get_evidence_matrix(standard: str = None) -> List[Dict]:
    """Get evidence matrix, optionally filtered by standard."""
    conn = _get_connection()
    cursor = conn.cursor()
    if standard:
        cursor.execute("SELECT * FROM evidence_matrix WHERE standard = ? ORDER BY created_at DESC", (standard,))
    else:
        cursor.execute("SELECT * FROM evidence_matrix ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def add_audit_trail(action: str, details: str = "", standard: str = ""):
    """Log an action to the audit trail."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO audit_trail (action, details, standard)
        VALUES (?, ?, ?)
    """, (action, details, standard))
    conn.commit()
    conn.close()

def get_audit_trail(limit: int = 50) -> List[Dict]:
    """Get recent audit trail entries."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM audit_trail ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def add_gap_analysis(document_name: str, standard: str, results: List[Dict]):
    """Store gap analysis results."""
    conn = _get_connection()
    cursor = conn.cursor()
    for result in results:
        cursor.execute("""
            INSERT INTO gap_analysis (document_name, standard, clause_id, status, finding, recommendation, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            document_name,
            standard,
            result.get("clause_id", ""),
            result.get("status", "unknown"),
            result.get("finding", ""),
            result.get("recommendation", ""),
            result.get("confidence", 0.0)
        ))
    conn.commit()
    conn.close()
    add_audit_trail("gap_analysis", f"Analyzed {document_name} against {standard}", standard)

def get_compliance_progress(standard: str) -> Dict:
    """Get compliance progress percentage for a standard."""
    conn = _get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as total FROM evidence_matrix WHERE standard = ?", (standard,))
    total = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as compliant FROM evidence_matrix WHERE standard = ? AND status = 'compliant'", (standard,))
    compliant = cursor.fetchone()["compliant"]
    
    cursor.execute("SELECT COUNT(*) as non_compliant FROM evidence_matrix WHERE standard = ? AND status = 'non_compliant'", (standard,))
    non_compliant = cursor.fetchone()["non_compliant"]
    
    conn.close()
    
    percentage = (compliant / total * 100) if total > 0 else 0
    return {
        "standard": standard,
        "total_evidence": total,
        "compliant": compliant,
        "non_compliant": non_compliant,
        "pending": total - compliant - non_compliant,
        "percentage": round(percentage, 1)
    }

# Initialize on import
init_db()
