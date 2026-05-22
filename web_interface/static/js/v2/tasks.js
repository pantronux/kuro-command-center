import { postJson } from './api.js';
import { setStatus } from './streaming.js';

export async function createTaskFromPrompt(defaultTitle = '') {
    const title = window.prompt('Task title', defaultTitle || '');
    if (!title) return;
    try {
        await postJson('/api/tasks', { title, source_chat_id: window.KURO_V2_ACTIVE_CHAT_ID || '' });
        setStatus('Task created', 'ready');
    } catch (error) {
        setStatus(`Tasks unavailable: ${error.message}`, 'error');
    }
}

export async function createReminderFromPrompt(defaultText = '') {
    const remindAt = window.prompt('Reminder time', 'tomorrow');
    if (!remindAt) return;
    const text = window.prompt('Reminder text', defaultText || '');
    if (!text) return;
    try {
        await postJson('/api/reminders', {
            remind_at: remindAt,
            channel: 'web',
            metadata: { text, source_chat_id: window.KURO_V2_ACTIVE_CHAT_ID || '' },
        });
        setStatus('Reminder created', 'ready');
    } catch (error) {
        setStatus(`Reminders unavailable: ${error.message}`, 'error');
    }
}

export function bindTaskButtons({ lastMessageText }) {
    document.getElementById('v2CreateTaskBtn')?.addEventListener('click', () => createTaskFromPrompt(lastMessageText?.() || ''));
    document.getElementById('v2CreateReminderBtn')?.addEventListener('click', () => createReminderFromPrompt(lastMessageText?.() || ''));
}
