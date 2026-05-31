# KRC Refocus Phases 2-4 UI and Playground Landing

These phases keep UI V1 and add profile-aware KRC rendering.

## Legacy Mode

`KURO_APP_PROFILE=legacy` keeps the existing dashboard label, chat wording,
profile menu, Market Sentinel link, Telegram admin tab, and chat-first default.

## KRC Mode

`KURO_APP_PROFILE=krc` renders:

- workspace label: `Kuro Research Center`
- sidebar workspace nav for Research Console, Kuro Playground, Knowledge,
  Documents, and research export/report actions
- `Research Console` wording for the chat surface
- Playground-first default mode when no browser runtime preference exists
- a KRC Playground landing surface above the existing Playground runtime
- QA Playground is hidden and disabled by default in KRC mode so Kuro
  Playground stays a single research surface

Daily/bloat items are hidden or de-emphasized in KRC mode:

- QA Playground routes stay behind `KURO_KRC_QA_PLAYGROUND_ENABLED=true`.
- Evaluation UI stays behind `KURO_KRC_EVALUATION_ENABLED=true`.
- Market Sentinel profile/admin links are hidden unless
  `KURO_KRC_MARKET_ENABLED=true`.
- Telegram admin tab remains available by default as an ops command center;
  market controls inside Telegram stay disabled unless `KURO_KRC_MARKET_ENABLED=true`.
- task/reminder composer actions are hidden unless
  `KURO_KRC_DAILY_TASKS_ENABLED=true`.
- generic Agent Mode is hidden unless `KURO_KRC_AGENT_TOOLS_ENABLED=true`.

## Constraints Preserved

- `index.html` remains the production UI V1 shell.
- No Frontend V2 shell was added.
- Existing backend routes, including `/api/chat/stream`, are unchanged.
- Admin-only controls remain conditional on the existing admin context.
