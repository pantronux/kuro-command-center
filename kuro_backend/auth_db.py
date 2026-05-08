"""Kuro AI V6.0 Sovereign - Authentication Database for Brute Force Protection.

ISO 27001 Compliant: A.9.4.2 Secure Log-on, A.9.5.1 Information Access Restriction.

--- Header Doc ---
Purpose: Track failed-login attempts + lockouts for dashboard auth.
Caller: main.py auth middleware / login route.
Dependencies: sqlite3, stdlib datetime.
Main Functions: init_db(), record_failed_attempt(), is_locked_out(), reset_attempts(), cleanup_old_rows().
Side Effects: Writes to kuro_auth.db; logs security events.
"""

import sqlite3
import logging
import os
import threading
from datetime import datetime, date, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent double-reporting to root logger

# Database path
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "kuro_auth.db")

_SCHEMA_READY_FOR: Optional[str] = None
_SCHEMA_LOCK = threading.Lock()

def _reset_schema_ready_for_tests() -> None:
    global _SCHEMA_READY_FOR
    with _SCHEMA_LOCK:
        _SCHEMA_READY_FOR = None


# Brute force protection constants
MAX_FAILED_ATTEMPTS = 3
LOCKOUT_DURATION_MINUTES = 15


def _get_connection():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


def init_auth_db():
    """Initialize the authentication database schema."""
    global _SCHEMA_READY_FOR
    current_path = DB_PATH
    if _SCHEMA_READY_FOR == current_path:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY_FOR == current_path:
            return
        _init_auth_db_locked()
        _SCHEMA_READY_FOR = current_path

def _init_auth_db_locked():
    conn = None
    try:
        try:
            from kuro_backend import backup_manager

            backup_manager.snapshot_pre_migration(DB_PATH, label="auth")
        except Exception as snap_exc:
            logger.warning("Pre-migration snapshot skipped: %s", snap_exc)
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

        # V6.0 Sovereign — proactive greeting ledger
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS proactive_greetings (
                username TEXT PRIMARY KEY,
                last_sent_date TEXT NOT NULL,
                last_sent_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # V1.0.0 Sovereign Cat — Robust User Management
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                email TEXT,
                display_name TEXT,
                role TEXT,
                master_name TEXT,
                restricted_persona TEXT DEFAULT '',
                custom_persona TEXT DEFAULT '',
                preferences TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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


def greeting_sent_within(username: str, cooldown_days: int) -> bool:
    """Return True if a proactive greeting was sent for ``username`` within
    the last ``cooldown_days`` calendar days.

    ``cooldown_days == 0`` forces the caller to always send (useful for the
    CLI smoke test / manual "speak now" overrides).
    """
    if cooldown_days <= 0 or not username:
        return False
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT last_sent_date FROM proactive_greetings WHERE username = ?",
            (username,),
        )
        row = cursor.fetchone()
        if not row:
            return False
        try:
            last = date.fromisoformat(row["last_sent_date"])
        except (TypeError, ValueError):
            return False
        return (date.today() - last) < timedelta(days=cooldown_days)
    except Exception as exc:
        logger.warning("greeting_sent_within failed: %s", exc)
        return False
    finally:
        if conn:
            conn.close()


def record_greeting_sent(username: str) -> None:
    """Upsert today's date as the last greeting for ``username``."""
    if not username:
        return
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO proactive_greetings (username, last_sent_date, last_sent_ts)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(username) DO UPDATE SET
                last_sent_date = excluded.last_sent_date,
                last_sent_ts = CURRENT_TIMESTAMP
            """,
            (username, date.today().isoformat()),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("record_greeting_sent failed: %s", exc)
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
def get_user(username: str) -> Optional[Dict]:
    """Get user information by username (case-insensitive)."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get user {username}: {e}")
        return None
    finally:
        if conn:
            conn.close()

def create_user(username: str, password_hash: str, email: str = "", display_name: str = "", role: str = "", master_name: str = "", restricted_persona: str = ""):
    """Create a new user in the database."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (username, password_hash, email, display_name, role, master_name, restricted_persona)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (username, password_hash, email, display_name, role, master_name, restricted_persona))
        conn.commit()
        logger.info(f"User created: {username}")
        return True
    except Exception as e:
        logger.error(f"Failed to create user {username}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def update_user_profile(username: str, email: str, display_name: str):
    """Update basic user profile information."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users 
            SET email = ?, display_name = ? 
            WHERE LOWER(username) = LOWER(?)
        """, (email, display_name, username))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to update profile for {username}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def update_password(username: str, new_password_hash: str):
    """Update user password."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password_hash = ? WHERE LOWER(username) = LOWER(?)", (new_password_hash, username))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to update password for {username}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def update_custom_persona(username: str, custom_persona: str):
    """Update user's custom persona instructions."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET custom_persona = ? WHERE LOWER(username) = LOWER(?)", (custom_persona, username))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to update custom persona for {username}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_all_users():
    """Get all users for migration check."""
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM users")
        return [row['username'] for row in cursor.fetchall()]
    except Exception:
        return []
    finally:
        if conn:
            conn.close()
