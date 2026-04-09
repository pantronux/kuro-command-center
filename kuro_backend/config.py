"""
Kuro AI V2.0.1 Official - Config [2026-04-05]
================================================================================
Centralized configuration for Kuro AI Butler System.
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
CLASSIFIER_MODEL = "gemini-3-flash-preview"  # For fact classification

class Settings:
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
