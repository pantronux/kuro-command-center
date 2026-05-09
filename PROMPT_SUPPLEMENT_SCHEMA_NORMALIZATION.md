# Prompt Supplement — Dynamic Schema Normalization Hardening
**Scope:** `playground_runtime/schema/` + `playground_runtime/governance/reasoning_policy.py`
**Prerequisite:** Implementasi PLAN.md sudah selesai dan terverifikasi.
**Acuan utama:** `PLAYGROUND_RUNTIME_IMPLEMENTATION_PROMPT.md` Section 6
**Prompt status:** Supplement — tidak menggantikan prompt utama, hanya memperluas Section 6.

---

## Konteks & Motivasi

Implementasi saat ini menggunakan **flat inheritance pattern**: `GeminiMapper`, `AnthropicMapper`, dan `DeepSeekMapper` semuanya mewarisi `OpenAIMapper` tanpa override apapun. Artinya, ketiga provider tersebut menggunakan logika field mapping yang identik dengan OpenAI.

Ini bekerja untuk kondisi sekarang, tapi akan **langsung rusak** ketika:

1. Gemini mengirim field yang tidak ada di OpenAI — misalnya `generationConfig`, `groundingMetadata`, `safetyRatings` dengan struktur nested berbeda
2. Provider yang sama merilis versi baru API dengan struktur response berbeda
3. Dua provider berbeda mengirim field dengan nama sama tapi semantik berbeda (misalnya `finish_reason` vs `finishReason` vs `stop_reason`)

Tujuan prompt ini: **hardening normalization pipeline** agar robust terhadap schema drift antar provider dan antar versi, tanpa melanggar raw evidence immutability.

---

## Temuan dari Kode Aktual

Sebelum implementasi, baca dan pahami state saat ini:

### ✅ Yang Sudah Benar

- `CanonicalInferenceTrace` memiliki `extra_fields: Dict[str, object]` — unknown fields tidak dibuang, disimpan
- `BaseMapper.collect_unknown_fields()` menghasilkan warning `UNKNOWN_FIELDS:...` untuk field tak dikenal
- `reasoning_policy.split_hidden_reasoning_fields()` memiliki blacklist `HIDDEN_REASONING_FIELDS` yang eksplisit
- `NormalizationRegistry.normalize()` mengoper `raw_record.copy()` — raw record asli tidak termutasi
- `EvidenceArtifact` bersifat `frozen=True` — immutability enforced di level dataclass
- `schema_version` per mapper sudah di-namespace: `"gemini/1.0.0"`, `"openai/1.0.0"`, dst.

### ⚠️ Gap yang Harus Ditutup

**Gap 1 — GeminiMapper tidak handle field Gemini-spesifik**

Dari sample payload Gemini aktual (AI Studio format), ada field-field yang tidak ada di OpenAI response:

```json
{
  "model": "models/gemini-3-flash-preview",
  "generationConfig": {
    "temperature": 0.25,
    "topP": 0.88,
    "topK": 48,
    "responseMimeType": ""
  },
  "tools": [{ "googleSearch": {} }],
  "systemInstruction": { "parts": [{ "text": "..." }], "role": "user" },
  "contents": [{ "parts": [{ "text": "..." }], "role": "user" }]
}
```

Saat ini `GeminiMapper` mewarisi `OpenAIMapper` dan field-field di atas masuk ke `extra_fields` dengan warning `UNKNOWN_FIELDS`. Ini belum cukup — field-field ini punya **makna forensik** dan harus di-map ke tempat yang tepat di `CanonicalInferenceTrace`.

**Gap 2 — `forensic_flags` hanya diisi dari grounding warnings**

```python
# Di openai_mapper.py saat ini:
forensic_flags=[w for w in warnings if w.startswith("GROUNDING")],
```

Artinya `HIDDEN_REASONING_FIELDS_STRIPPED`, `UNKNOWN_FIELDS`, dan flag lain tidak masuk ke `forensic_flags`. Ini menyebabkan forensic visibility rendah.

**Gap 3 — Tidak ada schema version mismatch detection**

Saat `raw_evidence` lama di-renormalize menggunakan mapper versi baru, tidak ada mekanisme untuk mendeteksi bahwa `schema_version` yang tersimpan berbeda dari `schema_version` mapper yang dipakai sekarang. Re-normalization bisa diam-diam menghasilkan trace yang berbeda dari trace aslinya.

**Gap 4 — `HIDDEN_REASONING_FIELDS` tidak cover variasi casing dan nested field**

```python
# Saat ini di reasoning_policy.py:
if key.lower() in HIDDEN_REASONING_FIELDS:
```

Ini sudah handle lowercase, tapi tidak handle:
- Nested field: `{"message": {"reasoning": "..."}}`  
- Camel case dalam nested: `{"choices": [{"message": {"chainOfThought": "..."}}]}`
- Field dengan prefix: `"_reasoning"`, `"__cot__"`

**Gap 5 — `NormalizationRegistry` fallback ke `OpenAIMapper()` diam-diam**

```python
def get(self, provider_id: str) -> BaseMapper:
    return self._mappers.get(provider_id, OpenAIMapper())  # silent fallback
```

Provider yang tidak dikenal mendapat `OpenAIMapper` tanpa warning apapun. Ini berbahaya untuk forensic reproducibility — trace akan ter-generate dengan `schema_version: "openai/1.0.0"` meski provider-nya bukan OpenAI.

---

## Instruksi Implementasi

**PENTING:** Baca seluruh file berikut sebelum menulis kode apapun:
- `playground_runtime/schema/canonical_trace.py`
- `playground_runtime/schema/mappers/base_mapper.py`
- `playground_runtime/schema/mappers/openai_mapper.py`
- `playground_runtime/schema/mappers/gemini_mapper.py`
- `playground_runtime/schema/normalization_registry.py`
- `playground_runtime/governance/reasoning_policy.py`

Jangan modifikasi `CanonicalInferenceTrace` struct — semua field yang dibutuhkan sudah ada. Implementasi hanya menyentuh mapper, policy, dan registry.

---

### Task 1 — Hardening `GeminiMapper`

Ubah `GeminiMapper` dari pure inheritance menjadi mapper dengan field mapping Gemini-spesifik.

**Field mapping yang harus diimplementasi:**

| Field Gemini (raw payload) | Target di `CanonicalInferenceTrace` | Catatan |
|---|---|---|
| `model` | `model_id` | Strip prefix `"models/"` jika ada |
| `generationConfig.temperature` | `extra_fields["generation_temperature"]` | Forensic metadata, bukan response field |
| `generationConfig.topP` | `extra_fields["generation_top_p"]` | |
| `generationConfig.topK` | `extra_fields["generation_top_k"]` | |
| `generationConfig.responseMimeType` | `extra_fields["response_mime_type"]` | Tambah flag `MIME_TYPE_UNSET` jika kosong string |
| `tools[*].googleSearch` | Signal: set `extra_fields["grounding_tool"]="googleSearch"` | Kehadiran tool, bukan hasil search |
| `candidates[0].content.parts[0].text` | `response_text` | Path response Gemini berbeda dari OpenAI |
| `candidates[0].finishReason` | `finish_reason` | camelCase di Gemini |
| `candidates[0].groundingMetadata.groundingChunks` | `grounding_chunks` | Jika ada |
| `candidates[0].groundingMetadata.webSearchQueries` | `citation_objects` | Map sebagai citation evidence |
| `candidates[0].safetyRatings` | `safety_ratings` | |
| `usageMetadata.promptTokenCount` | `input_tokens` | Nama berbeda dari OpenAI |
| `usageMetadata.candidatesTokenCount` | `output_tokens` | |
| `usageMetadata.totalTokenCount` | `total_tokens` | |
| `systemInstruction` | **TIDAK dimap ke canonical** | Privacy boundary — hanya ada di raw_evidence |

**Known fields Gemini** (untuk `collect_unknown_fields`):
```python
GEMINI_KNOWN_FIELDS = {
    "model", "contents", "generationConfig", "systemInstruction",
    "tools", "candidates", "usageMetadata", "promptFeedback",
    "modelVersion", "createTime", "responseId",
}
```

**Forensic flags yang harus ditambah oleh GeminiMapper:**
- `MIME_TYPE_UNSET` — jika `generationConfig.responseMimeType` adalah empty string
- `GROUNDING_TOOL_ABSENT` — jika `tools` tidak mengandung `googleSearch`
- `NO_CANDIDATES` — jika `candidates` kosong atau tidak ada
- `FINISH_REASON_ABNORMAL` — jika `finishReason` bukan `"STOP"` atau `"MAX_TOKENS"`

---

### Task 2 — Hardening `forensic_flags` di `OpenAIMapper`

Ubah logika `forensic_flags` dari filter sempit menjadi classifier yang komprehensif:

```python
# SEBELUM (hanya grounding):
forensic_flags=[w for w in warnings if w.startswith("GROUNDING")],

# SESUDAH — semua warning yang punya forensic significance:
FORENSIC_FLAG_PREFIXES = {
    "GROUNDING",          # Grounding absent/incomplete
    "HIDDEN_REASONING",   # CoT field ditemukan dan di-strip
    "FINISH_REASON",      # Abnormal finish reason
    "MIME_TYPE",          # Response type anomaly
    "NO_CANDIDATES",      # Empty response candidates
    "SCHEMA_DRIFT",       # Unknown fields dari provider versi baru (BARU)
}
forensic_flags=[w for w in warnings if any(w.startswith(p) for p in FORENSIC_FLAG_PREFIXES)],
```

Ubah `UNKNOWN_FIELDS:...` warning menjadi `SCHEMA_DRIFT:...` agar lebih deskriptif secara forensik, dan masuk ke `forensic_flags`. Update `collect_unknown_fields()` di `BaseMapper` untuk menggunakan prefix `SCHEMA_DRIFT` alih-alih `UNKNOWN_FIELDS`.

---

### Task 3 — Schema Version Mismatch Detection di `NormalizationRegistry`

Tambah method `renormalize()` yang berbeda dari `normalize()`:

```python
def renormalize(
    self,
    session_id: str,
    execution_id: str,
    provider_raw_id: str,
    raw_record: dict,
    original_schema_version: str,  # schema_version yang tersimpan di DB
) -> CanonicalInferenceTrace:
    """
    Re-normalize raw_evidence menggunakan mapper versi saat ini.
    Jika schema_version berbeda, tambah normalization_warning dan forensic_flag.
    """
    trace = self.normalize(session_id, execution_id, provider_raw_id, raw_record)
    
    if trace.schema_version != original_schema_version:
        trace.normalization_warnings.append(
            f"SCHEMA_VERSION_MISMATCH:stored={original_schema_version},current={trace.schema_version}"
        )
        trace.forensic_flags.append(
            f"SCHEMA_VERSION_MISMATCH"
        )
    return trace
```

**Catatan:** `CanonicalInferenceTrace` adalah dataclass biasa (bukan frozen), jadi append ke list field-nya diperbolehkan setelah konstruksi.

---

### Task 4 — Hardening `reasoning_policy.py` untuk Nested Fields

Tambah fungsi `split_hidden_reasoning_fields_deep()` yang handle nested dict:

```python
def split_hidden_reasoning_fields_deep(
    raw_record: Dict[str, Any],
    _depth: int = 0,
    _max_depth: int = 3,
) -> Tuple[Dict[str, Any], list[str]]:
    """
    Rekursif strip hidden reasoning fields sampai kedalaman max_depth.
    Hanya berjalan pada dict values — list of dict juga di-traverse.
    Tidak memodifikasi raw_record asli (deep copy pada entry point).
    """
```

Aturan traversal:
- Maksimum kedalaman: 3 level (cukup untuk `choices[0].message.reasoning`)
- Untuk setiap `dict` value yang ditemukan: rekursi
- Untuk `list` value: traverse setiap element yang merupakan `dict`
- Prefix warning untuk nested: `HIDDEN_REASONING_FIELDS_STRIPPED_NESTED:path.to.field`
- Tambah field `_reasoning`, `__cot__`, `_thought` ke `HIDDEN_REASONING_FIELDS` (underscore prefix variants)

**Perbarui `OpenAIMapper`** untuk memanggil `split_hidden_reasoning_fields_deep()` alih-alih `split_hidden_reasoning_fields()`. Pertahankan fungsi lama untuk backward compatibility.

---

### Task 5 — Silent Fallback Fix di `NormalizationRegistry`

Ubah `get()` agar tidak silent fallback:

```python
def get(self, provider_id: str) -> BaseMapper:
    mapper = self._mappers.get(provider_id)
    if mapper is None:
        # Fallback ke OpenAIMapper tapi catat sebagai warning
        # Warning ini akan masuk ke normalization_warnings via caller
        return _UnknownProviderMapper(provider_id=provider_id)
    return mapper
```

Buat `_UnknownProviderMapper` sebagai subclass `OpenAIMapper` dengan `schema_version = "unknown/fallback/1.0.0"` yang secara otomatis menambah `normalization_warnings` berisi `UNKNOWN_PROVIDER:{provider_id}` dan `forensic_flags` berisi `UNKNOWN_PROVIDER`.

---

### Task 6 — Test Tambahan

Tambah ke `tests/test_playground_schema_normalization.py` (file baru):

**Test yang wajib ada:**

```
test_gemini_mapper_model_field_strip_prefix
  → "models/gemini-3-flash-preview" → model_id = "gemini-3-flash-preview"

test_gemini_mapper_generation_config_to_extra_fields
  → generationConfig.temperature masuk extra_fields["generation_temperature"]

test_gemini_mapper_empty_mime_type_flag
  → responseMimeType="" → forensic_flags mengandung "MIME_TYPE_UNSET"

test_gemini_mapper_grounding_tool_detection
  → tools[].googleSearch ada → extra_fields["grounding_tool"]="googleSearch"

test_gemini_mapper_usage_metadata_token_mapping
  → promptTokenCount → input_tokens, candidatesTokenCount → output_tokens

test_gemini_mapper_system_instruction_not_in_canonical
  → systemInstruction tidak muncul di response_text, extra_fields, atau field lain

test_schema_drift_flag_on_unknown_field
  → field tak dikenal → forensic_flags mengandung "SCHEMA_DRIFT"

test_renormalize_detects_version_mismatch
  → original_schema_version="gemini/0.9.0", current="gemini/1.0.0"
  → normalization_warnings mengandung "SCHEMA_VERSION_MISMATCH"
  → forensic_flags mengandung "SCHEMA_VERSION_MISMATCH"

test_deep_reasoning_strip_nested
  → {"choices": [{"message": {"reasoning": "hidden"}}]}
  → "reasoning" ter-strip, warning HIDDEN_REASONING_FIELDS_STRIPPED_NESTED

test_unknown_provider_fallback_warning
  → provider_id="future_provider_xyz"
  → normalization_warnings mengandung "UNKNOWN_PROVIDER:future_provider_xyz"
  → schema_version = "unknown/fallback/1.0.0"

test_raw_evidence_not_mutated_after_normalize
  → raw_record sebelum dan sesudah normalize() identik (deep equality)
```

---

## Urutan Eksekusi

```
1. Baca semua file yang disebutkan di atas
2. Task 2 — forensic_flags hardening di OpenAIMapper + BaseMapper (paling aman, isolated)
3. Task 4 — reasoning_policy deep traversal
4. Task 1 — GeminiMapper field mapping (setelah Task 2 selesai, karena GeminiMapper depend ke OpenAIMapper)
5. Task 5 — NormalizationRegistry silent fallback fix
6. Task 3 — renormalize() method di NormalizationRegistry
7. Task 6 — test suite
8. python3 -m compileall -q playground_runtime
9. python3 -m pytest -q tests/test_playground_schema_normalization.py
10. python3 -m pytest -q tests/test_playground_* (pastikan tidak ada regression)
```

---

## Invariant yang Tidak Boleh Dilanggar

- `raw_record` yang diterima `map_to_canonical()` TIDAK BOLEH dimutasi — selalu operate pada copy
- `raw_evidence` di DB TIDAK BOLEH diupdate setelah insert — normalization bekerja pada copy
- `systemInstruction` dari Gemini TIDAK BOLEH masuk ke field canonical apapun
- `CanonicalInferenceTrace` struct TIDAK BOLEH diubah (tambah/hapus field) — ini breaking change
- `split_hidden_reasoning_fields()` lama TIDAK BOLEH dihapus — backward compatibility untuk mapper yang masih memanggilnya

---

## Catatan untuk Prompt Utama

Setelah Task ini selesai, Section 6 di `PLAYGROUND_RUNTIME_IMPLEMENTATION_PROMPT.md` sudah terpenuhi secara konkret. Jika ada provider baru yang ditambah di masa depan (misalnya Ollama), cukup:

1. Buat `OllamaMapper(BaseMapper)` dengan override `map_to_canonical()` dan `OLLAMA_KNOWN_FIELDS`
2. Set `schema_version = "ollama/1.0.0"`
3. Register di `NormalizationRegistry.__init__()`: `"ollama": OllamaMapper()`
4. Tambah test di `test_playground_schema_normalization.py`

Tidak perlu modifikasi di tempat lain.
