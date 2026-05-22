import {
    bookmarkMessage,
    editMessage,
    getContext,
    regenerateMessage,
} from './api.js';
import { bindAdminSettings, openAdminSettings } from './admin_settings.js';
import { bindMarket } from './market.js';
import { bindModelSettings, currentSettings, hydrateModelAliases, openModelSettings } from './model_settings.js';
import { bindModalCloseButtons, bindProfileMenu } from './profile_menu.js';
import {
    activeChatId,
    bindSidebar,
    refreshSessions,
    selectSession,
    sidebarState,
    startNewChat,
} from './sidebar.js';
import { streamChat, setStatus } from './streaming.js';
import { bindTaskButtons } from './tasks.js';

const context = getContext();
let selectedPersona = context.restrictedPersona || 'consultant';
let lastUserMessage = '';
let activeAssistantNode = null;

function icon(name) {
    return `<i data-lucide="${name}"></i>`;
}

function renderIcons() {
    window.lucide?.createIcons?.();
}

function messageAvatar(role) {
    if (role === 'assistant') return '<img src="/profile/kuro_avatar.png" alt="Kuro">';
    const initial = (context.displayName || context.username || 'U').slice(0, 1).toUpperCase();
    return `<span>${initial}</span>`;
}

function messageActions(message) {
    const idAttr = message.id ? `data-message-id="${message.id}"` : '';
    return `
        <div class="kuro-v2-message-actions" ${idAttr}>
            <button type="button" data-action="copy" title="Copy" aria-label="Copy">${icon('copy')}</button>
            ${message.role === 'user' ? `<button type="button" data-action="edit" title="Edit" aria-label="Edit">${icon('pencil')}</button>` : ''}
            ${message.role === 'assistant' ? `<button type="button" data-action="regenerate" title="Regenerate" aria-label="Regenerate">${icon('refresh-cw')}</button>` : ''}
            <button type="button" data-action="bookmark" title="Bookmark" aria-label="Bookmark">${icon('bookmark')}</button>
            <button type="button" data-action="export" title="Export" aria-label="Export">${icon('download')}</button>
        </div>
    `;
}

function renderMessage(message) {
    const role = message.role === 'user' ? 'user' : 'assistant';
    const article = document.createElement('article');
    article.className = `kuro-v2-message ${role}`;
    article.dataset.role = role;
    if (message.id) article.dataset.messageId = message.id;
    const raw = message.content || message.text || '';
    const content = window.marked?.parse ? window.marked.parse(raw) : raw.replace(/[<>&]/g, (ch) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[ch]));
    article.innerHTML = `
        <div class="kuro-v2-message-avatar">${messageAvatar(role)}</div>
        <div class="kuro-v2-message-body">
            <div class="kuro-v2-message-content">${content}</div>
            ${messageActions({ ...message, role })}
        </div>
    `;
    return article;
}

function appendMessage(message) {
    const list = document.getElementById('v2Messages');
    if (!list) return null;
    const node = renderMessage(message);
    list.appendChild(node);
    list.scrollTop = list.scrollHeight;
    renderIcons();
    return node;
}

function renderMessages(messages) {
    const list = document.getElementById('v2Messages');
    if (!list) return;
    list.replaceChildren();
    if (!messages.length) {
        appendMessage({ role: 'assistant', content: `Hello ${context.masterName || context.displayName || ''}.` });
        return;
    }
    messages.forEach((message) => appendMessage(message));
}

function openDrawer(title, payload) {
    const drawer = document.getElementById('v2RightDrawer');
    const drawerTitle = document.getElementById('v2DrawerTitle');
    const content = document.getElementById('v2DrawerContent');
    if (!drawer || !drawerTitle || !content) return;
    drawerTitle.textContent = title;
    content.innerHTML = `<pre>${JSON.stringify(payload || {}, null, 2)}</pre>`;
    drawer.dataset.open = 'true';
}

function bindDrawer() {
    document.getElementById('v2OpenSources')?.addEventListener('click', () => openDrawer('Sources', {
        citations: [],
        note: 'Sources appear here when streaming events include source metadata.',
    }));
    document.getElementById('v2OpenMemory')?.addEventListener('click', () => openDrawer('Memory', {
        memory: [],
        policy: 'Memory context follows backend policy.',
    }));
    document.getElementById('v2CloseDrawer')?.addEventListener('click', () => {
        document.getElementById('v2RightDrawer')?.setAttribute('data-open', 'false');
    });
}

async function ensureChat() {
    if (activeChatId()) return activeChatId();
    const chat = await startNewChat({
        persona: selectedPersona,
        renderMessages,
        onSelect: (session) => selectSession(session, { renderMessages }),
    });
    return chat.chat_id;
}

async function sendMessage(text) {
    const message = text.trim();
    if (!message) return;
    lastUserMessage = message;
    const chatId = await ensureChat();
    window.KURO_V2_ACTIVE_CHAT_ID = chatId;
    appendMessage({ role: 'user', content: message });
    activeAssistantNode = appendMessage({ role: 'assistant', content: '' });
    const contentNode = activeAssistantNode?.querySelector('.kuro-v2-message-content');
    document.getElementById('v2RetryLast')?.classList.add('hidden');
    await streamChat({
        message,
        persona: selectedPersona,
        chatId,
        settings: currentSettings(),
        onToken: (token) => {
            if (!contentNode) return;
            contentNode.textContent += token;
            const list = document.getElementById('v2Messages');
            if (list) list.scrollTop = list.scrollHeight;
        },
        onEvent: (event) => {
            if (event.event?.startsWith('tool_')) openDrawer('Tools', event.data);
            if (event.event === 'memory_context') openDrawer('Memory', event.data);
        },
        onError: () => {
            document.getElementById('v2RetryLast')?.classList.remove('hidden');
        },
    });
}

function bindComposer() {
    const form = document.getElementById('v2ComposerForm');
    const input = document.getElementById('v2MessageInput');
    form?.addEventListener('submit', async (event) => {
        event.preventDefault();
        const text = input?.value || '';
        if (input) input.value = '';
        await sendMessage(text);
    });
    input?.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
    });
    document.getElementById('v2RetryLast')?.addEventListener('click', () => sendMessage(lastUserMessage));
}

function bindToolToggles() {
    ['v2WebSearchToggle', 'v2AgentModeToggle'].forEach((id) => {
        document.getElementById(id)?.addEventListener('click', (event) => {
            const button = event.currentTarget;
            button.setAttribute('aria-pressed', button.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
        });
    });
    document.getElementById('v2DeepResearchBtn')?.addEventListener('click', () => {
        const topic = window.prompt('Research topic', lastUserMessage || '');
        if (topic) sendMessage(`/research ${topic}`);
    });
}

async function handleMessageAction(event) {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const article = button.closest('.kuro-v2-message');
    const content = article?.querySelector('.kuro-v2-message-content')?.innerText || '';
    const messageId = article?.dataset.messageId;
    const chatId = activeChatId();
    if (button.dataset.action === 'copy') {
        await navigator.clipboard?.writeText(content);
        setStatus('Copied', 'ready');
    }
    if (button.dataset.action === 'edit' && chatId && messageId) {
        const next = window.prompt('Edit message', content);
        if (next) await editMessage(chatId, messageId, next);
    }
    if (button.dataset.action === 'regenerate' && chatId && messageId) {
        await regenerateMessage(chatId, messageId);
        await sendMessage(lastUserMessage);
    }
    if (button.dataset.action === 'bookmark' && chatId && messageId) {
        await bookmarkMessage(chatId, messageId);
        setStatus('Bookmark updated', 'ready');
    }
    if (button.dataset.action === 'export' && chatId) {
        window.open(`/api/chats/${encodeURIComponent(chatId)}/export?format=md`, '_blank', 'noopener');
    }
}

async function boot() {
    window.KURO_USER_CONTEXT = context;
    document.getElementById('v2ActivePersona').textContent = selectedPersona.charAt(0).toUpperCase() + selectedPersona.slice(1);
    bindModalCloseButtons();
    bindProfileMenu({ onOpenAdmin: openAdminSettings, onOpenModelSettings: openModelSettings });
    bindAdminSettings();
    bindModelSettings();
    bindDrawer();
    bindComposer();
    bindToolToggles();
    bindTaskButtons({ lastMessageText: () => lastUserMessage });
    bindMarket();
    bindSidebar({
        persona: selectedPersona,
        renderMessages,
        onSelect: (session) => selectSession(session, { renderMessages }),
    });
    document.getElementById('v2Messages')?.addEventListener('click', handleMessageAction);
    await hydrateModelAliases();
    await refreshSessions({
        reset: true,
        persona: selectedPersona,
        onSelect: (session) => selectSession(session, { renderMessages }),
    });
    renderIcons();
}

boot().catch((error) => setStatus(error.message || 'Frontend V2 failed', 'error'));
