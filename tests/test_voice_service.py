"""Tests for Kuro AI V6.0 Sovereign voice_service (pluggable gTTS / piper + cache).

--- Header Doc ---
Purpose: Verify synthesize_to_file routes to correct engine + LRU cache behaviour.
Covers: kuro_backend.voice_service.synthesize_to_file.
Fixtures: tmp_path media dir + monkeypatched piper / gTTS shims.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "mem0" not in sys.modules:
    fake_mem0 = types.ModuleType("mem0")

    class _FakeMemory:
        def __init__(self, *a, **kw):
            pass

    fake_mem0.Memory = _FakeMemory
    sys.modules["mem0"] = fake_mem0

if "phoenix" not in sys.modules:
    fake_phoenix = types.ModuleType("phoenix")
    fake_phoenix.launch_app = lambda *a, **k: types.SimpleNamespace(
        url="http://x", close=lambda: None,
    )
    sys.modules["phoenix"] = fake_phoenix


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    import importlib
    import kuro_backend.voice_service as vs
    importlib.reload(vs)
    monkeypatch.setattr(vs, "_CACHE_DIR", tmp_path)
    yield tmp_path, vs


def test_text_length_cap_raises(isolated_cache):
    _, vs = isolated_cache
    with pytest.raises(vs.TTSError):
        vs.synthesize_to_file("x" * 2001)


def test_empty_text_raises(isolated_cache):
    _, vs = isolated_cache
    with pytest.raises(vs.TTSError):
        vs.synthesize_to_file("   ")


def test_unsupported_engine_raises(isolated_cache):
    _, vs = isolated_cache
    with pytest.raises(vs.TTSError):
        vs.synthesize_to_file("halo", engine="espeak")


def test_gtts_synth_writes_file_and_hits_cache(isolated_cache, monkeypatch):
    cache_dir, vs = isolated_cache

    calls = {"count": 0}

    def fake_synth_gtts(text, lang, target):
        calls["count"] += 1
        target.write_bytes(b"ID3FAKEAUDIO-" + text.encode("utf-8"))

    monkeypatch.setattr(vs, "_synth_gtts", fake_synth_gtts)
    path1, mime1 = vs.synthesize_to_file("Hai Master", engine="gtts", lang="id")
    assert path1.exists() and path1.stat().st_size > 0
    assert mime1 == "audio/mpeg"
    assert calls["count"] == 1

    # Second call with identical inputs must hit the cache.
    path2, _ = vs.synthesize_to_file("Hai Master", engine="gtts", lang="id")
    assert path2 == path1
    assert calls["count"] == 1


def test_piper_missing_model_raises_ttserror(isolated_cache, monkeypatch):
    cache_dir, vs = isolated_cache
    monkeypatch.setenv("KURO_PIPER_VOICE_PATH", str(cache_dir / "does-not-exist.onnx"))
    with pytest.raises(vs.TTSError) as excinfo:
        vs.synthesize_to_file("halo", engine="piper")
    assert "piper voice model not found" in str(excinfo.value)


def test_piper_happy_path_with_monkeypatched_engine(isolated_cache, monkeypatch, tmp_path):
    cache_dir, vs = isolated_cache
    fake_model = tmp_path / "fake.onnx"
    fake_model.write_bytes(b"\x00")
    monkeypatch.setenv("KURO_PIPER_VOICE_PATH", str(fake_model))
    monkeypatch.setenv("KURO_TTS_FFMPEG_ENABLED", "false")

    def fake_synth_piper(text, voice, target, **kwargs):
        target.write_bytes(b"RIFFFAKEWAV-" + text.encode("utf-8"))

    monkeypatch.setattr(vs, "_synth_piper", fake_synth_piper)
    path, mime = vs.synthesize_to_file("halo", engine="piper", lang="en")
    assert path.exists() and path.suffix == ".wav"
    assert mime == "audio/wav"


def test_cache_stats_reports_files(isolated_cache, monkeypatch):
    cache_dir, vs = isolated_cache
    monkeypatch.setattr(vs, "_synth_gtts", lambda t, l, target: target.write_bytes(b"x"))
    vs.synthesize_to_file("one", engine="gtts", lang="id")
    vs.synthesize_to_file("two", engine="gtts", lang="id")
    stats = vs.cache_stats()
    assert stats["files"] >= 2
    assert stats["bytes"] > 0


def test_synthesize_returns_bytes(isolated_cache, monkeypatch):
    cache_dir, vs = isolated_cache
    monkeypatch.setattr(vs, "_synth_gtts", lambda t, l, target: target.write_bytes(b"abc"))
    data = vs.synthesize("hi", engine="gtts", lang="id")
    assert data == b"abc"


# ---------------------------------------------------------------------------
# V6.0 Sovereign — Sebastian voice tuning (length_scale, pitch-shift, fallback)
# ---------------------------------------------------------------------------

def test_piper_length_scale_forwarded(isolated_cache, monkeypatch, tmp_path):
    """Piper synthesis must receive the KURO_PIPER_LENGTH_SCALE env value."""
    cache_dir, vs = isolated_cache
    fake_model = tmp_path / "fake.onnx"
    fake_model.write_bytes(b"\x00")
    monkeypatch.setenv("KURO_PIPER_VOICE_PATH", str(fake_model))
    monkeypatch.setenv("KURO_PIPER_LENGTH_SCALE", "1.25")
    monkeypatch.setenv("KURO_TTS_FFMPEG_ENABLED", "false")

    observed = {}

    def fake_synth_piper(text, voice, target, *, length_scale=None):
        observed["length_scale"] = length_scale
        target.write_bytes(b"RIFFFAKEWAV-" + text.encode("utf-8"))

    monkeypatch.setattr(vs, "_synth_piper", fake_synth_piper)
    vs.synthesize_to_file("hello", engine="piper", lang="en")
    assert observed["length_scale"] == pytest.approx(1.25, rel=1e-3)


def test_piper_pitch_shift_cache_key_differs(isolated_cache, monkeypatch, tmp_path):
    """Different pitch-shift values must produce distinct cache entries."""
    cache_dir, vs = isolated_cache
    fake_model = tmp_path / "fake.onnx"
    fake_model.write_bytes(b"\x00")
    monkeypatch.setenv("KURO_PIPER_VOICE_PATH", str(fake_model))

    # Force the pitch shift post-processor to be a no-op so the WAV bytes
    # match exactly; we're only testing cache-key isolation here.
    monkeypatch.setattr(vs, "_apply_pitch_shift", lambda src, shift: src)
    monkeypatch.setattr(
        vs, "_synth_piper",
        lambda text, voice, target, **kw: target.write_bytes(b"RIFFWAV-" + text.encode()),
    )

    monkeypatch.setenv("KURO_TTS_PITCH_SHIFT", "0.93")
    monkeypatch.setenv("KURO_TTS_FFMPEG_ENABLED", "true")
    path_a, _ = vs.synthesize_to_file("Master", engine="piper", lang="en")

    monkeypatch.setenv("KURO_TTS_PITCH_SHIFT", "0.85")
    path_b, _ = vs.synthesize_to_file("Master", engine="piper", lang="en")

    assert path_a != path_b
    assert path_a.exists() and path_b.exists()


def test_pitch_shift_uses_ffmpeg_when_available(isolated_cache, monkeypatch, tmp_path):
    """When ffmpeg reports success, the pitched output replaces the source."""
    cache_dir, vs = isolated_cache

    src = tmp_path / "in.wav"
    src.write_bytes(b"ORIG")

    def fake_which(name):
        return "/usr/bin/ffmpeg" if name == "ffmpeg" else None

    class FakeCompleted:
        returncode = 0
        stderr = b""

    def fake_run(cmd, *args, **kwargs):
        # cmd is ["ffmpeg", ..., out_path]
        out_path = Path(cmd[-1])
        out_path.write_bytes(b"PITCHED")
        return FakeCompleted()

    monkeypatch.setattr(vs.shutil, "which", fake_which)
    monkeypatch.setattr(vs.subprocess, "run", fake_run)

    result = vs._apply_pitch_shift(src, 0.9)
    assert result == src
    assert src.read_bytes() == b"PITCHED"


def test_pitch_shift_falls_back_when_ffmpeg_missing(isolated_cache, monkeypatch, tmp_path):
    """Missing ffmpeg must leave the original audio intact, never raise."""
    cache_dir, vs = isolated_cache
    src = tmp_path / "in.wav"
    src.write_bytes(b"ORIG")

    monkeypatch.setattr(vs.shutil, "which", lambda _: None)
    result = vs._apply_pitch_shift(src, 0.9)
    assert result == src
    assert src.read_bytes() == b"ORIG"


def test_pitch_shift_falls_back_on_ffmpeg_failure(isolated_cache, monkeypatch, tmp_path):
    """Non-zero ffmpeg exit must keep the original and never leave garbage."""
    cache_dir, vs = isolated_cache
    src = tmp_path / "in.wav"
    src.write_bytes(b"ORIG")

    class FakeCompleted:
        returncode = 1
        stderr = b"boom"

    def fake_run(cmd, *args, **kwargs):
        # Intentionally never write output.
        return FakeCompleted()

    monkeypatch.setattr(vs.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    monkeypatch.setattr(vs.subprocess, "run", fake_run)

    result = vs._apply_pitch_shift(src, 0.9)
    assert result == src
    assert src.read_bytes() == b"ORIG"


def test_pitch_shift_noop_when_shift_is_one(isolated_cache, monkeypatch, tmp_path):
    """shift == 1.0 must skip ffmpeg entirely (hot path for gtts fallback)."""
    cache_dir, vs = isolated_cache
    src = tmp_path / "in.wav"
    src.write_bytes(b"ORIG")
    called = {"ffmpeg": False}

    def tripwire(*a, **kw):
        called["ffmpeg"] = True
        raise AssertionError("ffmpeg should not be invoked when shift=1")

    monkeypatch.setattr(vs.subprocess, "run", tripwire)
    monkeypatch.setattr(vs.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    result = vs._apply_pitch_shift(src, 1.0)
    assert result == src
    assert called["ffmpeg"] is False


def test_default_engine_is_piper_in_v6(isolated_cache, monkeypatch):
    """With no explicit engine argument and no env override, V6.0 must
    resolve to Piper so Sebastian is the default voice."""
    _, vs = isolated_cache
    monkeypatch.delenv("KURO_TTS_ENGINE", raising=False)
    assert vs._resolve_engine(None) == "piper"
