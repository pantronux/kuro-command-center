"""
Kuro AI V1.0.0 Beta 4 "Sovereign Intelligence" - Config [2026-05-07]
================================================================================
Centralized configuration for Kuro AI System.

--- Header Doc ---
Purpose: Single source of truth for environment-driven runtime configuration.
Caller: Virtually every kuro_backend module + main.py bootstrap.
Dependencies: python-dotenv, pytz, stdlib os.
Main Functions: Settings() class; module constants PRIMARY_MODEL, CLASSIFIER_MODEL.
Side Effects: Reads .env at import-time; none thereafter.
"""
import os
import pytz
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ============================================
# PRIMARY MODEL CONFIGURATION
# ============================================
# CRITICAL: gemini-2.0-flash is DEPRECATED. Use gemini-3-flash-preview.
PRIMARY_MODEL = "gemini-3-flash-preview"
# V6.0 Perf Optimization: Use 2.5-flash for background tasks like memory extraction/classification
# to save latency and token costs, while preserving 3-flash for the primary responses.
CLASSIFIER_MODEL = "gemini-2.5-flash"  # For fact classification and internal routing tasks

class Settings:
    # -----------------------------------------------------------------
    # Chat Context Configuration
    # -----------------------------------------------------------------
    KURO_CHAT_CONTEXT_REFRESH_THRESHOLD: int = int(os.getenv("KURO_CHAT_CONTEXT_REFRESH_THRESHOLD", "20"))
    KURO_CHAT_CONTEXT_MODEL: str = os.getenv("KURO_CHAT_CONTEXT_MODEL", CLASSIFIER_MODEL)

    """
    Loads environment variables from the .env file.
    """
    PVE_HOST: str = os.getenv("PVE_HOST", "192.168.18.216")
    PVE_PORT: int = int(os.getenv("PVE_PORT", "8006"))
    PVE_TOKEN_ID: str = os.getenv("PVE_TOKEN_ID")
    PVE_TOKEN_SECRET: str = os.getenv("PVE_TOKEN_SECRET")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY")
    MODEL_NAME: str = os.getenv("MODEL_NAME", PRIMARY_MODEL)
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID")
    WORKING_DIR: str = os.getenv("WORKING_DIR")
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Jakarta")
    # Optional Gemini cached content resource (e.g. cachedContents/abc123) for repeated static prompts
    GEMINI_CACHED_CONTENT: str = os.getenv("GEMINI_CACHED_CONTENT", "").strip()

    # -----------------------------------------------------------------
    # Phoenix Observability Configuration
    # -----------------------------------------------------------------
    PHOENIX_WORKING_DIR: str = os.getenv("PHOENIX_WORKING_DIR", "./phoenix_data")
    PHOENIX_SQL_DATABASE_URL: str = os.getenv("PHOENIX_SQL_DATABASE_URL", "")
    KURO_TRACE_SPAN_TIMEOUT_S: int = int(os.getenv("KURO_TRACE_SPAN_TIMEOUT_S", "120"))

    # -----------------------------------------------------------------
    # Evaluation Configuration
    # -----------------------------------------------------------------
    KURO_EVAL_BATCH_RPM: int = int(os.getenv("KURO_EVAL_BATCH_RPM", "5"))
    KURO_EVAL_ALERT_THRESHOLD: float = float(os.getenv("KURO_EVAL_ALERT_THRESHOLD", "0.6"))

    # -----------------------------------------------------------------
    # Kuro V6.0 "Sovereign" — Sentinel, HUD, Voice, Sebastian toggles.
    # All defaults preserve prior behaviour; flip to enable.
    # -----------------------------------------------------------------
    # Nightly Proxmox + NVD CVE sentinel (runs inside dreaming_worker).
    KURO_CVE_SENTINEL_ENABLED: bool = os.getenv("KURO_CVE_SENTINEL_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
    KURO_CVE_MIN_CVSS: float = float(os.getenv("KURO_CVE_MIN_CVSS", "7.0"))
    KURO_CVE_MAX_ALERTS_PER_CYCLE: int = int(os.getenv("KURO_CVE_MAX_ALERTS_PER_CYCLE", "5"))
    KURO_VULN_NMAP_ENABLED: bool = os.getenv("KURO_VULN_NMAP_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")

    # Proactive event bus (fitness / hardware / memory anomalies).
    KURO_PROACTIVE_ENABLED: bool = os.getenv("KURO_PROACTIVE_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
    KURO_PROACTIVE_TELEGRAM_ENABLED: bool = os.getenv("KURO_PROACTIVE_TELEGRAM_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
    KURO_PROACTIVE_SEVERITY_FLOOR: str = os.getenv("KURO_PROACTIVE_SEVERITY_FLOOR", "warning")

    # Fitness anomaly sentinel.
    KURO_FITNESS_ENABLED: bool = os.getenv("KURO_FITNESS_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
    KURO_FITNESS_DATA_PATH: str = os.getenv("KURO_FITNESS_DATA_PATH", "~/.kuro/fitness_latest.json")
    KURO_FITNESS_INTERVAL_MIN: int = int(os.getenv("KURO_FITNESS_INTERVAL_MIN", "30"))


    # Proactive daily greeting (V6.0 Sovereign).
    KURO_PROACTIVE_GREETING_ENABLED: bool = os.getenv("KURO_PROACTIVE_GREETING_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
    KURO_PROACTIVE_GREETING_TEXT: str = os.getenv(
        "KURO_PROACTIVE_GREETING_TEXT",
        "Welcome back, Master Pantronux. All systems are operating normally.",
    )
    KURO_PROACTIVE_GREETING_COOLDOWN_DAYS: int = int(os.getenv("KURO_PROACTIVE_GREETING_COOLDOWN_DAYS", "1"))
    KURO_PROACTIVE_GREETING_LANG: str = os.getenv("KURO_PROACTIVE_GREETING_LANG", "en").strip().lower()

    # Default UI mode applied on cold start when no client-side preference
    # is remembered. One of NORMAL_MODE / HUD_MODE / RESEARCH_MODE / CINEMA_MODE.
    KURO_UI_MODE_DEFAULT: str = os.getenv("KURO_UI_MODE_DEFAULT", "NORMAL_MODE")

    # -----------------------------------------------------------------
    # Finances SSoT + Chancellor (V6.2)
    # -----------------------------------------------------------------
    KURO_FINANCE_TRACKING_ENABLED: bool = os.getenv(
        "KURO_FINANCE_TRACKING_ENABLED", "true",
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_FINANCE_DB_PATH: str = os.getenv(
        "KURO_FINANCE_DB_PATH",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "kuro_finances.db"),
    )
    KURO_FISCAL_DAILY_USD_THRESHOLD: float = float(
        os.getenv("KURO_FISCAL_DAILY_USD_THRESHOLD", "1.00"),
    )
    KURO_FISCAL_SENTINEL_ENABLED: bool = os.getenv(
        "KURO_FISCAL_SENTINEL_ENABLED", "true",
    ).strip().lower() in ("1", "true", "yes", "on")

    # Market Sentinel (Chancellor + OpenClaw) — V6.3
    KURO_MARKET_SENTINEL_ENABLED: bool = os.getenv(
        "KURO_MARKET_SENTINEL_ENABLED", "true",
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_MARKET_MOVE_PCT: float = float(os.getenv("KURO_MARKET_MOVE_PCT", "3"))
    KURO_PREDICTION_SCAN_ENABLED: bool = os.getenv(
        "KURO_PREDICTION_SCAN_ENABLED", "true",
    ).strip().lower() in ("1", "true", "yes", "on")

    # -----------------------------------------------------------------
    # Advisor Research (Beta 4 Sovereign Intelligence)
    # -----------------------------------------------------------------
    KURO_ADVISOR_AUTO_SEARCH: bool = os.getenv(
        "KURO_ADVISOR_AUTO_SEARCH", "true"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_ADVISOR_MAX_SERPER_CALLS: int = int(os.getenv("KURO_ADVISOR_MAX_SERPER_CALLS", "3"))
    KURO_RESEARCH_EXTRACT_MODEL: str = os.getenv("KURO_RESEARCH_EXTRACT_MODEL", "gemini-2.5-flash")
    KURO_ADVISOR_SCHOLAR_NUM_RESULTS: int = int(os.getenv("KURO_ADVISOR_SCHOLAR_NUM_RESULTS", "5"))

    @property
    def tz(self):
        """Get pytz timezone object for the configured timezone."""
        return pytz.timezone(self.TIMEZONE)
    
    def get_current_time(self):
        """Get current time in the configured timezone."""
        from datetime import datetime
        return datetime.now(self.tz)
    
    def get_current_time_formatted(self):
        """Get current time formatted for display."""
        ct = self.get_current_time()
        return ct.strftime("%A, %Y-%m-%d %H:%M") + " WIB"

# Initialize settings object
settings = Settings()
