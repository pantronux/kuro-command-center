# Component Mapping

| Prototype component | Source file | Production equivalent | Port status | Notes |
| --- | --- | --- | --- |
| Sidebar | `components/layout/Sidebar.tsx` | Current chat session sidebar and drawer logic | Safe visual candidate | Keep session endpoints and pagination untouched. |
| Header | `components/layout/Header.tsx` | Current dashboard header, persona label, runtime toggle | Safe visual candidate | Keep persona state and runtime mode behavior. |
| Composer | `components/chat/Composer.tsx` | Current `sendMessage`, upload, SSE parser | Partial visual candidate | Single plus menu can be ported around existing upload and files hooks. |
| Single plus menu | `components/chat/Composer.tsx` | Current upload, files modal, tools entry points | Partial visual candidate | Upload can wire first; Deep Research, Task, Reminder remain deferred. |
| Profile menu | `Sidebar.tsx`, `Header.tsx` | Current user dropdown, settings, admin controls | Safe visual candidate | Admin entry must render only for admin and remain backend protected. |
| Administration Settings | `components/modals/AdminSettingsModal.tsx` | Current system/settings/admin modals and routes | Reference only | Prototype has generic tabs; Kuro needs enterprise-specific tabs. |
| Chat messages | `pages/Chat.tsx` | Current streaming message renderer | Safe visual candidate | Do not replace SSE event handling or markdown behavior in this phase. |
| Session context menu | `Sidebar.tsx`, rename/delete modals | Current pin, rename, delete, export controls | Safe visual candidate | Replace browser prompts with native modals when endpoint behavior is stable. |
| Deep Research drawer | `components/drawers/DeepResearchDrawer.tsx` | No stable production drawer contract yet | Deferred | Requires a Deep Research endpoint and job state model. |
| Market drawer | `components/drawers/MarketAnalysisDrawer.tsx` | Current Market Sentinel page and HUD APIs | Deferred | Must not claim financial certainty or imply trading automation. |
| Playground Runtime | `pages/Playground.tsx` | Current `/api/playground/*` UI and service | Reference only | This is the closest usable page-level source. |
| Chat Settings | `components/modals/ChatSettingsModal.tsx` | Provider registry, model aliases, temperature controls | Deferred | Requires per-session settings contract. |

## Production Hooks To Preserve

- `composerActionMenu`
- `fileInput`
- `messageInput`
- `sendBtn`
- `chatSessionsList`
- `personaAccordionBtn`
- `runtimeModeToggle`
- `playgroundPanel`
- `userDropdownMenu`

## Future Extraction Rule

Only extract a visual pattern when the production DOM hook can remain stable or
the migration has a dedicated compatibility layer and test coverage.
