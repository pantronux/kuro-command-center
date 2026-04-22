/**
 * Kuro V6.1 — Live2D "Hijiki" mascot manager.
 *
 * Responsibilities:
 *   1. Dynamically load the Live2D Cubism Core + pixi.js + pixi-live2d-display.
 *      Offline-first: try `/static/vendor/live2d/*` first; fall back to the
 *      public Live2D CDN + jsDelivr when the local copies are absent.
 *   2. Create a PIXI application bound to `#live2d-canvas`, load the Hijiki
 *      model from `/profile/live2d/hijiki/runtime/hijiki.model3.json`, and
 *      start the Idle motion group.
 *   3. Expose a minimal public surface on `window.kuroLive2D`:
 *        - setLipSyncValue(v)  -> writes PARAM_MOUTH_OPEN_Y each frame the
 *                                  TTS pipeline hands in a value in [0, 1].
 *        - playTalkMotion()    -> starts a "Tap" motion at FORCE priority.
 *        - returnToIdle()      -> restores Idle and clears the mouth.
 *
 * Everything fails silently so the dashboard keeps working even when the
 * Live2D SDK cannot be loaded (license-gated binary, offline, etc.).
 *
 * --- Header Doc ---
 * Purpose: Live2D Hijiki avatar loader + motion controller used by the dashboard HUD.
 * Caller: index.html (script tag) + app.js (speak/idle transitions driven by chat events).
 * Dependencies: pixi.js, pixi-live2d-display, Cubism Core (loaded from /static/vendor/live2d or CDN fallback).
 * Main Functions: kuroLive2DInit, kuroLive2DSpeak, returnToIdle, kuroLive2DSetExpression.
 * Side Effects: Network fetches for SDK + model assets; DOM mutation on `#live2d-canvas`; RAF loop.
 */

const LOCAL_VENDOR_BASE = "/static/vendor/live2d";
const CDN_CUBISM_CORE = "https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js";
const CDN_PIXI = "https://cdn.jsdelivr.net/npm/pixi.js@7.3.2/dist/pixi.min.js";
const CDN_PIXI_LIVE2D = "https://cdn.jsdelivr.net/npm/pixi-live2d-display@0.4.0/dist/cubism4.min.js";

const MODEL_URL = "/profile/live2d/hijiki/runtime/hijiki.model3.json";

const MOTION_GROUP_IDLE = "Idle";
const MOTION_GROUP_TAP = "Tap";
const LIP_SYNC_PARAM = "PARAM_MOUTH_OPEN_Y";

let _initPromise = null;
let _state = {
    app: null,
    model: null,
    ready: false,
    lipSyncValue: 0,
    coreModel: null,
};

function _log(...args) {
    try { console.log("[Kuro Live2D]", ...args); } catch (_) {}
}

function _warn(...args) {
    try { console.warn("[Kuro Live2D]", ...args); } catch (_) {}
}

function _headOk(url) {
    return fetch(url, { method: "HEAD", cache: "no-store" })
        .then((r) => r.ok)
        .catch(() => false);
}

function _loadScript(url) {
    return new Promise((resolve, reject) => {
        const existing = document.querySelector(`script[data-live2d-src="${url}"]`);
        if (existing) {
            if (existing.dataset.live2dReady === "1") {
                resolve();
                return;
            }
            existing.addEventListener("load", () => resolve(), { once: true });
            existing.addEventListener("error", () => reject(new Error(`script error: ${url}`)), { once: true });
            return;
        }
        const s = document.createElement("script");
        s.src = url;
        s.async = false;
        s.dataset.live2dSrc = url;
        s.addEventListener("load", () => { s.dataset.live2dReady = "1"; resolve(); }, { once: true });
        s.addEventListener("error", () => reject(new Error(`script error: ${url}`)), { once: true });
        document.head.appendChild(s);
    });
}

async function _loadPreferred(localName, cdnUrl) {
    const localUrl = `${LOCAL_VENDOR_BASE}/${localName}`;
    if (await _headOk(localUrl)) {
        await _loadScript(localUrl);
        _log(`loaded local ${localName}`);
        return;
    }
    await _loadScript(cdnUrl);
    _log(`loaded CDN ${localName}`);
}

async function _loadSdk() {
    await _loadPreferred("live2dcubismcore.min.js", CDN_CUBISM_CORE);
    await _loadPreferred("pixi.min.js", CDN_PIXI);
    await _loadPreferred("pixi-live2d-display.min.js", CDN_PIXI_LIVE2D);

    if (!window.PIXI) throw new Error("PIXI global missing after load");
    if (!window.PIXI.live2d || !window.PIXI.live2d.Live2DModel) {
        throw new Error("pixi-live2d-display global missing after load");
    }
    if (!window.Live2DCubismCore) {
        throw new Error("Live2DCubismCore global missing after load");
    }
}

function _clamp01(v) {
    if (typeof v !== "number" || Number.isNaN(v)) return 0;
    if (v < 0) return 0;
    if (v > 1) return 1;
    return v;
}

async function initLive2D() {
    if (_initPromise) return _initPromise;
    _initPromise = (async () => {
        const canvas = document.getElementById("live2d-canvas");
        if (!canvas) {
            _warn("no #live2d-canvas element; dock disabled.");
            return;
        }
        try {
            await _loadSdk();
        } catch (e) {
            _warn("SDK load failed; mascot disabled.", e);
            canvas.parentElement && canvas.parentElement.classList.add("live2d-dock--hidden");
            return;
        }

        const PIXI = window.PIXI;
        const Live2DModel = PIXI.live2d.Live2DModel;

        // Hook PIXI Ticker so lip-sync updates each frame.
        if (typeof Live2DModel.registerTicker === "function") {
            try { Live2DModel.registerTicker(PIXI.Ticker); } catch (_) {}
        }

        const app = new PIXI.Application({
            view: canvas,
            autoStart: true,
            backgroundAlpha: 0,
            resolution: window.devicePixelRatio || 1,
            width: canvas.width,
            height: canvas.height,
            antialias: true,
        });
        _state.app = app;

        let model;
        try {
            model = await Live2DModel.from(MODEL_URL, { autoInteract: false });
        } catch (e) {
            _warn("failed to load Hijiki model at", MODEL_URL, e);
            canvas.parentElement && canvas.parentElement.classList.add("live2d-dock--hidden");
            return;
        }

        // Scale to fit the canvas while preserving aspect ratio.
        const scaleX = canvas.width / model.width;
        const scaleY = canvas.height / model.height;
        const scale = Math.min(scaleX, scaleY) * 0.95;
        model.scale.set(scale, scale);
        model.x = (canvas.width - model.width * scale) / 2;
        model.y = (canvas.height - model.height * scale) / 2;
        app.stage.addChild(model);

        _state.model = model;
        _state.coreModel = model.internalModel && model.internalModel.coreModel
            ? model.internalModel.coreModel
            : null;

        // Drive lip-sync every animation frame via the model's update hook.
        if (model.internalModel && typeof model.internalModel.motionManager === "object") {
            try {
                // Before each render pass, push the latest RMS value into the
                // mouth-open parameter so TTS-driven lip-sync overrides the
                // resting pose supplied by physics/motions.
                const origUpdate = model.internalModel.update.bind(model.internalModel);
                model.internalModel.update = (dt, now) => {
                    const ret = origUpdate(dt, now);
                    if (_state.coreModel && typeof _state.coreModel.setParameterValueById === "function") {
                        try {
                            _state.coreModel.setParameterValueById(LIP_SYNC_PARAM, _clamp01(_state.lipSyncValue));
                        } catch (_) {}
                    }
                    return ret;
                };
            } catch (e) {
                _warn("could not hook internalModel.update; lip-sync may stutter.", e);
            }
        }

        // Start idle loop.
        try {
            model.motion(MOTION_GROUP_IDLE, 0, 1); // MotionPriority.IDLE = 1
        } catch (_) {}

        _state.ready = true;
        _log("Hijiki ready.");

        window.kuroLive2D = {
            setLipSyncValue,
            playTalkMotion,
            returnToIdle,
            isReady: () => _state.ready,
        };
    })();
    return _initPromise;
}

function setLipSyncValue(v) {
    _state.lipSyncValue = _clamp01(Number(v));
}

function playTalkMotion() {
    if (!_state.ready || !_state.model) return;
    try {
        // MotionPriority.FORCE = 3 per pixi-live2d-display docs.
        _state.model.motion(MOTION_GROUP_TAP, undefined, 3);
    } catch (e) {
        _warn("playTalkMotion failed:", e);
    }
}

function returnToIdle() {
    _state.lipSyncValue = 0;
    if (!_state.ready || !_state.model) return;
    try {
        _state.model.motion(MOTION_GROUP_IDLE, 0, 1);
    } catch (e) {
        _warn("returnToIdle failed:", e);
    }
}

export { initLive2D, setLipSyncValue, playTalkMotion, returnToIdle };
