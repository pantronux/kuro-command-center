# KURO AI — UI Prototype Porting Codex Prompt

**Purpose:**  
Port the visual design direction from `pantronux/Kuro-UI-Prototype` into the main `pantronux/kuro-ai` repository safely, while keeping the production UI on the current working V1 frontend.

**Important status:**  
UI V2 is postponed as a production cutover. The prototype is a design reference only. Do **not** replace the working V1 frontend or break existing frontend-backend wiring.

**Reference repositories:**
- Main Kuro repository: `https://github.com/pantronux/kuro-ai`
- UI prototype repository: `https://github.com/pantronux/Kuro-UI-Prototype`

**Recommended commit message:**  
`UI Reference Port: import Kuro UI prototype design assets safely`

---

## 0. Critical Rule

The current Kuro UI V1 remains production.

```text
KURO_FRONTEND_V2_ENABLED=false
```

Do not switch the default frontend.

Do not replace existing `web_interface/templates/index.html` or `web_interface/static/js/app.js` with prototype code.

The goal is:

```text
prototype repo
→ extract design language and useful components
→ create safe reference/prototype files inside main Kuro repo
→ document a future porting plan
→ preserve all V1 behavior
```

---

## 1. Context From Current Main Repository

The current frontend inventory states that the main dashboard is primarily:

```text
web_interface/templates/index.html
web_interface/static/js/app.js
web_interface/static/css/style.css
```

Current UI already contains important working production behavior:

```text
- Jinja dashboard template
- SSE chat streaming parser
- sessions
- drafts
- sidebar
- admin nav guards
- uploads
- drag/drop
- file preview
- search
- export
- WebSocket dashboard updates
- market HUD polling
- playground calls
```

Do not regress these.

Known risks from the current frontend inventory:

```text
- app.js is large and owns many workflows
- CDN dependencies are runtime-critical
- markdown rendering needs sanitization review
- admin visibility guards are UX-only and must not be treated as security
- feature availability should eventually be driven by /api/capabilities
- SSE contract must be preserved
```

---

## 2. High-Level Goal

Create a safe UI reference port that can later be wired into production.

The prototype design direction:

```text
- dark gray Kuro AI interface
- teal accent
- ChatGPT/Claude-like layout
- left sidebar focused on chats/sessions
- top-right profile menu for tools/system/admin/settings
- composer with single + action menu
- native drawers/modals instead of window.prompt
- model selector near composer
- temperature/session controls
- welcome screen
- playground as first-class runtime surface
- no fake tools
- no user/Kuro photos, initials/monograms only
```

---

## 3. Hard Constraints

```text
1. Do not replace production V1 UI.
2. Do not wire UI V2 as default.
3. Do not break:
   - login
   - existing chat
   - /api/chat/stream
   - uploads
   - session list
   - pin/rename/delete
   - export
   - playground
   - system status
   - admin protections
   - market HUD
   - WebSocket dashboard
4. Do not add React/Vite/build dependency to the main app unless already present and explicitly needed.
5. Do not require a frontend build step for current production app.
6. Do not copy prototype runtime code blindly.
7. Do not expose secrets.
8. Do not expose admin controls to non-admin users.
9. Do not use window.prompt for UX.
10. Do not add fake image generation or unsupported tools.
11. Do not make real API calls in tests.
12. Keep all new prototype/reference routes behind safe docs/reference paths or explicit feature flag.
```

---

## 4. Required Output In Main Repository

Create a reference area:

```text
docs/ui_v2_reference/
  README.md
  design_tokens.md
  screenshot_mapping.md
  component_mapping.md
  porting_plan.md
  deferred_wiring.md
```

Create prototype/static export area:

```text
web_interface/prototypes/ui_v2/
  index_static.html
  v2_reference.css
  v2_reference.js
  README.md
```

Optional, only if safe:

```text
web_interface/templates/index_v2_reference.html
web_interface/static/css/v2_reference.css
web_interface/static/js/app_v2_reference.js
```

These must be reference-only, not production default.

---

## 5. Fetch Prototype Repository

Use the UI prototype repository as design reference:

```text
https://github.com/pantronux/Kuro-UI-Prototype
```

Tasks:

```text
1. Inspect repository structure.
2. Identify app entry files.
3. Identify design tokens/colors/spacing.
4. Identify reusable components/states:
   - sidebar
   - header
   - welcome screen
   - chat message layout
   - composer
   - plus menu
   - profile menu
   - admin settings
   - deep research drawer
   - market drawer
   - playground runtime
   - chat settings
   - rename/delete modals
5. Do not import large dependencies into main Kuro.
6. Translate useful visual patterns into static HTML/CSS/vanilla JS reference.
```

---

## 6. Screenshot/Page-by-Page Design Port

Create `docs/ui_v2_reference/screenshot_mapping.md`.

For each screenshot/state, document:

```text
- State name
- Visual elements
- User action
- Existing Kuro backend routes involved
- Current V1 equivalent
- Future V2 wiring needed
- Risk level
- Porting status: reference only / safe to port now / requires backend contract
```

Cover these states:

### Page 1 — Chat View
- left sidebar with New Chat, search, pinned/recent sessions, user card
- header with persona/runtime label, chat title, Normal/Playground toggle, search, theme, profile
- main chat message stream
- composer at bottom
- model selector near send button
- Porting target: reference only for layout and visual polish; do not replace current chat stream parser.

### Page 2 — Welcome Screen
- centered Kuro monogram
- greeting
- quick chips/actions
- composer remains available
- Porting target: safe future enhancement if no chat selected or new chat is empty; requires current session state awareness.

### Page 3 — Single Plus Menu
- one + menu in composer
- Add files, Recent files, Deep Research, Web Search, Agent Mode, Task, Reminder, Market, Playground
- Porting target: reference only until Tools V2/Deep Research/Task/Reminder/Market routes are stable; existing file upload can be mapped first.

### Page 4 — Deep Research Drawer
- native drawer/modal
- query input
- sources options
- depth
- start/cancel
- no window.prompt
- Porting target: reference only until Deep Research V2 endpoint exists.

### Page 5 — Market Analysis Drawer
- symbol input
- include news toggle
- analyze button
- inline result
- freshness/sentiment/source quality area
- Porting target: future Market V2 UI; must not claim financial certainty; must not support auto-trading.

### Page 6 — Session Controls
- context menu for rename/pin/delete
- rename modal
- delete confirmation modal
- pinned delete warning
- Porting target: safe to port visually if existing session endpoints remain unchanged.

### Page 7 — Profile Menu and Administration Settings
- profile dropdown
- Administration Settings only for admin
- Tools
- Model Settings
- Logout
- Porting target: safe visual reference; preserve backend admin enforcement; non-admin must never see admin menu.

### Page 8 — Administration Settings Modal
- modal/drawer style admin control plane
- System Status, Storage Health, Memory V3, Provider/Model Settings, AI Temperature, Runtime Settings, Market Sentinel, Ingestion Center, Evaluation, Backup, Telegram, Feature Flags
- Porting target: reference only until endpoints are available and stable; backend admin-only remains mandatory.

### Page 9 — Non-Admin State
- no Administration Settings menu
- model settings/logout remain available
- Porting target: must be enforced both UI and backend.

### Page 10 — Playground Runtime
- Playground toggle
- playground runtime panel
- session controls
- provider checklist
- execution prompt
- quick checks
- output panel
- Porting target: reference only; current playground routes must not break.

### Page 11 — Chat Settings
- model selector
- temperature
- per-session settings
- safe aliases only
- Porting target: requires provider registry and session settings backend; reference only until stable.

### Page 12 — Design Tokens and Execution Notes
- dark gray tokens
- teal accent
- border/radius system
- no photos
- monograms only
- background integration
- Porting target: safe to port into reference CSS; do not override production style globally yet.

---

## 7. Static Reference HTML Requirements

Create:

```text
web_interface/prototypes/ui_v2/index_static.html
web_interface/prototypes/ui_v2/v2_reference.css
web_interface/prototypes/ui_v2/v2_reference.js
```

Requirements:

```text
1. Dependency-free.
2. No React runtime.
3. No build step.
4. No backend API calls.
5. Pure visual/interaction reference.
6. Uses static/mock data only.
7. Must clearly show a banner/comment that it is not production.
8. Must include all major states:
   - chat
   - welcome
   - plus menu
   - deep research drawer
   - market drawer
   - rename/delete modal
   - profile menu
   - admin settings
   - non-admin state toggle
   - playground runtime
   - chat settings
9. Must use Kuro dark gray design tokens.
10. Must not contain real secrets or real user data beyond mock placeholders.
```

---

## 8. Do Not Wire These Yet

Do not wire these to production routes in this prompt:

```text
- Deep Research
- Web Search
- Agent Mode
- Task
- Reminder
- Market V2
- Memory V3 admin
- Provider admin settings
- Telegram admin
- Feature flags admin
```

Only document target endpoints where known.

---

## 9. What Can Be Safely Ported Later

Document in `docs/ui_v2_reference/porting_plan.md`.

Safe early candidates:

```text
1. CSS design tokens
2. session context menu visual style
3. rename/delete modal visual style
4. composer model selector visual placement, if backend already supports /api/models
5. welcome empty-chat state
6. profile menu visual style
7. admin settings entry point visibility logic
```

Requires backend contract first:

```text
1. Deep Research drawer
2. Agent Mode
3. Task/Reminder
4. Market V2 drawer
5. Memory V3 admin tab
6. Provider health/admin tab
7. Playground V2 panel
8. Chat V2 SSE event expansion
```

---

## 10. Tests To Add

Create:

```text
tests/test_ui_v2_reference_port.py
```

Tests:

```text
1. Reference files exist:
   - docs/ui_v2_reference/README.md
   - docs/ui_v2_reference/design_tokens.md
   - docs/ui_v2_reference/screenshot_mapping.md
   - docs/ui_v2_reference/component_mapping.md
   - docs/ui_v2_reference/porting_plan.md
   - docs/ui_v2_reference/deferred_wiring.md
   - web_interface/prototypes/ui_v2/index_static.html
   - web_interface/prototypes/ui_v2/v2_reference.css
   - web_interface/prototypes/ui_v2/v2_reference.js

2. Production UI files still exist:
   - web_interface/templates/index.html
   - web_interface/static/js/app.js

3. Reference HTML contains:
   - Kuro AI
   - New Chat
   - Administration Settings
   - Deep Research
   - Market Analysis
   - Playground Runtime
   - Chat Settings

4. Reference HTML/CSS/JS must not contain:
   - GEMINI_API_KEY
   - OPENAI_API_KEY
   - ANTHROPIC_API_KEY
   - DEEPSEEK_API_KEY
   - TELEGRAM_TOKEN
   - SERPER_API_KEY
   - sk-
   - real .env values

5. Production index.html must not be replaced by prototype:
   - It should still contain existing production markers from current Kuro UI.
   - Do not assert too strictly; use safe markers based on current file.

6. `KURO_FRONTEND_V2_ENABLED` must remain false by default if config exists.

7. No new test makes real network calls.
```

If current tests exist for V1 redesign, do not weaken them.

---

## 11. Optional Visual Diff Documentation

If easy, create:

```text
docs/ui_v2_reference/v1_to_v2_visual_delta.md
```

Include:

```text
- What V2 improves visually
- What V1 still does better functionally
- What cannot be ported yet
- Why V2 production cutover is postponed
```

---

## 12. Documentation Details

### README.md

Must explain:

```text
- This is a reference-only UI port.
- Kuro production remains on UI V1.
- UI V2 is postponed because frontend-backend wiring is incomplete.
- Prototype repo is used for design inspiration.
- Future cutover requires separate backend contract and regression tests.
```

### design_tokens.md

Must include:

```text
- colors
- typography
- radius
- spacing
- shadows
- component states
```

### component_mapping.md

Map prototype components to Kuro production equivalents:

```text
Prototype Sidebar -> current chat drawer/sidebar
Prototype Header -> current dashboard header/persona/runtime controls
Prototype Plus Menu -> current upload/export/tool controls
Prototype Profile Menu -> current user/admin controls
Prototype Admin Settings -> current admin/system modals/routes
Prototype Playground -> current /api/playground/* UI
Prototype Composer -> current sendMessage/upload/SSE logic
```

### deferred_wiring.md

Must include:

```text
- UI V2 deferred list
- backend dependencies
- required endpoints
- test requirements before enabling
- rollback plan
```

---

## 13. Acceptance Criteria

```text
[ ] Prototype repository inspected.
[ ] UI V2 reference docs created.
[ ] Static reference HTML/CSS/JS created.
[ ] Production V1 files not replaced.
[ ] KURO_FRONTEND_V2_ENABLED remains false by default.
[ ] Tests added.
[ ] No secrets in reference files.
[ ] No real network calls in tests.
[ ] docs explain UI V2 postponed.
[ ] Existing frontend tests pass.
[ ] Existing chat/SSE tests pass.
```

Run:

```bash
python -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
```

If frontend tests are available:

```bash
pytest tests/ -x --tb=short -k "frontend or ui or template"
```

---

## 14. Stop Conditions

Stop and revert if:

```text
- Existing production UI is replaced.
- Existing chat streaming breaks.
- Existing upload breaks.
- Existing admin visibility tests fail.
- UI V2 becomes default route unintentionally.
- Production app requires React/build step.
- Public UI exposes admin controls to non-admin.
- Reference files contain secrets.
- Tests require external network.
```

---

## 15. Future Cutover Plan

Do not implement cutover now, but document this plan:

```text
Phase UI-1:
Port design tokens into production style.css carefully.

Phase UI-2:
Port session context menu and modals only.

Phase UI-3:
Port composer plus menu only for existing upload/recent-file actions.

Phase UI-4:
Port profile menu and admin settings entry point, preserving server-side auth.

Phase UI-5:
Wire model selector to /api/models and per-session settings.

Phase UI-6:
Wire Deep Research / Task / Reminder / Market only after backend APIs are stable.

Phase UI-7:
A/B switch via KURO_FRONTEND_V2_ENABLED.

Phase UI-8:
Only then consider full V2 layout replacement.
```

---

## 16. Final Codex Instruction

```text
Port the Kuro UI prototype as a safe reference implementation into the main Kuro repository.

Do not replace production UI.
Do not enable UI V2.
Do not break existing frontend-backend wiring.
Create docs, static reference files, and tests.
Keep the current UI V1 as production.
```
