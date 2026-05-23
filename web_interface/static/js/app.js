/**
 * Kuro AI Web Dashboard - Main Application V4.0
 * One UI + Glassmorphism Design with Infinite Scroll
 *
 * --- Header Doc ---
 * Purpose: Frontend app for the main chat dashboard (chat, personas, HUD, market chips, infinite scroll, System Status modal).
 * Caller: Loaded from web_interface/templates/index.html.
 * Dependencies: Tailwind (CDN), Lucide icons, live2d_manager.js (avatar), browser Web APIs (WebSocket, fetch).
 * Main Functions: kuroSendMessage, kuroLoadHistory, kuroRenderSentinelTicker, persona switcher.
 * Side Effects: /api/chat XHR, WebSocket /ws/dashboard, localStorage cache, DOM mutations.
 */

// ============================================
// Configuration
// ============================================
const CONFIG = {
    API_BASE: '/api',
    MAX_FILES: 10,
    CHAT_PAGE_SIZE: 20,
    ALLOWED_TYPES: {
        'image/': 'image',
        'video/': 'video',
        'application/pdf': 'pdf',
        'application/msword': 'doc',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
        'application/vnd.ms-excel': 'xls',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
        'application/vnd.ms-powerpoint': 'ppt',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
        'application/json': 'json',
        'application/x-yaml': 'yaml',
        'text/plain': 'text',
        'text/markdown': 'markdown',
        'text/x-python': 'code',
        'text/csv': 'csv',
    },
    ALLOWED_EXTENSIONS: [
        '.txt', '.md', '.py', '.csv', '.log',
        '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.json', '.yaml', '.yml'
    ],
};

const MODEL_ALIAS_FALLBACK = [
    { alias: 'gemini_fast', display_name: 'Gemini Flash' },
    { alias: 'openai_nano', display_name: 'OpenAI Nano' },
    { alias: 'claude_fast', display_name: 'Claude Haiku' },
    { alias: 'deepseek_fast', display_name: 'DeepSeek Fast' },
    { alias: 'ollama_local', display_name: 'Ollama Local' },
];

const COMPOSER_FEATURE_STORAGE_KEY = 'kuro_composer_feature_state_v1';
const COMPOSER_FEATURE_DEFAULTS = {
    deep_research: false,
    web_search: false,
    agent_mode: false,
    task_mode: false,
    reminder_mode: false,
};
const COMPOSER_FEATURE_LABELS = {
    deep_research: 'Deep Research',
    web_search: 'Web Search',
    agent_mode: 'Agent Mode',
    task_mode: 'Task',
    reminder_mode: 'Reminder',
};
const COMPOSER_ACTION_TO_TOOL_ID = {
    deep_research: 'deep_research',
    web_search: 'web_search',
    agent_mode: 'agent_mode',
    task_mode: 'create_task',
    reminder_mode: 'create_reminder',
};

// ============================================
// Authentication Helper Functions (Cookie-Based)
// ============================================
function getUsername() {
    return window.KURO_USER_CONTEXT?.displayName || localStorage.getItem('kuro_username') || sessionStorage.getItem('kuro_username') || 'Pantronux';
}

function getUserInitial() {
    const source = (
        window.KURO_USER_CONTEXT?.displayName
        || window.KURO_USER_CONTEXT?.username
        || getUsername()
        || 'U'
    ).trim();
    return (source[0] || 'U').toUpperCase();
}

function logout() {
    console.log('Logging out...');
    fetch('/api/auth/logout', { method: 'POST' })
        .then(() => { window.location.href = '/login'; })
        .catch(() => { window.location.href = '/login'; });
}

// DEPRECATED: getChatSessionId() removed in V1.0.0 Chat Isolation.
// Use currentChatId state variable instead, managed per-chat by SSE meta events.

async function authFetch(url, options = {}) {
    const reqOptions = {
        ...options,
        credentials: options.credentials || 'include',
        headers: {
            ...(options.headers || {}),
        },
    };
    try {
        const response = await fetch(url, reqOptions);
        if (response.status === 401) {
            window.location.href = '/login';
            throw new Error('Authentication required');
        }
        if (!response.ok && response.status >= 500) {
            showToast(`Server error (${response.status}). Coba lagi dalam beberapa saat.`, 'error');
        }
        return response;
    } catch (error) {
        if (error && error.name === 'TypeError') {
            showToast('Koneksi terputus. Periksa jaringan kamu.', 'error');
        }
        throw error;
    }
}

// ============================================
// State
// ============================================
let selectedFiles = [];
let isProcessing = false;
let chatHistory = [];
let selectedPersona = 'consultant';
let currentChatId = null;
let chatSessions = [];
let runtimeMode = localStorage.getItem('kuro-runtime-mode') || 'normal';
let playgroundSessionId = null;
let playgroundExecuting = false;
let playgroundHistorySessionId = null;
let sessionSearchQuery = '';
let selectedModelAlias = localStorage.getItem('kuro_model_alias') || 'gemini_fast';
let availableModelAliases = [...MODEL_ALIAS_FALLBACK];
let pendingRenameChatId = null;
let pendingDeleteChatId = null;
let composerFeatureState = loadComposerFeatureState();
let composerToolAvailability = null;

// Infinite Scroll State
let chatOffset = 0;
let isLoadingMore = false;
let hasMoreMessages = true;
let scrollAnchorPosition = null;
let sessionDrafts = {}; // Beta 5: Save unsent drafts per session
let chatOldestMessageIdBySession = {};
let chatHasMoreBySession = {};
let currentUserProfile = {
    username: getUsername(),
    is_admin: window.KURO_USER_CONTEXT?.role === 'Administrator',
};
const VALID_PERSONAS = ['consultant', 'advisor', 'chill', 'tactical', 'chancellor', 'auditor'];

/**
 * Persist unsent draft text for a chat session.
 * Falls back to in-memory cache when sessionStorage is unavailable.
 * @param {string} chatId
 * @param {string} text
 */
function saveDraft(chatId, text) {
    if (!chatId) return;
    try {
        if (text && text.trim()) {
            sessionStorage.setItem(`draft_${chatId}`, text);
        } else {
            sessionStorage.removeItem(`draft_${chatId}`);
        }
    } catch (_) {
        sessionDrafts[chatId] = text || '';
    }
}

/**
 * Load the saved draft text for a chat session.
 * @param {string} chatId
 * @returns {string}
 */
function loadDraft(chatId) {
    if (!chatId) return '';
    try {
        return sessionStorage.getItem(`draft_${chatId}`) || sessionDrafts[chatId] || '';
    } catch (_) {
        return sessionDrafts[chatId] || '';
    }
}

function resolveComposerInputElement() {
    if (elements.welcomeScreen && !elements.welcomeScreen.classList.contains('hidden') && elements.welcomeInput) {
        return elements.welcomeInput;
    }
    return elements.messageInput;
}

function queueComposerPrompt(prefixText) {
    const targetInput = resolveComposerInputElement();
    if (!targetInput) return;
    const cleanPrefix = String(prefixText || '').trim();
    if (!cleanPrefix) return;
    const current = (targetInput.value || '').trim();
    targetInput.value = current ? `${current}\n${cleanPrefix}` : cleanPrefix;
    targetInput.dispatchEvent(new Event('input'));
    targetInput.focus();
}

function loadComposerFeatureState() {
    try {
        const parsed = JSON.parse(localStorage.getItem(COMPOSER_FEATURE_STORAGE_KEY) || '{}');
        return { ...COMPOSER_FEATURE_DEFAULTS, ...(parsed || {}) };
    } catch (_) {
        return { ...COMPOSER_FEATURE_DEFAULTS };
    }
}

function saveComposerFeatureState() {
    try {
        localStorage.setItem(COMPOSER_FEATURE_STORAGE_KEY, JSON.stringify(composerFeatureState));
    } catch (_) {
        // Non-critical: feature toggles still work for this page session.
    }
}

function getActiveComposerFeatures() {
    return Object.keys(COMPOSER_FEATURE_DEFAULTS).filter((action) => Boolean(composerFeatureState[action]));
}

function isComposerFeatureAvailable(action) {
    if (!composerToolAvailability) return true;
    const toolId = COMPOSER_ACTION_TO_TOOL_ID[action];
    return !toolId || composerToolAvailability.has(toolId);
}

function updateComposerFeatureIndicators() {
    const activeActions = getActiveComposerFeatures();
    document.querySelectorAll('[data-composer-action]').forEach((button) => {
        const action = button.dataset.composerAction;
        if (!Object.prototype.hasOwnProperty.call(COMPOSER_FEATURE_DEFAULTS, action)) return;

        const available = isComposerFeatureAvailable(action);
        const active = available && Boolean(composerFeatureState[action]);
        button.classList.toggle('composer-feature-active', active);
        button.toggleAttribute('disabled', !available);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
        button.title = available
            ? `${COMPOSER_FEATURE_LABELS[action]} ${active ? 'active' : 'inactive'}`
            : `${COMPOSER_FEATURE_LABELS[action]} belum aktif di backend`;
    });

    [elements?.uploadBtn, elements?.welcomeUploadBtn].forEach((button) => {
        if (!button) return;
        button.classList.toggle('has-active-features', activeActions.length > 0);
        button.title = activeActions.length
            ? `Active tools: ${activeActions.map((action) => COMPOSER_FEATURE_LABELS[action]).join(', ')}`
            : 'Open tools';
    });
}

function toggleComposerFeature(action) {
    if (!Object.prototype.hasOwnProperty.call(COMPOSER_FEATURE_DEFAULTS, action)) return;
    if (!isComposerFeatureAvailable(action)) {
        showNotification(`${COMPOSER_FEATURE_LABELS[action]} belum tersedia dari backend.`, 'error');
        return;
    }
    composerFeatureState[action] = !composerFeatureState[action];
    saveComposerFeatureState();
    updateComposerFeatureIndicators();
    showNotification(
        `${COMPOSER_FEATURE_LABELS[action]} ${composerFeatureState[action] ? 'aktif' : 'nonaktif'}`,
        composerFeatureState[action] ? 'success' : 'info'
    );
}

async function loadComposerToolAvailability() {
    try {
        const response = await authFetch(`${CONFIG.API_BASE}/tools?runtime_id=sovereign&workspace_id=default`);
        if (!response.ok) return;
        const payload = await response.json();
        const tools = Array.isArray(payload?.data) ? payload.data : [];
        composerToolAvailability = new Set(tools.map((tool) => tool.tool_id).filter(Boolean));
    } catch (_) {
        composerToolAvailability = null;
    } finally {
        updateComposerFeatureIndicators();
    }
}

function openComposerActionDestination(url) {
    if (!url) return;
    window.location.href = url;
}

function closeComposerMenus() {
    elements.composerActionMenu?.classList.add('hidden');
    elements.welcomeComposerActionMenu?.classList.add('hidden');
}

function toggleComposerMenu(menuElement) {
    if (!menuElement) return;
    const shouldShow = menuElement.classList.contains('hidden');
    closeComposerMenus();
    if (shouldShow) {
        menuElement.classList.remove('hidden');
    }
}

function normalizeModelDisplayName(alias, displayName) {
    if (displayName && displayName.trim()) {
        return displayName
            .replace(/\bfast\b/i, 'Flash')
            .replace(/\bnano\b/i, 'Nano')
            .trim();
    }
    const fallback = MODEL_ALIAS_FALLBACK.find((item) => item.alias === alias);
    return fallback ? fallback.display_name : alias;
}

function applyModelAlias(alias) {
    if (!alias) return;
    selectedModelAlias = String(alias).trim();
    localStorage.setItem('kuro_model_alias', selectedModelAlias);
    [elements.composerModelSelect, elements.welcomeModelSelect].forEach((selectEl) => {
        if (selectEl) selectEl.value = selectedModelAlias;
    });
}

function renderModelSelectorOptions(models) {
    const options = Array.isArray(models) && models.length ? models : MODEL_ALIAS_FALLBACK;
    const normalized = options.map((item) => ({
        alias: String(item.alias || '').trim(),
        display_name: normalizeModelDisplayName(item.alias, item.display_name),
    })).filter((item) => item.alias);
    if (!normalized.some((item) => item.alias === selectedModelAlias)) {
        normalized.unshift({ alias: selectedModelAlias, display_name: normalizeModelDisplayName(selectedModelAlias, '') });
    }
    availableModelAliases = normalized;

    const optionHtml = normalized
        .map((item) => `<option value="${escapeHtml(item.alias)}">${escapeHtml(item.display_name)}</option>`)
        .join('');
    [elements.composerModelSelect, elements.welcomeModelSelect].forEach((selectEl) => {
        if (!selectEl) return;
        selectEl.innerHTML = optionHtml;
        selectEl.value = selectedModelAlias;
    });
}

async function loadComposerModelAliases() {
    try {
        const response = await authFetch('/api/models');
        if (!response.ok) {
            renderModelSelectorOptions(MODEL_ALIAS_FALLBACK);
            return;
        }
        const payload = await response.json();
        const models = payload?.data?.models;
        renderModelSelectorOptions(models);
    } catch (_) {
        renderModelSelectorOptions(MODEL_ALIAS_FALLBACK);
    }
}

function handleComposerAction(action) {
    switch (action) {
        case 'attach':
            elements.fileInput?.click();
            return;
        case 'files':
            openFilesModal();
            return;
        case 'deep_research':
            toggleComposerFeature(action);
            return;
        case 'web_search':
            toggleComposerFeature(action);
            return;
        case 'agent_mode':
            toggleComposerFeature(action);
            return;
        case 'task_mode':
            toggleComposerFeature(action);
            return;
        case 'reminder_mode':
            toggleComposerFeature(action);
            return;
        case 'market_page':
            openComposerActionDestination('/market');
            return;
        case 'intelligence_page':
            openComposerActionDestination('/intelligence');
            return;
        case 'tutorial_page':
            openComposerActionDestination('/tutorial');
            return;
        case 'playground_mode':
            applyRuntimeMode('playground');
            return;
        default:
            return;
    }
}

function truncateForToolInput(value, maxLength) {
    const text = String(value || '').trim();
    if (text.length <= maxLength) return text;
    return `${text.slice(0, Math.max(0, maxLength - 3)).trim()}...`;
}

function buildComposerToolInput(action, message) {
    const cleanMessage = String(message || '').trim();
    const workspaceId = currentChatId || 'default';
    switch (action) {
        case 'web_search':
            return {
                query: truncateForToolInput(cleanMessage, 1000),
                search_type: 'search',
                max_results: 5,
            };
        case 'deep_research':
            return {
                query: truncateForToolInput(cleanMessage, 2000),
                workspace_id: workspaceId,
                max_sources: 5,
            };
        case 'agent_mode':
            return {
                goal: truncateForToolInput(cleanMessage, 4000),
                requested_steps: 5,
                allowed_tool_ids: ['web_search', 'deep_research', 'create_task', 'create_reminder'],
            };
        case 'task_mode':
            return {
                title: truncateForToolInput(cleanMessage.split('\n')[0] || cleanMessage, 500) || 'Untitled task',
                description: cleanMessage,
                source_chat_id: currentChatId || null,
                metadata: {
                    source: 'web_composer',
                    persona: selectedPersona,
                    model_alias: selectedModelAlias,
                },
            };
        case 'reminder_mode':
            return {
                remind_at: truncateForToolInput(cleanMessage, 128) || 'manual follow-up',
                channel: 'web',
                metadata: {
                    source: 'web_composer',
                    text: cleanMessage,
                    source_chat_id: currentChatId || '',
                    persona: selectedPersona,
                },
            };
        default:
            return {};
    }
}

async function executeComposerTool(action, message) {
    const toolId = COMPOSER_ACTION_TO_TOOL_ID[action];
    if (!toolId) return null;
    const input = buildComposerToolInput(action, message);
    const response = await authFetch(`${CONFIG.API_BASE}/tools/${encodeURIComponent(toolId)}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            input,
            runtime_id: 'sovereign',
            workspace_id: currentChatId || 'default',
            trace_id: `ui_tool_${Date.now()}_${Math.random().toString(16).slice(2)}`,
            metadata: {
                source: 'web_composer',
                action,
                chat_id: currentChatId || '',
                persona: selectedPersona,
            },
        }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        const detail = payload?.detail || payload?.error?.message || `Tool request failed (${response.status})`;
        throw new Error(detail);
    }
    return payload?.data || payload;
}

function summarizeComposerToolResult(result) {
    if (!result) return 'No result.';
    const status = result.status || (result.ok ? 'success' : 'unknown');
    if (result.approval_required) {
        return `Approval required. approval_id=${result.approval_id || '-'}`;
    }
    if (result.error?.message) {
        return `Error: ${result.error.message}`;
    }
    const output = result.output || {};
    if (Array.isArray(result.sources) && result.sources.length) {
        const sources = result.sources.slice(0, 5).map((source, index) => {
            const title = source.title || source.url || `Source ${index + 1}`;
            const url = source.url ? ` (${source.url})` : '';
            return `${index + 1}. ${title}${url}`;
        });
        return `Status: ${status}\nSources:\n${sources.join('\n')}`;
    }
    if (output.task?.task_id) {
        return `Status: ${status}\nCreated task: ${output.task.title || output.task.task_id} (${output.task.task_id})`;
    }
    if (output.reminder?.reminder_id) {
        return `Status: ${status}\nCreated reminder: ${output.reminder.remind_at || output.reminder.reminder_id} (${output.reminder.reminder_id})`;
    }
    if (output.job?.job_id) {
        const report = output.job.report_markdown ? `\nReport preview:\n${truncateForToolInput(output.job.report_markdown, 1800)}` : '';
        return `Status: ${status}\nDeep research job: ${output.job.job_id}\nJob status: ${output.job.status || '-'}${report}`;
    }
    const serialized = JSON.stringify(output || result, null, 2);
    return `Status: ${status}\n${truncateForToolInput(serialized, 2000)}`;
}

async function runComposerFeatureTools(message, activeActions) {
    const results = [];
    for (const action of activeActions) {
        if (!isComposerFeatureAvailable(action)) {
            results.push({
                action,
                label: COMPOSER_FEATURE_LABELS[action],
                ok: false,
                summary: 'Tool is not visible from backend for this user/runtime.',
            });
            continue;
        }
        try {
            const result = await executeComposerTool(action, message);
            results.push({
                action,
                label: COMPOSER_FEATURE_LABELS[action],
                ok: Boolean(result?.ok),
                status: result?.status || 'unknown',
                summary: summarizeComposerToolResult(result),
            });
        } catch (error) {
            results.push({
                action,
                label: COMPOSER_FEATURE_LABELS[action],
                ok: false,
                status: 'error',
                summary: error?.message || String(error),
            });
        }
    }
    const context = results.map((item) => (
        `## ${item.label}\nStatus: ${item.status || (item.ok ? 'success' : 'error')}\n${item.summary || ''}`
    )).join('\n\n');
    return { results, context };
}

// ============================================
// DOM Elements
// ============================================
const elements = {
    chatContainer: document.getElementById('chatContainer'),
    messageInput: document.getElementById('messageInput'),
    sendBtn: document.getElementById('sendBtn'),
    uploadBtn: document.getElementById('uploadBtn'),
    composerActionMenu: document.getElementById('composerActionMenu'),
    welcomeComposerActionMenu: document.getElementById('welcomeComposerActionMenu'),
    fileInput: document.getElementById('fileInput'),
    filePreview: document.getElementById('filePreview'),
    dropOverlay: document.getElementById('dropOverlay'),
    sidebar: document.getElementById('sidebar'),
    mainContent: document.getElementById('mainContent'),
    openSidebar: document.getElementById('openSidebar'),
    closeSidebar: document.getElementById('closeSidebar'),
    minimizeSidebar: document.getElementById('minimizeSidebar'),
    scrollLoader: document.getElementById('scrollLoader'),
    // System Status Modal
    systemStatusModal: document.getElementById('systemStatusModal'),
    systemStatusBackdrop: document.getElementById('systemStatusBackdrop'),
    closeSystemStatus: document.getElementById('closeSystemStatus'),
    systemStatusContent: document.getElementById('systemStatusContent'),
    // Settings Modal
    settingsModal: document.getElementById('settingsModal'),
    settingsBackdrop: document.getElementById('settingsBackdrop'),
    closeSettings: document.getElementById('closeSettings'),
    modelSelect: document.getElementById('modelSelect'),
    composerModelSelect: document.getElementById('composerModelSelect'),
    welcomeModelSelect: document.getElementById('welcomeModelSelect'),
    temperatureSlider: document.getElementById('temperatureSlider'),
    temperatureValue: document.getElementById('temperatureValue'),
    clearHistoryBtn: document.getElementById('clearHistoryBtn'),
    personaAdminRefreshBtn: document.getElementById('personaAdminRefreshBtn'),
    personaAdminStats: document.getElementById('personaAdminStats'),
    personaAdminPreviewBtn: document.getElementById('personaAdminPreviewBtn'),
    personaAdminApplyBtn: document.getElementById('personaAdminApplyBtn'),
    personaAdminPreview: document.getElementById('personaAdminPreview'),
    personaOverrideRowIds: document.getElementById('personaOverrideRowIds'),
    personaOverrideSelect: document.getElementById('personaOverrideSelect'),
    personaOverrideApplyBtn: document.getElementById('personaOverrideApplyBtn'),
    personaBackupSelect: document.getElementById('personaBackupSelect'),
    personaRestoreBtn: document.getElementById('personaRestoreBtn'),
    // Persona Toggle
    personaToggle: document.getElementById('personaToggle'),
    personaDropdown: document.getElementById('personaDropdown'),
    currentPersonaLabel: document.getElementById('currentPersonaLabel'),
    applyPersonaBtn: document.getElementById('applyPersona'),
    // Navigation
    navChat: document.getElementById('navChat'),
    navAdminSettings: document.getElementById('navAdminSettings'),
    navSystemStatus: document.getElementById('navSystemStatus'),
    navSettings: document.getElementById('navSettings'),
    navFiles: document.getElementById('navFiles'),
    // Files Modal
    filesModal: null,
    filesContent: null,
    // User Info & Logout
    userInfo: document.getElementById('userInfo'),
    logoutBtn: document.getElementById('logoutBtn'),
    // User Account Dropdown & Modals
    userDropdownToggle: document.getElementById('userDropdownToggle'),
    userDropdownMenu: document.getElementById('userDropdownMenu'),
    openChangePasswordModal: document.getElementById('openChangePasswordModal'),
    changePasswordModal: document.getElementById('changePasswordModal'),
    changePasswordForm: document.getElementById('changePasswordForm'),
    passwordBackdrop: document.getElementById('passwordBackdrop'),
    openPersonaModal: document.getElementById('openPersonaModal'),
    personaModal: document.getElementById('personaModal'),
    personaForm: document.getElementById('personaForm'),
    personaBackdrop: document.getElementById('personaBackdrop'),
    customPersonaInput: document.getElementById('customPersonaInput'),
    clearPersonaHistoryBtn: document.getElementById('clearPersonaHistoryBtn'),
    sidebarOpenChangePassword: document.getElementById('sidebarOpenChangePassword'),
    sidebarOpenPersona: document.getElementById('sidebarOpenPersona'),
    // File Preview Modal
    filePreviewModal: document.getElementById('filePreviewModal'),
    filePreviewBackdrop: document.getElementById('filePreviewBackdrop'),
    filePreviewTitle: document.getElementById('filePreviewTitle'),
    filePreviewIcon: document.getElementById('filePreviewIcon'),
    filePreviewBody: document.getElementById('filePreviewBody'),
    filePreviewLoader: document.getElementById('filePreviewLoader'),
    scrollToBottomBtn: document.getElementById('scrollToBottomBtn'),
    // Search Modal
    openSearchBtn: document.getElementById('openSearchBtn'),
    searchModal: document.getElementById('searchModal'),
    searchBackdrop: document.getElementById('searchBackdrop'),
    searchInput: document.getElementById('searchInput'),
    searchResults: document.getElementById('searchResults'),
    closeSearchModal: document.getElementById('closeSearchModal'),
    normalModeBtn: document.getElementById('normalModeBtn'),
    playgroundModeBtn: document.getElementById('playgroundModeBtn'),
    playgroundPanel: document.getElementById('playgroundPanel'),
    playgroundHealthBtn: document.getElementById('playgroundHealthBtn'),
    playgroundProvidersBtn: document.getElementById('playgroundProvidersBtn'),
    playgroundCreateSessionBtn: document.getElementById('playgroundCreateSessionBtn'),
    playgroundReconnectLatestBtn: document.getElementById('playgroundReconnectLatestBtn'),
    playgroundUseCustomSessionBtn: document.getElementById('playgroundUseCustomSessionBtn'),
    playgroundForensicViewSelect: document.getElementById('playgroundForensicViewSelect'),
    playgroundWorkflowModeSelect: document.getElementById('playgroundWorkflowModeSelect'),
    playgroundLoadForensicViewBtn: document.getElementById('playgroundLoadForensicViewBtn'),
    playgroundIntegrityOverviewBtn: document.getElementById('playgroundIntegrityOverviewBtn'),
    playgroundIntegrityOverview: document.getElementById('playgroundIntegrityOverview'),
    playgroundVerifySnapshotBtn: document.getElementById('playgroundVerifySnapshotBtn'),
    playgroundExportBundleBtn: document.getElementById('playgroundExportBundleBtn'),
    playgroundLineageBtn: document.getElementById('playgroundLineageBtn'),
    playgroundExecuteBtn: document.getElementById('playgroundExecuteBtn'),
    playgroundListTracesBtn: document.getElementById('playgroundListTracesBtn'),
    playgroundExecuteBtnLabel: document.getElementById('playgroundExecuteBtnLabel'),
    playgroundSessionMode: document.getElementById('playgroundSessionMode'),
    playgroundCustomSessionId: document.getElementById('playgroundCustomSessionId'),
    playgroundProviderChecklist: document.getElementById('playgroundProviderChecklist'),
    playgroundPromptInput: document.getElementById('playgroundPromptInput'),
    playgroundSessionId: document.getElementById('playgroundSessionId'),
    playgroundOutput: document.getElementById('playgroundOutput'),
    playgroundCopyOutputBtn: document.getElementById('playgroundCopyOutputBtn'),
    playgroundDownloadOutputBtn: document.getElementById('playgroundDownloadOutputBtn'),
    playgroundHistoryList: document.getElementById('playgroundHistoryList'),
    playgroundHistoryDetail: document.getElementById('playgroundHistoryDetail'),
    playgroundHistoryMeta: document.getElementById('playgroundHistoryMeta'),
    playgroundHistoryExecutions: document.getElementById('playgroundHistoryExecutions'),
    playgroundDownloadSessionArtifactBtn: document.getElementById('playgroundDownloadSessionArtifactBtn'),
    playgroundArtifactDrawer: document.getElementById('playgroundArtifactDrawer'),
    playgroundArtifactDrawerBackdrop: document.getElementById('playgroundArtifactDrawerBackdrop'),
    playgroundArtifactDrawerClose: document.getElementById('playgroundArtifactDrawerClose'),
    playgroundArtifactAcquisition: document.getElementById('playgroundArtifactAcquisition'),
    playgroundArtifactIntegrity: document.getElementById('playgroundArtifactIntegrity'),
    playgroundArtifactTransformation: document.getElementById('playgroundArtifactTransformation'),
    playgroundArtifactProvenance: document.getElementById('playgroundArtifactProvenance'),
    exportModal: document.getElementById('exportModal'),
    exportBackdrop: document.getElementById('exportBackdrop'),
    closeExportModal: document.getElementById('closeExportModal'),
    exportTargetLabel: document.getElementById('exportTargetLabel'),
    exportFormatSelect: document.getElementById('exportFormatSelect'),
    exportSubmitBtn: document.getElementById('exportSubmitBtn'),
    exportStatus: document.getElementById('exportStatus'),
    exportDownloadLink: document.getElementById('exportDownloadLink'),
    exportStatusContainer: document.getElementById('export-status-container'),
    // Chat Sessions & Persona Accordion
    chatDrawer: document.getElementById('chatDrawer'),
    chatSessionsList: document.getElementById('chatSessionsList'),
    toggleChatDrawer: document.getElementById('toggleChatDrawer'),
    newChatBtn: document.getElementById('newChatBtn'),
    sidebarChatSearch: document.getElementById('sidebarChatSearch'),
    sidebarSessionsMore: document.getElementById('sidebarSessionsMore'),
    headerPersonaLabel: document.getElementById('headerPersonaLabel'),
    headerChatTitle: document.getElementById('headerChatTitle'),
    chatRenameModal: document.getElementById('chatRenameModal'),
    chatRenameInput: document.getElementById('chatRenameInput'),
    chatRenameCancelBtn: document.getElementById('chatRenameCancelBtn'),
    chatRenameSaveBtn: document.getElementById('chatRenameSaveBtn'),
    chatDeleteModal: document.getElementById('chatDeleteModal'),
    chatDeleteMessage: document.getElementById('chatDeleteMessage'),
    chatDeleteCancelBtn: document.getElementById('chatDeleteCancelBtn'),
    chatDeleteConfirmBtn: document.getElementById('chatDeleteConfirmBtn'),
    personaAccordionBtn: document.getElementById('personaAccordionBtn'),
    personaAccordionContent: document.getElementById('personaAccordionContent'),
    personaChevron: document.getElementById('personaChevron'),
    activePersonaName: document.getElementById('activePersonaName'),
    // Welcome Screen
    welcomeScreen: document.getElementById('welcomeScreen'),
    welcomeInput: document.getElementById('welcomeInput'),
    welcomeSendBtn: document.getElementById('welcomeSendBtn'),
    welcomeUploadBtn: document.getElementById('welcomeUploadBtn'),
    mainInputArea: document.getElementById('mainInputArea'),
    backToSidebarBtn: document.getElementById('backToSidebarBtn'),
};

// ============================================
// Initialize
// ============================================
/**
 * Returns true when current authenticated user is admin.
 * @returns {boolean}
 */
function isCurrentUserAdmin() {
    return !!currentUserProfile?.is_admin;
}

/**
 * Load current authenticated profile for frontend RBAC guards.
 * @returns {Promise<void>}
 */
async function fetchCurrentUserProfile() {
    try {
        const response = await authFetch('/api/me');
        if (!response || !response.ok) return;
        const payload = await response.json();
        const data = payload?.data || payload || {};
        currentUserProfile = {
            username: data.username || currentUserProfile.username,
            is_admin: Boolean(data.is_admin),
        };
    } catch (_) {
        currentUserProfile = {
            username: currentUserProfile.username,
            is_admin: window.KURO_USER_CONTEXT?.role === 'Administrator',
        };
    }
}

/**
 * Hide admin-only navigation links for non-admin users.
 */
function applyAdminVisibilityGuards() {
    if (isCurrentUserAdmin()) return;
    document.querySelectorAll('[data-admin-only="true"]').forEach((node) => {
        node.style.display = 'none';
    });
}

/**
 * Block admin-only navigation attempts and redirect non-admin users.
 */
function setupAdminNavigationGuards() {
    if (isCurrentUserAdmin()) return;
    const guardedLinks = Array.from(document.querySelectorAll('a[href^="/ingestion"]'));
    guardedLinks.forEach((link) => {
        link.addEventListener('click', (event) => {
            event.preventDefault();
            showToast('Akses ditolak: halaman ini hanya untuk Administrator.', 'error');
            window.location.href = '/';
        });
    });
    if (window.location.pathname.startsWith('/ingestion')) {
        showToast('Akses ditolak: halaman ini hanya untuk Administrator.', 'error');
        window.location.href = '/';
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    await fetchCurrentUserProfile();
    applyAdminVisibilityGuards();
    setupAdminNavigationGuards();
    lucide.createIcons();

    marked.setOptions({
        highlight: function (code, lang) {
            if (lang && hljs.getLanguage(lang)) {
                return hljs.highlight(code, { language: lang }).value;
            }
            return hljs.highlightAuto(code).value;
        },
        breaks: true,
        gfm: true,
    });

    loadTheme();
    setupEventListeners();
    updateComposerFeatureIndicators();
    setupAutoResize();
    setupInfiniteScroll();
    renderModelSelectorOptions(MODEL_ALIAS_FALLBACK);
    applyModelAlias(selectedModelAlias);
    await loadComposerModelAliases();
    updateUserInfo();
    kuroRestoreUIMode();
    kuroConnectDashboardWS();
    applyRuntimeMode(runtimeMode);
    await loadComposerToolAvailability();
    const deniedFlag = new URLSearchParams(window.location.search).get('access_denied');
    if (deniedFlag === 'admin') {
        showToast('Akses ditolak: halaman ini hanya untuk Administrator.', 'error');
        const cleanUrl = `${window.location.pathname}${window.location.hash || ''}`;
        window.history.replaceState({}, '', cleanUrl);
    }
    // Show welcome screen on first load
    if (runtimeMode === 'normal') showWelcomeScreen();
});

// ============================================
// Event Listeners
// ============================================
function setupEventListeners() {
    elements.sendBtn.addEventListener('click', () => sendMessage(false));
    elements.messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage(false);
        }
    });
    elements.messageInput.addEventListener('input', () => {
        if (currentChatId) {
            saveDraft(currentChatId, elements.messageInput.value);
        }
    });

    if (elements.welcomeSendBtn) {
        elements.welcomeSendBtn.addEventListener('click', () => sendMessage(true));
        elements.welcomeInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage(true);
            }
        });
        elements.welcomeUploadBtn.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            elements.userDropdownMenu?.classList.add('hidden');
            toggleComposerMenu(elements.welcomeComposerActionMenu || elements.composerActionMenu);
        });
        // Auto resize welcome input
        elements.welcomeInput.addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 200) + 'px';
        });
    }

    if (elements.backToSidebarBtn) {
        elements.backToSidebarBtn.addEventListener('click', () => toggleChatDrawer(false));
    }

    elements.uploadBtn.addEventListener('click', (event) => {
        event.stopPropagation();
        elements.userDropdownMenu?.classList.add('hidden');
        if (elements.composerActionMenu) {
            toggleComposerMenu(elements.composerActionMenu);
        } else {
            elements.fileInput.click();
        }
    });
    [elements.composerActionMenu, elements.welcomeComposerActionMenu].forEach((menuEl) => {
        if (!menuEl) return;
        menuEl.addEventListener('click', (event) => {
            const actionButton = event.target.closest('[data-composer-action]');
            if (!actionButton) return;
            const action = actionButton.dataset.composerAction;
            closeComposerMenus();
            handleComposerAction(action);
        });
    });
    document.addEventListener('click', (event) => {
        const clickedOnMainUpload = elements.uploadBtn?.contains(event.target);
        const clickedOnWelcomeUpload = elements.welcomeUploadBtn?.contains(event.target);
        const clickedOnMainMenu = elements.composerActionMenu?.contains(event.target);
        const clickedOnWelcomeMenu = elements.welcomeComposerActionMenu?.contains(event.target);
        const clickedOnChatMenuTrigger = event.target.closest('[data-chat-session-menu-trigger]');
        const clickedOnChatMenu = event.target.closest('[data-chat-session-menu]');
        if (clickedOnMainUpload || clickedOnWelcomeUpload || clickedOnMainMenu || clickedOnWelcomeMenu ||
            clickedOnChatMenuTrigger || clickedOnChatMenu) {
            return;
        }
        closeComposerMenus();
        closeChatSessionMenus();
    });
    elements.fileInput.addEventListener('change', handleFileSelect);

    [elements.composerModelSelect, elements.welcomeModelSelect].forEach((modelSelectEl) => {
        if (!modelSelectEl) return;
        modelSelectEl.addEventListener('change', (event) => {
            applyModelAlias(event.target.value);
        });
    });

    // Ctrl+V paste support for images and files
    elements.messageInput.addEventListener('paste', handlePaste);

    setupDragAndDrop();

    elements.openSidebar.addEventListener('click', () => {
        elements.sidebar.classList.remove('-translate-x-full');
        document.body.style.overflow = 'hidden';
    });
    elements.closeSidebar.addEventListener('click', closeSidebar);

    // Minimize sidebar toggle (desktop only)
    if (elements.minimizeSidebar) {
        elements.minimizeSidebar.addEventListener('click', toggleSidebarCollapse);
        // Restore saved state
        const savedCollapsed = localStorage.getItem('kuro-sidebar-collapsed');
        if (savedCollapsed === 'true') {
            applySidebarCollapse(true);
        }
    }

    document.addEventListener('click', (e) => {
        if (window.innerWidth < 1024 &&
            !elements.sidebar.contains(e.target) &&
            !elements.openSidebar.contains(e.target)) {
            closeSidebar();
        }
    });

    // System Status Modal
    if (elements.navSystemStatus) {
        elements.navSystemStatus.addEventListener('click', (e) => {
            e.preventDefault();
            if (isCurrentUserAdmin()) {
                openSystemStatus();
                elements.userDropdownMenu?.classList.add('hidden');
            } else {
                showToast('Akses ditolak: halaman ini hanya untuk Administrator.', 'error');
            }
        });
    }
    elements.closeSystemStatus.addEventListener('click', closeSystemStatus);
    elements.systemStatusBackdrop.addEventListener('click', closeSystemStatus);

    // Files Modal
    if (elements.navFiles) {
        elements.navFiles.addEventListener('click', (e) => {
            e.preventDefault();
            openFilesModal();
            elements.userDropdownMenu?.classList.add('hidden');
        });
    }

    if (elements.navAdminSettings) {
        elements.navAdminSettings.addEventListener('click', (e) => {
            e.preventDefault();
            openSettings();
            elements.userDropdownMenu?.classList.add('hidden');
        });
    }

    // Settings Modal
    if (elements.navSettings) {
        elements.navSettings.addEventListener('click', (e) => {
            e.preventDefault();
            openSettings();
            elements.userDropdownMenu?.classList.add('hidden');
        });
    }
    elements.closeSettings.addEventListener('click', closeSettings);
    elements.settingsBackdrop.addEventListener('click', closeSettings);

    elements.temperatureSlider.addEventListener('input', (e) => {
        elements.temperatureValue.textContent = e.target.value;
    });

    // clearHistoryBtn and clearPersonaHistoryBtn removed in V1.0.0
    setupPersonaAdminControls();

    // Persona Accordion & Sessions
    if (elements.personaAccordionBtn) {
        elements.personaAccordionBtn.addEventListener('click', togglePersonaAccordion);

        document.querySelectorAll('.persona-option-v2').forEach(option => {
            option.addEventListener('click', () => {
                const newPersona = option.dataset.persona;
                if (newPersona !== selectedPersona) {
                    selectedPersona = newPersona;
                    localStorage.setItem('kuro_persona', selectedPersona);
                    localStorage.setItem('kuro-persona', selectedPersona); // compatibility
                    // Directly refresh page as requested to apply persona context
                    window.location.href = `/chat?persona=${encodeURIComponent(selectedPersona)}`;
                }
            });
        });
    }

    if (elements.toggleChatDrawer) {
        elements.toggleChatDrawer.addEventListener('click', toggleChatDrawer);
    }

    if (elements.newChatBtn) {
        elements.newChatBtn.addEventListener('click', () => {
            ensureNormalModeForChatNavigation();
            startNewChat();
            if (window.innerWidth < 1024) closeSidebar();
        });
    }
    if (elements.sidebarChatSearch) {
        elements.sidebarChatSearch.addEventListener('input', (event) => {
            if (runtimeMode === 'playground') return;
            sessionSearchQuery = (event.target.value || '').trim().toLowerCase();
            renderChatSessions();
        });
    }
    if (elements.sidebarSessionsMore) {
        elements.sidebarSessionsMore.addEventListener('click', () => {
            ensureNormalModeForChatNavigation();
            loadChatSessions();
        });
    }
    if (elements.chatSessionsList) {
        elements.chatSessionsList.addEventListener('click', handleChatSessionMenuClick, true);
    }
    if (elements.chatRenameCancelBtn) {
        elements.chatRenameCancelBtn.addEventListener('click', closeChatRenameModal);
    }
    if (elements.chatRenameModal) {
        elements.chatRenameModal.addEventListener('click', (event) => {
            if (event.target === elements.chatRenameModal) closeChatRenameModal();
        });
    }
    if (elements.chatRenameSaveBtn) {
        elements.chatRenameSaveBtn.addEventListener('click', submitChatRename);
    }
    if (elements.chatRenameInput) {
        elements.chatRenameInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') submitChatRename();
            if (event.key === 'Escape') closeChatRenameModal();
        });
    }
    if (elements.chatDeleteCancelBtn) {
        elements.chatDeleteCancelBtn.addEventListener('click', closeChatDeleteModal);
    }
    if (elements.chatDeleteModal) {
        elements.chatDeleteModal.addEventListener('click', (event) => {
            if (event.target === elements.chatDeleteModal) closeChatDeleteModal();
        });
    }
    if (elements.chatDeleteConfirmBtn) {
        elements.chatDeleteConfirmBtn.addEventListener('click', submitChatDelete);
    }

    // Load initial data
    loadPersona();
    loadChatSessions();

    // User Dropdown Toggle
    if (elements.userDropdownToggle) {
        elements.userDropdownToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            closeComposerMenus();
            elements.userDropdownMenu.classList.toggle('hidden');
        });

        document.addEventListener('click', (e) => {
            if (!elements.userDropdownMenu.contains(e.target)) {
                elements.userDropdownMenu.classList.add('hidden');
            }
        });
    }

    // Modal Handlers
    if (elements.openChangePasswordModal) {
        elements.openChangePasswordModal.addEventListener('click', () => {
            elements.changePasswordModal.classList.remove('hidden');
            elements.userDropdownMenu.classList.add('hidden');
        });
    }

    if (elements.openPersonaModal) {
        elements.openPersonaModal.addEventListener('click', () => {
            elements.personaModal.classList.remove('hidden');
            elements.userDropdownMenu.classList.add('hidden');
        });
    }

    if (elements.sidebarOpenChangePassword) {
        elements.sidebarOpenChangePassword.addEventListener('click', (e) => {
            e.preventDefault();
            elements.changePasswordModal.classList.remove('hidden');
        });
    }

    if (elements.sidebarOpenPersona) {
        elements.sidebarOpenPersona.addEventListener('click', (e) => {
            e.preventDefault();
            elements.personaModal.classList.remove('hidden');
        });
    }

    // Beta 5: Search Modal Listeners
    if (elements.openSearchBtn) elements.openSearchBtn.addEventListener('click', openSearchModal);
    if (elements.closeSearchModal) elements.closeSearchModal.addEventListener('click', closeSearchModal);
    if (elements.searchBackdrop) elements.searchBackdrop.addEventListener('click', closeSearchModal);
    if (elements.searchInput) {
        elements.searchInput.addEventListener('input', debounce(handleSearch, 300));
        elements.searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeSearchModal();
        });
    }

    if (elements.exportSubmitBtn) {
        elements.exportSubmitBtn.addEventListener('click', submitExportRequest);
    }
    if (elements.closeExportModal) {
        elements.closeExportModal.addEventListener('click', closeExportModal);
    }
    if (elements.exportBackdrop) {
        elements.exportBackdrop.addEventListener('click', closeExportModal);
    }

    // Beta 5: Scroll to Bottom Button
    if (elements.scrollToBottomBtn) {
        elements.scrollToBottomBtn.addEventListener('click', scrollToBottom);
        elements.chatContainer.addEventListener('scroll', () => {
            const isNearBottom = elements.chatContainer.scrollHeight - elements.chatContainer.scrollTop - elements.chatContainer.clientHeight < 200;
            elements.scrollToBottomBtn.classList.toggle('hidden', isNearBottom);
        });
    }

    document.querySelectorAll('.close-modal').forEach(btn => {
        btn.addEventListener('click', () => {
            elements.changePasswordModal?.classList.add('hidden');
            elements.personaModal?.classList.add('hidden');
        });
    });

    [elements.passwordBackdrop, elements.personaBackdrop].forEach(bg => {
        bg?.addEventListener('click', () => {
            elements.changePasswordModal?.classList.add('hidden');
            elements.personaModal?.classList.add('hidden');
        });
    });

    // Form Submissions
    if (elements.changePasswordForm) {
        elements.changePasswordForm.addEventListener('submit', handlePasswordChange);
    }
    if (elements.personaForm) {
        elements.personaForm.addEventListener('submit', handlePersonaUpdate);
    }

    // File Preview Modal
    if (elements.filePreviewBackdrop) {
        elements.filePreviewBackdrop.addEventListener('click', closeFilePreview);
    }
    document.querySelectorAll('.close-file-preview').forEach(btn => {
        btn.addEventListener('click', closeFilePreview);
    });

    if (elements.scrollToBottomBtn) {
        elements.scrollToBottomBtn.addEventListener('click', () => {
            scrollToBottom();
            elements.scrollToBottomBtn.classList.remove('visible');
        });
    }

    if (elements.openSearchBtn) {
        elements.openSearchBtn.addEventListener('click', openSearchModal);
    }
    if (elements.closeSearchModal) {
        elements.closeSearchModal.addEventListener('click', closeSearchModal);
    }
    if (elements.searchBackdrop) {
        elements.searchBackdrop.addEventListener('click', closeSearchModal);
    }
    if (elements.searchInput) {
        elements.searchInput.addEventListener('input', debounce(handleSearch, 300));
    }

    if (elements.normalModeBtn) {
        elements.normalModeBtn.addEventListener('click', () => applyRuntimeMode('normal'));
    }
    if (elements.playgroundModeBtn) {
        elements.playgroundModeBtn.addEventListener('click', () => applyRuntimeMode('playground'));
    }
    if (elements.playgroundHealthBtn) {
        elements.playgroundHealthBtn.addEventListener('click', playgroundHealth);
    }
    if (elements.playgroundProvidersBtn) {
        elements.playgroundProvidersBtn.addEventListener('click', playgroundProviders);
    }
    if (elements.playgroundCreateSessionBtn) {
        elements.playgroundCreateSessionBtn.addEventListener('click', playgroundCreateSession);
    }
    if (elements.playgroundReconnectLatestBtn) {
        elements.playgroundReconnectLatestBtn.addEventListener('click', playgroundReconnectLatestSession);
    }
    if (elements.playgroundUseCustomSessionBtn) {
        elements.playgroundUseCustomSessionBtn.addEventListener('click', playgroundUseCustomSessionId);
    }
    if (elements.playgroundExecuteBtn) {
        elements.playgroundExecuteBtn.addEventListener('click', playgroundExecute);
    }
    if (elements.playgroundListTracesBtn) {
        elements.playgroundListTracesBtn.addEventListener('click', playgroundListTraces);
    }
    if (elements.playgroundLoadForensicViewBtn) {
        elements.playgroundLoadForensicViewBtn.addEventListener('click', playgroundLoadForensicView);
    }
    if (elements.playgroundIntegrityOverviewBtn) {
        elements.playgroundIntegrityOverviewBtn.addEventListener('click', playgroundLoadIntegrityOverview);
    }
    if (elements.playgroundVerifySnapshotBtn) {
        elements.playgroundVerifySnapshotBtn.addEventListener('click', playgroundVerifyLatestSnapshot);
    }
    if (elements.playgroundExportBundleBtn) {
        elements.playgroundExportBundleBtn.addEventListener('click', playgroundExportForensicBundle);
    }
    if (elements.playgroundLineageBtn) {
        elements.playgroundLineageBtn.addEventListener('click', playgroundLoadLineage);
    }
    if (elements.playgroundArtifactDrawerClose) {
        elements.playgroundArtifactDrawerClose.addEventListener('click', closePlaygroundArtifactDrawer);
    }
    if (elements.playgroundArtifactDrawerBackdrop) {
        elements.playgroundArtifactDrawerBackdrop.addEventListener('click', closePlaygroundArtifactDrawer);
    }
    if (elements.playgroundCopyOutputBtn) {
        elements.playgroundCopyOutputBtn.addEventListener('click', copyPlaygroundOutput);
    }
    if (elements.playgroundDownloadOutputBtn) {
        elements.playgroundDownloadOutputBtn.addEventListener('click', downloadPlaygroundOutput);
    }
    if (elements.playgroundDownloadSessionArtifactBtn) {
        elements.playgroundDownloadSessionArtifactBtn.addEventListener('click', downloadSelectedSessionArtifact);
    }
}

function closeSidebar() {
    elements.sidebar.classList.add('-translate-x-full');
    document.body.style.overflow = '';
}

// ============================================
// Chat Session & Persona Accordion Helpers
// ============================================
function togglePersonaAccordion(force) {
    const isExpanded = typeof force === 'boolean' ? !force : elements.personaAccordionContent.classList.contains('opacity-100');

    if (isExpanded) {
        // Collapse
        elements.personaAccordionContent.style.maxHeight = '0px';
        elements.personaAccordionContent.classList.remove('opacity-100');
        elements.personaAccordionContent.classList.add('opacity-0');
        elements.personaChevron.style.transform = 'rotate(0deg)';
    } else {
        // Expand
        elements.personaAccordionContent.style.maxHeight = elements.personaAccordionContent.scrollHeight + 'px';
        elements.personaAccordionContent.classList.remove('opacity-0');
        elements.personaAccordionContent.classList.add('opacity-100');
        elements.personaChevron.style.transform = 'rotate(180deg)';
    }
}

function updatePersonaUI() {
    let personaName = selectedPersona.charAt(0).toUpperCase() + selectedPersona.slice(1);

    document.querySelectorAll('.persona-option-v2').forEach(opt => {
        if (opt.dataset.persona === selectedPersona) {
            opt.classList.add('active');
            const span = opt.querySelector('.font-medium');
            if (span) personaName = span.textContent.trim();
        } else {
            opt.classList.remove('active');
        }
    });

    if (elements.activePersonaName) elements.activePersonaName.textContent = personaName;
    updateConversationHeader();
}

function getActivePersonaDisplayName() {
    return elements.activePersonaName?.textContent?.trim()
        || selectedPersona.charAt(0).toUpperCase() + selectedPersona.slice(1);
}

function updateConversationHeader() {
    if (elements.headerPersonaLabel) {
        elements.headerPersonaLabel.textContent = getActivePersonaDisplayName();
    }
    if (!elements.headerChatTitle) return;

    if (runtimeMode === 'playground') {
        elements.headerChatTitle.textContent = 'Playground Runtime';
        return;
    }

    if (!currentChatId) {
        elements.headerChatTitle.textContent = 'New Chat';
        return;
    }

    const activeSession = chatSessions.find((session) => session.chat_id === currentChatId);
    elements.headerChatTitle.textContent = activeSession?.title || 'Default Chat';
}

function toggleChatDrawer(force) {
    if (!elements.chatDrawer) return;
    const isOpen = typeof force === 'boolean' ? !force : elements.chatDrawer.classList.contains('active');

    if (isOpen) {
        elements.chatDrawer.classList.remove('active', 'translate-x-0');
        elements.chatDrawer.classList.add('-translate-x-full');

        elements.sidebar.classList.remove('lg:-translate-x-full');
        elements.sidebar.classList.add('lg:translate-x-0');
        if (window.innerWidth >= 1024) {
            elements.sidebar.classList.remove('-translate-x-full');
        }
        elements.mainContent.classList.remove('drawer-open');
    } else {
        elements.chatDrawer.classList.add('active', 'translate-x-0');
        elements.chatDrawer.classList.remove('-translate-x-full');

        elements.sidebar.classList.remove('lg:translate-x-0');
        elements.sidebar.classList.add('-translate-x-full', 'lg:-translate-x-full');

        elements.mainContent.classList.add('drawer-open');
        loadChatSessions();
    }
}

/**
 * Render lightweight skeleton rows while sessions are loading.
 */
function renderSessionSkeleton() {
    if (!elements.chatSessionsList) return;
    elements.chatSessionsList.innerHTML = `
        <div class="space-y-2">
            ${Array.from({ length: 6 }).map(() => `
                <div class="skeleton h-10 w-full rounded-xl"></div>
            `).join('')}
        </div>
    `;
}

/**
 * Render chat skeleton while history page is loading.
 */
function renderHistorySkeleton() {
    if (!elements.chatContainer) return;
    elements.chatContainer.innerHTML = `
        <div class="space-y-3 p-3">
            ${Array.from({ length: 6 }).map(() => `
                <div class="skeleton h-16 w-full rounded-2xl"></div>
            `).join('')}
        </div>
    `;
}

/**
 * Show or hide a load-earlier indicator on top history fetch.
 * @param {boolean} isVisible
 */
function setLoadEarlierIndicator(isVisible) {
    if (!elements.scrollLoader) return;
    if (isVisible) {
        elements.scrollLoader.innerHTML = `
            <div class="flex items-center justify-center gap-2 text-xs text-amber-600 dark:text-amber-300">
                <span class="spinner border-amber-500"></span>
                <span>Load earlier messages...</span>
            </div>
        `;
        elements.scrollLoader.classList.add('visible');
        return;
    }
    elements.scrollLoader.innerHTML = '<div class="spinner"></div>';
    elements.scrollLoader.classList.remove('visible');
}

async function loadChatSessions() {
    renderSessionSkeleton();
    try {
        const response = await authFetch(`${CONFIG.API_BASE}/chats?persona=${selectedPersona}`);
        const result = await response.json();
        if (result.status === 'success') {
            chatSessions = result.data;
            updateConversationHeader();
            renderChatSessions();
        }
    } catch (error) {
        console.error('Failed to load sessions:', error);
    }
}

function renderChatSessions() {
    if (!elements.chatSessionsList) return;

    const filteredSessions = chatSessions.filter((session) => {
        if (!sessionSearchQuery) return true;
        const title = (session.title || 'New Chat').toLowerCase();
        return title.includes(sessionSearchQuery);
    });

    if (filteredSessions.length === 0) {
        elements.chatSessionsList.innerHTML = `
            <section>
                <p class="sidebar-section-label px-1 text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-wider">Pinned</p>
                <p class="mt-3 px-1 text-sm text-gray-500 dark:text-gray-400">No pinned chats</p>
            </section>
            <section>
                <p class="sidebar-section-label px-1 text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-wider">Recent</p>
                <p class="mt-3 px-1 text-sm text-gray-500 dark:text-gray-400">${sessionSearchQuery ? 'No matching chats' : `No sessions for ${selectedPersona}`}</p>
            </section>
        `;
        lucide.createIcons();
        return;
    }

    const renderRows = (sessions) => sessions.map(session => `
        <div class="chat-item session-item group relative flex items-center gap-3 px-3 py-2.5 rounded-xl cursor-pointer ${currentChatId === session.chat_id ? 'active' : 'text-gray-600 dark:text-gray-400'}" 
             onclick="selectChatSession('${session.chat_id}')" data-chat-id="${session.chat_id}">
            <i data-lucide="${session.is_pinned ? 'pin' : 'message-circle'}" class="w-4 h-4 flex-shrink-0 ${session.is_pinned ? 'text-emerald-500 fill-emerald-500/20' : ''}"></i>
            <span class="chat-item-name text-sm font-medium truncate flex-1">${escapeHtml(session.title || 'New Chat')}</span>
            <div class="session-menu-wrap" onclick="event.stopPropagation()">
                <button type="button" data-chat-session-menu-trigger
                    class="chat-item-menu-trigger p-1.5 text-gray-500 hover:text-gray-200 transition-colors rounded-md" 
                    aria-haspopup="menu"
                    title="More actions">
                    <i data-lucide="more-vertical" class="w-3.5 h-3.5"></i>
                </button>
                <div data-chat-session-menu class="chat-item-actions session-actions absolute z-20" data-chat-id="${session.chat_id}">
                    <button type="button" data-chat-session-action="pin" data-chat-id="${session.chat_id}" data-chat-pinned="${!!session.is_pinned}" class="session-action-btn justify-start" title="${session.is_pinned ? 'Unpin' : 'Pin'}">
                        <i data-lucide="${session.is_pinned ? 'pin-off' : 'pin'}" class="w-3.5 h-3.5"></i>
                        <span>${session.is_pinned ? 'Unpin' : 'Pin'}</span>
                    </button>
                    <button type="button" data-chat-session-action="rename" data-chat-id="${session.chat_id}" class="session-action-btn justify-start" title="Rename">
                        <i data-lucide="pencil" class="w-3.5 h-3.5"></i>
                        <span>Rename</span>
                    </button>
                    <button type="button" data-chat-session-action="export" data-chat-id="${session.chat_id}" class="session-action-btn justify-start" title="Export">
                        <i data-lucide="download" class="w-3.5 h-3.5"></i>
                        <span>Export</span>
                    </button>
                    <button type="button" data-chat-session-action="delete" data-chat-id="${session.chat_id}" class="session-action-btn session-action-delete justify-start" title="Delete">
                        <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                        <span>Delete</span>
                    </button>
                </div>
            </div>
        </div>
    `).join('');

    const pinned = filteredSessions.filter((session) => session.is_pinned);
    const recent = filteredSessions.filter((session) => !session.is_pinned);
    elements.chatSessionsList.innerHTML = `
        <section>
            <p class="sidebar-section-label px-1 text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-wider">Pinned</p>
            <div class="chat-list mt-3 space-y-2">
                ${pinned.length ? renderRows(pinned) : '<p class="px-1 text-sm text-gray-500 dark:text-gray-400">No pinned chats</p>'}
            </div>
        </section>
        <section>
            <p class="sidebar-section-label px-1 text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-wider">Recent</p>
            <div class="chat-list mt-3 space-y-2">
                ${recent.length ? renderRows(recent) : '<p class="px-1 text-sm text-gray-500 dark:text-gray-400">No recent chats</p>'}
            </div>
        </section>
    `;
    lucide.createIcons();
    bindChatSessionMenuControls();
}

function closeChatSessionMenus() {
    if (elements.chatSessionsList?.contains(document.activeElement)) {
        document.activeElement.blur();
    }
}

function toggleChatSessionMenu(event) {
    event?.stopPropagation();
    event?.preventDefault();
    toggleChatSessionMenuFromTrigger(event?.currentTarget);
}

function toggleChatSessionMenuFromTrigger(trigger) {
    trigger?.focus();
}

function handleChatSessionMenuClick(event) {
    const trigger = event.target.closest('[data-chat-session-menu-trigger]');
    if (trigger && elements.chatSessionsList.contains(trigger)) {
        event.preventDefault();
        event.stopPropagation();
        toggleChatSessionMenuFromTrigger(trigger);
        return;
    }

    const actionButton = event.target.closest('[data-chat-session-action]');
    if (!actionButton || !elements.chatSessionsList.contains(actionButton)) return;

    event.preventDefault();
    event.stopPropagation();
    const chatId = actionButton.dataset.chatId;
    const action = actionButton.dataset.chatSessionAction;
    const wasPinned = actionButton.dataset.chatPinned === 'true';
    closeChatSessionMenus();

    if (action === 'pin') {
        togglePinChatSession(chatId, wasPinned);
    } else if (action === 'rename') {
        renameChatSession(chatId);
    } else if (action === 'export') {
        openExportModal(chatId);
    } else if (action === 'delete') {
        deleteChatSession(chatId);
    }
}

function bindChatSessionMenuControls() {
    if (!elements.chatSessionsList) return;

    elements.chatSessionsList.querySelectorAll('[data-chat-session-menu-trigger]').forEach((trigger) => {
        trigger.onpointerdown = (event) => {
            event.preventDefault();
            event.stopPropagation();
        };
        trigger.onclick = (event) => {
            event.preventDefault();
            event.stopPropagation();
            toggleChatSessionMenuFromTrigger(trigger);
        };
    });

    elements.chatSessionsList.querySelectorAll('[data-chat-session-action]').forEach((actionButton) => {
        actionButton.onpointerdown = (event) => {
            event.stopPropagation();
        };
        actionButton.onclick = (event) => {
            event.preventDefault();
            event.stopPropagation();
            const chatId = actionButton.dataset.chatId;
            const action = actionButton.dataset.chatSessionAction;
            const wasPinned = actionButton.dataset.chatPinned === 'true';
            closeChatSessionMenus();

            if (action === 'pin') {
                togglePinChatSession(chatId, wasPinned);
            } else if (action === 'rename') {
                renameChatSession(chatId);
            } else if (action === 'export') {
                openExportModal(chatId);
            } else if (action === 'delete') {
                deleteChatSession(chatId);
            }
        };
    });
}

window.toggleChatSessionMenu = toggleChatSessionMenu;
window.closeChatSessionMenus = closeChatSessionMenus;

function startNewChat() {
    closeChatSessionMenus();
    ensureNormalModeForChatNavigation();
    if (currentChatId) {
        saveDraft(currentChatId, elements.messageInput.value);
    }
    currentChatId = null;
    updateConversationHeader();
    chatHistory = [];
    chatOffset = 0;
    hasMoreMessages = true;
    elements.chatContainer.innerHTML = '';
    elements.messageInput.value = '';

    elements.chatContainer.classList.add('hidden');
    if (elements.mainInputArea) elements.mainInputArea.classList.add('hidden');
    if (elements.welcomeScreen) {
        elements.welcomeScreen.classList.remove('hidden');
        elements.welcomeInput.value = '';
        setTimeout(() => elements.welcomeInput.focus(), 100);
    }

    renderChatSessions();
    lucide.createIcons();
}

async function selectChatSession(chatId) {
    closeChatSessionMenus();
    ensureNormalModeForChatNavigation();
    if (currentChatId === chatId) return;

    // Save current draft before switching
    if (currentChatId) {
        saveDraft(currentChatId, elements.messageInput.value);
    }
    currentChatId = chatId;
    updateConversationHeader();
    // Restore draft if any
    if (elements.messageInput) {
        elements.messageInput.value = loadDraft(chatId);
        elements.messageInput.dispatchEvent(new Event('input'));
    }
    chatOffset = 0;
    hasMoreMessages = chatHasMoreBySession[chatId] !== false;
    chatHistory = [];

    if (elements.welcomeScreen) elements.welcomeScreen.classList.add('hidden');
    elements.chatContainer.classList.remove('hidden');
    if (elements.mainInputArea) elements.mainInputArea.classList.remove('hidden');

    renderHistorySkeleton();

    renderChatSessions();
    await kuroLoadHistory(true);
}

async function deleteChatSession(chatId) {
    ensureNormalModeForChatNavigation();
    pendingDeleteChatId = chatId;
    const session = chatSessions.find(s => s.chat_id === chatId);
    if (elements.chatDeleteMessage) {
        const title = escapeHtml(session?.title || 'New Chat');
        elements.chatDeleteMessage.innerHTML = `"${title}" akan dihapus permanen.${session?.is_pinned ? ' Unpin chat ini dulu sebelum menghapus.' : ''}`;
    }
    if (elements.chatDeleteModal) {
        elements.chatDeleteModal.classList.remove('hidden');
        elements.chatDeleteModal.classList.add('flex');
        return;
    }
    await submitChatDelete();
}

function closeChatDeleteModal() {
    pendingDeleteChatId = null;
    if (!elements.chatDeleteModal) return;
    elements.chatDeleteModal.classList.add('hidden');
    elements.chatDeleteModal.classList.remove('flex');
}

async function submitChatDelete() {
    const chatId = pendingDeleteChatId;
    if (!chatId) return;

    try {
        const response = await authFetch(`${CONFIG.API_BASE}/chats/${chatId}`, { method: 'DELETE' });
        if (response.ok) {
            saveDraft(chatId, '');
            delete chatOldestMessageIdBySession[chatId];
            delete chatHasMoreBySession[chatId];
            if (currentChatId === chatId) startNewChat();
            loadChatSessions();
        } else if (response.status === 403) {
            showNotification('Cannot delete a pinned session. Unpin it first.', 'error');
        }
    } catch (error) {
        console.error('Delete failed:', error);
    } finally {
        closeChatDeleteModal();
    }
}

async function renameChatSession(chatId) {
    ensureNormalModeForChatNavigation();
    const session = chatSessions.find(s => s.chat_id === chatId);
    pendingRenameChatId = chatId;
    if (elements.chatRenameInput) {
        elements.chatRenameInput.value = session?.title || '';
    }
    if (elements.chatRenameModal) {
        elements.chatRenameModal.classList.remove('hidden');
        elements.chatRenameModal.classList.add('flex');
        setTimeout(() => {
            elements.chatRenameInput?.focus();
            elements.chatRenameInput?.select();
        }, 50);
        return;
    }
    await submitChatRename();
}

function closeChatRenameModal() {
    pendingRenameChatId = null;
    if (!elements.chatRenameModal) return;
    elements.chatRenameModal.classList.add('hidden');
    elements.chatRenameModal.classList.remove('flex');
}

async function submitChatRename() {
    const chatId = pendingRenameChatId;
    if (!chatId) return;
    const session = chatSessions.find(s => s.chat_id === chatId);
    const newTitle = (elements.chatRenameInput?.value || '').trim();
    if (!newTitle || newTitle === session?.title) {
        closeChatRenameModal();
        return;
    }

    try {
        const response = await authFetch(`${CONFIG.API_BASE}/chats/${chatId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: newTitle })
        });
        if (response.ok) {
            if (session) session.title = newTitle;
            updateConversationHeader();
            renderChatSessions();
            loadChatSessions();
        }
    } catch (error) {
        console.error('Rename failed:', error);
    } finally {
        closeChatRenameModal();
    }
}

// ============================================
// Sidebar Collapse Toggle (Desktop)
// ============================================
function toggleSidebarCollapse() {
    const isCollapsed = elements.sidebar.getAttribute('data-collapsed') === 'true';
    applySidebarCollapse(!isCollapsed);
}

function applySidebarCollapse(collapsed) {
    elements.sidebar.setAttribute('data-collapsed', collapsed);
    elements.mainContent.classList.toggle('sidebar-collapsed', collapsed);
    document.body.classList.toggle('sidebar-collapsed-shell', collapsed);
    if (elements.minimizeSidebar) {
        elements.minimizeSidebar.classList.toggle('collapsed', collapsed);
        elements.minimizeSidebar.setAttribute('aria-label', collapsed ? 'Show sidebar' : 'Hide sidebar');
        elements.minimizeSidebar.setAttribute('title', collapsed ? 'Show sidebar' : 'Hide sidebar');
    }
    localStorage.setItem('kuro-sidebar-collapsed', collapsed);

    // Update icon
    const icon = elements.minimizeSidebar?.querySelector('i');
    if (icon) {
        icon.setAttribute('data-lucide', collapsed ? 'panel-left-open' : 'panel-left-close');
        lucide.createIcons();
    }
}

// ============================================
// Auto-resize Textarea
// ============================================
function setupAutoResize() {
    elements.messageInput.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 150) + 'px';
    });
}

// ============================================
// Infinite Scroll Setup
// ============================================
function setupInfiniteScroll() {
    elements.chatContainer.addEventListener('scroll', handleScroll);
}

function handleScroll() {
    if (isLoadingMore || !hasMoreMessages) return;

    // Check if scrolled to top (with small threshold)
    if (elements.chatContainer.scrollTop < 100) {
        loadMoreMessages();
    }

    // Toggle Scroll to Bottom button
    if (elements.scrollToBottomBtn) {
        if (!isNearBottom(200)) {
            elements.scrollToBottomBtn.classList.add('visible');
        } else {
            elements.scrollToBottomBtn.classList.remove('visible');
        }
    }
}

async function kuroLoadHistory(isInitial = false) {
    if (isLoadingMore) return;
    if (isInitial) {
        chatOffset = 0;
        hasMoreMessages = true;
        chatHistory = [];
        elements.chatContainer.innerHTML = '';
        if (currentChatId) {
            chatOldestMessageIdBySession[currentChatId] = null;
            chatHasMoreBySession[currentChatId] = true;
        }
    }
    if (!hasMoreMessages) return;

    isLoadingMore = true;
    setLoadEarlierIndicator(true);

    const previousScrollHeight = elements.chatContainer.scrollHeight;
    const previousScrollTop = elements.chatContainer.scrollTop;

    try {
        if (currentChatId) {
            const beforeId = !isInitial ? chatOldestMessageIdBySession[currentChatId] : null;
            const params = new URLSearchParams({
                limit: String(CONFIG.CHAT_PAGE_SIZE),
            });
            if (beforeId) params.set('before_id', String(beforeId));
            const response = await authFetch(`${CONFIG.API_BASE}/chats/${encodeURIComponent(currentChatId)}/messages?${params.toString()}`);
            const payload = await response.json();
            const page = payload?.data || payload || {};
            const messages = Array.isArray(page.messages) ? page.messages : [];

            if (messages.length > 0) {
                hasMoreMessages = Boolean(page.has_more);
                chatHasMoreBySession[currentChatId] = hasMoreMessages;
                chatOldestMessageIdBySession[currentChatId] = page.oldest_id || messages[0]?.id || null;

                [...messages].reverse().forEach((msg) => {
                    const role = msg.role === 'user' ? 'user' : 'ai';
                    const attachments = Array.isArray(msg.attachments)
                        ? msg.attachments
                        : (typeof msg.attachments === 'string' ? JSON.parse(msg.attachments) : []);
                    prependMessageToChat(role, msg.content, attachments, msg.id, {
                        is_edited: msg.is_edited,
                        is_bookmarked: msg.is_bookmarked,
                        is_regenerated: msg.is_regenerated,
                        export_suggestions: msg.export_suggestions || [],
                        timestamp: msg.timestamp,
                    });
                });

                if (isInitial) {
                    scrollToBottom();
                } else {
                    requestAnimationFrame(() => {
                        const newScrollHeight = elements.chatContainer.scrollHeight;
                        const heightDifference = newScrollHeight - previousScrollHeight;
                        elements.chatContainer.scrollTop = previousScrollTop + heightDifference;
                    });
                }
            } else {
                hasMoreMessages = false;
                chatHasMoreBySession[currentChatId] = false;
                if (isInitial) startNewChat();
            }
        } else {
            let url = `${CONFIG.API_BASE}/history?limit=${CONFIG.CHAT_PAGE_SIZE}&offset=${chatOffset}&platform=web&persona=${encodeURIComponent(selectedPersona)}`;
            const response = await authFetch(url);
            const data = await response.json();
            if (data.status === 'success' && data.history.length > 0) {
                chatOffset += data.history.length;
                hasMoreMessages = data.has_more;
                data.history.forEach((msg) => {
                    const role = msg.role === 'user' ? 'user' : 'ai';
                    const attachments = Array.isArray(msg.attachments) ? msg.attachments : (typeof msg.attachments === 'string' ? JSON.parse(msg.attachments) : []);
                    prependMessageToChat(role, msg.content, attachments, msg.id, {
                        is_edited: msg.is_edited,
                        is_bookmarked: msg.is_bookmarked,
                        is_regenerated: msg.is_regenerated,
                        export_suggestions: msg.export_suggestions || [],
                        timestamp: msg.timestamp,
                    });
                });
                if (isInitial) {
                    scrollToBottom();
                }
            } else {
                hasMoreMessages = false;
            }
        }
    } catch (error) {
        console.error('Failed to load history:', error);
    } finally {
        isLoadingMore = false;
        setLoadEarlierIndicator(false);
    }
}

// Keep loadMoreMessages as alias for scroll handler
async function loadMoreMessages() {
    return kuroLoadHistory(false);
}

// ============================================
// Dark Mode
// ============================================
function loadTheme() {
    localStorage.setItem('kuro-theme', 'dark');
    document.documentElement.classList.add('dark');
}

function syncDarkModeToggleIcons() {
    return;
}

function toggleDarkMode() {
    loadTheme();
}

// ============================================
// Dashboard WebSocket: REFRESH_NOW + UI_COMMAND (Kuro V6.0 Sovereign)
// ============================================
const KURO_UI_MODES = ['HUD_MODE', 'RESEARCH_MODE', 'CINEMA_MODE', 'NORMAL_MODE'];
const KURO_THEME_CLASSES = ['theme-hud', 'theme-research', 'theme-cinema'];
const KURO_SENTINEL_IDLE_MS = 30000; // Client-side watchdog: revert to IDLE
// if backend stops updating.
let _kuroDashboardWS = null;
let _kuroDashboardReconnectTimer = null;
let _kuroCurrentMode = 'NORMAL_MODE';
let _kuroLastStatusSnapshot = null;
let _kuroTickerWatchdog = null;
const WS_RECONNECT = {
    delay: 1000,
    maxDelay: 30000,
    multiplier: 2,
    jitter: () => Math.random() * 500,
    attempts: 0,
};

function kuroApplyUIMode(command, payload) {
    if (!KURO_UI_MODES.includes(command)) return;
    const root = document.documentElement;
    KURO_THEME_CLASSES.forEach((cls) => root.classList.remove(cls));
    if (command === 'HUD_MODE') root.classList.add('theme-hud');
    else if (command === 'RESEARCH_MODE') root.classList.add('theme-research');
    else if (command === 'CINEMA_MODE') root.classList.add('theme-cinema');
    _kuroCurrentMode = command;
    try { localStorage.setItem('kuro-ui-mode', command); } catch (_) { }
    if (payload && payload.server_status) {
        _kuroLastStatusSnapshot = payload.server_status;
        kuroRenderStatusTicker(payload.server_status);
    }
    if (command === 'HUD_MODE') {
        // HUD mode always starts in IDLE posture so master sees "SENTINEL: IDLE"
        // instantly even if no sentinel has fired yet this session.
        kuroRenderSentinelTicker({ status: 'IDLE', source: 'ALL' });
    }
    const banner = document.getElementById('kuroModeBanner');
    if (banner) {
        banner.textContent = command.replace('_MODE', '').toUpperCase();
        banner.classList.toggle('hidden', command === 'NORMAL_MODE');
    }
}

function kuroEnsureTicker() {
    let ticker = document.getElementById('kuroStatusTicker');
    if (!ticker) {
        ticker = document.createElement('div');
        ticker.id = 'kuroStatusTicker';
        ticker.className = 'fixed bottom-4 right-4 max-w-md p-3 rounded-lg text-xs font-mono whitespace-pre-wrap shadow-xl z-50 bg-black/80 text-cyan-200 border border-cyan-700/50 pointer-events-none';
        document.body.appendChild(ticker);
    }
    return ticker;
}

function kuroRenderStatusTicker(snapshot) {
    const ticker = kuroEnsureTicker();
    const txt = [
        snapshot && snapshot.proxmox ? snapshot.proxmox : '(no proxmox data)',
        snapshot && snapshot.host ? `\nHost: CPU ${snapshot.host.cpu}% | RAM ${snapshot.host.ram}% | Disk ${snapshot.host.disk}%` : ''
    ].join('');
    ticker.textContent = txt;
    setTimeout(() => {
        if (ticker && _kuroCurrentMode !== 'RESEARCH_MODE' && _kuroCurrentMode !== 'HUD_MODE') {
            ticker.remove();
        }
    }, 60000);
}

function kuroMarketHudChipLine(it) {
    const id = (it && it.id || '').toString();
    if (it && it.kind === 'equity') {
        const s = it.sentiment || 'FLAT';
        const p = it.last_pct_change != null ? it.last_pct_change.toFixed(2) + '%' : '—';
        return '[' + id + ': ' + s + ' ' + p + ']';
    }
    const prob = it && it.prob != null ? it.prob.toFixed(0) + '%' : '—';
    const tr = (it && it.trend || 'flat').toString();
    const arrow = tr === 'up' ? '↗' : tr === 'down' ? '↘' : '→';
    return '[' + id + ': ' + prob + ' ' + arrow + ']';
}


function kuroRenderSentinelTicker(payload) {
    // HUD-mode sentinel presentation. Outside HUD_MODE we stay silent to
    // avoid clashing with RESEARCH_MODE's server-status dump.
    if (_kuroCurrentMode !== 'HUD_MODE') return;
    const p = payload || {};
    const status = (p.status || 'IDLE').toString().toUpperCase();
    const source = (p.source || 'ALL').toString().toUpperCase();
    const detail = (p.detail || '').toString().slice(0, 120);
    const ticker = kuroEnsureTicker();
    ticker.classList.remove('sentinel-scanning', 'sentinel-alert');
    let line = detail
        ? `SENTINEL ${source}: ${status} — ${detail}`
        : `SENTINEL ${source}: ${status}`;
    if (source === 'MARKET' && p.market_chips && Array.isArray(p.market_chips) && p.market_chips.length) {
        line = p.market_chips.map(kuroMarketHudChipLine).join(' ').slice(0, 220);
    }
    ticker.textContent = line;
    if (status === 'SCANNING') {
        ticker.classList.add('sentinel-scanning');
    } else if (status === 'ALERT') {
        ticker.classList.add('sentinel-alert');
    }
    // Watchdog: if nothing else arrives within 30s, revert to IDLE so a
    // crashed backend never strands "SCANNING…" on the master's screen.
    if (_kuroTickerWatchdog) clearTimeout(_kuroTickerWatchdog);
    if (status !== 'IDLE') {
        _kuroTickerWatchdog = setTimeout(() => {
            kuroRenderSentinelTicker({ status: 'IDLE', source: 'ALL' });
        }, KURO_SENTINEL_IDLE_MS);
    }
}

/**
 * Display transient connection state in the status ticker.
 * @param {string} text
 * @param {'connected'|'reconnecting'} state
 */
function updateConnectionStatus(text, state = 'connected') {
    const ticker = kuroEnsureTicker();
    ticker.classList.remove('ws-reconnecting');
    if (state === 'reconnecting') {
        ticker.classList.add('ws-reconnecting');
    }
    ticker.textContent = text;
}

/**
 * Fetch missed proactive events after WS reconnect when endpoint is available.
 */
async function fetchMissedProactiveEvents() {
    try {
        const response = await authFetch('/api/proactive-events?limit=5');
        if (!response || !response.ok) return;
        const payload = await response.json();
        const events = payload?.data?.events || payload?.events || [];
        if (!Array.isArray(events) || events.length === 0) return;
        const newest = events[0];
        const title = newest?.title || 'Event update';
        updateConnectionStatus(`Realtime synced: ${title}`.slice(0, 200), 'connected');
    } catch (_) {
        // Endpoint is optional; ignore when absent.
    }
}

/**
 * Schedule dashboard WS reconnect with exponential backoff + jitter.
 */
function scheduleDashboardReconnect() {
    if (_kuroDashboardReconnectTimer) return;
    const delay = Math.min(
        WS_RECONNECT.delay * Math.pow(WS_RECONNECT.multiplier, WS_RECONNECT.attempts),
        WS_RECONNECT.maxDelay,
    ) + WS_RECONNECT.jitter();
    WS_RECONNECT.attempts += 1;
    updateConnectionStatus(
        `⟳ Reconnecting in ${Math.max(1, Math.round(delay / 1000))}s... (attempt ${WS_RECONNECT.attempts})`,
        'reconnecting',
    );
    _kuroDashboardReconnectTimer = setTimeout(() => {
        _kuroDashboardReconnectTimer = null;
        kuroConnectDashboardWS();
    }, delay);
}

function kuroConnectDashboardWS() {
    try {
        if (_kuroDashboardWS && (_kuroDashboardWS.readyState === WebSocket.OPEN || _kuroDashboardWS.readyState === WebSocket.CONNECTING)) return;
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        const ws = new WebSocket(`${proto}://${location.host}/ws/dashboard`);
        _kuroDashboardWS = ws;
        ws.addEventListener('open', () => {
            WS_RECONNECT.attempts = 0;
            WS_RECONNECT.delay = 1000;
            updateConnectionStatus('Realtime connected', 'connected');
            fetchMissedProactiveEvents();
        });
        ws.addEventListener('message', (evt) => {
            try {
                const msg = JSON.parse(evt.data);
                if (!msg || typeof msg !== 'object') return;
                if (msg.type !== 'UI_COMMAND' || !msg.command) return;
                const cmd = msg.command;
                const payload = msg.payload || {};
                if (KURO_UI_MODES.includes(cmd)) {
                    kuroApplyUIMode(cmd, payload);
                } else if (cmd === 'STATUS_TICKER') {
                    kuroRenderSentinelTicker(payload);
                } else if (cmd === 'GREETING') {
                    kuroHandleGreeting(payload);
                } else if (cmd === 'chat_title_updated') {
                    const { chat_id, title } = payload;
                    const session = chatSessions.find(s => s.chat_id === chat_id);
                    if (session) {
                        session.title = title;
                        updateConversationHeader();
                        renderChatSessions();
                    }
                }
            } catch (_) { }
        });
        ws.addEventListener('close', () => {
            _kuroDashboardWS = null;
            scheduleDashboardReconnect();
        });
        ws.addEventListener('error', () => {
            try { ws.close(); } catch (_) { }
            scheduleDashboardReconnect();
        });
    } catch (_) { }
}

function kuroHandleGreeting(payload) {
    const text = (payload && payload.text || '').toString().trim();
    if (!text) return;
    // Render a butler-styled system bubble in the chat.
    try {
        if (typeof addMessageToChat === 'function') {
            addMessageToChat('ai', text);
        }
    } catch (_) { }
}

function kuroRestoreUIMode() {
    try {
        const saved = localStorage.getItem('kuro-ui-mode');
        if (saved && KURO_UI_MODES.includes(saved) && saved !== 'NORMAL_MODE') {
            kuroApplyUIMode(saved, {});
        }
    } catch (_) { }
}

window.kuroApplyUIMode = kuroApplyUIMode;
window.kuroRenderSentinelTicker = kuroRenderSentinelTicker;
window.kuroMarketHudChipLine = kuroMarketHudChipLine;
window.kuroConnectDashboardWS = kuroConnectDashboardWS;
window.kuroRestoreUIMode = kuroRestoreUIMode;

// ============================================
// Drag & Drop
// ============================================
function setupDragAndDrop() {
    let dragCounter = 0;

    document.addEventListener('dragenter', (e) => {
        e.preventDefault();
        dragCounter++;
        elements.dropOverlay.classList.remove('hidden');
    });

    document.addEventListener('dragleave', (e) => {
        e.preventDefault();
        dragCounter--;
        if (dragCounter === 0) {
            elements.dropOverlay.classList.add('hidden');
        }
    });

    document.addEventListener('dragover', (e) => {
        e.preventDefault();
    });

    document.addEventListener('drop', (e) => {
        e.preventDefault();
        dragCounter = 0;
        elements.dropOverlay.classList.add('hidden');

        const files = Array.from(e.dataTransfer.files);
        handleFiles(files);
    });
}

// ============================================
// File Handling
// ============================================
function handleFileSelect(e) {
    const files = Array.from(e.target.files);
    handleFiles(files);
}

// ============================================
// Ctrl+V Paste Handler for Images and Files
// ============================================
function handlePaste(e) {
    const items = e.clipboardData?.items;
    if (!items) return;

    const filesToHandle = [];

    for (const item of items) {
        // Handle image files (screenshots, copied images)
        if (item.kind === 'file' && item.type.startsWith('image/')) {
            const file = item.getAsFile();
            if (file) {
                filesToHandle.push(file);
                e.preventDefault(); // Prevent default paste behavior
            }
        }
        // Handle other file types (PDFs, documents, etc.)
        else if (item.kind === 'file') {
            const file = item.getAsFile();
            if (file) {
                filesToHandle.push(file);
                e.preventDefault();
            }
        }
    }

    if (filesToHandle.length > 0) {
        handleFiles(filesToHandle);
        showNotification(`${filesToHandle.length} file(s) pasted from clipboard`, 'success');
    }
}

function handleFiles(files) {
    if (selectedFiles.length + files.length > CONFIG.MAX_FILES) {
        showNotification(`Maximum ${CONFIG.MAX_FILES} files allowed`, 'error');
        return;
    }

    files.forEach(file => {
        if (isValidFileType(file)) {
            selectedFiles.push(file);
        } else {
            showNotification(`File type not allowed: ${file.name}`, 'error');
        }
    });

    updateFilePreview();
}

function isValidFileType(file) {
    for (const [prefix, type] of Object.entries(CONFIG.ALLOWED_TYPES)) {
        if (file.type.startsWith(prefix)) return true;
    }
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    return CONFIG.ALLOWED_EXTENSIONS.includes(ext);
}

function updateFilePreview() {
    elements.filePreview.innerHTML = '';
    elements.filePreview.classList.toggle('hidden', selectedFiles.length === 0);

    selectedFiles.forEach((file, index) => {
        const card = document.createElement('div');
        card.className = 'file-preview-card';

        const icon = getFileIcon(file.type);
        card.innerHTML = `
            <i data-lucide="${icon}" class="w-4 h-4 text-emerald-500"></i>
            <span class="text-gray-600 dark:text-gray-300 truncate max-w-[120px]">${file.name}</span>
            <button onclick="removeFile(${index})" class="text-gray-400 hover:text-red-500 transition-colors">
                <i data-lucide="x" class="w-3 h-3"></i>
            </button>
        `;

        elements.filePreview.appendChild(card);
    });

    lucide.createIcons();
}

function getFileIcon(mimeType) {
    if (mimeType.startsWith('image/')) return 'image';
    if (mimeType.startsWith('video/')) return 'video';
    if (mimeType === 'application/pdf') return 'file-text';
    if (mimeType.startsWith('text/')) return 'file-code';
    return 'file';
}

function removeFile(index) {
    selectedFiles.splice(index, 1);
    updateFilePreview();
}

function showWelcomeScreen() {
    if (runtimeMode === 'playground') return;
    if (elements.welcomeScreen) elements.welcomeScreen.classList.remove('hidden');
    elements.chatContainer.classList.add('hidden');
    if (elements.mainInputArea) elements.mainInputArea.classList.add('hidden');

    // Close sidebar on mobile when starting new chat
    if (window.innerWidth < 1024) {
        closeSidebar();
    }
}

function isPlaygroundAuthorizedUser() {
    return (window.KURO_USER_CONTEXT?.username || '').trim() === 'Pantronux';
}

function ensureNormalModeForChatNavigation() {
    if (runtimeMode === 'playground') {
        applyRuntimeMode('normal');
    }
}

function applyRuntimeMode(mode) {
    const wantsPlayground = mode === 'playground';
    if (wantsPlayground && !isPlaygroundAuthorizedUser()) {
        runtimeMode = 'normal';
        localStorage.setItem('kuro-runtime-mode', runtimeMode);
        openAccessDeniedModal();
        playgroundPrint('Forbidden: Playground access is only for Pantronux.');
    } else {
        runtimeMode = wantsPlayground ? 'playground' : 'normal';
        localStorage.setItem('kuro-runtime-mode', runtimeMode);
    }

    if (elements.normalModeBtn) {
        const active = runtimeMode === 'normal';
        elements.normalModeBtn.classList.toggle('active', active);
        elements.normalModeBtn.classList.toggle('bg-emerald-500', active);
        elements.normalModeBtn.classList.toggle('text-white', active);
        elements.normalModeBtn.classList.toggle('text-gray-600', !active);
        elements.normalModeBtn.classList.toggle('dark:text-gray-200', !active);
        elements.normalModeBtn.classList.toggle('hover:bg-gray-200', !active);
        elements.normalModeBtn.classList.toggle('dark:hover:bg-gray-600', !active);
    }
    if (elements.playgroundModeBtn) {
        const active = runtimeMode === 'playground';
        elements.playgroundModeBtn.classList.toggle('active', active);
        elements.playgroundModeBtn.classList.toggle('bg-emerald-500', active);
        elements.playgroundModeBtn.classList.toggle('text-white', active);
        elements.playgroundModeBtn.classList.toggle('text-gray-600', !active);
        elements.playgroundModeBtn.classList.toggle('dark:text-gray-200', !active);
        elements.playgroundModeBtn.classList.toggle('hover:bg-gray-200', !active);
        elements.playgroundModeBtn.classList.toggle('dark:hover:bg-gray-600', !active);
    }

    document.body.classList.toggle('runtime-mode-playground', runtimeMode === 'playground');

    if (runtimeMode === 'playground') {
        updateConversationHeader();
        if (elements.playgroundPanel) elements.playgroundPanel.classList.remove('hidden');
        if (elements.welcomeScreen) elements.welcomeScreen.classList.add('hidden');
        if (elements.chatContainer) elements.chatContainer.classList.add('hidden');
        if (elements.mainInputArea) elements.mainInputArea.classList.add('hidden');
        playgroundRefreshSessionHistory();
        playgroundPrint({
            mode: 'playground',
            note: 'Playground mode active. Use panel controls to hit /api/playground/*.',
        });
        return;
    }

    if (elements.playgroundPanel) elements.playgroundPanel.classList.add('hidden');
    updateConversationHeader();
    if (currentChatId) {
        if (elements.welcomeScreen) elements.welcomeScreen.classList.add('hidden');
        if (elements.chatContainer) elements.chatContainer.classList.remove('hidden');
        if (elements.mainInputArea) elements.mainInputArea.classList.remove('hidden');
    } else {
        showWelcomeScreen();
    }
}
window.applyRuntimeMode = applyRuntimeMode;

function playgroundPrint(payload) {
    if (!elements.playgroundOutput) return;
    if (typeof payload === 'string') {
        elements.playgroundOutput.textContent = payload;
        return;
    }
    elements.playgroundOutput.textContent = JSON.stringify(payload, null, 2);
}

async function parsePlaygroundJson(response) {
    try {
        return await response.json();
    } catch (_) {
        return null;
    }
}

function resolvePlaygroundSessionId(payload) {
    if (!payload || typeof payload !== 'object') return null;
    if (typeof payload.session_id === 'string' && payload.session_id) return payload.session_id;
    if (payload.data && typeof payload.data === 'object') {
        const nested = payload.data.session_id;
        if (typeof nested === 'string' && nested) return nested;
    }
    return null;
}

function formatPlaygroundError(action, response, payload) {
    const detail = payload && typeof payload === 'object'
        ? (payload.detail || payload.error || JSON.stringify(payload))
        : 'Unknown error';
    return `${action} failed (${response.status} ${response.statusText}): ${detail}`;
}

function setActivePlaygroundSession(sessionId) {
    playgroundSessionId = sessionId || null;
    if (elements.playgroundSessionId) {
        elements.playgroundSessionId.textContent = playgroundSessionId || '-';
    }
}

async function fetchPlaygroundJson(path) {
    const response = await authFetch(path);
    const data = await parsePlaygroundJson(response);
    if (!response.ok) {
        throw new Error(formatPlaygroundError('Playground request', response, data));
    }
    return data;
}

function renderPlaygroundHistoryList(sessions) {
    if (!elements.playgroundHistoryList) return;
    if (!Array.isArray(sessions) || sessions.length === 0) {
        elements.playgroundHistoryList.innerHTML = '<p class="px-3 py-2 text-gray-500 dark:text-gray-400">(no sessions)</p>';
        return;
    }
    const rows = sessions.map((s) => {
        const sid = s.session_id || '';
        const mode = s.mode || 'unknown';
        const created = s.created_at_utc || '-';
        const integrity = (s.session_integrity_status || 'unverified').toUpperCase();
        const active = sid === playgroundSessionId ? 'border-l-2 border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20' : '';
        return `
            <button data-session-id="${sid}" class="playground-history-item w-full text-left px-3 py-2 border-b border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800/70 ${active}">
                <p class="font-medium text-gray-800 dark:text-gray-100 truncate">${sid}</p>
                <p class="text-[11px] text-gray-500 dark:text-gray-400">${mode} • ${created}</p>
                <p class="text-[10px] text-emerald-600 dark:text-emerald-300">Integrity: ${escapeHtml(integrity)}</p>
            </button>
        `;
    }).join('');
    elements.playgroundHistoryList.innerHTML = rows;
    elements.playgroundHistoryList.querySelectorAll('.playground-history-item').forEach((btn) => {
        btn.addEventListener('click', async () => {
            const sid = btn.getAttribute('data-session-id');
            if (!sid) return;
            playgroundHistorySessionId = sid;
            await playgroundLoadSessionHistoryDetail(sid);
        });
    });
}

async function playgroundRefreshSessionHistory() {
    if (!elements.playgroundHistoryList) return;
    try {
        const data = await fetchPlaygroundJson('/api/playground/sessions?limit=20');
        renderPlaygroundHistoryList(data.sessions || []);
    } catch (error) {
        elements.playgroundHistoryList.innerHTML = `<p class="px-3 py-2 text-red-500">${escapeHtml(error.message)}</p>`;
    }
}

function buildExecutionArtifactButtons(sessionId, executionId, trustRow = null) {
    const integrityChip = trustRow
        ? `<span class="px-2 py-0.5 rounded-md bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 text-[10px]">Integrity: ${escapeHtml(trustRow.integrity_status || 'UNVERIFIED')}</span>`
        : '';
    const snapshotChip = trustRow
        ? `<span class="px-2 py-0.5 rounded-md bg-cyan-500/15 text-cyan-700 dark:text-cyan-300 text-[10px]">Snapshot: ${escapeHtml(trustRow.snapshot_state || 'UNVERIFIED')}</span>`
        : '';
    const driftChip = trustRow && trustRow.schema_drift_detected
        ? `<span class="px-2 py-0.5 rounded-md bg-amber-500/15 text-amber-700 dark:text-amber-300 text-[10px]">Schema Drift</span>`
        : '';
    const transformChip = trustRow
        ? `<span class="px-2 py-0.5 rounded-md bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 text-[10px]">Transform: ${escapeHtml(trustRow.transformation_integrity_state || 'UNKNOWN')}</span>`
        : '';
    return `
        <div class="flex flex-wrap gap-1 mt-1">${integrityChip}${snapshotChip}${driftChip}${transformChip}</div>
        <div class="flex items-center gap-2 mt-1">
            <button class="playground-open-integrity-detail px-2 py-1 rounded-lg bg-purple-500/15 hover:bg-purple-500/25 text-purple-700 dark:text-purple-300 text-[11px]"
                data-session-id="${sessionId}" data-execution-id="${executionId}">Trust Detail</button>
            <button class="playground-download-artifact px-2 py-1 rounded-lg bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-700 dark:text-emerald-300 text-[11px]"
                data-session-id="${sessionId}" data-execution-id="${executionId}" data-type="execution_raw">Download Raw JSON</button>
            <button class="playground-download-artifact px-2 py-1 rounded-lg bg-cyan-500/15 hover:bg-cyan-500/25 text-cyan-700 dark:text-cyan-300 text-[11px]"
                data-session-id="${sessionId}" data-execution-id="${executionId}" data-type="execution_trace">Download Trace JSON</button>
        </div>
    `;
}

function installArtifactDownloadHandlers(scope) {
    scope.querySelectorAll('.playground-download-artifact').forEach((btn) => {
        btn.addEventListener('click', async () => {
            const sid = btn.getAttribute('data-session-id');
            const eid = btn.getAttribute('data-execution-id');
            const type = btn.getAttribute('data-type');
            if (!sid || !eid || !type) return;
            await downloadPlaygroundArtifactJson(sid, type, eid, btn);
        });
    });
    scope.querySelectorAll('.playground-open-integrity-detail').forEach((btn) => {
        btn.addEventListener('click', async () => {
            const sid = btn.getAttribute('data-session-id');
            const eid = btn.getAttribute('data-execution-id');
            if (!sid || !eid) return;
            await playgroundOpenIntegrityDetail(sid, eid);
        });
    });
}

async function playgroundLoadSessionHistoryDetail(sessionId) {
    if (!elements.playgroundHistoryDetail || !elements.playgroundHistoryMeta || !elements.playgroundHistoryExecutions) return;
    elements.playgroundHistoryDetail.classList.remove('hidden');
    elements.playgroundHistoryMeta.innerHTML = '<p class="text-gray-500 dark:text-gray-400">Loading history...</p>';
    elements.playgroundHistoryExecutions.innerHTML = '';
    try {
        const data = await fetchPlaygroundJson(`/api/playground/sessions/${encodeURIComponent(sessionId)}/history`);
        const session = data.session || {};
        const executions = Array.isArray(data.executions) ? data.executions : [];
        const integrityRows = Array.isArray(data.execution_integrity_rows) ? data.execution_integrity_rows : [];
        const trustByExecution = new Map(integrityRows.map((row) => [row.execution_id, row]));
        elements.playgroundHistoryMeta.innerHTML = `
            <p><span class="font-medium">Session:</span> ${escapeHtml(session.session_id || '-')}</p>
            <p><span class="font-medium">Mode:</span> ${escapeHtml(session.mode || '-')} • <span class="font-medium">Status:</span> ${escapeHtml(session.status || '-')}</p>
            <p><span class="font-medium">Created:</span> ${escapeHtml(session.created_at_utc || '-')}</p>
            <p><span class="font-medium">Traces:</span> ${escapeHtml(String((data.traces_summary || {}).count || 0))} • <span class="font-medium">Reports:</span> ${escapeHtml(String((data.reports || []).length || 0))}</p>
            <p><span class="font-medium">Session Integrity:</span> ${escapeHtml(session.session_integrity_status || 'unverified')}</p>
        `;
        if (elements.playgroundIntegrityOverview) {
            const overview = data.integrity_overview || {};
            const metrics = overview.metrics || {};
            const alerts = Array.isArray(overview.alerts) ? overview.alerts : [];
            const alertText = alerts.length > 0
                ? alerts.map((a) => `${a.severity}: ${a.message}`).join(' | ')
                : 'No active integrity alerts.';
            elements.playgroundIntegrityOverview.innerHTML = `
                <p class="font-semibold text-gray-800 dark:text-gray-100">Forensic Integrity Overview</p>
                <p>verified artifacts: ${escapeHtml(String(metrics.verified_artifacts || 0))}</p>
                <p>integrity failures: ${escapeHtml(String(metrics.integrity_failures || 0))}</p>
                <p>schema drift events: ${escapeHtml(String(metrics.schema_drift_events || 0))}</p>
                <p>snapshot mismatches: ${escapeHtml(String(metrics.snapshot_mismatches || 0))}</p>
                <p class="text-[11px] text-amber-600 dark:text-amber-300">${escapeHtml(alertText)}</p>
            `;
        }
        if (executions.length === 0) {
            elements.playgroundHistoryExecutions.innerHTML = '<p class="text-gray-500 dark:text-gray-400">No executions yet.</p>';
        } else {
            elements.playgroundHistoryExecutions.innerHTML = executions.map((row) => `
                <div class="rounded-lg border border-gray-200 dark:border-gray-700 p-2">
                    <p class="font-medium text-gray-800 dark:text-gray-100">${escapeHtml(row.execution_id || '-')}</p>
                    <p class="text-gray-600 dark:text-gray-300">${escapeHtml(row.provider_id || '-')} • ${escapeHtml(row.model_id || '-')}</p>
                    <p class="text-gray-500 dark:text-gray-400 text-[11px]">${escapeHtml(row.created_at_utc || '-')} • latency: ${escapeHtml(String(row.latency_ms || '-'))} ms</p>
                    ${buildExecutionArtifactButtons(sessionId, row.execution_id || '', trustByExecution.get(row.execution_id || ''))}
                </div>
            `).join('');
            installArtifactDownloadHandlers(elements.playgroundHistoryExecutions);
        }
    } catch (error) {
        elements.playgroundHistoryMeta.innerHTML = `<p class="text-red-500">${escapeHtml(error.message)}</p>`;
    }
}

async function downloadPlaygroundArtifactJson(sessionId, type, executionId = null, button = null) {
    const q = new URLSearchParams({ type });
    if (executionId) q.set('execution_id', executionId);
    const url = `/api/playground/sessions/${encodeURIComponent(sessionId)}/artifacts/json?${q.toString()}`;
    const originalText = button ? button.textContent : null;
    if (button) button.textContent = 'Downloading...';
    try {
        const response = await authFetch(url);
        if (!response.ok) {
            const payload = await parsePlaygroundJson(response);
            throw new Error(formatPlaygroundError('Artifact download', response, payload));
        }
        const blob = await response.blob();
        const header = response.headers.get('content-disposition') || '';
        const m = header.match(/filename=\"?([^\";]+)\"?/i);
        const filename = m ? m[1] : `playground-${type}.json`;
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(link.href);
    } catch (error) {
        playgroundPrint(`Artifact download failed: ${error.message}`);
    } finally {
        if (button && originalText) button.textContent = originalText;
    }
}

async function downloadSelectedSessionArtifact() {
    const sid = playgroundHistorySessionId || playgroundSessionId;
    if (!sid) {
        playgroundPrint('No session selected for artifact download.');
        return;
    }
    await downloadPlaygroundArtifactJson(sid, 'session', null, elements.playgroundDownloadSessionArtifactBtn);
}

function setPlaygroundExecuteLoading(isLoading) {
    playgroundExecuting = isLoading;
    if (!elements.playgroundExecuteBtn) return;
    elements.playgroundExecuteBtn.disabled = isLoading;
    elements.playgroundExecuteBtn.classList.toggle('opacity-70', isLoading);
    elements.playgroundExecuteBtn.classList.toggle('cursor-not-allowed', isLoading);
    if (elements.playgroundExecuteBtnLabel) {
        elements.playgroundExecuteBtnLabel.textContent = isLoading ? 'Executing...' : 'Execute';
    } else {
        elements.playgroundExecuteBtn.textContent = isLoading ? 'Executing...' : 'Execute';
    }
}

function getPlaygroundOutputText() {
    return (elements.playgroundOutput?.textContent || '').trim();
}

function flashPlaygroundAction(button, text, fallbackText) {
    if (!button) return;
    const original = button.textContent || fallbackText;
    button.textContent = text;
    setTimeout(() => {
        button.textContent = original || fallbackText;
    }, 1200);
}

async function copyPlaygroundOutput() {
    const text = getPlaygroundOutputText();
    if (!text || text === '(no output)') {
        flashPlaygroundAction(elements.playgroundCopyOutputBtn, 'No output', 'Copy');
        return;
    }
    try {
        await navigator.clipboard.writeText(text);
        flashPlaygroundAction(elements.playgroundCopyOutputBtn, 'Copied', 'Copy');
    } catch (_) {
        flashPlaygroundAction(elements.playgroundCopyOutputBtn, 'Copy failed', 'Copy');
    }
}

function downloadPlaygroundOutput() {
    const text = getPlaygroundOutputText();
    if (!text || text === '(no output)') {
        flashPlaygroundAction(elements.playgroundDownloadOutputBtn, 'No output', 'Download');
        return;
    }
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    const blob = new Blob([text], { type: 'application/json;charset=utf-8' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `playground-output-${stamp}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
    flashPlaygroundAction(elements.playgroundDownloadOutputBtn, 'Downloaded', 'Download');
}

async function playgroundHealth() {
    try {
        const response = await authFetch('/api/playground/health');
        const data = await parsePlaygroundJson(response);
        if (!response.ok) {
            playgroundPrint(formatPlaygroundError('Health check', response, data));
            return;
        }
        playgroundPrint(data);
    } catch (error) {
        playgroundPrint(`Health check failed: ${error.message}`);
    }
}

async function playgroundProviders() {
    try {
        const response = await authFetch('/api/playground/providers');
        const data = await parsePlaygroundJson(response);
        if (!response.ok) {
            playgroundPrint(formatPlaygroundError('Providers check', response, data));
            return;
        }
        playgroundPrint(data);
    } catch (error) {
        playgroundPrint(`Providers check failed: ${error.message}`);
    }
}

async function playgroundCreateSession(customSessionId = null) {
    const mode = elements.playgroundSessionMode?.value || 'research';
    const payload = { mode };
    const sid = (customSessionId || '').trim();
    if (sid) {
        payload.session_id = sid;
    }
    try {
        const response = await authFetch('/api/playground/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await parsePlaygroundJson(response);
        if (!response.ok) {
            playgroundPrint(formatPlaygroundError('Create session', response, data));
            return;
        }
        const sessionId = resolvePlaygroundSessionId(data);
        if (sessionId) {
            setActivePlaygroundSession(sessionId);
            playgroundHistorySessionId = sessionId;
            if (elements.playgroundCustomSessionId && !customSessionId) {
                elements.playgroundCustomSessionId.value = '';
            }
        } else {
            playgroundPrint('Create session succeeded but `session_id` missing in response.');
            return;
        }
        playgroundPrint(data);
        await playgroundRefreshSessionHistory();
        await playgroundLoadSessionHistoryDetail(sessionId);
    } catch (error) {
        playgroundPrint(`Create session failed: ${error.message}`);
    }
}

async function playgroundReconnectLatestSession() {
    try {
        const data = await fetchPlaygroundJson('/api/playground/sessions/latest');
        const sessionId = data.session_id;
        if (!sessionId) {
            playgroundPrint('Latest session payload missing session_id.');
            return;
        }
        setActivePlaygroundSession(sessionId);
        playgroundHistorySessionId = sessionId;
        if (elements.playgroundCustomSessionId) {
            elements.playgroundCustomSessionId.value = sessionId;
        }
        playgroundPrint({ reconnected_latest: data });
        await playgroundRefreshSessionHistory();
        await playgroundLoadSessionHistoryDetail(sessionId);
    } catch (error) {
        playgroundPrint(`Reconnect latest failed: ${error.message}`);
    }
}

async function playgroundUseCustomSessionId() {
    const customId = (elements.playgroundCustomSessionId?.value || '').trim();
    if (!customId) {
        playgroundPrint('Custom Session ID is empty.');
        return;
    }
    await playgroundCreateSession(customId);
}

async function playgroundExecute() {
    if (playgroundExecuting) {
        return;
    }
    const prompt = (elements.playgroundPromptInput?.value || '').trim();
    const selectedProviders = Array.from(
        (elements.playgroundProviderChecklist || document).querySelectorAll('input[type="checkbox"]:checked')
    ).map((el) => el.value);
    if (!playgroundSessionId) {
        playgroundPrint('No active session. Create session first.');
        return;
    }
    if (!prompt) {
        playgroundPrint('Prompt is empty.');
        return;
    }
    if (selectedProviders.length === 0) {
        playgroundPrint('No provider selected. Checklist minimal 1 model.');
        return;
    }
    setPlaygroundExecuteLoading(true);
    try {
        const isComparative = selectedProviders.length > 1;
        const endpoint = isComparative
            ? '/api/playground/comparative-executions'
            : '/api/playground/executions';
        const payload = isComparative
            ? {
                session_id: playgroundSessionId,
                provider_ids: selectedProviders,
                prompt,
            }
            : {
                session_id: playgroundSessionId,
                provider_id: selectedProviders[0],
                prompt,
            };
        const response = await authFetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await parsePlaygroundJson(response);
        if (!response.ok) {
            playgroundPrint(formatPlaygroundError('Execution', response, data));
            return;
        }
        playgroundPrint({
            mode: isComparative ? 'comparative' : 'single',
            selected_providers: selectedProviders,
            response: data,
        });
        await playgroundRefreshSessionHistory();
        playgroundHistorySessionId = playgroundSessionId;
        await playgroundLoadSessionHistoryDetail(playgroundSessionId);
    } catch (error) {
        playgroundPrint(`Execution failed: ${error.message}`);
    } finally {
        setPlaygroundExecuteLoading(false);
    }
}

async function playgroundListTraces() {
    if (!playgroundSessionId) {
        playgroundPrint('No active session. Create session first.');
        return;
    }
    try {
        const response = await authFetch(`/api/playground/sessions/${encodeURIComponent(playgroundSessionId)}/traces`);
        const data = await parsePlaygroundJson(response);
        if (!response.ok) {
            playgroundPrint(formatPlaygroundError('List traces', response, data));
            return;
        }
        playgroundPrint(data);
        await playgroundRefreshSessionHistory();
        playgroundHistorySessionId = playgroundSessionId;
        await playgroundLoadSessionHistoryDetail(playgroundSessionId);
    } catch (error) {
        playgroundPrint(`List traces failed: ${error.message}`);
    }
}

async function playgroundLoadForensicView() {
    const sid = playgroundHistorySessionId || playgroundSessionId;
    if (!sid) {
        playgroundPrint('No active session. Create session first.');
        return;
    }
    const view = (elements.playgroundForensicViewSelect?.value || 'summary').trim();
    const workflowMode = (elements.playgroundWorkflowModeSelect?.value || 'quick').trim();
    try {
        const data = await fetchPlaygroundJson(
            `/api/playground/sessions/${encodeURIComponent(sid)}/forensic-view?view=${encodeURIComponent(view)}&workflow_mode=${encodeURIComponent(workflowMode)}`
        );
        playgroundPrint(data);
    } catch (error) {
        playgroundPrint(`Forensic view failed: ${error.message}`);
    }
}

async function playgroundLoadIntegrityOverview() {
    const sid = playgroundHistorySessionId || playgroundSessionId;
    if (!sid) {
        playgroundPrint('No active session. Create session first.');
        return;
    }
    const workflowMode = (elements.playgroundWorkflowModeSelect?.value || 'quick').trim();
    try {
        const data = await fetchPlaygroundJson(
            `/api/playground/sessions/${encodeURIComponent(sid)}/integrity-overview?workflow_mode=${encodeURIComponent(workflowMode)}`
        );
        if (elements.playgroundIntegrityOverview) {
            const metrics = data.metrics || {};
            const alerts = Array.isArray(data.alerts) ? data.alerts : [];
            const alertText = alerts.length > 0 ? alerts.map((a) => `${a.severity}: ${a.message}`).join(' | ') : 'No active integrity alerts.';
            elements.playgroundIntegrityOverview.innerHTML = `
                <p class="font-semibold text-gray-800 dark:text-gray-100">Forensic Integrity Overview</p>
                <p>verified artifacts: ${escapeHtml(String(metrics.verified_artifacts || 0))}</p>
                <p>integrity failures: ${escapeHtml(String(metrics.integrity_failures || 0))}</p>
                <p>schema drift events: ${escapeHtml(String(metrics.schema_drift_events || 0))}</p>
                <p>orphaned traces: ${escapeHtml(String(metrics.orphaned_traces || 0))}</p>
                <p>snapshot mismatches: ${escapeHtml(String(metrics.snapshot_mismatches || 0))}</p>
                <p>unresolved mappings: ${escapeHtml(String(metrics.unresolved_canonical_mappings || 0))}</p>
                <p>corrupted exports: ${escapeHtml(String(metrics.corrupted_exports || 0))}</p>
                <p class="text-[11px] text-amber-600 dark:text-amber-300">${escapeHtml(alertText)}</p>
            `;
        }
        playgroundPrint({ integrity_overview: data });
    } catch (error) {
        playgroundPrint(`Integrity overview failed: ${error.message}`);
    }
}

async function playgroundVerifyLatestSnapshot() {
    const sid = playgroundHistorySessionId || playgroundSessionId;
    if (!sid) {
        playgroundPrint('No active session. Create session first.');
        return;
    }
    try {
        const history = await fetchPlaygroundJson(`/api/playground/sessions/${encodeURIComponent(sid)}/history`);
        const snapshots = (history.evidence_snapshots || {}).items || [];
        if (!Array.isArray(snapshots) || snapshots.length === 0) {
            playgroundPrint('No snapshot found for this session.');
            return;
        }
        const snapshotId = snapshots[0].snapshot_id;
        const response = await authFetch(`/api/playground/snapshots/${encodeURIComponent(snapshotId)}/verify`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sid }),
        });
        const data = await parsePlaygroundJson(response);
        if (!response.ok) {
            playgroundPrint(formatPlaygroundError('Verify snapshot', response, data));
            return;
        }
        playgroundPrint({ snapshot_verification: data });
        await playgroundLoadSessionHistoryDetail(sid);
    } catch (error) {
        playgroundPrint(`Snapshot verification failed: ${error.message}`);
    }
}

async function playgroundExportForensicBundle() {
    const sid = playgroundHistorySessionId || playgroundSessionId;
    if (!sid) {
        playgroundPrint('No active session. Create session first.');
        return;
    }
    try {
        const response = await authFetch(`/api/playground/sessions/${encodeURIComponent(sid)}/exports/forensic-bundle`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
        const data = await parsePlaygroundJson(response);
        if (!response.ok) {
            playgroundPrint(formatPlaygroundError('Export forensic bundle', response, data));
            return;
        }
        playgroundPrint({ forensic_bundle: data });
    } catch (error) {
        playgroundPrint(`Forensic bundle export failed: ${error.message}`);
    }
}

async function playgroundLoadLineage() {
    const sid = playgroundHistorySessionId || playgroundSessionId;
    if (!sid) {
        playgroundPrint('No active session. Create session first.');
        return;
    }
    try {
        const data = await fetchPlaygroundJson(`/api/playground/sessions/${encodeURIComponent(sid)}/lineage`);
        playgroundPrint({ lineage: data });
    } catch (error) {
        playgroundPrint(`Lineage view failed: ${error.message}`);
    }
}

async function playgroundOpenIntegrityDetail(sessionId, executionId) {
    try {
        const data = await fetchPlaygroundJson(
            `/api/playground/sessions/${encodeURIComponent(sessionId)}/executions/${encodeURIComponent(executionId)}/integrity-detail`
        );
        if (elements.playgroundArtifactAcquisition) {
            elements.playgroundArtifactAcquisition.textContent = JSON.stringify(data.acquisition_metadata || {}, null, 2);
        }
        if (elements.playgroundArtifactIntegrity) {
            elements.playgroundArtifactIntegrity.textContent = JSON.stringify(data.integrity_metadata || {}, null, 2);
        }
        if (elements.playgroundArtifactTransformation) {
            elements.playgroundArtifactTransformation.textContent = JSON.stringify(data.transformation_metadata || {}, null, 2);
        }
        if (elements.playgroundArtifactProvenance) {
            elements.playgroundArtifactProvenance.textContent = JSON.stringify(data.provenance_metadata || {}, null, 2);
        }
        if (elements.playgroundArtifactDrawer) {
            elements.playgroundArtifactDrawer.classList.remove('hidden');
        }
    } catch (error) {
        playgroundPrint(`Integrity detail failed: ${error.message}`);
    }
}

function closePlaygroundArtifactDrawer() {
    if (elements.playgroundArtifactDrawer) {
        elements.playgroundArtifactDrawer.classList.add('hidden');
    }
}
// ============================================
// V5.5 STREAMING: Send message with SSE streaming
// ============================================
async function sendMessage(isFromWelcome = false) {
    const inputElement = isFromWelcome ? elements.welcomeInput : elements.messageInput;
    const sendBtnElement = isFromWelcome ? elements.welcomeSendBtn : elements.sendBtn;
    const message = inputElement.value.trim();

    if (runtimeMode === 'playground') return;
    if (!message && selectedFiles.length === 0) return;
    if (isProcessing) return;

    isProcessing = true;
    if (elements.sendBtn) elements.sendBtn.disabled = true;
    if (elements.welcomeSendBtn) elements.welcomeSendBtn.disabled = true;

    if (isFromWelcome) {
        if (elements.welcomeScreen) elements.welcomeScreen.classList.add('hidden');
        elements.chatContainer.classList.remove('hidden');
        if (elements.mainInputArea) elements.mainInputArea.classList.remove('hidden');
    }

    // Add user message to chat
    addMessageToChat('user', message, selectedFiles);

    // Clear input
    inputElement.value = '';
    inputElement.style.height = 'auto';

    // Prepare files for upload
    const filesToSend = [...selectedFiles];
    selectedFiles = [];
    updateFilePreview();

    // STEP 1: Create ONE empty chat bubble for Kuro and insert into DOM
    const aiMessageDiv = document.createElement('div');
    aiMessageDiv.className = 'msg-row ai flex items-start gap-3 message-enter';
    aiMessageDiv.innerHTML = `
        <div class="msg-avatar w-8 h-8 rounded-full bg-emerald-500 flex items-center justify-center flex-shrink-0 text-white font-bold text-sm shadow-lg shadow-emerald-500/10">K</div>
        <div class="max-w-[85%] lg:max-w-[70%] relative group">
            <div class="msg-bubble chat-bubble-ai px-4 py-3 shadow-sm relative border border-emerald-500/5">
                <div class="typing-indicator" id="thinkingIndicator">
                    <span></span><span></span><span></span>
                </div>
                <div class="markdown-content streaming-content"></div>
            </div>
            <div class="flex items-center justify-between mt-1 px-1">
                <span class="text-[10px] text-gray-400 font-mono tracking-tighter js-message-time">${getCurrentTime()}</span>
            </div>
        </div>
    `;
    elements.chatContainer.appendChild(aiMessageDiv);
    lucide.createIcons();

    // Get reference to the content div inside the bubble
    const streamingContent = aiMessageDiv.querySelector('.streaming-content');
    let botMessage = '';
    let buffer = '';
    let streamStarted = false;
    let pendingRender = '';
    let renderTimer = null;
    let wasPinnedToBottom = true;
    let streamMeta = null;
    let streamHadError = false;
    let sendCompleted = false;

    const flushStreamingRender = () => {
        if (!pendingRender) return;
        botMessage += pendingRender;
        pendingRender = '';
        streamingContent.textContent = botMessage;
        if (wasPinnedToBottom) {
            scrollToBottom();
        }
    };

    // Setup Stop Generating
    const stopBtn = document.getElementById('stopGeneratingBtn');
    const abortController = new AbortController();
    if (stopBtn) {
        elements.sendBtn?.classList.add('hidden');
        stopBtn.classList.remove('hidden');
        stopBtn.onclick = () => {
            abortController.abort();
            stopBtn.classList.add('hidden');
            elements.sendBtn?.classList.remove('hidden');
        };
    }

    try {
        const activeComposerActions = getActiveComposerFeatures();
        let toolContext = '';
        let toolResults = [];
        if (activeComposerActions.length) {
            const activeLabels = activeComposerActions.map((action) => COMPOSER_FEATURE_LABELS[action]).join(', ');
            const indicator = aiMessageDiv.querySelector('#thinkingIndicator');
            if (indicator) indicator.classList.add('hidden');
            streamingContent.textContent = `Running ${activeLabels}...`;
            const toolRun = await runComposerFeatureTools(message || filesToSend.map((file) => file.name).join(', '), activeComposerActions);
            toolContext = toolRun.context;
            toolResults = toolRun.results;
            streamingContent.textContent = '';
            const successful = toolResults.filter((result) => result.ok).length;
            const approvalRequired = toolResults.some((result) => String(result.summary || '').includes('Approval required'));
            if (successful || approvalRequired) {
                showNotification(
                    approvalRequired ? 'Tool Runtime menunggu approval untuk salah satu aksi.' : `Tool Runtime selesai: ${successful}/${toolResults.length}`,
                    approvalRequired ? 'info' : 'success'
                );
            } else if (toolResults.length) {
                showNotification('Tool Runtime belum berhasil. Detail dikirim ke chat untuk recovery.', 'error');
            }
        }

        const formData = new FormData();
        formData.append('message', message);
        formData.append('persona', selectedPersona);
        if (currentChatId) formData.append('chat_id', currentChatId);
        if (selectedModelAlias) formData.append('model_alias', selectedModelAlias);
        if (elements.temperatureSlider?.value) formData.append('temperature', String(elements.temperatureSlider.value));
        formData.append('tools_enabled', String(activeComposerActions.length > 0));
        formData.append('web_search_enabled', String(Boolean(composerFeatureState.web_search)));
        formData.append('deep_research_enabled', String(Boolean(composerFeatureState.deep_research)));
        formData.append('agent_mode_enabled', String(Boolean(composerFeatureState.agent_mode)));
        formData.append('task_mode_enabled', String(Boolean(composerFeatureState.task_mode)));
        formData.append('reminder_mode_enabled', String(Boolean(composerFeatureState.reminder_mode)));
        if (toolContext) formData.append('tool_context', toolContext);
        filesToSend.forEach(file => formData.append('files', file));

        // STEP 2: Fetch the streaming endpoint
        const response = await authFetch(`${CONFIG.API_BASE}/chat/stream`, {
            method: 'POST',
            body: formData,
            credentials: 'include',
            signal: abortController.signal
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        // STEP 3: Get reader and decoder
        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');

        // STEP 4: Start the loop with BUFFER pattern
        // FIX: Properly handle multi-line SSE events (event: chunk\ndata: {...}\n\n)
        // CRITICAL: Only 'chunk' events update the active bubble.
        // 'complete' event is used ONLY for final rendering, NOT to create a new bubble.
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            buffer = buffer.replace(/\r\n/g, '\n');
            const events = buffer.split('\n\n');
            buffer = events.pop(); // Save incomplete event to buffer

            for (const event of events) {
                // Parse SSE event: extract event: and data: lines
                const lines = event.split('\n');
                let eventType = 'chunk'; // Default event type
                const dataParts = [];

                for (const line of lines) {
                    if (line.startsWith('event: ')) {
                        eventType = line.substring(7).trim();
                    } else if (line.startsWith('data: ')) {
                        dataParts.push(line.substring(6));
                    }
                }
                const dataStr = dataParts.join('\n').trim();

                if (!dataStr) continue;
                if (dataStr === '[DONE]') continue;

                try {
                    const data = JSON.parse(dataStr);
                    const piece = data.text != null && data.text !== '' ? data.text : data.chunk;

                    if (eventType === 'chunk' && piece != null && piece !== '') {
                        if (!streamStarted) {
                            streamStarted = true;
                            // Hide thinking indicator
                            const indicator = aiMessageDiv.querySelector('#thinkingIndicator');
                            if (indicator) indicator.classList.add('hidden');
                        }
                        wasPinnedToBottom = isNearBottom();
                        pendingRender += piece;
                        if (!renderTimer) {
                            renderTimer = setTimeout(() => {
                                flushStreamingRender();
                                renderTimer = null;
                            }, 50);
                        }
                    } else if (eventType === 'complete' && (data.response || data?.data?.response)) {
                        if (renderTimer) {
                            clearTimeout(renderTimer);
                            renderTimer = null;
                        }
                        flushStreamingRender();
                        // Complete event: DO NOT create a new bubble.
                        // Only use for final markdown rendering and syntax highlighting.
                        // The bubble already exists from the chunk events above.
                        botMessage = data.response || data?.data?.response; // Use the complete response for consistency
                        streamingContent.innerHTML = marked.parse(botMessage);
                        streamingContent.classList.add('markdown-content');
                        highlightInContainer(streamingContent);
                        streamMeta = data.meta || null;
                        if (data && data.ui_command) {
                            kuroApplyUIMode(data.ui_command, data.payload || {});
                        }
                        if (streamMeta?.ttfb_ms || streamMeta?.total_ms) {
                            const metaInfo = document.createElement('div');
                            metaInfo.className = 'text-[10px] text-gray-400 mt-2';
                            metaInfo.textContent = `TTFB ${streamMeta.ttfb_ms ?? '-'} ms | Total ${streamMeta.total_ms ?? '-'} ms`;
                            streamingContent.appendChild(metaInfo);
                        }
                        if (streamMeta?.export_suggestions?.length) {
                            renderExportSuggestions(streamingContent, streamMeta.export_suggestions);
                        } else if (streamMeta?.export_suggestion) {
                            renderExportSuggestions(streamingContent, [streamMeta.export_suggestion]);
                        }
                        const serverTimestamp = data?.meta?.timestamp || data?.timestamp || data?.data?.timestamp;
                        if (serverTimestamp) {
                            const timeEl = aiMessageDiv.querySelector('.js-message-time');
                            if (timeEl) timeEl.textContent = formatChatTimestamp(serverTimestamp);
                        }
                        if (wasPinnedToBottom) {
                            scrollToBottom();
                        }
                        // Refresh session list to catch title updates
                        loadChatSessions();
                    } else if (eventType === 'error' && data.error) {
                        streamHadError = true;
                        streamingContent.innerHTML = `<span style="color:red">Error: ${escapeHtml(data.error)}</span>`;
                    } else if (eventType === 'meta') {
                        streamMeta = data;
                        if (data && data.chat_id) {
                            currentChatId = data.chat_id;
                            updateConversationHeader();
                            // Re-load sessions to show the new one
                            loadChatSessions();
                        }
                        if (data && data.ui_command) {
                            kuroApplyUIMode(data.ui_command, data.payload || {});
                        }
                    }
                } catch (e) {
                    console.error("JSON Parse Error on event:", dataStr);
                }
            }
        }

        if (renderTimer) {
            clearTimeout(renderTimer);
            renderTimer = null;
        }
        flushStreamingRender();

        // Final render (fallback if complete event wasn't received)
        if (botMessage && !streamHadError) {
            streamingContent.innerHTML = marked.parse(botMessage);
            highlightInContainer(streamingContent);
        }
        if (wasPinnedToBottom) {
            scrollToBottom();
        }

        // V1.0.0: After completion, if this was the first message, refresh sessions to show the new title
        if (!currentChatId || chatHistory.length <= 2) {
            setTimeout(loadChatSessions, 1500); // Wait for background title gen
        }

        // Save AI message to internal history
        chatHistory.push({ role: 'assistant', content: botMessage });
        sendCompleted = !streamHadError;

    } catch (error) {
        console.error('Chat error:', error);
        if (streamingContent) {
            if (botMessage) {
                streamingContent.innerHTML = marked.parse(botMessage) +
                    `<p style="color:#f59e0b;margin-top:8px"><em>⚠️ Connection interrupted, but partial response above is available.</em></p>`;
            } else {
                streamingContent.innerHTML = `<span style="color:red">Connection lost. Please try again.</span>`;
            }
        } else {
            addMessageToChat('ai', '<span style="color:red">Connection lost. Please try again.</span>');
        }
    } finally {
        if (sendCompleted && currentChatId) {
            saveDraft(currentChatId, '');
        }
        if (stopBtn) stopBtn.classList.add('hidden');
        elements.sendBtn?.classList.remove('hidden');
        isProcessing = false;
        if (elements.sendBtn) elements.sendBtn.disabled = false;
        if (elements.welcomeSendBtn) elements.welcomeSendBtn.disabled = false;
        // Fix Bug 2: Reset file input and state
        elements.fileInput.value = '';
        selectedFiles = [];
        updateFilePreview();
    }
}

// V5.5: Scroll to bottom helper for streaming
function scrollToBottom() {
    if (elements.chatContainer) {
        elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
    }
}

function isNearBottom(threshold = 80) {
    if (!elements.chatContainer) return true;
    const remaining = elements.chatContainer.scrollHeight - elements.chatContainer.scrollTop - elements.chatContainer.clientHeight;
    return remaining < threshold;
}

function highlightInContainer(container) {
    if (!container) return;
    container.querySelectorAll('pre code').forEach(block => {
        hljs.highlightElement(block);
    });
}

function addMessageToChat(role, content, files = [], messageId = null, extra = {}) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `msg-row ${role === 'user' ? 'user flex-row-reverse' : 'ai'} flex items-start gap-3 message-enter`;
    if (messageId) {
        messageDiv.setAttribute('data-message-id', messageId);
    }

    // Avatar
    const avatar = role === 'user'
        ? `<div class="msg-avatar user-message-avatar w-8 h-8 rounded-full bg-emerald-500 flex items-center justify-center flex-shrink-0 text-white font-bold text-sm shadow-lg shadow-emerald-500/10">${escapeHtml(getUserInitial())}</div>`
        : `<div class="msg-avatar w-8 h-8 rounded-full bg-emerald-500 flex items-center justify-center flex-shrink-0 text-white font-bold text-sm shadow-lg shadow-emerald-500/10">K</div>`;

    let contentHtml = '';

    if (files.length > 0) {
        files.forEach(file => {
            if (file.type.startsWith('image/')) {
                const url = URL.createObjectURL(file);
                contentHtml += `<img src="${url}" alt="${file.name}" class="chat-image" onclick="window.open(this.src)">`;
            } else {
                const ext = file.name.split('.').pop().toLowerCase();
                contentHtml += `<div class="flex items-center justify-between gap-3 mt-2 p-3 bg-black/5 dark:bg-white/5 border border-gray-200 dark:border-gray-700 rounded-xl">
                    <div class="flex items-center gap-2 overflow-hidden">
                        <i data-lucide="${getIconForExt(ext)}" class="w-4 h-4 text-emerald-500"></i>
                        <span class="text-xs font-medium truncate">${file.name}</span>
                    </div>
                    <div class="flex gap-1">
                        <button onclick="previewFileLocal(this)" class="p-1.5 rounded-lg hover:bg-emerald-500/10 text-emerald-600 transition-colors" title="Preview">
                            <i data-lucide="eye" class="w-3.5 h-3.5"></i>
                        </button>
                    </div>
                </div>`;
            }
        });
    }

    if (content) {
        if (role === 'ai') {
            // Parse markdown and add copy buttons for code blocks and tables
            const parsedContent = marked.parse(content);
            contentHtml += `<div class="markdown-content">${parsedContent}</div>`;
        } else {
            contentHtml += `<p class="whitespace-pre-wrap">${escapeHtml(content)}</p>`;
        }
    }

    const bubbleClass = role === 'user' ? 'chat-bubble-user' : 'chat-bubble-ai';

    // Beta 5: Dynamic Toolbar
    const isBookmarked = !!extra.is_bookmarked;
    const toolbar = `
        <div class="message-toolbar absolute ${role === 'user' ? 'right-full mr-2' : 'left-full ml-2'} top-0 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-all duration-300">
            <button onclick="copyMessageText(this)" class="p-1.5 rounded-lg bg-white/50 dark:bg-gray-800/50 hover:bg-emerald-500/10 text-gray-400 hover:text-emerald-500 border border-gray-100 dark:border-gray-700 backdrop-blur-sm transition-all" title="Copy">
                <i data-lucide="copy" class="w-3.5 h-3.5"></i>
            </button>
            ${role === 'user' ? `
                <button onclick="editMessage('${messageId}')" class="p-1.5 rounded-lg bg-white/50 dark:bg-gray-800/50 hover:bg-emerald-500/10 text-gray-400 hover:text-emerald-500 border border-gray-100 dark:border-gray-700 backdrop-blur-sm transition-all" title="Edit">
                    <i data-lucide="pencil" class="w-3.5 h-3.5"></i>
                </button>
            ` : `
                <button onclick="regenerateMessage('${messageId}')" class="p-1.5 rounded-lg bg-white/50 dark:bg-gray-800/50 hover:bg-emerald-500/10 text-gray-400 hover:text-emerald-500 border border-gray-100 dark:border-gray-700 backdrop-blur-sm transition-all" title="Regenerate">
                    <i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i>
                </button>
                <button onclick="toggleMessageBookmark('${messageId}', this)" class="p-1.5 rounded-lg bg-white/50 dark:bg-gray-800/50 hover:bg-amber-500/10 ${isBookmarked ? 'text-amber-500' : 'text-gray-400 hover:text-amber-500'} border border-gray-100 dark:border-gray-700 backdrop-blur-sm transition-all" title="Bookmark">
                    <i data-lucide="star" class="w-3.5 h-3.5 ${isBookmarked ? 'fill-amber-500' : ''}"></i>
                </button>
            `}
        </div>
    `;

    messageDiv.innerHTML = `
        ${avatar}
        <div class="max-w-[85%] lg:max-w-[70%] relative group">
            <div class="msg-bubble ${bubbleClass} px-4 py-3 shadow-sm relative border ${role === 'ai' ? 'border-emerald-500/5' : 'border-purple-500/5'}">
                ${contentHtml}
            </div>
            ${toolbar}
            <div class="flex items-center ${role === 'user' ? 'justify-end' : 'justify-start'} mt-1 px-1 gap-2">
                ${extra.is_edited ? '<span class="text-[9px] text-gray-400 italic">edited</span>' : ''}
                ${extra.is_regenerated ? '<span class="text-[9px] text-gray-400 italic">regenerated</span>' : ''}
                <span class="text-[10px] text-gray-400 font-mono tracking-tighter">${formatChatTimestamp(extra.timestamp)}</span>
            </div>
        </div>
    `;

    elements.chatContainer.appendChild(messageDiv);
    lucide.createIcons();

    // Add copy buttons to code blocks and tables
    if (role === 'ai') {
        addCodeBlockCopyButtons(messageDiv);
        addTableCopyButtons(messageDiv);
        if (extra.export_suggestions?.length) {
            renderExportSuggestions(
                messageDiv.querySelector('.markdown-content'),
                extra.export_suggestions
            );
        }
    }

    if (!isLoadingMore) scrollToBottom();
}

function prependMessageToChat(role, content, attachments = [], messageId = null, extra = {}) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `msg-row ${role === 'user' ? 'user flex-row-reverse' : 'ai'} flex items-start gap-3 mb-6 group`;
    if (messageId) messageDiv.setAttribute('data-message-id', messageId);

    const avatar = role === 'user'
        ? `<div class="msg-avatar user-message-avatar w-8 h-8 rounded-full bg-emerald-500 flex items-center justify-center flex-shrink-0 text-white font-bold text-sm shadow-lg shadow-emerald-500/10">${escapeHtml(getUserInitial())}</div>`
        : `<div class="msg-avatar w-8 h-8 rounded-full bg-emerald-500 flex items-center justify-center flex-shrink-0 text-white font-bold text-sm shadow-lg shadow-emerald-500/10">K</div>`;

    let contentHtml = '';

    // Handle persistent attachments from history
    if (attachments && attachments.length > 0) {
        attachments.forEach(file => {
            if (file.content_type?.startsWith('image/')) {
                contentHtml += `<img src="${file.stored_path}" alt="${file.original_filename}" class="chat-image rounded-xl mb-2 max-w-sm" onclick="window.open(this.src)">`;
            } else {
                contentHtml += `<div class="flex items-center gap-3 p-3 bg-black/5 dark:bg-white/5 border border-gray-200 dark:border-gray-700 rounded-xl mb-2">
                    <i data-lucide="file" class="w-4 h-4 text-emerald-500"></i>
                    <span class="text-xs font-medium truncate">${file.original_filename}</span>
                </div>`;
            }
        });
    }

    if (content) {
        if (role === 'ai') {
            contentHtml += `<div class="markdown-content">${marked.parse(content)}</div>`;
        } else {
            contentHtml += `<p class="whitespace-pre-wrap">${escapeHtml(content)}</p>`;
        }
    }

    const bubbleClass = role === 'user' ? 'chat-bubble-user' : 'chat-bubble-ai';
    const isBookmarked = !!extra.is_bookmarked;
    const toolbar = `
        <div class="message-toolbar absolute ${role === 'user' ? 'right-full mr-2' : 'left-full ml-2'} top-0 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-all duration-300">
            <button onclick="copyMessageText(this)" class="p-1.5 rounded-lg bg-white/50 dark:bg-gray-800/50 hover:bg-emerald-500/10 text-gray-400 hover:text-emerald-500 border border-gray-100 dark:border-gray-700 backdrop-blur-sm transition-all" title="Copy">
                <i data-lucide="copy" class="w-3.5 h-3.5"></i>
            </button>
            ${role === 'user' ? `
                <button onclick="editMessage('${messageId}')" class="p-1.5 rounded-lg bg-white/50 dark:bg-gray-800/50 hover:bg-emerald-500/10 text-gray-400 hover:text-emerald-500 border border-gray-100 dark:border-gray-700 backdrop-blur-sm transition-all" title="Edit">
                    <i data-lucide="pencil" class="w-3.5 h-3.5"></i>
                </button>
            ` : `
                <button onclick="regenerateMessage('${messageId}')" class="p-1.5 rounded-lg bg-white/50 dark:bg-gray-800/50 hover:bg-emerald-500/10 text-gray-400 hover:text-emerald-500 border border-gray-100 dark:border-gray-700 backdrop-blur-sm transition-all" title="Regenerate">
                    <i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i>
                </button>
                <button onclick="toggleMessageBookmark('${messageId}', this)" class="p-1.5 rounded-lg bg-white/50 dark:bg-gray-800/50 hover:bg-amber-500/10 ${isBookmarked ? 'text-amber-500' : 'text-gray-400 hover:text-amber-500'} border border-gray-100 dark:border-gray-700 backdrop-blur-sm transition-all" title="Bookmark">
                    <i data-lucide="star" class="w-3.5 h-3.5 ${isBookmarked ? 'fill-amber-500' : ''}"></i>
                </button>
            `}
        </div>
    `;

    messageDiv.innerHTML = `
        ${avatar}
        <div class="max-w-[85%] lg:max-w-[70%] relative group">
            <div class="msg-bubble ${bubbleClass} px-4 py-3 shadow-sm relative border ${role === 'ai' ? 'border-emerald-500/5' : 'border-purple-500/5'}">
                ${contentHtml}
            </div>
            ${toolbar}
            <div class="flex items-center ${role === 'user' ? 'justify-end' : 'justify-start'} mt-1 px-1 gap-2">
                ${extra.is_edited ? '<span class="text-[9px] text-gray-400 italic">edited</span>' : ''}
                ${extra.is_regenerated ? '<span class="text-[9px] text-gray-400 italic">regenerated</span>' : ''}
                <span class="text-[10px] text-gray-400 font-mono tracking-tighter">${formatChatTimestamp(extra.timestamp)}</span>
            </div>
        </div>
    `;

    // Insert after the scroll loader
    if (elements.scrollLoader && elements.scrollLoader.nextSibling) {
        elements.chatContainer.insertBefore(messageDiv, elements.scrollLoader.nextSibling);
    } else {
        elements.chatContainer.insertBefore(messageDiv, elements.chatContainer.firstChild);
    }

    lucide.createIcons();
    if (role === 'ai') {
        addCodeBlockCopyButtons(messageDiv);
        addTableCopyButtons(messageDiv);
        if (extra.export_suggestions?.length) {
            renderExportSuggestions(
                messageDiv.querySelector('.markdown-content'),
                extra.export_suggestions
            );
        }
    }
}

function getIconForExt(ext) {
    if (['pdf'].includes(ext)) return 'file-text';
    if (['doc', 'docx'].includes(ext)) return 'file-text';
    if (['xls', 'xlsx'].includes(ext)) return 'table';
    if (['ppt', 'pptx'].includes(ext)) return 'presentation';
    if (['py', 'js', 'html', 'css', 'json', 'yaml', 'yml'].includes(ext)) return 'file-code';
    if (['txt', 'md'].includes(ext)) return 'file-text';
    return 'file';
}

function previewFile(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    const url = `/uploads/${filename}`;

    elements.filePreviewTitle.textContent = filename;
    elements.filePreviewModal.classList.remove('hidden');
    elements.filePreviewBody.innerHTML = '';
    elements.filePreviewLoader.classList.remove('hidden');

    if (ext === 'pdf') {
        const iframe = document.createElement('iframe');
        iframe.src = url;
        iframe.className = 'w-full h-full border-none';
        iframe.onload = () => elements.filePreviewLoader.classList.add('hidden');
        elements.filePreviewBody.appendChild(iframe);
    } else if (['txt', 'md', 'py', 'js', 'json', 'yaml', 'yml', 'log', 'csv'].includes(ext)) {
        fetch(url)
            .then(res => res.text())
            .then(text => {
                const pre = document.createElement('pre');
                pre.className = 'p-6 text-sm font-mono text-gray-800 dark:text-gray-200 h-full overflow-auto whitespace-pre-wrap';
                pre.textContent = text;
                elements.filePreviewBody.appendChild(pre);
                elements.filePreviewLoader.classList.add('hidden');
            })
            .catch(err => {
                elements.filePreviewBody.innerHTML = `<div class="p-8 text-center text-red-500">Failed to load file: ${err.message}</div>`;
                elements.filePreviewLoader.classList.add('hidden');
            });
    } else {
        elements.filePreviewBody.innerHTML = `
            <div class="flex flex-col items-center justify-center h-full p-8 text-center">
                <i data-lucide="eye-off" class="w-16 h-16 text-gray-300 mb-4"></i>
                <h4 class="text-xl font-bold text-gray-800 dark:text-white mb-2">No Preview Available</h4>
                <p class="text-gray-500 mb-6">Preview is not supported for .${ext} files.</p>
                <a href="${url}" download class="px-6 py-3 bg-emerald-500 text-white rounded-xl font-bold hover:bg-emerald-600 transition-all">Download File</a>
            </div>
        `;
        elements.filePreviewLoader.classList.add('hidden');
        lucide.createIcons();
    }
}

function previewFileLocal(btn) {
    const messageDiv = btn.closest('.flex');
    const filename = btn.closest('.rounded-xl').querySelector('span').textContent;

    // Find the file in selectedFiles if it was just added, 
    // or if it's already in the chat, we might need a different approach.
    // Actually, for simplicity, if it's a local file, we can't easily find it again 
    // unless we store the Blobs. 
    // Let's just alert that preview is available after sending/refreshing for now, 
    // OR better: handle it if we have the blob.

    // For now, let's just make it work for images (already works) 
    // and for other files, we'll just say "Please wait for upload to complete".
    showNotification("Preview will be available after the message is processed.", "info");
}

function closeFilePreview() {
    elements.filePreviewModal.classList.add('hidden');
    elements.filePreviewBody.innerHTML = '';
}

// ============================================
// Search Functions
// ============================================
function openSearchModal() {
    elements.searchModal.classList.remove('hidden');
    elements.searchInput.focus();
}

function closeSearchModal() {
    elements.searchModal.classList.add('hidden');
    elements.searchInput.value = '';
    elements.searchResults.innerHTML = `
        <div class="flex flex-col items-center justify-center py-12 text-gray-400">
            <i data-lucide="message-square" class="w-12 h-12 mb-3 opacity-20"></i>
            <p class="text-sm">Type a keyword to search your past conversations</p>
        </div>
    `;
    lucide.createIcons();
}

async function handleSearch() {
    const query = elements.searchInput.value.trim();
    if (!query) {
        elements.searchResults.innerHTML = '';
        return;
    }

    elements.searchResults.innerHTML = '<div class="flex justify-center py-8"><div class="spinner border-emerald-500 border-t-transparent"></div></div>';

    try {
        const response = await authFetch(`${CONFIG.API_BASE}/chat/search?q=${encodeURIComponent(query)}&persona=${selectedPersona}`);
        const data = await response.json();

        if (data.status === 'success' && data.data.results.length > 0) {
            renderSearchResults(data.data.results);
        } else {
            elements.searchResults.innerHTML = `
                <div class="flex flex-col items-center justify-center py-12 text-gray-400">
                    <i data-lucide="search-x" class="w-12 h-12 mb-3 opacity-20"></i>
                    <p class="text-sm">No results found for "${query}"</p>
                </div>
            `;
            lucide.createIcons();
        }
    } catch (error) {
        console.error('Search failed:', error);
        elements.searchResults.innerHTML = '<p class="text-center text-red-500 py-8">Search failed. Please try again.</p>';
    }
}

function renderSearchResults(results) {
    elements.searchResults.innerHTML = '';
    results.forEach(res => {
        const card = document.createElement('div');
        card.className = 'p-4 bg-gray-50 dark:bg-gray-900/40 border border-gray-100 dark:border-gray-700 rounded-2xl hover:border-emerald-500/50 hover:bg-emerald-500/5 transition-all cursor-pointer group';
        card.onclick = () => jumpToMessage(res.id);

        const date = new Date(res.timestamp).toLocaleString();
        const personaLabel = res.persona ? res.persona.charAt(0).toUpperCase() + res.persona.slice(1) : 'Unknown';

        card.innerHTML = `
            <div class="flex items-center justify-between mb-2">
                <span class="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600">${personaLabel}</span>
                <span class="text-[10px] text-gray-400">${date}</span>
            </div>
            <p class="text-sm text-gray-700 dark:text-gray-300 line-clamp-2 group-hover:text-gray-900 dark:group-hover:text-white transition-colors">
                <span class="font-bold text-emerald-500">${res.role === 'user' ? 'You: ' : 'Kuro: '}</span>
                ${escapeHtml(res.content)}
            </p>
        `;
        elements.searchResults.appendChild(card);
    });
}

function jumpToMessage(messageId) {
    // 1. Close modal
    closeSearchModal();

    // 2. Try to find the message in the current DOM
    const target = document.querySelector(`[data-message-id="${messageId}"]`);
    if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        target.classList.add('highlight-pulse');
        setTimeout(() => target.classList.remove('highlight-pulse'), 2000);
    } else {
        // 3. If not in DOM, we'd ideally load a slice of history around it.
        // For now, let's just notify that it's further up in history.
        showNotification("Message is further up in history. Try scrolling up to load more.", "info");
    }
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

window.previewFile = previewFile;
window.closeFilePreview = closeFilePreview;

function showTypingIndicator() {
    const indicator = document.createElement('div');
    indicator.id = 'typingIndicator';
    indicator.className = 'flex items-start gap-3 message-enter';
    indicator.innerHTML = `
        <div class="w-8 h-8 rounded-full bg-emerald-500 flex items-center justify-center flex-shrink-0 text-white font-bold text-sm">K</div>
        <div class="chat-bubble-ai px-4 py-3 shadow-sm">
            <div class="typing-indicator">
                <span></span><span></span><span></span>
            </div>
        </div>
    `;
    elements.chatContainer.appendChild(indicator);
    lucide.createIcons();
    elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
}

function removeTypingIndicator() {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) indicator.remove();
}

// ============================================
// Chat History (Infinite Scroll)
// ============================================
async function loadChatHistory() {
    try {
        renderHistorySkeleton();
        // Reset pagination state
        chatOffset = 0;
        hasMoreMessages = true;
        isLoadingMore = false;

        console.log('[CHAT_HISTORY] Fetching history from backend...');
        const response = await authFetch(
            `${CONFIG.API_BASE}/history?limit=${CONFIG.CHAT_PAGE_SIZE}&offset=0&platform=web&persona=${encodeURIComponent(selectedPersona)}`
        );
        const data = await response.json();
        console.log('[CHAT_HISTORY] Backend response:', data);

        // Clear container but keep scroll loader
        elements.chatContainer.innerHTML = `
            <div class="scroll-loader" id="scrollLoader">
                <div class="spinner"></div>
            </div>
        `;
        elements.scrollLoader = document.getElementById('scrollLoader');

        if (data.status === 'success' && data.history && data.history.length > 0) {
            console.log(`[CHAT_HISTORY] Loaded ${data.history.length} messages from backend`);

            // FIX: Backend already returns data in chronological order (oldest first)
            // via list(reversed(history)) in chat_history.py line 102.
            // DO NOT reverse again - this was causing the double-reverse anomaly.
            const messages = data.history;

            // Render messages in chronological order (oldest at top, newest at bottom)
            messages.forEach(msg => {
                const role = msg.role === 'user' ? 'user' : 'ai';
                const attachments = Array.isArray(msg.attachments) ? msg.attachments : (typeof msg.attachments === 'string' ? JSON.parse(msg.attachments) : []);
                addMessageToChat(role, msg.content, attachments, msg.id, {
                    is_edited: msg.is_edited,
                    is_regenerated: msg.is_regenerated,
                    is_bookmarked: msg.is_bookmarked,
                    export_suggestions: msg.export_suggestions || [],
                    timestamp: msg.timestamp,
                });
            });

            chatOffset = data.history.length;
            hasMoreMessages = data.has_more;

            // FIX: Auto-scroll to bottom after loading history
            // Use setTimeout to ensure all DOM elements are fully rendered
            setTimeout(() => {
                elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
            }, 100);
        } else {
            console.log('[CHAT_HISTORY] No history found, showing welcome message');
            // Show welcome message if no history
            const masterName = window.KURO_USER_CONTEXT?.masterName || 'Master Pantronux';
            addMessageToChat('ai', `Welcome, ${masterName}. I am Kuro, your devoted AI Butler. How may I be of service today?`);
            hasMoreMessages = false;
        }
    } catch (error) {
        console.error('[CHAT_HISTORY] Failed to load chat history:', error);
        elements.chatContainer.innerHTML = `
            <div class="scroll-loader" id="scrollLoader">
                <div class="spinner"></div>
            </div>
        `;
        elements.scrollLoader = document.getElementById('scrollLoader');
        const masterName = window.KURO_USER_CONTEXT?.masterName || 'Master Pantronux';
        addMessageToChat('ai', `Welcome, ${masterName}. I am Kuro, your devoted AI Butler. How may I be of service today?`);
        hasMoreMessages = false;
    }
}

async function clearChatHistory() {
    if (confirm('Are you sure you want to clear ALL chat history? This cannot be undone.')) {
        try {
            await authFetch(`${CONFIG.API_BASE}/history`, { method: 'DELETE' });
            elements.chatContainer.innerHTML = '';
            showNotification('All chat history cleared', 'success');
            closeSettings();
            // Reload chat with welcome message
            loadChatHistory();
        } catch (error) {
            showNotification('Failed to clear history', 'error');
        }
    }
}

async function clearPersonaChatHistory() {
    const persona = selectedPersona;
    if (confirm(`Are you sure you want to clear history for persona: ${persona}? Other persona history will be kept.`)) {
        try {
            await authFetch(`${CONFIG.API_BASE}/history?persona=${encodeURIComponent(persona)}`, { method: 'DELETE' });
            elements.chatContainer.innerHTML = '';
            showNotification(`History for ${persona} cleared`, 'success');
            closeSettings();
            // Reload chat
            loadChatHistory();
        } catch (error) {
            showNotification('Failed to clear persona history', 'error');
        }
    }
}

// ============================================
// System Status
// ============================================
async function openSystemStatus() {
    elements.systemStatusModal.classList.remove('hidden');
    elements.systemStatusModal.classList.add('flex');
    elements.systemStatusContent.innerHTML = '<div class="flex items-center justify-center py-8"><div class="spinner"></div></div>';

    try {
        const [sysResponse, logResponse] = await Promise.all([
            authFetch(`${CONFIG.API_BASE}/system-status`),
            authFetch(`${CONFIG.API_BASE}/log-storage`)
        ]);

        const sysData = await sysResponse.json();
        const logData = await logResponse.json();

        if (sysData.status === 'success') {
            const systemStatus = sysData.data || {};
            const healthReport = typeof systemStatus === 'string'
                ? systemStatus
                : (systemStatus.system_health_report || 'System status unavailable.');
            let logStorageHtml = '';
            let backupHtml = '';
            if (logData.status === 'success' && logData.data) {
                const logInfo = logData.data;
                let breakdownHtml = '';

                if (logInfo.breakdown) {
                    breakdownHtml = '<div class="mt-3 space-y-1">';
                    logInfo.breakdown.forEach((entry) => {
                        breakdownHtml += `
                            <div class="flex justify-between items-start gap-3 text-xs text-blue-700/70 dark:text-blue-300/60">
                                <div>
                                    <div>${entry.name}</div>
                                    <div class="text-[11px] opacity-70">Updated ${entry.modified_at}</div>
                                </div>
                                <span class="font-mono whitespace-nowrap">${entry.size_mb.toFixed(2)} MB</span>
                            </div>
                        `;
                    });
                    breakdownHtml += '</div>';
                }

                logStorageHtml = `
                    <div class="mt-4 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-xl border border-blue-200 dark:border-blue-800">
                        <div class="flex items-center gap-2 mb-2">
                            <i data-lucide="file-text" class="w-4 h-4 text-blue-600 dark:text-blue-400"></i>
                            <h4 class="font-medium text-blue-800 dark:text-blue-300">Log Storage Usage</h4>
                        </div>
                        <div class="grid grid-cols-3 gap-2 text-sm">
                            <div>
                                <p class="text-blue-600 dark:text-blue-400">Total Size</p>
                                <p class="font-medium text-blue-800 dark:text-blue-200">${logInfo.total_size_mb?.toFixed(2) || '0.00'} MB</p>
                            </div>
                            <div>
                                <p class="text-blue-600 dark:text-blue-400">Log Files</p>
                                <p class="font-medium text-blue-800 dark:text-blue-200">${logInfo.log_files || 0}</p>
                            </div>
                            <div>
                                <p class="text-blue-600 dark:text-blue-400">Retention</p>
                                <p class="font-medium text-blue-800 dark:text-blue-200">${logInfo.retention_days || 30} days</p>
                            </div>
                        </div>
                        ${breakdownHtml}
                    </div>
                `;
            }

            backupHtml = renderBackupStatusCard(systemStatus.backup);

            elements.systemStatusContent.innerHTML = `
                <div class="space-y-4">
                    <div class="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 font-mono text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">${healthReport}</div>
                    ${logStorageHtml}
                    ${backupHtml}
                </div>
            `;
            lucide.createIcons();
        } else {
            elements.systemStatusContent.innerHTML = '<p class="text-red-500">Failed to load system status</p>';
        }
    } catch (error) {
        elements.systemStatusContent.innerHTML = `<p class="text-red-500">Error: ${error.message}</p>`;
    }
}

function closeSystemStatus() {
    elements.systemStatusModal.classList.add('hidden');
    elements.systemStatusModal.classList.remove('flex');
}

function renderBackupStatusCard(backup) {
    if (backup === null || backup === undefined) {
        return `
            <div class="p-4 bg-teal-50 dark:bg-teal-900/20 rounded-xl border border-teal-200 dark:border-teal-800">
                <div class="flex items-center justify-between gap-3 mb-2">
                    <div class="flex items-center gap-2">
                        <i data-lucide="database-backup" class="w-4 h-4 text-teal-600 dark:text-teal-400"></i>
                        <h4 class="font-medium text-teal-800 dark:text-teal-300">Backup Status</h4>
                    </div>
                </div>
                <p class="text-sm text-teal-700 dark:text-teal-200">Backup system not yet configured.</p>
            </div>
        `;
    }

    const badge = getBackupStatusBadge(backup.last_backup_status);
    const assets = Array.isArray(backup.assets_covered) ? backup.assets_covered : [];
    const assetItems = assets.length
        ? assets.map((asset) => `
            <div class="font-mono text-[0.75rem] text-gray-500 dark:text-gray-400 break-all">${asset}</div>
        `).join('')
        : '<div class="font-mono text-[0.75rem] text-gray-500 dark:text-gray-400">No assets recorded.</div>';
    const errorHtml = backup.last_backup_status === 'failed' && backup.error_message
        ? `<p class="mt-3 text-xs text-red-600 dark:text-red-400">${escapeHtml(backup.error_message)}</p>`
        : '';

    return `
        <div class="p-4 bg-teal-50 dark:bg-teal-900/20 rounded-xl border border-teal-200 dark:border-teal-800">
            <div class="flex items-center justify-between gap-3 mb-3">
                <div class="flex items-center gap-2">
                    <i data-lucide="database-backup" class="w-4 h-4 text-teal-600 dark:text-teal-400"></i>
                    <h4 class="font-medium text-teal-800 dark:text-teal-300">Backup Status</h4>
                </div>
                <button
                    type="button"
                    onclick="openBackupHistoryDetails()"
                    class="inline-flex items-center gap-1 rounded-lg border border-teal-300/70 dark:border-teal-700 px-2.5 py-1 text-xs font-semibold text-teal-700 dark:text-teal-300 hover:bg-teal-100 dark:hover:bg-teal-900/40 transition-colors"
                    title="Open /api/backup/history details"
                >
                    <i data-lucide="external-link" class="w-3.5 h-3.5"></i>
                    <span>View history</span>
                </button>
            </div>
            <div class="grid grid-cols-3 gap-3 text-sm mb-4">
                <div>
                    <p class="text-teal-600 dark:text-teal-400">Last Backup</p>
                    <p class="font-mono text-teal-900 dark:text-teal-100">${formatBackupTimestamp(backup.last_backup_at)}</p>
                </div>
                <div>
                    <p class="text-teal-600 dark:text-teal-400">Status</p>
                    <p>${badge}</p>
                </div>
                <div>
                    <p class="text-teal-600 dark:text-teal-400">Next Backup</p>
                    <p class="font-mono text-teal-900 dark:text-teal-100">${formatBackupTimestamp(backup.next_backup_at)}</p>
                </div>
            </div>
            <div class="grid grid-cols-3 gap-3 text-sm mb-4">
                <div>
                    <p class="text-teal-600 dark:text-teal-400">Total Backup Size</p>
                    <p class="font-mono text-teal-900 dark:text-teal-100">${formatBackupMegabytes(backup.backup_dir_size_mb)}</p>
                </div>
                <div>
                    <p class="text-teal-600 dark:text-teal-400">Daily Copies</p>
                    <p class="font-mono text-teal-900 dark:text-teal-100">${backup.backup_count_daily ?? 0}</p>
                </div>
                <div>
                    <p class="text-teal-600 dark:text-teal-400">Retention</p>
                    <p class="font-mono text-teal-900 dark:text-teal-100">${backup.retain_days ?? 0} days</p>
                </div>
            </div>
            <div class="mb-4">
                <p class="text-sm text-teal-700 dark:text-teal-200 mb-2">Assets Covered (${assets.length} files):</p>
                <div class="grid grid-cols-2 gap-x-3 gap-y-1">
                    ${assetItems}
                </div>
            </div>
            <div class="flex flex-wrap gap-x-6 gap-y-2 text-sm">
                <p class="text-teal-700 dark:text-teal-200">Last duration: <span class="font-mono text-teal-900 dark:text-teal-100">${formatBackupDuration(backup.duration_seconds)}</span></p>
                <p class="text-teal-700 dark:text-teal-200">Pre-migration snaps: <span class="font-mono text-teal-900 dark:text-teal-100">${backup.backup_count_pre_migration ?? 0}</span></p>
            </div>
            ${errorHtml}
        </div>
    `;
}

function getBackupStatusBadge(status) {
    switch ((status || '').toLowerCase()) {
        case 'success':
            return '<span class="inline-flex items-center rounded-full bg-emerald-100 px-2 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300">✅ Success</span>';
        case 'partial':
            return '<span class="inline-flex items-center rounded-full bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">⚠️ Partial</span>';
        case 'failed':
            return '<span class="inline-flex items-center rounded-full bg-red-100 px-2 py-1 text-xs font-semibold text-red-700 dark:bg-red-900/40 dark:text-red-300">❌ Failed</span>';
        default:
            return '<span class="inline-flex items-center rounded-full bg-gray-100 px-2 py-1 text-xs font-semibold text-gray-700 dark:bg-gray-800 dark:text-gray-300">⚪ Not configured</span>';
    }
}

function formatBackupTimestamp(value) {
    if (!value) return 'N/A';
    const parsed = new Date(String(value).replace(' ', 'T'));
    if (Number.isNaN(parsed.getTime())) return String(value);
    return parsed.toLocaleString('en-GB', {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    });
}

function formatBackupMegabytes(value) {
    const amount = Number(value);
    return Number.isFinite(amount) ? `${amount.toFixed(1)} MB` : '0.0 MB';
}

function formatBackupDuration(value) {
    const seconds = Number(value);
    return Number.isFinite(seconds) ? `${seconds.toFixed(1)}s` : '0.0s';
}

function openBackupHistoryDetails() {
    window.open(`${CONFIG.API_BASE}/backup/history`, '_blank', 'noopener,noreferrer');
}

function escapeHtml(value) {
    return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

// ============================================
// Settings
// ============================================
function openSettings() {
    elements.settingsModal.classList.remove('hidden');
    refreshPersonaAdminStats();
}

function closeSettings() {
    elements.settingsModal.classList.add('hidden');
}

function setupPersonaAdminControls() {
    if (elements.personaAdminRefreshBtn) {
        elements.personaAdminRefreshBtn.addEventListener('click', refreshPersonaAdminStats);
    }
    if (elements.personaAdminPreviewBtn) {
        elements.personaAdminPreviewBtn.addEventListener('click', previewPersonaReclassify);
    }
    if (elements.personaAdminApplyBtn) {
        elements.personaAdminApplyBtn.addEventListener('click', applyPersonaReclassify);
    }
    if (elements.personaOverrideApplyBtn) {
        elements.personaOverrideApplyBtn.addEventListener('click', applyPersonaOverride);
    }
    if (elements.personaRestoreBtn) {
        elements.personaRestoreBtn.addEventListener('click', restorePersonaFromBackup);
    }
}

async function refreshPersonaAdminStats() {
    if (!elements.personaAdminStats) return;
    elements.personaAdminStats.textContent = 'Loading stats...';
    try {
        const response = await authFetch(`${CONFIG.API_BASE}/persona/history/stats`);
        const data = await response.json();
        if (data.status !== 'success') throw new Error(data.message || 'Stats request failed');

        const counts = data.counts || {};
        const backups = data.backups || [];
        const statsLines = Object.keys(counts).length
            ? Object.entries(counts).map(([k, v]) => `${k}: ${v}`).join('\n')
            : 'No persona rows found.';
        elements.personaAdminStats.textContent = statsLines;
        populateBackupOptions(backups);
    } catch (error) {
        elements.personaAdminStats.textContent = `Failed: ${error.message}`;
    }
}

function populateBackupOptions(backups) {
    if (!elements.personaBackupSelect) return;
    elements.personaBackupSelect.innerHTML = '';
    if (!backups || backups.length === 0) {
        elements.personaBackupSelect.innerHTML = '<option value="">No backup loaded</option>';
        return;
    }
    backups.forEach(file => {
        const option = document.createElement('option');
        option.value = file;
        option.textContent = file;
        elements.personaBackupSelect.appendChild(option);
    });
}

async function previewPersonaReclassify() {
    if (!elements.personaAdminPreview) return;
    elements.personaAdminPreview.textContent = 'Running preview...';
    try {
        const response = await authFetch(`${CONFIG.API_BASE}/persona/history/preview?limit_turns=10`);
        const data = await response.json();
        if (data.status !== 'success') throw new Error(data.message || 'Preview failed');
        const preview = data.preview || {};
        const lines = [
            `rows_scanned: ${preview.rows_scanned || 0}`,
            `turns_scanned: ${preview.turns_scanned || 0}`,
            `updates_total: ${preview.updates_total || 0}`,
            `updates_to_advisor: ${preview.updates_to_advisor || 0}`,
            `updates_to_consultant: ${preview.updates_to_consultant || 0}`,
        ];
        const sample = (preview.sample_turns || [])
            .slice(0, 5)
            .map(turn => `- ${turn.target} ${JSON.stringify(turn.row_ids)} :: ${turn.excerpt || ''}`);
        elements.personaAdminPreview.textContent = [...lines, '', 'sample:', ...sample].join('\n');
    } catch (error) {
        elements.personaAdminPreview.textContent = `Failed: ${error.message}`;
    }
}

async function applyPersonaReclassify() {
    if (!confirm('Apply advisor/consultant reclassification now?')) return;
    if (elements.personaAdminPreview) {
        elements.personaAdminPreview.textContent = 'Applying reclassify...';
    }
    try {
        const response = await authFetch(`${CONFIG.API_BASE}/persona/history/reclassify`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ apply: true })
        });
        const data = await response.json();
        if (data.status !== 'success') throw new Error(data.message || 'Apply failed');
        const result = data.result || {};
        if (elements.personaAdminPreview) {
            elements.personaAdminPreview.textContent = `Applied.\nupdates_total: ${result.updates_total || 0}\ncounts_after: ${JSON.stringify(result.counts_after || {}, null, 2)}`;
        }
        await refreshPersonaAdminStats();
        showNotification('Persona reclassify applied', 'success');
    } catch (error) {
        if (elements.personaAdminPreview) {
            elements.personaAdminPreview.textContent = `Failed: ${error.message}`;
        }
        showNotification(`Reclassify failed: ${error.message}`, 'error');
    }
}

function parseRowIds(raw) {
    return String(raw || '')
        .split(',')
        .map(x => Number.parseInt(x.trim(), 10))
        .filter(Number.isInteger);
}

async function applyPersonaOverride() {
    const rowIds = parseRowIds(elements.personaOverrideRowIds?.value);
    const persona = elements.personaOverrideSelect?.value;
    if (!rowIds.length) {
        showNotification('Isi row IDs dulu untuk override', 'error');
        return;
    }
    try {
        const response = await authFetch(`${CONFIG.API_BASE}/persona/history/override`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ row_ids: rowIds, persona })
        });
        const data = await response.json();
        if (data.status !== 'success') throw new Error(data.message || 'Override failed');
        showNotification(`Override success: ${data.result?.updated_rows || 0} rows`, 'success');
        await refreshPersonaAdminStats();
    } catch (error) {
        showNotification(`Override failed: ${error.message}`, 'error');
    }
}

async function restorePersonaFromBackup() {
    const backupFile = elements.personaBackupSelect?.value;
    if (!backupFile) {
        showNotification('Pilih backup file dulu', 'error');
        return;
    }
    if (!confirm(`Restore persona labels from backup ${backupFile}?`)) return;
    try {
        const response = await authFetch(`${CONFIG.API_BASE}/persona/history/restore`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ backup_file: backupFile })
        });
        const data = await response.json();
        if (data.status !== 'success') throw new Error(data.message || 'Restore failed');
        showNotification(`Restore success: ${data.result?.restored_rows || 0} rows`, 'success');
        await refreshPersonaAdminStats();
        await previewPersonaReclassify();
    } catch (error) {
        showNotification(`Restore failed: ${error.message}`, 'error');
    }
}

// ============================================
// Uploaded Files Modal
// ============================================
async function openFilesModal() {
    if (!elements.filesModal) {
        const modalHtml = `
            <div id="filesModal" class="fixed inset-0 z-[60] hidden">
                <div class="absolute inset-0 bg-black/50 backdrop-blur-sm" id="filesBackdrop"></div>
                <div class="absolute right-0 top-0 h-full w-full max-w-md bg-white dark:bg-gray-800 shadow-2xl animate-slide-right overflow-y-auto">
                    <div class="p-6">
                        <div class="flex items-center justify-between mb-6">
                            <h3 class="text-xl font-bold text-gray-800 dark:text-white">Uploaded Files</h3>
                            <button id="closeFiles" class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
                                <i data-lucide="x" class="w-5 h-5 text-gray-600 dark:text-gray-300"></i>
                            </button>
                        </div>
                        <div id="filesContent" class="space-y-3">
                            <div class="flex items-center justify-center py-8">
                                <div class="spinner"></div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        elements.filesModal = document.getElementById('filesModal');
        elements.filesContent = document.getElementById('filesContent');

        document.getElementById('closeFiles').addEventListener('click', closeFilesModal);
        document.getElementById('filesBackdrop').addEventListener('click', closeFilesModal);
    }

    elements.filesModal.classList.remove('hidden');
    elements.filesContent.innerHTML = '<div class="flex items-center justify-center py-8"><div class="spinner"></div></div>';

    try {
        const response = await authFetch(`${CONFIG.API_BASE}/list-files`);
        const data = await response.json();

        if (data.status === 'success' && Array.isArray(data.data)) {
            const files = data.data;

            if (files.length === 0) {
                elements.filesContent.innerHTML = `
                    <div class="text-center py-8 text-gray-500">
                        <i data-lucide="folder-open" class="w-12 h-12 mx-auto mb-3 opacity-50"></i>
                        <p>No files uploaded yet</p>
                    </div>
                `;
            } else {
                let html = '';
                files.forEach(file => {
                    html += renderFileCard(file);
                });
                elements.filesContent.innerHTML = html;
            }
        } else {
            elements.filesContent.innerHTML = '<p class="text-red-500 text-center py-8">Failed to load files</p>';
        }
    } catch (error) {
        elements.filesContent.innerHTML = `<p class="text-red-500 text-center py-8">Error: ${error.message}</p>`;
    }

    lucide.createIcons();
}

function renderFileCard(file) {
    const name = file.original_filename || file.stored_filename;
    const ext = name.split('.').pop().toLowerCase();
    let colorClass = 'text-gray-400';
    if (['pdf'].includes(ext)) colorClass = 'text-red-400';
    else if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext)) colorClass = 'text-blue-400';
    else if (['py', 'js', 'json'].includes(ext)) colorClass = 'text-yellow-400';

    const size = formatBytes(file.size_bytes);
    const date = new Date(file.uploaded_at).toLocaleString();

    // Check for expiry
    let expiryBadge = '';
    if (file.expires_at) {
        const expires = new Date(file.expires_at);
        const now = new Date();
        const diffDays = Math.ceil((expires - now) / (1000 * 60 * 60 * 24));
        if (diffDays <= 30) {
            expiryBadge = `<span class="ml-2 text-[10px] px-1.5 py-0.5 bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300 rounded flex items-center gap-1">
                <i data-lucide="clock" class="w-3 h-3"></i> Expires in ${diffDays}d
            </span>`;
        }
    }

    return `
        <div class="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 hover:bg-gray-100 dark:hover:bg-gray-600 transition-colors">
            <div class="flex items-center gap-3">
                <i data-lucide="file" class="w-5 h-5 ${colorClass}"></i>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center">
                        <p class="text-sm font-medium text-gray-800 dark:text-white truncate">${escapeHtml(name)}</p>
                        ${expiryBadge}
                    </div>
                    <p class="text-xs text-gray-500">${size} • ${date}</p>
                </div>
            </div>
        </div>
    `;
}

function formatBytes(bytes, decimals = 2) {
    if (!+bytes) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}

function openAccessDeniedModal() {
    const modal = document.getElementById('accessDeniedModal');
    if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }
}

function closeAccessDeniedModal() {
    const modal = document.getElementById('accessDeniedModal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
}

function closeFilesModal() {
    if (elements.filesModal) {
        elements.filesModal.classList.add('hidden');
    }
}

// ============================================
// Utility Functions
// ============================================
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Safe attribute-value encoder: escapeHtml handles `<`/`>`/`&` but leaves
// straight quotes intact, which breaks `data-…="…"` embedding. Replace the
// remaining quotes explicitly so the Sebastian replay button survives any
// response containing quotation marks.
function escapeAttr(text) {
    return escapeHtml(String(text || ''))
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function getCurrentTime() {
    return new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

function formatChatTimestamp(timestamp) {
    if (!timestamp) return getCurrentTime();
    let value = String(timestamp).trim();
    if (!value) return getCurrentTime();
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(value)) {
        value = value.replace(' ', 'T') + 'Z';
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return getCurrentTime();
    return parsed.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

function showNotification(message, type = 'info') {
    console.log(`[${type.toUpperCase()}] ${message}`);
}

// ============================================
// Persona Toggle Functions
// ============================================
const personaLabels = {
    consultant: '🎯 Consultant',
    advisor: '🧪 Advisor',
    chill: '😎 Chill Wingman',
    tactical: '🔧 Tactical Ops',
    butler: '🛡️ Butler',
    chancellor: '📒 The Chancellor',
    auditor: '🔍 QA Architect'
};

const personaAliases = {
    support: 'tactical',
    technical: 'tactical',
    casual: 'chill',
    adversarial_scholar: 'advisor',
    qa: 'auditor'
};

function normalizePersona(persona) {
    const raw = String(persona || '').trim().toLowerCase();
    if (VALID_PERSONAS.includes(raw)) return raw;
    if (personaAliases[raw]) return personaAliases[raw];
    return 'consultant';
}

function getPersonaFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const value = params.get('persona');
    return value ? normalizePersona(value) : null;
}

function setPersonaInUrl(personaName, refresh = false) {
    const normalized = normalizePersona(personaName);
    const target = `/chat?persona=${encodeURIComponent(normalized)}`;
    if (refresh) {
        window.history.replaceState({}, '', target);
        return;
    }
    window.history.replaceState({}, '', target);
}

function updatePersonaLabel() {
    if (elements.currentPersonaLabel) {
        elements.currentPersonaLabel.textContent = personaLabels[selectedPersona] || 'Consultant';
    }

    // Add "System Status: Auditing" ticker in HUD when auditor is active
    if (selectedPersona === 'auditor') {
        if (window.auditorInterval) clearInterval(window.auditorInterval);
        kuroRenderSentinelTicker({ status: 'SCANNING', source: 'AUDITOR', detail: 'System Status: Auditing' });
        window.auditorInterval = setInterval(() => {
            if (selectedPersona === 'auditor') {
                kuroRenderSentinelTicker({ status: 'SCANNING', source: 'AUDITOR', detail: 'System Status: Auditing' });
            }
        }, 25000); // refresh before 30s timeout
    } else {
        if (window.auditorInterval) {
            clearInterval(window.auditorInterval);
            window.auditorInterval = null;
        }
        if (typeof kuroRenderSentinelTicker === 'function') {
            kuroRenderSentinelTicker({ status: 'IDLE', source: 'ALL' });
        }
    }
}

async function applyPersona() {
    // Show loading state
    elements.messageInput.disabled = true;
    if(elements.sendBtn) elements.sendBtn.disabled = true;
    showNotification('Swapping persona, please wait...', 'info');

    try {
        const response = await authFetch(`${CONFIG.API_BASE}/persona`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ persona: selectedPersona })
        });

        const data = await response.json();

        if (data.status === 'success') {
            elements.personaDropdown.classList.add('hidden');
            showNotification(`Persona changed to ${personaLabels[selectedPersona]}`, 'success');
            localStorage.setItem('kuro-persona', selectedPersona);
            setPersonaInUrl(selectedPersona, true);
            await loadChatHistory();
        } else {
            showNotification('Failed to change persona: ' + data.message, 'error');
        }
    } catch (error) {
        showNotification('Error changing persona: ' + error.message, 'error');
    } finally {
        elements.messageInput.disabled = false;
        if(elements.sendBtn) elements.sendBtn.disabled = false;
    }
}

async function loadPersona() {
    const restricted = window.KURO_USER_CONTEXT?.restrictedPersona;
    const urlPersona = getPersonaFromUrl();
    const savedPersona = localStorage.getItem('kuro-persona');

    if (restricted) {
        selectedPersona = restricted;
        // Disable other options in UI
        document.querySelectorAll('.persona-option').forEach(option => {
            if (option.dataset.persona !== restricted) {
                option.disabled = true;
                option.classList.add('opacity-50', 'cursor-not-allowed');
                option.style.pointerEvents = 'none';
                option.title = "This persona is restricted for your account.";
            }
        });
    } else {
        selectedPersona = normalizePersona(urlPersona || savedPersona || 'consultant');
    }

    localStorage.setItem('kuro-persona', selectedPersona);
    localStorage.setItem('kuro_persona', selectedPersona); // consistency
    setPersonaInUrl(selectedPersona, false);

    // Use the new UI updater for the sidebar accordion
    updatePersonaUI();
    await loadChatHistory();
}

// ============================================
// User Info & Logout
// ============================================
function updateUserInfo() {
    const username = getUsername();
    if (elements.userInfo && username) {
        elements.userInfo.textContent = username;
    }

    // Update sidebar if exists (for dynamic branding)
    const sidebarDisplayName = document.getElementById('sidebarDisplayName');
    const sidebarRole = document.getElementById('sidebarRole');
    if (sidebarDisplayName && window.KURO_USER_CONTEXT?.displayName) {
        sidebarDisplayName.textContent = window.KURO_USER_CONTEXT.displayName;
    }
    if (sidebarRole && window.KURO_USER_CONTEXT?.role) {
        sidebarRole.textContent = window.KURO_USER_CONTEXT.role;
    }

    if (elements.logoutBtn) {
        elements.logoutBtn.addEventListener('click', logout);
    }
}

// ============================================
// Copy Message Content
// ============================================
function copyMessageContent(button) {
    const messageBubble = button.closest('.chat-bubble-ai');
    const markdownContent = messageBubble.querySelector('.markdown-content');

    if (!markdownContent) return;

    // Get the raw text content (strip HTML for clean copy)
    const textContent = markdownContent.innerText || markdownContent.textContent;

    navigator.clipboard.writeText(textContent).then(() => {
        // Visual feedback
        const originalIcon = button.innerHTML;
        button.innerHTML = '<i data-lucide="check" class="w-3.5 h-3.5 text-emerald-500"></i>';
        lucide.createIcons();

        setTimeout(() => {
            button.innerHTML = originalIcon;
            lucide.createIcons();
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy message:', err);
    });
}

// ============================================
// Copy Code Block
// ============================================
function copyCodeBlock(button) {
    const pre = button.closest('pre');
    const code = pre.querySelector('code');
    const text = code.textContent || code.innerText;

    navigator.clipboard.writeText(text).then(() => {
        const originalIcon = button.innerHTML;
        button.innerHTML = '<i data-lucide="check" class="w-3.5 h-3.5 text-emerald-500"></i>';
        button.querySelector('span').textContent = 'Copied!';
        lucide.createIcons();

        setTimeout(() => {
            button.innerHTML = originalIcon;
            lucide.createIcons();
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy code:', err);
    });
}

// ============================================
// Copy Table
// ============================================
function copyTable(button) {
    const table = button.closest('.table-wrapper').querySelector('table');

    // Convert table to CSV-like format
    const rows = table.querySelectorAll('tr');
    let csv = [];

    rows.forEach(row => {
        const cells = row.querySelectorAll('th, td');
        const rowData = [];
        cells.forEach(cell => {
            let text = cell.textContent || cell.innerText;
            // Escape commas and quotes
            if (text.includes(',') || text.includes('"') || text.includes('\n')) {
                text = '"' + text.replace(/"/g, '""') + '"';
            }
            rowData.push(text);
        });
        csv.push(rowData.join(','));
    });

    navigator.clipboard.writeText(csv.join('\n')).then(() => {
        const originalIcon = button.innerHTML;
        button.innerHTML = '<i data-lucide="check" class="w-3.5 h-3.5 text-emerald-500"></i>';
        button.querySelector('span').textContent = 'Copied!';
        lucide.createIcons();

        setTimeout(() => {
            button.innerHTML = originalIcon;
            lucide.createIcons();
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy table:', err);
    });
}

// ============================================
// Add Copy Buttons to Code Blocks
// ============================================
function addCodeBlockCopyButtons(container) {
    const codeBlocks = container.querySelectorAll('pre');
    codeBlocks.forEach(pre => {
        // Wrap in relative container
        const wrapper = document.createElement('div');
        wrapper.className = 'relative group/code';
        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(pre);

        // Add copy button
        const copyBtn = document.createElement('button');
        copyBtn.className = 'absolute top-2 right-2 p-1.5 rounded-lg bg-gray-700 hover:bg-gray-600 text-white opacity-0 group-hover/code:opacity-100 transition-opacity flex items-center gap-1 text-xs';
        copyBtn.onclick = function () { copyCodeBlock(this); };
        copyBtn.innerHTML = '<i data-lucide="copy" class="w-3.5 h-3.5"></i><span>Copy</span>';
        wrapper.appendChild(copyBtn);
    });
    lucide.createIcons();
}

// ============================================
// Add Copy Buttons to Tables
// ============================================
function addTableCopyButtons(container) {
    const tables = container.querySelectorAll('table');
    tables.forEach(table => {
        // Wrap in relative container
        const wrapper = document.createElement('div');
        wrapper.className = 'table-wrapper relative group/table overflow-x-auto';
        table.parentNode.insertBefore(wrapper, table);
        wrapper.appendChild(table);

        // Add copy button
        const copyBtn = document.createElement('button');
        copyBtn.className = 'absolute top-2 right-2 p-1.5 rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 opacity-0 group-hover/table:opacity-100 transition-opacity flex items-center gap-1 text-xs';
        copyBtn.onclick = function () { copyTable(this); };
        copyBtn.innerHTML = '<i data-lucide="copy" class="w-3.5 h-3.5 text-gray-500 dark:text-gray-400"></i><span class="text-gray-600 dark:text-gray-300">Copy</span>';
        wrapper.appendChild(copyBtn);
    });
    lucide.createIcons();
}

// ============================================
async function handlePasswordChange(e) {
    e.preventDefault();
    const oldPassword = document.getElementById('oldPassword').value;
    const newPassword = document.getElementById('newPassword').value;
    const repeatPassword = document.getElementById('repeatPassword').value;
    const spinner = document.getElementById('passwordSpinner');
    const submitBtn = e.target.querySelector('button[type="submit"]');

    if (newPassword !== repeatPassword) {
        showNotification('New passwords do not match', 'error');
        return;
    }

    submitBtn.disabled = true;
    spinner.classList.remove('hidden');

    // Setup Stop Generating
    const stopBtn = document.getElementById('stopGeneratingBtn');
    const abortController = new AbortController();
    if (stopBtn) {
        stopBtn.classList.remove('hidden');
        stopBtn.onclick = () => {
            abortController.abort();
            stopBtn.classList.add('hidden');
        };
    }

    try {
        const formData = new FormData();
        formData.append('old_password', oldPassword);
        formData.append('new_password', newPassword);
        formData.append('repeat_password', repeatPassword);

        const response = await fetch('/api/user/change-password', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();
        if (result.success) {
            showNotification('Password changed successfully!', 'success');
            elements.changePasswordModal.classList.add('hidden');
            elements.changePasswordForm.reset();
        } else {
            showNotification(result.error || 'Failed to change password', 'error');
        }
    } catch (err) {
        showNotification('Connection error', 'error');
    } finally {
        submitBtn.disabled = false;
        spinner.classList.add('hidden');
    }
}

async function handlePersonaUpdate(e) {
    e.preventDefault();
    const customPersona = elements.customPersonaInput.value;
    const spinner = document.getElementById('personaSpinner');
    const submitBtn = e.target.querySelector('button[type="submit"]');

    submitBtn.disabled = true;
    spinner.classList.remove('hidden');

    // Setup Stop Generating
    const stopBtn = document.getElementById('stopGeneratingBtn');
    const abortController = new AbortController();
    if (stopBtn) {
        stopBtn.classList.remove('hidden');
        stopBtn.onclick = () => {
            abortController.abort();
            stopBtn.classList.add('hidden');
        };
    }

    try {
        const formData = new FormData();
        formData.append('custom_persona', customPersona);

        const response = await fetch('/api/user/update-persona', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();
        if (result.success) {
            showNotification('Global persona updated!', 'success');
            elements.personaModal.classList.add('hidden');
            // Update local context
            if (window.KURO_USER_CONTEXT) {
                window.KURO_USER_CONTEXT.customPersona = customPersona;
            }
        } else {
            showNotification(result.error || 'Failed to update persona', 'error');
        }
    } catch (err) {
        showNotification('Connection error', 'error');
    } finally {
        submitBtn.disabled = false;
        spinner.classList.add('hidden');
    }
}


let marketHudInterval = null;
const KURO_MARKET_HUD_POLL_INTERVAL_MS = window.KURO_MARKET_HUD_POLL_INTERVAL_MS || 30000;

async function kuroStartMarketHudPoll() {
    if (marketHudInterval) clearInterval(marketHudInterval);

    const fetchHud = async () => {
        if (_kuroCurrentMode !== 'HUD_MODE') return;
        try {
            const response = await authFetch(`${CONFIG.API_BASE}/market/hud`);
            if (response.ok) {
                const data = await response.json();
                const payload = data?.data || data || {};
                const chips = Array.isArray(payload.hud_items)
                    ? [...payload.hud_items]
                    : (Array.isArray(payload.items) ? [...payload.items] : []);
                if (payload.news_available === false) {
                    chips.push({
                        id: 'news_na',
                        label: '📰 News N/A',
                        kind: 'system',
                        trend: 'flat',
                        sentiment: null,
                    });
                }
                if (chips.length > 0 && typeof kuroRenderSentinelTicker === 'function') {
                    kuroRenderSentinelTicker({
                        status: 'ALERT',
                        source: 'MARKET',
                        market_chips: chips,
                    });
                }
            }
        } catch (e) {
            console.error('Market HUD poll failed:', e);
        }
    };

    marketHudInterval = setInterval(fetchHud, KURO_MARKET_HUD_POLL_INTERVAL_MS);
    // Initial fetch
    fetchHud();
}

// Call on startup
document.addEventListener('DOMContentLoaded', () => {
    if (typeof kuroStartMarketHudPoll === 'function') {
        setTimeout(kuroStartMarketHudPoll, 2000);
    }
});


// ============================================
// Beta 5 Sovereign Chat Functions
// ============================================

async function togglePinChatSession(chatId, currentlyPinned) {
    ensureNormalModeForChatNavigation();
    const endpoint = currentlyPinned ? 'unpin' : 'pin';
    try {
        const response = await authFetch(`${CONFIG.API_BASE}/chats/${chatId}/${endpoint}`, { method: 'POST' });
        if (response.ok) {
            const session = chatSessions.find(s => s.chat_id === chatId);
            if (session) session.is_pinned = !currentlyPinned;
            loadChatSessions();
            showNotification(currentlyPinned ? 'Chat unpinned' : 'Chat pinned', 'success');
        }
    } catch (error) {
        console.error('Pin toggle failed:', error);
    }
}

async function editMessage(messageId) {
    const messageDiv = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageDiv) return;

    const contentP = messageDiv.querySelector('p');
    if (!contentP) return;

    const originalContent = contentP.textContent;
    const newContent = prompt('Edit your message:', originalContent);
    
    if (newContent === null || newContent === originalContent) return;

    try {
        const response = await authFetch(`${CONFIG.API_BASE}/chats/${currentChatId}/messages/${messageId}/edit`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_content: newContent })
        });

        if (response.ok) {
            // Success! Reload the chat history to reflect changes and truncation
            await selectChatSession(currentChatId);
            showNotification('Message updated. Subsequent history truncated.', 'success');
        }
    } catch (error) {
        console.error('Edit failed:', error);
        showNotification('Failed to edit message', 'error');
    }
}

async function regenerateMessage(messageId) {
    if (!confirm('Regenerate this response? Subsequent messages will be deleted.')) return;

    try {
        const response = await authFetch(`${CONFIG.API_BASE}/chats/${currentChatId}/messages/${messageId}/regenerate`, {
            method: 'POST'
        });

        if (response.ok) {
            const result = await response.json();
            const precedingMsg = result.data.preceding_user_message;
            
            // Re-trigger sendMessage with the preceding user content
            // but first, clean up the UI
            await selectChatSession(currentChatId);
            
            // Now "re-send" the last message
            elements.messageInput.value = precedingMsg.content;
            sendMessage(false);
            showNotification('Regenerating response...', 'success');
        }
    } catch (error) {
        console.error('Regeneration failed:', error);
        showNotification('Failed to regenerate message', 'error');
    }
}

async function toggleMessageBookmark(messageId, btn) {
    try {
        const response = await authFetch(`${CONFIG.API_BASE}/chats/${currentChatId}/messages/${messageId}/bookmark`, {
            method: 'POST'
        });

        if (response.ok) {
            const result = await response.json();
            const isBookmarked = result.data.is_bookmarked;
            
            const icon = btn.querySelector('i');
            if (isBookmarked) {
                btn.classList.add('text-amber-500');
                btn.classList.remove('text-gray-400');
                icon.classList.add('fill-amber-500');
            } else {
                btn.classList.remove('text-amber-500');
                btn.classList.add('text-gray-400');
                icon.classList.remove('fill-amber-500');
            }
            lucide.createIcons();
        }
    } catch (error) {
        console.error('Bookmark toggle failed:', error);
    }
}

async function handleSearch() {
    const query = elements.searchInput.value.trim();
    if (query.length < 2) {
        elements.searchResults.innerHTML = `
            <div class="flex flex-col items-center justify-center py-12 text-gray-400">
                <i data-lucide="message-square" class="w-12 h-12 mb-3 opacity-20"></i>
                <p class="text-sm">Type at least 2 characters to search</p>
            </div>
        `;
        lucide.createIcons();
        return;
    }

    elements.searchResults.innerHTML = '<div class="flex justify-center p-8"><div class="spinner border-emerald-500"></div></div>';

    try {
        const response = await authFetch(`${CONFIG.API_BASE}/chats/${currentChatId}/search?q=${encodeURIComponent(query)}`);
        const result = await response.json();
        
        if (result.status === 'success') {
            const results = result.data;
            if (results.length === 0) {
                elements.searchResults.innerHTML = '<p class="text-center py-8 text-gray-500">No results found in this session.</p>';
            } else {
                elements.searchResults.innerHTML = results.map(msg => `
                    <div class="p-3 rounded-xl border border-gray-100 dark:border-gray-700 bg-gray-50/50 dark:bg-gray-900/20 hover:border-emerald-500/30 transition-colors cursor-pointer"
                         onclick="jumpToMessage(${msg.id})">
                        <div class="flex items-center gap-2 mb-1">
                            <span class="text-[10px] font-bold uppercase tracking-wider ${msg.role === 'user' ? 'text-purple-500' : 'text-emerald-500'}">${msg.role}</span>
                            <span class="text-[9px] text-gray-400">${msg.timestamp}</span>
                        </div>
                        <p class="text-sm text-gray-600 dark:text-gray-300 line-clamp-2">${escapeHtml(msg.content)}</p>
                    </div>
                `).join('');
            }
            lucide.createIcons();
        }
    } catch (error) {
        console.error('Search failed:', error);
    }
}

function jumpToMessage(messageId) {
    closeSearchModal();
    const msgEl = document.querySelector(`[data-message-id="${messageId}"]`);
    if (msgEl) {
        msgEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        msgEl.classList.add('highlight-pulse');
        setTimeout(() => msgEl.classList.remove('highlight-pulse'), 3000);
    } else {
        showNotification('Message not currently loaded in view.', 'info');
    }
}

function openSearchModal() {
    elements.searchModal.classList.remove('hidden');
    elements.searchInput.focus();
}

function closeSearchModal() {
    elements.searchModal.classList.add('hidden');
}

async function exportChatSession(chatId) {
    openExportModal(chatId);
}

function openExportModal(chatId) {
    ensureNormalModeForChatNavigation();

    if (!elements.exportModal) return;
    elements.exportModal.dataset.chatId = chatId;
    elements.exportTargetLabel.textContent = `Chat Session: ${chatId}`;
    elements.exportFormatSelect.value = 'md';
    elements.exportStatus.textContent = '';
    elements.exportStatus.className = 'text-sm text-gray-500 dark:text-gray-400';
    elements.exportDownloadLink.classList.add('hidden');
    elements.exportDownloadLink.href = '#';
    elements.exportModal.classList.remove('hidden');
}

function closeExportModal() {
    if (!elements.exportModal) return;
    elements.exportModal.classList.add('hidden');
}

function renderExportSuggestions(container, suggestions) {
    if (!container || !Array.isArray(suggestions) || suggestions.length === 0) return;

    const existing = container.querySelector('.export-suggestion');
    if (existing) existing.remove();

    const action = document.createElement('div');
    action.className = 'export-suggestion mt-3 flex flex-col gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-3 py-2';
    const reason = suggestions[0]?.reason || 'Structured output detected.';
    const iconForFormat = (format) => {
        if (format === 'pdf' || format === 'docx') return 'file-text';
        if (format === 'csv' || format === 'xlsx') return 'table';
        return 'download';
    };
    const buttons = suggestions.map((suggestion, index) => `
        <button data-suggestion-index="${index}" class="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-600 transition-colors">
            <i data-lucide="${iconForFormat(suggestion.format)}" class="w-3.5 h-3.5"></i>
            ${escapeHtml(suggestion.title || `Export to ${String(suggestion.format || '').toUpperCase()}`)}
        </button>
    `).join('');

    action.innerHTML = `
        <span class="text-[11px] text-emerald-700 dark:text-emerald-300">${escapeHtml(reason)}</span>
        <div class="flex flex-wrap gap-2">${buttons}</div>
    `;
    action.querySelectorAll('button[data-suggestion-index]').forEach((button) => {
        button.addEventListener('click', () => {
            const idx = Number(button.getAttribute('data-suggestion-index'));
            quickExportSuggestedChat(suggestions[idx]);
        });
    });
    container.appendChild(action);
    lucide.createIcons();
}

async function quickExportSuggestedChat(suggestion) {
    const chatId = suggestion.chat_id || currentChatId;
    if (!chatId) {
        showNotification('Chat session not available for export.', 'error');
        return;
    }

    try {
        const response = await authFetch(`${CONFIG.API_BASE}/export`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target: suggestion.target || 'chat_session',
                chat_id: chatId,
                format: suggestion.format || 'xlsx',
                message_ids: Array.isArray(suggestion.message_ids) ? suggestion.message_ids : [],
            }),
        });
        await downloadBlobResponse(response, `chat_${chatId}.${suggestion.format || 'xlsx'}`);
        showNotification(`${String(suggestion.format || 'file').toUpperCase()} export generated`, 'success');
    } catch (error) {
        showNotification(`Export failed: ${error.message}`, 'error');
    }
}

async function submitExportRequest() {
    const chatId = elements.exportModal?.dataset.chatId;
    const format = elements.exportFormatSelect?.value || 'md';
    if (!chatId) return;

    elements.exportSubmitBtn.disabled = true;
    elements.exportStatus.textContent = 'Preparing export...';
    elements.exportStatus.className = 'text-sm text-gray-500 dark:text-gray-400';
    elements.exportDownloadLink.classList.add('hidden');

    try {
        const response = await authFetch(`${CONFIG.API_BASE}/export`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target: 'chat_session',
                chat_id: chatId,
                format,
                message_ids: [],
            }),
        });

        if (format === 'pdf') {
            const result = await response.json();
            elements.exportStatus.textContent = `PDF export queued. Job #${result.job_id}`;
            showExportProgress(result.job_id);
        } else {
            await downloadBlobResponse(response, `chat_${chatId}.${format}`);
            elements.exportStatus.textContent = 'Export ready. Download started.';
            showNotification('Export generated', 'success');
        }
    } catch (error) {
        elements.exportStatus.textContent = `Export failed: ${error.message}`;
        elements.exportStatus.className = 'text-sm text-red-500';
        showNotification('Export failed', 'error');
    } finally {
        elements.exportSubmitBtn.disabled = false;
    }
}

/**
 * Render and poll export progress for background PDF jobs.
 * @param {number|string} jobId
 */
function showExportProgress(jobId) {
    const container = elements.exportStatusContainer;
    if (!container) return;
    const indicatorId = `export-progress-${jobId}`;
    const existing = document.getElementById(indicatorId);
    if (existing) existing.remove();

    const indicator = document.createElement('div');
    indicator.id = indicatorId;
    indicator.className = 'export-progress-indicator';
    indicator.innerHTML = `<span class="spinner"></span> Generating PDF...`;
    container.appendChild(indicator);

    const poll = setInterval(async () => {
        try {
            const res = await authFetch(`${CONFIG.API_BASE}/export/${jobId}`);
            if (!res || !res.ok) {
                indicator.innerHTML = `❌ Export gagal: status ${res?.status || 'unknown'}`;
                clearInterval(poll);
                return;
            }
            const data = await res.json();
            const job = data?.data || data || {};
            const status = job.status || 'queued';
            if (status === 'completed') {
                clearInterval(poll);
                indicator.innerHTML = `✅ PDF ready — <a href="/api/export/${jobId}/download">Download</a>`;
                elements.exportStatus.textContent = 'PDF export completed.';
                elements.exportDownloadLink.href = `/api/export/${jobId}/download`;
                elements.exportDownloadLink.classList.remove('hidden');
                showToast('Export selesai! Klik untuk download.', 'success');
            } else if (status === 'failed') {
                clearInterval(poll);
                indicator.innerHTML = `❌ Export gagal: ${job.error || job.error_message || 'Unknown error'}`;
                elements.exportStatus.textContent = indicator.textContent || 'PDF export failed.';
                elements.exportStatus.className = 'text-sm text-red-500';
            } else {
                indicator.innerHTML = `<span class="spinner"></span> Generating PDF... (${status})`;
                elements.exportStatus.textContent = `PDF export ${status}...`;
            }
        } catch (error) {
            clearInterval(poll);
            indicator.innerHTML = `❌ Export gagal: ${error.message}`;
            elements.exportStatus.textContent = `Export failed: ${error.message}`;
            elements.exportStatus.className = 'text-sm text-red-500';
        }
    }, 2000);
}

async function downloadBlobResponse(response, fallbackFilename) {
    const blob = await response.blob();
    const header = response.headers.get('Content-Disposition') || '';
    const match = header.match(/filename=\"?([^\";]+)\"?/i);
    const filename = match ? match[1] : fallbackFilename;
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
}

function copyMessageText(btn) {
    const group = btn.closest('.group');
    const bubble = group.querySelector('.chat-bubble-user, .chat-bubble-ai');
    
    // For AI bubbles, prefer the markdown source if available, or just the text
    const markdownContent = bubble.querySelector('.markdown-content');
    const text = markdownContent ? markdownContent.textContent : bubble.innerText;
    
    navigator.clipboard.writeText(text.trim()).then(() => {
        const icon = btn.querySelector('i');
        const originalIcon = icon.getAttribute('data-lucide');
        icon.setAttribute('data-lucide', 'check');
        lucide.createIcons();
        showNotification('Copied to clipboard', 'success');
        setTimeout(() => {
            icon.setAttribute('data-lucide', originalIcon);
            lucide.createIcons();
        }, 2000);
    });
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function showNotification(message, type = 'success') {
    // Check if toast container exists
    let container = document.getElementById('toastContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toastContainer';
        container.className = 'fixed top-6 right-6 z-[100] flex flex-col gap-3 pointer-events-none';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `px-6 py-3 rounded-2xl shadow-2xl backdrop-blur-xl border flex items-center gap-3 animate-slide-in pointer-events-auto
        ${type === 'success' ? 'bg-emerald-500/90 text-white border-emerald-400/20' : 
          type === 'error' ? 'bg-red-500/90 text-white border-red-400/20' : 
          'bg-gray-800/90 text-white border-gray-700/20'}`;
    
    const icon = type === 'success' ? 'check-circle' : type === 'error' ? 'alert-circle' : 'info';
    
    toast.innerHTML = `
        <i data-lucide="${icon}" class="w-5 h-5"></i>
        <span class="text-sm font-medium">${message}</span>
    `;
    
    container.appendChild(toast);
    lucide.createIcons();
    
    setTimeout(() => {
        toast.classList.add('animate-fade-out');
        setTimeout(() => toast.remove(), 500);
    }, 4000);
}

/**
 * Non-blocking toast helper used by global fetch/reconnect flows.
 * @param {string} message
 * @param {'success'|'error'|'info'} type
 */
function showToast(message, type = 'info') {
    showNotification(message, type);
}
