# Design Tokens

The prototype uses a Tailwind/Radix token set in `artifacts/kuro-ai/src/index.css`.
The reference export translates the dark theme into plain CSS custom properties.

## Colors

| Token | Value | Usage |
| --- | --- | --- |
| `--bg-primary` | `#1a1a1f` | App canvas and chat background |
| `--bg-sidebar` | `#18181d` | Sidebar |
| `--bg-card` | `#2a2a32` | Message cards, composer, panels |
| `--bg-popover` | `#222228` | Menus and drawers |
| `--bg-muted` | `#222229` | Secondary controls |
| `--border-subtle` | `#2e2e38` | Dividers and panel borders |
| `--accent-primary` | `#14b8a6` | Primary action, active state |
| `--accent-soft` | `rgba(20, 184, 166, 0.16)` | Pills and selected rows |
| `--text-primary` | `#e8e8ee` | Body text and headings |
| `--text-secondary` | `#9090a0` | Metadata, labels, placeholder text |
| `--status-error` | `#7c1f1f` | Destructive surfaces |

## Typography

- Font stack: Inter first, with system UI fallback. Production should avoid
  adding a blocking remote font unless bundled safely.
- Chat body: 14px to 15px, line-height 1.5.
- Sidebar row: 13px.
- Section labels: 10px, uppercase, 0.08em letter spacing.
- Headers: 16px to 24px, 700 weight.

## Radius

| Token | Value | Usage |
| --- | --- | --- |
| `--radius-sm` | `6px` | Chat rows, compact buttons |
| `--radius-md` | `8px` | Inputs, profile menu rows |
| `--radius-lg` | `10px` | Base Radix card/dialog radius |
| `--radius-xl` | `14px` | Composer, cards, and large panels |

## Spacing

- Sidebar width: 260px.
- Header height: 52px.
- App frame: 16px sidebar top section, 12px sidebar list padding.
- Composer shell: max-width 896px, 8px inner padding.
- Drawer and modal body: 20px to 24px.
- Chat stream gap: 18px to 24px.
- Sidebar list gap: 8px between groups, 2px between rows.

## Shadows

The base UI avoids decorative shadows. Shadows are reserved for elevated menus,
drawers, and modals:

- Menu: `0 24px 56px rgba(0, 0, 0, 0.45)`
- Modal: `0 16px 48px rgba(0, 0, 0, 0.5)`

## Component States

- Hover: switch background to `--bg-hover`.
- Active: switch background to `--bg-active` plus a teal indicator when useful.
- Disabled: opacity 0.45 and cursor `not-allowed`; keep explanation visible.
- Destructive: `--status-error`, never hidden behind ambiguous icons.
