# OpenClaw skill: `harvest_gemini_share`

Scrapes a **public** Gemini share link and writes a Markdown file under:

`/home/kuro/research_library/scraped_sources/gemini-share_{timestamp}.md`

## Requirements

```bash
pip install playwright
playwright install chromium
```

## Parameters (JSON `params` from Kuro)

| Field | Required | Description |
|-------|----------|-------------|
| `share_url` | Yes | Full URL, e.g. `https://gemini.google.com/share/xxxx` |
| `output_dir` | No | Override output directory (default: `/home/kuro/research_library/scraped_sources`) |

## Response contract (HTTP body to Kuro)

**Success:**

```json
{
  "ok": true,
  "skill_name": "harvest_gemini_share",
  "saved_path": "/home/kuro/research_library/scraped_sources/gemini-share_20260116_120000.md",
  "data_mutation": true,
  "chars_written": 12345
}
```

**Failure (timeout, bot wall, empty content):**

```json
{
  "ok": false,
  "skill_name": "harvest_gemini_share",
  "error_code": "blocked_or_timeout",
  "user_message": "Master, akses ke link Gemini ini tersumbat (Timeout/Bot Protection). Mohon cek kembali atau berikan file PDF-nya saja."
}
```

## Registering on the OpenClaw daemon

1. Copy this folder to your OpenClaw skills directory (or add to `PYTHONPATH`).
2. In the daemon handler for `POST /execute`, when `skill_name == "harvest_gemini_share"`:
   - `from harvest_gemini_share import run` (adjust import path).
   - `result = run(body.get("params") or {})`
   - Return HTTP 200 with `result` as JSON body (Kuro treats 200 + JSON as success; map `ok: false` inside body if your daemon wraps differently — align with your existing `general_execution` pattern).

## Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `HARVEST_GEMINI_TIMEOUT_MS` | `60000` | Playwright navigation timeout |
| `HARVEST_GEMINI_HEADLESS` | `1` | Set `0` to show browser (debug) |
| `HARVEST_GEMINI_OUTPUT_DIR` | see default above | Override output root |

## Notes

- Gemini may show sign-in or bot challenges; headless automation often fails. The skill returns `blocked_or_timeout` and the user message above.
- Selectors: primary `.message-content`; fallbacks are documented in `harvest_gemini_share.py`.

## Manual test

```bash
python3 harvest_gemini_share.py "https://gemini.google.com/share/YOUR_ID"
```
