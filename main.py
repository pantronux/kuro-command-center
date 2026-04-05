import logging
import signal
import sys
import time
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import NetworkError, TimedOut

from kuro_backend.config import settings
from kuro_backend.core import process_chat
from kuro_backend import memory_manager

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

    # Send typing action to indicate processing
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        # Send to AI Core
        response_text = process_chat(message_text)

        # Send response back to Telegram (handle long messages)
        if len(response_text) > 4096:
            # Split long messages into chunks
            for i in range(0, len(response_text), 4000):
                chunk = response_text[i:i+4000]
                await context.bot.send_message(
                    chat_id=settings.TELEGRAM_CHAT_ID,
                    text=chunk
                )
        else:
            await context.bot.send_message(
                chat_id=settings.TELEGRAM_CHAT_ID,
                text=response_text
            )
    except Exception as e:
        logger.exception(f"Error sending response to Telegram: {e}")
        await context.bot.send_message(
            chat_id=settings.TELEGRAM_CHAT_ID,
            text="Maaf, Master Irfan. Kuro mengalami kesalahan saat mengirim respons. Silakan coba lagi."
        )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handles errors from the Telegram bot."""
    error = context.error
    if isinstance(error, (NetworkError, TimedOut)):
        logger.warning(f"Network error: {error}")
        return
    logger.error(f"Update {update} caused error: {error}", exc_info=error)


def run_bot_with_recovery():
    """Runs the Telegram bot with automatic recovery on network failures."""
    max_retries = 5
    retry_delay = 5  # seconds

    for attempt in range(max_retries):
        try:
            logger.info(f"Starting Telegram bot polling... (Attempt {attempt + 1}/{max_retries})")

            # Initialize Telegram Bot
            application = ApplicationBuilder().token(settings.TELEGRAM_TOKEN).build()

            start_handler = CommandHandler('start', start)
            message_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)

            application.add_handler(start_handler)
            application.add_handler(message_handler)
            application.add_error_handler(error_handler)

            # Run the bot (blocking call)
            application.run_polling(drop_pending_updates=True)

        except (NetworkError, TimedOut) as e:
            logger.warning(f"Network error during polling: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                logger.critical("Max retries reached. Shutting down.")
                raise

        except KeyboardInterrupt:
            logger.info("Received shutdown signal. Stopping bot gracefully...")
            break

        except Exception as e:
            logger.exception(f"Unexpected error in bot polling: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                logger.critical("Max retries reached. Shutting down.")
                raise


if __name__ == "__main__":
    # Check for essential libraries
    try:
        import requests
        import google.genai
    except ImportError as e:
        logger.critical(f"CRITICAL ERROR: Missing essential library - {e}. Please install requirements. Shutting down.")
        sys.exit(1)

    logger.info("Kuro AI Reborn is starting...")
    logger.info(f"Memory stats: {memory_manager.get_memory_stats()}")

    # Graceful shutdown handler
    def signal_handler(sig, frame):
        logger.info("Received interrupt signal. Shutting down gracefully...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run the bot with recovery (blocking)
    run_bot_with_recovery()

    logger.info("Kuro AI Reborn has shut down.")
