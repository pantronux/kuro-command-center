You are working on the Kuro AI repository.

Context:
I have installed Ollama on Ubuntu 24 and verified that it works locally.

Verified commands:

ollama --version
# ollama version is 0.24.0

curl http://localhost:11434/api/tags
# returns qwen3:4b

curl http://localhost:11434/v1/models
# returns qwen3:4b

curl http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3:4b",
    "messages": [
      {"role": "user", "content": "Say hello in one sentence."}
    ]
  }'

This returns a valid OpenAI-compatible chat completion response with:
- model: qwen3:4b
- choices[0].message.content
- choices[0].message.reasoning
- usage.prompt_tokens
- usage.completion_tokens
- usage.total_tokens
- finish_reason: stop

Goal:
Make sure Kuro Playground can connect to Ollama through the existing provider system and execute qwen3:4b as a local provider.

Expected environment variables:

KURO_PLAYGROUND_ENABLED=true
KURO_PLAYGROUND_API_ENABLED=true
KURO_PLAYGROUND_RESEARCH_MODE=true
KURO_PLAYGROUND_FORENSIC_MODE=true
KURO_PLAYGROUND_COMPARATIVE_MODE=true
KURO_PLAYGROUND_REPORT_EXPORT=true

PLAYGROUND_OLLAMA_BASE_URL=http://localhost:11434/v1
PLAYGROUND_OLLAMA_MODEL_NAME=qwen3:4b

Tasks:

1. Inspect the Playground configuration layer.
   - Check playground_runtime/config.py.
   - Confirm that PLAYGROUND_OLLAMA_BASE_URL and PLAYGROUND_OLLAMA_MODEL_NAME are read correctly.
   - Confirm that the ollama provider becomes active when PLAYGROUND_OLLAMA_BASE_URL is set.
   - Confirm that model_name is passed from PLAYGROUND_OLLAMA_MODEL_NAME.

2. Inspect the provider registry.
   - Check playground_runtime/providers/registry.py.
   - Confirm that provider_id="ollama" is registered when active.
   - Confirm that the registry instantiates OllamaAdapter with:
     - base_url from PLAYGROUND_OLLAMA_BASE_URL
     - default_model/model_name from PLAYGROUND_OLLAMA_MODEL_NAME
   - If the registry still falls back to llama3.1:8b or ignores the env model, fix it.

3. Inspect the Ollama adapter.
   - Check playground_runtime/providers/adapters/ollama_adapter.py.
   - It currently wraps OpenAICompatAdapter.
   - Ensure it works with Ollama OpenAI-compatible endpoint:
     - base_url should support http://localhost:11434/v1
     - api_key should be None or a harmless placeholder if OpenAICompatAdapter requires one.
   - Do not use Ollama native /api/generate in this adapter unless the existing architecture already expects native Ollama format.
   - Keep the current OpenAI-compatible path if possible.

4. Inspect the OpenAI-compatible adapter.
   - Check playground_runtime/providers/adapters/openai_compat_adapter.py.
   - Confirm that it sends requests to:
     POST {base_url}/chat/completions
     when base_url is http://localhost:11434/v1.
   - Ensure it does not accidentally produce:
     http://localhost:11434/v1/v1/chat/completions
     or
     http://localhost:11434/chat/completions
   - Add URL normalization if needed.

5. Confirm raw response preservation.
   - Ensure the raw Ollama OpenAI-compatible response is preserved before canonical mapping.
   - Important fields from Ollama OpenAI-compatible response:
     - id
     - object
     - created
     - model
     - system_fingerprint
     - choices[0].message.content
     - choices[0].message.reasoning
     - choices[0].finish_reason
     - usage.prompt_tokens
     - usage.completion_tokens
     - usage.total_tokens
   - Do not discard choices[0].message.reasoning.
   - Store it as provider-specific metadata or visible_reasoning_trace.
   - Do not interpret it as true internal reasoning. Treat it as a model-generated reasoning artifact.

6. Confirm canonical mapping.
   - Ensure the Ollama OpenAI-compatible response maps into canonical trace fields:
     - provider_id = "ollama"
     - model_id/model_version = response.model or configured model name
     - response_text = choices[0].message.content
     - finish_reason = choices[0].finish_reason
     - input_tokens = usage.prompt_tokens
     - output_tokens = usage.completion_tokens
     - total_tokens = usage.total_tokens
   - Preserve extra fields:
     - system_fingerprint
     - choices[0].message.reasoning
     - raw model metadata if available
   - If current mapper leaves response_text/model_id/token fields null, fix the mapper.

7. Add or update tests.
   - Add tests for PlaygroundSettings provider_env_configs() with:
     PLAYGROUND_OLLAMA_BASE_URL=http://localhost:11434/v1
     PLAYGROUND_OLLAMA_MODEL_NAME=qwen3:4b
   - Assert:
     - ollama.active is True
     - ollama.base_url == "http://localhost:11434/v1"
     - ollama.model_name == "qwen3:4b"
   - Add adapter test using a mocked OpenAI-compatible Ollama response.
   - Add canonical mapping test to ensure:
     - response_text is populated
     - model_id is populated
     - finish_reason is populated
     - token usage is populated
     - reasoning field is preserved in extra/provider-specific metadata

8. Add a small developer note if missing.
   - Document local Ollama setup for Playground:
     export PLAYGROUND_OLLAMA_BASE_URL=http://localhost:11434/v1
     export PLAYGROUND_OLLAMA_MODEL_NAME=qwen3:4b
   - Include verification commands:
     curl http://localhost:11434/v1/models
     curl http://localhost:11434/v1/chat/completions ...

Constraints:
- Keep changes additive and minimal.
- Do not break existing OpenAI/Gemini/Anthropic/DeepSeek providers.
- Do not change the normal chat runtime.
- Do not hardcode qwen3:4b except in documentation/tests.
- Use env configuration as the source of truth.
- Preserve backward compatibility.
- Run tests after changes:

pytest tests/ -x --tb=short

Expected result:
After setting the env variables and restarting Kuro backend, the Playground provider checklist should show ollama as active. Executing a prompt through the Playground with provider ollama should call local Ollama qwen3:4b through http://localhost:11434/v1/chat/completions, preserve the raw response, and create a canonical trace with populated response_text, model_id, finish_reason, and token usage.