# KRC ↔ Prototype Full Menu Parity & Porting Review

**Tanggal:** 2026-05-30
**Scope:** parity audit + implementation review for production shell `web_interface/templates/index.html` against `Kuro-UI-Prototype` menu surface behavior.

## Ringkas

Target kita adalah **KRC UI**: tetap memakai existing runtime stack (Flask/FastAPI + vanilla JS), tetapi surface-nya dibuat mengikuti prototipe dari sisi shell, spacing, dan behavior. Backend API/flow tetap tidak berubah.

Implementasi yang sudah dimatangkan pada pass ini:

- Composer action menu (`+`) telah dipasang lengkap termasuk item prototype: `Market Analysis` dan `Playground`.
- Header, sidebar, profile menu, chat action menu (`3-dots`) dan welcome composer sudah diposisikan agar sinkron dengan pola KRC/prototype.
- Sidebar default width diset ke `260px`.
- Tidak ada perubahan runtime API/kontrak.

---

## Parity Matrix (Prototype → KRC Shell)

| Prototype Surface | KRC Current Mapping | Action |
| --- | --- | --- |
| Sidebar width 260px | `#sidebar.sidebar { width: 260px }` | Copy (already implemented, width adjusted) |
| Brand text | `Kuro Research Center / Kuro Playground` | Copy (krc text, non-krc remains legacy title) |
| Sidebar nav items: Research Console / Knowledge / Ingestion | `krcNavResearchConsole`, `krcNavKnowledge`, `krcNavIngestion` | Copy (admin-protected for Ingestion) |
| Sidebar collapse on desktop + drawer on mobile | `data-collapsed` + mobile transform controls | Copy/Adopt |
| Chat sessions area + search + chat actions row | `#chatSessionsList`, search, + menu rows with `data-chat-session-action` | Copy with adaptation |
| Session row overflow actions via 3-dots | `session-menu-wrap` + `data-chat-session-action` menu |
| **Menu options**: Pin/Unpin, Rename, Export, Delete | Pin/unpin + Rename/Export/Delete present, delete styled red |
| Header runtime toggle | `Normal` / `Playground` in header buttons | Copy |
| Header search icon | Search button available on header toolbar | Copy |
| Profile menu + Admin Settings entry | `userDropdownMenu`, `Administration Settings` | Copy (admin-only guard still active) |
| Tools submenu (Tutorial/Uploaded Files/Intelligence Hub/Market/...) | Profile `Tools` section with modal/submenu links | Copy (kept legacy-compatible behavior where applicable) |
| Composer `+` action menu | `Add Photos & Files/Recent Files/Deep Research/Web Search/Agent Mode/Task/Reminder` | Copy |
| Composer extra actions from prototype | `Market Analysis`, `Playground` | **Added in this pass** |
| Composer model selector | `#composerModelSelect` + `#welcomeModelSelect` and API-driven options | Copy |
| Send/Stop state exclusivity | `sendBtn` + `stopGeneratingBtn` toggle | Copy |
| Active tool pills | `data-composer-feature-pill` badges with active state | Copy |
| Ingest doc action from playground landing | `openKrcIngestion()` + landing button wiring | Copy/adapt |
| Administration settings tabs | existing backend tabs retained | Copy (no API/schema changes) |

## Features intentionally not visually migrated (by design)

- React component behavior from prototype (state hooks, drawer/portal internals)
- React routing transitions and dedicated React layouts
- Non-shared styling tokens from prototype build system

Semua fitur runtime tersebut tetap dipertahankan di endpoint backend yang sama dan dijaga via helper/JS yang ada.

---

## Runtime Wiring Audit (No contract changes)

- Chat streaming stays on `/api/chat/stream`.
- Session operations tetap ` /api/chats/* `.
- Composer model aliases: `/api/models`.
- Tool executors tetap via existing `/api/tools/{tool_id}/execute` mapping.
- File modal tetap menggunakan existing `/api/` endpoints + current upload path.
- Playground tetap `/api/playground/*`.
- Admin/settings endpoints remain unchanged.

## Menu Parity Checklist (Current)

- [x] Composer menu now includes: Add Photos & Files, Recent Files, Deep Research, Web Search, Agent Mode, Task, Reminder, Market Analysis, Playground.
- [x] Chat session row menu contains Pin, Rename, Export, Delete.
- [x] Sidebar primary navigation includes Research Console, Knowledge, and admin-gated Ingestion.
- [x] Header includes mode toggle + profile trigger.
- [x] Welcome + main composer action menus mirrored for both entry points.
- [x] `Kuro`/`Kuro Research Center` avatar branding simplified to flat mark (tanpa asset foto).

## Test Evidence Checklist

Executed and validated in this cycle:

1. `python3 -m compileall kuro_backend main.py playground_runtime`
2. `python3 -m pytest tests/test_frontend_v1_redesign.py tests/test_krc_navigation_profile.py -q`
3. `python3 -m pytest tests/test_api_sse_contract.py tests/test_tools_v2.py tests/test_playground_api.py -x --tb=short`
4. `python3 -m pytest tests/ -x --tb=short`
5. Manual/automasi UI pass (playback + quick interaction smoke) for menu clickability, sidebar hide/open, header toggle, composer `+`, and three-dots session actions.

> Catatan: item 5 dilakukan via local browser validation (Playwright where available) dengan fokus on/off-screen layout, overlay/click target overlap, dan fitur menu.

## Menu Audit Automation (Prototype vs KRC)

- Script: `scripts/compare_krc_prototype_menus.py`
- Command:
  - `python3 scripts/compare_krc_prototype_menus.py --markdown docs/enterprise_refactor/20_krc_ui_prototype_menu_matrix.md`
- Latest hasil match:
  - Sidebar parity: **3/3 matched** (Research Console, Knowledge, Ingestion)
  - Composer parity: **9/9 matched** (`Add Photos & Files`, `Recent Files`, `Deep Research`, `Web Search`, `Agent Mode`, `Task`, `Reminder`, `Market Analysis`, `Playground`)
  - Header parity: **2/2 matched** (`Normal`, `Playground`)
  - Admin signal parity: Administration Settings + Sign Out tersedia
  - Chat session actions from JS: `Pin`, `Rename`, `Export`, `Delete`
- Generated screenshots from side-by-side checks were kept in:
  - `tmp/kuro_main_1920.png`
  - `tmp/proto_1920.png`
  - `tmp/krc_vs_prototype_1920.png`

## Rekomendasi lanjutan

1. Jalankan script audit menu secara rutin (`scripts/compare_krc_prototype_menus.py`) agar regresi menu langsung ketauan saat UI berubah.
2. Jika ada regressi klik/overlay, fokuskan perbaikan pada z-index + pointer-events area pada `.kuro-composer-menu` dan `.session-actions`.
3. Jika perlu exact pixel parity, sinkronisasi spacing dengan `@media` tuning di breakpoint 1366/768/390.
