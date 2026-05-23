# UI V2 Recovery & Dark Gray Redesign Plan
**Revision:** 2 — Updated from screenshot comparison (V1 → V2 delta + new requirements)
**Status:** Ready for Codex execution

---

## Context & Problem Statement

UI V2 saat ini adalah **downgrade fungsional** dari V1. Screenshot comparison menunjukkan:

| Fitur | V1 (Referensi) | V2 (Saat ini) | Action |
|---|---|---|---|
| Color scheme | Dark navy/teal | ✅ Sudah dark, tapi terlalu gelap/flat | Ganti ke dark gray warm |
| Sidebar: Persona label | ✅ Ada (`QA Architect`) | ✅ Ada (`Runtime Sovereign`) | Keep, perbaiki styling |
| Sidebar: TOOLS section | ✅ Tutorial, Intelligence Hub, Market Sentinel | ❌ Hilang | Restore |
| Sidebar: SYSTEM section | ✅ System Status, Uploaded Files, Settings | ❌ Hilang | Restore |
| Sidebar: PREFERENCES section | ✅ Settings | ❌ Hilang | Restore |
| Sidebar: Pin/Rename/Delete chat | ✅ Ada | ❌ Hilang | Restore |
| Header: Persona mode switcher | ✅ `Normal` / `Playground` toggle | ❌ Hilang | Restore |
| Header: Search, Dark mode toggle | ✅ Ada | ❌ Hilang | Restore |
| Header: User profile | ✅ Ada | ✅ Ada (inisial) | Keep, flat style |
| Composer: Attach file button | ✅ Ada (paperclip icon) | ❌ Hilang | Restore via `+` menu |
| Composer: Tool row | V1: horizontal row | V2: horizontal row (numpuk) | Pindah ke `+` menu |
| Composer: Model selector | ✅ Ada di header (code name) | ✅ Ada di header (code name) | Pindah ke dekat send, human-readable label |
| Welcome screen | ✅ Ada | ❌ Langsung masuk chat | Restore |
| Avatar/foto | V1: ada avatar Kuro + user photo | — | Flat icon only, no photos |
| Deep Research modal | V1: native | V2: `window.prompt` | Native drawer |
| Task modal | V1: native | V2: `window.prompt` | Native drawer |
| Reminder modal | V1: native | V2: `window.prompt` | Native drawer |
| Market modal | V1: native | V2: `window.prompt` | Native drawer |
| Playground button | ✅ Ada di header | ❌ Hilang | Restore via `+` menu + in-app drawer |

---

## Design Direction

### Color System (Dark Gray — bukan dark navy, bukan pure black)
```
--bg-primary:     #1a1a1a   /* main background, message pane */
--bg-secondary:   #212121   /* sidebar background */
--bg-tertiary:    #2a2a2a   /* composer, input fields, drawers */
--bg-hover:       #2f2f2f   /* hover state rows, menu items */
--bg-active:      #333333   /* active session row, selected item */
--border-subtle:  #383838   /* dividers, input borders */
--border-focus:   #4a4a4a   /* focus ring elements */

--accent-primary: #0d9488   /* teal — buttons, active indicators, links */
--accent-hover:   #0f766e   /* teal darker on hover */
--accent-soft:    #134e4a1a /* teal 10% opacity — subtle backgrounds */

--text-primary:   #f5f5f5   /* main text */
--text-secondary: #a3a3a3   /* labels, timestamps, placeholder */
--text-muted:     #6b6b6b   /* disabled states, hints */

--status-ok:      #22c55e   /* green */
--status-warn:    #f59e0b   /* amber */
--status-error:   #ef4444   /* red */
--status-info:    #3b82f6   /* blue */

/* User bubble */
--bubble-user-bg: #0d9488
--bubble-user-text: #ffffff

/* Kuro bubble */
--bubble-kuro-bg: transparent
--bubble-kuro-text: #f5f5f5
```

### Typography & Spacing
- Font: `Inter`, fallback `system-ui`, `-apple-system`
- Base size: 14px
- Line height: 1.6
- Sidebar width: 260px (collapsible ke 56px di mobile)
- Composer max-width: 768px (centered)
- Border radius: 12px (cards, modals), 8px (inputs), 6px (buttons, chips), 20px (message bubbles)

### Motion
- Transitions: `150ms ease` untuk hover/focus
- Drawer: `200ms ease-out` slide-in dari kanan
- Modal: `150ms ease` fade + scale(0.97 → 1)
- Menu: `100ms ease` opacity + translateY(-4px → 0)

---

## Key Changes (Revised)

### 1. Layout & Visual Overhaul

**Sidebar (260px, collapsible):**
```
[Kuro AI logo + version]
[+ New Chat button — full width, teal]
[Search chats input]

PINNED
  [pinned session rows]
  "No pinned chats" if empty

RECENT
  [session rows with hover overflow menu]
  [More button if > 8 sessions]

── divider ──

TOOLS
  Tutorial
  Intelligence Hub
  Market Sentinel

── divider ──

SYSTEM
  System Status
  Uploaded Files
  Settings

── divider ──

[User info row — bottom]
  Flat initials icon | Name | Role
```

Setiap **session row** punya:
- Hover state: show `···` overflow menu icon (kanan)
- Overflow menu items: `Rename`, `Pin / Unpin`, `Delete`
- Active session: background `--bg-active`, left border accent teal 2px

**Header (active chat):**
```
[Persona badge: mode label e.g. "Consultant"]  [Chat title]
                                          [Normal] [Playground]  [🔍] [🌙]  [User initial]
```
- `Normal` / `Playground` toggle: pill-style, teal when active
- Search icon: opens search overlay
- Dark mode toggle: switches CSS vars (dark/light), default dark
- User initial: flat circle, opens user menu (Settings, Logout)
- Model selector: **dipindah ke composer** (lihat bagian Composer)

**Message pane:**
- Background: `--bg-primary`
- Max-width content: 768px, centered
- User bubble: teal background, white text, right-aligned
- Kuro bubble: transparent background, light text, left-aligned, dengan Kuro flat icon (monogram "K" dalam circle teal kecil — no photo)
- Timestamp: subtle, hover-reveal
- Message action bar (hover): Copy, Regenerate, Bookmark, Export — flat icon buttons

**Welcome screen (saat chat kosong):**
```
        [K]  ← flat teal circle, monogram only, no photo
     Selamat datang, [Nama].
  Apa yang ingin kamu kerjakan hari ini?

[💡 Quick suggestion chip]  [📊 Market analysis]  [🔬 Research mode]  [⚙️ QA Test]

        ┌─────────────────────────────────────────────┐
        │ + │ Message Kuro...          [Model ▾] [▶] │
        └─────────────────────────────────────────────┘
```
- Suggestion chips: klik → langsung isi textarea
- Chips content: dinamis, bisa hardcoded 4-6 suggestion yang relevan dengan persona aktif

---

### 2. Composer (Single Bar)

```
┌─[+]──────────────────────────────────────────────[Gemini Flash ▾]──[■/▶]─┐
│      Message Kuro...                                                       │
└────────────────────────────────────────────────────────────────────────────┘
```

Komponen dari kiri ke kanan:
1. **`+` button** — membuka action menu (lihat bagian 3)
2. **Textarea** — auto-grow, max 6 baris, Enter = send, Shift+Enter = newline
3. **File preview chips** — muncul di atas textarea jika ada file terpilih (nama file + × untuk hapus)
4. **Model selector dropdown** — label human-readable, posisi di kanan sebelum send:
   - `Gemini Flash` → alias: `gemini_fast`
   - `Gemini Pro` → alias: `gemini_pro`
   - `OpenAI Nano` → alias: `openai_nano`
   - `Claude Fast` → alias: `claude_fast`
   - `DeepSeek Fast` → alias: `deepseek_fast`
   - `Local Ollama` → alias: `ollama_local`
   - Internal value (dikirim ke backend) tetap alias; label hanya untuk display
5. **Stop button** (■) — muncul saat streaming aktif, replace send button
6. **Send button** (▶) — teal, disabled jika textarea kosong dan tidak ada file

**Stream routing:**
- Ada file terpilih → POST ke `/api/chat/stream` (legacy, sudah support `files`)
- Tidak ada file → POST ke `/api/chat/v2/stream`
- Aktif streaming → tampilkan stop button, klik stop → abort fetch + kirim signal ke backend

---

### 3. Single `+` Action Menu

Menu muncul di atas composer, fade + slide up. Tutup jika klik di luar atau tekan Escape.

```
┌─────────────────────────────┐
│ 📎  Add photos & files      │
│ 🗂️  Recent files          › │
├─────────────────────────────┤
│ 🔬  Deep Research           │
│ 🌐  Web Search              │
│ 🤖  Agent Mode              │
├─────────────────────────────┤
│ ✅  Task                    │
│ 🔔  Reminder                │
│ 📊  Market                  │
├─────────────────────────────┤
│ 🧪  Playground              │
└─────────────────────────────┘
```

**Setiap item behavior:**

| Item | Action |
|---|---|
| Add photos & files | Trigger hidden `<input type="file">`, preview chips di composer |
| Recent files | Expand submenu → GET `/api/list-files` → file list, klik = preview drawer |
| Deep Research | Buka **Deep Research Drawer** |
| Web Search | Toggle state ON/OFF di composer (visual indicator: teal pill di composer) |
| Agent Mode | Toggle state ON/OFF (visual indicator: teal pill di composer) |
| Task | Buka **Task Drawer** |
| Reminder | Buka **Reminder Drawer** |
| Market | Buka **Market Drawer** |
| Playground | Buka **Playground Drawer** |

**Toggle states (Web Search, Agent Mode):**
- Saat aktif: badge muncul di composer area (`🌐 Web Search ON ×`) dengan × untuk deaktivasi
- State disimpan di JS variable per session, tidak persist ke backend kecuali dikirim sebagai param di request

**Tidak ada:**
- `Create Image` (bukan fitur existing yang working)
- Item disabled/greyed-out yang tidak berfungsi

---

### 4. Chat/Session Controls

**Overflow menu per session row** (muncul saat hover, klik `···`):
```
┌──────────────┐
│ ✏️  Rename   │
│ 📌  Pin      │  (atau "Unpin" jika sudah pinned)
│ 🗑️  Delete  │
└──────────────┘
```

**Rename:**
- Buka modal kecil: input text pre-filled nama sesi, tombol `Save` dan `Cancel`
- Tidak menggunakan `window.prompt`
- POST ke existing rename endpoint
- Setelah save: update sidebar row label tanpa full reload

**Pin/Unpin:**
- Toggle langsung, optimistic UI update
- Pinned session pindah ke PINNED section atas
- Unpinned pindah kembali ke RECENT
- POST ke existing pin endpoint

**Delete:**
- Buka confirmation modal:
  ```
  Hapus chat ini?
  "Nama Session" akan dihapus permanen.
  [Cancel]  [Hapus]
  ```
- Jika sesi yang dihapus adalah pinned: tambah warning text di modal
- Setelah delete: navigasi ke sesi lain jika active session dihapus
- DELETE ke existing endpoint

**Active-chat header actions** (opsional, jika ada overflow menu di header):
- `Rename`, `Pin`, `Export`, `Delete` — sama behavior seperti sidebar overflow

---

### 5. Tool Drawers/Modals (Native V2 — no `window.prompt`)

Semua drawer: slide dari kanan, overlay backdrop `rgba(0,0,0,0.4)`, closeable via × atau Escape.

**Deep Research Drawer:**
```
Deep Research
─────────────
Query
[________________________________________]

Advanced options ▾
  └ Sources: [ ] Web  [ ] Uploaded docs
  └ Depth: [Standard ▾]

[Cancel]  [Start Research]
─────────────────────────
Status: (muncul setelah submit)
  ⏳ Job queued — ID: dr_xxxxx
  [View status] link ke job tracker
```
- POST `/api/deep-research/jobs` → tampilkan job ID + status
- Polling job status setiap 5s jika drawer masih terbuka

**Task Drawer:**
```
Buat Task Baru
──────────────
Title *
[________________________________________]

Description
[________________________________________]
[________________________________________]

Due date
[Date picker]

Priority: [Medium ▾]

[Cancel]  [Buat Task]
```
- POST `/api/tasks`
- Success: toast notification, drawer tutup otomatis

**Reminder Drawer:**
```
Set Reminder
────────────
Remind me about
[________________________________________]

Waktu
[Date] [Time]

Channel: (•) In-app  ( ) Telegram

[Cancel]  [Set Reminder]
```
- POST `/api/reminders`
- Telegram option hanya aktif jika TELEGRAM_TOKEN configured (cek dari `/api/system/status` atau config flag)

**Market Drawer:**
```
Market Analysis
───────────────
Symbol (e.g. BBCA.JK, AAPL)
[________________________________________]

[ ] Include news analysis

[Cancel]  [Analyze]
────────────────────
Hasil: (muncul setelah submit)
  [rendered ringkasan harga + sentiment]
```
- POST `/api/market-v2/analyze`
- Render hasil inline di drawer, tidak buka halaman baru

**Web Search & Agent Mode:**
- Tidak perlu drawer — toggle state saja (sudah dijelaskan di bagian `+` menu)

---

### 6. Playground Drawer (PhD/QA Research)

```
🧪 Playground — QA Research Mode
──────────────────────────────────
Mode: [PhD Research ▾]
  Options: PhD Research | QA Testing | Gherkin Generator

── PhD Research ──────────────────
Input your research context or requirement:
[________________________________________]
[________________________________________]

[Interpret Requirement]  [Generate Test Cases]  [Generate Gherkin]

── Output ────────────────────────
(rendered result appears here)

[Copy output]  [Send to chat]

──────────────────────────────────
[Tutorial & docs ↗]
```

- `Interpret Requirement` → POST `/api/playground/qa/interpret`
- `Generate Test Cases` → POST `/api/playground/qa/generate-testcases`
- `Generate Gherkin` → POST `/api/playground/qa/generate-gherkin`
- Output dirender di dalam drawer (markdown-aware)
- `Send to chat` → inject output sebagai user message ke aktif chat
- `Tutorial & docs` → link ke `/playground/tutorial` (buka tab baru)
- Jika `KURO_QA_PLAYGROUND_ENABLED=false` atau endpoint 503:
  ```
  🚧 Playground sedang tidak tersedia.
  Pastikan QA runtime aktif atau hubungi admin.
  ```
  Tidak ada alert/prompt JS.

---

### 7. Removed / Deprecated

Hal berikut **dihapus dari V2** dan tidak direstorasi:

| Item | Alasan |
|---|---|
| Foto/avatar Kuro (gambar) | Replaced dengan flat monogram icon "K" |
| Foto user | Replaced dengan flat initials circle |
| `window.prompt()` untuk semua tool | Replaced dengan native drawers |
| Horizontal tool row di composer | Replaced dengan `+` menu |
| `Create Image` di `+` menu | Bukan fitur working, tidak dimasukkan |
| Code name model di selector | Replaced dengan human-readable label |

---

## File Scope

Files yang boleh diubah:
```
web_interface/templates/index_v2.html     ← layout, structure, welcome screen
web_interface/static/css/v2.css           ← semua visual, color vars, dark gray
web_interface/static/js/app_v2.js         ← semua behavior, drawers, modals, routing
```

Files yang TIDAK boleh diubah (kecuali tiny hook yang diperlukan):
```
main.py                    ← no backend changes
kuro_backend/              ← no backend changes
web_interface/templates/index.html  ← legacy UI, jangan disentuh
web_interface/static/js/app.js      ← legacy JS, jangan disentuh
```

Backend exception yang diizinkan (hanya jika diperlukan):
- Tambah `runtime_id` sebagai optional field ke `/api/chat/v2/stream` request body jika belum ada
- Tidak ada perubahan DB schema

---

## Test Plan (Updated)

### Automated tests — update/extend `tests/test_frontend_v2.py`

**Structural tests (parse HTML):**
- [ ] V2 renders dark gray CSS vars (`--bg-primary`, `--bg-secondary`, `--accent-primary`)
- [ ] Welcome screen markup ada (`data-kuro="welcome-screen"` atau equivalent)
- [ ] `+` button ada di composer
- [ ] Hidden file input ada (`<input type="file" id="v2-file-input">`)
- [ ] Model selector ada di composer (bukan di header)
- [ ] Model option values adalah alias, labels adalah human-readable
- [ ] Tidak ada `window.prompt` di `app_v2.js` (grep check)
- [ ] Tidak ada raw secrets atau base URLs di HTML
- [ ] Playground drawer markup ada
- [ ] Session overflow menu markup ada (rename/pin/delete)

**API contract tests:**
- [ ] File upload route ke `/api/chat/stream` (bukan v2) saat ada file
- [ ] No-file route ke `/api/chat/v2/stream`
- [ ] Playground endpoints reachable: interpret, generate-testcases, generate-gherkin
- [ ] Non-admin endpoints tetap protected (existing RBAC tests)

**JS contract tests (static analysis):**
- [ ] `openDeepResearchDrawer()` function exists, no `window.prompt`
- [ ] `openTaskDrawer()` function exists, no `window.prompt`
- [ ] `openReminderDrawer()` function exists, no `window.prompt`
- [ ] `openMarketDrawer()` function exists, no `window.prompt`
- [ ] `renameChat()` uses modal, not `window.prompt`
- [ ] Model selector `change` handler sends alias value, not label text
- [ ] Web Search toggle mengupdate visual state di composer

### Run commands:
```bash
python3 -m compileall kuro_backend main.py
pytest tests/test_frontend_v2.py -x --tb=short
pytest tests/ -x --tb=short
```

---

## Assumptions (Updated)

- Scope: **UI V2 only** (`index_v2.html`, `v2.css`, `app_v2.js`). Legacy UI tidak disentuh.
- Playground: **in-app drawer**, bukan halaman terpisah.
- `+` menu: hanya fitur existing yang working. Tidak ada placeholder disabled.
- Backend: tidak ada perubahan kecuali optional tiny hook untuk file upload / playground status.
- Avatar/foto: **flat icon only** — monogram "K" circle untuk Kuro, initials circle untuk user.
- Model aliases: value dikirim ke backend tetap alias string; label di UI human-readable.
- `window.prompt`: **zero tolerance** — semua tool pakai native modal/drawer.
- Dark gray theme: referensi color system di atas adalah source of truth untuk v2.css.
- V1 sidebar sections (TOOLS, SYSTEM, PREFERENCES): **restored** di V2 dengan endpoint yang sama.
- Suggestion chips di welcome screen: **hardcoded** 4-6 chips, bisa disesuaikan per persona.
