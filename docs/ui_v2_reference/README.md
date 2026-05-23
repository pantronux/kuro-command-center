# Kuro AI UI V2 Reference Port

This directory is a reference-only UI port. It documents the design direction
from the local prototype copy at `Kuro-UI-Prototype-main/` without replacing the
production Kuro V1 frontend.

Production remains on:

- `web_interface/templates/index.html`
- `web_interface/static/js/app.js`
- `web_interface/static/css/style.css`

UI V2 production cutover is postponed because the visual prototype is ahead of
several backend contracts: Deep Research V2, Task and Reminder flows, governed
Agent Mode, Market V2 drawer data, Memory V3 admin tabs, and expanded streaming
events.

## Source Inspection

The prototype source is a pnpm workspace under `Kuro-UI-Prototype-main/`.
The design app lives in `artifacts/kuro-ai/` and uses React, Vite, Tailwind,
Radix UI primitives, Wouter, and lucide-react.

Important prototype files inspected:

- `artifacts/kuro-ai/src/index.css`
- `artifacts/kuro-ai/src/components/layout/AppLayout.tsx`
- `artifacts/kuro-ai/src/components/layout/Sidebar.tsx`
- `artifacts/kuro-ai/src/components/layout/Header.tsx`
- `artifacts/kuro-ai/src/components/chat/Composer.tsx`
- `artifacts/kuro-ai/src/components/drawers/DeepResearchDrawer.tsx`
- `artifacts/kuro-ai/src/components/drawers/MarketAnalysisDrawer.tsx`
- `artifacts/kuro-ai/src/components/drawers/PlaygroundRuntimeDrawer.tsx`
- `artifacts/kuro-ai/src/components/modals/AdminSettingsModal.tsx`
- `artifacts/kuro-ai/src/components/modals/ChatSettingsModal.tsx`
- `artifacts/kuro-ai/src/components/modals/RenameChatModal.tsx`
- `artifacts/kuro-ai/src/components/modals/DeleteChatModal.tsx`
- `artifacts/kuro-ai/src/pages/Home.tsx`
- `artifacts/kuro-ai/src/pages/Chat.tsx`
- `artifacts/kuro-ai/src/pages/Playground.tsx`

The reference export translates those visual patterns into dependency-free
HTML/CSS/vanilla JS.

## Safety Rules

- Do not route production traffic to this reference.
- Do not replace the V1 Jinja template or `app.js`.
- Do not introduce React, Vite, or a frontend build step.
- Do not wire mock controls to real backend routes.
- Do not expose admin controls to non-admin users in production.
- Keep admin-only backend enforcement in `main.py`.

## Reference Output

The static prototype lives at:

- `web_interface/prototypes/ui_v2/index_static.html`
- `web_interface/prototypes/ui_v2/v2_reference.css`
- `web_interface/prototypes/ui_v2/v2_reference.js`

It is dependency-free and uses only mock data. It exists to help future UI
porting work converge on one visual language before any production cutover.
