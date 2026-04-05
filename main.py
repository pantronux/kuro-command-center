import logging
import os
import signal
import sys
import threading
import time
import uvicorn
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import NetworkError, TimedOut

from kuro_backend.config import settings
from kuro_backend.core import process_chat
from kuro_backend import memory_manager
from kuro_backend import chat_history
from kuro_backend import tools

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

# --- FastAPI App ---
app = FastAPI(title="Kuro AI Web Dashboard")

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Can be restricted in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files and templates
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web_interface")
app.mount("/static", StaticFiles(directory=os.path.join(WEB_DIR, "static")), name="static")

# Upload directory
UPLOAD_DIR = os.path.join(BASE_DIR, "uploaded_files")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# --- Routes ---
@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main web dashboard."""
    return FileResponse(os.path.join(WEB_DIR, "templates", "index.html"))

@app.get("/api/history")
async def get_chat_history(limit: int = 50):
    """Get chat history from database."""
    return {"history": chat_history.get_history(limit=limit), "status": "success"}

@app.delete("/api/history")
async def clear_chat_history():
    """Clear all chat history."""
    chat_history.clear_history()
    return {"status": "success", "message": "Chat history cleared"}

@app.post("/api/chat")
async def chat_endpoint(
    message: str = Form(""),
    files: list[UploadFile] = File([])
):
    """Handle chat requests from the web interface with vision support."""
    try:
        # Save uploaded files
        image_paths = []
        file_attachments = []
        
        for file in files:
            if file.filename:
                file_path = os.path.join(UPLOAD_DIR, file.filename)
                with open(file_path, "wb") as f:
                    content = await file.read()
                    f.write(content)
                
                # Check if it's an image for vision processing
                if file.content_type and file.content_type.startswith("image/"):
                    image_paths.append(file_path)
                    file_attachments.append({"type": "image", "filename": file.filename, "path": file_path})
                else:
                    file_attachments.append({"type": "file", "filename": file.filename})
                
                logger.info(f"File saved: {file_path}")
        
        # Save user message to chat history
        chat_history.add_message("web", "user", message, [f["filename"] for f in file_attachments])
        
        # Process with AI core (with vision if images uploaded)
        response = process_chat(message, image_paths=image_paths if image_paths else None)
        
        # Save AI response to chat history
        chat_history.add_message("web", "assistant", response)
        
        return {"response": response, "status": "success"}
        
    except Exception as e:
        logger.exception(f"Error in chat endpoint: {e}")
        return {"response": f"Maaf, Master Irfan. Terjadi kesalahan: {e}", "status": "error"}

@app.get("/api/system-status")
async def system_status():
    """Get real-time system status."""
    return {"status": "success", "data": tools.get_system_status()}

@app.get("/api/proxmox-status")
async def proxmox_status():
    """Get Proxmox infrastructure status."""
    return {"status": "success", "data": tools.check_proxmox_infrastructure()}

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "memory_stats": memory_manager.get_memory_stats()
    }

# --- Telegram Bot Logic ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Greetings, Master. Kuro is at your service."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != settings.TELEGRAM_CHAT_ID:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="I apologize, but I am only authorized to serve Master Irfan."
        )
        logger.warning(f"Unauthorized access attempt by chat_id: {update.effective_chat.id}")
        return

    message_text = update.message.text
    logger.info(f"Received message from Master Irfan: {message_text}")

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        response_text = process_chat(message_text)

        if len(response_text) > 4096:
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
    error = context.error
    if isinstance(error, (NetworkError, TimedOut)):
        logger.warning(f"Network error: {error}")
        return
    logger.error(f"Update {update} caused error: {error}", exc_info=error)


def run_bot_with_recovery():
    """Runs the Telegram bot with automatic recovery on network failures."""
    max_retries = 5
    retry_delay = 5

    for attempt in range(max_retries):
        try:
            logger.info(f"Starting Telegram bot polling... (Attempt {attempt + 1}/{max_retries})")

            application = ApplicationBuilder().token(settings.TELEGRAM_TOKEN).build()

            start_handler = CommandHandler('start', start)
            message_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)

            application.add_handler(start_handler)
            application.add_handler(message_handler)
            application.add_error_handler(error_handler)

            application.run_polling(drop_pending_updates=True)

        except (NetworkError, TimedOut) as e:
            logger.warning(f"Network error during polling: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2
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


def run_uvicorn():
    """Runs FastAPI server."""
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    try:
        import requests
        import google.genai
    except ImportError as e:
        logger.critical(f"CRITICAL ERROR: Missing essential library - {e}. Please install requirements. Shutting down.")
        sys.exit(1)

    logger.info("Kuro AI Reborn is starting...")
    logger.info(f"Memory stats: {memory_manager.get_memory_stats()}")
    logger.info(f"Web Dashboard: http://0.0.0.0:8000")

    def signal_handler(sig, frame):
        logger.info("Received interrupt signal. Shutting down gracefully...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start FastAPI in a daemon thread
    uvicorn_thread = threading.Thread(target=run_uvicorn, daemon=True)
    uvicorn_thread.start()
    logger.info("FastAPI server started on port 8000")

    # Run the bot with recovery (blocking)
    run_bot_with_recovery()

    logger.info("Kuro AI Reborn has shut down.")
