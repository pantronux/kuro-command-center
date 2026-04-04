import logging
import uvicorn
from fastapi import FastAPI
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

from kuro_backend.config import settings
from kuro_backend.core import process_chat

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("kuro_butler.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- FastAPI App (for future webhook) ---
app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Kuro AI Reborn is running."}

# --- Telegram Bot Logic ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Greetings, Master. Kuro is at your service."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Process only messages from the designated Master Irfan
    if str(update.effective_chat.id) != settings.TELEGRAM_CHAT_ID:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="I apologize, but I am only authorized to serve Master Irfan."
        )
        logger.warning(f"Unauthorized access attempt by chat_id: {update.effective_chat.id}")
        return

    message_text = update.message.text
    logger.info(f"Received message from Master Irfan: {message_text}")

    # Send to AI Core
    response_text = process_chat(message_text)

    # Send response back to Telegram
    await context.bot.send_message(
        chat_id=settings.TELEGRAM_CHAT_ID,
        text=response_text
    )

if __name__ == "__main__":
    # Check for essential libraries
    try:
        import proxmoxer
        import google.genai
    except ImportError as e:
        logger.critical(f"CRITICAL ERROR: Missing essential library - {e}. Please install requirements. Shutting down.")
        exit(1)

    logger.info("Kuro AI Reborn is starting...")

    # Initialize Telegram Bot
    application = ApplicationBuilder().token(settings.TELEGRAM_TOKEN).build()

    start_handler = CommandHandler('start', start)
    message_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)

    application.add_handler(start_handler)
    application.add_handler(message_handler)

    # Run the bot
    logger.info("Starting Telegram bot polling...")
    application.run_polling()

    # Note: uvicorn is not run here because the bot is polling.
    # If you wanted to run both, you would need a more complex setup (e.g., threading).
    # uvicorn.run(app, host="0.0.0.0", port=8000)
