/**
 * KRC research shell controller.
 *
 * Purpose: Bind the additive /krc-shell template to existing Kuro APIs without
 * mutating destructive resources or reusing the legacy dashboard DOM.
 */
(function () {
    "use strict";

    const $ = (selector, root = document) => root.querySelector(selector);
    const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

    const state = {
        context: readContext(),
        currentView: "console",
        currentChatId: null,
        currentAssistantBubble: null,
        currentAssistantText: "",
        sessions: [],
        selectedFiles: [],
        activeFeatures: {
            web_search: false,
        },
        runtime: {
            runtimeId: "sovereign",
            modelAlias: localStorage.getItem("krc_shell_model_alias") || "gemini_fast",
            temperature: localStorage.getItem("krc_shell_temperature") || "0.7",
            topP: localStorage.getItem("krc_shell_top_p") || "1.0",
            maxTokens: localStorage.getItem("krc_shell_max_tokens") || "2048",
            variables: [{ key: "user_name", value: stateUserNameFallback() }],
        },
        playground: {
            sessionId: null,
            historySessionId: null,
            executing: false,
        },
        capabilities: null,
        toolIds: new Set(),
        messagesBySession: new Map(),
        lastOutputText: "",
        streamAbort: null,
    };

    function stateUserNameFallback() {
        const node = $("#krcShellContext");
        if (!node) return "Pantronux";
        try {
            const payload = JSON.parse(node.textContent || "{}");
            return payload.username || payload.display_name || "Pantronux";
        } catch (_) {
            return "Pantronux";
        }
    }

    function readContext() {
        const node = $("#krcShellContext");
        if (!node) return {};
        try {
            return JSON.parse(node.textContent || "{}");
        } catch (_) {
            return {};
        }
    }

    function isAdmin() {
        return Boolean(state.context && state.context.is_admin);
    }

    function unwrapApiData(payload) {
        if (payload && Object.prototype.hasOwnProperty.call(payload, "data")) {
            return payload.data;
        }
        return payload;
    }

    async function authFetch(url, options = {}) {
        const response = await fetch(url, {
            credentials: "include",
            ...options,
            headers: {
                ...(options.headers || {}),
            },
        });
        if (response.status === 401) {
            window.location.href = "/login";
            throw new Error("Authentication required");
        }
        return response;
    }

    async function fetchJson(url, options = {}) {
        const response = await authFetch(url, options);
        const text = await response.text();
        let payload = null;
        if (text) {
            try {
                payload = JSON.parse(text);
            } catch (_) {
                payload = text;
            }
        }
        if (!response.ok) {
            const message = payload?.error || payload?.detail || response.statusText || "Request failed";
            throw new Error(String(message));
        }
        return payload;
    }

    function showToast(message, type = "info") {
        const toast = $("#krcToast");
        if (!toast) return;
        toast.textContent = message;
        toast.className = `krc-toast ${type}`;
        toast.hidden = false;
        window.clearTimeout(showToast._timer);
        showToast._timer = window.setTimeout(() => {
            toast.hidden = true;
        }, 3200);
    }

    function setText(node, value) {
        if (node) node.textContent = value;
    }

    function setPreJson(node, payload) {
        if (!node) return;
        if (typeof payload === "string") {
            node.textContent = payload;
            return;
        }
        node.textContent = JSON.stringify(payload, null, 2);
    }

    function initIcons() {
        if (window.lucide && typeof window.lucide.createIcons === "function") {
            window.lucide.createIcons();
        }
    }

    function initialize() {
        initIcons();
        syncRuntimeControls();
        bindViewNavigation();
        bindSidebar();
        bindProfileMenu();
        bindComposer();
        bindRuntime();
        bindAdminModal();
        void loadCapabilities();
        void loadTools();
        void loadModels();
        void loadRuntimes();
        void loadSessions();
    }

    function bindViewNavigation() {
        $$("[data-krc-view-target]").forEach((node) => {
            node.addEventListener("click", () => {
                switchView(node.getAttribute("data-krc-view-target") || "console");
            });
        });

        $("#krcHeaderRunBtn")?.addEventListener("click", () => executeRuntimePrompt());
    }

    function switchView(view) {
        if (!["console", "playground"].includes(view)) return;
        state.currentView = view;

        $$(".krc-view").forEach((node) => {
            node.classList.toggle("is-active", node.getAttribute("data-krc-view") === view);
        });
        $$(".krc-nav-item[data-krc-view-target]").forEach((node) => {
            node.classList.toggle("is-active", node.getAttribute("data-krc-view-target") === view);
        });

        $("#krcNormalModeBtn")?.classList.toggle("is-active", view !== "playground");
        $("#krcPlaygroundModeBtn")?.classList.toggle("is-active", view === "playground");
        setText($("#krcBreadcrumbLeaf"), viewLabel(view));

        const headerRun = $("#krcHeaderRunBtn");
        if (headerRun) headerRun.hidden = view !== "playground";

        if (view === "playground") {
            void refreshPlaygroundSessionHistory();
            $("#krcPlaygroundPrompt")?.focus();
        } else if (view === "console") {
            $("#krcMessageInput")?.focus();
        }
    }

    function viewLabel(view) {
        if (view === "playground") return "Playground Runtime";
        return "Research Console";
    }

    function bindSidebar() {
        $("#krcSidebarToggle")?.addEventListener("click", () => {
            if (window.matchMedia("(max-width: 900px)").matches) {
                document.body.classList.toggle("krc-sidebar-open");
            } else {
                document.body.classList.toggle("krc-sidebar-collapsed");
            }
        });

        $("#krcHeaderSearchBtn")?.addEventListener("click", () => {
            document.body.classList.add("krc-sidebar-open");
            $("#krcSessionSearch")?.focus();
        });

        $("#krcSessionSearch")?.addEventListener("input", () => renderSessions());
        $("#krcNewConsoleBtn")?.addEventListener("click", () => {
            resetConversationSurface();
            switchView("console");
            $("#krcMessageInput")?.focus();
        });
    }

    function bindProfileMenu() {
        const button = $("#krcProfileButton");
        const menu = $("#krcProfileMenu");
        if (!button || !menu) return;

        button.addEventListener("click", (event) => {
            event.stopPropagation();
            const isOpen = !menu.hidden;
            menu.hidden = isOpen;
            button.setAttribute("aria-expanded", String(!isOpen));
        });

        document.addEventListener("click", (event) => {
            if (!menu.hidden && !menu.contains(event.target) && !button.contains(event.target)) {
                menu.hidden = true;
                button.setAttribute("aria-expanded", "false");
            }
        });

        $("#krcThemeToggle")?.addEventListener("click", () => {
            showToast("KRC shell theme is fixed for the research workspace.", "info");
        });

        $("#krcLogoutBtn")?.addEventListener("click", async () => {
            try {
                await authFetch("/api/auth/logout", { method: "POST" });
            } finally {
                window.location.href = "/login";
            }
        });
    }

    function bindComposer() {
        const form = $("#krcComposerForm");
        const input = $("#krcMessageInput");
        const fileInput = $("#krcFileInput");

        input?.addEventListener("input", () => {
            autoGrow(input);
            updateSendState();
        });
        input?.addEventListener("keydown", (event) => {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                form?.requestSubmit();
            }
        });

        $("#krcComposerMenuBtn")?.addEventListener("click", (event) => {
            event.stopPropagation();
            const menu = $("#krcComposerMenu");
            const button = $("#krcComposerMenuBtn");
            if (!menu || !button) return;
            menu.hidden = !menu.hidden;
            button.setAttribute("aria-expanded", String(!menu.hidden));
        });

        document.addEventListener("click", (event) => {
            const menu = $("#krcComposerMenu");
            const button = $("#krcComposerMenuBtn");
            if (menu && button && !menu.hidden && !menu.contains(event.target) && !button.contains(event.target)) {
                menu.hidden = true;
                button.setAttribute("aria-expanded", "false");
            }
        });

        $("#krcComposerMenu")?.addEventListener("click", (event) => {
            const item = event.target.closest("[data-krc-composer-action]");
            if (!item || item.disabled) return;
            handleComposerAction(item.getAttribute("data-krc-composer-action"));
            $("#krcComposerMenu").hidden = true;
            $("#krcComposerMenuBtn")?.setAttribute("aria-expanded", "false");
        });

        fileInput?.addEventListener("change", () => {
            state.selectedFiles = Array.from(fileInput.files || []);
            renderSelectedFiles();
            updateSendState();
        });

        $("#krcModelSelect")?.addEventListener("change", (event) => {
            state.runtime.modelAlias = event.target.value;
            localStorage.setItem("krc_shell_model_alias", state.runtime.modelAlias);
            syncRuntimeControls();
        });

        form?.addEventListener("submit", (event) => {
            event.preventDefault();
            void sendConsoleMessage();
        });

        updateSendState();
    }

    function handleComposerAction(action) {
        if (action === "attach") {
            $("#krcFileInput")?.click();
            return;
        }
        if (action === "files") {
            renderFilesDrawer();
            openDrawer("#krcFilesDrawer");
            return;
        }
        if (action === "web_search") {
            state.activeFeatures.web_search = !state.activeFeatures.web_search;
            renderComposerPills();
            return;
        }
        if (action === "playground") {
            openDrawer("#krcRuntimeDrawer");
            return;
        }
    }

    function autoGrow(textarea) {
        textarea.style.height = "auto";
        textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
    }

    function updateSendState() {
        const value = ($("#krcMessageInput")?.value || "").trim();
        const send = $("#krcSendBtn");
        if (send) send.disabled = !value && state.selectedFiles.length === 0;
    }

    function renderSelectedFiles() {
        const wrap = $("#krcSelectedFiles");
        if (!wrap) return;
        wrap.innerHTML = "";
        wrap.hidden = state.selectedFiles.length === 0;
        state.selectedFiles.forEach((file, index) => {
            const chip = document.createElement("span");
            chip.className = "krc-file-chip";
            chip.innerHTML = `<span></span><button type="button" aria-label="Remove file">&times;</button>`;
            $("span", chip).textContent = file.name;
            $("button", chip).addEventListener("click", () => {
                state.selectedFiles.splice(index, 1);
                const input = $("#krcFileInput");
                if (input) input.value = "";
                renderSelectedFiles();
                updateSendState();
            });
            wrap.appendChild(chip);
        });
    }

    function renderComposerPills() {
        const wrap = $("#krcComposerPills");
        if (!wrap) return;
        wrap.innerHTML = "";
        const active = [];
        if (state.activeFeatures.web_search) active.push(["Web Search ON", "globe"]);

        active.forEach(([label, icon]) => {
            const pill = document.createElement("span");
            pill.className = "krc-context-pill";
            pill.innerHTML = `<i data-lucide="${icon}" aria-hidden="true"></i><span></span>`;
            $("span", pill).textContent = label;
            wrap.appendChild(pill);
        });
        wrap.hidden = active.length === 0;
        initIcons();
    }

    async function sendConsoleMessage() {
        const input = $("#krcMessageInput");
        const message = (input?.value || "").trim();
        if (!message && state.selectedFiles.length === 0) return;

        try {
            if (!state.currentChatId) {
                await createSession("Research Console");
            }
            appendMessage("user", message || state.selectedFiles.map((file) => file.name).join(", "));
            if (input) {
                input.value = "";
                autoGrow(input);
            }
            const assistant = appendMessage("assistant", "");
            state.currentAssistantBubble = assistant;
            state.currentAssistantText = "";
            updateSendState();
            await streamMessage({
                message,
                output: "console",
            });
            state.selectedFiles = [];
            const fileInput = $("#krcFileInput");
            if (fileInput) fileInput.value = "";
            renderSelectedFiles();
            void loadSessions();
        } catch (error) {
            showToast(error.message || "Message failed", "error");
            if (state.currentAssistantBubble && !state.currentAssistantText) {
                state.currentAssistantBubble.textContent = `Error: ${error.message || "stream failed"}`;
            }
        }
    }

    function appendMessage(role, content) {
        const messages = $("#krcMessages");
        const welcome = $("#krcWelcomePanel");
        if (!messages) return null;
        if (welcome) welcome.remove();

        const row = document.createElement("div");
        row.className = `krc-chat-row ${role}`;
        const bubble = document.createElement("div");
        bubble.className = "krc-chat-bubble";
        bubble.textContent = content;
        row.appendChild(bubble);
        messages.appendChild(row);
        messages.scrollTop = messages.scrollHeight;
        return bubble;
    }

    async function streamMessage({ message, output }) {
        if (state.streamAbort) {
            state.streamAbort.abort();
        }
        state.streamAbort = new AbortController();

        const form = new FormData();
        form.append("message", message || "");
        form.append("persona", "phd_advisor");
        form.append("chat_id", state.currentChatId || "");
        form.append("runtime_id", state.runtime.runtimeId || "sovereign");
        form.append("model_alias", state.runtime.modelAlias || "gemini_fast");
        form.append("temperature", state.runtime.temperature || "0.7");
        form.append("web_search_enabled", state.activeFeatures.web_search ? "true" : "false");
        state.selectedFiles.forEach((file) => form.append("files", file));

        const response = await authFetch("/api/chat/stream", {
            method: "POST",
            body: form,
            signal: state.streamAbort.signal,
            headers: state.currentChatId ? { "X-Chat-Session": state.currentChatId } : {},
        });
        if (!response.ok) {
            throw new Error(`Stream failed (${response.status})`);
        }
        if (!response.body) {
            throw new Error("Streaming is not supported by this browser");
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const parts = buffer.split(/\r?\n\r?\n/);
            buffer = parts.pop() || "";
            parts.forEach((part) => processSseBlock(part, output));
        }
        if (buffer.trim()) processSseBlock(buffer, output);
    }

    function processSseBlock(block, output) {
        const lines = block.split(/\r?\n/);
        let eventType = "message";
        const dataLines = [];
        lines.forEach((line) => {
            if (line.startsWith("event:")) {
                eventType = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
                dataLines.push(line.slice(5).trimStart());
            }
        });
        if (dataLines.length === 0) return;
        const raw = dataLines.join("\n");
        if (raw === "[DONE]") return;

        let data = raw;
        try {
            data = JSON.parse(raw);
        } catch (_) {
            data = { text: raw };
        }

        if (eventType === "meta") {
            const chatId = data.chat_id || data.session_id || data.meta?.chat_id;
            if (chatId) {
                state.currentChatId = chatId;
                setText($("#krcActiveSessionLabel"), chatId);
            }
            return;
        }
        if (eventType === "chunk" || eventType === "message") {
            const text = data.text || data.chunk || data.delta || "";
            if (!text) return;
            if (output === "runtime") {
                state.lastOutputText += text;
                setText($("#krcRuntimeOutput"), state.lastOutputText);
                return;
            }
            state.currentAssistantText += text;
            if (state.currentAssistantBubble) {
                renderMarkdownInto(state.currentAssistantBubble, state.currentAssistantText);
                $("#krcMessages").scrollTop = $("#krcMessages").scrollHeight;
            }
            return;
        }
        if (eventType === "error") {
            const message = data.error || data.message || "Stream error";
            if (output === "runtime") {
                setText($("#krcRuntimeOutput"), `Error: ${message}`);
            } else if (state.currentAssistantBubble) {
                state.currentAssistantBubble.textContent = `Error: ${message}`;
            }
            return;
        }
        if (eventType === "complete" && output === "runtime") {
            $("#krcPlaygroundPulse").hidden = true;
        }
    }

    function renderMarkdownInto(node, text) {
        if (!node) return;
        if (window.marked && typeof window.marked.parse === "function") {
            node.innerHTML = window.marked.parse(text);
        } else {
            node.textContent = text;
        }
    }

    async function loadSessions() {
        try {
            const payload = await fetchJson("/api/chats?persona=phd_advisor&limit=50");
            const data = unwrapApiData(payload);
            state.sessions = Array.isArray(data) ? data : [];
            renderSessions();
        } catch (error) {
            renderSessionError(error.message || "Could not load sessions");
        }
    }

    function renderSessions() {
        const query = ($("#krcSessionSearch")?.value || "").trim().toLowerCase();
        const sessions = state.sessions.filter((session) => {
            if (!query) return true;
            return String(session.title || session.chat_id || "").toLowerCase().includes(query);
        });
        const pinned = sessions.filter((session) => Boolean(session.is_pinned));
        const recent = sessions.filter((session) => !Boolean(session.is_pinned));
        renderSessionList($("#krcPinnedSessions"), pinned, "No pinned sessions");
        renderSessionList($("#krcRecentSessions"), recent, "No recent sessions");
    }

    function renderSessionError(message) {
        renderSessionList($("#krcPinnedSessions"), [], "No pinned sessions");
        renderSessionList($("#krcRecentSessions"), [], message);
    }

    function renderSessionList(container, sessions, emptyLabel) {
        if (!container) return;
        container.innerHTML = "";
        if (!sessions.length) {
            const empty = document.createElement("div");
            empty.className = "krc-empty-row";
            empty.textContent = emptyLabel;
            container.appendChild(empty);
            return;
        }
        sessions.forEach((session) => {
            const item = document.createElement("button");
            item.type = "button";
            item.className = "krc-session-item";
            item.classList.toggle("is-active", session.chat_id === state.currentChatId);
            item.innerHTML = `<i data-lucide="message-square" aria-hidden="true"></i><span></span>`;
            $("span", item).textContent = session.title || session.chat_id || "Research Console";
            item.addEventListener("click", () => {
                void openSession(session.chat_id);
            });
            container.appendChild(item);
        });
        initIcons();
    }

    async function createSession(title) {
        const payload = await fetchJson("/api/chats", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ persona: "phd_advisor", title }),
        });
        const data = unwrapApiData(payload) || {};
        state.currentChatId = data.chat_id || data.id || state.currentChatId;
        setText($("#krcActiveSessionLabel"), state.currentChatId || "none");
        $("#krcPlaygroundPulse").hidden = false;
        void loadSessions();
        return state.currentChatId;
    }

    async function openSession(chatId) {
        if (!chatId) return;
        state.currentChatId = chatId;
        setText($("#krcActiveSessionLabel"), chatId);
        switchView("console");
        const messages = $("#krcMessages");
        if (!messages) return;
        messages.innerHTML = "";
        try {
            const payload = await fetchJson(`/api/chats/${encodeURIComponent(chatId)}/messages?limit=80`);
            const data = unwrapApiData(payload);
            const rows = Array.isArray(data?.messages) ? data.messages : Array.isArray(data) ? data : [];
            state.messagesBySession.set(chatId, rows);
            rows.forEach((message) => appendMessage(message.role === "user" ? "user" : "assistant", message.content || ""));
            renderSessions();
        } catch (error) {
            appendMessage("assistant", `Could not load session: ${error.message || "unknown error"}`);
        }
    }

    function resetConversationSurface() {
        state.currentChatId = null;
        state.currentAssistantBubble = null;
        state.currentAssistantText = "";
        setText($("#krcActiveSessionLabel"), "none");
        const messages = $("#krcMessages");
        if (!messages) return;
        messages.innerHTML = "";
        const welcome = document.createElement("div");
        welcome.id = "krcWelcomePanel";
        welcome.className = "krc-welcome-panel";
        welcome.innerHTML = `
            <div class="krc-welcome-copy">
                <span class="krc-eyebrow">Research Console</span>
                <h1>Research Console</h1>
                <p>PhD research workspace for literature, argumentation, source discipline, and advisor-guided research.</p>
            </div>
            <div class="krc-console-grid">
                <button class="krc-action-card" type="button">
                    <i data-lucide="library" aria-hidden="true"></i>
                    <span><strong>Literature Library</strong><small>Organize papers, source metadata, and research notes.</small></span>
                </button>
                <button class="krc-action-card" type="button">
                    <i data-lucide="circle-help" aria-hidden="true"></i>
                    <span><strong>Research Questions</strong><small>Track scope, contribution, and falsification criteria.</small></span>
                </button>
                <button class="krc-action-card" type="button">
                    <i data-lucide="scan-search" aria-hidden="true"></i>
                    <span><strong>Novelty Gap Board</strong><small>Separate contribution claims from unsupported speculation.</small></span>
                </button>
                <button class="krc-action-card" type="button" data-krc-view-target="playground">
                    <i data-lucide="terminal" aria-hidden="true"></i>
                    <span><strong>Playground Runtime</strong><small>Run controlled prompts for research evidence and comparison.</small></span>
                </button>
                <button class="krc-action-card" type="button" id="krcOpenRuntimeDrawerCardReset">
                    <i data-lucide="sliders-horizontal" aria-hidden="true"></i>
                    <span><strong>Runtime Drawer</strong><small>Adjust model, temperature, and research context.</small></span>
                </button>
            </div>`;
        messages.appendChild(welcome);
        bindViewNavigation();
        $("#krcOpenRuntimeDrawerCardReset")?.addEventListener("click", () => openDrawer("#krcRuntimeDrawer"));
        initIcons();
        renderSessions();
    }

    async function loadCapabilities() {
        try {
            const payload = await fetchJson("/api/capabilities");
            state.capabilities = unwrapApiData(payload) || {};
        } catch (_) {
            state.capabilities = {};
        }
        applyComposerAvailability();
    }

    async function loadTools() {
        try {
            const payload = await fetchJson("/api/tools?runtime_id=sovereign&workspace_id=default");
            const tools = unwrapApiData(payload);
            state.toolIds = new Set((Array.isArray(tools) ? tools : []).map((tool) => tool.tool_id || tool.id || tool.name).filter(Boolean));
        } catch (_) {
            state.toolIds = new Set();
        }
        applyComposerAvailability();
    }

    function applyComposerAvailability() {
        const features = state.capabilities?.features || {};
        const webSearchAvailable = Boolean(
            features.web_search?.available ||
            features.web_search?.v2_enabled ||
            state.toolIds.has("web_search") ||
            state.toolIds.has("web_search_v2")
        );
        const webButton = $('[data-krc-composer-action="web_search"]');
        if (webButton) {
            webButton.hidden = !webSearchAvailable;
            webButton.disabled = !webSearchAvailable;
            if (!webSearchAvailable) {
                state.activeFeatures.web_search = false;
                renderComposerPills();
            }
        }
    }

    async function loadModels() {
        try {
            const payload = await fetchJson("/api/models");
            const data = unwrapApiData(payload);
            const models = Array.isArray(data?.models) ? data.models : [];
            if (models.length) {
                updateModelSelect($("#krcModelSelect"), models);
                updateModelSelect($("#krcDrawerModelSelect"), models);
            }
        } catch (_) {
            syncRuntimeControls();
        }
    }

    function updateModelSelect(select, models) {
        if (!select) return;
        select.innerHTML = "";
        models.forEach((model) => {
            const option = document.createElement("option");
            option.value = model.alias || model.id || model.model_alias || model.provider || "";
            option.textContent = model.display_name || model.label || model.alias || option.value;
            if (option.value) select.appendChild(option);
        });
        if ($(`option[value="${cssEscape(state.runtime.modelAlias)}"]`, select)) {
            select.value = state.runtime.modelAlias;
        }
    }

    async function loadRuntimes() {
        try {
            const payload = await fetchJson("/api/runtimes");
            const runtimes = Array.isArray(payload) ? payload : unwrapApiData(payload);
            const select = $("#krcRuntimeSelect");
            if (!select || !Array.isArray(runtimes) || !runtimes.length) return;
            select.innerHTML = "";
            runtimes.forEach((runtime) => {
                const option = document.createElement("option");
                option.value = runtime.runtime_id || runtime.id || "";
                option.textContent = runtime.display_name || runtime.runtime_id || option.value;
                if (option.value) select.appendChild(option);
            });
            if ($(`option[value="${cssEscape(state.runtime.runtimeId)}"]`, select)) {
                select.value = state.runtime.runtimeId;
            } else {
                state.runtime.runtimeId = select.value;
            }
        } catch (_) {
            setPreJson($("#krcRuntimeOutput"), "Runtime list unavailable.");
        }
    }

    function bindRuntime() {
        $("#krcOpenRuntimeDrawer")?.addEventListener("click", () => openDrawer("#krcRuntimeDrawer"));
        $("#krcOpenRuntimeDrawerCard")?.addEventListener("click", () => openDrawer("#krcRuntimeDrawer"));
        $("#krcCloseRuntimeDrawer")?.addEventListener("click", () => closeDrawer("#krcRuntimeDrawer"));
        $("#krcCloseFilesDrawer")?.addEventListener("click", () => closeDrawer("#krcFilesDrawer"));
        $("#krcClosePlaygroundArtifactDrawer")?.addEventListener("click", () => closeDrawer("#krcPlaygroundArtifactDrawer"));

        $("#krcDrawerModelSelect")?.addEventListener("change", (event) => {
            state.runtime.modelAlias = event.target.value;
            localStorage.setItem("krc_shell_model_alias", state.runtime.modelAlias);
            syncRuntimeControls();
        });
        $("#krcTemperature")?.addEventListener("input", (event) => {
            state.runtime.temperature = event.target.value;
            localStorage.setItem("krc_shell_temperature", state.runtime.temperature);
            syncRuntimeControls();
        });
        $("#krcTopP")?.addEventListener("input", (event) => {
            state.runtime.topP = event.target.value;
            localStorage.setItem("krc_shell_top_p", state.runtime.topP);
            syncRuntimeControls();
        });
        $("#krcMaxTokens")?.addEventListener("input", (event) => {
            state.runtime.maxTokens = event.target.value;
            localStorage.setItem("krc_shell_max_tokens", state.runtime.maxTokens);
            syncRuntimeControls();
        });
        $("#krcAddRuntimeVariable")?.addEventListener("click", () => {
            state.runtime.variables.push({ key: "", value: "" });
            renderRuntimeVariables();
        });
        $("#krcApplyRuntimeSettings")?.addEventListener("click", () => {
            setPreJson($("#krcDrawerOutput"), {
                model_alias: state.runtime.modelAlias,
                temperature: Number(state.runtime.temperature),
                top_p: Number(state.runtime.topP),
                max_tokens: Number(state.runtime.maxTokens),
                system_prompt: $("#krcRuntimeSystemPrompt")?.value || "",
                variables: runtimeVariablesPayload(),
                status: "applied locally",
            });
            showToast("Runtime settings applied locally.", "success");
        });
        $("#krcDrawerRun")?.addEventListener("click", () => executeRuntimePrompt());
        $("#krcPlaygroundCreateSession")?.addEventListener("click", () => playgroundCreateSession());
        $("#krcPlaygroundReconnectLatest")?.addEventListener("click", () => playgroundReconnectLatestSession());
        $("#krcPlaygroundUseCustomSession")?.addEventListener("click", () => playgroundUseCustomSessionId());
        $("#krcPlaygroundExecute")?.addEventListener("click", () => executeRuntimePrompt());
        $("#krcPlaygroundHealth")?.addEventListener("click", () => playgroundHealth());
        $("#krcPlaygroundProviders")?.addEventListener("click", () => playgroundProviders());
        $("#krcPlaygroundListTraces")?.addEventListener("click", () => playgroundListTraces());
        $("#krcPlaygroundLoadView")?.addEventListener("click", () => playgroundLoadForensicView());
        $("#krcPlaygroundIntegrityOverviewBtn")?.addEventListener("click", () => playgroundLoadIntegrityOverview());
        $("#krcPlaygroundVerifySnapshot")?.addEventListener("click", () => playgroundVerifyLatestSnapshot());
        $("#krcPlaygroundExportBundle")?.addEventListener("click", () => playgroundExportForensicBundle());
        $("#krcPlaygroundLineage")?.addEventListener("click", () => playgroundLoadLineage());
        $("#krcCopyOutput")?.addEventListener("click", () => copyText($("#krcRuntimeOutput")?.textContent || ""));
        $("#krcDownloadOutput")?.addEventListener("click", () => downloadPlaygroundOutput());
        $("#krcAnalyzeOutputInKs")?.addEventListener("click", () => analyzePlaygroundInKuroStack({ preferSelectedSession: false }));
        $("#krcPlaygroundDownloadSessionArtifact")?.addEventListener("click", () => downloadSelectedSessionArtifact());
        $("#krcPlaygroundAnalyzeSessionInKs")?.addEventListener("click", () => analyzePlaygroundInKuroStack({ preferSelectedSession: true }));
        renderRuntimeVariables();
    }

    function syncRuntimeControls() {
        const temperature = $("#krcTemperature");
        const temperatureValue = $("#krcTemperatureValue");
        const topP = $("#krcTopP");
        const topPValue = $("#krcTopPValue");
        const maxTokens = $("#krcMaxTokens");
        const maxTokensValue = $("#krcMaxTokensValue");
        const modelSelect = $("#krcModelSelect");
        const drawerModelSelect = $("#krcDrawerModelSelect");
        if (temperature) temperature.value = state.runtime.temperature;
        setText(temperatureValue, state.runtime.temperature);
        if (topP) topP.value = state.runtime.topP;
        setText(topPValue, state.runtime.topP);
        if (maxTokens) maxTokens.value = state.runtime.maxTokens;
        setText(maxTokensValue, state.runtime.maxTokens);
        if (modelSelect) modelSelect.value = state.runtime.modelAlias;
        if (drawerModelSelect) drawerModelSelect.value = state.runtime.modelAlias;
    }

    async function executeRuntimePrompt() {
        if (state.playground.executing) return;
        const prompt = ($("#krcPlaygroundPrompt")?.value || "").trim();
        const selectedProviders = selectedPlaygroundProviders();
        if (!prompt) {
            showToast("Enter a runtime prompt first.", "error");
            $("#krcPlaygroundPrompt")?.focus();
            return;
        }
        if (!state.playground.sessionId) {
            playgroundPrint("No active Playground session. Create or reconnect a session first.");
            showToast("Create or reconnect a Playground session first.", "error");
            return;
        }
        if (!selectedProviders.length) {
            playgroundPrint("No provider selected. Select at least one provider.");
            showToast("Select at least one provider.", "error");
            return;
        }
        setPlaygroundExecuteLoading(true);
        $("#krcPlaygroundPulse").hidden = false;
        try {
            const comparative = selectedProviders.length > 1;
            const endpoint = comparative ? "/api/playground/comparative-executions" : "/api/playground/executions";
            const metadata = {
                source: "krc_shell",
                model_alias: state.runtime.modelAlias,
                temperature: Number(state.runtime.temperature),
                top_p: Number(state.runtime.topP),
                max_tokens: Number(state.runtime.maxTokens),
                system_prompt: $("#krcRuntimeSystemPrompt")?.value || "",
                variables: runtimeVariablesPayload(),
            };
            const payload = comparative ? {
                session_id: state.playground.sessionId,
                provider_ids: selectedProviders,
                prompt,
                metadata,
            } : {
                session_id: state.playground.sessionId,
                provider_id: selectedProviders[0],
                prompt,
                metadata,
            };
            playgroundPrint({
                mode: comparative ? "comparative" : "single",
                status: "executing",
                selected_providers: selectedProviders,
            });
            const data = await fetchJson(endpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            playgroundPrint({
                mode: comparative ? "comparative" : "single",
                selected_providers: selectedProviders,
                response: data,
            });
            state.playground.historySessionId = state.playground.sessionId;
            await refreshPlaygroundSessionHistory();
            await loadPlaygroundSessionHistoryDetail(state.playground.sessionId);
        } catch (error) {
            playgroundPrint(`Execution failed: ${error.message || "runtime execution failed"}`);
            showToast(error.message || "Runtime execution failed", "error");
        } finally {
            $("#krcPlaygroundPulse").hidden = true;
            setPlaygroundExecuteLoading(false);
        }
    }

    function selectedPlaygroundProviders() {
        return $$("#krcPlaygroundView .krc-provider-checklist input:checked").map((node) => node.value);
    }

    function setPlaygroundExecuteLoading(isLoading) {
        state.playground.executing = isLoading;
        const button = $("#krcPlaygroundExecute");
        if (button) {
            button.disabled = isLoading;
            button.classList.toggle("is-loading", isLoading);
        }
        setText($("#krcPlaygroundExecuteLabel"), isLoading ? "Executing..." : "Execute");
    }

    function playgroundPrint(payload) {
        const output = $("#krcRuntimeOutput");
        if (!output) return;
        const text = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
        output.textContent = text;
        state.lastOutputText = text;
        setText($("#krcDrawerOutput"), text);
    }

    function runtimeVariablesPayload() {
        return state.runtime.variables
            .map((row) => ({ key: String(row.key || "").trim(), value: String(row.value || "") }))
            .filter((row) => row.key);
    }

    function renderRuntimeVariables() {
        const root = $("#krcRuntimeVariables");
        if (!root) return;
        root.innerHTML = "";
        if (!state.runtime.variables.length) {
            root.innerHTML = '<p class="krc-empty-row">No variables defined.</p>';
            return;
        }
        state.runtime.variables.forEach((row, index) => {
            const item = document.createElement("div");
            item.className = "krc-runtime-var-row";
            item.innerHTML = `
                <input type="text" placeholder="Key" value="${escapeHtml(row.key || "")}" data-krc-var-key="${index}">
                <input type="text" placeholder="Value" value="${escapeHtml(row.value || "")}" data-krc-var-value="${index}">
                <button class="krc-icon-btn" type="button" title="Remove variable" data-krc-var-remove="${index}">
                    <i data-lucide="x" aria-hidden="true"></i>
                </button>
            `;
            root.appendChild(item);
        });
        $$("[data-krc-var-key]", root).forEach((input) => {
            input.addEventListener("input", () => {
                const index = Number(input.getAttribute("data-krc-var-key"));
                if (state.runtime.variables[index]) state.runtime.variables[index].key = input.value;
            });
        });
        $$("[data-krc-var-value]", root).forEach((input) => {
            input.addEventListener("input", () => {
                const index = Number(input.getAttribute("data-krc-var-value"));
                if (state.runtime.variables[index]) state.runtime.variables[index].value = input.value;
            });
        });
        $$("[data-krc-var-remove]", root).forEach((button) => {
            button.addEventListener("click", () => {
                const index = Number(button.getAttribute("data-krc-var-remove"));
                state.runtime.variables.splice(index, 1);
                renderRuntimeVariables();
            });
        });
        initIcons();
    }

    function resolvePlaygroundSessionId(payload) {
        if (!payload || typeof payload !== "object") return null;
        if (typeof payload.session_id === "string" && payload.session_id) return payload.session_id;
        if (payload.data && typeof payload.data.session_id === "string") return payload.data.session_id;
        return null;
    }

    function setActivePlaygroundSession(sessionId) {
        state.playground.sessionId = sessionId || null;
        setText($("#krcPlaygroundSessionId"), state.playground.sessionId || "-");
    }

    async function fetchPlaygroundJson(path, options = {}) {
        return fetchJson(path, options);
    }

    async function playgroundCreateSession(customSessionId = null) {
        const mode = $("#krcPlaygroundSessionMode")?.value || "research";
        const sid = String(customSessionId || "").trim();
        const payload = { mode };
        if (sid) payload.session_id = sid;
        try {
            const data = await fetchPlaygroundJson("/api/playground/sessions", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const sessionId = resolvePlaygroundSessionId(data);
            if (!sessionId) {
                playgroundPrint("Create session succeeded but response did not include session_id.");
                return;
            }
            setActivePlaygroundSession(sessionId);
            state.playground.historySessionId = sessionId;
            if (!customSessionId && $("#krcPlaygroundCustomSessionId")) $("#krcPlaygroundCustomSessionId").value = "";
            playgroundPrint(data);
            await refreshPlaygroundSessionHistory();
            await loadPlaygroundSessionHistoryDetail(sessionId);
            showToast("Playground session created.", "success");
        } catch (error) {
            playgroundPrint(`Create session failed: ${error.message}`);
            showToast(error.message || "Create session failed", "error");
        }
    }

    async function playgroundReconnectLatestSession() {
        try {
            const data = await fetchPlaygroundJson("/api/playground/sessions/latest");
            const sessionId = resolvePlaygroundSessionId(data);
            if (!sessionId) {
                playgroundPrint("Latest session payload missing session_id.");
                return;
            }
            setActivePlaygroundSession(sessionId);
            state.playground.historySessionId = sessionId;
            if ($("#krcPlaygroundCustomSessionId")) $("#krcPlaygroundCustomSessionId").value = sessionId;
            playgroundPrint({ reconnected_latest: data });
            await refreshPlaygroundSessionHistory();
            await loadPlaygroundSessionHistoryDetail(sessionId);
            showToast("Latest Playground session connected.", "success");
        } catch (error) {
            playgroundPrint(`Reconnect latest failed: ${error.message}`);
            showToast(error.message || "Reconnect latest failed", "error");
        }
    }

    async function playgroundUseCustomSessionId() {
        const customId = ($("#krcPlaygroundCustomSessionId")?.value || "").trim();
        if (!customId) {
            playgroundPrint("Custom Session-ID is empty.");
            return;
        }
        if (!/^[A-Za-z0-9._:-]{8,128}$/.test(customId)) {
            playgroundPrint("Custom Session-ID must be 8-128 safe characters.");
            return;
        }
        await playgroundCreateSession(customId);
    }

    async function refreshPlaygroundSessionHistory() {
        const list = $("#krcPlaygroundHistoryList");
        if (!list) return;
        try {
            const data = await fetchPlaygroundJson("/api/playground/sessions?limit=20");
            renderPlaygroundHistoryList(data.sessions || []);
        } catch (error) {
            list.innerHTML = `<p class="krc-empty-row error">${escapeHtml(error.message || "Could not load Playground sessions.")}</p>`;
        }
    }

    function renderPlaygroundHistoryList(sessions) {
        const list = $("#krcPlaygroundHistoryList");
        if (!list) return;
        if (!Array.isArray(sessions) || !sessions.length) {
            list.innerHTML = '<p class="krc-empty-row">(no sessions)</p>';
            return;
        }
        list.innerHTML = sessions.map((session) => {
            const sid = session.session_id || session.id || "";
            const mode = session.mode || "unknown";
            const created = session.created_at_utc || "-";
            const integrity = String(session.session_integrity_status || "unverified").toUpperCase();
            const active = sid === state.playground.sessionId ? " is-active" : "";
            return `
                <button class="krc-history-row${active}" type="button" data-krc-playground-session="${escapeHtml(sid)}">
                    <strong>${escapeHtml(sid || "-")}</strong>
                    <span>${escapeHtml(mode)} • ${escapeHtml(created)}</span>
                    <em>Integrity: ${escapeHtml(integrity)}</em>
                </button>
            `;
        }).join("");
        $$("[data-krc-playground-session]", list).forEach((button) => {
            button.addEventListener("click", async () => {
                const sid = button.getAttribute("data-krc-playground-session");
                if (!sid) return;
                setActivePlaygroundSession(sid);
                state.playground.historySessionId = sid;
                await loadPlaygroundSessionHistoryDetail(sid);
                renderPlaygroundHistoryList(sessions);
            });
        });
    }

    function buildExecutionArtifactButtons(sessionId, executionId, trustRow = null) {
        const chips = [];
        if (trustRow) {
            chips.push(`<span>Integrity: ${escapeHtml(trustRow.integrity_status || "UNVERIFIED")}</span>`);
            chips.push(`<span>Snapshot: ${escapeHtml(trustRow.snapshot_state || "UNVERIFIED")}</span>`);
            chips.push(`<span>Transform: ${escapeHtml(trustRow.transformation_integrity_state || "UNKNOWN")}</span>`);
            if (trustRow.schema_drift_detected) chips.push("<span>Schema Drift</span>");
        }
        return `
            <div class="krc-trust-chips">${chips.join("")}</div>
            <div class="krc-execution-actions">
                <button class="krc-secondary-btn compact" type="button" data-krc-open-integrity="${escapeHtml(executionId)}" data-session-id="${escapeHtml(sessionId)}">Trust Detail</button>
                <button class="krc-secondary-btn compact" type="button" data-krc-download-artifact="execution_raw" data-execution-id="${escapeHtml(executionId)}" data-session-id="${escapeHtml(sessionId)}">Raw JSON</button>
                <button class="krc-secondary-btn compact" type="button" data-krc-download-artifact="execution_trace" data-execution-id="${escapeHtml(executionId)}" data-session-id="${escapeHtml(sessionId)}">Trace JSON</button>
            </div>
        `;
    }

    async function loadPlaygroundSessionHistoryDetail(sessionId) {
        const detail = $("#krcPlaygroundHistoryDetail");
        const meta = $("#krcPlaygroundHistoryMeta");
        const executionsRoot = $("#krcPlaygroundHistoryExecutions");
        if (!detail || !meta || !executionsRoot) return;
        detail.hidden = false;
        meta.innerHTML = '<p class="krc-empty-row">Loading history...</p>';
        executionsRoot.innerHTML = "";
        try {
            const data = await fetchPlaygroundJson(`/api/playground/sessions/${encodeURIComponent(sessionId)}/history`);
            const session = data.session || {};
            const executions = Array.isArray(data.executions) ? data.executions : [];
            const integrityRows = Array.isArray(data.execution_integrity_rows) ? data.execution_integrity_rows : [];
            const trustByExecution = new Map(integrityRows.map((row) => [row.execution_id, row]));
            meta.innerHTML = `
                <p><strong>Session:</strong> ${escapeHtml(session.session_id || sessionId || "-")}</p>
                <p><strong>Mode:</strong> ${escapeHtml(session.mode || "-")} • <strong>Status:</strong> ${escapeHtml(session.status || "-")}</p>
                <p><strong>Created:</strong> ${escapeHtml(session.created_at_utc || "-")}</p>
                <p><strong>Traces:</strong> ${escapeHtml(String((data.traces_summary || {}).count || 0))} • <strong>Reports:</strong> ${escapeHtml(String((data.reports || []).length || 0))}</p>
                <p><strong>Session Integrity:</strong> ${escapeHtml(session.session_integrity_status || "unverified")}</p>
            `;
            renderIntegrityOverview(data.integrity_overview);
            if (!executions.length) {
                executionsRoot.innerHTML = '<p class="krc-empty-row">No executions yet.</p>';
                return;
            }
            executionsRoot.innerHTML = executions.map((row) => {
                const executionId = row.execution_id || "";
                return `
                    <div class="krc-execution-row">
                        <strong>${escapeHtml(executionId || "-")}</strong>
                        <span>${escapeHtml(row.provider_id || "-")} • ${escapeHtml(row.model_id || "-")}</span>
                        <small>${escapeHtml(row.created_at_utc || "-")} • latency: ${escapeHtml(String(row.latency_ms || "-"))} ms</small>
                        ${buildExecutionArtifactButtons(sessionId, executionId, trustByExecution.get(executionId))}
                    </div>
                `;
            }).join("");
            installPlaygroundArtifactHandlers(executionsRoot);
        } catch (error) {
            meta.innerHTML = `<p class="krc-empty-row error">${escapeHtml(error.message || "History load failed.")}</p>`;
        }
    }

    function renderIntegrityOverview(overview) {
        const root = $("#krcPlaygroundIntegrityOverview");
        if (!root) return;
        const pre = $("pre", root);
        if (!pre) return;
        if (!overview) {
            pre.textContent = "No integrity overview loaded.";
            return;
        }
        const metrics = overview.metrics || {};
        const alerts = Array.isArray(overview.alerts) ? overview.alerts : [];
        const alertText = alerts.length ? alerts.map((alert) => `${alert.severity}: ${alert.message}`).join(" | ") : "No active integrity alerts.";
        pre.textContent = [
            `verified artifacts: ${metrics.verified_artifacts || 0}`,
            `integrity failures: ${metrics.integrity_failures || 0}`,
            `schema drift events: ${metrics.schema_drift_events || 0}`,
            `orphaned traces: ${metrics.orphaned_traces || 0}`,
            `snapshot mismatches: ${metrics.snapshot_mismatches || 0}`,
            `unresolved mappings: ${metrics.unresolved_canonical_mappings || 0}`,
            `corrupted exports: ${metrics.corrupted_exports || 0}`,
            alertText,
        ].join("\n");
    }

    function installPlaygroundArtifactHandlers(scope) {
        $$("[data-krc-download-artifact]", scope).forEach((button) => {
            button.addEventListener("click", async () => {
                const sessionId = button.getAttribute("data-session-id");
                const executionId = button.getAttribute("data-execution-id");
                const type = button.getAttribute("data-krc-download-artifact");
                if (!sessionId || !type) return;
                await downloadPlaygroundArtifactJson(sessionId, type, executionId, button);
            });
        });
        $$("[data-krc-open-integrity]", scope).forEach((button) => {
            button.addEventListener("click", async () => {
                const sessionId = button.getAttribute("data-session-id");
                const executionId = button.getAttribute("data-krc-open-integrity");
                if (!sessionId || !executionId) return;
                await playgroundOpenIntegrityDetail(sessionId, executionId);
            });
        });
    }

    async function playgroundHealth() {
        try {
            playgroundPrint(await fetchPlaygroundJson("/api/playground/health"));
        } catch (error) {
            playgroundPrint(`Health check failed: ${error.message}`);
        }
    }

    async function playgroundProviders() {
        try {
            playgroundPrint(await fetchPlaygroundJson("/api/playground/providers"));
        } catch (error) {
            playgroundPrint(`Providers check failed: ${error.message}`);
        }
    }

    async function playgroundListTraces() {
        if (!state.playground.sessionId) {
            playgroundPrint("No active Playground session. Create session first.");
            return;
        }
        try {
            const data = await fetchPlaygroundJson(`/api/playground/sessions/${encodeURIComponent(state.playground.sessionId)}/traces`);
            playgroundPrint(data);
            state.playground.historySessionId = state.playground.sessionId;
            await refreshPlaygroundSessionHistory();
            await loadPlaygroundSessionHistoryDetail(state.playground.sessionId);
        } catch (error) {
            playgroundPrint(`List traces failed: ${error.message}`);
        }
    }

    async function playgroundLoadForensicView() {
        const sessionId = state.playground.historySessionId || state.playground.sessionId;
        if (!sessionId) {
            playgroundPrint("No active Playground session. Create session first.");
            return;
        }
        const view = ($("#krcPlaygroundForensicView")?.value || "summary").trim();
        const workflowMode = ($("#krcPlaygroundWorkflowMode")?.value || "quick").trim();
        try {
            const data = await fetchPlaygroundJson(
                `/api/playground/sessions/${encodeURIComponent(sessionId)}/forensic-view?view=${encodeURIComponent(view)}&workflow_mode=${encodeURIComponent(workflowMode)}`
            );
            playgroundPrint(data);
        } catch (error) {
            playgroundPrint(`Forensic view failed: ${error.message}`);
        }
    }

    async function playgroundLoadIntegrityOverview() {
        const sessionId = state.playground.historySessionId || state.playground.sessionId;
        if (!sessionId) {
            playgroundPrint("No active Playground session. Create session first.");
            return;
        }
        const workflowMode = ($("#krcPlaygroundWorkflowMode")?.value || "quick").trim();
        try {
            const data = await fetchPlaygroundJson(
                `/api/playground/sessions/${encodeURIComponent(sessionId)}/integrity-overview?workflow_mode=${encodeURIComponent(workflowMode)}`
            );
            renderIntegrityOverview(data);
            playgroundPrint({ integrity_overview: data });
        } catch (error) {
            playgroundPrint(`Integrity overview failed: ${error.message}`);
        }
    }

    async function playgroundVerifyLatestSnapshot() {
        const sessionId = state.playground.historySessionId || state.playground.sessionId;
        if (!sessionId) {
            playgroundPrint("No active Playground session. Create session first.");
            return;
        }
        try {
            const history = await fetchPlaygroundJson(`/api/playground/sessions/${encodeURIComponent(sessionId)}/history`);
            const snapshots = (history.evidence_snapshots || {}).items || [];
            if (!Array.isArray(snapshots) || !snapshots.length) {
                playgroundPrint("No snapshot found for this session.");
                return;
            }
            const snapshotId = snapshots[0].snapshot_id;
            const data = await fetchPlaygroundJson(`/api/playground/snapshots/${encodeURIComponent(snapshotId)}/verify`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: sessionId }),
            });
            playgroundPrint({ snapshot_verification: data });
            await loadPlaygroundSessionHistoryDetail(sessionId);
        } catch (error) {
            playgroundPrint(`Snapshot verification failed: ${error.message}`);
        }
    }

    async function playgroundExportForensicBundle() {
        const sessionId = state.playground.historySessionId || state.playground.sessionId;
        if (!sessionId) {
            playgroundPrint("No active Playground session. Create session first.");
            return;
        }
        try {
            const data = await fetchPlaygroundJson(`/api/playground/sessions/${encodeURIComponent(sessionId)}/exports/forensic-bundle`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({}),
            });
            playgroundPrint({ forensic_bundle: data });
        } catch (error) {
            playgroundPrint(`Forensic bundle export failed: ${error.message}`);
        }
    }

    async function playgroundLoadLineage() {
        const sessionId = state.playground.historySessionId || state.playground.sessionId;
        if (!sessionId) {
            playgroundPrint("No active Playground session. Create session first.");
            return;
        }
        try {
            const data = await fetchPlaygroundJson(`/api/playground/sessions/${encodeURIComponent(sessionId)}/lineage`);
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
            setPreJson($("#krcPlaygroundArtifactAcquisition"), data.acquisition_metadata || {});
            setPreJson($("#krcPlaygroundArtifactIntegrity"), data.integrity_metadata || {});
            setPreJson($("#krcPlaygroundArtifactTransformation"), data.transformation_metadata || {});
            setPreJson($("#krcPlaygroundArtifactProvenance"), data.provenance_metadata || {});
            openDrawer("#krcPlaygroundArtifactDrawer");
        } catch (error) {
            playgroundPrint(`Integrity detail failed: ${error.message}`);
        }
    }

    async function downloadPlaygroundArtifactJson(sessionId, type, executionId = null, button = null) {
        const query = new URLSearchParams({ type });
        if (executionId) query.set("execution_id", executionId);
        const originalText = button?.textContent;
        if (button) button.textContent = "Downloading...";
        try {
            const response = await authFetch(`/api/playground/sessions/${encodeURIComponent(sessionId)}/artifacts/json?${query.toString()}`);
            if (!response.ok) {
                const payload = await response.text();
                throw new Error(payload || `HTTP ${response.status}`);
            }
            const blob = await response.blob();
            const header = response.headers.get("content-disposition") || "";
            const match = header.match(/filename="?([^";]+)"?/i);
            const filename = match ? match[1] : `playground-${type}.json`;
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
        } catch (error) {
            playgroundPrint(`Artifact download failed: ${error.message}`);
        } finally {
            if (button && originalText) button.textContent = originalText;
        }
    }

    async function fetchPlaygroundArtifactText(sessionId, type = "session", executionId = null) {
        const query = new URLSearchParams({ type });
        if (executionId) query.set("execution_id", executionId);
        const response = await authFetch(`/api/playground/sessions/${encodeURIComponent(sessionId)}/artifacts/json?${query.toString()}`);
        if (!response.ok) {
            const payload = await response.text();
            throw new Error(payload || `HTTP ${response.status}`);
        }
        return response.text();
    }

    async function downloadSelectedSessionArtifact() {
        const sessionId = state.playground.historySessionId || state.playground.sessionId;
        if (!sessionId) {
            playgroundPrint("No session selected for artifact download.");
            return;
        }
        await downloadPlaygroundArtifactJson(sessionId, "session", null, $("#krcPlaygroundDownloadSessionArtifact"));
    }

    function getPlaygroundOutputText() {
        return ($("#krcRuntimeOutput")?.textContent || "").trim();
    }

    function downloadPlaygroundOutput() {
        const text = getPlaygroundOutputText();
        if (!text || text.startsWith("No Playground output")) {
            showToast("No Playground output to download.", "error");
            return;
        }
        const stamp = new Date().toISOString().replace(/[:.]/g, "-");
        downloadText(`playground-output-${stamp}.json`, text);
    }

    function resolveKuroStackChatUrl(chatId) {
        const protocol = window.location.protocol === "http:" ? "http:" : "https:";
        const host = window.location.hostname || "127.0.0.1";
        return `${protocol}//${host}:9443/c/${encodeURIComponent(chatId)}`;
    }

    function getPlaygroundAnalysisMode() {
        const value = ($("#krcPlaygroundAnalysisMode")?.value || "auto").trim();
        const allowed = new Set(["auto", "summary", "integrity", "forensic", "divergence", "ontology", "lineage"]);
        return allowed.has(value) ? value : "auto";
    }

    function getPlaygroundWorkflowMode() {
        const value = ($("#krcPlaygroundWorkflowMode")?.value || "quick").trim();
        const allowed = new Set(["quick", "deep", "academic"]);
        return allowed.has(value) ? value : "quick";
    }

    function resolvePlaygroundHandoffRequest(preferSelectedSession) {
        const sessionId = (preferSelectedSession ? state.playground.historySessionId : null) || state.playground.historySessionId || state.playground.sessionId;
        const requestBody = {
            analysis_mode: getPlaygroundAnalysisMode(),
            workflow_mode: getPlaygroundWorkflowMode(),
        };
        if (sessionId) {
            return {
                ...requestBody,
                session_id: sessionId,
                source_label: "KRC Playground session artifact",
            };
        }
        const outputText = getPlaygroundOutputText();
        if (!outputText || outputText.startsWith("No Playground output")) {
            throw new Error("No Playground session or output available to analyze.");
        }
        return {
            ...requestBody,
            source_label: "current Playground Output panel",
            output_text: outputText,
        };
    }

    async function analyzePlaygroundInKuroStack({ preferSelectedSession = false } = {}) {
        const button = preferSelectedSession ? $("#krcPlaygroundAnalyzeSessionInKs") : $("#krcAnalyzeOutputInKs");
        const originalText = button?.textContent || "Analyze in KS";
        if (button) {
            button.disabled = true;
            button.textContent = "Creating...";
        }
        try {
            const payload = await fetchJson("/api/integrations/kuro-stack/analyze-playground", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(resolvePlaygroundHandoffRequest(preferSelectedSession)),
            });
            if (payload?.chat_id) {
                window.open(resolveKuroStackChatUrl(payload.chat_id), "_blank", "noopener,noreferrer");
            }
            playgroundPrint({ kuro_stack_analysis: payload });
            showToast("Kuro Stack analysis chat created.", "success");
        } catch (error) {
            playgroundPrint(`Analyze in KS failed: ${error.message}`);
            showToast(error.message || "Analyze in KS failed", "error");
        } finally {
            if (button) {
                setTimeout(() => {
                    button.disabled = false;
                    button.textContent = originalText;
                }, 1200);
            }
        }
    }

    function openDrawer(selector) {
        const drawer = $(selector);
        if (!drawer) return;
        drawer.classList.add("is-open");
        drawer.setAttribute("aria-hidden", "false");
    }

    function closeDrawer(selector) {
        const drawer = $(selector);
        if (!drawer) return;
        drawer.classList.remove("is-open");
        drawer.setAttribute("aria-hidden", "true");
    }

    function renderFilesDrawer() {
        const list = $("#krcFilesList");
        if (!list) return;
        const files = [];
        state.selectedFiles.forEach((file) => files.push({ name: file.name, source: "selected" }));
        const rows = state.messagesBySession.get(state.currentChatId) || [];
        rows.forEach((message) => {
            (message.attachments || []).forEach((attachment) => {
                files.push({
                    name: attachment.original_filename || attachment.stored_filename || "attachment",
                    source: attachment.stored_path || "history",
                    href: attachment.stored_path,
                });
            });
        });

        list.innerHTML = "";
        if (!files.length) {
            list.textContent = "No files loaded for this shell session.";
            return;
        }
        files.forEach((file) => {
            const row = document.createElement(file.href ? "a" : "div");
            row.className = "krc-file-row";
            if (file.href) {
                row.href = file.href;
                row.target = "_blank";
                row.rel = "noreferrer";
            }
            row.innerHTML = `<i data-lucide="file" aria-hidden="true"></i><span></span>`;
            $("span", row).textContent = file.name;
            list.appendChild(row);
        });
        initIcons();
    }

    function bindAdminModal() {
        if (!isAdmin()) return;
        $("#krcOpenAdminSettings")?.addEventListener("click", () => {
            const modal = $("#krcAdminSettingsModal");
            if (modal) modal.hidden = false;
            void loadAdminTab("general");
        });
        $("#krcCloseAdminSettings")?.addEventListener("click", () => {
            const modal = $("#krcAdminSettingsModal");
            if (modal) modal.hidden = true;
        });
        $$("[data-krc-close-admin]").forEach((node) => {
            node.addEventListener("click", () => {
                const modal = $("#krcAdminSettingsModal");
                if (modal) modal.hidden = true;
            });
        });
        $$("[data-krc-admin-tab]").forEach((button) => {
            button.addEventListener("click", () => {
                $$("[data-krc-admin-tab]").forEach((node) => node.classList.remove("is-active"));
                button.classList.add("is-active");
                void loadAdminTab(button.getAttribute("data-krc-admin-tab"));
            });
        });
    }

    async function loadAdminTab(tab) {
        const titleMap = {
            general: ["General Settings", "/api/system-status"],
            models: ["Models", "/api/models"],
            runtime: ["Runtime", "/api/admin/runtime-health"],
            security: ["Security", "/api/admin/enterprise-flags"],
            audit: ["Audit Log", "/api/admin/krc/profile"],
        };
        const [title, endpoint] = titleMap[tab] || titleMap.general;
        const panel = $("#krcAdminPanel");
        if (!panel) return;
        panel.innerHTML = `<h3></h3><p>Read-only operator snapshot from ${endpoint}.</p><pre id="krcAdminOutput">Loading...</pre>`;
        $("h3", panel).textContent = title;
        try {
            const payload = await fetchJson(endpoint);
            setPreJson($("#krcAdminOutput"), payload);
        } catch (error) {
            setPreJson($("#krcAdminOutput"), { error: error.message || "admin snapshot failed", endpoint });
        }
    }

    async function copyText(text) {
        try {
            await navigator.clipboard.writeText(text);
            showToast("Copied.", "success");
        } catch (_) {
            showToast("Copy failed.", "error");
        }
    }

    function downloadText(filename, text) {
        const blob = new Blob([text], { type: "application/json;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function cssEscape(value) {
        if (window.CSS && typeof window.CSS.escape === "function") {
            return window.CSS.escape(value);
        }
        return String(value).replace(/"/g, '\\"');
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize);
    } else {
        initialize();
    }
})();
