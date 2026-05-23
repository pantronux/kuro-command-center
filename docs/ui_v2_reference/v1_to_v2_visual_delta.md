# V1 to V2 Visual Delta

## What V2 Improves

- Cleaner dark gray visual hierarchy.
- Sidebar focuses on chats and sessions.
- Tools and admin controls move away from the main sidebar.
- Composer uses a single plus menu instead of scattered action buttons.
- Native drawers and modals replace browser prompts.
- Model selector sits near the send button.
- Welcome state is more intentional.

## What V1 Still Does Better Functionally

- Production chat streaming already works.
- Uploads, drag/drop, file previews, and export are wired.
- Admin backend protections already exist.
- Playground routes already exist and should not be forked.
- Market HUD and websocket dashboard updates are already integrated.

## What Cannot Be Ported Yet

- Deep Research drawer.
- Governed Agent Mode.
- Task and Reminder creation.
- Market V2 drawer.
- Full Administration Settings control plane.
- Per-session chat settings persistence.
- Expanded V2 streaming event taxonomy.

## Why Production Cutover Is Postponed

The visual prototype is useful, but the backend contracts and regression tests
are not complete enough for a safe full replacement. The practical path is to
port visual pieces into V1 in small, tested phases.

