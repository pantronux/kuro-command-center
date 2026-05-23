# Screenshot Mapping

The states below map the actual local prototype source at
`Kuro-UI-Prototype-main/artifacts/kuro-ai/src`.

## Page 1: Chat View

- Visual elements: 260px session-focused sidebar, 52px header, centered
  Normal/Playground toggle, chat stream, bottom composer.
- User action: select a chat, send a message, use message actions.
- Existing routes: `/api/chats`, `/api/chats/{chat_id}/messages`,
  `/api/chat/stream`.
- V1 equivalent: current `index.html` and `app.js` chat dashboard.
- Future wiring: keep SSE parser intact; only port layout and controls.
- Risk: high.
- Porting status: reference only.

## Page 2: Welcome Screen

- Visual elements: centered Kuro monogram, greeting, quick chips, composer.
- User action: start a new chat or open playground.
- Existing routes: same chat stream after first send.
- Prototype source: `pages/Home.tsx`.
- V1 equivalent: current welcome screen logic.
- Future wiring: show only for new or empty chats.
- Risk: medium.
- Porting status: safe future enhancement.

## Page 3: Single Plus Menu

- Visual elements: one composer plus menu with file, recent files, Deep
  Research, Web Search, Agent Mode, Task, Reminder, Market Analysis, Playground.
- User action: open menu and choose an action.
- Existing routes: upload and files modal can map first.
- V1 equivalent: upload button plus scattered tool controls.
- Future wiring: capability-driven disabled states.
- Risk: medium.
- Porting status: partial; file actions safe first.

## Page 4: Deep Research Drawer

- Visual elements: query input, source options, depth, start/cancel.
- User action: create research job.
- Prototype source: `components/drawers/DeepResearchDrawer.tsx`.
- Existing routes: no stable route confirmed for this drawer.
- V1 equivalent: current research controls where available.
- Future wiring: Deep Research V2 endpoint and job lifecycle.
- Risk: high.
- Porting status: reference only.

## Page 5: Market Analysis Drawer

- Visual elements: symbol input, include news toggle, analyze button, result
  summary, freshness and source quality area.
- User action: request market analysis.
- Prototype source: `components/drawers/MarketAnalysisDrawer.tsx`.
- Existing routes: `/api/market/hud`, `/api/sentinel/*`, `/market`.
- V1 equivalent: Market Sentinel page and HUD.
- Future wiring: Market V2 drawer contract.
- Risk: high.
- Porting status: reference only.

## Page 6: Session Controls

- Visual elements: chat context menu, rename modal, delete confirmation modal.
- User action: rename, pin, export, delete.
- Existing routes: chat session endpoints in `main.py`.
- Prototype source: `Sidebar.tsx`, `RenameChatModal.tsx`, `DeleteChatModal.tsx`.
- V1 equivalent: current session list controls.
- Future wiring: native modal UX around existing endpoints.
- Risk: low to medium.
- Porting status: safe visual candidate.

## Page 7: Profile Menu and Administration Settings

- Visual elements: profile dropdown, Tools submenu, Model Settings,
  Administration Settings for admins only.
- User action: open profile menu and navigate tools/settings.
- Existing routes: settings modals, `/tutorial`, `/intelligence`, `/market`,
  admin routes.
- Prototype source: `Sidebar.tsx` and `Header.tsx`.
- V1 equivalent: current user dropdown and sidebar tool nav.
- Future wiring: profile menu visual migration.
- Risk: medium.
- Porting status: safe visual candidate with admin tests.

## Page 8: Administration Settings Modal

- Visual elements: prototype modal uses General, Models, Usage & Limits,
  Security, Integrations, Audit Log. Kuro target expands this to System Status,
  Storage Health, Memory V3, Provider/Model Settings, AI Temperature, Runtime
  Settings, Market Sentinel, Ingestion Center, Evaluation, Backup, Telegram,
  Feature Flags.
- User action: admin opens control plane.
- Existing routes: `/api/admin/*`, system status, backup, ingestion.
- V1 equivalent: separate admin/system/settings modals and routes.
- Future wiring: endpoint-by-endpoint inventory and RBAC.
- Risk: high.
- Porting status: reference only.

## Page 9: Non-Admin State

- Visual elements: profile menu without Administration Settings.
- User action: non-admin opens profile menu.
- Existing routes: backend must still forbid direct admin access.
- V1 equivalent: current admin-only checks.
- Future wiring: server-side role context plus frontend hidden state.
- Risk: medium.
- Porting status: required for any profile menu port.

## Page 10: Playground Runtime

- Visual elements: runtime toggle, session controls, provider checklist,
  execution prompt, quick checks, output panel.
- User action: switch to playground and execute research.
- Existing routes: `/api/playground/*`.
- Prototype source: `pages/Playground.tsx` and
  `components/drawers/PlaygroundRuntimeDrawer.tsx`.
- V1 equivalent: current playground panel.
- Future wiring: visual polish only; no backend fork.
- Risk: high.
- Porting status: reference only.

## Page 11: Chat Settings

- Visual elements: model selector, temperature control, per-session settings.
- User action: change session model or temperature.
- Existing routes: provider registry and future session settings endpoints.
- Prototype source: `components/modals/ChatSettingsModal.tsx`.
- V1 equivalent: current model selector/settings controls.
- Future wiring: safe aliases and per-session persistence.
- Risk: medium.
- Porting status: deferred.

## Page 12: Design Tokens and Execution Notes

- Visual elements: color swatches, spacing, radius, monograms only.
- User action: none; design reference.
- Existing routes: none.
- V1 equivalent: current CSS token migration.
- Future wiring: scoped CSS token port.
- Risk: low.
- Porting status: safe reference.
