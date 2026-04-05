import os
import pytz
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings:
    """
    Loads environment variables from the .env file.
    """
    PVE_HOST: str = os.getenv("PVE_HOST", "192.168.18.216")
    PVE_PORT: int = int(os.getenv("PVE_PORT", "8006"))
    PVE_TOKEN_ID: str = os.getenv("PVE_TOKEN_ID")
    PVE_TOKEN_SECRET: str = os.getenv("PVE_TOKEN_SECRET")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY")
    MODEL_NAME: str = os.getenv("MODEL_NAME")
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID")
    WORKING_DIR: str = os.getenv("WORKING_DIR")
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Jakarta")
    
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
