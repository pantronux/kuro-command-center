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
- **REPLACED**: `gemini-2.0-flash` → `gemini-2.5-flash` (deprecated model was causing 404 errors)
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
