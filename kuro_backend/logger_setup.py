import os
import logging
import logging.handlers

def setup_logging(log_filename="kuro_butler.log", backup_count=30):
    """
    Centralized logging configuration for Kuro AI.
    Features: Timed rotation (30 days), noise filtering, and centralized directory.
    """
    # 1. Centralized Log Directory
    log_dir = os.path.join(os.getcwd(), "logs", "system")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, log_filename)

    # 2. Noise Filters
    class NoiseFilter(logging.Filter):
        """Filters out repetitive third-party logs and specific noise patterns."""
        def filter(self, record: logging.LogRecord) -> bool:
            # Exclude Telegram polling noise
            if "api.telegram.org" in record.getMessage() and "getUpdates" in record.getMessage():
                return False
            
            # Exclude OpenTelemetry status noise
            if record.name.startswith("opentelemetry.trace.status") and record.levelno < logging.ERROR:
                return False
                
            return True

    # 3. Formatter - Structured & Readable
    log_format = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 4. Handlers
    # Timed Rotation at midnight
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_path,
        when='midnight',
        interval=1,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(log_format)
    file_handler.addFilter(NoiseFilter())

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    console_handler.addFilter(NoiseFilter())

    # 5. Root Logger Configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.propagate = False
    
    # Clear existing handlers to prevent duplicates
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
        
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # 6. Third-party Library Silencing
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("pydantic").setLevel(logging.ERROR)
    logging.getLogger("opentelemetry").setLevel(logging.ERROR)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("phoenix.server.api").setLevel(logging.WARNING)
    
    # Ensure httpx logs are filtered if they still come through
    logging.getLogger("httpx").addFilter(NoiseFilter())

    logging.info(f"Logging initialized. Logs saved to: {log_path} (Retention: {backup_count} days)")
    return root_logger
