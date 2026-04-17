# Kuro V6.1 — Live2D Vendor Cache (Optional, Offline-First)

`live2d_manager.js` will try to load the Live2D SDK from this folder **before**
falling back to the public CDN. Dropping the files below here makes the
dashboard mascot work fully offline and avoids third-party network calls.

## Expected filenames

Place these files directly inside `web_interface/static/vendor/live2d/`:

| File                             | Purpose                                 |
| -------------------------------- | --------------------------------------- |
| `live2dcubismcore.min.js`        | Cubism Core runtime (license-gated)     |
| `pixi.min.js`                    | pixi.js v7.x                            |
| `pixi-live2d-display.min.js`     | pixi-live2d-display v0.4.x (Cubism 4)   |

If a file is missing, the loader automatically retries from the CDN.

## Download URLs (manual — we never commit these binaries)

- **Live2D Cubism Core JS** — governed by the Live2D Proprietary Software
  License. Download from
  <https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js>
  after agreeing to
  <https://www.live2d.com/en/sdk/license/>.
- **pixi.js v7.3.2** — MIT. jsDelivr copy:
  <https://cdn.jsdelivr.net/npm/pixi.js@7.3.2/dist/pixi.min.js>
- **pixi-live2d-display v0.4.0 (Cubism 4 bundle)** — MIT. jsDelivr copy:
  <https://cdn.jsdelivr.net/npm/pixi-live2d-display@0.4.0/dist/cubism4.min.js>
  (save it locally as `pixi-live2d-display.min.js`).

## Hijiki model

The model itself lives outside this folder at
`profile/live2d/hijiki/runtime/hijiki.model3.json` and is served by the
`/profile` FastAPI static mount (registered in `main.py`). Nothing to copy —
just keep the `profile/` directory intact.

## Verifying the offline path

1. Drop the three JS files above into this folder.
2. Start Kuro and open the dashboard; the browser DevTools Network tab
   should show the three scripts served from `/static/vendor/live2d/` with
   status 200, and no requests to `cubism.live2d.com` or `cdn.jsdelivr.net`.
3. The Hijiki mascot should appear in the bottom-right dock, idling. Type a
   message so Kuro speaks — the mouth parameter drives with the TTS audio.

## Troubleshooting

- **Hijiki not showing** — open DevTools, look for `[Kuro Live2D]` log lines.
  SDK failures hide the dock via the `live2d-dock--hidden` class.
- **Mouth not moving** — the browser blocks `createMediaElementSource` until
  the page has received a user gesture; click anywhere first.
- **Model appears oversized** — the manager auto-fits to the 300x380 canvas;
  edit the canvas dimensions in `index.html` if you want a taller dock.
