import logging
import os
import signal
import sys
import threading
import time
import uvicorn
from datetime import datetime, timedelta
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
from kuro_backend import compliance_db
from kuro_backend import reminder_db
from kuro_backend import daily_habits_db

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

# Upload directory - use tools.PROJECT_ROOT for consistency
UPLOAD_DIR = tools.UPLOAD_DIR
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
    """Handle chat requests from the web interface with vision and file reading support."""
    try:
        # Save and process uploaded files
        image_paths = []
        file_contents = []
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
                    # Use universal_read to extract text from PDF, text files, etc.
                    read_result = tools.universal_read(file_path, max_chars=10000)
                    if read_result.get("content"):
                        file_contents.append(f"\n--- File: {file.filename} ---\n{read_result['content']}")
                        
                        # Store PDF content in ChromaDB for semantic search
                        if read_result.get("format") == "pdf":
                            from kuro_backend import memory_manager
                            memory_manager.add_long_term(
                                f"PDF Document: {file.filename}\nContent: {read_result['content'][:5000]}",
                                metadata={"type": "pdf", "filename": file.filename, "path": file_path}
                            )
                            logger.info(f"Stored PDF content in ChromaDB: {file.filename}")
                    
                    file_attachments.append({"type": "file", "filename": file.filename})
                
                logger.info(f"File saved: {file_path}")
        
        # Build enhanced message with file contents
        enhanced_message = message
        if file_contents:
            enhanced_message += "\n\n[Attached Files Content:]\n" + "\n".join(file_contents)
        
        # Save user message to chat history
        chat_history.add_message("web", "user", message, [f["filename"] for f in file_attachments])
        
        # Process with AI core (with vision if images uploaded)
        response = process_chat(enhanced_message, image_paths=image_paths if image_paths else None)
        
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

@app.get("/api/system-analysis")
async def system_analysis():
    """Full system health analysis from /var/log."""
    return {"status": "success", "data": tools.analyze_system_health()}

@app.post("/api/index-path")
async def index_path(path: str = Form("/home/kuro/projects/")):
    """Index a system path recursively."""
    # Security: only allow whitelisted paths
    is_whitelisted = any(path.startswith(wp) for wp in tools.WHITELIST_PATHS)
    if not is_whitelisted:
        return {"status": "error", "message": "Path not in whitelist"}
    
    result = tools.index_system_path(path)
    return result

@app.post("/api/read-file")
async def read_file(file_path: str = Form("")):
    """Read a file using universal parser."""
    if not file_path:
        return {"status": "error", "message": "No file path provided"}
    result = tools.universal_read(file_path)
    return result

@app.get("/api/list-files")
async def list_files(directory: str = None):
    """List all files in a directory (reality check - no memory reliance)."""
    result = tools.list_my_files(directory)
    return {"status": "success", "data": result}

# --- Compliance Routes ---
@app.get("/compliance", response_class=HTMLResponse)
async def compliance_dashboard():
    """Serve the compliance dashboard."""
    return FileResponse(os.path.join(WEB_DIR, "templates", "compliance.html"))

@app.get("/api/compliance/progress/{standard}")
async def compliance_progress(standard: str):
    """Get compliance progress for a standard."""
    return {"status": "success", "data": compliance_db.get_compliance_progress(standard)}

@app.get("/api/compliance/evidence")
async def compliance_evidence(standard: str = None):
    """Get evidence matrix."""
    return {"status": "success", "data": compliance_db.get_evidence_matrix(standard)}

@app.get("/api/compliance/search")
async def compliance_search(query: str, standard: str = None):
    """Search compliance clauses."""
    return {"status": "success", "data": tools.search_compliance_clause(query, standard)}

@app.post("/api/compliance/analyze")
async def compliance_analyze(document: str = Form(""), standard: str = Form("iso27001")):
    """Run gap analysis on a document."""
    result = tools.analyze_compliance(document, standard)
    if "results" in result:
        compliance_db.add_gap_analysis("Uploaded Document", standard, result["results"])
    compliance_db.add_audit_trail("compliance_analysis", f"Analyzed document against {standard}", standard)
    return result

@app.get("/api/compliance/audit-trail")
async def audit_trail(limit: int = 50):
    """Get audit trail entries."""
    return {"status": "success", "data": compliance_db.get_audit_trail(limit)}

# --- Reminder Routes ---
@app.get("/reminders", response_class=HTMLResponse)
async def reminder_dashboard():
    """Serve the reminder dashboard."""
    return FileResponse(os.path.join(WEB_DIR, "templates", "reminder.html"))

@app.post("/api/reminders/add")
async def add_reminder(
    event_name: str = Form(""),
    event_time: str = Form(""),
    description: str = Form(""),
    source: str = Form("web")
):
    """Add a new reminder."""
    if not event_name or not event_time:
        return {"success": False, "error": "Event name and time are required."}
    
    reminder_id = reminder_db.add_reminder(
        event_name=event_name,
        event_time=event_time,
        description=description,
        source=source
    )
    
    # Format confirmation
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(event_time)
        time_str = dt.strftime("%A, %d %B %Y pukul %H:%M WIB")
    except:
        time_str = event_time
    
    return {
        "success": True,
        "reminder_id": reminder_id,
        "confirmation": f"Reminder '{event_name}' set for {time_str}."
    }

@app.get("/api/reminders/upcoming")
async def get_upcoming_reminders():
    """Get upcoming reminders."""
    reminders = reminder_db.get_upcoming_reminders()
    return {"status": "success", "reminders": reminders}

@app.get("/api/reminders/history")
async def get_reminder_history():
    """Get reminder history."""
    reminders = reminder_db.get_reminder_history()
    return {"status": "success", "reminders": reminders}

@app.get("/api/reminders/stats")
async def get_reminder_stats():
    """Get reminder statistics."""
    stats = reminder_db.get_reminder_stats()
    return {"status": "success", "stats": stats}

@app.get("/api/reminders/notifications")
async def get_pending_notifications():
    """Check for reminders that need notification."""
    notifications = []
    
    # Check 10-minute warnings
    ten_min_reminders = reminder_db.get_reminders_needing_10m_notification()
    for r in ten_min_reminders:
        reminder_db.mark_notified_10m(r['id'])
        notifications.append({
            "type": "warning",
            "message": f"Persiapan Master, 10 menit lagi event '{r['event_name']}'.",
            "reminder_id": r['id']
        })
    
    # Check event-time notifications
    event_reminders = reminder_db.get_reminders_needing_event_notification()
    for r in event_reminders:
        reminder_db.mark_notified_event(r['id'])
        notifications.append({
            "type": "urgent",
            "message": f"Waktunya event '{r['event_name']}' dimulai, Master!",
            "reminder_id": r['id']
        })
    
    return {"status": "success", "notifications": notifications}

@app.delete("/api/reminders/{reminder_id}")
async def delete_reminder(reminder_id: int):
    """Delete a reminder."""
    reminder_db.delete_reminder(reminder_id)
    return {"status": "success", "message": "Reminder deleted."}

# --- Daily Habits Routes ---
@app.get("/habits", response_class=HTMLResponse)
async def habits_dashboard():
    """Serve the daily habits dashboard."""
    return FileResponse(os.path.join(WEB_DIR, "templates", "daily_habits.html"))

@app.get("/api/habits")
async def get_habits():
    """Get all daily habits."""
    habits = daily_habits_db.get_all_habits()
    return {"status": "success", "habits": habits}

@app.post("/api/habits/add")
async def add_habit(
    title: str = Form(""),
    scheduled_time: str = Form(""),
    category: str = Form("General")
):
    """Add a new daily habit."""
    if not title or not scheduled_time:
        return {"success": False, "error": "Title and scheduled time are required."}
    
    habit_id = daily_habits_db.add_habit(title, scheduled_time, category)
    return {"success": True, "habit_id": habit_id}

@app.post("/api/habits/{habit_id}/done")
async def mark_habit_done(habit_id: int):
    """Mark a habit as done for today."""
    success = daily_habits_db.mark_habit_done(habit_id)
    if success:
        # Send Telegram notification
        habit = daily_habits_db.get_all_habits()
        habit = next((h for h in habit if h['id'] == habit_id), None)
        if habit:
            send_telegram_reminder_notification(f"✅ Habit '{habit['title']}' selesai hari ini, Master!")
    return {"success": success}

@app.post("/api/habits/{habit_id}/undo")
async def undo_habit(habit_id: int):
    """Undo a habit (mark as pending)."""
    daily_habits_db.mark_habit_undone(habit_id)
    return {"success": True}

@app.delete("/api/habits/{habit_id}")
async def delete_habit(habit_id: int):
    """Delete a habit."""
    daily_habits_db.delete_habit(habit_id)
    return {"status": "success", "message": "Habit deleted."}

@app.get("/api/habits/stats")
async def get_habits_stats():
    """Get today's habit completion stats."""
    stats = daily_habits_db.get_completion_stats()
    return {"status": "success", "stats": stats}

@app.get("/api/habits/report")
async def get_end_of_day_report():
    """Get end-of-day narrative report."""
    report = daily_habits_db.get_end_of_day_report()
    return {"status": "success", "report": report}

# --- Background Scheduler for Reminders & Habits ---
_reminder_scheduler = None

def start_reminder_scheduler():
    """Start the background scheduler for reminder notifications."""
    global _reminder_scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    
    _reminder_scheduler = BackgroundScheduler(daemon=True)
    
    # Check for pending reminders every 30 seconds
    _reminder_scheduler.add_job(
        check_reminder_notifications,
        'interval',
        seconds=30,
        id='reminder_checker',
        replace_existing=True
    )
    
    # Recovery: Load pending reminders on startup
    _reminder_scheduler.add_job(
        recover_pending_reminders,
        'date',
        run_date=datetime.now() + timedelta(seconds=5),
        id='reminder_recovery',
        replace_existing=True
    )
    
    # End-of-day habit report at 8 PM (20:00)
    _reminder_scheduler.add_job(
        send_end_of_day_report,
        'cron',
        hour=20,
        minute=0,
        id='habit_eod_report',
        replace_existing=True
    )
    
    # Midnight habit reset at 00:00
    _reminder_scheduler.add_job(
        reset_daily_habits,
        'cron',
        hour=0,
        minute=0,
        id='habit_midnight_reset',
        replace_existing=True
    )
    
    _reminder_scheduler.start()
    logger.info("Reminder & Habits scheduler started.")

def check_reminder_notifications():
    """Check and send notifications for due reminders."""
    try:
        # 10-minute warnings
        ten_min_reminders = reminder_db.get_reminders_needing_10m_notification()
        for r in ten_min_reminders:
            reminder_db.mark_notified_10m(r['id'])
            msg = f"⏰ Persiapan Master, 10 menit lagi event '{r['event_name']}'."
            logger.info(f"Reminder notification (10m): {r['event_name']}")
            # Send to Telegram if source is telegram or always
            send_telegram_reminder_notification(msg)
        
        # Event-time notifications
        event_reminders = reminder_db.get_reminders_needing_event_notification()
        for r in event_reminders:
            reminder_db.mark_notified_event(r['id'])
            msg = f"🔔 Waktunya event '{r['event_name']}' dimulai, Master!"
            logger.info(f"Reminder notification (event): {r['event_name']}")
            send_telegram_reminder_notification(msg)
    except Exception as e:
        logger.error(f"Error in reminder scheduler: {e}")

def recover_pending_reminders():
    """Recovery protocol: Load and report pending reminders on startup."""
    try:
        pending = reminder_db.get_pending_reminders()
        if pending:
            logger.info(f"Recovery: Found {len(pending)} pending reminders on startup.")
            for r in pending:
                logger.info(f"  - {r['event_name']} at {r['event_time']}")
    except Exception as e:
        logger.error(f"Error in reminder recovery: {e}")

def send_telegram_reminder_notification(message: str):
    """Send a reminder notification to Telegram."""
    try:
        import requests
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": settings.TELEGRAM_CHAT_ID,
            "text": message
        }, timeout=10)
    except Exception as e:
        logger.error(f"Failed to send Telegram reminder: {e}")

def send_end_of_day_report():
    """Send end-of-day habit report at 8 PM."""
    try:
        report = daily_habits_db.get_end_of_day_report()
        send_telegram_reminder_notification(f"📊 Laporan Harian:\n\n{report}")
        logger.info("End-of-day habit report sent.")
    except Exception as e:
        logger.error(f"Failed to send end-of-day report: {e}")

def reset_daily_habits():
    """Midnight reset: Reset all habit is_done to False."""
    try:
        daily_habits_db.reset_all_habits()
        logger.info("Daily habits reset for new day.")
    except Exception as e:
        logger.error(f"Failed to reset daily habits: {e}")

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
    logger.info(f"Reminder Dashboard: http://0.0.0.0:8000/reminders")
    logger.info(f"Habits Dashboard: http://0.0.0.0:8000/habits")

    def signal_handler(sig, frame):
        logger.info("Received interrupt signal. Shutting down gracefully...")
        if _reminder_scheduler:
            _reminder_scheduler.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start reminder scheduler
    start_reminder_scheduler()

    # Start FastAPI in a daemon thread
    uvicorn_thread = threading.Thread(target=run_uvicorn, daemon=True)
    uvicorn_thread.start()
    logger.info("FastAPI server started on port 8000")

    # Run the bot with recovery (blocking)
    run_bot_with_recovery()

    logger.info("Kuro AI Reborn has shut down.")
