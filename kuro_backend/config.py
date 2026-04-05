import os
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

# Initialize settings object
settings = Settings()
