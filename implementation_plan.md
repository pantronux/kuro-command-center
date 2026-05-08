# Antigravity Prompt — Kuro AI V1.0.0 Beta 5 Hotfix
## "Sovereign Shield" — Automated Backup & Data Safety System

---

## ⚠️ MANDATORY FIRST STEP: Read Implementation Plan Before Any Code

**Context dari insiden**: Test suite Beta 5 (`test_chat_session_features.py`)
tidak menggunakan `tmp_path` isolation — operasi `DELETE` dari test langsung
menghantam `kuro_chat_history.db` production, menghapus seluruh 356 chat messages.
`_init_db_locked()` tidak membuat pre-migration snapshot sehingga tidak ada
rollback point. Insiden ini yang mendorong sprint ini.

**Do NOT write any code until the Implementation Plan di bawah dikonfirmasi.**

---

# SECTION 1 — IMPLEMENTATION PLAN (Review Before Execution)

## 1.0 Apa yang Perlu Di-backup (Inventory Lengkap)

Berdasarkan SYSTEM_MAP.md, berikut seluruh data kritikal Kuro:

### Tier 1 — CRITICAL (data hilang = tidak bisa recover)
| Asset | Path | Frekuensi Mutasi |
|---|---|---|
| `kuro_chat_history.db` | `{WORKING_DIR}/` | Per-message (tinggi) |
| `kuro_short_term.db` | `{WORKING_DIR}/` | Per-turn (sangat tinggi) |
| `kuro_auth.db` | `{WORKING_DIR}/` | Per-login (rendah) |
| `kuro_finances.db` | `{WORKING_DIR}/` | Per-ticker update (medium) |
| `kuro_intelligence.db` | `{WORKING_DIR}/` | Nightly (rendah) |
| `master_profile.json` | `{WORKING_DIR}/` | Per-profile update (sangat rendah) |
| `kuro_memory.json` | `{WORKING_DIR}/` | Per-memory write (medium) |
| `kuro_chromadb/` | `{WORKING_DIR}/` | Per-turn (medium) |

### Tier 2 — IMPORTANT (bisa diregenerasi tapi mahal)
| Asset | Path | Frekuensi Mutasi |
|---|---|---|
| `kuro_compliance.db` | `{WORKING_DIR}/` | Jarang |
| `kuro_habits.db` | `{WORKING_DIR}/` | Harian |
| `kuro_reminders.db` | `{WORKING_DIR}/` | Per-event |
| `phoenix_data/phoenix.db` | `{WORKING_DIR}/phoenix_data/` | Per-trace |
| `uploaded_files/` | `{WORKING_DIR}/` | Per-upload |
| `.archive/` | `{WORKING_DIR}/` | Nightly retention |

### Tier 3 — RECOVERABLE (bisa diregenerasi dari source)
| Asset | Kenapa bisa recover |
|---|---|
| `logs/` | Informatif saja, bukan data operasional |
| `certs/` | Bisa di-regenerate dengan `openssl` |

### Yang TIDAK perlu di-backup
- `kuro_chromadb/` versi lama — Mem0 adalah source of truth
- `phoenix_data/phoenix.db-wal`, `.db-shm` — WAL checkpoint files
- `venv/` — re-installable dari `requirements.txt`

---

## 1.1 Objective

Implementasikan **3 lapis proteksi**:

1. **Pre-migration snapshot** — `_init_db_locked()` di setiap `*_db.py`
   membuat snapshot sebelum `ALTER TABLE` dijalankan.
2. **Scheduled automated backup** — APScheduler job yang berjalan nightly
   mem-backup semua Tier 1 + Tier 2 assets ke `backups/` directory terstruktur.
3. **Test isolation enforcement** — `conftest.py` global fixture yang
   meng-intercept semua `*_db.py` `DB_PATH` sehingga test tidak pernah menyentuh
   production DB.

---

## 1.2 Scope of Files Changed

| File | Change Type | Reason |
|---|---|---|
| `kuro_backend/backup_manager.py` | **NEW** | Core backup engine |
| `kuro_backend/chat_history.py` | **Targeted** | Pre-migration snapshot hook |
| `kuro_backend/auth_db.py` | **Targeted** | Pre-migration snapshot hook |
| `kuro_backend/finance_db.py` | **Targeted** | Pre-migration snapshot hook |
| `kuro_backend/intelligence_db.py` | **Targeted** | Pre-migration snapshot hook |
| `kuro_backend/memory_manager.py` | **Targeted** | Pre-migration snapshot hook |
| `kuro_backend/config.py` | **Additive** | New backup env keys |
| `main.py` | **Additive** | Register nightly backup APScheduler job + new API routes |
| `conftest.py` | **Major fix** | Global DB isolation fixture untuk semua tests |
| `tests/test_backup_manager.py` | **NEW** | Test coverage for backup system |
| `.gitignore` | **Update** | Ensure `backups/` excluded from VCS |
| `SYSTEM_MAP.md` | **Update** | Document new module, routes, env keys |
| `CHANGELOG.md` | **Additive** | Beta 5 Hotfix entry |

---

## 1.3 Clean Tree (Delta)

```
kuro_backend/
│   └── backup_manager.py            # [NEW] — core backup engine
main.py                              # [MODIFIED] — backup scheduler job + API routes
kuro_backend/
│   ├── chat_history.py              # [MODIFIED] — pre-migration snapshot
│   ├── auth_db.py                   # [MODIFIED] — pre-migration snapshot
│   ├── finance_db.py                # [MODIFIED] — pre-migration snapshot
│   ├── intelligence_db.py           # [MODIFIED] — pre-migration snapshot
│   ├── memory_manager.py            # [MODIFIED] — pre-migration snapshot
│   └── config.py                    # [MODIFIED] — backup env keys
conftest.py                          # [MODIFIED] — global DB isolation fixture
tests/
│   └── test_backup_manager.py       # [NEW] — backup system tests
backups/                             # [NEW DIR] — created at runtime, git-ignored
│   ├── daily/
│   │   └── 2026-05-08/
│   │       ├── kuro_chat_history.db.gz
│   │       ├── kuro_short_term.db.gz
│   │       ├── kuro_auth.db.gz
│   │       ├── kuro_finances.db.gz
│   │       ├── kuro_intelligence.db.gz
│   │       ├── master_profile.json.gz
│   │       ├── kuro_memory.json.gz
│   │       └── backup_manifest.json
│   ├── pre_migration/
│   │   └── kuro_chat_history.db.pre_migration_20260508_143022.gz
│   └── weekly/
│       └── 2026-W19/
.gitignore                           # [MODIFIED] — add backups/, *.db, *.db-*
```

---

## 1.4 Flow Diagrams

### Flow 1 — Pre-Migration Snapshot

```
_init_db_locked() dipanggil
        │
        ▼
DB file exists di disk?
   │                │
  YES               NO
   │                └──► skip snapshot, lanjut CREATE TABLE
   ▼
backup_manager.snapshot_pre_migration(db_path)
        │
        ▼
Copy DB ke: backups/pre_migration/
  {db_name}.pre_migration_{YYYYMMDD_HHMMSS}.gz
        │
        ▼
Log: "Pre-migration snapshot: {path}" → kuro_sovereign.log
        │
        ▼
Lanjut ALTER TABLE / migrasi normal
        │
        ▼
Migrasi berhasil? ──NO──► Log error, snapshot masih ada untuk rollback
        │
       YES
        ▼
Hapus snapshots pre_migration > 7 hari
```

### Flow 2 — Nightly Scheduled Backup

```
APScheduler: 01:00 WIB daily
        │
        ▼
backup_manager.run_nightly_backup()
        │
        ├──► Tier 1 DB files (semua *.db)
        │         │
        │         ▼
        │    SQLite: VACUUM INTO '{backup_path}/{name}.db.gz'
        │    (WAL-safe copy via SQLite API, bukan shutil.copy)
        │
        ├──► JSON state files
        │         │
        │         ▼
        │    shutil.copy2 + gzip compress
        │
        ├──► kuro_chromadb/ (weekly only, bukan nightly — terlalu besar)
        │
        ├──► Write backup_manifest.json
        │         {
        │           "timestamp": "...",
        │           "files": [...],
        │           "total_size_mb": ...,
        │           "status": "success|partial|failed"
        │         }
        │
        ├──► Prune: hapus daily backups > KURO_BACKUP_RETAIN_DAYS hari
        │
        ├──► Log summary ke kuro_sovereign.log
        │
        └──► Jika status "failed": kirim Telegram alert
                  "⚠️ Kuro backup FAILED: {error}"
```

### Flow 3 — Test DB Isolation (conftest.py fix)

```
pytest session mulai
        │
        ▼
conftest.py: session-scoped fixture 'isolated_db_paths'
        │
        ▼
Untuk setiap DB module (chat_history, auth_db, finance_db, dll):
  - monkeypatch modul-level DB_PATH → tmp_path / "{db_name}.db"
  - panggil init_db() pada tmp path baru
        │
        ▼
Test berjalan dengan DB di tmp_path (bukan production)
        │
        ▼
Test selesai → tmp_path otomatis dihapus oleh pytest
        │
        ▼
Production DB tidak tersentuh sama sekali
```

---

## 1.5 Database — Schema Addition

### New Table: `backup_log` (→ `kuro_intelligence.db`)

Menyimpan audit trail setiap backup run — berguna untuk memantau
kesehatan backup sistem dari dashboard.

```sql
CREATE TABLE IF NOT EXISTS backup_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    backup_type     TEXT NOT NULL CHECK(backup_type IN
                    ('nightly', 'weekly', 'pre_migration', 'manual')),
    status          TEXT NOT NULL CHECK(status IN
                    ('success', 'partial', 'failed')),
    backup_path     TEXT NOT NULL,
    files_backed_up INTEGER NOT NULL DEFAULT 0,
    total_size_bytes INTEGER NOT NULL DEFAULT 0,
    duration_seconds REAL NOT NULL DEFAULT 0.0,
    error_message   TEXT DEFAULT NULL,
    started_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at    DATETIME DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_backup_log_started
ON backup_log(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_backup_log_type_status
ON backup_log(backup_type, status);
```

**New functions in `intelligence_db.py`**:
```python
log_backup_start(backup_type: str, backup_path: str) -> int  # returns id
log_backup_complete(log_id: int, status: str, files_count: int,
                    size_bytes: int, duration_s: float,
                    error: str | None = None) -> None
get_backup_history(limit: int = 30) -> list[dict]
get_last_backup_status() -> dict | None
```

---

## 1.6 New Module — `kuro_backend/backup_manager.py`

### Header Doc
```python
"""
Kuro AI V1.0.0 Beta 5 — Backup Manager
Purpose: Automated backup engine for all critical Kuro data assets.
Caller: main.py (APScheduler nightly job), *_db.py (pre-migration hook),
        /api/backup/* routes.
Dependencies: sqlite3, gzip, shutil, pathlib, kuro_backend.config,
              kuro_backend.intelligence_db.
Main Functions: run_nightly_backup, snapshot_pre_migration,
                run_manual_backup, get_backup_status, prune_old_backups.
Side Effects: Writes to backups/ directory. Reads all *.db files.
              Calls intelligence_db.log_backup_* for audit trail.
              Optionally sends Telegram alert on failure.
"""
```

### Public Functions

```python
def get_backup_dir() -> Path:
    """Returns resolved backups/ root directory, creating if needed."""

def snapshot_pre_migration(db_path: str | Path, label: str = "") -> Path | None:
    """
    Create a compressed snapshot of a DB file before schema migration.
    Called by every _init_db_locked() at startup.

    Args:
        db_path: Absolute path to the SQLite DB file.
        label: Optional label suffix (e.g. "chat_history").
    Returns:
        Path to snapshot file, or None if db_path doesn't exist yet.
    Raises: Never — all exceptions are caught and logged.
    """

async def run_nightly_backup() -> dict:
    """
    Main nightly backup job. Backs up all Tier 1 + Tier 2 assets.
    Uses SQLite VACUUM INTO for DB files (WAL-safe).
    Compresses output with gzip (level 6).
    Writes backup_manifest.json to the dated directory.
    Prunes daily backups older than KURO_BACKUP_RETAIN_DAYS.
    Logs to backup_log table in kuro_intelligence.db.
    Sends Telegram alert if status == 'failed'.

    Returns: {
        "status": "success|partial|failed",
        "backup_path": str,
        "files": list[str],
        "total_size_mb": float,
        "duration_seconds": float,
        "errors": list[str]
    }
    """

def run_manual_backup(label: str = "manual") -> dict:
    """
    Synchronous wrapper for manual backup trigger via API or CLI.
    Same logic as run_nightly_backup but backup_type='manual'.
    """

def get_backup_status() -> dict:
    """
    Returns status of last backup from backup_log table.
    Used by /api/backup/status endpoint.
    """

def prune_old_backups(retain_days: int | None = None) -> int:
    """
    Delete daily backup directories older than retain_days.
    Returns count of directories deleted.
    """

def _vacuum_into(source_db: Path, dest_path: Path) -> int:
    """
    Private: SQLite VACUUM INTO for WAL-safe backup.
    Returns file size in bytes.
    Must use a separate connection from the main app connection.
    """

def _compress_file(source: Path, dest: Path) -> int:
    """
    Private: gzip compress source file to dest.
    Returns compressed size in bytes.
    """
```

### DB Files to Backup (derived from config)

```python
BACKUP_TIER1 = [
    ("kuro_chat_history.db",   "sqlite"),
    ("kuro_short_term.db",     "sqlite"),
    ("kuro_auth.db",           "sqlite"),
    ("kuro_finances.db",       "sqlite"),
    ("kuro_intelligence.db",   "sqlite"),
    ("master_profile.json",    "json"),
    ("kuro_memory.json",       "json"),
]

BACKUP_TIER2 = [
    ("kuro_compliance.db",     "sqlite"),
    ("kuro_habits.db",         "sqlite"),
    ("kuro_reminders.db",      "sqlite"),
    ("phoenix_data/phoenix.db","sqlite"),
]

BACKUP_WEEKLY_DIRS = [
    ("kuro_chromadb/",         "directory"),  # only on Sunday
    ("uploaded_files/",        "directory"),  # only on Sunday
]
```

---

## 1.7 Pre-Migration Snapshot — Pattern untuk Semua `*_db.py`

Tambahkan di setiap `_init_db_locked()`, **sebelum** operasi `CREATE TABLE` atau
`ALTER TABLE` pertama:

```python
# Pre-migration safety snapshot (Beta 5 — Sovereign Shield)
try:
    from kuro_backend import backup_manager
    backup_manager.snapshot_pre_migration(DB_PATH, label="chat_history")
except Exception as _snap_err:
    logger.warning(f"Pre-migration snapshot skipped: {_snap_err}")
```

File yang perlu diupdate:
- `chat_history.py` → `_init_db_locked()`
- `auth_db.py` → `init_auth_db()`
- `finance_db.py` → `_init_db_locked()`
- `intelligence_db.py` → `init_db()`
- `memory_manager.py` → fungsi inisialisasi `kuro_short_term.db`

**Penting**: Import harus lazy (`try/except`) untuk menghindari circular import.
Label harus mencerminkan nama DB-nya.

---

## 1.8 APScheduler Registration (`main.py`)

Tambahkan di dalam `_start_intelligence_scheduler()`, setelah
`file_retention_cycle` job (02:00 WIB), sebelum `scheduler.start()`:

```python
from kuro_backend import backup_manager

async def _run_nightly_backup_job():
    result = await backup_manager.run_nightly_backup()
    if result["status"] == "failed":
        logger.error(f"[BACKUP] Nightly backup FAILED: {result['errors']}")
    else:
        logger.info(
            f"[BACKUP] Nightly backup OK — "
            f"{result['files_backed_up']} files, "
            f"{result['total_size_mb']:.1f} MB, "
            f"{result['duration_seconds']:.1f}s"
        )

_reminder_scheduler.add_job(
    _run_nightly_backup_job,
    "cron",
    hour=1,
    minute=0,
    id="nightly_backup",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
)
logger.info("Nightly backup job scheduled at 01:00 WIB.")
```

---

## 1.9 New API Routes (`main.py`)

Tambahkan setelah block routes `/api/evaluation/`:

| Method | Path | Function | Auth | Note |
|---|---|---|---|---|
| `GET` | `/api/backup/status` | `backup_status` | Admin only | Last backup info |
| `POST` | `/api/backup/run` | `trigger_manual_backup` | Admin only | Manual trigger |
| `GET` | `/api/backup/history` | `backup_history` | Admin only | Last 30 runs |

**`GET /api/backup/status`**: Calls `backup_manager.get_backup_status()`.
Returns last backup timestamp, status, file count, size.

**`POST /api/backup/run`**: Calls `backup_manager.run_manual_backup("manual")`.
Returns same dict as nightly job. Timeout: 120 seconds.

**`GET /api/backup/history`**: Calls `intelligence_db.get_backup_history(limit=30)`.

Semua 3 route menggunakan pattern `is_admin` check yang sama dengan
`/api/evaluation/summary` — pastikan konsisten.

---

## 1.10 `conftest.py` — Global Test DB Isolation Fix

Ini adalah **root cause fix** dari insiden. Implementasikan session-scoped
fixture yang meng-intercept semua DB paths sebelum test berjalan.

```python
# conftest.py — tambahkan fixture ini

import pytest
import importlib
from pathlib import Path

# Semua modul yang memiliki module-level DB_PATH variable
_DB_MODULES = [
    ("kuro_backend.chat_history", "DB_PATH", "kuro_chat_history.db"),
    ("kuro_backend.auth_db",      "DB_PATH", "kuro_auth.db"),
    ("kuro_backend.finance_db",   "DB_PATH", "kuro_finances.db"),
    ("kuro_backend.intelligence_db", "DB_PATH", "kuro_intelligence.db"),
    ("kuro_backend.compliance_db",   "DB_PATH", "kuro_compliance.db"),
]

@pytest.fixture(scope="function", autouse=True)
def isolate_all_dbs(tmp_path, monkeypatch):
    """
    CRITICAL SAFETY FIXTURE — autouse=True means it applies to EVERY test.

    Redirects all DB module paths to tmp_path so tests can never
    touch production databases. Also calls _reset_schema_ready_for_tests()
    on modules that expose it, and re-runs init_db() on the tmp path.
    """
    for module_name, path_attr, db_filename in _DB_MODULES:
        try:
            mod = importlib.import_module(module_name)
            test_db_path = str(tmp_path / db_filename)
            monkeypatch.setattr(mod, path_attr, test_db_path)

            # Reset schema cache so init_db() re-runs on new tmp path
            if hasattr(mod, "_reset_schema_ready_for_tests"):
                mod._reset_schema_ready_for_tests()
            elif hasattr(mod, "_SCHEMA_READY_FOR"):
                monkeypatch.setattr(mod, "_SCHEMA_READY_FOR", None)

            # Re-initialize schema on the tmp path
            if hasattr(mod, "init_db"):
                mod.init_db()
            elif hasattr(mod, "init_auth_db"):
                mod.init_auth_db()
        except Exception as e:
            # Non-fatal: log but don't fail the fixture
            import logging
            logging.getLogger("conftest").warning(
                f"DB isolation setup failed for {module_name}: {e}"
            )

    # Also redirect memory_manager's short_term DB
    try:
        from kuro_backend import memory_manager
        monkeypatch.setattr(
            memory_manager,
            "SHORT_TERM_DB_PATH",
            str(tmp_path / "kuro_short_term.db")
        )
        if hasattr(memory_manager, "_reset_schema_ready_for_tests"):
            memory_manager._reset_schema_ready_for_tests()
        memory_manager.init_short_term_db()
    except Exception as e:
        import logging
        logging.getLogger("conftest").warning(f"memory_manager isolation failed: {e}")

    yield  # test runs here

    # tmp_path auto-cleanup by pytest after yield
```

**Catatan penting untuk Antigravity**:
- Fixture ini `autouse=True` di scope `function` — berlaku untuk SEMUA test
  tanpa perlu dekorasi eksplisit.
- Setiap test yang sebelumnya menggunakan `tmp_path` manual untuk DB harus
  diaudit — kemungkinan ada double-patching yang perlu dibersihkan.
- Existing tests yang sudah berjalan dengan benar tidak boleh regresi.

---

## 1.11 Config.py — New Env Keys

```python
# Backup system
KURO_BACKUP_ENABLED: bool = True
KURO_BACKUP_DIR: str = "./backups"
KURO_BACKUP_RETAIN_DAYS: int = 14        # daily backups retained for 14 days
KURO_BACKUP_WEEKLY_RETAIN_WEEKS: int = 8 # weekly backups retained for 8 weeks
KURO_BACKUP_PRE_MIGRATION_RETAIN_DAYS: int = 7
KURO_BACKUP_COMPRESS_LEVEL: int = 6      # gzip level 1-9
KURO_BACKUP_ALERT_ON_FAILURE: bool = True  # send Telegram alert if backup fails
```

---

## 1.12 `.gitignore` Updates

Pastikan baris-baris ini ada di `.gitignore`:

```gitignore
# Runtime databases — NEVER commit
*.db
*.db-wal
*.db-shm
*.db-backup*
*.db-recovery*
*.db-corrupted*
*.db.from_github
*.db.pre_migration*
*.db.gz

# Backup directory
backups/

# Vector stores
kuro_chromadb/

# Runtime state
master_profile.json
kuro_memory.json
phoenix_data/
uploaded_files/
.archive/
```

---

## 1.13 Tests — `tests/test_backup_manager.py`

```python
# Test cases:
test_snapshot_pre_migration_creates_gz_file()
test_snapshot_pre_migration_skips_if_db_not_exist()
test_snapshot_pre_migration_never_raises()  # exception safety
test_run_nightly_backup_backs_up_tier1()
test_run_nightly_backup_writes_manifest_json()
test_run_nightly_backup_logs_to_backup_log_table()
test_run_nightly_backup_partial_on_missing_file()  # missing file = partial not failed
test_prune_old_backups_deletes_old_dirs()
test_prune_old_backups_keeps_recent()
test_manual_backup_returns_success_dict()
test_get_backup_status_returns_last_run()
test_backup_dir_created_if_not_exists()
test_isolate_all_dbs_fixture_prevents_production_write()  # meta-test
```

---

# SECTION 2 — ANTIGRAVITY EXECUTION PROMPT

> Paste section ini ke Antigravity setelah Implementation Plan dikonfirmasi.

---

## Context: What Has Been Done

**V1.0.0 Beta 5 Hotfix — "Sovereign Shield"**.
Semua prior sprints (Beta 1–4 + Patch Runs + Beta 5 Chat features) complete.
Sprint ini adalah **hotfix wajib** sebelum deployment production.

**Root cause insiden**: `test_chat_session_features.py` tidak menggunakan `tmp_path`
isolation. `DELETE` dari test menghapus seluruh production `kuro_chat_history.db`.
356 messages hilang. Recovery parsial dari backup April 15.

Operating constraints (sama dengan semua sprint sebelumnya):
- Do NOT modify `*.db` files, `kuro_memory.json`, `master_profile.json`.
- Do NOT commit secrets.
- V7.2.2 Header Doc contract — update di setiap file yang disentuh.
- `pytest tests/ -v` zero failures setelah setiap batch perubahan.
- Asyncio-safe patterns throughout.
- Read SYSTEM_MAP.md (Beta 4) sebelum menulis kode apapun.

---

## Execution Order

### Step 1 — `config.py`: Tambahkan backup env keys (§1.11)

### Step 2 — `kuro_backend/backup_manager.py`: Buat modul baru (§1.6)

Implementasikan semua public functions. Untuk `_vacuum_into()`:
```python
def _vacuum_into(source_db: Path, dest_path: Path) -> int:
    """WAL-safe copy via SQLite VACUUM INTO."""
    import sqlite3
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(source_db))
    try:
        conn.execute(f"VACUUM INTO '{str(dest_path)}'")
        conn.commit()
    finally:
        conn.close()
    return dest_path.stat().st_size
```

Untuk JSON files, gunakan `shutil.copy2` bukan `VACUUM INTO`.

Untuk weekly ChromaDB backup: `shutil.copytree` dengan
`ignore=shutil.ignore_patterns('*.lock', '__pycache__')`.

### Step 3 — `intelligence_db.py`: Tambahkan `backup_log` table + 4 fungsi (§1.5)

### Step 4 — Pre-migration snapshot di semua `*_db.py` (§1.7)

File yang dimodifikasi: `chat_history.py`, `auth_db.py`, `finance_db.py`,
`intelligence_db.py`, `memory_manager.py`.

Pastikan lazy import pattern (`try/except`) digunakan untuk menghindari
circular import. Label snapshot harus mencerminkan nama DB.

### Step 5 — `main.py`: APScheduler job + 3 API routes (§1.8 + §1.9)

Backup job di 01:00 WIB, setelah file_retention_cycle (02:00).
Perhatikan urutan jam: backup (01:00) → retention (02:00) → evaluation (02:30).

### Step 6 — `conftest.py`: Global DB isolation fixture (§1.10)

**Ini adalah perubahan paling kritis sprint ini.**

Setelah menambahkan fixture `isolate_all_dbs`, jalankan full test suite:
```bash
pytest tests/ -v --tb=short 2>&1 | head -100
```

Jika ada test yang fail karena fixture conflict (double-patching), audit
test tersebut dan hapus manual `tmp_path` DB setup yang redundan.

### Step 7 — `.gitignore` update (§1.12)

Pastikan semua `.db*` patterns dan `backups/` terdaftar.
Jalankan `git status` untuk verifikasi tidak ada DB files yang ter-track.

### Step 8 — `tests/test_backup_manager.py`: New test file (§1.13)

### Step 9 — `SYSTEM_MAP.md` updates

**Clean Tree**: Tambahkan `kuro_backend/backup_manager.py` dan `backups/` directory.

**Module Map — Feature Services**: Tambahkan section baru:
```
### Backup & Safety
- [`kuro_backend/backup_manager.py`] — *public*: `run_nightly_backup`,
  `snapshot_pre_migration`, `run_manual_backup`, `get_backup_status`,
  `prune_old_backups`. WAL-safe SQLite backup via VACUUM INTO.
  Tier 1: chat_history, short_term, auth, finances, intelligence, JSON state.
  Tier 2: compliance, habits, reminders, phoenix.
  Weekly: chromadb/, uploaded_files/ (Sunday only).
```

**Module Map — DB Layer**: Update `intelligence_db.py` entry untuk mencantumkan
`backup_log` table dan 4 fungsi baru.

**Routes listing**: Tambahkan 3 route baru (§1.9).

**Env keys**: Tambahkan 6 backup keys baru (§1.11).

**DB table one-liners**: Tambahkan `backup_log` entry.

**Evolution & Core Milestones**: Tambahkan:
```
### V1.0.0 Beta 5 Hotfix Architecture Notes ("Sovereign Shield")
- **Pre-migration snapshot**: Semua *_db.py _init_db_locked() membuat
  compressed snapshot ke backups/pre_migration/ sebelum ALTER TABLE.
  Rollback tersedia secara otomatis untuk setiap migrasi schema.
- **Nightly automated backup** (01:00 WIB): backup_manager.run_nightly_backup()
  mem-backup semua Tier 1 + Tier 2 via SQLite VACUUM INTO (WAL-safe).
  Compressed gzip, retained 14 days daily / 8 weeks weekly.
  Audit trail di backup_log table (kuro_intelligence.db).
  Telegram alert otomatis jika backup gagal.
- **Test DB isolation (conftest.py)**: autouse fixture isolate_all_dbs
  me-redirect semua module-level DB_PATH ke tmp_path. Production DB
  tidak dapat disentuh oleh test suite manapun.
- **backup_log table** (kuro_intelligence.db): audit trail setiap backup run.
- **Root cause fix**: insiden hilangnya 356 chat messages akibat test
  contamination pada 2026-05-07 tidak dapat terulang.
```

**Risks section**: Update untuk menambahkan:
```
- **Backup storage**: backups/ directory tumbuh ~{DB_total_size}MB/hari.
  Monitor disk usage di VM. KURO_BACKUP_RETAIN_DAYS default 14 hari.
  Weekly backup (termasuk chromadb) bisa mencapai 500MB+.
```

### Step 10 — `CHANGELOG.md`

```markdown
## [1.0.0-beta.5-hotfix.1] - Sovereign Shield

### Critical Fix
- **Test DB isolation**: `conftest.py` now enforces `autouse=True` fixture
  `isolate_all_dbs` that redirects all `*_db.py` module-level `DB_PATH`
  variables to `tmp_path`. Production databases can no longer be touched
  by any test. Fixes incident where `test_chat_session_features.py` deleted
  356 production chat messages via `DELETE` cascade.

### Added
- **`kuro_backend/backup_manager.py`**: New backup engine with WAL-safe
  SQLite VACUUM INTO, gzip compression, tiered backup strategy
  (Tier 1 nightly, Tier 2 nightly, weekly dirs).
- **Nightly backup job** (01:00 WIB): APScheduler job backing up all
  critical data assets. Retained 14 days (daily) / 8 weeks (weekly).
- **Pre-migration snapshot**: All `_init_db_locked()` functions now create
  `backups/pre_migration/{name}.pre_migration_{ts}.gz` before any
  `ALTER TABLE` or schema change. Automatic rollback point for every migration.
- **`backup_log` table** (`kuro_intelligence.db`): Audit trail for every
  backup run with status, file count, size, duration, errors.
- **API routes**: `GET /api/backup/status`, `POST /api/backup/run`,
  `GET /api/backup/history` (Admin only).
- **Telegram alert**: Automatic notification if nightly backup fails.
- **`.gitignore` hardening**: All `*.db*` patterns, `backups/`, `kuro_chromadb/`,
  `master_profile.json`, `kuro_memory.json` explicitly excluded from VCS.
```

---

## Deliverables Checklist

- [ ] `config.py` — 6 new backup env keys
- [ ] `kuro_backend/backup_manager.py` — new module, all 6 public functions
- [ ] `intelligence_db.py` — `backup_log` table + 4 new functions
- [ ] `chat_history.py` — pre-migration snapshot hook in `_init_db_locked()`
- [ ] `auth_db.py` — pre-migration snapshot hook
- [ ] `finance_db.py` — pre-migration snapshot hook
- [ ] `intelligence_db.py` — pre-migration snapshot hook
- [ ] `memory_manager.py` — pre-migration snapshot hook
- [ ] `main.py` — nightly backup APScheduler job + 3 API routes
- [ ] `conftest.py` — `isolate_all_dbs` autouse fixture (CRITICAL)
- [ ] `.gitignore` — all DB and backup patterns added
- [ ] `tests/test_backup_manager.py` — 13 test cases passing
- [ ] `SYSTEM_MAP.md` — all sections updated
- [ ] `CHANGELOG.md` — hotfix entry at top
- [ ] Header Docs updated in every modified file
- [ ] `pytest tests/ -v` — zero failures, zero production DB contamination

---

*Reference: Kuro AI V1.0.0 Beta 4 "Sovereign Intelligence" + Beta 5 "Sovereign Chat".*
*Insiden: 2026-05-07, 356 chat messages hilang akibat test contamination.*
*Root cause confirmed: missing `tmp_path` isolation in `conftest.py`.*