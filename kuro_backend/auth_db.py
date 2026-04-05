# auth_db.py
# Kuro AI V2.1 - Authentication Database for Brute Force Protection
# ISO 27001 Compliant: A.9.4.2 Secure Log-on, A.9.5.1 Information Access Restriction

import sqlite3
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Database path
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "kuro_auth.db")

# Brute force protection constants
MAX_FAILED_ATTEMPTS = 3
LOCKOUT_DURATION_MINUTES = 15


def _get_connection():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_db():
    """Initialize the authentication database schema."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        
        # Failed login attempts tracker
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS failed_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                ip_address TEXT,
                attempt_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_agent TEXT
            )
        """)
        
        # Successful login sessions tracker
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS login_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                ip_address TEXT,
                login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                logout_time TIMESTAMP,
                user_agent TEXT
            )
        """)
        
        # Account lockout tracker (in-memory cache alternative)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS account_lockouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                lockout_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                lockout_until TIMESTAMP,
                reason TEXT DEFAULT 'brute_force_protection'
            )
        """)
        
        conn.commit()
        logger.info("Auth database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize auth database: {e}")
        raise
    finally:
        if conn:
            conn.close()


def record_failed_attempt(username: str, ip_address: str = "", user_agent: str = "") -> int:
    """Record a failed login attempt and return the total count."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        
        # Insert failed attempt
        cursor.execute(
            "INSERT INTO failed_attempts (username, ip_address, user_agent) VALUES (?, ?, ?)",
            (username, ip_address, user_agent)
        )
        conn.commit()
        
        # Count recent failed attempts (within lockout window)
        cutoff_time = (datetime.now() - timedelta(minutes=LOCKOUT_DURATION_MINUTES * 2)).isoformat()
        cursor.execute(
            "SELECT COUNT(*) as count FROM failed_attempts WHERE username = ? AND attempt_time > ?",
            (username, cutoff_time)
        )
        result = cursor.fetchone()
        return result['count'] if result else 0
    except Exception as e:
        logger.error(f"Failed to record failed attempt: {e}")
        return 0
    finally:
        if conn:
            conn.close()


def clear_failed_attempts(username: str):
    """Clear failed attempts after successful login."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM failed_attempts WHERE username = ?", (username,))
        conn.commit()
        logger.info(f"Cleared failed attempts for user: {username}")
    except Exception as e:
        logger.error(f"Failed to clear failed attempts: {e}")
    finally:
        if conn:
            conn.close()


def is_account_locked(username: str) -> Dict:
    """Check if an account is currently locked out."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        
        # Check lockout table
        cursor.execute(
            "SELECT lockout_until FROM account_lockouts WHERE username = ?",
            (username,)
        )
        lockout = cursor.fetchone()
        
        if lockout:
            lockout_until = datetime.fromisoformat(lockout['lockout_until'])
            if datetime.now() < lockout_until:
                remaining = lockout_until - datetime.now()
                minutes = int(remaining.total_seconds() // 60)
                seconds = int(remaining.total_seconds() % 60)
                return {
                    "locked": True,
                    "remaining_minutes": minutes,
                    "remaining_seconds": seconds,
                    "message": f"Account locked. Try again in {minutes}m {seconds}s"
                }
            else:
                # Lockout expired, remove it
                cursor.execute("DELETE FROM account_lockouts WHERE username = ?", (username,))
                conn.commit()
        
        return {"locked": False}
    except Exception as e:
        logger.error(f"Failed to check account lockout: {e}")
        return {"locked": False}
    finally:
        if conn:
            conn.close()


def lock_account(username: str):
    """Lock an account after too many failed attempts."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        lockout_until = datetime.now() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
        
        cursor.execute("""
            INSERT OR REPLACE INTO account_lockouts (username, lockout_until)
            VALUES (?, ?)
        """, (username, lockout_until.isoformat()))
        conn.commit()
        
        logger.warning(f"ACCOUNT LOCKED: {username} - Brute force protection activated")
    except Exception as e:
        logger.error(f"Failed to lock account: {e}")
    finally:
        if conn:
            conn.close()


def record_successful_login(username: str, ip_address: str = "", user_agent: str = ""):
    """Record a successful login session."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO login_sessions (username, ip_address, user_agent) VALUES (?, ?, ?)",
            (username, ip_address, user_agent)
        )
        conn.commit()
        logger.info(f"Successful login recorded: {username}")
    except Exception as e:
        logger.error(f"Failed to record successful login: {e}")
    finally:
        if conn:
            conn.close()


def get_login_stats() -> Dict:
    """Get authentication statistics for dashboard."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        
        # Total failed attempts today
        today_start = datetime.now().replace(hour=0, minute=0, second=0).isoformat()
        cursor.execute(
            "SELECT COUNT(*) as count FROM failed_attempts WHERE attempt_time > ?",
            (today_start,)
        )
        failed_today = cursor.fetchone()['count']
        
        # Total successful logins today
        cursor.execute(
            "SELECT COUNT(*) as count FROM login_sessions WHERE login_time > ?",
            (today_start,)
        )
        successful_today = cursor.fetchone()['count']
        
        # Currently locked accounts
        cursor.execute(
            "SELECT COUNT(*) as count FROM account_lockouts WHERE lockout_until > ?",
            (datetime.now().isoformat(),)
        )
        locked_accounts = cursor.fetchone()['count']
        
        return {
            "failed_attempts_today": failed_today,
            "successful_logins_today": successful_today,
            "locked_accounts": locked_accounts
        }
    except Exception as e:
        logger.error(f"Failed to get login stats: {e}")
        return {"failed_attempts_today": 0, "successful_logins_today": 0, "locked_accounts": 0}
    finally:
        if conn:
            conn.close()
