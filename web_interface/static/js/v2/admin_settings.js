import { getJson } from './api.js';

const PANEL_ENDPOINTS = {
    'system-status': '/api/system/status',
    'storage-health': '/api/admin/storage/health',
    'memory-v3': '/api/admin/memory-v3/health',
    providers: '/api/admin/providers/health',
    temperature: '/api/models',
    runtime: '/api/capabilities',
    market: '/api/admin/market-v2/health',
    ingestion: '/api/ingestion/analytics/overview',
    evaluation: '/api/evaluation/summary',
    backup: '/api/admin/backup/status',
    telegram: '/api/admin/telegram-v2/health',
    'feature-flags': '/api/admin/enterprise/flags',
};

function pretty(value) {
    return JSON.stringify(value || {}, null, 2);
}

async function renderPanel(panelId) {
    const target = document.getElementById('v2AdminPanelContent');
    if (!target) return;
    target.innerHTML = '<p>Loading...</p>';
    const endpoint = PANEL_ENDPOINTS[panelId];
    try {
        const payload = await getJson(endpoint);
        target.innerHTML = `<pre>${pretty(payload.data ?? payload)}</pre>`;
    } catch (error) {
        target.innerHTML = `<pre>${pretty({ status: 'unavailable', message: error.message, endpoint })}</pre>`;
    }
}

export function openAdminSettings() {
    const modal = document.getElementById('v2AdminSettingsModal');
    if (!modal) return;
    modal.classList.remove('hidden');
    renderPanel('system-status');
}

export function bindAdminSettings() {
    document.querySelectorAll('[data-admin-panel]').forEach((button) => {
        button.addEventListener('click', () => {
            document.querySelectorAll('[data-admin-panel]').forEach((tab) => tab.classList.remove('active'));
            button.classList.add('active');
            renderPanel(button.dataset.adminPanel);
        });
    });
}
