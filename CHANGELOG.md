# Kuro AI V3.2 Official - Changelog

**Release Date:** 2026-04-06
**Version:** 3.2.0
**Codename:** "Habit Tracker V2.0 - Data Viz & AI Scolding"

---

## V3.2.0 - Habit Tracker V2.0 (2026-04-06)

### Major Upgrade: Monthly/Weekly Analytics Dashboard with AI Evaluation

#### Database Schema Refactor (V2.0)
- **New Table**: `habit_logs` - Daily log entries with date-based tracking (habit_id, log_date, status, notes)
- **Updated Table**: `daily_habits` - Added `target_per_month` (default 30) and `target_per_week` (default 7) columns
- **New Table**: `ai_evaluations` - Cache for Gemini 3 monthly/weekly reports (prevents redundant API calls)
- **Migration**: Auto-detects and adds missing columns to existing databases

#### Backend API Endpoints
- **GET `/api/habits/monthly`**: Returns monthly grid data with per-habit daily logs, overall stats
- **GET `/api/habits/weekly`**: Returns weekly grid data with ISO week calculation
- **POST `/api/habits/evaluate`**: Generates AI evaluation using Gemini 3 with mentor persona
  - Checks cache first to avoid redundant API calls
  - Scolds if score < 90%, praises if >= 90%
  - Returns typewriter-ready formatted text
- **PUT `/api/habits/{habit_id}`**: Update habit settings including targets

#### Frontend Visualization (ApexCharts)
- **Monthly Grid**: 31-column grid showing habit completion per day (✓ = done, red = missed, gray = future)
- **Weekly Grid**: 7-column grid for ISO week view
- **Sparkline Chart**: Area chart showing daily completion trend across the month/week
- **Donut Chart**: Completed vs Missed ratio with percentage display
- **Progress Bars**: Per-habit progress with category-colored fills
- **Stats Cards**: Overall score, total completed, active habits, best streak

#### AI Report Card
- **Generate Button**: Triggers Gemini 3 evaluation for current period
- **Typewriter Effect**: Streams AI response character by character
- **Scolding Mode**: Red-tinted card when score < 90%
- **Praise Mode**: Green-tinted card when score >= 90%
- **Cache System**: Evaluations cached per period to save API costs

#### Filter System
- **Monthly View**: Month dropdown (Jan-Dec) + Year dropdown (current - 2 years)
- **Weekly View**: Year dropdown + Week dropdown (1-53)
- **AJAX Loading**: Filter changes trigger data reload without page refresh

#### UI/UX Improvements
- **Dark Mode**: Futuristic dark theme with glass morphism effects
- **Category Colors**: Gym (red), Study (blue), Game (purple), Work (orange), Health (teal), General (indigo)
- **Responsive**: Mobile-friendly grid with horizontal scroll
- **Animations**: Fade-in effects, hover states, pulse animations

### Files Changed
- `kuro_backend/daily_habits_db.py`: Complete V2.0 refactor with new schema and analytics functions
- `main.py`: Added 4 new API endpoints for V2.0
- `web_interface/templates/daily_habits.html`: Complete rewrite with ApexCharts, grid visualization, AI Report Card

---

# Kuro AI V3.1 Official - Changelog

**Release Date:** 2026-04-06
**Version:** 3.1.0
**Codename:** "Compliance Knowledge Base Integration"

---

## V3.1.0 - Compliance Knowledge Base Integration (2026-04-06)

### Major Upgrade: Golden Memory Tier for Compliance

#### Multimodal Ingestion Pipeline
- **PROBLEM**: 25 ISO/compliance PDFs in `/home/kuro/ComplianceDoc` not being used as knowledge source
- **SOLUTION**: Dedicated ingestion pipeline with OCR support for scanned documents
- **Implementation**:
  - `extract_pdf_text()`: Handles both text-based and scanned PDFs
  - `_ocr_page_with_gemini()`: Uses Gemini 3 Flash multimodal vision for OCR on scanned pages
  - Triggers OCR when >30% of pages are scanned (low text extraction)
  - 2x resolution pixmap for better OCR accuracy
  - Max 100 pages per PDF, 20 pages for OCR (RAM/API cost protection)

#### Dedicated Compliance ChromaDB Collection
- **New Collection**: `compliance_standards` in separate `kuro_compliance_chroma/` directory
- **Isolation**: Compliance data completely separate from regular chat memory
- **Chunking Rule**: Each chunk prefixed with `[COMPLIANCE_STANDARD: {ISO_NAME}] | [SCOPE: {Scope_Klausul}]`
- **Clause-Aware Chunking**: Attempts to split by clause boundaries (e.g., "5.1.2", "A.8.1.3")
- **Larger Chunks**: 2000 chars with 300 char overlap (vs 1500/200 for regular memory)

#### Compliance Context Generation
- **Global Summary**: Gemini 3 generates ISO name, scope, summary, and key clauses for each document
- **Metadata Extraction**: Identifies ISO standard name automatically from content
- **JSON Response**: Structured metadata for each document including clause numbers

#### Search Weighting/Boosting
- **Compliance Keywords**: 25+ keywords trigger boosted search (compliance, audit, ISO, A.5, A.8, etc.)
- **Boosted Results**: 8 results for compliance queries (vs 5 for regular)
- **Dedicated Search**: `search_compliance_base()` searches only compliance_standards collection
- **Formatted Output**: Results include ISO name, clause numbers, and relevance scores

#### Memory Injection
- **New Memory Tier**: "compliance" section added to memory injection
- **Format**: `[COMPLIANCE KNOWLEDGE BASE - SUMBER RESMI ISO/STANDAR]`
- **Conditional**: Only injected when query matches compliance keywords
- **Logging**: `[COMPLIANCE_BOOST]` log entry when compliance data is injected

### Maintenance Script
- **New Script**: `maintenance/rebuild_compliance_base.py`
- **Options**:
  - `--directory PATH`: Custom compliance document directory
  - `--stats`: Show current compliance database statistics
  ---clear`: Clear existing database before ingestion
  - `--dry-run`: List files without processing
- **Security**: Only reads from specified directory, never copies files
- **RAM Protection**: 2 files per batch, 3-second delay between batches

### API Endpoints Added
- **POST `/api/compliance/ingest`**: Trigger compliance batch ingestion (with optional `clear` parameter)
- **GET `/api/compliance/stats`**: Compliance knowledge base statistics
- **GET `/api/compliance/search`**: Search compliance knowledge base with query parameter

### Security & Git Protection
- **External Directory**: Compliance docs remain in `/home/kuro/ComplianceDoc` (NOT copied to project)
- **.gitignore Updated**: Added `compliance_cache/`, `kuro_compliance_chroma/`, `*.compliance.db`
- **Read-Only Access**: Script only reads files, never modifies source directory

### Documents Indexed (25 PDFs)
- ISO 27001:2022, ISO 27002:2022, ISO 27005:2022, ISO 27017:2015, ISO 27018:2019
- ISO 27031:2025, ISO 27037:2012, ISO 27037:2012 (SNI), ISO 27557:2022
- ISO 27701:2019, ISO 27701:2025
- ISO 19011:2018, ISO 19944-1:2020, ISO 20000-1:2018
- ISO 22301:2019, ISO 22317:2021, ISO 22331:2018
- ISO 23894:2022, ISO 38507:2022, ISO 42001:2023, ISO 42001:2024 (OCR)
- BS ISO 29134:2020, GDPR, UU Nomor 27 Tahun 2022

### Files Changed
- **MODIFIED**: `.gitignore` - Added compliance cache exclusions
- **MODIFIED**: `kuro_backend/memory_manager.py` - Added 600+ lines of compliance ingestion code
- **MODIFIED**: `main.py` - Added 3 new compliance API endpoints
- **NEW**: `maintenance/rebuild_compliance_base.py` - Maintenance script for manual rebuilds

### Usage Examples
```bash
# Rebuild compliance base (clear and re-ingest all)
python maintenance/rebuild_compliance_base.py --clear

# Check current stats
python maintenance/rebuild_compliance_base.py --stats

# API trigger
curl -X POST https://192.168.18.84:8443/api/compliance/ingest -F "clear=true" -b "kuro_access_token=..."

# Search compliance
curl "https://192.168.18.84:8443/api/compliance/search?query=access+control+A.8"
```

---

# Kuro AI V3.0 Official - Changelog

**Release Date:** 2026-04-06
**Version:** 3.0.0
**Codename:** "Gemini 3 Flash Engine & Contextual RAG Upgrade"

---

## V3.0.0 - Gemini 3 Flash Engine & Contextual RAG (2026-04-06)

### Major Upgrade: Contextual Retrieval Architecture

#### Gemini 3 Flash Engine
- **Model**: Upgraded to `gemini-3-flash-preview` as PRIMARY_MODEL and CLASSIFIER_MODEL
- **Configuration**: Verified in `config.py` and `.env` (MODEL_NAME="gemini-3-flash-preview")
- **Benefits**: Improved reasoning, better context understanding, faster response times
- **Version String**: Updated to "V3.0 Official - Contextual RAG"

#### Contextual Ingestion (Memory Manager V3.0)
- **PROBLEM**: Old ChromaDB entries lacked file-level context, causing poor retrieval accuracy
- **SOLUTION**: Gemini 3 generates global file context before chunking, then prepends it to every chunk
- **Implementation**:
  - `generate_file_context()`: Sends first 100k chars to Gemini 3, gets 1-2 sentence dense description
  - `chunk_text_with_context()`: Enriches each chunk with format `[FILE_CONTEXT: {deskripsi}] | [CHUNK_CONTENT: {isi_asli_chunk}]`
  - `ingest_file_contextual()`: Main function combining context generation + chunking + upsert
- **Example Context**: "Ini adalah dokumen Kebijakan Keamanan Informasi PT Medco tahun 2026 yang fokus pada kontrol akses fisik dan logis sesuai ISO 27001:2022 Annex A.5 dan A.8."

#### Re-Indexing System
- **New API**: `POST /api/memory/reindex` - Triggers full ChromaDB cleanup and re-indexing
- **Process**:
  1. Deletes all existing entries from ChromaDB (mass cleanup)
  2. Reads files from `/uploaded_files` directory
  3. Processes files in batches of 5 (MAX_FILES_PER_BATCH)
  4. Generates context for each file using Gemini 3
  5. Chunks with context injection and upserts to ChromaDB
  6. 2-second delay between batches (RAM protection)
- **Response**: Returns files processed, total chunks, contexts generated, and any errors

#### Query Expansion (Intelligent Retrieval)
- **PROBLEM**: Ambiguous queries like "ini maksudnya?" failed to find relevant context
- **SOLUTION**: Gemini 3 expands queries using recent conversation context
- **Implementation**:
  - `expand_query()`: Analyzes last 6 messages to identify what pronouns refer to
  - Detects ambiguous indicators: "ini", "itu", "dia", "mereka", "tersebut", "maksudnya"
  - Generates expanded search query optimized for semantic retrieval
  - Falls back to original query if expansion fails or query is already specific
- **Example**: "ini maksudnya?" + context about ISO 27001 → "ISO 27001 access control policy requirements and implementation details"

#### Enhanced Search Function
- **New Function**: `search_long_term_contextual()` - Combines query expansion with contextual retrieval
- **Features**:
  - Automatically expands ambiguous queries
  - Extracts clean chunk content (removes context prefix for display)
  - Preserves anti-VCT bias filtering
  - Returns top_k most relevant results

### Resource Protection (6GB RAM Systems)

#### Batch Processing
- **MAX_FILES_PER_BATCH**: 5 files per batch to prevent OOM
- **BATCH_DELAY_SECONDS**: 2-second delay between batches
- **CHUNK_SIZE**: 1500 characters per chunk with 200 char overlap
- **CONTEXT_MAX_CHARS**: 100k character limit for context generation input
- **Batch Insert**: 100 chunks per ChromaDB insert operation

#### Memory Safeguards
- Text truncated to 100k chars before context generation
- Context descriptions capped at 300 characters
- Progress logging for large files during batch processing
- Graceful error handling with fallback to original query

### API Endpoints Added
- **POST `/api/memory/reindex`**: Trigger contextual re-indexing of uploaded files
- **GET `/api/memory/stats`**: Enhanced memory statistics (unchanged but documented)

### Files Changed
- **MODIFIED**: `kuro_backend/config.py` - Updated header to V3.0, verified gemini-3-flash-preview
- **MODIFIED**: `kuro_backend/core.py` - Updated version string, passes recent_messages for query expansion
- **MODIFIED**: `kuro_backend/memory_manager.py` - Added 6 new functions for Contextual RAG (~400 lines)
- **MODIFIED**: `main.py` - Added `/api/memory/reindex` and `/api/memory/stats` endpoints

### Architecture Changes
- **Before**: ChromaDB stored raw chunks without file context → poor retrieval for ambiguous queries
- **After**: Every chunk enriched with Gemini-generated file context → superior retrieval accuracy
- **Query Flow**: User query → Query Expansion (if ambiguous) → Contextual Search → Relevant results

### Security & Compliance
- No changes to authentication or authorization
- Contextual RAG maintains existing anti-VCT bias filtering
- Memory decay and anti-hallucination protocols preserved

---

# Kuro AI V2.1.1 Official - Changelog

**Release Date:** 2026-04-05
**Version:** 2.1.1
**Codename:** "Cookie-Based Auth & Telegram Bot Rescue"

---

## V2.1.1 - Critical Refactor: Cookie-Based JWT & Telegram Bot Fix (2026-04-05)

### Critical Fixes

#### Cookie-Based JWT Authentication (Replaced localStorage)
- **PROBLEM**: localStorage-based auth caused redirect loops because browser navigation doesn't send Authorization headers
- **SOLUTION**: Switched to HttpOnly cookies for JWT token storage
- **Implementation**:
  - `response.set_cookie(key="kuro_access_token", value=f"Bearer {token}", httponly=True, secure=True, samesite="lax")`
  - Browser automatically sends cookies with every request
  - No JavaScript token handling needed
  - More secure: JavaScript cannot access HttpOnly cookies (XSS protection)

#### Middleware Refactor (No More Redirect Loops)
- **PROBLEM**: Middleware was checking Authorization header on HTML page requests, causing infinite redirect loops
- **SOLUTION**: Simplified middleware to only protect `/api/*` endpoints
- **New Architecture**:
  - HTML pages (`/`, `/login`, `/compliance`, etc.) are served directly
  - Backend middleware checks cookie for auth status
  - If no valid cookie → redirect to `/login`
  - If valid cookie → serve dashboard
  - API endpoints require valid cookie token

#### Telegram Bot Rescue (Main Thread Requirement)
- **PROBLEM**: `set_wakeup_fd only works in main thread of the main interpreter`
- **ROOT CAUSE**: `python-telegram-bot` v20+ requires main thread for asyncio event loop
- **SOLUTION**: Swapped thread assignment:
  - **Before**: Bot in daemon thread, FastAPI in main thread → bot crashed
  - **After**: FastAPI in daemon thread, Bot in main thread → both work
- **Verification**: Bot polling returns HTTP 200 OK consistently

#### Frontend Cleanup
- Removed all localStorage token handling from `app.js`
- Removed client-side auth check script from `index.html`
- Removed `checkExistingSession()` from `login.html`
- Simplified `authFetch()` to use `credentials: 'include'` for automatic cookie sending
- Backend now handles all redirect logic

#### SSL/mkcert Setup
- Installed `libnss3-tools` and `mkcert v1.4.4`
- Generated trusted certificate for `192.168.18.84`, `localhost`, `127.0.0.1`
- Certificates stored in `/home/kuro/projects/kuro/certs/`
- FastAPI configured for HTTPS on port 8443

#### Dependency Fixes
- Downgraded `bcrypt` from 5.0.0 to 4.0.1 (passlib compatibility)
- Installed `python-jose[cryptography]` and `passlib[bcrypt]` in venv

### Files Changed
- **MODIFIED**: `main.py` - Cookie-based JWT, simplified middleware, thread swap for bot
- **MODIFIED**: `web_interface/templates/login.html` - Removed localStorage, cookie auto-handled
- **MODIFIED**: `web_interface/templates/index.html` - Removed client-side auth check
- **MODIFIED**: `web_interface/static/js/app.js` - Simplified auth helpers, no token handling
- **NEW**: `certs/cert.pem` - SSL certificate
- **NEW**: `certs/key.pem` - SSL private key
- **MODIFIED**: `requirements.txt` - Added `python-jose[cryptography]`, `passlib[bcrypt]`

### Security Improvements
- **HttpOnly Cookies**: JavaScript cannot access tokens (XSS protection)
- **Secure Flag**: Cookies only sent over HTTPS
- **SameSite=Lax**: CSRF protection
- **No Client-Side Token Storage**: Eliminates localStorage XSS attack vector

---

## V2.1.0 - Secure Authentication & Brute Force Protection (2026-04-05)

### New Features

#### Secure Authentication System
- **JWT Token Authentication**: Implemented OAuth2PasswordBearer with JWT tokens
- **Token Duration**: 12-hour session validity (configurable via `JWT_EXPIRATION_HOURS`)
- **Password Hashing**: Using `passlib[bcrypt]` for secure password storage
- **No Plain-Text Passwords**: Password stored as bcrypt hash in `.env`

#### Brute Force Protection (The Gatekeeper)
- **Failed Attempt Tracking**: SQLite-based login attempt tracker
- **Lockout Rule**: 3 failed attempts → 15-minute account lockout
- **Clear Error Messages**: "Terlalu banyak percobaan login. Akun dikunci selama 15 menit untuk keamanan."
- **Countdown Timer**: Real-time lockout countdown on login page

#### Login Page (Glassmorphism Design)
- **New Route**: `/login` - Beautiful glassmorphic login form
- **Show/Hide Password**: Toggle password visibility
- **Remember Me**: Persistent session via HttpOnly cookie
- **Animated Background**: Gradient animation with floating particles
- **Security Badge**: ISO 27001 compliant authentication indicator

#### Protected Routes
- **Middleware**: HTTP middleware checks JWT cookie for all routes
- **Auto-Redirect**: Unauthenticated users redirected to `/login`
- **Cookie-Based Auth**: Browser automatically sends cookies with requests
- **Logout Button**: Added to header with user info display

### Files Changed
- **NEW**: `kuro_backend/auth_db.py` - Authentication database for failed attempts tracking
- **NEW**: `web_interface/templates/login.html` - Login page with glassmorphism design
- **MODIFIED**: `main.py` - Added JWT auth, login endpoint, middleware, logout
- **MODIFIED**: `web_interface/static/js/app.js` - Simplified auth helpers for cookie-based auth
- **MODIFIED**: `web_interface/templates/index.html` - Added user info & logout button
- **MODIFIED**: `.env` - Added `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`, `JWT_SECRET_KEY`
- **MODIFIED**: `requirements.txt` - Added `python-jose[cryptography]`, `passlib[bcrypt]`

### Security Compliance (ISO 27001)
- **A.9.4.2**: Secure log-on procedures implemented
- **A.9.5.1**: Information access restriction via JWT
- **A.10.1.1**: Cryptographic controls (bcrypt + JWT)
- **A.12.4.1**: Event logging (login attempts recorded)

### Default Credentials
- **Username**: `Pantronux`
- **Password**: `Noobcry17!` (stored as bcrypt hash)

---

# Kuro AI V2.0.1 Official - Changelog

**Release Date:** 2026-04-05
**Version:** 2.0.1
**Codename:** "Supreme Accuracy & Logic Refinement"

---

## V2.0.1 - Critical Engine Repair (2026-04-05)

### Critical Fixes

#### Model Deprecation Fix
- **REPLACED**: `gemini-2.0-flash` → `gemini-3-flash` (deprecated model was causing 404 errors)
- Added `PRIMARY_MODEL` and `CLASSIFIER_MODEL` config variables in `config.py`
- All model references now use centralized config variables

#### Error Handling for API Responses
- Added validation in `_classify_fact_with_llm`:
  - Checks for empty response text
  - Validates JSON structure before parsing
  - Logs `Critical: Classifier Model Failed` on errors
  - Falls back to safe mode (`temporary`, `decay_exempt: False`)

#### Context Priority & Anaphora Resolution
- Added `[ACTIVE_CONVERSATION_CONTEXT - PRIORITY 1]` injection in every prompt
- Added `get_last_topic()` function for automatic topic extraction
- Added `[LAST_TOPIC: ...]` context for pronoun resolution
- System instruction now enforces: "Context First, Memory Second"

#### Chain of Thought Enforcement
- Added explicit thinking steps to system instruction:
  1. Analyze Master's intent
  2. Check active conversation context for pronouns
  3. Verify file existence with `os.path.exists()`
  4. Check memory (Tier 1 > Tier 2 > Tier 3)
  5. Cross-verify between SQLite and ChromaDB
  6. Provide accurate, verified answer

#### Negative Constraints & Hallucination Check
- Added strict rules:
  - "DILARANG berasumsi file ada jika os.path.exists() mengembalikan False"
  - "Jika tidak tahu, katakan tidak tahu"
  - "JANGAN mengarang fakta, data, atau referensi klausul"
  - "Selalu verifikasi silang antara Memori Tier-1 dan Tier-2"

#### Temporal & Versioning Awareness
- Injected `current_date` dynamically into every prompt
- Added `[KURO_VERSION: V2.0.1 Official - {date}]` to system instruction
- Kuro now aware of its version and current date

---

## V2.0.0 - Major Release (2026-04-05)

### New Features

#### 1. Trinity Persona System
- **Casual Persona**: Friendly, relaxed tone without technical jargon
- **IT Consultant Persona**: GRC/ISO expert with citation rules and structured analysis
- **IT Support Persona**: DevOps-focused with code analysis and log reading capabilities
- Dynamic persona switching via UI dropdown with API persistence
- Persona state saved to `master_profile.json`

#### 2. Hardware Sentinel
- Automated hardware monitoring with dynamic intervals:
  - **Work hours (08:00-16:00)**: Check every 2 hours
  - **Off-hours**: Check every 4 hours
- Metrics monitored: CPU%, RAM%, Disk%, Network I/O
- Alert thresholds: RAM > 90%, CPU > 85%, Disk > 85%
- Telegram notifications for critical alerts

#### 3. Log Rotation & Cleanup
- `TimedRotatingFileHandler` with midnight rotation
- 7-day log retention (`kuro_butler.log.YYYY-MM-DD`)
- Automated artifact cleanup at midnight (14-day retention)
- Log storage usage displayed in System Health UI

#### 4. Memory V2.1 Anti-Hallucination
- Semantic Upsert with similarity search (>0.85 threshold)
- Categorical Fact Tagging (identity/preference/goal/schedule/temporary)
- Smart Decay respecting `decay_exempt` flags
- Temporal Grounding with timestamp injection
- Master Profile Override Layer (Tier 3 = absolute truth)
- Auto-migration of repeated facts to JSON

### Bug Fixes

#### PHASE 1: SDK v3 Consistency
- Verified 100% `google-genai` v3 protocol usage
- All API calls use `client.models.generate_content`
- All configs use `types.GenerateContentConfig`

#### PHASE 1: Path Integrity
- Standardized `PROJECT_ROOT` using `os.path.abspath()`
- All file interactions use absolute paths

#### PHASE 2: Memory Relevancy
- Context ranking with relevance threshold (distance <= 0.5)
- Anti-VCT bias: VCT data only returned for VCT-specific queries
- Low-relevance facts filtered out before prompt injection

#### PHASE 2: Physical Validation
- `os.path.exists()` checks before all file operations
- Proper error messages for missing files/folders

#### PHASE 4: Database Safety
- `try-except-finally` pattern on all database operations
- Guaranteed `conn.close()` in `finally` blocks
- WAL journal mode for better concurrency

#### PHASE 4: ChromaDB Optimization
- Memory-efficient queries (no full collection loading)
- Distance-based filtering at query time

### Infrastructure
- Service runs at ~112MB RAM (below 150MB limit)
- APScheduler for background tasks (reminders, habits, hardware sentinel)
- Telegram bot with recovery polling

---

## V1.x - Previous Versions

### V1.5 - PDF & Document Support
- PDF summarization with `pdfplumber`
- Universal document support (DOCX, XLSX, PPTX)
- Text chunking for large documents

### V1.4 - Reminder & Habit System
- APScheduler-based reminder notifications
- Daily habit tracking with 8 PM reports
- Midnight habit reset automation

### V1.3 - Compliance Module
- ISO 27001, NIST 800-53, GDPR compliance tracking
- Evidence matrix and audit trail
- Cross-mapping between standards

### V1.2 - Memory System
- 3-tier cognitive memory (SQLite, ChromaDB, JSON)
- Short-term buffer (last 20 interactions)
- Semantic long-term memory with embeddings
- Structured master profile

### V1.1 - Web Dashboard
- Glassmorphism UI with Tailwind CSS
- Dark mode support
- Chat history persistence
- System status modal

### V1.0 - Initial Release
- FastAPI backend
- Telegram bot integration
- Google GenAI SDK v3 integration
- Basic chat functionality

---

## Contributors
- **Master Irfan**: Product Owner & IT Security Consultant
- **Roo**: Senior System Architect & Code Implementation

## Technical Stack
- **Backend**: Python 3.10+, FastAPI, google-genai v3
- **Database**: SQLite, ChromaDB
- **Frontend**: Tailwind CSS, Vanilla JS, Lucide Icons
- **Infrastructure**: Proxmox VM (4GB RAM), systemd service
- **Notifications**: Telegram Bot API
