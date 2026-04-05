/**
 * Kuro AI Web Dashboard - Main Application V2
 * Full functionality with chat history, vision, system status, and settings
 */

// ============================================
// Configuration
// ============================================
const CONFIG = {
    API_BASE: '/api',
    MAX_FILES: 10,
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
// State
// ============================================
let selectedFiles = [];
let isProcessing = false;
let chatHistory = [];

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
    openSidebar: document.getElementById('openSidebar'),
    closeSidebar: document.getElementById('closeSidebar'),
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
    // Navigation
    navChat: document.getElementById('navChat'),
    navSystemStatus: document.getElementById('navSystemStatus'),
    navSettings: document.getElementById('navSettings'),
    navFiles: document.getElementById('navFiles'),
    // Files Modal
    filesModal: null,
    filesContent: null,
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
    loadChatHistory();
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
    
    setupDragAndDrop();
    elements.darkModeToggle.addEventListener('click', toggleDarkMode);
    
    elements.openSidebar.addEventListener('click', () => {
        elements.sidebar.classList.remove('-translate-x-full');
        document.body.style.overflow = 'hidden';
    });
    elements.closeSidebar.addEventListener('click', closeSidebar);
    
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
}

function closeSidebar() {
    elements.sidebar.classList.add('-translate-x-full');
    document.body.style.overflow = '';
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
    
    try {
        const formData = new FormData();
        formData.append('message', message);
        filesToSend.forEach(file => formData.append('files', file));
        
        const response = await fetch(`${CONFIG.API_BASE}/chat`, {
            method: 'POST',
            body: formData,
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        removeTypingIndicator();
        addMessageToChat('ai', data.response);
        
    } catch (error) {
        console.error('Chat error:', error);
        removeTypingIndicator();
        addMessageToChat('ai', 'Maaf, Master Irfan. Terjadi kesalahan saat memproses permintaan Anda. Silakan coba lagi.');
    } finally {
        isProcessing = false;
        elements.sendBtn.disabled = false;
    }
}

function addMessageToChat(role, content, files = []) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `flex items-start gap-3 message-enter ${role === 'user' ? 'flex-row-reverse' : ''}`;
    
    // Cat icon for Kuro, initial for user
    const avatar = role === 'user' 
        ? `<div class="w-8 h-8 rounded-full bg-gradient-to-br from-purple-400 to-pink-500 flex items-center justify-center flex-shrink-0 text-white font-bold text-sm">M</div>`
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
    
    elements.chatContainer.appendChild(messageDiv);
    lucide.createIcons();
    elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
}

function showTypingIndicator() {
    const indicator = document.createElement('div');
    indicator.id = 'typingIndicator';
    indicator.className = 'flex items-start gap-3 message-enter';
    indicator.innerHTML = `
        <div class="w-8 h-8 rounded-full bg-gradient-to-br from-emerald-400 to-teal-500 flex items-center justify-center flex-shrink-0">
            <i data-lucide="cat" class="w-4 h-4 text-white"></i>
        </div>
        <div class="bg-white dark:bg-gray-800 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm border border-gray-100 dark:border-gray-700">
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
// Chat History
// ============================================
async function loadChatHistory() {
    try {
        const response = await fetch(`${CONFIG.API_BASE}/history?limit=50`);
        const data = await response.json();
        
        if (data.status === 'success' && data.history.length > 0) {
            // Clear welcome message
            elements.chatContainer.innerHTML = '';
            
            data.history.forEach(msg => {
                const role = msg.role === 'user' ? 'user' : 'ai';
                addMessageToChat(role, msg.content);
            });
        }
    } catch (error) {
        console.error('Failed to load chat history:', error);
    }
}

async function clearChatHistory() {
    if (confirm('Are you sure you want to clear all chat history?')) {
        try {
            await fetch(`${CONFIG.API_BASE}/history`, { method: 'DELETE' });
            elements.chatContainer.innerHTML = '';
            showNotification('Chat history cleared', 'success');
            closeSettings();
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
    elements.systemStatusContent.innerHTML = '<div class="flex items-center justify-center py-8"><div class="spinner"></div></div>';
    
    try {
        const response = await fetch(`${CONFIG.API_BASE}/system-status`);
        const data = await response.json();
        
        if (data.status === 'success') {
            // Format the status text
            const statusText = data.data.replace(/\n/g, '<br>');
            elements.systemStatusContent.innerHTML = `
                <div class="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 font-mono text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
                    ${data.data}
                </div>
            `;
        } else {
            elements.systemStatusContent.innerHTML = '<p class="text-red-500">Failed to load system status</p>';
        }
    } catch (error) {
        elements.systemStatusContent.innerHTML = `<p class="text-red-500">Error: ${error.message}</p>`;
    }
}

function closeSystemStatus() {
    elements.systemStatusModal.classList.add('hidden');
}

// ============================================
// Settings
// ============================================
function openSettings() {
    elements.settingsModal.classList.remove('hidden');
}

function closeSettings() {
    elements.settingsModal.classList.add('hidden');
}

// ============================================
// Uploaded Files Modal
// ============================================
async function openFilesModal() {
    // Create modal if it doesn't exist
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
        const response = await fetch(`${CONFIG.API_BASE}/list-files`);
        const data = await response.json();
        
        if (data.status === 'success' && data.data) {
            // Parse the text response
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
                        continue; // Skip header
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
