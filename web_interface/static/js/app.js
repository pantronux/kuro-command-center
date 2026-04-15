/**
 * Kuro AI Web Dashboard - Main Application V4.0
 * One UI + Glassmorphism Design with Infinite Scroll
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
        'text/plain': 'text',
        'text/markdown': 'markdown',
        'text/x-python': 'code',
        'text/csv': 'csv',
    },
    ALLOWED_EXTENSIONS: ['.txt', '.md', '.py', '.csv'],
};

// ============================================
// Authentication Helper Functions (Cookie-Based)
// ============================================
function getUsername() {
    return localStorage.getItem('kuro_username') || sessionStorage.getItem('kuro_username') || 'Pantronux';
}

function logout() {
    console.log('Logging out...');
    fetch('/api/auth/logout', { method: 'POST' })
        .then(() => { window.location.href = '/login'; })
        .catch(() => { window.location.href = '/login'; });
}

async function authFetch(url, options = {}) {
    options.credentials = options.credentials || 'include';
    const response = await fetch(url, options);
    
    if (response.status === 401) {
        window.location.href = '/login';
        throw new Error('Authentication required');
    }
    
    return response;
}

// ============================================
// State
// ============================================
let selectedFiles = [];
let isProcessing = false;
let chatHistory = [];
let selectedPersona = 'consultant';

// Infinite Scroll State
let chatOffset = 0;
let isLoadingMore = false;
let hasMoreMessages = true;
let scrollAnchorPosition = null;
const VALID_PERSONAS = ['consultant', 'advisor', 'chill', 'tactical', 'butler'];

// ============================================
// DOM Elements
// ============================================
const elements = {
    chatContainer: document.getElementById('chatContainer'),
    messageInput: document.getElementById('messageInput'),
    sendBtn: document.getElementById('sendBtn'),
    uploadBtn: document.getElementById('uploadBtn'),
    fileInput: document.getElementById('fileInput'),
    filePreview: document.getElementById('filePreview'),
    dropOverlay: document.getElementById('dropOverlay'),
    darkModeToggle: document.getElementById('darkModeToggle'),
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
    navSystemStatus: document.getElementById('navSystemStatus'),
    navSettings: document.getElementById('navSettings'),
    navFiles: document.getElementById('navFiles'),
    // Files Modal
    filesModal: null,
    filesContent: null,
    // User Info & Logout
    userInfo: document.getElementById('userInfo'),
    logoutBtn: document.getElementById('logoutBtn'),
};

// ============================================
// Initialize
// ============================================
document.addEventListener('DOMContentLoaded', () => {
    lucide.createIcons();
    
    marked.setOptions({
        highlight: function(code, lang) {
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
    setupAutoResize();
    setupInfiniteScroll();
    loadChatHistory();
    updateUserInfo();
});

// ============================================
// Event Listeners
// ============================================
function setupEventListeners() {
    elements.sendBtn.addEventListener('click', sendMessage);
    elements.messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    
    elements.uploadBtn.addEventListener('click', () => elements.fileInput.click());
    elements.fileInput.addEventListener('change', handleFileSelect);
    
    // Ctrl+V paste support for images and files
    elements.messageInput.addEventListener('paste', handlePaste);
    
    setupDragAndDrop();
    elements.darkModeToggle.addEventListener('click', toggleDarkMode);
    
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
    elements.navSystemStatus.addEventListener('click', (e) => {
        e.preventDefault();
        openSystemStatus();
    });
    elements.closeSystemStatus.addEventListener('click', closeSystemStatus);
    elements.systemStatusBackdrop.addEventListener('click', closeSystemStatus);
    
    // Files Modal
    if (elements.navFiles) {
        elements.navFiles.addEventListener('click', (e) => {
            e.preventDefault();
            openFilesModal();
        });
    }
    
    // Settings Modal
    elements.navSettings.addEventListener('click', (e) => {
        e.preventDefault();
        openSettings();
    });
    elements.closeSettings.addEventListener('click', closeSettings);
    elements.settingsBackdrop.addEventListener('click', closeSettings);
    
    elements.temperatureSlider.addEventListener('input', (e) => {
        elements.temperatureValue.textContent = e.target.value;
    });
    
    elements.clearHistoryBtn.addEventListener('click', clearChatHistory);
    setupPersonaAdminControls();
    
    // Persona Toggle
    if (elements.personaToggle && elements.personaDropdown) {
        elements.personaToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            elements.personaDropdown.classList.toggle('hidden');
        });
        
        document.addEventListener('click', (e) => {
            if (!elements.personaDropdown.contains(e.target) && !elements.personaToggle.contains(e.target)) {
                elements.personaDropdown.classList.add('hidden');
            }
        });
        
        document.querySelectorAll('.persona-option').forEach(option => {
            option.addEventListener('click', () => {
                selectedPersona = option.dataset.persona;
                updatePersonaLabel();
                document.querySelectorAll('.persona-option').forEach(o => o.classList.remove('bg-emerald-50', 'dark:bg-emerald-900/30'));
                option.classList.add('bg-emerald-50', 'dark:bg-emerald-900/30');
            });
        });
        
        if (elements.applyPersonaBtn) {
            elements.applyPersonaBtn.addEventListener('click', applyPersona);
        }
        
        loadPersona();
    }
}

function closeSidebar() {
    elements.sidebar.classList.add('-translate-x-full');
    document.body.style.overflow = '';
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
    elements.minimizeSidebar.classList.toggle('collapsed', collapsed);
    localStorage.setItem('kuro-sidebar-collapsed', collapsed);
    
    // Update icon
    const icon = elements.minimizeSidebar.querySelector('i');
    if (icon) {
        icon.setAttribute('data-lucide', collapsed ? 'panel-left-open' : 'panel-left-close');
        lucide.createIcons();
    }
}

// ============================================
// Auto-resize Textarea
// ============================================
function setupAutoResize() {
    elements.messageInput.addEventListener('input', function() {
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
    if (elements.chatContainer.scrollTop < 50) {
        loadMoreMessages();
    }
}

async function loadMoreMessages() {
    if (isLoadingMore || !hasMoreMessages) return;
    
    isLoadingMore = true;
    elements.scrollLoader.classList.add('visible');
    
    // Save current scroll height and position for anchor retention
    const previousScrollHeight = elements.chatContainer.scrollHeight;
    const previousScrollTop = elements.chatContainer.scrollTop;
    
    try {
        // FIX: Add platform=web filter to only load web messages
        const response = await authFetch(
            `${CONFIG.API_BASE}/history?limit=${CONFIG.CHAT_PAGE_SIZE}&offset=${chatOffset}&platform=web&persona=${encodeURIComponent(selectedPersona)}`
        );
        const data = await response.json();
        
        if (data.status === 'success' && data.history.length > 0) {
            // FIX: Backend already returns data in chronological order (oldest first).
            // For infinite scroll (loading older messages), we need to prepend them
            // in reverse order so the oldest appears at the very top.
            const messages = [...data.history].reverse();
            messages.forEach(msg => {
                const role = msg.role === 'user' ? 'user' : 'ai';
                prependMessageToChat(role, msg.content);
            });
            
            chatOffset += data.history.length;
            hasMoreMessages = data.has_more;
            
            // Scroll anchor retention: maintain visual position
            requestAnimationFrame(() => {
                const newScrollHeight = elements.chatContainer.scrollHeight;
                const heightDifference = newScrollHeight - previousScrollHeight;
                elements.chatContainer.scrollTop = previousScrollTop + heightDifference;
            });
        } else {
            hasMoreMessages = false;
        }
    } catch (error) {
        console.error('Failed to load more messages:', error);
    } finally {
        isLoadingMore = false;
        elements.scrollLoader.classList.remove('visible');
    }
}

// ============================================
// Dark Mode
// ============================================
function loadTheme() {
    const savedTheme = localStorage.getItem('kuro-theme');
    if (savedTheme === 'dark' || (!savedTheme && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
        document.documentElement.classList.add('dark');
    }
}

function toggleDarkMode() {
    document.documentElement.classList.toggle('dark');
    localStorage.setItem('kuro-theme', document.documentElement.classList.contains('dark') ? 'dark' : 'light');
}

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

// ============================================
// Chat Functions
// ============================================
// V5.1 STREAMING: Send message with SSE streaming
// ============================================
async function sendMessage() {
    const message = elements.messageInput.value.trim();
    
    if (!message && selectedFiles.length === 0) return;
    if (isProcessing) return;
    
    isProcessing = true;
    elements.sendBtn.disabled = true;
    
    // Add user message to chat
    addMessageToChat('user', message, selectedFiles);
    
    // Clear input
    elements.messageInput.value = '';
    elements.messageInput.style.height = 'auto';
    
    // Prepare files for upload
    const filesToSend = [...selectedFiles];
    selectedFiles = [];
    updateFilePreview();
    
    // Show typing indicator
    showTypingIndicator();
    
    // STEP 1: Create ONE empty chat bubble for Kuro and insert into DOM
    const aiMessageDiv = document.createElement('div');
    aiMessageDiv.className = 'flex items-start gap-3 message-enter';
    aiMessageDiv.innerHTML = `
        <div class="w-8 h-8 rounded-full bg-gradient-to-br from-emerald-400 to-teal-500 flex items-center justify-center flex-shrink-0"><i data-lucide="cat" class="w-4 h-4 text-white"></i></div>
        <div class="max-w-[85%] lg:max-w-[70%]">
            <div class="chat-bubble-ai px-4 py-3 shadow-sm">
                <div class="markdown-content streaming-content"></div>
            </div>
            <span class="text-xs text-gray-400 mt-1 block">${getCurrentTime()}</span>
        </div>
    `;
    elements.chatContainer.appendChild(aiMessageDiv);
    lucide.createIcons();
    
    // Get reference to the content div inside the bubble
    const streamingContent = aiMessageDiv.querySelector('.streaming-content');
    let botMessage = '';
    let buffer = '';
    let streamStarted = false;
    
    try {
        const formData = new FormData();
        formData.append('message', message);
        formData.append('persona', selectedPersona);
        filesToSend.forEach(file => formData.append('files', file));
        
        // STEP 2: Fetch the streaming endpoint
        const response = await fetch(`${CONFIG.API_BASE}/chat/stream`, {
            method: 'POST',
            body: formData,
            credentials: 'include',
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
            const events = buffer.split('\n\n');
            buffer = events.pop(); // Save incomplete event to buffer
            
            for (const event of events) {
                // Parse SSE event: extract event: and data: lines
                const lines = event.split('\n');
                let eventType = 'chunk'; // Default event type
                let dataStr = null;
                
                for (const line of lines) {
                    if (line.startsWith('event: ')) {
                        eventType = line.substring(7).trim();
                    } else if (line.startsWith('data: ')) {
                        dataStr = line.substring(6).trim();
                    }
                }
                
                if (!dataStr) continue;
                if (dataStr === '[DONE]') continue;
                
                try {
                    const data = JSON.parse(dataStr);
                    const piece = data.text != null && data.text !== '' ? data.text : data.chunk;
                    
                    if (eventType === 'chunk' && piece != null && piece !== '') {
                        if (!streamStarted) {
                            removeTypingIndicator();
                            streamStarted = true;
                        }
                        // Prefer plain text while streaming so half-open markdown does not blank the bubble
                        botMessage += piece;
                        streamingContent.textContent = botMessage;
                        elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
                    } else if (eventType === 'complete' && data.response) {
                        // Complete event: DO NOT create a new bubble.
                        // Only use for final markdown rendering and syntax highlighting.
                        // The bubble already exists from the chunk events above.
                        botMessage = data.response; // Use the complete response for consistency
                        streamingContent.innerHTML = marked.parse(botMessage);
                        streamingContent.classList.add('markdown-content');
                        hljs.highlightAll();
                        elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
                    } else if (eventType === 'error' && data.error) {
                        streamingContent.innerHTML = `<span style="color:red">Error: ${escapeHtml(data.error)}</span>`;
                    }
                } catch (e) {
                    console.error("JSON Parse Error on event:", dataStr);
                }
            }
        }
        
        if (!streamStarted) {
            removeTypingIndicator();
        }
        
        // Final render (fallback if complete event wasn't received)
        if (botMessage) {
            streamingContent.innerHTML = marked.parse(botMessage);
            hljs.highlightAll();
        }
        elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
        
    } catch (error) {
        console.error('Chat error:', error);
        removeTypingIndicator();
        // Error handling with recovery - show red text in the SAME bubble
        if (streamingContent) {
            // If we already have partial content, show it with error notice
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
        isProcessing = false;
        elements.sendBtn.disabled = false;
        // FIX: DO NOT call loadHistory() here - DOM is already updated in real-time
    }
}

// V5.1: Scroll to bottom helper for streaming
function scrollToBottom() {
    if (elements.chatContainer) {
        elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
    }
}

function addMessageToChat(role, content, files = []) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `flex items-start gap-3 message-enter ${role === 'user' ? 'flex-row-reverse' : ''}`;
    
    // Avatar
    const avatar = role === 'user'
        ? `<div class="w-8 h-8 rounded-full bg-gradient-to-br from-purple-400 to-pink-500 flex items-center justify-center flex-shrink-0 text-white font-bold text-sm">P</div>`
        : `<div class="w-8 h-8 rounded-full bg-gradient-to-br from-emerald-400 to-teal-500 flex items-center justify-center flex-shrink-0"><i data-lucide="cat" class="w-4 h-4 text-white"></i></div>`;
    
    let contentHtml = '';
    
    if (files.length > 0) {
        files.forEach(file => {
            if (file.type.startsWith('image/')) {
                const url = URL.createObjectURL(file);
                contentHtml += `<img src="${url}" alt="${file.name}" class="chat-image" onclick="window.open(this.src)">`;
            } else {
                contentHtml += `<div class="flex items-center gap-2 mt-2 p-2 bg-black/10 dark:bg-white/10 rounded-lg">
                    <i data-lucide="${getFileIcon(file.type)}" class="w-4 h-4"></i>
                    <span class="text-sm">${file.name}</span>
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
    
    // Add copy button for AI messages
    const copyButton = role === 'ai' ? `
        <button class="copy-message-btn absolute top-2 right-2 p-1.5 rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors opacity-0 group-hover:opacity-100"
                onclick="copyMessageContent(this)" title="Copy message">
            <i data-lucide="copy" class="w-3.5 h-3.5 text-gray-500 dark:text-gray-400"></i>
        </button>
    ` : '';
    
    messageDiv.innerHTML = `
        ${avatar}
        <div class="max-w-[85%] lg:max-w-[70%] relative group">
            <div class="${bubbleClass} px-4 py-3 shadow-sm relative">
                ${copyButton}
                ${contentHtml}
            </div>
            <span class="text-xs text-gray-400 mt-1 block ${role === 'user' ? 'text-right' : ''}">${getCurrentTime()}</span>
        </div>
    `;
    
    elements.chatContainer.appendChild(messageDiv);
    lucide.createIcons();
    
    // Add copy buttons to code blocks and tables
    if (role === 'ai') {
        addCodeBlockCopyButtons(messageDiv);
        addTableCopyButtons(messageDiv);
    }
    
    elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
}

function prependMessageToChat(role, content, files = []) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `flex items-start gap-3 message-prepend ${role === 'user' ? 'flex-row-reverse' : ''}`;
    
    const avatar = role === 'user' 
        ? `<div class="w-8 h-8 rounded-full bg-gradient-to-br from-purple-400 to-pink-500 flex items-center justify-center flex-shrink-0 text-white font-bold text-sm">P</div>`
        : `<div class="w-8 h-8 rounded-full bg-gradient-to-br from-emerald-400 to-teal-500 flex items-center justify-center flex-shrink-0"><i data-lucide="cat" class="w-4 h-4 text-white"></i></div>`;
    
    let contentHtml = '';
    
    if (content) {
        if (role === 'ai') {
            contentHtml += `<div class="markdown-content">${marked.parse(content)}</div>`;
        } else {
            contentHtml += `<p class="whitespace-pre-wrap">${escapeHtml(content)}</p>`;
        }
    }
    
    const bubbleClass = role === 'user' ? 'chat-bubble-user' : 'chat-bubble-ai';
    
    messageDiv.innerHTML = `
        ${avatar}
        <div class="max-w-[85%] lg:max-w-[70%]">
            <div class="${bubbleClass} px-4 py-3 shadow-sm">
                ${contentHtml}
            </div>
            <span class="text-xs text-gray-400 mt-1 block ${role === 'user' ? 'text-right' : ''}">${getCurrentTime()}</span>
        </div>
    `;
    
    // Insert after the scroll loader
    if (elements.scrollLoader && elements.scrollLoader.nextSibling) {
        elements.chatContainer.insertBefore(messageDiv, elements.scrollLoader.nextSibling);
    } else {
        elements.chatContainer.insertBefore(messageDiv, elements.chatContainer.firstChild);
    }
    
    lucide.createIcons();
}

function showTypingIndicator() {
    const indicator = document.createElement('div');
    indicator.id = 'typingIndicator';
    indicator.className = 'flex items-start gap-3 message-enter';
    indicator.innerHTML = `
        <div class="w-8 h-8 rounded-full bg-gradient-to-br from-emerald-400 to-teal-500 flex items-center justify-center flex-shrink-0">
            <i data-lucide="cat" class="w-4 h-4 text-white"></i>
        </div>
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
                addMessageToChat(role, msg.content);
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
            addMessageToChat('ai', 'Halo Pantronux! Saya Kuro, AI Butler setia Anda. Ada yang bisa saya bantu hari ini?');
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
        addMessageToChat('ai', 'Halo Pantronux! Saya Kuro, AI Butler setia Anda. Ada yang bisa saya bantu hari ini?');
        hasMoreMessages = false;
    }
}

async function clearChatHistory() {
    if (confirm('Are you sure you want to clear all chat history?')) {
        try {
            await authFetch(`${CONFIG.API_BASE}/history`, { method: 'DELETE' });
            elements.chatContainer.innerHTML = '';
            showNotification('Chat history cleared', 'success');
            closeSettings();
            // Reload chat with welcome message
            loadChatHistory();
        } catch (error) {
            showNotification('Failed to clear history', 'error');
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
            let logStorageHtml = '';
            if (logData.status === 'success' && logData.data) {
                const logInfo = logData.data;
                logStorageHtml = `
                    <div class="mt-4 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-xl border border-blue-200 dark:border-blue-800">
                        <div class="flex items-center gap-2 mb-2">
                            <i data-lucide="file-text" class="w-4 h-4 text-blue-600 dark:text-blue-400"></i>
                            <h4 class="font-medium text-blue-800 dark:text-blue-300">Log Storage Usage</h4>
                        </div>
                        <div class="grid grid-cols-3 gap-2 text-sm">
                            <div>
                                <p class="text-blue-600 dark:text-blue-400">Total Size</p>
                                <p class="font-medium text-blue-800 dark:text-blue-200">${logInfo.total_size_mb?.toFixed(2) || 'N/A'} MB</p>
                            </div>
                            <div>
                                <p class="text-blue-600 dark:text-blue-400">Log Files</p>
                                <p class="font-medium text-blue-800 dark:text-blue-200">${logInfo.log_files || 0}</p>
                            </div>
                            <div>
                                <p class="text-blue-600 dark:text-blue-400">Retention</p>
                                <p class="font-medium text-blue-800 dark:text-blue-200">${logInfo.retention_days || 7} days</p>
                            </div>
                        </div>
                    </div>
                `;
            }
            
            elements.systemStatusContent.innerHTML = `
                <div class="space-y-4">
                    <div class="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 font-mono text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
                        ${sysData.data}
                    </div>
                    ${logStorageHtml}
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
        
        if (data.status === 'success' && data.data) {
            const lines = data.data.split('\n').filter(l => l.trim());
            
            if (lines.length === 0 || data.data.includes('empty') || data.data.includes('does not exist')) {
                elements.filesContent.innerHTML = `
                    <div class="text-center py-8 text-gray-500">
                        <i data-lucide="folder-open" class="w-12 h-12 mx-auto mb-3 opacity-50"></i>
                        <p>No files uploaded yet</p>
                    </div>
                `;
            } else {
                let html = '';
                let currentFile = null;
                
                for (const line of lines) {
                    if (line.startsWith('📁')) {
                        continue;
                    } else if (line.startsWith('📕') || line.startsWith('📄') || line.startsWith('🖼️') || line.startsWith('💻')) {
                        if (currentFile) {
                            html += renderFileCard(currentFile);
                        }
                        currentFile = { icon: line.substring(0, 2), name: line.substring(2).trim(), path: '', size: '', modified: '' };
                    } else if (line.startsWith('Path:') && currentFile) {
                        currentFile.path = line.replace('Path:', '').trim();
                    } else if (line.startsWith('Size:') && currentFile) {
                        const parts = line.replace('Size:', '').trim().split('|');
                        currentFile.size = parts[0]?.trim() || '';
                        currentFile.modified = parts[1]?.replace('Modified:', '').trim() || '';
                    }
                }
                if (currentFile) {
                    html += renderFileCard(currentFile);
                }
                
                elements.filesContent.innerHTML = html || '<p class="text-center text-gray-500 py-8">No files found</p>';
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
    const ext = file.name.split('.').pop().toLowerCase();
    let colorClass = 'text-gray-400';
    if (['pdf'].includes(ext)) colorClass = 'text-red-400';
    else if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext)) colorClass = 'text-blue-400';
    else if (['py', 'js', 'json'].includes(ext)) colorClass = 'text-yellow-400';
    
    return `
        <div class="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 hover:bg-gray-100 dark:hover:bg-gray-600 transition-colors">
            <div class="flex items-center gap-3">
                <i data-lucide="file" class="w-5 h-5 ${colorClass}"></i>
                <div class="flex-1 min-w-0">
                    <p class="text-sm font-medium text-gray-800 dark:text-white truncate">${escapeHtml(file.name)}</p>
                    <p class="text-xs text-gray-500">${file.size} • ${file.modified}</p>
                </div>
            </div>
        </div>
    `;
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

function getCurrentTime() {
    return new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
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
    butler: '🛡️ Butler'
};

const personaAliases = {
    support: 'tactical',
    technical: 'tactical',
    casual: 'chill',
    adversarial_scholar: 'advisor',
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
        window.location.href = target;
        return;
    }
    window.history.replaceState({}, '', target);
}

function updatePersonaLabel() {
    if (elements.currentPersonaLabel) {
        elements.currentPersonaLabel.textContent = personaLabels[selectedPersona] || 'Consultant';
    }
}

async function applyPersona() {
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
        } else {
            showNotification('Failed to change persona: ' + data.message, 'error');
        }
    } catch (error) {
        showNotification('Error changing persona: ' + error.message, 'error');
    }
}

async function loadPersona() {
    const urlPersona = getPersonaFromUrl();
    const savedPersona = localStorage.getItem('kuro-persona');
    selectedPersona = normalizePersona(urlPersona || savedPersona || 'consultant');
    localStorage.setItem('kuro-persona', selectedPersona);
    setPersonaInUrl(selectedPersona, false);
    
    updatePersonaLabel();
    
    document.querySelectorAll('.persona-option').forEach(option => {
        option.classList.remove('bg-emerald-50', 'dark:bg-emerald-900/30');
        if (option.dataset.persona === selectedPersona) {
            option.classList.add('bg-emerald-50', 'dark:bg-emerald-900/30');
        }
    });
}

// ============================================
// User Info & Logout
// ============================================
function updateUserInfo() {
    const username = getUsername();
    if (elements.userInfo && username) {
        elements.userInfo.textContent = username;
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
        copyBtn.onclick = function() { copyCodeBlock(this); };
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
        copyBtn.onclick = function() { copyTable(this); };
        copyBtn.innerHTML = '<i data-lucide="copy" class="w-3.5 h-3.5 text-gray-500 dark:text-gray-400"></i><span class="text-gray-600 dark:text-gray-300">Copy</span>';
        wrapper.appendChild(copyBtn);
    });
    lucide.createIcons();
}
