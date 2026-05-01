# Kuro AI V7.2.1 "Sovereign Leviathan" - Changelog

**Release Date:** 2026-04-29
**Version:** 7.2.1
**Codename:** "Sovereign Leviathan"

---

## V7.2.1 - Natural Agency: Auto-RAG Self-Correction Loop (2026-04-29)

### Summary
Implementation of an **Automated RAG (Self-RAG)** pattern to harden the perceptual
feedback loop of the retrieval layer. Kuro now actively grades its own memory
retrievals and attempts query-transformation loops if context is found to be
irrelevant or ambiguous, with a last-resort failover to web search.

### Highlights

- **New Auto-RAG Loop Topology:**
  `memory_retrieval_node → retrieval_grader_node ↺ query_transform_node → attention_filter_node`

- **Retrieval Grader (CRAG pattern):**
  - `retrieval_grader_node`: Uses `CLASSIFIER_MODEL` to evaluate the relevance of
    retrieved Mem0 context against `user_input`.
  - Grades: `relevant` (proceed), `ambiguous` (loop to transform), `irrelevant`
    (loop to transform).
  - Fast-path bypass if zero results are found.

- **Query Transformer & Failover:**
  - `query_transform_node`: Rewrites the original query into a more optimized
    search string for the next retrieval pass.
  - **Bounded Loop:** Maximum of 2 retries (`_RAG_MAX_RETRIES`) to prevent
    infinite token-burn.
  - **Serper Failover:** If retries are exhausted, the node triggers a `serper_search`
    (web search) to inject external grounding, then unblocks the pipeline by forcing
    `relevant` status.

- **Metacognitive Evidence Signal:**
  - `metacognitive_review_node` now incorporates `retrieval_grade`.
  - If a belief conflict is detected AND retrieval was low-quality, the reflective
    message explicitly warns the Master about the lack of solid evidential grounding.

- **State Updates:**
  - Added `retrieval_grade`, `retrieval_retry_count`, and `rewritten_query` to `KuroState`.

- **Multi-User Memory Isolation & Identity Hardening:**
  - **Context Bleed Prevention:** Updated `memory_coordinator.py` and `chat_history.py` to strictly enforce `username` isolation. This prevents User A (e.g., Faikhira) from accidentally seeing the session state or history of User B (Pantronux).
  - **Dynamic Identity Injection:** Refactored `personas.py` to use `{master_name}` placeholders. Kuro now dynamically adapts its self-identity to the logged-in user, greeting them correctly and scoping its purpose (e.g., as "Master Faikhira's Senior Auditor").
  - **Personalized Proactive Greetings:** Updated `proactive_greeting.py` to resolve the Master's name from the user registry for a more personalized "Welcome back" experience.

### Modified Files (V7.2.1)

| File | Change |
|---|---|
| `kuro_backend/memory_coordinator.py` | User-aware grounding and context retrieval |
| `kuro_backend/langgraph_core.py` | Username propagation + dynamic error messaging |
| `kuro_backend/personas.py` | `{master_name}` placeholder implementation |
| `kuro_backend/proactive_greeting.py` | Personalized dashboard greetings |
| `kuro_backend/memory_manager.py` | Strict `username` parameter in `query_memory` |
| `main.py` | User registry updates and session hardening |

---

# Kuro AI V7.2.0 "Natural Agency" - Changelog

## V7.2.0 - Natural Agency: Three-Tier Control System (2026-04-29)

### Summary
Architectural transition from a stimulus-driven processor to a **Natural Agency** model
based on Michael Tomasello's (2025) *"Natural Agency: From Intentional to Rational to
Social Agents"* framework. Kuro now operates across three hierarchical control tiers:
**T1 Executive** (inhibition + imaginative simulation), **T2 Metacognitive** (belief
revision + cognitive effort allocation), and **T3 Shared Agency** (joint commitments +
coordination partner protocol). All agency behaviour is gated to the `advisor`,
`consultant`, and `auditor` personas. Non-agency personas (`chill`, `tactical`,
`chancellor`) experience zero latency overhead via O(1) self-bypass.

### Highlights

- **New LangGraph Topology:** `reflection → supervisor → memory_retrieval →
  attention_filter → executive_monitor → metacognitive_review →
  [reflective_response | tool | response] → memory_extraction → END`

- **T1 — Executive / Intentional Agent:**
  - `attention_filter_node`: Classifies input intent into `dissertation`, `research`,
    `technical`, `administrative`, `off_track`, or `general` using pure-regex patterns
    (no LLM call).
  - `executive_monitor_node`: (a) **Inhibitory filter** — blocks bloatware-type or
    off-track impulsive requests when an agency persona is active, routing them to
    `reflective_response_node` instead of the LLM. (b) **Imaginative simulation** —
    generates two strategic drafts via `CLASSIFIER_MODEL`:
    - `advisor` / `consultant`: Draft A (Conservative) vs Draft B (Novel) — picks
      highest `novelty_score`.
    - `auditor`: Draft A (Pass/Safe) vs Draft B (Adversarial/Fail) — always selects
      Draft B to proactively surface risks.
  - Selected simulation strategy is injected into `response_node` as
    `[EXECUTIVE SIMULATION]` context block.

- **T2 — Metacognitive / Rational Agent:**
  - `cognitive_effort.py` (`kuro_backend/agency/`): Pure-regex effort allocator maps
    intent category to `low / medium / high`. High effort injects a 5-step
    dissertation-novelty CoT into the system prompt. Zero LLM calls.
  - `metacognitive_review_node`: Calls `memory_coordinator.evaluate_alignment()` to
    compare current input against `research_ledger` BRD commitments (`decision` +
    `novelty_point` kinds). If `alignment_score < KURO_ALIGNMENT_THRESHOLD` (default
    `0.35`), routes to `reflective_response_node` with a bilingual realignment message
    instead of answering directly.
  - `evaluate_alignment()` added to `memory_coordinator.py`: single-call
    `CLASSIFIER_MODEL` audit returning `{score, conflicts, supports, recommendation}`.

- **T3 — Shared Agency / Social Agent:**
  - `joint_goal_store.py` (`kuro_backend/agency/`): SQLite-backed store using WAL mode
    in `kuro_short_term.db`. Stores `joint_goals(id, description, chapter_ref, status,
    created_at, closed_at)`. Survives process restarts — PhD commitments span weeks.
    Exposes `add_commitment()`, `get_active_commitments()`, `close_commitment()`,
    `search_commitments()`, `format_for_prompt()`.
  - Active commitments are injected as `[JOINT_COMMITMENTS]` block into the system
    prompt of every agency-persona turn.
  - `advisor`, `consultant`, and `auditor` personas updated with **Coordination Partner**
    framing: proactive commitment referencing and standing authority to issue
    constructive call-outs when input diverges from dissertation goals.
  - `auditor` persona extended with **Adversarial Simulation Protocol**: leads response
    with `[ADVERSARIAL FINDING]` when Draft B simulation is injected.

- **`KuroState` Extended (V7.2 fields):**
  `_intent_category`, `inhibited`, `inhibition_reason`, `simulated_outcomes`,
  `selected_outcome`, `cognitive_effort`, `alignment_score`, `metacognitive_flag`,
  `joint_goal_block`.

- **New env var:** `KURO_ALIGNMENT_THRESHOLD` (float, default `0.35`) — alignment
  conflict floor below which metacognitive realignment fires.

### New Files

| File | Purpose |
|---|---|
| `kuro_backend/agency/__init__.py` | Package root for Natural Agency sub-system |
| `kuro_backend/agency/joint_goal_store.py` | SQLite joint commitment CRUD (T3) |
| `kuro_backend/agency/cognitive_effort.py` | Regex-based effort allocator (T2) |

### Modified Files

| File | Change |
|---|---|
| `kuro_backend/langgraph_core.py` | +4 nodes, +2 routing fns, new topology, extended `KuroState`, agency field defaults |
| `kuro_backend/memory_coordinator.py` | +`evaluate_alignment()` (T2 Belief Revision) |
| `kuro_backend/personas.py` | `advisor` + `auditor` Shared Agency Protocol framing |
| `SYSTEM_MAP.md` | V7.2 architecture notes, updated graph topology, `agency/` in module tree |
| `CHANGELOG.md` | This entry |

### Performance Notes

- All agency nodes self-bypass in **O(1)** for non-agency personas — zero added latency
  for `chill`, `tactical`, `chancellor`.
- Simulation + alignment calls use `CLASSIFIER_MODEL` (Gemini Flash) — lightweight,
  consistent with `reflection_node` pattern.
- `cognitive_effort` is pure-regex — no LLM call.
- `evaluate_alignment` is skipped when `research_ledger` has no prior commitments
  (returns `score=1.0` immediately).

---

# Kuro AI V7.1.0 "Sovereign Unbound" - Changelog

**Release Date:** 2026-04-28
**Version:** 7.1.0
**Codename:** "Sovereign Unbound — The Final Purge"

---

## V7.1.0 - Sovereign Unbound: The Final Purge (2026-04-28)

### Summary
The final stage of the V7 "Leviathan" transition. This release completes the decommissioning of all legacy Project Kuro components, specifically purging the Live2D "Hijiki" mascot, the associated UI tips/trivia bubble, and the entire voice/TTS infrastructure. The backend has been further sanitized by removing the Habits and Reminders services, resulting in a significantly leaner and more performant "Sovereign" codebase.

### Highlights
- **Live2D Decommissioning:** Completely removed the Hijiki model, PIXI.js integration, and `live2d_manager.js`. The dashboard is now mascot-free.
- **UI Sanitization:** Purged the Kuro Tips & Trivia bubble and the associated 10-minute timer logic.
- **Voice Infrastructure Purge:** Removed all TTS/voice services (Piper, gTTS) and associated dependencies (`piper-tts`, `onnxruntime`) from `requirements.txt`.
- **Backend Streamlining:** Deleted `habit_service.py`, `reminder_service.py`, and their respective SQLite databases. Legacy endpoints now return `410 Gone`.
- **Sovereign Rebranding:** Updated all internal documentation and system maps to reflect the "Sovereign" persona evolution from the legacy "Butler" model.
- **System Map & Tutorial:** Refreshed `SYSTEM_MAP.md` and the Tutorial page to reflect the new lean architecture.

---

# Kuro AI V7.0 "Leviathan" - Changelog

**Release Date:** 2026-04-22
**Version:** 7.0.0
**Codename:** "Leviathan — Discipline & Documentation Pass"

---

## V7.0.0 - Leviathan: Discipline & Documentation Pass (2026-04-22)

### Summary
Repository-wide discipline pass. Promotes every Python, HTML, JS and CSS
source file to a standardized five-field **Header Doc** contract (Purpose,
Caller, Dependencies, Main Functions, Side Effects), hardens
`kuro_backend/finance_db.py` with an in-memory `_SCHEMA_READY` guard so
`init_db()` is idempotent in hot paths, adds indexes for the active
recurring-expense and watched-symbol hot queries, and refreshes
`SYSTEM_MAP.md` + test coverage to match. No runtime behaviour changes
outside the finance_db schema-guard and new indexes.

### Highlights
- **Version:** `kuro_backend/version.py` -> 7.0.0 "Leviathan", UI badge
  reads `Leviathan V7.0`.
- **Docs discipline:** 89 files (50 backend + 4 OpenClaw + 10 frontend +
  25 tests) carry the Header Doc block; SYSTEM_MAP gains a
  "Documentation discipline" section and NEWSAPI / Metaculus rows on the
  External Integrations table.
- **DB audit:** `finance_db.init_db()` now short-circuits after the first
  successful bootstrap via a `threading.Lock`-guarded flag; new
  `idx_recurring_active` and `idx_watched_active` indexes support the
  hot list-by-active queries; `apply_watched_price` and
  `format_market_snapshot_for_prompt` cost justification documented
  inline.
- **Tests:** updated `test_version.py`, added
  `test_finance_db_schema_guard.py` (idempotent bootstrap + index
  presence); `pytest` green.

---

## V7.0.1 - Leviathan: Mem0 Supremacy Reset (2026-04-25)

### Summary
Architectural reset for memory and reasoning flow. LangGraph is reduced to
`Input -> Memory Retrieval -> Tool/Action -> Response`, compliance and
habit/reminder logic are purged from the core brain path, and Mem0 is now the
sole long-term semantic layer. Short-term prompt context now uses the last
15 raw turns without summarization. Session-local attachment extraction is
persisted and prioritized for deictic follow-up requests ("edit previous",
"add to that").

### Highlights
- **LangGraph purge:** removed compliance/habit nodes and routing, removed
  summary-refresh post-response task, and simplified response context assembly
  to referent + Mem0 + memory injection + finance/market/tool sections.
- **Memory coordinator:** `build_context_for_llm*` no longer depends on
  compliance/Chroma conversational retrieval and no longer injects compressed
  short-term summaries in runtime path.
- **Raw short-term window:** conversational short-term window standardized to
  15 turns (`SHORT_TERM_LIMIT=15`) and prompt labels updated accordingly.
- **Attachment continuity:** `/api/chat` and `/api/chat/stream` now persist
  `current_session_state` (attachments + extracted snippets) in runtime
  context to anchor follow-up edits to the current session.
- **Product surface purge (disabled):** compliance, reminder, and habits APIs
  return `410 disabled`; corresponding legacy tools are stubbed with explicit
  "moved/purged in KURO V7.0" responses.
- **Sebastian migration phrase:** one-time runtime confirmation message added
  after reset deployment.

---

## V6.3.0 - Sovereign: Market Sentinel & Chancellor Oracle (2026-04-22)

### Summary
Extends The Chancellor with **OpenClaw-backed** readonly market tools
(`get_ticker_price_tool`, `get_market_news_tool`, `prediction_market_scan_tool`),
new `openclaw_skills/market_analysis` and `prediction_market_scan`, finances DB
extensions (`watched_symbols`, `prediction_watch`, `market_hud_snapshot`),
nightly `_run_market_sentinel` in `dreaming_worker` (CLI `--run-market`),
`market_alert` proactive events, `/api/market/*` routes + `/market` dashboard,
HUD chip polling on the main chat chrome, and persona guardrails that forbid
inventing quotes when the bridge fails.

### Highlights
- **OpenClaw:** reference skills under `openclaw_skills/` (Stooq price path;
  optional NewsAPI / Metaculus / demo prediction rows).
- **LangGraph:** supervisor routes market keywords to `tool_node`; response
  assembly injects `market_block` for Chancellor.
- **Config:** `KURO_MARKET_SENTINEL_ENABLED`, `KURO_MARKET_MOVE_PCT`,
  `KURO_PREDICTION_SCAN_ENABLED` on `Settings`.

---

## V6.2.0 - Sovereign: The Chancellor — Finances SSoT & Fiscal Sentinel (2026-04-17)

### Summary
Adds **The Chancellor** persona (Sovereign Accountant register), a new
SQLite **finances** domain (`monthly_budget`, `recurring_expenses`,
`api_usage_daily`), per-persona Piper tuning via `voice_profiles.py`, SSoT
shortcuts + REST routes under `/api/finances/*`, Gemini tool-calling entries
for the ledger, static Gemini **pricing** estimates rolled into
`observability.track_token_usage`, and a nightly **fiscal sentinel** in
`dreaming_worker` that Telegram-alerts when yesterday's estimated API spend
exceeds `KURO_FISCAL_DAILY_USD_THRESHOLD` (default USD 1.00).

### Highlights
- **Persona:** `chancellor` in `personas.py`, `memory_manager` canonical list,
  dashboard persona picker + `app.js` `VALID_PERSONAS`.
- **DB:** `kuro_backend/finance_db.py` (+ env `KURO_FINANCE_DB_PATH`);
  initialized from `core_service.init_all_databases()`.
- **Voice:** `kuro_backend/voice_profiles.py`; `/api/voice/speech` passes
  active persona into `voice_service.synthesize_to_file`.
- **Proactive:** `fiscal_alert` kind in `proactive_events`; `_run_fiscal_sentinel`
  + CLI `--run-fiscal`.

---

## V6.1.0 - Sovereign: English Migration & Live2D Hijiki (2026-04-17)

### Summary
Completes the Sovereign rollout by migrating every user-facing and
prompt-level string from Bahasa Indonesia to elegant, Sebastian-register
English, replacing the placeholder initial on the dashboard avatar with the
real `profile/kuro_avatar.png` + favicon, and integrating a Live2D "Hijiki"
mascot whose mouth lip-syncs to Piper TTS playback via Web Audio amplitude
sampling.

### Highlights
- **Full ID → EN migration (Sebastian register):**
  - `kuro_backend/personas.py` — every persona + SSoT directive + CoT tail
    (`consultant`, `chill`, `advisor`, `tactical`, `butler`) rewritten in
    refined butler-English. Structural headers (CORE KNOWLEDGE BASE,
    CHAIN OF THOUGHT, HITL SECURITY POLICY, etc.) preserved verbatim.
  - `kuro_backend/ui_mode_router.py` — new English triggers:
    *"Activate Research Mode"*, *"Switch to HUD"*, *"Engage HUD Mode"*,
    *"Stand down"*, *"System Status"*. Legacy Bahasa patterns retained.
    All acknowledgements rewritten.
  - `kuro_backend/telegram_notifier.py` — `_INCONSISTENCY_TEMPLATE` now in
    butler English.
  - `main.py` — chat-reply and WebSocket error messages, reminder previews,
    hardware CPU/RAM/disk alert bodies all translated.
  - `web_interface/static/js/app.js` — dashboard greeting bubbles
    translated to *"Welcome, Master Pantronux. I am Kuro, your devoted AI
    Butler…"*.
- **Branding:**
  - New `/profile` FastAPI static mount in `main.py` exposes
    `profile/kuro_avatar.png`, `favicon.ico`, and the Live2D runtime to
    the browser.
  - `#kuroAvatar` now renders `profile/kuro_avatar.png` with graceful
    fallback to the letter "K" on image load failure. Pulse-glow
    animation continues to fire via the `.speaking` class.
  - Favicon + Apple-touch-icon wired into every HTML template (index,
    reminder, daily_habits, intelligence, login, compliance).
- **Live2D Hijiki mascot:**
  - New `<canvas id="live2d-canvas">` inside a fixed bottom-right
    `#live2dDock` (auto-hides below 900 px viewports).
  - New `web_interface/static/js/live2d_manager.js` dynamically loads
    `live2dcubismcore.min.js` + `pixi.js@7` + `pixi-live2d-display@0.4`.
    Offline-first: tries `/static/vendor/live2d/*` before falling back to
    the Live2D CDN / jsDelivr. Drop README at
    `web_interface/static/vendor/live2d/README.md` with download URLs.
  - Loads the Hijiki model from
    `profile/live2d/hijiki/runtime/hijiki.model3.json`, starts the Idle
    motion, and exposes `window.kuroLive2D.{setLipSyncValue,
    playTalkMotion, returnToIdle}`.
  - **Connecting dots:** `kuroPlayTTS` in `app.js` now builds a shared
    `AudioContext` + `AnalyserNode` on first playback, computes normalized
    RMS each `requestAnimationFrame`, and pushes it into
    `PARAM_MOUTH_OPEN_Y` on the Hijiki model so the mouth tracks the
    Piper waveform. `Tap` motion plays on speech start, Idle restores on
    `ended`/`pause`/`error`.
- **Voice reaffirmation:** Piper `en_GB-alan-medium` (British male) remains
  the shipped default with `KURO_PIPER_LENGTH_SCALE=1.1` and
  `KURO_TTS_PITCH_SHIFT=0.93` unchanged from V6.0.
- **Tests:**
  - `tests/test_ui_mode_router.py` extended with English command coverage
    (*activate research mode*, *switch to hud*, *stand down*,
    *system status*) + English acknowledgement assertions.
  - New `tests/test_branding.py` template-smoke covering favicon,
    kuro_avatar.png, and the Live2D canvas dock.
  - New persona-English smoke asserts the `consultant` prompt reads
    "AI Butler" and contains no more "Kamu adalah".

### Assets required at runtime
- `profile/kuro_avatar.png` (shipped).
- `profile/favicon.ico` (shipped).
- `profile/live2d/hijiki/runtime/hijiki.model3.json` + associated Cubism 4
  assets (shipped).
- `~/.kuro/piper/en_GB-alan-medium.onnx` (user download — unchanged from
  V6.0).
- Optionally, `web_interface/static/vendor/live2d/*.js` for offline SDK.

---

## V6.0.0 - Sovereign: Sebastian Voice, HUD Polish, Proactive Greeting (2026-04-17)

### Summary
Upgrades the Jarvis sentinel foundation (V5.5.1) into a full Sebastian-style
butler. Kuro now boots with an offline, pitch-treated Piper voice (calm UK
male), pulses an avatar visualizer while speaking, lets the master re-play
any message with a single click, shows a live "SENTINEL: SCANNING/IDLE"
ticker around every sentinel sweep, and greets the master once per day the
moment the dashboard opens — all over the existing WebSocket channel.

### Highlights
- **Sebastian voice:** `KURO_TTS_ENGINE=piper` is now the default. The
  default model is `en_GB-alan-medium` (offline). New env knobs:
  `KURO_PIPER_LENGTH_SCALE=1.1` (elegant cadence) and
  `KURO_TTS_PITCH_SHIFT=0.93` (~7% deeper via ffmpeg
  `asetrate + atempo`). `voice_service._apply_pitch_shift` degrades
  gracefully when ffmpeg is missing.
- **HUD avatar visualizer:** `#kuroAvatar` pulses (CSS keyframes) while
  the `<audio>` element is playing — both for auto-speak and the new
  per-message replay button.
- **Replay buttons:** Every assistant bubble now carries a small 🔊
  button that re-hits `/api/voice/speech` for that message.
- **Sentinel status ticker:** `STATUS_TICKER` UI_COMMAND carries
  `{status, source, detail}`; CVE / fitness / hardware sentinels broadcast
  SCANNING on entry and IDLE on exit, with a 30-second client-side
  watchdog so a crashed backend never strands the ticker.
- **Proactive daily greeting:** A new `proactive_greetings` table in
  `kuro_auth.db` tracks one-greeting-per-day-per-user. On dashboard WS
  connect, Kuro whispers a butler-flavoured welcome (spoken + chat
  bubble). Config: `KURO_PROACTIVE_GREETING_ENABLED`,
  `KURO_PROACTIVE_GREETING_TEXT`,
  `KURO_PROACTIVE_GREETING_COOLDOWN_DAYS`.
- **Versioning SSOT:** New `kuro_backend/version.py` + `GET /api/version`.
  Dashboard sidebar badge reads from this single source.

### New Files (V6.0.0)
- `kuro_backend/version.py`
- `kuro_backend/proactive_greeting.py`
- `tests/test_version.py`
- `tests/test_proactive_greeting.py`

### Files Changed (V6.0.0)
- `kuro_backend/voice_service.py` (Piper default, length_scale, ffmpeg pitch)
- `kuro_backend/dashboard_broadcast.py` (`GREETING` added to `UI_COMMANDS`)
- `kuro_backend/dreaming_worker.py` / `kuro_backend/fitness_service.py` /
  `main.py` (hardware sentinel) — STATUS_TICKER broadcasts.
- `kuro_backend/auth_db.py` (greeting persistence).
- `kuro_backend/config.py` (new env knobs).
- `main.py` (`/api/version`, `proactive_greeting` hook in
  `/ws/dashboard`, V5.5 banner refresh).
- `web_interface/templates/index.html` (sidebar badge,
  `#kuroAvatar` + keyframes, HUD ticker markup).
- `web_interface/static/js/app.js` (`kuroPlayTTS` shared helper,
  avatar pulse, replay button, `GREETING` + `STATUS_TICKER` handlers).
- `requirements.txt` (piper-tts + onnxruntime promoted to required).
- `tests/test_voice_service.py` (length_scale + pitch-shift + fallback tests).
- V5.5 banner lines across module docstrings refreshed to V6.0 Sovereign.

---

## V5.5.1 - Jarvis Sentinel, HUD Modes, Proactive Bus & Voice (2026-04-17)

### Summary
Adds a presence layer on top of V5.5: a nightly Proxmox + NVD CVE sentinel
wired through OpenClaw (with direct NVD fallback), a dashboard
`ui_command` channel + chat-side mode router for HUD / RESEARCH / CINEMA
atmospheres, an event-driven proactive anomaly bus that centralises Telegram
dispatch for hardware / fitness / CVE / memory anomalies, and a pluggable
TTS endpoint so Kuro can speak in the dashboard.

#### Highlights
- **Cyber Sentinel:** `openclaw_skills/vulnerability_scan/` reference skill
  (Proxmox enumeration + NVD lookup + optional `nmap -sV`). Kuro-side
  `_run_cve_sentinel` in `kuro_backend/dreaming_worker.py` persists
  `#cve-alert` metadata to Chroma and fires `security_cve` events.
- **Proactive Event Bus:** new `kuro_backend/proactive_events.py` with
  dedup via the existing `dream_notifications` fingerprint table, severity
  gating, and a thread-safe async publish path.
- **Hardware sentinel refactor:** `hardware_sentinel_check` now routes
  through `proactive_events.publish` instead of raw Telegram calls.
- **Fitness sentinel:** `kuro_backend/fitness_service.py` reads
  `~/.kuro/fitness_latest.json` every 30 minutes (env-gated) and emits
  resting-HR / sleep / recovery / sync-stale anomalies.
- **Memory coordinator hook:** `_maybe_emit_proactive_from_mutation`
  attached to `record_mutation` + `apply_openclaw_execution_result` so
  payload-marked anomalies become `ProactiveEvent`s without duplicating
  dedup logic.
- **HUD Mode UI channel:** `dashboard_broadcast.broadcast_ui_command`
  with whitelist + thread-safe scheduler; chat-side `ui_mode_router`
  (BI + EN keyword matcher) wired into `/api/chat` and `/api/chat/stream`;
  frontend theme classes (`theme-hud`, `theme-research`, `theme-cinema`)
  with WS handler in `app.js`, `daily_habits.html`, `reminder.html`.
- **Voice Readiness:** `kuro_backend/voice_service.py` with pluggable
  gTTS (default) and Piper engines, SHA-1 cache under `media/tts/`
  capped at 50 MB with 7-day TTL. `POST /api/voice/speech` endpoint
  and `/media/tts` static mount. Frontend auto-speaks the assistant
  reply when HUD_MODE is active.

#### Env / Config
- `KURO_CVE_SENTINEL_ENABLED` (default `true`)
- `KURO_CVE_MIN_CVSS` (default `7.0`)
- `KURO_CVE_MAX_ALERTS_PER_CYCLE` (default `5`)
- `KURO_VULN_NMAP_ENABLED` (default `false`)
- `KURO_PROACTIVE_ENABLED`, `KURO_PROACTIVE_TELEGRAM_ENABLED`,
  `KURO_PROACTIVE_SEVERITY_FLOOR` (default `warning`)
- `KURO_FITNESS_ENABLED`, `KURO_FITNESS_DATA_PATH`, `KURO_FITNESS_INTERVAL_MIN`
- `KURO_TTS_ENGINE` (`gtts` | `piper`), `KURO_PIPER_VOICE_PATH`, `KURO_TTS_CACHE_DIR`
- `KURO_UI_MODE_DEFAULT` (default `NORMAL_MODE`)

#### Dependencies
- Added: `gTTS>=2.5.0` (default TTS engine).
- Optional: `piper-tts>=1.2.0`, `onnxruntime>=1.17.0` (offline TTS,
  install manually + voice model download).

#### Files Changed (V5.5.1)
- **NEW:** `kuro_backend/proactive_events.py`, `kuro_backend/ui_mode_router.py`,
  `kuro_backend/fitness_service.py`, `kuro_backend/voice_service.py`,
  `openclaw_skills/vulnerability_scan/vulnerability_scan.py`,
  `openclaw_skills/vulnerability_scan/README.md`,
  `tests/test_proactive_events.py`, `tests/test_ui_mode_router.py`,
  `tests/test_cve_sentinel.py`, `tests/test_voice_service.py`.
- **MODIFIED:** `kuro_backend/dashboard_broadcast.py`,
  `kuro_backend/dreaming_worker.py`, `kuro_backend/memory_coordinator.py`,
  `kuro_backend/config.py`, `main.py`, `requirements.txt`,
  `web_interface/static/js/app.js`, `web_interface/templates/index.html`,
  `web_interface/templates/daily_habits.html`,
  `web_interface/templates/reminder.html`, `CHANGELOG.md`.

---

## V5.5.0 - Extreme Optimization — Performance, Latency & Grounding (2026-04-17)

### Summary
Enterprise-grade tuning across concurrency, token economy, semantic routing, and anti-hallucination sampling. SSoT primitives (`bump_data_revision`, `record_mutation`, `*_svc`) remain unchanged.

#### Highlights
- **Concurrency (P1):** Parallel fan-out in `build_context_for_llm` (`_parallel_gather_sync`), `build_context_for_llm_async` for streaming fast path, Mem0 prefetch from supervisor + consume in `memory_retrieval_node`, parallel Chroma in `compliance_node` expansion mode, parallel SQLite reads in `habit_node`, TTL cache for `expand_query`.
- **Token economy (P2):** `token_budget.py` per-section quotas + global ceiling + duplicate block collapse; sliding-window short-term summarization with SQLite `short_term_summaries` cache; compressed tool-router system instruction.
- **Routing & cache (P3):** `ssot_shortcuts.py` deterministic factual answers; `semantic_cache.py` + `embedding_cache.py` (opt-in semantic cache, shared embeddings).
- **Grounding & sampling (P4):** SSoT priority directive in persona tails; per-persona `SAMPLING_PROFILES`; deterministic tool router; `build_factual_response_config` for JSON factual path; `sniper_ssot_grounding_lint` after response postprocess.

#### Files Changed (V5.5.0) — representative
- **NEW / MODIFIED:** `kuro_backend/token_budget.py`, `kuro_backend/ssot_shortcuts.py`, `kuro_backend/semantic_cache.py`, `kuro_backend/embedding_cache.py`, `kuro_backend/personas.py`, `kuro_backend/memory_coordinator.py`, `kuro_backend/memory_manager.py`, `kuro_backend/langgraph_core.py`, `kuro_backend/core.py`, `kuro_backend/guardrails/sniper_pipeline.py`, `kuro_backend/observability.py`, `main.py`, `web_interface/static/js/app.js`, `maintenance/rebuild_compliance_base.py`, and aligned module headers across `kuro_backend/`.
- **MODIFIED:** `CHANGELOG.md` (this file).

---

# Kuro AI V5.2 Official - Changelog (archive)

**Release Date:** 2026-04-16
**Version:** 5.2.0
**Codename:** "Unified Memory Coordinator & Deictic Vision Grounding"

---

## V5.2.0 - Unified Memory Coordinator & Deictic Vision Grounding (2026-04-16)

### Major Upgrade: Single Memory Orchestration + Image Context Reliability

#### 1. Unified Memory Coordinator Rollout
- **New orchestration module**: `kuro_backend/memory_coordinator.py` as centralized surface for:
  - Habit mutation routing (`habit_create`, `habit_update`, `habit_delete`)
  - OpenClaw revision bump policy (`apply_openclaw_execution_result`)
  - LLM read bundle (`build_context_for_llm`)
  - Post-response workers (`execute_memory_write_task`, `execute_mem0_extract_task`)
- **Contract entrypoint added**: `record_mutation(...)` for domain-based mutation dispatch (`habits`, `long_term`, `mem0`) with forward-compatible idempotency key slot.

#### 2. Strong Consistency for Habits + OpenClaw
- **API write path centralized**: `POST/PUT/DELETE /api/habits` in `main.py` now routes through `memory_coordinator` gateway.
- **OpenClaw SSoT sync centralized**: revision bump decision moved behind coordinator policy so `touched_habits`/`touched_reminders` and `harvest_gemini_share` are handled consistently.
- **Invariant preserved**: canonical write via `*_svc` paths retains bump-after-commit behavior.

#### 3. Deictic Grounding for "ini/itu/tadi"
- **New grounding helpers** in coordinator:
  - `build_referent_grounding_block(...)`
  - `format_same_turn_attachment_index(...)`
  - `user_message_looks_deictic(...)`
- **Prompt grounding blocks** now include:
  - `[ATTACHMENT_ORDER_THIS_REQUEST]` (same-turn deterministic ordering from upload metadata)
  - `[RECENT_ATTACHMENTS_GROUNDING]` (recent user attachment history for referent resolution)
- **Path-aware context bridge**: `apply_path_tokens_to_runtime(...)` resolves explicit image path/basename references via integrity metadata and updates `last_accessed_file`.

#### 4. LangGraph Vision Path Fixed
- **`response_node` now multimodal**: image paths are converted to Gemini `inline_data` parts (aligned with legacy `core.process_chat` behavior).
- **Fast-stream parity improved**: same coordinator read bundle and referent grounding are used in true-token fast path text context.
- **Multi-image consistency improved**: deterministic attachment ordering is injected so "gambar pertama/kedua" mapping is stable.

#### 5. Observability + Test Coverage
- **Phoenix attributes added** for coordinator read-layer grounding (`memory.domain`, `memory.source`, `memory.ok`, optional `memory.revision_after`).
- **NEW tests**:
  - `tests/test_memory_coordinator_contract.py`
  - `tests/test_referent_grounding.py`
- **Regression status**: full suite passes (`31 passed`) after coordinator + grounding + vision changes.

#### 6. Known Issues Status Update
- **Mitigated**: inconsistent image analysis path between LangGraph and legacy core.
- **Mitigated**: frequent deictic confusion for image/file references (`ini/itu`) via attachment grounding blocks.
- **Partially open**:
  - Optional quota-aware batching for very large multi-image requests.
  - Edge-case path normalization when user references files outside upload integrity scope.

#### Files Changed (V5.2.0)
- **MODIFIED**: `kuro_backend/memory_coordinator.py`
- **MODIFIED**: `kuro_backend/langgraph_core.py`
- **MODIFIED**: `main.py`
- **MODIFIED**: `kuro_backend/tools/base_tools.py`
- **MODIFIED**: `tests/test_sync_revision_contract.py`
- **NEW**: `tests/test_memory_coordinator_contract.py`
- **NEW**: `tests/test_referent_grounding.py`
- **MODIFIED**: `CHANGELOG.md`

---

# Kuro AI V5.1 Official - Changelog

**Release Date:** 2026-04-15
**Version:** 5.1.0
**Codename:** "Upload Integrity, Sync Reliability & Smart Read Unification"

---

## V5.1.0 - Upload Integrity, Sync Reliability & Smart Read Unification (2026-04-15)

### Major Upgrade: File Lifecycle Hardening + Dashboard Data Sync

#### 1. Smart Read Flow Unification
- **Unified facade**: Introduced `smart_read(...)` as the primary file-reading entrypoint.
- **Format routing**:
  - PDF -> PDF engine + instruction processing
  - DOCX/XLSX/PPTX -> native parser + LLM processing
  - Images -> Vision OCR extraction path
  - Text/log/code -> `universal_read` fallback
- **Context resolution**: Added contextual resolution for references like `ini/itu/tadi` using `last_accessed_file`.
- **Prompt alignment**: System instructions in core/langgraph now point to `smart_read` as canonical interface.

#### 2. Habits & Reminders Synchronization Hardening
- **Habits write APIs restored**:
  - `POST /api/habits`
  - `PUT /api/habits/{habit_id}`
  - `DELETE /api/habits/{habit_id}`
- **Reminder mutation consistency**:
  - Added `mark_notified_10m_svc(...)`
  - Added `mark_notified_event_svc(...)`
  - Wrapper now routes notified mutations via svc path to guarantee revision bump.
- **DB path diagnostics**: Added explicit DB path resolution logging and fallback warnings to reduce cross-process path drift risk.

#### 3. Dynamic Upload Filename Refactor (Anti-Overwrite)
- **Unique filename policy**:
  - Format: `{slugified_original}_{YYYYMMDD_HHMMSS}.{ext}`
  - Collision failsafe: append random 4-digit suffix on same-second duplicates.
- **Category-based storage**:
  - `images/`, `docs/`, `logs/`, `misc/` under upload root.
- **Metadata consistency**:
  - Chat attachments now persist `stored_filename` (unique server filename), not raw client filename.
- **Frontend alignment**:
  - Attach/drag-drop/paste still uses same UX.
  - Allowed types extended to include `.log`, Office files, and structured text extensions.

#### 4. SHA-256 Integrity Logging for Uploads
- **New integrity table**: `uploaded_file_integrity` in chat history SQLite.
- **Stored metadata**:
  - `request_id`, `platform`, `persona`
  - `original_filename`, `stored_filename`, `stored_path`
  - `content_type`, `size_bytes`, `sha256`, `uploaded_at`
- **Automatic checksum generation**:
  - SHA-256 computed at upload save time (without rereading file).
  - Persisted for both `/api/chat` and `/api/chat/stream` upload paths.
- **Verification helpers**:
  - Added internal APIs to record/query integrity metadata from `chat_history` module.

#### 5. Test Coverage Added/Updated
- **NEW**: `tests/test_smart_read_flow.py`
- **NEW**: `tests/test_sync_revision_contract.py`
- **NEW**: `tests/test_upload_filename_generation.py`
- **Regression status**: Core targeted suites pass for smart_read, sync revision, upload uniqueness, and integrity logging paths.

#### 6. Bug & Scheduled Improvements
- **Mitigated (2026-04-16)**: LangGraph `response_node` now sends `image_paths` to Gemini as `inline_data` parts (aligned with legacy `core.process_chat`), with ordered `[ATTACHMENT_ORDER_THIS_REQUEST]` injected from `main.py` and `[RECENT_ATTACHMENTS_GROUNDING]` from `memory_coordinator` for deictic resolution (`ini`/`itu`/attachments). `last_accessed_file` is set on web upload and when user messages contain resolvable paths/basenames (integrity-backed).
- **Remaining / follow-up**: Optional quota-aware batching for very large multi-image requests; edge cases if clients send unusual paths outside upload integrity.
- **Scheduled improvement**:
  - Further harden multi-image orchestration and response quality controls if product needs stricter caps.
  - Consider optional quota-aware batching strategy for image-heavy requests.

#### Files Changed (V5.1.0)
- **MODIFIED**: `kuro_backend/tools/base_tools.py`
- **MODIFIED**: `kuro_backend/core.py`
- **MODIFIED**: `kuro_backend/langgraph_core.py`
- **MODIFIED**: `kuro_backend/services/core_service.py`
- **MODIFIED**: `kuro_backend/reminder_service.py`
- **MODIFIED**: `kuro_backend/chat_history.py`
- **MODIFIED**: `main.py`
- **MODIFIED**: `web_interface/templates/index.html`
- **MODIFIED**: `web_interface/static/js/app.js`
- **NEW**: `tests/test_smart_read_flow.py`
- **NEW**: `tests/test_sync_revision_contract.py`
- **NEW**: `tests/test_upload_filename_generation.py`

---

## V5.0.0 - Integration & Data Integrity Hardening (2026-04-15)

### Major Upgrade: Cross-System Integrity, Approval Security, and SSE Contract Reliability

#### 1. HITL Approval Security Hardening (P0)
- **Session-scoped state**: Pending approval is now isolated by `approval_scope` (web session + persona), replacing global cross-request state behavior.
- **Nonce-only confirmation**: Approval now requires `approve <nonce>` (plain `y` removed).
- **Payload integrity**: Pending approval stores `payload_hash` and verifies hash before tool execution.
- **TTL enforcement**: Approval request expires automatically after 10 minutes.
- **Audit lifecycle**: Added explicit logs for `requested`, `token mismatch`, `cancelled`, `executed`, and `cleared` with `trace_id` correlation.
- **Safe fallback policy**: Graph failure path no longer routes risky requests into legacy auto-tool execution.

#### 2. Persona & Memory Data Integrity (P1)
- **Persona-scoped async jobs**: Background memory tasks now carry explicit `persona_scope`.
- **Summary scope consistency**: `summarize_conversation_to_chroma()` accepts persona scope and tags summary metadata with persona provenance.
- **Served vs stored response consistency**: Canonical response persistence is aligned with served response flow.
- **Chat idempotency key**:
  - Added `request_id` column to `chat_history` (migration-safe).
  - Added unique partial index `(platform, role, request_id)` for dedup on retry/reconnect.
  - Write path now uses `INSERT OR IGNORE`.
- **Platform parity**: Telegram user/assistant turns now persist to `chat_history` with persona tagging and request id.

#### 3. OpenClaw Execution Reliability (P2)
- **Circuit breaker recovery**: Refined to `closed/open/half-open` behavior with cooldown and probe recovery.
- **Atomic half-open probe claim**: Eliminates race risk where concurrent requests could run multiple probes.
- **Typed execution policy**: Introduced and enforced `execution_mode: readonly|mutating`.
- **Mutating safety requirement**: Mutating execution requires explicit command/task payload.
- **Router/schema alignment**: Tool routing prompt and callable signature now consistently use `execution_mode`.

#### 4. API & SSE Contract Hardening (P3)
- **Unified envelope adoption**: Introduced API envelope helper (`status`, `data`, `error`, `trace_id`) and applied to critical chat/system endpoints with backward-compatible legacy fields where needed.
- **Auth-aware stream request**: Frontend stream now uses `authFetch` and follows same 401 behavior as non-stream APIs.
- **Session continuity header**: Frontend now sends `X-Chat-Session`; backend validates and uses it for approval scoping.
- **SSE parser robustness**:
  - CRLF normalization (`\r\n` safe).
  - Multi-line `data:` merge support.
  - Terminal error preservation (error event not overwritten by fallback render).
- **Streaming complete envelope**: `complete` and `error` SSE events now carry contract-aligned payload structure.

#### 5. Contract Test Coverage
- **NEW**: `tests/test_api_sse_contract.py`
  - Validates event order: `meta -> chunk* -> complete`.
  - Validates terminal `error` event structure.
- **NEW**: `tests/test_approval_integrity.py`
  - Validates nonce mismatch rejection behavior.
  - Validates cancellation clears pending approval.

#### 6. Technical Notes & Documentation
- **NEW**: `INTEGRATION_HARDENING_DETAILS.md` with:
  - P0-P3 implementation details
  - session scope design
  - verification checklist and commands

#### Files Changed (V5.0.0)
- **MODIFIED**: `kuro_backend/langgraph_core.py` - nonce approval, scoped state, payload hash validation, trace-aware audit, safe fallback alignment
- **MODIFIED**: `kuro_backend/chat_history.py` - request_id migration, idempotent insert/index
- **MODIFIED**: `kuro_backend/memory_manager.py` - persona-scoped summary call path
- **MODIFIED**: `kuro_backend/execution/openclaw_bridge.py` - half-open recovery, atomic probe, typed execution policy
- **MODIFIED**: `kuro_backend/tools/base_tools.py` - `execution_mode` signature and payload propagation
- **MODIFIED**: `main.py` - session header handling, envelope helper adoption, trace/request id propagation
- **MODIFIED**: `web_interface/static/js/app.js` - auth-aware stream, session header, SSE parser hardening
- **NEW**: `tests/test_api_sse_contract.py` - SSE contract tests
- **NEW**: `tests/test_approval_integrity.py` - approval integrity tests
- **NEW**: `INTEGRATION_HARDENING_DETAILS.md` - hardening detail documentation

---

# Kuro AI V4.9 Official - Changelog

**Release Date:** 2026-04-06
**Version:** 4.9.0
**Codename:** "Proactive Intelligence Research & Intelligence Hub"

---

## V4.9.0 - Proactive Intelligence Research & Intelligence Hub (2026-04-06)

### Major Upgrade: Autonomous Research System with Serper.dev Integration

#### 1. Serper.dev Search Tool
- **New Module**: `kuro_backend/tools/serper_tool.py` - Web search integration
- **Functions**: `serper_search()`, `serper_news()`, `serper_scholar()`
- **Indonesia Focus**: Parameters `gl: id` and `hl: id` for Indonesian market relevance
- **API Key**: Uses `SERPER_API_KEY` from `.env`

#### 2. Intelligence Briefings Database
- **New Module**: `kuro_backend/intelligence_db.py` - SQLite storage for daily briefings
- **Table**: `intelligence_briefings` with columns: id, date, summary_text, raw_json_data, experimental_signals
- **Functions**: `save_briefing()`, `get_briefings()`, `search_briefings()`, `get_briefing_by_date()`
- **Log Storage**: Briefings saved to `logs/briefings/briefing_YYYY-MM-DD.json`

#### 3. Intelligence Research Engine
- **New Module**: `kuro_backend/intelligence_engine.py` - Complete research pipeline
- **Research Pillars**:
  - IT Security & Compliance: UU PDP, ISO 27001, OWASP for LLM
  - AI Technology: Agentic AI, Autonomous RAG, AI productivity tools
  - Finance & Business: BEI tech stocks, SaaS AI opportunities, IT passive income
  - Lifestyle & Fitness: Body recomposition science, nutrition optimization
- **Synthesis**: Gemini 3.1 Flash analyzes search results and generates structured briefing
- **Report Format**: 7-section formal report (Status Pagi, Intelijen Sektoral, Wawasan Teknologi, Wawasan Finansial, Rekomendasi Eksperimental, Catatan Kesehatan, Penutup)
- **Telegram Integration**: Formatted markdown message sent to Pantronux's Telegram

#### 4. APScheduler Integration
- **Daily Briefing**: Scheduled at 08:00 AM via `send_daily_intelligence_briefing()`
- **Manual Trigger**: `GET /api/intelligence/run` endpoint for on-demand research
- **Combined Scheduler**: Reminder, Habits & Intelligence scheduler unified

#### 5. Intelligence Hub Dashboard
- **New Template**: `web_interface/templates/intelligence.html` - List-Detail layout
- **Features**:
  - Left sidebar: Date-based briefing list with search functionality
  - Right panel: Full briefing content with markdown rendering
  - Category tags: #Security, #AI, #Finance color-coded labels
  - Glassmorphism styling consistent with One UI design
- **API Endpoints**:
  - `GET /api/intelligence/history` - Paginated briefing history with search
  - `GET /api/intelligence/latest` - Latest briefing
  - `GET /api/intelligence/run` - Manual trigger
  - `GET /intelligence` - Dashboard page

#### Files Changed
- **NEW**: `kuro_backend/tools/serper_tool.py` - Serper.dev search tool
- **NEW**: `kuro_backend/intelligence_db.py` - Briefing storage
- **NEW**: `kuro_backend/intelligence_engine.py` - Research pipeline
- **NEW**: `web_interface/templates/intelligence.html` - Intelligence Hub dashboard
- **MODIFIED**: `main.py` - Added scheduler job, API endpoints, intelligence imports
- **MODIFIED**: `CHANGELOG.md` - Version bump to 4.9.0

---

## V4.8.0 - Proactive Intelligence, Observability & Tool Use (2026-04-06)

### Major Upgrade: Arize Phoenix Observability, LangGraph Tool Use, Web UI Revamp

#### 1. Arize Phoenix Observability (Black Box System)
- **New Module**: `kuro_backend/observability.py` - Complete observability framework
- **Phoenix Server**: Auto-starts on port 6006 with simple auth (username: pantronux)
- **OpenTelemetry Integration**: OTLP exporter sends traces to Phoenix
- **Node Tracing**: Every LangGraph node (supervisor, compliance, habit, tool, response, memory) traced with duration, input/output
- **Guardrails Tracking**: Logs validation failures, re-ask loops, original vs corrected responses
- **Token Usage Monitoring**: Per-session token tracking with 5000 token alert threshold
- **Client Data Labeling**: Queries related to compliance/clients automatically labeled for filtering
- **Session Context**: user_id, session_id, thread_id enriched on every trace
- **New API Endpoints**:
  - `GET /api/observability/status` - Observability component status
  - `GET /api/observability/tokens` - Token usage per session
  - `GET /api/observability/cleanup` - Cleanup old sessions
  - `GET /observability` - Dashboard page with Phoenix link

#### 2. LangGraph Tool Use ("The Hands")
- **New Module**: `kuro_backend/tools/system_tools.py` - LangChain @tool decorated system tools
- **Excel Generator Tool**: `generate_excel_report()` - Creates .xlsx from JSON data using pandas + openpyxl
- **File Manager Tool**: `manage_files()` - List, read, write, delete, info files in `/home/kuro/exports/`
- **Report Templater Tool**: `generate_report_template()` - Generates audit/compliance reports (audit_findings, compliance_gap, risk_assessment, executive_summary)
- **Security Sandbox**: Path validation prevents traversal outside exports directory, file extension whitelist, 50MB size limit
- **HITL Interrupt**: Write/delete operations require Master approval before execution
- **LangGraph Integration**: New `tool_node` added to graph, supervisor routes tool-related queries
- **KuroState Updates**: Added `tool_execution_result` and `requires_approval` fields
- **Exports Directory**: Created at `/home/kuro/exports/`

#### 3. Web UI Revamp - One UI + Glassmorphism + Infinite Scroll
- **CSS Redesign**: Complete rewrite with CSS variables for glassmorphism (`--glass-bg`, `--glass-border`, `--glass-blur`)
- **One UI Shapes**: Border-radius 24px-32px for containers, cards, chat bubbles
- **Glassmorphism Effects**: Sidebar, header, and cards use backdrop-filter blur with transparency
- **Floating Chat Bubbles**: Subtle drop-shadows for "mengambang" effect
- **Enhanced Typography**: Line-height 1.6 for readability, wider padding (24px mobile, 48px desktop)
- **Infinite Scroll**: Paginated chat history (20 messages/page), scroll anchor retention, loading spinner
- **Backend Pagination**: `get_history()` now supports `offset` parameter, `get_total_count()` added
- **API Update**: `/api/history` returns `has_more` flag for infinite scroll

#### 4. Global Identity Rebranding: "Master Irfan" → "Pantronux"
- **Code Updates**: All system prompts, error messages, persona instructions updated
- **Database**: `master_profile.json` name changed to "Pantronux"
- **Web UI**: Profile name, welcome messages, error messages updated
- **JavaScript**: Error messages, welcome messages, user avatar initial changed to "P"
- **Perpetual Memory**: User ID changed to "pantronux", memory templates updated
- **Files Modified**: 11 source files, 2 HTML files, 1 JS file, 1 JSON file

#### 5. Dependencies Added
- `arize-phoenix` - Phoenix observability server
- `opentelemetry-sdk` - OpenTelemetry SDK
- `opentelemetry-exporter-otlp` - OTLP trace exporter
- `opentelemetry-instrumentation-langchain` - LangChain instrumentation

#### Files Changed
- **NEW**: `kuro_backend/observability.py` - Observability framework
- **NEW**: `kuro_backend/tools/system_tools.py` - System tools (Excel, File Manager, Report Templates)
- **MODIFIED**: `kuro_backend/langgraph_core.py` - Added tool_node, observability tracing, updated state
- **MODIFIED**: `kuro_backend/chat_history.py` - Added offset pagination, get_total_count()
- **MODIFIED**: `kuro_backend/core.py` - Updated persona instructions to "Pantronux"
- **MODIFIED**: `kuro_backend/memory_manager.py` - Updated master profile defaults
- **MODIFIED**: `kuro_backend/perpetual_memory.py` - Updated user ID and memory templates
- **MODIFIED**: `kuro_backend/tools.py` - Updated reminder confirmation
- **MODIFIED**: `kuro_backend/compliance_db.py` - Updated default user field
- **MODIFIED**: `kuro_backend/daily_habits_db.py` - Updated report messages
- **MODIFIED**: `main.py` - Added observability endpoints, pagination, observability init
- **MODIFIED**: `web_interface/templates/index.html` - Glassmorphism classes, scroll loader
- **MODIFIED**: `web_interface/templates/reminder.html` - Updated messages
- **MODIFIED**: `web_interface/static/css/style.css` - Complete One UI + Glassmorphism redesign
- **MODIFIED**: `web_interface/static/js/app.js` - Infinite scroll, pagination, prepend logic
- **MODIFIED**: `master_profile.json` - Name changed to "Pantronux"
- **MODIFIED**: `requirements.txt` - Added observability dependencies

---

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
