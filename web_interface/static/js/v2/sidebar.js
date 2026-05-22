import { createChat, deleteChat, loadChats, loadMessages, pinChat, updateChatTitle } from './api.js';

const state = {
    sessions: [],
    activeChatId: null,
    offset: 0,
    limit: 30,
    filter: '',
};

function sessionTitle(session) {
    return session.title || session.chat_title || session.chat_id || 'Untitled';
}

function renderItem(session, onSelect) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'kuro-v2-session-item';
    button.dataset.chatId = session.chat_id;
    if (session.chat_id === state.activeChatId) button.classList.add('active');
    button.innerHTML = `
        <span class="truncate">${sessionTitle(session)}</span>
        <span aria-hidden="true">${session.is_pinned ? '•' : ''}</span>
    `;
    button.addEventListener('click', () => onSelect(session));
    return button;
}

export function renderSessions({ onSelect }) {
    const list = document.getElementById('v2SessionList');
    const pinned = document.getElementById('v2PinnedSessions');
    if (!list || !pinned) return;
    list.replaceChildren();
    pinned.replaceChildren();
    const filter = state.filter.toLowerCase();
    const sessions = state.sessions.filter((session) => sessionTitle(session).toLowerCase().includes(filter));
    sessions.filter((session) => session.is_pinned).forEach((session) => pinned.appendChild(renderItem(session, onSelect)));
    sessions.filter((session) => !session.is_pinned).forEach((session) => list.appendChild(renderItem(session, onSelect)));
}

export async function refreshSessions({ reset = false, persona = '', onSelect } = {}) {
    if (reset) state.offset = 0;
    const payload = await loadChats({ persona, limit: state.limit, offset: state.offset }).catch(() => ({ data: [] }));
    const sessions = payload.data || [];
    state.sessions = reset ? sessions : [...state.sessions, ...sessions];
    state.offset += sessions.length;
    renderSessions({ onSelect });
    return state.sessions;
}

export async function selectSession(session, { renderMessages }) {
    state.activeChatId = session.chat_id;
    document.getElementById('v2ChatTitle').textContent = sessionTitle(session);
    renderSessions({ onSelect: (next) => selectSession(next, { renderMessages }) });
    const payload = await loadMessages(session.chat_id, { limit: 40 }).catch(() => ({ data: { messages: [] } }));
    renderMessages(payload.data?.messages || payload.messages || []);
}

export async function startNewChat({ persona = 'consultant', renderMessages, onSelect }) {
    const payload = await createChat({ persona, title: 'New Chat' });
    const chat = {
        chat_id: payload.data.chat_id,
        title: payload.data.title || 'New Chat',
        persona,
        is_pinned: false,
    };
    state.sessions = [chat, ...state.sessions];
    onSelect?.(chat);
    renderMessages?.([]);
    renderSessions({ onSelect });
    return chat;
}

export function bindSidebar({ persona, renderMessages, onSelect }) {
    document.getElementById('v2NewChatBtn')?.addEventListener('click', () => startNewChat({
        persona,
        renderMessages,
        onSelect,
    }));
    document.getElementById('v2LoadMoreChats')?.addEventListener('click', () => refreshSessions({ persona, onSelect }));
    document.getElementById('v2ChatSearch')?.addEventListener('input', (event) => {
        state.filter = event.target.value || '';
        renderSessions({ onSelect });
    });
    document.getElementById('v2OpenSidebar')?.addEventListener('click', () => {
        document.getElementById('v2Sidebar')?.setAttribute('data-open', 'true');
    });
    document.getElementById('v2CloseSidebar')?.addEventListener('click', () => {
        document.getElementById('v2Sidebar')?.removeAttribute('data-open');
    });
}

export async function renameActiveChat() {
    if (!state.activeChatId) return;
    const title = window.prompt('Rename chat', document.getElementById('v2ChatTitle')?.textContent || '');
    if (!title) return;
    await updateChatTitle(state.activeChatId, title);
    const session = state.sessions.find((item) => item.chat_id === state.activeChatId);
    if (session) session.title = title;
    document.getElementById('v2ChatTitle').textContent = title;
}

export async function deleteActiveChat() {
    if (!state.activeChatId) return;
    await deleteChat(state.activeChatId);
    state.sessions = state.sessions.filter((session) => session.chat_id !== state.activeChatId);
    state.activeChatId = null;
}

export async function togglePinActiveChat() {
    if (!state.activeChatId) return;
    const session = state.sessions.find((item) => item.chat_id === state.activeChatId);
    if (!session) return;
    session.is_pinned = !session.is_pinned;
    await pinChat(session.chat_id, session.is_pinned);
}

export function activeChatId() {
    return state.activeChatId;
}

export { state as sidebarState };
