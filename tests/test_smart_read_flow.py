import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "mem0" not in sys.modules:
    fake_mem0 = types.ModuleType("mem0")

    class _FakeMemory:
        def __init__(self, *args, **kwargs):
            pass

    fake_mem0.Memory = _FakeMemory
    sys.modules["mem0"] = fake_mem0

if "phoenix" not in sys.modules:
    fake_phoenix = types.ModuleType("phoenix")

    class _FakePhoenixApp:
        url = "http://localhost:6006"

        def close(self):
            return None

    def _launch_app(*args, **kwargs):
        return _FakePhoenixApp()

    fake_phoenix.launch_app = _launch_app
    sys.modules["phoenix"] = fake_phoenix

from kuro_backend.tools import base_tools
from kuro_backend import memory_manager


def test_smart_read_context_unresolved(monkeypatch):
    monkeypatch.setattr(memory_manager, "get_runtime_context_value", lambda key, default="": "")
    result = base_tools.smart_read(file_ref="ini", instruction="ringkas")
    assert result["success"] is False
    assert result["resolved_by"] == "context_missing"


def test_smart_read_context_resolves_last_file(tmp_path, monkeypatch):
    sample = tmp_path / "runtime.log"
    sample.write_text("alpha\nbeta", encoding="utf-8")

    monkeypatch.setattr(memory_manager, "get_runtime_context_value", lambda key, default="": str(sample))
    captured = {}
    monkeypatch.setattr(memory_manager, "set_runtime_context_value", lambda key, value: captured.update({key: value}))

    result = base_tools.smart_read(file_ref="ini", instruction="baca")
    assert result["success"] is True
    assert result["resolved_by"] == "context"
    assert "alpha" in result["summary"]
    assert captured.get("last_accessed_file") == str(sample)


def test_smart_read_docx_route_uses_docx_engine(tmp_path, monkeypatch):
    sample = tmp_path / "report.docx"
    sample.write_text("placeholder", encoding="utf-8")

    monkeypatch.setattr(memory_manager, "set_runtime_context_value", lambda key, value: None)
    monkeypatch.setattr(base_tools, "read_docx_content", lambda file_path, max_chars=15000: {"content": "isi docx"})
    monkeypatch.setattr(base_tools, "_run_instruction_on_text", lambda instruction, extracted_text, source_label: {"success": True, "output": "ringkasan docx"})

    result = base_tools.smart_read(file_ref=str(sample), instruction="ringkas")
    assert result["success"] is True
    assert result["engine_used"] == "read_docx_content+llm"
    assert result["file_type"] == "Word (.docx)"
    assert result["summary"] == "ringkasan docx"


def test_smart_read_image_route_uses_ocr_engine(tmp_path, monkeypatch):
    sample = tmp_path / "evidence.png"
    sample.write_bytes(b"fake-image")

    monkeypatch.setattr(memory_manager, "set_runtime_context_value", lambda key, value: None)
    monkeypatch.setattr(
        base_tools,
        "_extract_image_text_with_vision",
        lambda image_path, instruction="": {
            "success": True,
            "content": "OCR RESULT",
            "ocr_engine": "gemini_vision",
        },
    )

    result = base_tools.smart_read(file_ref=str(sample), instruction="ekstrak teks")
    assert result["success"] is True
    assert result["engine_used"] == "vision_ocr"
    assert result["ocr_engine"] == "gemini_vision"
    assert result["summary"] == "OCR RESULT"


def test_smart_read_not_found_returns_deterministic_error(monkeypatch):
    monkeypatch.setattr(memory_manager, "get_runtime_context_value", lambda key, default="": "")
    result = base_tools.smart_read(file_ref="not-exists-xyz-123.docx")
    assert result["success"] is False
    assert result["resolved_by"] == "not_found"
    assert "File not found" in result["error"]
