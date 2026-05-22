import { loadModels, saveChatSettings } from './api.js';
import { activeChatId } from './sidebar.js';
import { setStatus } from './streaming.js';

const SAFE_FALLBACK_ALIASES = ['gemini_fast', 'openai_nano', 'claude_fast', 'deepseek_fast'];

function extractAliases(payload) {
    const data = payload?.data || {};
    const aliases = data.aliases || data.models || {};
    if (Array.isArray(aliases)) {
        return aliases.map((item) => item.alias || item.model_alias || item.id).filter(Boolean);
    }
    return Object.keys(aliases).filter(Boolean);
}

function isSafeAlias(alias) {
    return /^[a-zA-Z0-9_.:-]{1,64}$/.test(alias || '') && !/key|secret|token/i.test(alias);
}

export function currentSettings() {
    return {
        provider_alias: '',
        model_alias: document.getElementById('v2ModelSelect')?.value || 'gemini_fast',
        temperature: Number(document.getElementById('v2Temperature')?.value || '0.7'),
        runtime_id: document.getElementById('v2RuntimeSelect')?.value || 'sovereign',
        mode: document.getElementById('v2AgentModeToggle')?.getAttribute('aria-pressed') === 'true' ? 'agent' : 'default',
        tools_enabled: true,
        web_search_enabled: document.getElementById('v2WebSearchToggle')?.getAttribute('aria-pressed') === 'true',
        memory_v3_enabled: true,
    };
}

export async function hydrateModelAliases() {
    const select = document.getElementById('v2ModelSelect');
    if (!select) return;
    const payload = await loadModels();
    const aliases = extractAliases(payload).filter(isSafeAlias);
    const safeAliases = aliases.length ? aliases : SAFE_FALLBACK_ALIASES;
    select.replaceChildren(...safeAliases.map((alias) => {
        const option = document.createElement('option');
        option.value = alias;
        option.textContent = alias;
        return option;
    }));
}

export function openModelSettings() {
    document.getElementById('v2ModelSettingsModal')?.classList.remove('hidden');
}

export function bindModelSettings() {
    const temp = document.getElementById('v2Temperature');
    const tempValue = document.getElementById('v2TemperatureValue');
    temp?.addEventListener('input', () => {
        if (tempValue) tempValue.textContent = temp.value;
    });
    document.getElementById('v2SaveSettingsBtn')?.addEventListener('click', async () => {
        const chatId = activeChatId();
        if (!chatId) {
            setStatus('Create or select a chat first', 'error');
            return;
        }
        try {
            await saveChatSettings(chatId, currentSettings());
            setStatus('Settings saved', 'ready');
            document.getElementById('v2ModelSettingsModal')?.classList.add('hidden');
        } catch (error) {
            setStatus(error.message, 'error');
        }
    });
}
