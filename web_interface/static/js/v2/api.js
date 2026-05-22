const DEFAULT_HEADERS = {
    'Accept': 'application/json',
};

export function getContext() {
    const el = document.getElementById('kuro-v2-context');
    if (!el) return {};
    try {
        return JSON.parse(el.textContent || '{}');
    } catch (_) {
        return {};
    }
}

export async function apiRequest(path, options = {}) {
    const response = await fetch(path, {
        credentials: 'include',
        ...options,
        headers: {
            ...DEFAULT_HEADERS,
            ...(options.headers || {}),
        },
    });
    if (response.status === 401) {
        window.location.href = '/login';
        throw new Error('Authentication required');
    }
    return response;
}

export async function readJson(response) {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        const message = payload?.error?.message || payload?.detail || payload?.error || `HTTP ${response.status}`;
        const error = new Error(String(message));
        error.status = response.status;
        error.payload = payload;
        throw error;
    }
    return payload;
}

export async function getJson(path, options = {}) {
    return readJson(await apiRequest(path, options));
}

export async function postJson(path, body, options = {}) {
    return readJson(await apiRequest(path, {
        ...options,
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...(options.headers || {}),
        },
        body: JSON.stringify(body || {}),
    }));
}

export async function patchJson(path, body, options = {}) {
    return readJson(await apiRequest(path, {
        ...options,
        method: 'PATCH',
        headers: {
            'Content-Type': 'application/json',
            ...(options.headers || {}),
        },
        body: JSON.stringify(body || {}),
    }));
}

export async function deleteJson(path, options = {}) {
    return readJson(await apiRequest(path, { ...options, method: 'DELETE' }));
}

export async function loadModels() {
    return getJson('/api/models').catch(() => ({
        status: 'error',
        data: {
            aliases: {
                gemini_fast: { alias: 'gemini_fast' },
                openai_nano: { alias: 'openai_nano' },
                claude_fast: { alias: 'claude_fast' },
                deepseek_fast: { alias: 'deepseek_fast' },
            },
        },
    }));
}

export async function loadChats({ persona = '', limit = 30, offset = 0 } = {}) {
    const params = new URLSearchParams();
    if (persona) params.set('persona', persona);
    params.set('limit', String(limit));
    params.set('offset', String(offset));
    return getJson(`/api/chats?${params.toString()}`);
}

export async function createChat({ persona = 'consultant', title = 'New Chat' } = {}) {
    return postJson('/api/chats', { persona, title });
}

export async function loadMessages(chatId, { limit = 40, beforeId = null } = {}) {
    const params = new URLSearchParams({ limit: String(limit) });
    if (beforeId) params.set('before_id', String(beforeId));
    return getJson(`/api/chats/${encodeURIComponent(chatId)}/messages?${params.toString()}`);
}

export async function updateChatTitle(chatId, title) {
    return apiRequest(`/api/chats/${encodeURIComponent(chatId)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
    }).then(readJson);
}

export async function deleteChat(chatId) {
    return deleteJson(`/api/chats/${encodeURIComponent(chatId)}`);
}

export async function pinChat(chatId, pinned) {
    const action = pinned ? 'pin' : 'unpin';
    return postJson(`/api/chats/${encodeURIComponent(chatId)}/${action}`, {});
}

export async function saveChatSettings(chatId, settings) {
    return postJson(`/api/chats/${encodeURIComponent(chatId)}/settings`, settings);
}

export async function bookmarkMessage(chatId, messageId) {
    return postJson(`/api/chats/${encodeURIComponent(chatId)}/messages/${messageId}/bookmark`, {});
}

export async function regenerateMessage(chatId, messageId) {
    return postJson(`/api/chats/${encodeURIComponent(chatId)}/messages/${messageId}/regenerate`, {});
}

export async function editMessage(chatId, messageId, newContent) {
    return apiRequest(`/api/chats/${encodeURIComponent(chatId)}/messages/${messageId}/edit`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_content: newContent }),
    }).then(readJson);
}
