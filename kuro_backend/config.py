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


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


class Settings:
    # -----------------------------------------------------------------
    # Enterprise Refactor Control Plane (Phase 0)
    # -----------------------------------------------------------------
    # All enterprise refactor paths default off to preserve current runtime
    # behavior until each future phase explicitly gates a replacement path.
    KURO_ENTERPRISE_REFACTOR_ENABLED: bool = _env_bool("KURO_ENTERPRISE_REFACTOR_ENABLED", "false")
    KURO_MEMORY_V3_ENABLED: bool = _env_bool("KURO_MEMORY_V3_ENABLED", "false")
    KURO_STORAGE_V2_ENABLED: bool = _env_bool("KURO_STORAGE_V2_ENABLED", "false")
    KURO_CHAT_V2_ENABLED: bool = _env_bool("KURO_CHAT_V2_ENABLED", "false")
    KURO_MARKET_SENTINEL_V2_ENABLED: bool = _env_bool("KURO_MARKET_SENTINEL_V2_ENABLED", "false")
    KURO_TELEGRAM_V2_ENABLED: bool = _env_bool("KURO_TELEGRAM_V2_ENABLED", "false")
    KURO_PROVIDER_REGISTRY_V2_ENABLED: bool = _env_bool("KURO_PROVIDER_REGISTRY_V2_ENABLED", "false")
    KURO_AGENT_TOOLS_V2_ENABLED: bool = _env_bool("KURO_AGENT_TOOLS_V2_ENABLED", "false")
    KURO_TASKS_V2_ENABLED: bool = _env_bool("KURO_TASKS_V2_ENABLED", "false")
    KURO_DEEP_RESEARCH_V2_ENABLED: bool = _env_bool("KURO_DEEP_RESEARCH_V2_ENABLED", "false")
    KURO_WEB_SEARCH_V2_ENABLED: bool = _env_bool("KURO_WEB_SEARCH_V2_ENABLED", "false")
    KURO_FRONTEND_V2_ENABLED: bool = _env_bool("KURO_FRONTEND_V2_ENABLED", "false")
    KURO_ADMIN_SETTINGS_V2_ENABLED: bool = _env_bool("KURO_ADMIN_SETTINGS_V2_ENABLED", "false")
    KURO_ENTERPRISE_OBSERVABILITY_ENABLED: bool = _env_bool("KURO_ENTERPRISE_OBSERVABILITY_ENABLED", "false")
    KURO_API_V2_ENABLED: bool = _env_bool("KURO_API_V2_ENABLED", "false")

    # -----------------------------------------------------------------
    # Chat Context Configuration
    # -----------------------------------------------------------------
    KURO_CHAT_CONTEXT_REFRESH_THRESHOLD: int = int(os.getenv("KURO_CHAT_CONTEXT_REFRESH_THRESHOLD", "20"))
    KURO_CHAT_CONTEXT_MODEL: str = os.getenv("KURO_CHAT_CONTEXT_MODEL", CLASSIFIER_MODEL)
    KURO_NODE_TIMEOUT_S: int = int(os.getenv("KURO_NODE_TIMEOUT_S", "60"))
    KURO_ADVISOR_NODE_TIMEOUT_S: int = int(os.getenv("KURO_ADVISOR_NODE_TIMEOUT_S", "120"))
    KURO_EPISTEMIC_V2_ENABLED: bool = os.getenv(
        "KURO_EPISTEMIC_V2_ENABLED", "true"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_STREAM_SANITIZER_ENABLED: bool = os.getenv(
        "KURO_STREAM_SANITIZER_ENABLED", "true"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_PROVIDER_ROUTER_ENABLED: bool = os.getenv(
        "KURO_PROVIDER_ROUTER_ENABLED", "false"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_QA_PLAYGROUND_ENABLED: bool = os.getenv(
        "KURO_QA_PLAYGROUND_ENABLED", "true"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_RETRIEVAL_QUALITY_V2_ENABLED: bool = os.getenv(
        "KURO_RETRIEVAL_QUALITY_V2_ENABLED", "true"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_PERSONA_RUNTIME_V2_ENABLED: bool = os.getenv(
        "KURO_PERSONA_RUNTIME_V2_ENABLED", "true"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_MEMORY_INTEGRITY_V2_ENABLED: bool = os.getenv(
        "KURO_MEMORY_INTEGRITY_V2_ENABLED", "true"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_CANVAS2_GOAL_RUNTIME_ENABLED: bool = os.getenv(
        "KURO_CANVAS2_GOAL_RUNTIME_ENABLED", "false"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_CANVAS2_GOVERNANCE_ENABLED: bool = os.getenv(
        "KURO_CANVAS2_GOVERNANCE_ENABLED", "false"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_CANVAS2_REFLECTION_ENABLED: bool = os.getenv(
        "KURO_CANVAS2_REFLECTION_ENABLED", "false"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_CANVAS2_COG_ROUTER_ENABLED: bool = os.getenv(
        "KURO_CANVAS2_COG_ROUTER_ENABLED", "false"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_CANVAS2_OPENAI_MODEL_PLACEHOLDER_ENABLED: bool = os.getenv(
        "KURO_CANVAS2_OPENAI_MODEL_PLACEHOLDER_ENABLED", "false"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_CANVAS2_AUTONOMOUS_REPRIORITIZATION_ENABLED: bool = os.getenv(
        "KURO_CANVAS2_AUTONOMOUS_REPRIORITIZATION_ENABLED", "false"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_CANVAS3_TOOL_GOVERNANCE_ENABLED: bool = os.getenv(
        "KURO_CANVAS3_TOOL_GOVERNANCE_ENABLED", "false"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_CANVAS3_MEMORY_CANONICALIZATION_ENABLED: bool = os.getenv(
        "KURO_CANVAS3_MEMORY_CANONICALIZATION_ENABLED", "false"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_CANVAS3_COGNITIVE_BUDGET_ENABLED: bool = os.getenv(
        "KURO_CANVAS3_COGNITIVE_BUDGET_ENABLED", "false"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_CANVAS3_FAILURE_RECOVERY_ENABLED: bool = os.getenv(
        "KURO_CANVAS3_FAILURE_RECOVERY_ENABLED", "false"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_CANVAS3_RUNTIME_MODES_ENABLED: bool = os.getenv(
        "KURO_CANVAS3_RUNTIME_MODES_ENABLED", "false"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_CANVAS3_IDENTITY_CORE_ENABLED: bool = os.getenv(
        "KURO_CANVAS3_IDENTITY_CORE_ENABLED", "false"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_CANVAS3_CONSTITUTION_ENABLED: bool = os.getenv(
        "KURO_CANVAS3_CONSTITUTION_ENABLED", "false"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_CANVAS3_SOURCE_RELIABILITY_ENABLED: bool = os.getenv(
        "KURO_CANVAS3_SOURCE_RELIABILITY_ENABLED", "false"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_CANVAS3_AUTONOMY_BOUNDARIES_ENABLED: bool = os.getenv(
        "KURO_CANVAS3_AUTONOMY_BOUNDARIES_ENABLED", "false"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_CANVAS3_EVALUATION_RUNTIME_ENABLED: bool = os.getenv(
        "KURO_CANVAS3_EVALUATION_RUNTIME_ENABLED", "false"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_RUNTIME_MODE_DEFAULT: str = os.getenv("KURO_RUNTIME_MODE_DEFAULT", "BALANCED")
    KURO_CANVAS3_MAX_TOOL_CALLS: int = int(os.getenv("KURO_CANVAS3_MAX_TOOL_CALLS", "4"))
    KURO_CANVAS3_MAX_REFLECTION_DEPTH: int = int(os.getenv("KURO_CANVAS3_MAX_REFLECTION_DEPTH", "2"))
    KURO_CANVAS3_MAX_CONSENSUS_ROUNDS: int = int(os.getenv("KURO_CANVAS3_MAX_CONSENSUS_ROUNDS", "3"))
    KURO_CANVAS3_MAX_RETRIEVAL_EXPANSION: int = int(os.getenv("KURO_CANVAS3_MAX_RETRIEVAL_EXPANSION", "5"))
    KURO_DB_BUSY_TIMEOUT_MS: int = int(os.getenv("KURO_DB_BUSY_TIMEOUT_MS", "5000"))

    """
    Loads environment variables from the .env file.
    """
    PVE_HOST: str = os.getenv("PVE_HOST", "192.168.18.216")
    PVE_PORT: int = int(os.getenv("PVE_PORT", "8006"))
    PVE_TOKEN_ID: str = os.getenv("PVE_TOKEN_ID")
    PVE_TOKEN_SECRET: str = os.getenv("PVE_TOKEN_SECRET")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    KURO_DEFAULT_PROVIDER: str = os.getenv("KURO_DEFAULT_PROVIDER", "gemini")
    KURO_DEFAULT_MODEL_ALIAS: str = os.getenv("KURO_DEFAULT_MODEL_ALIAS", "gemini_fast")
    KURO_MODEL_GEMINI_FAST: str = os.getenv("KURO_MODEL_GEMINI_FAST", "gemini-3-flash-preview")
    KURO_MODEL_OPENAI_NANO: str = os.getenv("KURO_MODEL_OPENAI_NANO", "gpt-5.4-nano")
    KURO_MODEL_CLAUDE_FAST: str = os.getenv("KURO_MODEL_CLAUDE_FAST", "claude-haiku-4-5")
    KURO_MODEL_DEEPSEEK_FAST: str = os.getenv("KURO_MODEL_DEEPSEEK_FAST", "deepseek-v4-flash")
    KURO_OLLAMA_ENABLED: bool = _env_bool("KURO_OLLAMA_ENABLED", "false")
    KURO_OLLAMA_BASE_URL: str = os.getenv("KURO_OLLAMA_BASE_URL", "http://localhost:11434")
    KURO_OLLAMA_OPENAI_BASE_URL: str = os.getenv("KURO_OLLAMA_OPENAI_BASE_URL", "http://localhost:11434/v1")
    KURO_OLLAMA_TIMEOUT_S: int = int(os.getenv("KURO_OLLAMA_TIMEOUT_S", "60"))
    KURO_OLLAMA_STREAM_TIMEOUT_S: int = int(os.getenv("KURO_OLLAMA_STREAM_TIMEOUT_S", "120"))
    KURO_OLLAMA_DEFAULT_MODEL: str = os.getenv("KURO_OLLAMA_DEFAULT_MODEL", "qwen")
    KURO_MODEL_OLLAMA_LOCAL: str = os.getenv("KURO_MODEL_OLLAMA_LOCAL", KURO_OLLAMA_DEFAULT_MODEL)
    KURO_OLLAMA_USE_OPENAI_COMPAT: bool = _env_bool("KURO_OLLAMA_USE_OPENAI_COMPAT", "false")
    KURO_OLLAMA_ALLOW_PUBLIC_MODEL_LIST: bool = _env_bool("KURO_OLLAMA_ALLOW_PUBLIC_MODEL_LIST", "false")
    KURO_LOCAL_MODEL_ROUTING_ENABLED: bool = _env_bool("KURO_LOCAL_MODEL_ROUTING_ENABLED", "false")
    MODEL_NAME: str = os.getenv("MODEL_NAME", PRIMARY_MODEL)
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID")
    TELEGRAM_WEBHOOK_SECRET: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    KURO_TELEGRAM_ENABLED: bool = os.getenv(
        "KURO_TELEGRAM_ENABLED",
        os.getenv("KURO_DREAMING_TELEGRAM_ENABLED", "true"),
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_TELEGRAM_RATE_LIMIT_PER_MIN: int = int(os.getenv("KURO_TELEGRAM_RATE_LIMIT_PER_MIN", "10"))
    KURO_TELEGRAM_QUEUE_MAXSIZE: int = int(os.getenv("KURO_TELEGRAM_QUEUE_MAXSIZE", "50"))
    KURO_TELEGRAM_RESPONSE_TIMEOUT_S: int = int(os.getenv("KURO_TELEGRAM_RESPONSE_TIMEOUT_S", "180"))
    KURO_TELEGRAM_DROP_PENDING_UPDATES: bool = os.getenv(
        "KURO_TELEGRAM_DROP_PENDING_UPDATES", "false"
    ).strip().lower() in ("1", "true", "yes", "on")
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
    KURO_SENTINEL_STALE_THRESHOLD_MIN: int = int(os.getenv("KURO_SENTINEL_STALE_THRESHOLD_MIN", "15"))
    KURO_SENTINEL_DEDUP_WINDOW_MIN: int = int(os.getenv("KURO_SENTINEL_DEDUP_WINDOW_MIN", "30"))
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

    # -----------------------------------------------------------------
    # Ingestion-to-Chat Bridge (Beta 6)
    # -----------------------------------------------------------------
    KURO_INGESTION_BRIDGE_ENABLED: bool = os.getenv(
        "KURO_INGESTION_BRIDGE_ENABLED", "true"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_INGESTION_BRIDGE_TOP_K: int = int(
        os.getenv("KURO_INGESTION_BRIDGE_TOP_K", "5")
    )
    KURO_INGESTION_BRIDGE_MAX_CHARS: int = int(
        os.getenv("KURO_INGESTION_BRIDGE_MAX_CHARS", "2500")
    )
    KURO_INGESTION_BRIDGE_MIN_SCORE: float = float(
        os.getenv("KURO_INGESTION_BRIDGE_MIN_SCORE", "0.28")
    )

    # -----------------------------------------------------------------
    # Backup & Safety (Beta 5 Hotfix - Sovereign Shield)
    # -----------------------------------------------------------------
    KURO_BACKUP_ENABLED: bool = os.getenv(
        "KURO_BACKUP_ENABLED", "true"
    ).strip().lower() in ("1", "true", "yes", "on")
    KURO_BACKUP_DIR: str = os.getenv("KURO_BACKUP_DIR", "./backups")
    KURO_BACKUP_RETAIN_DAYS: int = int(os.getenv("KURO_BACKUP_RETAIN_DAYS", "30"))
    KURO_BACKUP_WEEKLY_RETAIN_WEEKS: int = int(
        os.getenv("KURO_BACKUP_WEEKLY_RETAIN_WEEKS", "8")
    )
    KURO_BACKUP_PRE_MIGRATION_RETAIN_DAYS: int = int(
        os.getenv("KURO_BACKUP_PRE_MIGRATION_RETAIN_DAYS", "7")
    )
    KURO_BACKUP_COMPRESS_LEVEL: int = int(
        os.getenv("KURO_BACKUP_COMPRESS_LEVEL", "6")
    )
    KURO_BACKUP_ALERT_ON_FAILURE: bool = os.getenv(
        "KURO_BACKUP_ALERT_ON_FAILURE", "true"
    ).strip().lower() in ("1", "true", "yes", "on")

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
