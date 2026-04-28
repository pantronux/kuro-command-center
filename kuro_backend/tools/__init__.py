"""
Kuro AI V6.0 Sovereign Tools Package
Re-exports all functions from the original tools.py module.

--- Header Doc ---
Purpose: Public tool surface for Gemini tool-calling (re-export from base_tools).
Caller: core.py, langgraph_core.py, main.py (when assembling generation_config tools).
Dependencies: kuro_backend.tools.base_tools.
Main Functions: finance/market/system tools + filesystem path constants.
Side Effects: None at import (base_tools itself is import-safe).
"""
# Re-export everything from the original tools.py (now base_tools.py)
from kuro_backend.tools.base_tools import (
    get_system_status,
    check_proxmox_infrastructure,
    list_my_files,
    list_project_files,
    universal_read,
    read_pdf_content,
    parse_log_content,
    index_system_path,
    analyze_system_health,
    process_video,
    set_monthly_budget_tool,
    get_budget_tool,
    add_recurring_expense_tool,
    list_recurring_expenses_tool,
    get_daily_api_cost_tool,
    get_ticker_price_tool,
    get_market_news_tool,
    prediction_market_scan_tool,
    advanced_execution_tool,
    summarize_pdf,
    summarize_document,
    smart_read,
    read_docx_content,
    read_xlsx_content,
    read_pptx_content,
    PROJECT_ROOT,
    UPLOAD_DIR,
    LOGS_DIR,
    DB_DIR,
    MAX_FILE_SIZE_MB,
    WHITELIST_PATHS,
    TEXT_EXTENSIONS,
    PDF_EXTENSIONS,
    IMAGE_EXTENSIONS,
    DOCX_EXTENSIONS,
    XLSX_EXTENSIONS,
    PPTX_EXTENSIONS,
)
