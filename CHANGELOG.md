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
