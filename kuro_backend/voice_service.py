"""Kuro AI V6.0 "Sovereign" — Pluggable Text-to-Speech service.

Two engines:

- ``piper`` (default; fully offline via ``piper-tts`` + ``onnxruntime``).
  Ships configured for the ``en_GB-alan-medium`` voice — the calm UK
  butler Kuro uses to channel Sebastian Michaelis.
- ``gtts``  (fallback; online, multi-language).

Engine selection is controlled by the ``KURO_TTS_ENGINE`` env var or per-call
argument. Synthesised audio is cached under ``media/tts/`` keyed by a SHA-1
of ``(engine|lang|voice|length_scale|pitch_shift|text)`` so differently-tuned
variants never collide. A 50 MB LRU cap keeps the cache bounded.

Voice character controls (V6.0):

- ``KURO_PIPER_LENGTH_SCALE`` (default ``1.1``) slows Alan down for elegance.
- ``KURO_TTS_PITCH_SHIFT`` (default ``0.93``) post-processes the WAV with
  ffmpeg's ``asetrate=<rate>*shift,atempo=1/shift`` to drop pitch ~7%
  without warping tempo. A missing / broken ffmpeg degrades gracefully to
  un-shifted audio.

Install the Alan voice once:

    mkdir -p ~/.kuro/piper
    curl -L -o ~/.kuro/piper/en_GB-alan-medium.onnx \\
      https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx
    curl -L -o ~/.kuro/piper/en_GB-alan-medium.onnx.json \\
      https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json

This module never imports the heavy engines at import-time — both imports
live behind lazy helpers so the FastAPI server keeps booting even when
gTTS or piper are not installed.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import threading
import wave
from pathlib import Path
from typing import Dict, Final, Optional, Tuple

logger = logging.getLogger(__name__)

_CACHE_DIR: Final[Path] = Path(
    os.getenv("KURO_TTS_CACHE_DIR") or "media/tts"
).resolve()
_MAX_TEXT_LEN: Final[int] = 2000
_CACHE_CAP_BYTES: Final[int] = 50 * 1024 * 1024  # 50 MB
_CACHE_TTL_SECONDS: Final[int] = 7 * 24 * 3600   # 7 days
_SUPPORTED_ENGINES: Final[Tuple[str, ...]] = ("gtts", "piper")
_DEFAULT_ENGINE: Final[str] = "piper"
_DEFAULT_LANG: Final[str] = "en"
_DEFAULT_PIPER_VOICE: Final[str] = "~/.kuro/piper/en_GB-alan-medium.onnx"

# Pitch-shift bounds: keep the Sebastian character without sounding distorted.
_PITCH_SHIFT_MIN: Final[float] = 0.80
_PITCH_SHIFT_MAX: Final[float] = 1.20
# Length-scale bounds: 0.7x .. 1.5x covers "brisk" to "deliberately elegant".
_LENGTH_SCALE_MIN: Final[float] = 0.6
_LENGTH_SCALE_MAX: Final[float] = 1.6

_cache_lock = threading.Lock()


class TTSError(RuntimeError):
    """Raised when synthesis cannot be completed (missing dep, model, etc)."""


# ---------------------------------------------------------------------------
# Env / settings helpers
# ---------------------------------------------------------------------------

def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("[TTS] %s=%r invalid float, using default %.3f",
                       name, raw, default)
        return default
    if value < lo or value > hi:
        logger.warning("[TTS] %s=%.3f out of [%.2f, %.2f], clamping",
                       name, value, lo, hi)
        return max(lo, min(hi, value))
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _current_length_scale() -> float:
    return _env_float(
        "KURO_PIPER_LENGTH_SCALE", 1.1, _LENGTH_SCALE_MIN, _LENGTH_SCALE_MAX,
    )


def _current_pitch_shift() -> float:
    if not _env_bool("KURO_TTS_FFMPEG_ENABLED", True):
        return 1.0
    return _env_float(
        "KURO_TTS_PITCH_SHIFT", 0.93, _PITCH_SHIFT_MIN, _PITCH_SHIFT_MAX,
    )


def _ensure_cache_dir() -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def _resolve_engine(engine: Optional[str]) -> str:
    selected = (
        engine or os.getenv("KURO_TTS_ENGINE") or _DEFAULT_ENGINE
    ).strip().lower()
    if selected not in _SUPPORTED_ENGINES:
        raise TTSError(f"unsupported TTS engine: {selected}")
    return selected


def _cache_key(
    engine: str,
    lang: str,
    voice: Optional[str],
    text: str,
    *,
    length_scale: float,
    pitch_shift: float,
) -> str:
    seed = (
        f"{engine}|{lang}|{voice or ''}|ls={length_scale:.3f}|"
        f"ps={pitch_shift:.3f}|{text}"
    ).encode("utf-8")
    return hashlib.sha1(seed).hexdigest()


def _cache_path(engine: str, digest: str) -> Path:
    ext = ".mp3" if engine == "gtts" else ".wav"
    return _ensure_cache_dir() / f"{digest}{ext}"


def _prune_cache() -> None:
    """Evict oldest files until total size is within the LRU cap."""
    try:
        files = [
            (p, p.stat().st_mtime, p.stat().st_size)
            for p in _CACHE_DIR.glob("*")
            if p.is_file()
        ]
    except FileNotFoundError:
        return
    now_ts = __import__("time").time()
    survivors = []
    evicted = 0
    for path, mtime, size in files:
        if now_ts - mtime > _CACHE_TTL_SECONDS:
            try:
                path.unlink(missing_ok=True)
                evicted += 1
                continue
            except Exception:
                pass
        survivors.append((path, mtime, size))
    survivors.sort(key=lambda row: row[1])  # oldest first
    total = sum(size for _, _, size in survivors)
    while total > _CACHE_CAP_BYTES and survivors:
        path, _, size = survivors.pop(0)
        try:
            path.unlink(missing_ok=True)
            total -= size
            evicted += 1
        except Exception:
            break
    if evicted:
        logger.info("[TTS] cache pruned (%d file(s))", evicted)


# ---------------------------------------------------------------------------
# Engine: gTTS (online)
# ---------------------------------------------------------------------------

def _synth_gtts(text: str, lang: str, target: Path) -> None:
    try:
        from gtts import gTTS  # type: ignore
    except ImportError as exc:
        raise TTSError(
            "gTTS engine selected but gTTS package is not installed"
        ) from exc
    try:
        gTTS(text=text, lang=lang or _DEFAULT_LANG).save(str(target))
    except Exception as exc:
        raise TTSError(f"gTTS synthesis failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Engine: Piper (offline)
# ---------------------------------------------------------------------------

def _piper_voice_path(voice: Optional[str]) -> Path:
    raw = voice or os.getenv("KURO_PIPER_VOICE_PATH") or _DEFAULT_PIPER_VOICE
    return Path(os.path.expanduser(raw))


def _synth_piper(
    text: str,
    voice: Optional[str],
    target: Path,
    *,
    length_scale: Optional[float] = None,
) -> None:
    model_path = _piper_voice_path(voice)
    if not model_path.exists():
        raise TTSError(
            f"piper voice model not found at {model_path}; download the "
            "en_GB-alan-medium voice via the curl commands in "
            "kuro_backend/voice_service.py. Kuro will not auto-download "
            "to respect the offline promise."
        )
    try:
        from piper import PiperVoice  # type: ignore
    except ImportError as exc:
        raise TTSError(
            "piper engine selected but piper-tts is not installed"
        ) from exc

    ls = length_scale if length_scale is not None else _current_length_scale()

    try:
        voice_obj = PiperVoice.load(str(model_path))
        with wave.open(str(target), "wb") as wav:
            # piper-tts has evolved: newer builds accept a SynthesisConfig,
            # older ones accept keyword args directly. Try the new API first,
            # then fall back — and finally fall back to a plain call so we
            # still produce audio on ancient installs.
            try:
                from piper import SynthesisConfig  # type: ignore

                cfg = SynthesisConfig(length_scale=ls)
                voice_obj.synthesize(text, wav, syn_config=cfg)
                return
            except TypeError:
                # Newer API present but arg shape drifted; fall through.
                pass
            except ImportError:
                pass
            try:
                voice_obj.synthesize(text, wav, length_scale=ls)
                return
            except TypeError:
                pass
            voice_obj.synthesize(text, wav)
    except TTSError:
        raise
    except Exception as exc:
        raise TTSError(f"piper synthesis failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Pitch shift (ffmpeg)
# ---------------------------------------------------------------------------

def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _read_wav_sample_rate(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as wav:
            return int(wav.getframerate() or 22050)
    except Exception:
        return 22050


def _apply_pitch_shift(src: Path, shift: float) -> Path:
    """Post-process ``src`` with ffmpeg to shift pitch by ``shift``.

    Uses the ``asetrate`` trick so the final clip keeps Alan's cadence while
    dropping formants by ``shift``. If ffmpeg is missing or returns non-zero
    the original file is kept (Kuro still speaks, just un-deepened).

    Returns the path that should be served — either the shifted output or
    ``src`` on fallback.
    """
    if abs(shift - 1.0) < 0.005:
        return src
    if not _ffmpeg_available():
        logger.warning(
            "[TTS] ffmpeg not on PATH; serving un-shifted audio (shift=%.3f)",
            shift,
        )
        return src
    rate = _read_wav_sample_rate(src)
    tmp_out = src.with_name(src.stem + "_pitched" + src.suffix)
    new_rate = max(8000, int(rate * shift))
    try:
        completed = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                "-af",
                f"asetrate={new_rate},aresample={rate},atempo={1 / shift:.6f}",
                str(tmp_out),
            ],
            check=False, capture_output=True, timeout=15,
        )
        if completed.returncode != 0 or not tmp_out.exists() or tmp_out.stat().st_size == 0:
            logger.warning(
                "[TTS] ffmpeg pitch shift failed rc=%s stderr=%s",
                completed.returncode, completed.stderr[-200:] if completed.stderr else b"",
            )
            tmp_out.unlink(missing_ok=True)
            return src
        # Atomically replace the original with the pitched version so the
        # cache key lookup still finds a single file per digest.
        os.replace(tmp_out, src)
        return src
    except Exception as exc:
        logger.warning("[TTS] ffmpeg invocation raised: %s", exc)
        try:
            tmp_out.unlink(missing_ok=True)
        except Exception:
            pass
        return src


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def synthesize_to_file(
    text: str,
    *,
    engine: Optional[str] = None,
    lang: str = _DEFAULT_LANG,
    voice: Optional[str] = None,
) -> Tuple[Path, str]:
    """Synthesise ``text`` and return ``(path, media_type)``.

    Results are cached; repeat calls with the same inputs (including
    current ``length_scale`` / ``pitch_shift``) short-circuit. Raises
    :class:`TTSError` on any failure.
    """
    if not isinstance(text, str):
        raise TTSError("text must be a string")
    trimmed = text.strip()
    if not trimmed:
        raise TTSError("text is empty")
    if len(trimmed) > _MAX_TEXT_LEN:
        raise TTSError(f"text exceeds {_MAX_TEXT_LEN} characters")

    selected_engine = _resolve_engine(engine)
    selected_lang = (lang or _DEFAULT_LANG).strip().lower() or _DEFAULT_LANG
    length_scale = _current_length_scale() if selected_engine == "piper" else 1.0
    pitch_shift = _current_pitch_shift() if selected_engine == "piper" else 1.0

    digest = _cache_key(
        selected_engine, selected_lang, voice, trimmed,
        length_scale=length_scale, pitch_shift=pitch_shift,
    )
    target = _cache_path(selected_engine, digest)
    media_type = "audio/mpeg" if selected_engine == "gtts" else "audio/wav"

    with _cache_lock:
        if target.exists() and target.stat().st_size > 0:
            logger.debug(
                "[TTS] cache hit key=%s engine=%s", digest[:8], selected_engine,
            )
            try:
                os.utime(target, None)  # bump mtime for LRU
            except Exception:
                pass
            return target, media_type

        _ensure_cache_dir()
        if selected_engine == "gtts":
            _synth_gtts(trimmed, selected_lang, target)
        else:
            _synth_piper(
                trimmed, voice, target, length_scale=length_scale,
            )
            # Pitch-shift only makes sense on WAV output (piper). gTTS output
            # is MP3; skipping keeps the cache deterministic.
            _apply_pitch_shift(target, pitch_shift)

        if not target.exists() or target.stat().st_size == 0:
            raise TTSError("synthesis produced no audio")
        _prune_cache()
        logger.info(
            "[TTS] synthesised engine=%s lang=%s voice=%s key=%s size=%d "
            "ls=%.2f ps=%.2f",
            selected_engine, selected_lang, voice or "-", digest[:8],
            target.stat().st_size, length_scale, pitch_shift,
        )
        return target, media_type


def synthesize(
    text: str,
    *,
    engine: Optional[str] = None,
    lang: str = _DEFAULT_LANG,
    voice: Optional[str] = None,
) -> bytes:
    """Synthesise and return the raw audio bytes (convenience for callers
    that don't need the cache path)."""
    path, _ = synthesize_to_file(text, engine=engine, lang=lang, voice=voice)
    return path.read_bytes()


def cache_stats() -> Dict[str, int]:
    """Return ``{files, bytes}`` for the cache dir (diagnostic)."""
    try:
        files = [p for p in _CACHE_DIR.glob("*") if p.is_file()]
        total = sum(p.stat().st_size for p in files)
        return {"files": len(files), "bytes": total}
    except FileNotFoundError:
        return {"files": 0, "bytes": 0}


__all__ = [
    "TTSError",
    "cache_stats",
    "synthesize",
    "synthesize_to_file",
]
