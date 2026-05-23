# Porting Plan

UI V2 is a design reference, not a production replacement. Porting should happen
in small slices with rollback-friendly tests.

## Phase UI-1: Tokens

Port the dark gray color tokens, radius scale, and compact spacing into a
production-scoped CSS layer. Avoid global resets and preserve pages outside
`index.html`.

## Phase UI-2: Session Controls

Port the visual treatment for chat rows, pin, rename, delete, and export. Keep
existing session endpoints and replace any browser prompt with native modals.

## Phase UI-3: Composer Plus Menu

Port the single plus menu for existing safe actions first:

- Add photos and files
- Uploaded files
- Existing Tutorial, Intelligence Hub, and Market page links

Keep Deep Research, Agent Mode, Task, Reminder, and Market drawer as disabled or
reference-only until backend contracts exist.

## Phase UI-4: Profile Menu

Move tools and system controls visually into the top-right profile menu while
preserving backend admin checks. Non-admin users must not see Administration
Settings.

## Phase UI-5: Model Settings

Wire model selector and temperature to safe aliases only. Do not expose raw
provider names, API keys, or backend secrets. Store settings per session only
after the session settings contract exists.

## Phase UI-6: Advanced Drawers

Wire Deep Research, Task, Reminder, Market, and Agent Mode only after the backend
provides stable endpoints, validation rules, and audit behavior.

## Phase UI-7: Feature Flag

Only after the previous phases are tested, consider an explicit feature flag or
A/B switch. The default must remain production V1 until the cutover is approved.

## Phase UI-8: Full Layout Replacement

Consider replacing the full layout only after chat streaming, uploads, admin
guards, playground, market HUD, and websocket dashboard updates are covered by
regression tests.

