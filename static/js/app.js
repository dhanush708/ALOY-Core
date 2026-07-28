// ==========================================================================
// ALOY Frontend SPA Logic
// ==========================================================================

document.addEventListener("DOMContentLoaded", () => {
    // State management
    let activeConversationId = null;
    let currentTheme = localStorage.getItem("aloy-theme") || "dark";
    let leftSidebarCollapsed = false;
    let rightSidebarCollapsed = true;
    let allSessionsList = [];
    let collapsedGroups = { today: false, yesterday: false, lastWeek: false, older: false };

    // DOM Elements
    const body = document.body;
    const navItems = document.querySelectorAll(".nav-item");
    const stageViews = document.querySelectorAll(".stage-view");
    const viewTitle = document.getElementById("view-title");
    const newChatBtn = document.getElementById("new-chat-btn");
    const historyList = document.getElementById("history-list");
    const chatForm = document.getElementById("chat-form");
    const chatInput = document.getElementById("chat-input");
    const chatMessages = document.getElementById("chat-messages");
    
    // Sidebar toggles
    const sidebarToggleLeft = document.getElementById("sidebar-toggle-left");
    const sidebarToggleRight = document.getElementById("sidebar-toggle-right");
    const sidebarLeft = document.getElementById("sidebar-left");
    const sidebarRight = document.getElementById("sidebar-right");
    
    // Details panel fields
    const activeModelEl = document.getElementById("active-model");
    const activeIntentEl = document.getElementById("active-intent");
    const reasoningStatusEl = document.getElementById("reasoning-status");
    const reasoningThoughtsEl = document.getElementById("reasoning-thoughts");
    const memoryHitsEl = document.getElementById("memory-hits-count");
    const tokenBudgetEl = document.getElementById("token-budget");
    const toolUseCountEl = document.getElementById("tool-use-count");
    const toolsListEl = document.getElementById("tools-list");

    // Theme selector
    const themeBtns = document.querySelectorAll(".theme-select-btn");

    // Initialize Theme
    setTheme(currentTheme);

    // ==========================================
    // 1. Theme Selector
    // ==========================================
    function setTheme(theme) {
        body.className = "";
        body.classList.add(`theme-${theme}`);
        currentTheme = theme;
        localStorage.setItem("aloy-theme", theme);
        
        themeBtns.forEach(btn => {
            if (btn.getAttribute("data-theme") === theme) {
                btn.classList.add("active");
            } else {
                btn.classList.remove("active");
            }
        });
    }

    themeBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const theme = btn.getAttribute("data-theme");
            setTheme(theme);
        });
    });

    // ==========================================
    // 2. View Router Navigation
    // ==========================================
    navItems.forEach(item => {
        item.addEventListener("click", (e) => {
            e.preventDefault();
            const view = item.getAttribute("data-view");
            
            navItems.forEach(n => n.classList.remove("active"));
            item.classList.add("active");
            
            stageViews.forEach(v => v.classList.remove("active"));
            const targetView = document.getElementById(`view-${view}`);
            if (targetView) {
                targetView.classList.add("active");
            }
            
            // Update Title
            viewTitle.textContent = item.textContent.trim();
            
            // Mobile collapse left sidebar on navigate
            if (window.innerWidth <= 768) {
                sidebarLeft.classList.remove("active");
            }
        });
    });

    // Sidebar Toggles
    const sidebarCloseRight = document.getElementById("sidebar-close-right");
    const dashboardContainer = document.querySelector(".dashboard-container");

    function updateRightSidebarLayout() {
        if (rightSidebarCollapsed) {
            sidebarRight?.classList.add("collapsed");
            dashboardContainer?.classList.add("right-collapsed");
        } else {
            sidebarRight?.classList.remove("collapsed");
            dashboardContainer?.classList.remove("right-collapsed");
        }
    }

    // Ensure initial state matches
    updateRightSidebarLayout();

    sidebarToggleLeft?.addEventListener("click", () => {
        sidebarLeft?.classList.toggle("active");
    });

    sidebarToggleRight?.addEventListener("click", () => {
        rightSidebarCollapsed = !rightSidebarCollapsed;
        updateRightSidebarLayout();
    });

    sidebarCloseRight?.addEventListener("click", () => {
        rightSidebarCollapsed = true;
        updateRightSidebarLayout();
    });

    // Keyboard support: Escape closes Device Info panel
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && !rightSidebarCollapsed) {
            rightSidebarCollapsed = true;
            updateRightSidebarLayout();
        }
    });

    // ==========================================
    // 3. Conversation History Ajax
    // ==========================================
    // Configure marked options if available
    if (typeof marked !== 'undefined') {
        marked.setOptions({
            gfm: true,
            breaks: true
        });
    }

    // Markdown Parser
    function renderMarkdown(content, isStreaming) {
        if (typeof marked === 'undefined') {
            const escaped = content
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;");
            return isStreaming ? `${escaped}<span class="token-cursor-inline">▍</span>` : escaped;
        }
        
        let html = marked.parse(content);
        
        if (isStreaming) {
            const lastTagRegex = /(<\/[a-zA-Z0-9]+>\s*)$/;
            const match = html.match(lastTagRegex);
            if (match) {
                const tag = match[1];
                const cursor = '<span class="token-cursor-inline">▍</span>';
                const index = html.lastIndexOf(tag);
                html = html.substring(0, index) + cursor + tag;
            } else {
                html += '<span class="token-cursor-inline">▍</span>';
            }
        }
        return html;
    }

    // Code Block Formatter
    function formatCodeBlocks(container) {
        const preElements = container.querySelectorAll("pre");
        preElements.forEach(pre => {
            if (pre.parentElement && pre.parentElement.classList.contains("code-block-container")) {
                return;
            }
            
            const code = pre.querySelector("code");
            let lang = "plaintext";
            if (code) {
                const classes = Array.from(code.classList);
                const langClass = classes.find(c => c.startsWith("language-") || c.startsWith("lang-"));
                if (langClass) {
                    lang = langClass.replace("language-", "").replace("lang-", "");
                }
            }
            
            const wrapper = document.createElement("div");
            wrapper.className = "code-block-container";
            
            const header = document.createElement("div");
            header.className = "code-block-header";
            header.innerHTML = `
                <span class="code-lang">${lang}</span>
                <button class="code-copy-btn"><i class="fa-regular fa-copy"></i> Copy</button>
            `;
            
            const copyBtn = header.querySelector(".code-copy-btn");
            copyBtn.addEventListener("click", () => {
                const textToCopy = code ? code.textContent : pre.textContent;
                navigator.clipboard.writeText(textToCopy).then(() => {
                    copyBtn.innerHTML = `<i class="fa-solid fa-check" style="color: #22c55e;"></i> Copied!`;
                    setTimeout(() => {
                        copyBtn.innerHTML = `<i class="fa-regular fa-copy"></i> Copy`;
                    }, 2000);
                }).catch(err => {
                    console.error("Failed to copy code: ", err);
                });
            });
            
            pre.parentNode.insertBefore(wrapper, pre);
            wrapper.appendChild(header);
            wrapper.appendChild(pre);
        });
    }

    // Date grouping utility
    function groupSessionsByDate(sessions) {
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);
        const lastWeek = new Date(today);
        lastWeek.setDate(lastWeek.getDate() - 7);
        
        const groups = {
            today: [],
            yesterday: [],
            lastWeek: [],
            older: []
        };
        
        sessions.forEach(session => {
            const date = new Date(session.created_at || session.updated_at || Date.now());
            if (date >= today) {
                groups.today.push(session);
            } else if (date >= yesterday) {
                groups.yesterday.push(session);
            } else if (date >= lastWeek) {
                groups.lastWeek.push(session);
            } else {
                groups.older.push(session);
            }
        });
        
        return groups;
    }

    // Render categorized and filtered conversations
    function renderFilteredConversations() {
        const query = (document.getElementById("search-history")?.value || "").toLowerCase().trim();
        
        const filtered = allSessionsList.filter(s => {
            const title = (s.title || "Untitled Chat").toLowerCase();
            return title.includes(query);
        });
        
        historyList.innerHTML = "";
        if (filtered.length === 0) {
            historyList.innerHTML = '<div class="history-item-placeholder">No conversations found</div>';
            return;
        }
        
        const groups = groupSessionsByDate(filtered);
        
        function renderGroup(groupName, displayName, items) {
            if (items.length === 0) return;
            
            const isCollapsed = collapsedGroups[groupName];
            
            const groupHeader = document.createElement("div");
            groupHeader.className = "history-group-header";
            if (isCollapsed) groupHeader.classList.add("collapsed");
            groupHeader.setAttribute("data-group", groupName);
            groupHeader.innerHTML = `
                <span>${displayName}</span>
                <i class="fa-solid fa-chevron-down"></i>
            `;
            
            const itemsContainer = document.createElement("div");
            itemsContainer.className = "history-group-items";
            if (isCollapsed) itemsContainer.classList.add("collapsed");
            itemsContainer.id = `group-items-${groupName}`;
            
            items.forEach(session => {
                const item = document.createElement("div");
                item.className = "history-item";
                if (session.id === activeConversationId) {
                    item.classList.add("active");
                }
                item.setAttribute("data-id", session.id);
                
                const title = session.title || "Untitled Chat";
                item.innerHTML = `
                    <span class="history-item-label" title="${title}"><i class="fa-regular fa-comment"></i> ${title}</span>
                    <div class="history-item-actions">
                        <button class="history-action-btn btn-rename" title="Rename"><i class="fa-solid fa-pen"></i></button>
                        <button class="history-action-btn btn-delete" title="Delete"><i class="fa-solid fa-trash"></i></button>
                    </div>
                `;
                
                item.addEventListener("click", () => {
                    selectConversation(session.id);
                });
                
                const renameBtn = item.querySelector(".btn-rename");
                renameBtn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    renameConversation(session.id, title);
                });
                
                const deleteBtn = item.querySelector(".btn-delete");
                deleteBtn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    deleteConversation(session.id);
                });
                
                itemsContainer.appendChild(item);
            });
            
            groupHeader.addEventListener("click", () => {
                collapsedGroups[groupName] = !collapsedGroups[groupName];
                groupHeader.classList.toggle("collapsed", collapsedGroups[groupName]);
                itemsContainer.classList.toggle("collapsed", collapsedGroups[groupName]);
            });
            
            historyList.appendChild(groupHeader);
            historyList.appendChild(itemsContainer);
        }
        
        renderGroup("today", "Today", groups.today);
        renderGroup("yesterday", "Yesterday", groups.yesterday);
        renderGroup("lastWeek", "Previous 7 Days", groups.lastWeek);
        renderGroup("older", "Older", groups.older);
    }

    async function renameConversation(id, currentTitle) {
        const newTitle = prompt("Enter new chat title:", currentTitle);
        if (newTitle === null) return;
        const trimmed = newTitle.trim();
        if (!trimmed) return;
        
        try {
            const res = await fetch(`/api/conversation/${id}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ title: trimmed })
            });
            if (!res.ok) throw new Error("Failed to rename");
            loadConversations();
        } catch (err) {
            console.error(err);
            alert("Error renaming conversation: " + err.message);
        }
    }
    
    async function deleteConversation(id) {
        if (!confirm("Are you sure you want to delete this conversation? This cannot be undone.")) return;
        
        try {
            const res = await fetch(`/api/conversation/${id}`, {
                method: "DELETE"
            });
            if (!res.ok) throw new Error("Failed to delete");
            
            if (activeConversationId === id) {
                activeConversationId = null;
                newChatBtn.click();
            }
            loadConversations();
        } catch (err) {
            console.error(err);
            alert("Error deleting conversation: " + err.message);
        }
    }

    async function loadConversations() {
        try {
            const res = await fetch("/api/conversation");
            if (!res.ok) throw new Error("Failed to fetch sessions");
            allSessionsList = await res.json();
            renderFilteredConversations();
        } catch (err) {
            console.error(err);
            historyList.innerHTML = '<div class="history-item-placeholder text-danger">Failed to load</div>';
        }
    }

    async function selectConversation(id) {
        activeConversationId = id;
        loadConversations();
        
        chatMessages.innerHTML = '<div class="history-item-placeholder">Loading messages...</div>';
        
        try {
            const res = await fetch(`/api/conversation/${id}/history`);
            if (!res.ok) throw new Error("Failed to fetch history");
            const history = await res.json();
            
            chatMessages.innerHTML = "";
            if (history.length === 0) {
                showWelcome();
            } else {
                history.forEach(msg => {
                    appendMessageBubble(msg.role, msg.content, msg.id, msg.metadata);
                });
            }
            
            document.querySelector('[data-view="chat"]').click();
            scrollChat();
            loadConversationState(id);
        } catch (err) {
            console.error(err);
            chatMessages.innerHTML = '<div class="history-item-placeholder text-danger">Failed to load chat history.</div>';
        }
    }

    async function loadConversationState(id) {
        try {
            const res = await fetch(`/api/conversation/${id}/state`);
            if (!res.ok) return;
            const state = await res.json();
            
            activeModelEl.textContent = state.last_model_used || "phi4-mini";
            activeIntentEl.textContent = state.current_intent || "simple_chat";
            memoryHitsEl.textContent = state.active_memories ? state.active_memories.length : 0;
            
            const tokenCount = state.context_token_count || 0;
            const tokenPercent = Math.min((tokenCount / 8192) * 100, 100);
            tokenBudgetEl.textContent = `${tokenCount} / 8192`;
            const barTokens = document.getElementById("bar-tokens");
            if (barTokens) {
                barTokens.style.width = `${tokenPercent}%`;
            }
        } catch (err) {
            console.error(err);
        }
    }

    function showWelcome() {
        chatMessages.innerHTML = `
            <div class="welcome-message">
                <div class="welcome-icon"><i class="fa-solid fa-terminal"></i></div>
                <h2>Welcome to ALOY OS</h2>
                <p>An intelligent microkernel-based AI core. Ask a question or start a debugging chain.</p>
            </div>
        `;
    }

    newChatBtn.addEventListener("click", () => {
        activeConversationId = null;
        chatMessages.innerHTML = "";
        showWelcome();
        // Clear active selection in history
        document.querySelectorAll(".history-item").forEach(item => item.classList.remove("active"));
        
        // Reset sidebar indicators
        activeModelEl.textContent = "phi4-mini";
        activeIntentEl.textContent = "simple_chat";
        memoryHitsEl.textContent = "0";
        tokenBudgetEl.textContent = "0 / 8192";
        reasoningThoughtsEl.innerHTML = '<span class="placeholder-text">Thoughts empty...</span>';
        toolsListEl.innerHTML = '<span class="placeholder-text">No tools used in this session.</span>';
    });

    // ==========================================
    // 4. Event Bus status listeners
    // ==========================================
    function updateStatusIndicator(subsystem, status, message = "") {
        const indicator = document.getElementById(`status-${subsystem}`);
        if (!indicator) return;
        
        let colorClass = "gray";
        if (status === "Ready" || status === "success") colorClass = "green";
        else if (status === "Working" || status === "progress") colorClass = "yellow";
        else if (status === "Waiting") colorClass = "yellow";
        else if (status === "Error" || status === "failed") colorClass = "red";
        
        indicator.innerHTML = `<span class="status-dot ${colorClass}"></span> ${subsystem.charAt(0).toUpperCase() + subsystem.slice(1)}: ${status}`;
        
        if (message) {
            document.getElementById("status-logs").textContent = `[${subsystem.toUpperCase()}] ${message}`;
        }
    }

    // ==========================================
    // 5. Post SSE Chunk Stream Client
    // ==========================================
    async function sendMessage(text, override = null) {
        if (!activeConversationId) {
            // Create a new session first
            try {
                const res = await fetch("/api/conversation", { method: "POST" });
                if (!res.ok) throw new Error("Could not initialize chat session");
                const state = await res.json();
                activeConversationId = state.id;
                loadConversations();
            } catch (err) {
                console.error(err);
                appendMessageBubble("assistant", "System error: Failed to initialize conversation context.", null);
                return;
            }
        }
        
        // Clear welcome message if present
        const welcome = chatMessages.querySelector(".welcome-message");
        if (welcome) welcome.remove();
        
        // Append user message bubble
        const userMsgId = crypto.randomUUID();
        appendMessageBubble("user", text, userMsgId);
        scrollChat();
        
        // Setup assistant container bubble with TYPING INDICATOR
        const assistantMsgId = crypto.randomUUID();
        const bubble = appendMessageBubble("assistant", "", assistantMsgId);
        const bodyEl = bubble.querySelector(".message-bubble-body");
        
        // Show bouncing dots while waiting for first token
        bodyEl.innerHTML = `<span class="typing-indicator"><span></span><span></span><span></span></span>`;
        bodyEl.classList.add("streaming");
        
        // Clear previous reasoning details
        reasoningThoughtsEl.innerHTML = "";
        reasoningStatusEl.textContent = "Idle";
        
        let firstTokenReceived = false;
        let fullAssistantResponse = "";
        
        function startTextStream() {
            if (!firstTokenReceived) {
                firstTokenReceived = true;
                bodyEl.innerHTML = "";
            }
        }
        
        function finalizeStream() {
            bodyEl.classList.remove("streaming");
        }
        
        try {
            updateStatusIndicator("router", "Working", "Routing query and initiating LLM stream...");
            
            const payload = { content: text };
            if (override) {
                payload.override = override;
            }
            
            const response = await fetch(`/api/conversation/${activeConversationId}/message`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            
            if (!response.ok) throw new Error(`Server error: ${response.status}`);
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            
            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                
                buffer += decoder.decode(value, { stream: true });
                
                const lines = buffer.split("\n");
                buffer = lines.pop();
                
                for (const line of lines) {
                    const trimmed = line.trim();
                    if (!trimmed.startsWith("data:")) continue;
                    
                    const payload = trimmed.slice(5).trim();
                    if (!payload) continue;
                    
                    let data;
                    try {
                        data = JSON.parse(payload);
                    } catch (e) {
                        continue;
                    }
                    
                    switch (data.type) {
                        case "meta":
                            activeModelEl.textContent = data.model || "phi4-mini";
                            activeIntentEl.textContent = data.intent || "simple_chat";
                            updateStatusIndicator("router", "Working", `Loading ${data.model || "model"}...`);
                            
                            if (data.search_status) {
                                const badgeBox = bubble.querySelector(".knowledge-badges");
                                badgeBox.style.display = "flex";
                                let statusText = "";
                                let statusClass = "";
                                if (data.search_status === "success") {
                                    statusText = "🌐 Used Live Web Search";
                                    statusClass = "search-success";
                                } else if (data.search_status === "failed") {
                                    statusText = "⚠ Live Search Failed";
                                    statusClass = "search-failed";
                                } else {
                                    statusText = "🧠 Answered from Local Knowledge";
                                    statusClass = "search-local";
                                }
                                badgeBox.innerHTML = `<span class="badge-source ${statusClass}">${statusText}</span>`;
                            }
                            break;
                            
                        case "token":
                            startTextStream();
                            fullAssistantResponse += data.content;
                            bodyEl.classList.add("markdown-content");
                            bodyEl.innerHTML = renderMarkdown(fullAssistantResponse, true);
                            updateStatusIndicator("router", "Working", `Streaming from ${activeModelEl.textContent}...`);
                            scrollChat();
                            break;
                            
                        case "reasoning_started":
                            reasoningStatusEl.textContent = "Working";
                            updateStatusIndicator("reasoning", "Working", "Reasoning pipeline activated.");
                            appendThoughtStep(data.stage || "Thinking", "Evaluating reasoning path...");
                            break;
                            
                        case "reasoning_progress":
                            appendThoughtStep(data.stage || "Thinking", data.content || "");
                            break;
                            
                        case "reasoning_finished":
                            reasoningStatusEl.textContent = "Idle";
                            updateStatusIndicator("reasoning", "Ready", "Reasoning verification completed.");
                            break;
                            
                        case "tool_started":
                            updateStatusIndicator("tools", "Working", `Running tool: ${data.tool_name}...`);
                            incrementToolCount();
                            appendToolLog(data.tool_name, "Working");
                            break;
                            
                        case "tool_finished":
                            updateStatusIndicator("tools", "Ready", `Completed tool: ${data.tool_name}.`);
                            updateToolLog(data.tool_name, "Done");
                            break;
                            
                        case "learning_started":
                            updateStatusIndicator("learning", "Working", "Background insight extraction active.");
                            break;
                            
                        case "learning_finished":
                            updateStatusIndicator("learning", "Ready", "Consolidation complete.");
                            break;
                            
                        case "done":
                            finalizeStream();
                            bodyEl.innerHTML = renderMarkdown(fullAssistantResponse, false);
                            bodyEl.classList.add("markdown-content");
                            formatCodeBlocks(bodyEl);
                            updateStatusIndicator("router", "Ready", "Stream finished successfully.");
                            appendBubbleActions(bubble, assistantMsgId);
                            loadConversationState(activeConversationId);
                            loadConversations();
                            break;
                            
                        default:
                            break;
                    }
                }
            }
            
            // Edge-case: stream ended (done=true) without a "done" event
            finalizeStream();
            
        } catch (err) {
            console.error(err);
            finalizeStream();
            bodyEl.textContent = "[Connection error — please try again]";
            updateStatusIndicator("router", "Error", "Failed to retrieve LLM response.");
        }
    }

    // Segmented Model Override Pill Control
    const btnOverrideAuto = document.getElementById("btn-override-auto");
    const btnOverrideThink = document.getElementById("btn-override-think");
    const btnOverrideCode = document.getElementById("btn-override-code");
    let activeOverride = null;

    function setOverrideMode(mode) {
        activeOverride = mode;
        [btnOverrideAuto, btnOverrideThink, btnOverrideCode].forEach(btn => {
            if (!btn) return;
            btn.classList.remove("active");
            btn.setAttribute("aria-checked", "false");
        });

        if (mode === "reasoning" && btnOverrideThink) {
            btnOverrideThink.classList.add("active");
            btnOverrideThink.setAttribute("aria-checked", "true");
        } else if (mode === "coding" && btnOverrideCode) {
            btnOverrideCode.classList.add("active");
            btnOverrideCode.setAttribute("aria-checked", "true");
        } else if (btnOverrideAuto) {
            btnOverrideAuto.classList.add("active");
            btnOverrideAuto.setAttribute("aria-checked", "true");
        }
    }

    btnOverrideAuto?.addEventListener("click", () => setOverrideMode(null));
    btnOverrideThink?.addEventListener("click", () => setOverrideMode("reasoning"));
    btnOverrideCode?.addEventListener("click", () => setOverrideMode("coding"));

    chatForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const text = chatInput.value.trim();
        if (!text) return;
        
        chatInput.value = "";
        
        const currentOverride = activeOverride;
        setOverrideMode(null);
        
        sendMessage(text, currentOverride);
    });

    // Handle Enter to submit, Shift+Enter for newline
    chatInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            chatForm.dispatchEvent(new Event("submit"));
        }
    });

    // ==========================================
    // 6. UI Helpers (Bubbles, Thoughts, Tools)
    // ==========================================
    function appendMessageBubble(role, content, msgId, metadata = {}) {
        const bubble = document.createElement("div");
        bubble.className = `message-bubble ${role}`;
        if (msgId) bubble.setAttribute("data-msg-id", msgId);
        
        const avatarIcon = role === "user" ? '<i class="fa-solid fa-user"></i>' : '<i class="fa-solid fa-terminal"></i>';
        
        const bodyClass = role === "assistant" ? "message-bubble-body markdown-content" : "message-bubble-body";
        const initialHtml = role === "assistant" ? renderMarkdown(content, false) : "";
        
        bubble.innerHTML = `
            <div class="avatar">${avatarIcon}</div>
            <div class="message-content-wrapper">
                <div class="message-bubble-body ${bodyClass}">${initialHtml}</div>
                <div class="knowledge-badges" style="display: none;"></div>
                <div class="message-actions" style="display: none;"></div>
            </div>
        `;
        
        chatMessages.appendChild(bubble);
        
        const bodyEl = bubble.querySelector(".message-bubble-body");
        if (role === "user") {
            bodyEl.textContent = content;
        } else if (role === "assistant" && content) {
            formatCodeBlocks(bodyEl);
        }
        
        if (metadata) {
            const badgeBox = bubble.querySelector(".knowledge-badges");
            let hasBadges = false;
            
            if (metadata.search_status) {
                badgeBox.style.display = "flex";
                hasBadges = true;
                let statusText = "";
                let statusClass = "";
                if (metadata.search_status === "success") {
                    statusText = "🌐 Used Live Web Search";
                    statusClass = "search-success";
                } else if (metadata.search_status === "failed") {
                    statusText = "⚠ Live Search Failed";
                    statusClass = "search-failed";
                } else {
                    statusText = "🧠 Answered from Local Knowledge";
                    statusClass = "search-local";
                }
                badgeBox.innerHTML += `<span class="badge-source ${statusClass}">${statusText}</span>`;
            }
            
            if (metadata.sources) {
                badgeBox.style.display = "flex";
                hasBadges = true;
                metadata.sources.forEach(src => {
                    const label = (typeof src === "object" && src !== null) ? (src.title || src.url) : src;
                    badgeBox.innerHTML += `<span class="badge-source">${label}</span>`;
                });
            }
        }
        
        if (role === "assistant" && msgId && content) {
            appendBubbleActions(bubble, msgId);
        }
        
        return bubble;
    }

    function appendBubbleActions(bubble, msgId) {
        const actionsBox = bubble.querySelector(".message-actions");
        actionsBox.style.display = "flex";
        actionsBox.innerHTML = `
            <button class="msg-act-btn btn-thumbs-up" aria-label="Like"><i class="fa-regular fa-thumbs-up"></i></button>
            <button class="msg-act-btn btn-thumbs-down" aria-label="Dislike"><i class="fa-regular fa-thumbs-down"></i></button>
            <button class="msg-act-btn btn-regenerate" aria-label="Regenerate"><i class="fa-solid fa-arrows-rotate"></i> Regenerate</button>
            <button class="msg-act-btn btn-branch" aria-label="Branch conversation"><i class="fa-solid fa-code-fork"></i> Branch</button>
        `;
        
        // Attach event handlers
        const thumbsUp = actionsBox.querySelector(".btn-thumbs-up");
        const thumbsDown = actionsBox.querySelector(".btn-thumbs-down");
        const regenerate = actionsBox.querySelector(".btn-regenerate");
        const branch = actionsBox.querySelector(".btn-branch");
        
        thumbsUp.addEventListener("click", () => submitFeedback(msgId, "thumbs_up", thumbsUp, thumbsDown));
        thumbsDown.addEventListener("click", () => submitFeedback(msgId, "thumbs_down", thumbsDown, thumbsUp));
        regenerate.addEventListener("click", () => regenerateMessage(msgId));
        branch.addEventListener("click", () => branchSession(msgId));
    }

    function appendThoughtStep(stage, content) {
        // Clear placeholder text if present
        const placeholder = reasoningThoughtsEl.querySelector(".placeholder-text");
        if (placeholder) placeholder.remove();
        
        // Check if stage block already exists
        let stageBlock = document.getElementById(`thought-stage-${stage}`);
        if (!stageBlock) {
            stageBlock = document.createElement("div");
            stageBlock.className = "thought-step";
            stageBlock.id = `thought-stage-${stage}`;
            stageBlock.innerHTML = `
                <div class="thought-stage-title">> ${stage}</div>
                <div class="thought-stage-content">${content}</div>
            `;
            reasoningThoughtsEl.appendChild(stageBlock);
        } else {
            const contentEl = stageBlock.querySelector(".thought-stage-content");
            contentEl.textContent += "\n" + content;
        }
        
        reasoningThoughtsEl.scrollTop = reasoningThoughtsEl.scrollHeight;
    }

    function incrementToolCount() {
        const count = parseInt(toolUseCountEl.textContent) + 1;
        toolUseCountEl.textContent = count;
    }

    function appendToolLog(toolName, status) {
        const placeholder = toolsListEl.querySelector(".placeholder-text");
        if (placeholder) placeholder.remove();
        
        const toolEl = document.createElement("div");
        toolEl.className = "meta-row";
        toolEl.id = `tool-log-${toolName}`;
        toolEl.innerHTML = `
            <span class="meta-label"><i class="fa-solid fa-screwdriver-wrench"></i> ${toolName}</span>
            <span class="meta-val" style="color: var(--accent);">${status}...</span>
        `;
        toolsListEl.appendChild(toolEl);
        toolsListEl.scrollTop = toolsListEl.scrollHeight;
    }

    function updateToolLog(toolName, status) {
        const toolEl = document.getElementById(`tool-log-${toolName}`);
        if (toolEl) {
            const valEl = toolEl.querySelector(".meta-val");
            valEl.textContent = status;
            valEl.style.color = "var(--text)";
        }
    }

    function scrollChat() {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    // ==========================================
    // 7. Interactive Features
    // ==========================================
    async function submitFeedback(msgId, type, btnActive, btnInactive) {
        btnActive.classList.toggle("active");
        btnInactive.classList.remove("active");
        
        const isLiked = btnActive.classList.contains("active");
        const feedbackType = isLiked ? type : "neutral";
        
        try {
            await fetch(`/api/conversation/${activeConversationId}/messages/${msgId}/feedback`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ feedback_type: feedbackType })
            });
        } catch (err) {
            console.error("Failed to submit feedback", err);
        }
    }

    async function regenerateMessage(msgId) {
        const bubble = document.querySelector(`[data-msg-id="${msgId}"]`);
        if (!bubble) return;
        
        let sibling = bubble.nextElementSibling;
        while (sibling) {
            const next = sibling.nextElementSibling;
            sibling.remove();
            sibling = next;
        }
        bubble.remove();
        
        const assistantMsgId = crypto.randomUUID();
        const newBubble = appendMessageBubble("assistant", "", assistantMsgId);
        const bodyEl = newBubble.querySelector(".message-bubble-body");
        
        bodyEl.innerHTML = `<span class="typing-indicator"><span></span><span></span><span></span></span>`;
        bodyEl.classList.add("streaming");
        
        reasoningThoughtsEl.innerHTML = "";
        reasoningStatusEl.textContent = "Idle";
        
        let firstTokenReceived = false;
        let fullAssistantResponse = "";
        
        function startTextStream() {
            if (!firstTokenReceived) {
                firstTokenReceived = true;
                bodyEl.innerHTML = "";
            }
        }
        
        function finalizeStream() {
            bodyEl.classList.remove("streaming");
        }
        
        try {
            updateStatusIndicator("router", "Working", "Initiating regeneration stream...");
            
            const response = await fetch(`/api/conversation/${activeConversationId}/messages/${msgId}/regenerate`, {
                method: "POST"
            });
            
            if (!response.ok) throw new Error("Regeneration failed");
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            
            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop();
                
                for (const line of lines) {
                    const trimmed = line.trim();
                    if (!trimmed.startsWith("data:")) continue;
                    
                    const payload = trimmed.slice(5).trim();
                    if (!payload) continue;
                    
                    let data;
                    try {
                        data = JSON.parse(payload);
                    } catch (e) {
                        continue;
                    }
                    
                    if (data.type === "token") {
                        startTextStream();
                        fullAssistantResponse += data.content;
                        bodyEl.classList.add("markdown-content");
                        bodyEl.innerHTML = renderMarkdown(fullAssistantResponse, true);
                        scrollChat();
                    } else if (data.type === "done") {
                        finalizeStream();
                        bodyEl.innerHTML = renderMarkdown(fullAssistantResponse, false);
                        bodyEl.classList.add("markdown-content");
                        formatCodeBlocks(bodyEl);
                        updateStatusIndicator("router", "Ready", "Regeneration complete.");
                        appendBubbleActions(newBubble, assistantMsgId);
                        loadConversationState(activeConversationId);
                    }
                }
            }
        } catch (err) {
            console.error(err);
            finalizeStream();
            bodyEl.textContent = " [System Error: Failed to regenerate response]";
            updateStatusIndicator("router", "Error", "Regeneration failed.");
        }
    }

    async function branchSession(msgId) {
        try {
            updateStatusIndicator("kernel", "Working", "Forking session branch...");
            const res = await fetch(`/api/conversation/${activeConversationId}/branch`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ from_message_id: msgId })
            });
            
            if (!res.ok) throw new Error("Branching failed");
            const newState = await res.json();
            
            // Switch active session to branch
            activeConversationId = newState.id;
            updateStatusIndicator("kernel", "Ready", `Switched to branch session: ${newState.id.slice(0,8)}`);
            
            // Reload history list & select the new conversation
            await loadConversations();
            selectConversation(newState.id);
        } catch (err) {
            console.error(err);
            alert("Failed to branch conversation.");
            updateStatusIndicator("kernel", "Ready", "Branch failed.");
        }
    }

    // ==========================================================================
    // 8. Autonomous Agent Dashboard Controller (Mission 12)
    // ==========================================================================
    let activeAgentSessionId = null;
    let agentPollInterval = null;

    // DOM Elements
    const agentSessionSelect = document.getElementById("agent-session-select");
    const btnToggleNewSession = document.getElementById("btn-toggle-new-session");
    const newSessionFormContainer = document.getElementById("new-session-form-container");
    const newSessionProject = document.getElementById("new-session-project");
    const newSessionGoal = document.getElementById("new-session-goal");
    const btnStartSession = document.getElementById("btn-start-session");
    
    const btnPauseAgent = document.getElementById("btn-pause-agent");
    const btnResumeAgent = document.getElementById("btn-resume-agent");
    const btnCancelAgent = document.getElementById("btn-cancel-agent");
    
    const activeAgentGoalDisplay = document.getElementById("active-agent-goal-display");
    const activeAgentStatusBadge = document.getElementById("active-agent-status-badge");
    const agentTaskList = document.getElementById("agent-task-list");
    const agentEventLogs = document.getElementById("agent-event-logs");
    const agentCheckpointsList = document.getElementById("agent-checkpoints-list");

    const tabBtnLogs = document.getElementById("tab-btn-logs");
    const tabBtnCheckpoints = document.getElementById("tab-btn-checkpoints");
    const tabContentLogs = document.getElementById("tab-content-logs");
    const tabContentCheckpoints = document.getElementById("tab-content-checkpoints");

    // Toggle Creator Form
    btnToggleNewSession.addEventListener("click", () => {
        const metaBox = document.querySelector(".active-session-meta-box");
        const statusGrid = document.querySelector(".agent-status-grid");
        const layoutFlex = document.querySelector(".layout-flex");

        if (newSessionFormContainer.style.display === "none") {
            newSessionFormContainer.style.display = "block";
            btnToggleNewSession.innerHTML = '<i class="fa-solid fa-xmark"></i> Close';
            if (metaBox) metaBox.style.display = "none";
            if (statusGrid) statusGrid.style.display = "none";
            if (layoutFlex) layoutFlex.style.display = "none";
            loadProjectsForSessionCreator();
        } else {
            newSessionFormContainer.style.display = "none";
            btnToggleNewSession.innerHTML = '<i class="fa-solid fa-plus"></i> New Session';
            if (metaBox) metaBox.style.display = "flex";
            if (statusGrid) statusGrid.style.display = "grid";
            if (layoutFlex) layoutFlex.style.display = "flex";
            
            // Clean up inline project form
            if (inlineRegForm) inlineRegForm.style.display = "none";
            const inlineProjName = document.getElementById("inline-proj-name");
            const inlineProjPath = document.getElementById("inline-proj-path");
            if (inlineProjName) inlineProjName.value = "";
            if (inlineProjPath) inlineProjPath.value = "";
        }
    });

    // Populate Projects Dropdown — shows hint if empty
    async function loadProjectsForSessionCreator() {
        newSessionProject.innerHTML = '<option value="">Loading...</option>';
        try {
            const res = await fetch("/api/projects");
            if (!res.ok) throw new Error("Failed to load projects");
            const projects = await res.json();

            if (projects.length === 0) {
                newSessionProject.innerHTML = '<option value="">No projects yet — go to Projects tab to register one</option>';
                return;
            }

            newSessionProject.innerHTML = '<option value="">-- Choose Project --</option>';
            projects.forEach(proj => {
                const opt = document.createElement('option');
                opt.value = proj.id;
                opt.textContent = proj.name + ' (' + proj.root_path.split(/[\\/]/).pop() + ')';
                newSessionProject.appendChild(opt);
            });
        } catch (err) {
            console.error(err);
            newSessionProject.innerHTML = '<option value="">Error loading projects</option>';
        }
    }

    // Populate Agent Sessions Dropdown
    async function loadAgentSessions() {
        try {
            const res = await fetch("/api/agent/sessions");
            if (!res.ok) throw new Error("Failed to load agent sessions");
            const sessions = await res.json();
            
            const currentSelected = agentSessionSelect.value;
            agentSessionSelect.innerHTML = '<option value="">-- Select Agent Session --</option>';
            sessions.forEach(sess => {
                const selected = sess.session_id === currentSelected ? "selected" : "";
                agentSessionSelect.innerHTML += `
                    <option value="${sess.session_id}" ${selected}>
                        ${sess.session_id.slice(0, 8)}: ${sess.goal.slice(0, 30)}...
                    </option>
                `;
            });
        } catch (err) {
            console.error(err);
        }
    }

    // Dropdown Selection Change
    agentSessionSelect.addEventListener("change", () => {
        const val = agentSessionSelect.value;
        if (val) {
            selectAgentSession(val);
        } else {
            clearAgentSessionView();
        }
    });

    function clearAgentSessionView() {
        activeAgentSessionId = null;
        if (agentPollInterval) {
            clearInterval(agentPollInterval);
            agentPollInterval = null;
        }
        activeAgentGoalDisplay.textContent = "No active session selected";
        activeAgentStatusBadge.className = "badge-status status-gray";
        activeAgentStatusBadge.textContent = "Idle";
        btnPauseAgent.disabled = true;
        btnResumeAgent.disabled = true;
        btnCancelAgent.disabled = true;
        agentTaskList.innerHTML = '<div class="empty-list">No active tasks. Select a session above.</div>';
        agentEventLogs.textContent = "System idle. Select or create an agent session to begin monitoring workflow...";
        agentCheckpointsList.innerHTML = '<div class="empty-list">No checkpoints recorded for the active session.</div>';
        resetAgentCardDots();
    }

    function resetAgentCardDots() {
        const agents = ["manager", "planner", "architect", "coder", "tester", "debugger", "reviewer", "documenter", "learner"];
        agents.forEach(a => {
            const card = document.getElementById(`agent-card-${a}`);
            if (card) {
                const dot = card.querySelector(".dot");
                if (dot) dot.className = "dot gray";
            }
        });
    }

    function selectAgentSession(sessionId) {
        activeAgentSessionId = sessionId;
        if (agentPollInterval) clearInterval(agentPollInterval);
        
        // Initial Poll
        pollAgentSessionStatus();
        
        // Poll every 2 seconds
        agentPollInterval = setInterval(pollAgentSessionStatus, 2000);
        
        // Update live status bar indicator
        updateStatusIndicator("agent", "Ready", `Monitoring agent session ${sessionId.slice(0,8)}`);
    }

    // Create & Trigger Agent Session
    btnStartSession.addEventListener("click", async () => {
        const goal = newSessionGoal.value.trim();
        if (!goal) {
            alert("Please describe a goal for the agent session.");
            return;
        }

        const projectId = newSessionProject.value || null;

        btnStartSession.disabled = true;
        btnStartSession.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Initializing...';

        try {
            // 1. Create Session
            const createRes = await fetch("/api/agent/session", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ goal, project_id: projectId })
            });
            if (!createRes.ok) {
                const errData = await createRes.json().catch(() => ({}));
                throw new Error(errData.detail || "Failed to create agent session");
            }
            const createData = await createRes.json();
            const sessionId = createData.session_id;

            // 2. Refresh dropdown list and select the new session
            await loadAgentSessions();
            agentSessionSelect.value = sessionId;
            selectAgentSession(sessionId);

            // 3. Trigger execution in background
            const execRes = await fetch(`/api/agent/session/${sessionId}/execute`, {
                method: "POST"
            });
            if (!execRes.ok) {
                const errData = await execRes.json().catch(() => ({}));
                throw new Error(errData.detail || "Failed to trigger execution");
            }

            // Hide creation box
            newSessionFormContainer.style.display = "none";
            btnToggleNewSession.innerHTML = '<i class="fa-solid fa-plus"></i> New Session';
            newSessionGoal.value = "";

            const metaBox = document.querySelector(".active-session-meta-box");
            const statusGrid = document.querySelector(".agent-status-grid");
            const layoutFlex = document.querySelector(".layout-flex");
            if (metaBox) metaBox.style.display = "flex";
            if (statusGrid) statusGrid.style.display = "grid";
            if (layoutFlex) layoutFlex.style.display = "flex";

        } catch (err) {
            console.error(err);
            alert("Error creating agent session: " + err.message);
        } finally {
            btnStartSession.disabled = false;
            btnStartSession.innerHTML = 'Initialize &amp; Run Agent Grid';
        }
    });

    // Control buttons handlers
    btnPauseAgent.addEventListener("click", async () => {
        if (!activeAgentSessionId) return;
        try {
            await fetch(`/api/agent/session/${activeAgentSessionId}/pause`, { method: "POST" });
            pollAgentSessionStatus();
        } catch (err) {
            console.error(err);
        }
    });

    btnResumeAgent.addEventListener("click", async () => {
        if (!activeAgentSessionId) return;
        try {
            await fetch(`/api/agent/session/${activeAgentSessionId}/resume`, { method: "POST" });
            pollAgentSessionStatus();
        } catch (err) {
            console.error(err);
        }
    });

    btnCancelAgent.addEventListener("click", async () => {
        if (!activeAgentSessionId) return;
        if (!confirm("Are you sure you want to cancel the entire agent session run?")) return;
        try {
            await fetch(`/api/agent/session/${activeAgentSessionId}/cancel`, { method: "POST" });
            pollAgentSessionStatus();
        } catch (err) {
            console.error(err);
        }
    });

    // Main status polling loop
    async function pollAgentSessionStatus() {
        if (!activeAgentSessionId) return;
        
        try {
            // 1. Fetch Session Status & Checkpoints
            const res = await fetch(`/api/agent/session/${activeAgentSessionId}`);
            if (!res.ok) throw new Error("Session status fetch failed");
            const statusData = await res.json();
            
            // Update goal display
            activeAgentGoalDisplay.textContent = statusData.goal;
            
            // Update status badge
            activeAgentStatusBadge.textContent = statusData.status;
            activeAgentStatusBadge.className = `badge-status status-${statusData.status}`;
            
            // Expose rich progress metadata if present
            const progressBox = document.getElementById("active-session-progress-details");
            if (progressBox) {
                let meta = {};
                if (statusData.metadata) {
                    try {
                        meta = typeof statusData.metadata === "string" ? JSON.parse(statusData.metadata) : statusData.metadata;
                    } catch (e) {
                        console.error("Failed to parse session metadata:", e);
                    }
                }
                if (meta && (meta.progress_pct !== undefined || meta.elapsed_seconds !== undefined)) {
                    progressBox.style.display = "block";
                    document.getElementById("progress-pct").textContent = `${meta.progress_pct || 0}%`;
                    document.getElementById("progress-elapsed").textContent = `${meta.elapsed_seconds || 0}s`;
                    document.getElementById("progress-eta").textContent = meta.eta_seconds !== undefined ? `${meta.eta_seconds}s` : "N/A";
                    document.getElementById("progress-model").textContent = meta.current_model || "None";
                    document.getElementById("progress-retry").textContent = meta.retry_count || 0;
                    document.getElementById("progress-waiting").textContent = (meta.waiting_reason && meta.waiting_reason !== "None") ? meta.waiting_reason : "None";
                } else {
                    progressBox.style.display = "none";
                }
            }
            
            // Enable/disable control buttons
            btnPauseAgent.disabled = statusData.status !== "executing";
            btnResumeAgent.disabled = statusData.status !== "paused";
            btnCancelAgent.disabled = ["completed", "failed", "rolled_back"].includes(statusData.status);
            
            // Update footer agent status dot
            if (statusData.status === "executing") {
                updateStatusIndicator("agent", "Working", `Running workflow. Current status: ${statusData.status}`);
            } else if (["completed", "failed"].includes(statusData.status)) {
                updateStatusIndicator("agent", "Ready", `Execution ended with: ${statusData.status}`);
            }
            
            // Render checkpoints tab
            renderCheckpoints(statusData.checkpoints || []);

            // 2. Fetch Tasks Queue
            const tasksRes = await fetch(`/api/agent/session/${activeAgentSessionId}/tasks`);
            if (tasksRes.ok) {
                const tasks = await tasksRes.json();
                renderTaskList(tasks);
                updateAgentGridStatus(tasks, statusData.status);
                generateTerminalLogs(tasks, statusData);
            }
            
        } catch (err) {
            console.error("Agent polling error:", err);
            // If session not found, clear
            if (err.message.includes("404")) {
                clearAgentSessionView();
                loadAgentSessions();
            }
        }
    }

    // Checkpoints renderer
    function renderCheckpoints(checkpoints) {
        if (checkpoints.length === 0) {
            agentCheckpointsList.innerHTML = '<div class="empty-list">No checkpoints recorded for the active session.</div>';
            return;
        }
        
        agentCheckpointsList.innerHTML = "";
        checkpoints.forEach(chk => {
            const item = document.createElement("div");
            item.className = "checkpoint-item";
            item.innerHTML = `
                <div class="checkpoint-info">
                    <div class="checkpoint-title">Checkpoint Step index: ${chk.step_index}</div>
                    <div class="checkpoint-time">Created: ${new Date(chk.created_at).toLocaleString()}</div>
                    <div class="checkpoint-time" style="font-family: monospace; font-size: 0.72rem;">ID: ${chk.id}</div>
                </div>
                <div class="checkpoint-actions">
                    <button class="btn-chk-action btn-rollback" data-id="${chk.id}">Rollback</button>
                    <button class="btn-chk-action btn-resume" data-id="${chk.id}">Resume From Here</button>
                </div>
            `;
            
            // Attach checkpoint actions
            item.querySelector(".btn-rollback").addEventListener("click", () => rollbackToCheckpoint(chk.id));
            item.querySelector(".btn-resume").addEventListener("click", () => resumeSessionFromCheckpoint(chk.id));
            
            agentCheckpointsList.appendChild(item);
        });
    }

    async function rollbackToCheckpoint(checkpointId) {
        if (!confirm("This will restore workspace files to the checkpoint state. Proceed?")) return;
        updateStatusIndicator("agent", "Working", "Rolling back workspace state...");
        try {
            const res = await fetch(`/api/agent/session/${activeAgentSessionId}/rollback`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ checkpoint_id: checkpointId })
            });
            if (!res.ok) throw new Error("Rollback failed");
            pollAgentSessionStatus();
            alert("Workspace rolled back successfully.");
        } catch (err) {
            console.error(err);
            alert("Rollback failed: " + err.message);
        }
    }

    async function resumeSessionFromCheckpoint(checkpointId) {
        if (!confirm("Workspace will be restored and execution will resume. Proceed?")) return;
        updateStatusIndicator("agent", "Working", "Resuming workspace from checkpoint...");
        try {
            const res = await fetch(`/api/agent/session/${activeAgentSessionId}/resume-from-checkpoint`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ checkpoint_id: checkpointId })
            });
            if (!res.ok) throw new Error("Checkpoint resumption failed");
            pollAgentSessionStatus();
            alert("Execution resumed from checkpoint.");
        } catch (err) {
            console.error(err);
            alert("Resumption failed: " + err.message);
        }
    }

    // Task Queue renderer
    function renderTaskList(tasks) {
        if (tasks.length === 0) {
            agentTaskList.innerHTML = '<div class="empty-list">No active tasks. Select a session above.</div>';
            return;
        }
        
        // Find existing open output boxes so we don't collapse them on refresh
        const openTaskIds = new Set();
        document.querySelectorAll(".task-output-detail").forEach(box => {
            const taskId = box.getAttribute("data-task-id");
            if (taskId) openTaskIds.add(taskId);
        });

        agentTaskList.innerHTML = "";
        tasks.forEach(task => {
            const isDone = task.status === "done";
            const isRunning = task.status === "running";
            
            const item = document.createElement("div");
            item.className = "task-item";
            
            // Build task layout
            let taskIcon = "";
            if (task.assigned_agent === "coder") taskIcon = '<i class="fa-solid fa-code"></i>';
            else if (task.assigned_agent === "tester") taskIcon = '<i class="fa-solid fa-vial"></i>';
            else if (task.assigned_agent === "planner") taskIcon = '<i class="fa-solid fa-map"></i>';
            else if (task.assigned_agent === "debugger") taskIcon = '<i class="fa-solid fa-bug"></i>';
            else taskIcon = '<i class="fa-solid fa-robot"></i>';

            const outputData = task.result || task.error;
            const outputHtml = outputData ? `
                <div class="task-output-expander">
                    <button class="btn-expander" data-id="${task.id}">
                        <i class="fa-solid ${openTaskIds.has(task.id) ? 'fa-chevron-up' : 'fa-chevron-down'}"></i> 
                        ${task.error ? 'Show Error Log' : 'Show Result Details'}
                    </button>
                    <div class="task-output-detail" data-task-id="${task.id}" style="${openTaskIds.has(task.id) ? '' : 'display:none;'}">${outputData}</div>
                </div>
            ` : "";

            item.innerHTML = `
                <div class="task-item-header">
                    <div class="task-title-group">
                        <span class="task-agent-badge">${taskIcon} ${task.assigned_agent}</span>
                        <strong>${task.title}</strong>
                    </div>
                    <span class="task-status-badge ${task.status}">${task.status}</span>
                </div>
                <div class="task-desc">${task.description}</div>
                <div class="task-meta-row">
                    <span>Priority: ${task.priority}</span>
                    <span>Retries: ${task.retry_count}</span>
                    ${task.depends_on.length > 0 ? `<span>Depends on: [${task.depends_on.join(', ')}]</span>` : ''}
                </div>
                ${outputHtml}
            `;
            
            // Expander toggle event
            const btnExpander = item.querySelector(".btn-expander");
            if (btnExpander) {
                btnExpander.addEventListener("click", () => {
                    const detailBox = item.querySelector(".task-output-detail");
                    const icon = btnExpander.querySelector("i");
                    if (detailBox.style.display === "none") {
                        detailBox.style.display = "block";
                        icon.className = "fa-solid fa-chevron-up";
                    } else {
                        detailBox.style.display = "none";
                        icon.className = "fa-solid fa-chevron-down";
                    }
                });
            }

            agentTaskList.appendChild(item);
        });
    }

    // Dynamic grid lighting based on active running task
    function updateAgentGridStatus(tasks, sessionStatus) {
        resetAgentCardDots();
        
        if (["completed", "failed", "rolled_back", "paused"].includes(sessionStatus)) {
            return;
        }

        // Check if any task is running
        const runningTask = tasks.find(t => t.status === "running");
        if (runningTask) {
            const activeAgent = runningTask.assigned_agent;
            const card = document.getElementById(`agent-card-${activeAgent}`);
            if (card) {
                const dot = card.querySelector(".dot");
                if (dot) dot.className = "dot green"; // light up green
            }
        } else if (sessionStatus === "planning") {
            const card = document.getElementById("agent-card-manager");
            if (card) {
                const dot = card.querySelector(".dot");
                if (dot) dot.className = "dot yellow"; // yellow = initial scheduling
            }
        }
    }

    // Chronological terminal events logs compiler
    function generateTerminalLogs(tasks, sessionData) {
        let events = [];
        
        events.push(`[${new Date(sessionData.created_at).toLocaleTimeString()}] SESSION_STARTED: Initialized runtime workspace loop.`);
        
        tasks.forEach(t => {
            if (t.status === "running") {
                events.push(`[${new Date().toLocaleTimeString()}] TASK_RUNNING: Agent [${t.assigned_agent}] has claimed step: "${t.title}".`);
            } else if (t.status === "done") {
                events.push(`[${new Date(t.updated_at || new Date()).toLocaleTimeString()}] TASK_SUCCESS: Agent [${t.assigned_agent}] completed step: "${t.title}".`);
            } else if (t.status === "failed") {
                events.push(`[${new Date(t.updated_at || new Date()).toLocaleTimeString()}] TASK_FAILED: Agent [${t.assigned_agent}] crashed executing step: "${t.title}". Error: ${t.error ? t.error.slice(0, 40) : 'Unknown crash'}`);
            }
        });

        if (sessionData.status === "completed") {
            events.push(`[${new Date(sessionData.updated_at).toLocaleTimeString()}] SESSION_COMPLETED: Goal achieved successfully. Closed locks.`);
        } else if (sessionData.status === "failed") {
            events.push(`[${new Date(sessionData.updated_at).toLocaleTimeString()}] SESSION_FAILED: Runtime orchestration terminated due to critical failures.`);
        } else if (sessionData.status === "paused") {
            events.push(`[${new Date(sessionData.updated_at).toLocaleTimeString()}] SESSION_PAUSED: Execution suspended by controller.`);
        }

        // Keep last 15 log events
        events = events.slice(-15);
        agentEventLogs.innerHTML = events.map(e => `<div>${e}</div>`).join("");
        agentEventLogs.scrollTop = agentEventLogs.scrollHeight;
    }

    // Logs & Checkpoints tabs controllers
    tabBtnLogs.addEventListener("click", () => {
        tabBtnLogs.classList.add("active");
        tabBtnCheckpoints.classList.remove("active");
        tabContentLogs.style.display = "block";
        tabContentCheckpoints.style.display = "none";
    });

    tabBtnCheckpoints.addEventListener("click", () => {
        tabBtnCheckpoints.classList.add("active");
        tabBtnLogs.classList.remove("active");
        tabContentCheckpoints.style.display = "block";
        tabContentLogs.style.display = "none";
    });

    // ==========================================
    // 9. Backups & Rollbacks Settings (Mission 13)
    // ==========================================
    const btnTriggerBackup = document.getElementById("btn-trigger-backup");
    const backupsListContainer = document.getElementById("backups-list-container");
    const rollbackSessionSelect = document.getElementById("rollback-session-select");
    const rollbackCheckpointSelect = document.getElementById("rollback-checkpoint-select");
    const rollbackFilePath = document.getElementById("rollback-file-path");
    const btnRevertFile = document.getElementById("btn-revert-file");

    // Load and render GFS Backups list
    async function loadBackups() {
        try {
            const res = await fetch("/api/security/backups");
            if (!res.ok) throw new Error("Failed to load backups");
            const backups = await res.json();

            backupsListContainer.innerHTML = "";
            if (backups.length === 0) {
                backupsListContainer.innerHTML = '<div class="empty-list">No backups created yet.</div>';
                return;
            }

            backups.forEach(backup => {
                const item = document.createElement("div");
                item.className = "checkpoint-item";
                item.style.marginBottom = "8px";
                
                const dateStr = new Date(backup.created_at).toLocaleString();
                const sizeKb = (backup.size_bytes / 1024).toFixed(1);

                item.innerHTML = `
                    <div class="checkpoint-info">
                        <div class="checkpoint-title">
                            <span class="badge-status status-gray" style="padding: 2px 6px; font-size: 0.68rem; margin-right: 6px;">${backup.bucket.toUpperCase()}</span>
                            ${backup.name}
                        </div>
                        <div class="checkpoint-time">Created: ${dateStr} | Size: ${sizeKb} KB</div>
                    </div>
                    <div class="checkpoint-actions">
                        <button class="btn-chk-action btn-rollback" data-path="${backup.path}">Restore</button>
                    </div>
                `;

                item.querySelector(".btn-rollback").addEventListener("click", () => restoreDbBackup(backup.path));
                backupsListContainer.appendChild(item);
            });
        } catch (err) {
            console.error("Error loading backups:", err);
            backupsListContainer.innerHTML = '<div class="empty-list text-danger">Error loading backups.</div>';
        }
    }

    async function restoreDbBackup(backupPath) {
        if (!confirm("Warning: This will restore the database to this backup state. Current session details will be overwritten. Proceed?")) return;
        try {
            const res = await fetch("/api/security/backup/restore", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ backup_path: backupPath })
            });
            if (!res.ok) throw new Error("Restore failed");
            alert("Database backup restored successfully.");
            // Reload all UI data
            loadBackups();
            loadAgentSessions();
            loadConversations();
        } catch (err) {
            console.error(err);
            alert("Restore failed: " + err.message);
        }
    }

    // Trigger backup
    btnTriggerBackup.addEventListener("click", async () => {
        btnTriggerBackup.disabled = true;
        btnTriggerBackup.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Backing up...';
        try {
            const res = await fetch("/api/security/backup", { method: "POST" });
            if (!res.ok) throw new Error("Backup failed");
            alert("Database backup created successfully (GFS rotation executed).");
            await loadBackups();
        } catch (err) {
            console.error(err);
            alert("Backup failed: " + err.message);
        } finally {
            btnTriggerBackup.disabled = false;
            btnTriggerBackup.innerHTML = '<i class="fa-solid fa-cloud-arrow-up"></i> Trigger Immediate Backup';
        }
    });

    // Populate Rollback Session Select
    async function loadRollbackSessions() {
        try {
            const res = await fetch("/api/agent/sessions");
            if (!res.ok) throw new Error("Failed to load sessions");
            const sessions = await res.json();

            rollbackSessionSelect.innerHTML = '<option value="">-- Choose Session --</option>';
            sessions.forEach(sess => {
                rollbackSessionSelect.innerHTML += `
                    <option value="${sess.session_id}">
                        ${sess.session_id.slice(0, 8)}: ${sess.goal.slice(0, 30)}...
                    </option>
                `;
            });
        } catch (err) {
            console.error(err);
        }
    }

    // Load checkpoints when session is selected
    rollbackSessionSelect.addEventListener("change", async () => {
        const sessionId = rollbackSessionSelect.value;
        rollbackCheckpointSelect.innerHTML = '<option value="">-- Choose Checkpoint --</option>';
        if (!sessionId) return;

        try {
            const res = await fetch(`/api/agent/session/${sessionId}`);
            if (!res.ok) throw new Error("Failed to load session details");
            const data = await res.json();
            
            const checkpoints = data.checkpoints || [];
            checkpoints.forEach(chk => {
                rollbackCheckpointSelect.innerHTML += `
                    <option value="${chk.id}">Step ${chk.step_index} (${chk.id.slice(0,8)})</option>
                `;
            });
        } catch (err) {
            console.error(err);
        }
    });

    // Run Surgical Rollback
    btnRevertFile.addEventListener("click", async () => {
        const sessionId = rollbackSessionSelect.value;
        const checkpointId = rollbackCheckpointSelect.value;
        const filePath = rollbackFilePath.value.trim();

        if (!sessionId || !checkpointId || !filePath) {
            alert("Please select a session, a checkpoint, and enter a file path.");
            return;
        }

        if (!confirm(`Surgically roll back '${filePath}' to selected checkpoint? This cannot be undone.`)) return;

        btnRevertFile.disabled = true;
        btnRevertFile.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Reverting...';

        try {
            const res = await fetch("/api/security/rollback/file", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: sessionId, checkpoint_id: checkpointId, file_path: filePath })
            });
            if (!res.ok) {
                const errData = await res.json();
                throw new Error(errData.detail || "Revert failed");
            }
            alert(`Successfully reverted '${filePath}' to the checkpoint state.`);
            rollbackFilePath.value = "";
        } catch (err) {
            console.error(err);
            alert("Surgical rollback failed: " + err.message);
        } finally {
            btnRevertFile.disabled = false;
            btnRevertFile.innerHTML = '<i class="fa-solid fa-file-shield"></i> Run Surgical Rollback';
        }
    });

    // Trigger load when switching to Settings view
    document.querySelector('[data-view="settings"]')?.addEventListener("click", () => {
        loadBackups();
        loadRollbackSessions();
    });

    // Settings tab-switching navigation
    const settingsTabBtns = document.querySelectorAll(".settings-tab-btn");
    const settingsTabContents = document.querySelectorAll(".settings-tab-content");
    
    settingsTabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const targetTabId = btn.getAttribute("data-tab");
            
            settingsTabBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            
            settingsTabContents.forEach(content => {
                if (content.id === targetTabId) {
                    content.style.display = "flex";
                    content.classList.add("active");
                } else {
                    content.style.display = "none";
                    content.classList.remove("active");
                }
            });
        });
    });

    // Live Telemetry status updater
    async function updateSystemStats() {
        try {
            const res = await fetch("/api/system/dashboard/stats");
            if (!res.ok) throw new Error("Telemetry fetch failed");
            const stats = await res.json();
            
            const cpu = stats.cpu_percent || 0;
            const valCpu = document.getElementById("val-cpu");
            const barCpu = document.getElementById("bar-cpu");
            if (valCpu) valCpu.textContent = `${cpu.toFixed(1)}%`;
            if (barCpu) barCpu.style.width = `${cpu}%`;
            
            const gpu = stats.gpu_percent || 0;
            const valGpu = document.getElementById("val-gpu");
            const barGpu = document.getElementById("bar-gpu");
            if (valGpu) valGpu.textContent = `${gpu.toFixed(1)}%`;
            if (barGpu) barGpu.style.width = `${gpu}%`;
            
            const ram = stats.ram_percent || 0;
            const valRam = document.getElementById("val-ram");
            const barRam = document.getElementById("bar-ram");
            if (valRam) valRam.textContent = `${ram.toFixed(1)}%`;
            if (barRam) barRam.style.width = `${ram}%`;
            
            const vram = stats.vram_mb_used || 0;
            const vramPercent = Math.min((vram / 8192) * 100, 100);
            const valVram = document.getElementById("val-vram");
            const barVram = document.getElementById("bar-vram");
            if (valVram) valVram.textContent = `${vram.toFixed(0)} MB / 8192 MB`;
            if (barVram) barVram.style.width = `${vramPercent}%`;
            
            const latency = stats.avg_llm_latency_ms || 0;
            const statLatency = document.getElementById("stat-latency");
            if (statLatency) statLatency.textContent = `${latency.toFixed(0)} ms`;
            
        } catch (err) {
            console.error("Telemetry update failed:", err);
        }
    }

    // Search input listener
    const searchHistory = document.getElementById("search-history");
    if (searchHistory) {
        searchHistory.addEventListener("input", () => {
            renderFilteredConversations();
        });
    }

    // Telemetry polling loop initialization
    updateSystemStats();
    setInterval(updateSystemStats, 5000);

    // Verify system health dependencies before checking onboarding status
    checkSystemDependencies();

    // ==========================================================================
    // PROJECTS PANEL (Full CRUD)
    // ==========================================================================
    const projectsListContainer = document.getElementById("projects-list-container");
    const btnToggleNewProject = document.getElementById("btn-toggle-new-project");
    const newProjectForm = document.getElementById("new-project-form-container");
    const btnRegisterProject = document.getElementById("btn-register-project");
    const btnCancelNewProject = document.getElementById("btn-cancel-new-project");

    async function loadProjects() {
        if (!projectsListContainer) return;
        projectsListContainer.innerHTML = '<div class="empty-list"><i class="fa-solid fa-spinner fa-spin"></i> Loading...</div>';
        try {
            const res = await fetch("/api/projects");
            if (!res.ok) throw new Error("Failed to load projects");
            const projects = await res.json();

            if (!Array.isArray(projects)) {
                throw new Error("Invalid response format from server");
            }

            if (projects.length === 0) {
                projectsListContainer.innerHTML = `
                    <div style="padding: 40px 20px; text-align: center; background: var(--card); border: 1px dashed var(--border); border-radius: 12px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px; margin-top: 16px;">
                        <div style="font-size: 2.5rem; color: var(--accent);"><i class="fa-solid fa-folder-plus"></i></div>
                        <h3 style="font-family: var(--font-heading); font-size: 1.1rem; margin: 0; color: var(--text);">No Project Workspaces Registered</h3>
                        <p style="font-size: 0.85rem; color: var(--text-muted); max-width: 320px; margin: 0; line-height: 1.4;">
                            Workspaces let you run agent sessions, perform directory indexing, and track changes. Register a project folder to start.
                        </p>
                        <button class="btn-primary" onclick="document.getElementById('btn-toggle-new-project').click()" style="padding: 8px 16px; font-size: 0.85rem; cursor: pointer;">
                            <i class="fa-solid fa-plus"></i> Register Your First Project
                        </button>
                    </div>
                `;
                return;
            }

            projectsListContainer.innerHTML = "";
            projects.forEach(proj => {
                const card = document.createElement("div");
                card.className = "checkpoint-item";
                card.style.marginBottom = "10px";
                card.innerHTML = `
                    <div class="checkpoint-info">
                        <div class="checkpoint-title"><i class="fa-solid fa-folder-open" style="color:#60a5fa;margin-right:6px;"></i>${proj.name}</div>
                        <div class="checkpoint-time" style="font-family:monospace;">${proj.root_path}</div>
                        <div class="checkpoint-time">Registered: ${new Date(proj.created_at).toLocaleString()}</div>
                    </div>
                    <div class="checkpoint-actions">
                        <button class="btn-chk-action btn-rollback" data-proj-delete="${proj.id}">
                            <i class="fa-solid fa-trash"></i> Delete
                        </button>
                    </div>
                `;
                card.querySelector("[data-proj-delete]").addEventListener("click", () => deleteProject(proj.id, proj.name));
                projectsListContainer.appendChild(card);
            });
        } catch (err) {
            console.error(err);
            projectsListContainer.innerHTML = `<div class="empty-list text-danger">Failed to load projects: ${err.message}</div>`;
        }
    }

    async function deleteProject(id, name) {
        if (!confirm(`Delete project "${name}"? This only removes the registration, not your actual files.`)) return;
        try {
            const res = await fetch(`/api/projects/${id}`, { method: "DELETE" });
            if (!res.ok) throw new Error("Delete failed");
            loadProjects();
        } catch (err) {
            alert("Failed to delete project: " + err.message);
        }
    }

    if (btnToggleNewProject) {
        btnToggleNewProject.addEventListener("click", () => {
            const isHidden = newProjectForm.style.display === "none";
            newProjectForm.style.display = isHidden ? "block" : "none";
            btnToggleNewProject.innerHTML = isHidden
                ? '<i class="fa-solid fa-xmark"></i> Cancel'
                : '<i class="fa-solid fa-plus"></i> Register Project';
        });
    }

    if (btnCancelNewProject) {
        btnCancelNewProject.addEventListener("click", () => {
            newProjectForm.style.display = "none";
            btnToggleNewProject.innerHTML = '<i class="fa-solid fa-plus"></i> Register Project';
        });
    }

    if (btnRegisterProject) {
        btnRegisterProject.addEventListener("click", async () => {
            const name = document.getElementById("new-proj-name").value.trim();
            const rootPath = document.getElementById("new-proj-path").value.trim();
            const desc = document.getElementById("new-proj-desc").value.trim();
            if (!name || !rootPath) { alert("Please enter a project name and root path."); return; }
            btnRegisterProject.disabled = true;
            btnRegisterProject.textContent = "Registering...";
            try {
                const res = await fetch("/api/projects", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ name, root_path: rootPath, description: desc })
                });
                if (!res.ok) { const e = await res.json(); throw new Error(e.detail || "Registration failed"); }
                document.getElementById("new-proj-name").value = "";
                document.getElementById("new-proj-path").value = "";
                document.getElementById("new-proj-desc").value = "";
                newProjectForm.style.display = "none";
                btnToggleNewProject.innerHTML = '<i class="fa-solid fa-plus"></i> Register Project';
                loadProjects();
            } catch (err) {
                alert("Error: " + err.message);
            } finally {
                btnRegisterProject.disabled = false;
                btnRegisterProject.textContent = "Register Project";
            }
        });
    }

    // Trigger load when switching to Projects view
    document.querySelector('[data-view="projects"]')?.addEventListener("click", () => loadProjects());

    // ==========================================================================
    // AGENT PANEL — Inline Project Registration
    // ==========================================================================
    const btnInlineRegister = document.getElementById("btn-inline-register-project");
    const inlineRegForm = document.getElementById("inline-project-reg-form");
    const btnSaveInline = document.getElementById("btn-save-inline-project");
    const btnCancelInline = document.getElementById("btn-cancel-inline-project");

    if (btnInlineRegister) {
        btnInlineRegister.addEventListener("click", (e) => {
            e.preventDefault();
            inlineRegForm.style.display = inlineRegForm.style.display === "none" ? "block" : "none";
        });
    }
    if (btnCancelInline) {
        btnCancelInline.addEventListener("click", (e) => {
            e.preventDefault();
            inlineRegForm.style.display = "none";
        });
    }
    if (btnSaveInline) {
        btnSaveInline.addEventListener("click", async (e) => {
            e.preventDefault();
            const name = document.getElementById("inline-proj-name").value.trim();
            const path = document.getElementById("inline-proj-path").value.trim();
            if (!name || !path) { alert("Enter a project name and path."); return; }
            btnSaveInline.disabled = true;
            btnSaveInline.textContent = "Saving...";
            try {
                const res = await fetch("/api/projects", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ name, root_path: path, description: "" })
                });
                if (!res.ok) { const e = await res.json(); throw new Error(e.detail || "Failed"); }
                const proj = await res.json();
                // Reload dropdown and auto-select new project
                await loadProjectsForSessionCreator();
                newSessionProject.value = proj.id;
                document.getElementById("inline-proj-name").value = "";
                document.getElementById("inline-proj-path").value = "";
                inlineRegForm.style.display = "none";
            } catch (err) {
                alert("Error registering project: " + err.message);
            } finally {
                btnSaveInline.disabled = false;
                btnSaveInline.textContent = "Save & Select";
            }
        });
    }

    // ==========================================================================
    // MEMORIES PANEL
    // ==========================================================================
    const memoriesListContainer = document.getElementById("memories-list-container");
    const memorySearchInput = document.getElementById("memory-search-input");
    const btnSearchMemories = document.getElementById("btn-search-memories");
    const btnRefreshMemories = document.getElementById("btn-refresh-memories");
    const memoryStatsRow = document.getElementById("memory-stats-row");

    const tierColors = {
        short_term: { bg: "#78350f", text: "#fbbf24", label: "Short Term" },
        long_term:  { bg: "#14532d", text: "#4ade80", label: "Long Term"  },
        permanent:  { bg: "#1e3a5f", text: "#60a5fa", label: "Permanent"  },
    };

    async function loadMemories(query = "") {
        if (!memoriesListContainer) return;
        memoriesListContainer.innerHTML = '<div class="empty-list"><i class="fa-solid fa-spinner fa-spin"></i> Loading...</div>';
        try {
            const url = query.trim()
                ? `/api/memory/search?query=${encodeURIComponent(query.trim())}&limit=30`
                : `/api/memory/search?limit=30`;
            const res = await fetch(url);
            if (!res.ok) throw new Error("Failed to fetch memories");
            const memories = await res.json();

            // Load stats
            const statsRes = await fetch("/api/memory/stats");
            if (statsRes.ok) {
                const stats = await statsRes.json();
                if (memoryStatsRow) {
                    memoryStatsRow.innerHTML = `
                        <span style="color:#fbbf24;">⬤ Short: ${stats.short_term}</span>
                        <span style="color:#4ade80;">⬤ Long: ${stats.long_term}</span>
                        <span style="color:#60a5fa;">⬤ Permanent: ${stats.permanent}</span>
                        <span>Total: ${stats.total}</span>
                    `;
                }
            }

            if (memories.length === 0) {
                memoriesListContainer.innerHTML = '<div class="empty-list">No memories found. Start chatting with ALOY to build memory.</div>';
                return;
            }

            memoriesListContainer.innerHTML = "";
            memories.forEach(mem => {
                const tierStyle = tierColors[mem.tier] || { bg: "#1e2a3d", text: "#8b9bb4", label: mem.tier };
                const scoreHtml = mem.score !== null
                    ? `<span style="color:#22d3ee;font-size:0.72rem;">Score: ${mem.score}</span>`
                    : "";
                const impPct = Math.round((mem.importance || 0) * 100);
                const card = document.createElement("div");
                card.className = "checkpoint-item";
                card.style.marginBottom = "8px";
                card.innerHTML = `
                    <div class="checkpoint-info" style="flex:1;">
                        <div style="display:flex;gap:8px;align-items:center;margin-bottom:4px;flex-wrap:wrap;">
                            <span style="background:${tierStyle.bg};color:${tierStyle.text};font-size:0.7rem;padding:2px 8px;border-radius:4px;font-weight:600;">${tierStyle.label}</span>
                            <span style="background:#1e2a3d;color:#8b9bb4;font-size:0.7rem;padding:2px 8px;border-radius:4px;">${mem.type}</span>
                            <span style="font-size:0.7rem;color:#8b9bb4;">Imp: ${impPct}%</span>
                            <span style="font-size:0.7rem;color:#8b9bb4;">Access: ${mem.access_count}</span>
                            ${scoreHtml}
                        </div>
                        <div style="font-size:0.85rem;line-height:1.5;color:#cbd5e1;word-break:break-word;">${mem.content.replace(/</g,"&lt;").replace(/>/g,"&gt;")}</div>
                        <div style="font-size:0.7rem;color:#4b5e7a;margin-top:4px;">${new Date(mem.created_at).toLocaleString()}</div>
                    </div>
                `;
                memoriesListContainer.appendChild(card);
            });
        } catch (err) {
            console.error(err);
            memoriesListContainer.innerHTML = `<div class="empty-list text-danger">Error: ${err.message}</div>`;
        }
    }

    btnSearchMemories?.addEventListener("click", () => loadMemories(memorySearchInput?.value || ""));
    btnRefreshMemories?.addEventListener("click", () => loadMemories(""));
    memorySearchInput?.addEventListener("keydown", (e) => { if (e.key === "Enter") loadMemories(memorySearchInput.value); });
    document.querySelector('[data-view="memories"]')?.addEventListener("click", () => loadMemories(""));

    // ==========================================================================
    // RESEARCH PANEL
    // ==========================================================================
    const researchQueryInput = document.getElementById("research-query-input");
    const btnRunResearch = document.getElementById("research-query-input") ? document.getElementById("btn-run-research") : null;
    const researchLoading = document.getElementById("research-loading");
    const researchResultsContainer = document.getElementById("research-results-container");
    const researchEmpty = document.getElementById("research-empty");
    const researchLayerBadge = document.getElementById("research-layer-badge");
    const researchConfBar = document.getElementById("research-confidence-bar");
    const researchConfVal = document.getElementById("research-confidence-val");
    const researchAnswerBox = document.getElementById("research-answer-box");
    const researchSourcesBox = document.getElementById("research-sources-box");
    const researchCacheBadge = document.getElementById("research-cache-badge");

    const layerLabels = {
        global_memory: "Memory Cache",
        workspace_memory: "Workspace Memory",
        project_documentation: "Project Docs",
        official_documentation: "Official Docs",
        internet_search: "Web Search",
        community_sources: "Community (SO/GitHub)",
        none: "No Result",
    };

    async function runResearch(e) {
        if (e) e.preventDefault();
        const query = researchQueryInput?.value.trim();
        if (!query) { alert("Please enter a research question."); return; }

        researchEmpty.style.display = "none";
        researchResultsContainer.style.display = "none";
        researchLoading.style.display = "block";
        btnRunResearch.disabled = true;

        try {
            // Load cache size
            const cacheRes = await fetch("/api/knowledge/cache/stats");
            if (cacheRes.ok) {
                const cacheData = await cacheRes.json();
                if (researchCacheBadge) researchCacheBadge.textContent = `Cache: ${cacheData.cache_size} queries stored`;
            }

            const res = await fetch(`/api/knowledge/query?query=${encodeURIComponent(query)}`);
            if (!res.ok) { const e = await res.json(); throw new Error(e.detail || "Query failed"); }
            const data = await res.json();

            researchLoading.style.display = "none";
            researchResultsContainer.style.display = "block";

            // Layer badge
            const layerLabel = layerLabels[data.layer] || data.layer;
            researchLayerBadge.textContent = `Source: ${layerLabel}`;
            researchLayerBadge.className = "badge-status status-gray";

            // Confidence bar
            const confPct = Math.round((data.confidence || 0) * 100);
            researchConfBar.style.width = `${confPct}%`;
            researchConfVal.textContent = `${confPct}% confidence`;

            // Answer
            if (typeof marked !== "undefined") {
                researchAnswerBox.innerHTML = marked.parse(data.answer || "No answer returned.");
                formatCodeBlocks(researchAnswerBox);
            } else {
                researchAnswerBox.textContent = data.answer || "No answer returned.";
            }

            // Sources
            researchSourcesBox.innerHTML = "";
            if (data.sources && data.sources.length > 0) {
                const sourcesTitle = document.createElement("div");
                sourcesTitle.style.cssText = "font-size:0.75rem;color:#8b9bb4;margin-bottom:6px;";
                sourcesTitle.textContent = `Sources (${data.sources.length}):`;
                researchSourcesBox.appendChild(sourcesTitle);
                data.sources.forEach(src => {
                    const s = document.createElement("div");
                    s.style.cssText = "font-size:0.72rem;color:#60a5fa;margin-bottom:3px;word-break:break-all;";
                    const txt = typeof src === "string" ? src : (src.url || src.title || JSON.stringify(src));
                    s.innerHTML = `<i class="fa-solid fa-link" style="margin-right:4px;"></i>${txt}`;
                    researchSourcesBox.appendChild(s);
                });
            }
        } catch (err) {
            researchLoading.style.display = "none";
            researchEmpty.style.display = "block";
            researchEmpty.innerHTML = `<i class="fa-solid fa-triangle-exclamation" style="font-size:2rem;color:#f87171;margin-bottom:12px;"></i><div style="color:#f87171;">Research failed: ${err.message}</div>`;
        } finally {
            btnRunResearch.disabled = false;
        }
    }

    document.getElementById("btn-run-research")?.addEventListener("click", runResearch);
    researchQueryInput?.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            runResearch();
        }
    });

    // Search input listener
    const searchHistory2 = document.getElementById("search-history");

    // ==========================================
    // Onboarding & Dynamic Profile System
    // ==========================================
    async function checkOnboardingStatus() {
        loadAgentSessions();
        await loadConversations();
        if (allSessionsList.length > 0 && !activeConversationId) {
            selectConversation(allSessionsList[0].id);
        }

        try {
            const res = await fetch("/api/profile/status");
            const data = await res.json();
            if (data.onboarded === false) {
                // Launch 6-step wizard
                wizardInit();
            } else {
                document.getElementById("onboarding-overlay").style.display = "none";
            }
        } catch (err) {
            console.error("Error checking onboarding status:", err);
            document.getElementById("onboarding-overlay").style.display = "none";
        }
    }

    // ============================================================
    //  6-STEP FIRST-RUN WIZARD ENGINE
    // ============================================================
    let _wizardStep = 1;
    let _wizardHealthData = null;
    const WIZARD_TOTAL_STEPS = 8;

    function wizardInit() {
        _wizardStep = 1;
        document.getElementById("onboarding-overlay").style.display = "flex";
        // Apply saved or default theme during wizard
        const savedTheme = localStorage.getItem("aloy-theme") || "dark";
        setTheme(savedTheme);
        document.getElementById("wizard-selected-theme").value = savedTheme;
        document.querySelectorAll(".wizard-theme-card").forEach(c => {
            c.classList.toggle("selected", c.dataset.theme === savedTheme);
        });
        wizardRenderStep(1);
    }

    function wizardRenderStep(step) {
        // Hide all steps
        for (let i = 1; i <= WIZARD_TOTAL_STEPS; i++) {
            const el = document.getElementById(`wizard-step-${i}`);
            if (el) el.style.display = "none";
        }
        // Show current step
        const current = document.getElementById(`wizard-step-${step}`);
        if (current) { current.style.display = "block"; }

        // Update progress
        const pct = (step / WIZARD_TOTAL_STEPS) * 100;
        const bar = document.getElementById("wizard-progress-bar");
        if (bar) bar.style.width = pct + "%";
        const label = document.getElementById("wizard-step-label");
        if (label) label.textContent = `Step ${step} of ${WIZARD_TOTAL_STEPS}`;

        // Update dots
        document.querySelectorAll(".wizard-dot").forEach((dot) => {
            const ds = parseInt(dot.dataset.step);
            dot.classList.remove("active", "completed");
            if (ds === step) dot.classList.add("active");
            else if (ds < step) dot.classList.add("completed");
        });

        // Back button
        const backBtn = document.getElementById("btn-wizard-back");
        if (backBtn) backBtn.style.display = step > 1 ? "flex" : "none";

        // Next button label
        const nextBtn = document.getElementById("btn-wizard-next");
        if (nextBtn) {
            if (step === 1) nextBtn.innerHTML = `Get Started <i class="fa-solid fa-arrow-right" style="margin-left:8px"></i>`;
            else if (step === WIZARD_TOTAL_STEPS) nextBtn.innerHTML = `<i class="fa-solid fa-rocket" style="margin-right:8px"></i> Launch ALOY`;
            else nextBtn.innerHTML = `Next <i class="fa-solid fa-arrow-right" style="margin-left:8px"></i>`;
            nextBtn.disabled = false;
        }

        // Trigger async content for certain steps
        if (step === 2) wizardLoadHardware();
        if (step === 3) wizardLoadCoreDeps();
        if (step === 4) wizardLoadOllama();
        if (step === 5) wizardLoadModels();
        if (step === 8) wizardRunLaunchCheck();
    }

    async function wizardNext() {
        if (_wizardStep === 6) {
            // Validate profile fields
            const name = document.getElementById("onboard-name").value.trim();
            const prefName = document.getElementById("onboard-pref-name").value.trim();
            if (!name || !prefName) {
                showWizardToast("Please enter your name and preferred name.");
                return;
            }
        }
        if (_wizardStep === WIZARD_TOTAL_STEPS) {
            await wizardFinish();
            return;
        }
        _wizardStep++;
        wizardRenderStep(_wizardStep);
    }

    function wizardBack() {
        if (_wizardStep > 1) {
            _wizardStep--;
            wizardRenderStep(_wizardStep);
        }
    }


    // Step 2 — Hardware
    async function wizardLoadHardware() {
        const list = document.getElementById("wizard-hw-list");
        const note = document.getElementById("wizard-hw-note");
        if (!list) return;
        list.innerHTML = `<div style="text-align:center;padding:30px;color:var(--text-muted)"><i class="fa-solid fa-spinner fa-spin" style="font-size:1.8rem;margin-bottom:10px;display:block"></i>Checking hardware...</div>`;
        try {
            const res = await fetch("/api/system/health");
            const health = await res.json();
            _wizardHealthData = health;
            list.innerHTML = "";
            const compat = health.compatibility || {};
            const items = [
                { label: "Operating System", ...compat.os },
                { label: "RAM", ...compat.ram },
                { label: "Disk Space", ...compat.disk },
                { label: "GPU Acceleration", ...compat.gpu }
            ];
            let hasWarning = false;
            items.forEach(item => {
                if (!item.ok) hasWarning = true;
                const row = document.createElement("div");
                row.className = `wizard-launch-item ${item.ok ? "ok" : "fail"}`;
                row.innerHTML = `<i class="fa-solid ${item.ok ? "fa-circle-check" : "fa-triangle-exclamation"}" style="color:${item.ok ? "#4ade80" : "#fbbf24"}"></i><div style="flex:1"><div style="font-weight:600">${item.label || item.detail}</div><div style="font-size:0.8rem;color:var(--text-muted)">${item.detail || ""}</div></div>${item.ok ? `<span style="color:#4ade80;font-size:0.8rem;font-weight:600">✓ Compatible</span>` : `<span style="color:#fbbf24;font-size:0.8rem;font-weight:600">⚠ Limited</span>`}`;
                list.appendChild(row);

            });
            if (hasWarning && note) note.style.display = "block";
        } catch (e) {
            list.innerHTML = `<div style="color:var(--text-muted);font-size:0.9rem;padding:20px;text-align:center">Could not retrieve hardware data. Continuing anyway.</div>`;
        }
    }

    // Step 3 — Core Dependencies Check
    async function wizardLoadCoreDeps() {
        const list = document.getElementById("wizard-dep-list");
        const nextBtn = document.getElementById("btn-wizard-next");
        if (!list) return;

        list.innerHTML = `<div style="text-align:center;padding:30px;color:var(--text-muted)"><i class="fa-solid fa-spinner fa-spin" style="font-size:1.8rem;margin-bottom:10px;display:block"></i>Checking dependencies...</div>`;
        if (nextBtn) nextBtn.disabled = true;

        try {
            const res = await fetch("/api/system/health");
            const health = await res.json();
            _wizardHealthData = health;
            list.innerHTML = "";

            const items = [
                { label: "Python Runtime", ok: health.environment.python.ok, message: `Python ${health.environment.python.version} (3.11+ required)` },
                { label: "Git VCS", ok: health.environment.git.ok, message: health.environment.git.ok ? "Git is installed and available" : "Git not found (optional, recommended for version tracking)" },
                { label: "Database Engine", ok: health.database.ok, message: health.database.message },
                { label: "Surgical SQLite Extension", ok: health.sqlite_vec.ok, message: health.sqlite_vec.message },
                { label: "Workspace Access", ok: health.workspace.ok, message: health.workspace.message },
                { label: "Internet Connectivity", ok: health.internet.ok, message: health.internet.message }
            ];

            let allRequiredOk = true;
            items.forEach(item => {
                // Warn or fail based on ok
                // OS/RAM/Disk/Database/Workspace/Python are critical. Git/Internet/sqlite-vec warnings are yellow/gray.
                const isCritical = ["Python Runtime", "Database Engine", "Workspace Access"].includes(item.label);
                if (isCritical && !item.ok) allRequiredOk = false;

                const card = document.createElement("div");
                let borderCol = "rgba(255,255,255,0.06)";
                let bgCol = "rgba(255,255,255,0.02)";
                let iconClass = "fa-circle-check";
                let iconColor = "#4ade80";

                if (!item.ok) {
                    if (isCritical) {
                        borderCol = "rgba(239, 68, 68, 0.25)";
                        bgCol = "rgba(239, 68, 68, 0.04)";
                        iconClass = "fa-circle-xmark";
                        iconColor = "#ef4444";
                    } else {
                        borderCol = "rgba(251, 191, 36, 0.25)";
                        bgCol = "rgba(251, 191, 36, 0.04)";
                        iconClass = "fa-triangle-exclamation";
                        iconColor = "#fbbf24";
                    }
                }

                card.style.cssText = `border: 1px solid ${borderCol}; background: ${bgCol}; border-radius: 10px; padding: 14px 16px; display: flex; align-items: center; gap: 12px; font-size: 0.88rem;`;
                card.innerHTML = `<i class="fa-solid ${iconClass}" style="color:${iconColor}; font-size:1.2rem;"></i><div style="flex:1;"><div style="font-weight:600; color:var(--text);">${item.label}</div><div style="font-size:0.8rem; color:var(--text-muted); margin-top:2px;">${item.message}</div></div>`;
                list.appendChild(card);
            });

            if (nextBtn) nextBtn.disabled = !allRequiredOk;
        } catch (e) {
            list.innerHTML = `<div style="color:#ef4444;font-size:0.9rem;padding:20px;text-align:center"><i class="fa-solid fa-circle-xmark" style="margin-right:6px;"></i>Failed to connect to local ALOY server.</div>`;
        }
    }

    // Step 4 — Ollama Check
    async function wizardLoadOllama() {
        const cardEl = document.getElementById("wizard-ollama-status-card");
        const guideEl = document.getElementById("wizard-ollama-guide");
        const nextBtn = document.getElementById("btn-wizard-next");
        if (!cardEl) return;

        cardEl.innerHTML = `<div style="text-align:center;padding:30px;color:var(--text-muted)"><i class="fa-solid fa-spinner fa-spin" style="font-size:1.8rem;margin-bottom:10px;display:block"></i>Checking Ollama Connection...</div>`;
        if (nextBtn) nextBtn.disabled = true;
        if (guideEl) guideEl.style.display = "none";

        try {
            const res = await fetch("/api/system/health");
            const health = await res.json();
            _wizardHealthData = health;

            cardEl.innerHTML = "";
            if (health.ollama.ok) {
                cardEl.style.cssText = "border: 1px solid rgba(74, 222, 128, 0.25); background: rgba(74, 222, 128, 0.04); border-radius: 12px; padding: 20px; display: flex; align-items: center; gap: 15px;";
                cardEl.innerHTML = `<i class="fa-solid fa-circle-check" style="color:#4ade80; font-size:2rem;"></i><div style="flex:1;"><div style="font-weight:700; font-size:1.05rem; color:#4ade80;">Ollama Service Active</div><div style="font-size:0.85rem; color:var(--text-muted); margin-top:3px;">Successfully connected to Ollama runtime at http://localhost:11434</div></div>`;
                if (nextBtn) nextBtn.disabled = false;
            } else {
                cardEl.style.cssText = "border: 1px solid rgba(239, 68, 68, 0.25); background: rgba(239, 68, 68, 0.04); border-radius: 12px; padding: 20px; display: flex; align-items: center; gap: 15px;";
                cardEl.innerHTML = `<i class="fa-solid fa-circle-xmark" style="color:#ef4444; font-size:2rem;"></i><div style="flex:1;"><div style="font-weight:700; font-size:1.05rem; color:#ef4444;">Ollama Service Offline</div><div style="font-size:0.85rem; color:var(--text-muted); margin-top:3px;">No running Ollama runtime detected. Follow the guide below to set it up.</div></div>`;
                if (guideEl) guideEl.style.display = "block";
                if (nextBtn) nextBtn.disabled = true;
            }
        } catch (e) {
            cardEl.innerHTML = `<div style="color:#ef4444;font-size:0.9rem;padding:20px;text-align:center">Error connecting to server.</div>`;
        }
    }

    // Step 5 — Required Models Check
    async function wizardLoadModels() {
        const list = document.getElementById("wizard-models-required-list");
        const guidEl = document.getElementById("wizard-models-pull-guidance");
        const cmdsEl = document.getElementById("wizard-models-pull-cmds");
        const nextBtn = document.getElementById("btn-wizard-next");
        if (!list) return;

        list.innerHTML = `<div style="text-align:center;padding:30px;color:var(--text-muted)"><i class="fa-solid fa-spinner fa-spin" style="font-size:1.8rem;margin-bottom:10px;display:block"></i>Checking model libraries...</div>`;
        if (nextBtn) nextBtn.disabled = true;
        if (guidEl) guidEl.style.display = "none";

        try {
            const res = await fetch("/api/system/health");
            const health = await res.json();
            _wizardHealthData = health;
            list.innerHTML = "";

            let allRequiredOk = true;
            let missingNames = [];

            health.required_models.forEach(m => {
                if (!m.ok) {
                    allRequiredOk = false;
                    missingNames.push(m.name);
                }

                const card = document.createElement("div");
                card.style.cssText = `background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; font-size: 0.85rem; display: flex; align-items: center; justify-content: space-between;`;
                card.innerHTML = `<div style="display:flex; align-items:center; gap:10px;"><i class="fa-solid ${m.ok ? "fa-circle-check" : "fa-circle-xmark"}" style="color:${m.ok ? "#4ade80" : "#ef4444"}; font-size:1.1rem;"></i><div><strong style="color:var(--text);">${m.label}</strong><div style="font-size:0.75rem; color:var(--text-muted); margin-top:2px;">${m.description}</div></div></div><span style="color:var(--text-muted); font-size:0.8rem;">${m.ok ? `Installed (${m.installed_name})` : `${m.size_gb} GB download`}</span>`;
                list.appendChild(card);
            });

            if (allRequiredOk) {
                if (nextBtn) nextBtn.disabled = false;
            } else {
                let codeCmds = missingNames.map(name => `ollama pull ${name}`).join("<br>");
                if (cmdsEl) cmdsEl.innerHTML = `Please run the following command(s) in a terminal or command prompt:<br><pre style="background: rgba(0, 0, 0, 0.4); padding: 10px 14px; border-radius: 8px; font-family: monospace; font-size: 0.85rem; color: #fff; margin-top: 8px; overflow-x: auto; border: 1px solid var(--border);">${codeCmds}</pre>`;
                if (guidEl) guidEl.style.display = "block";
                // Keep Next button disabled unless skipped
                if (nextBtn) nextBtn.disabled = true;
            }
        } catch (e) {
            list.innerHTML = `<div style="color:#ef4444;font-size:0.9rem;padding:20px;text-align:center">Error loading models.</div>`;
        }
    }


    document.getElementById("btn-wizard-recheck-deps")?.addEventListener("click", wizardLoadCoreDeps);
    document.getElementById("btn-wizard-recheck-ollama")?.addEventListener("click", wizardLoadOllama);
    document.getElementById("btn-wizard-recheck-models")?.addEventListener("click", wizardLoadModels);
    document.getElementById("btn-wizard-skip-models")?.addEventListener("click", () => {
        const nextBtn = document.getElementById("btn-wizard-next");
        if (nextBtn) nextBtn.disabled = false;
        wizardNext();
    });


    // Step 6 — Launch verification
    async function wizardRunLaunchCheck() {
        const checksEl = document.getElementById("wizard-launch-checks");
        const readyEl = document.getElementById("wizard-launch-ready");
        const warnEl = document.getElementById("wizard-launch-warn");
        const warnText = document.getElementById("wizard-launch-warn-text");
        const titleEl = document.getElementById("wizard-launch-title");
        const subEl = document.getElementById("wizard-launch-subtitle");
        const iconEl = document.getElementById("wizard-launch-icon");
        const nextBtn = document.getElementById("btn-wizard-next");
        if (nextBtn) nextBtn.disabled = true;
        if (checksEl) checksEl.innerHTML = "";
        if (readyEl) readyEl.style.display = "none";
        if (warnEl) warnEl.style.display = "none";

        const subsystems = [
            { label: "Database Engine", key: "database" },
            { label: "Workspace Permissions", key: "workspace" },
            { label: "Ollama Service", key: "ollama" },
            { label: "Required AI Models", key: "models" },
            { label: "Hardware Compatibility", key: "hardware" },
        ];

        try {
            const res = await fetch("/api/system/health");
            const health = await res.json();

            const checks = [
                { label: "Database Engine", ok: health.database?.ok, detail: health.database?.message },
                { label: "Workspace Permissions", ok: health.workspace?.ok, detail: health.workspace?.message },
                { label: "Ollama Service", ok: health.ollama?.ok, detail: health.ollama?.message },
                { label: "Required AI Models", ok: (health.required_models || []).every(m => m.ok), detail: (health.required_models || []).every(m => m.ok) ? "All required models installed" : "One or more required models missing" },
                { label: "Hardware Compatibility", ok: true, detail: "System check passed" },
            ];

            if (checksEl) {
                checks.forEach(c => {
                    const row = document.createElement("div");
                    row.className = `wizard-launch-item ${c.ok ? "ok" : "fail"}`;
                    row.innerHTML = `<i class="fa-solid ${c.ok ? "fa-circle-check" : "fa-circle-xmark"}" style="color:${c.ok ? "#4ade80" : "#ef4444"}"></i><div style="flex:1"><div style="font-weight:600">${c.label}</div><div style="font-size:0.8rem;color:var(--text-muted)">${c.detail || ""}</div></div>`;
                    checksEl.appendChild(row);
                });
            }

            const allPassed = checks.every(c => c.ok);
            const criticalPassed = checks.filter(c => ["Database Engine", "Workspace Permissions"].includes(c.label)).every(c => c.ok);

            if (iconEl) iconEl.innerHTML = allPassed ? `<i class="fa-solid fa-rocket" style="font-size:2.8rem;color:var(--accent)"></i>` : `<i class="fa-solid fa-triangle-exclamation" style="font-size:2.8rem;color:#fbbf24"></i>`;
            if (titleEl) titleEl.textContent = allPassed ? "Ready to Launch!" : "Launch with Warnings";
            if (subEl) subEl.textContent = allPassed ? "All systems verified. Click Launch to begin." : "Some non-critical items are missing (Ollama or models). You can still launch ALOY.";

            if (criticalPassed) {
                if (readyEl) readyEl.style.display = "block";
                if (nextBtn) nextBtn.disabled = false;
            } else {
                if (warnText) warnText.textContent = "Please ensure the database and workspace folders are writeable before starting.";
                if (warnEl) warnEl.style.display = "block";
                if (nextBtn) nextBtn.disabled = true;
            }

        } catch (e) {
            if (iconEl) iconEl.innerHTML = `<i class="fa-solid fa-triangle-exclamation" style="font-size:2.8rem;color:#ef4444"></i>`;
            if (titleEl) titleEl.textContent = "Cannot verify systems";
            if (subEl) subEl.textContent = "Backend is unreachable. Check that ALOY server is running.";
            if (warnText) warnText.textContent = e.message;
            if (warnEl) warnEl.style.display = "block";
        }
    }

    // Theme selection in Step 5
    window.wizardSelectTheme = function(theme) {
        document.querySelectorAll(".wizard-theme-card").forEach(c => c.classList.toggle("selected", c.dataset.theme === theme));
        document.getElementById("wizard-selected-theme").value = theme;
        setTheme(theme);
    };

    // Expose wizard navigation to global scope (called via onclick in HTML)
    window.wizardNext = function() { wizardNext(); };
    window.wizardBack = function() { wizardBack(); };


    // Wizard finish — save profile + theme + launch
    async function wizardFinish() {
        const nextBtn = document.getElementById("btn-wizard-next");
        if (nextBtn) { nextBtn.disabled = true; nextBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Launching...`; }

        const name = document.getElementById("onboard-name").value.trim() || "User";
        const prefName = document.getElementById("onboard-pref-name").value.trim() || name;
        const age = parseInt(document.getElementById("onboard-age").value) || 25;
        const country = document.getElementById("onboard-country").value.trim() || "";
        const preferences = document.getElementById("onboard-preferences").value.trim() || "";
        const primaryUse = document.getElementById("onboard-primary-use").value || "Developer";
        const experience = document.getElementById("onboard-experience").value || "Intermediate";
        const theme = document.getElementById("wizard-selected-theme").value || "dark";

        // Build combined preferences string
        const fullPrefs = `Primary Use: ${primaryUse}. Coding Experience: ${experience}. ${preferences}`.trim();

        // Persist theme
        localStorage.setItem("aloy-theme", theme);
        setTheme(theme);

        try {
            const res = await fetch("/api/profile", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, preferred_name: prefName, age, country, preferences: fullPrefs })
            });
            if (!res.ok) throw new Error("Profile save failed");

            // Hide wizard
            document.getElementById("onboarding-overlay").style.display = "none";
            loadAgentSessions();
            loadConversations();

            // Create welcome conversation
            const chatRes = await fetch("/api/conversation", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: "Welcome Chat" })
            });
            if (chatRes.ok) {
                const newConv = await chatRes.json();
                selectConversation(newConv.id);
            }
        } catch (err) {
            showWizardToast("Launch failed: " + err.message);
            if (nextBtn) { nextBtn.disabled = false; nextBtn.innerHTML = `<i class="fa-solid fa-rocket" style="margin-right:8px"></i> Launch ALOY`; }
        }
    }

    // Wire use-case card clicks (Step 4)
    document.querySelectorAll(".wizard-use-card").forEach(card => {
        card.addEventListener("click", () => {
            document.querySelectorAll(".wizard-use-card").forEach(c => c.classList.remove("selected"));
            card.classList.add("selected");
            const hidden = document.getElementById("onboard-primary-use");
            if (hidden) hidden.value = card.dataset.value;
        });
    });

    // Wire experience pill clicks (Step 4)
    document.querySelectorAll(".wizard-exp-pill").forEach(pill => {
        pill.addEventListener("click", () => {
            document.querySelectorAll(".wizard-exp-pill").forEach(p => p.classList.remove("selected"));
            pill.classList.add("selected");
            const hidden = document.getElementById("onboard-experience");
            if (hidden) hidden.value = pill.dataset.value;
        });
    });

    // Simple toast for wizard
    function showWizardToast(msg) {
        const t = document.createElement("div");
        t.style.cssText = "position:fixed;bottom:30px;left:50%;transform:translateX(-50%);background:#ef4444;color:#fff;padding:12px 24px;border-radius:10px;font-size:0.9rem;z-index:99999;box-shadow:0 8px 24px rgba(0,0,0,0.4);animation:slideUp 0.3s ease";
        t.textContent = msg;
        document.body.appendChild(t);
        setTimeout(() => t.remove(), 4000);
    }

    let _skipCrashCheck = sessionStorage.getItem("aloy_crash_acknowledged") === "true";

    async function checkSystemDependencies() {
        const overlay = document.getElementById("dependency-overlay");
        const hwList = document.getElementById("hardware-report-list");
        const reqList = document.getElementById("required-models-list");
        const optList = document.getElementById("optional-models-list");
        const guidanceContainer = document.getElementById("dependency-guidance");
        const guidanceText = document.getElementById("dependency-guidance-text");
        const storageBanner = document.getElementById("storage-estimate-banner");
        const storageVal = document.getElementById("storage-needed-val");

        if (!overlay) return;

        try {
            const res = await fetch("/api/system/health");
            if (!res.ok) throw new Error("Health check returned status " + res.status);
            const health = await res.json();

            // Crash Recovery handling
            if (health.unexpected_exit === true && !_skipCrashCheck) {
                const crashOverlay = document.getElementById("crash-recovery-overlay");
                if (crashOverlay) {
                    crashOverlay.style.display = "flex";
                    
                    document.getElementById("btn-crash-restore").onclick = () => {
                        crashOverlay.style.display = "none";
                        sessionStorage.setItem("aloy_crash_acknowledged", "true");
                        _skipCrashCheck = true;
                        checkSystemDependencies();
                    };

                    
                    document.getElementById("btn-crash-reset").onclick = async () => {
                        if (confirm("This will permanently wipe all local database records, agent tasks, memory indexes, and preferences. Are you sure you want to start fresh?")) {
                            sessionStorage.setItem("aloy_crash_acknowledged", "true");
                            await fetch("/api/profile/reset", { method: "POST" });
                            window.location.reload();
                        }
                    };
                    return;
                }
            }


            if (health.status === "healthy") {
                overlay.style.display = "none";
                checkOnboardingStatus();
                return;
            }


            // Unhealthy: show overlay and details
            overlay.style.display = "flex";
            guidanceContainer.style.display = "none";
            if (storageBanner) storageBanner.style.display = "none";

            // 1. Populate Hardware Compatibility Report
            if (hwList) {
                hwList.innerHTML = "";
                // OS
                addHardwareItem(hwList, health.compatibility.os.label, health.compatibility.os.ok, health.compatibility.os.detail);
                // RAM
                addHardwareItem(hwList, health.compatibility.ram.label, health.compatibility.ram.ok, health.compatibility.ram.detail);
                // Disk Space
                addHardwareItem(hwList, health.compatibility.disk.label, health.compatibility.disk.ok, health.compatibility.disk.detail);
                // GPU
                addHardwareItem(hwList, health.compatibility.gpu.label, health.compatibility.gpu.ok, health.compatibility.gpu.detail);
            }

            // 2. Required Models
            if (reqList) {
                reqList.innerHTML = "";
                health.required_models.forEach(m => {
                    addModelItem(reqList, m.label, m.ok, m.ok ? `Installed (${m.installed_name})` : `Missing - Size: ${m.size_gb} GB`, m.description);
                });
            }

            // 3. Optional Models
            if (optList) {
                optList.innerHTML = "";
                health.optional_models.forEach(m => {
                    addModelItem(optList, m.label, m.ok, m.ok ? `Installed (${m.installed_name})` : `Optional - Size: ${m.size_gb} GB`, m.description);
                });
            }

            // 4. Calculate Storage Estimation for missing required models
            let missingRequiredSize = 0.0;
            health.required_models.forEach(m => {
                if (!m.ok) missingRequiredSize += m.size_gb;
            });
            if (missingRequiredSize > 0.0 && storageBanner && storageVal) {
                storageVal.textContent = `${missingRequiredSize.toFixed(1)} GB`;
                storageBanner.style.display = "flex";
            }

            // 5. Guidance Warning
            if (!health.ollama.ok) {
                guidanceText.innerHTML = "<strong>Ollama service is unreachable.</strong> Please ensure Ollama is installed and running on your local machine. Download Ollama from <a href='https://ollama.com' target='_blank' style='color: var(--accent); text-decoration: underline;'>ollama.com</a>, start the application, and click Recheck.";
                guidanceContainer.style.display = "block";
            } else {
                let missingRequiredNames = health.required_models.filter(m => !m.ok).map(m => m.name);
                if (missingRequiredNames.length > 0) {
                    let codeCmds = missingRequiredNames.map(name => `ollama pull ${name}`).join("<br>");
                    guidanceText.innerHTML = `<strong>Required model(s) are missing.</strong> Please run the following command(s) in a terminal or command prompt window to pull them:<br><pre style="background: rgba(0, 0, 0, 0.4); padding: 8px 12px; border-radius: 6px; font-family: monospace; font-size: 0.82rem; color: #fff; margin-top: 8px; overflow-x: auto; border: 1px solid var(--border);">${codeCmds}</pre>`;
                    guidanceContainer.style.display = "block";
                }
            }

        } catch (err) {
            console.error("Dependency check request failed:", err);
            showRecoveryScreen(err.message || "Failed to communicate with local ALOY backend server.");
        }
    }

    function addHardwareItem(container, label, ok, detail) {
        const div = document.createElement("div");
        div.style.display = "flex";
        div.style.alignItems = "center";
        div.style.gap = "8px";
        div.style.padding = "6px 8px";
        div.style.background = "rgba(255, 255, 255, 0.01)";
        div.style.borderRadius = "4px";

        const icon = document.createElement("i");
        if (ok) {
            icon.className = "fa-solid fa-circle-check";
            icon.style.color = "#4ade80";
        } else {
            icon.className = "fa-solid fa-triangle-exclamation";
            icon.style.color = "#fbbf24";
        }

        const span = document.createElement("span");
        span.innerHTML = `<strong>${label}:</strong> ${detail}`;
        
        div.appendChild(icon);
        div.appendChild(span);
        container.appendChild(div);
    }

    function addModelItem(container, label, ok, detail, desc) {
        const div = document.createElement("div");
        div.style.background = "rgba(255, 255, 255, 0.02)";
        div.style.border = "1px solid var(--border)";
        div.style.borderRadius = "8px";
        div.style.padding = "10px 14px";
        div.style.fontSize = "0.85rem";
        div.title = desc;

        const top = document.createElement("div");
        top.style.display = "flex";
        top.style.alignItems = "center";
        top.style.justifyContent = "space-between";

        const left = document.createElement("div");
        left.style.display = "flex";
        left.style.alignItems = "center";
        left.style.gap = "8px";

        const icon = document.createElement("i");
        icon.className = ok ? "fa-solid fa-circle-check" : "fa-solid fa-circle-xmark";
        icon.style.color = ok ? "#4ade80" : "#ef4444";
        if (!ok && container.id === "optional-models-list") {
            icon.className = "fa-solid fa-circle-minus";
            icon.style.color = "#8b9bb4";
        }

        const titleText = document.createElement("span");
        titleText.style.fontWeight = "600";
        titleText.textContent = label;

        left.appendChild(icon);
        left.appendChild(titleText);

        const right = document.createElement("span");
        right.style.color = "var(--text-muted)";
        right.textContent = detail;

        top.appendChild(left);
        top.appendChild(right);
        div.appendChild(top);
        container.appendChild(div);
    }

    function showRecoveryScreen(errorDetail) {
        const overlay = document.getElementById("recovery-overlay");
        const detailBox = document.getElementById("recovery-error-detail");
        if (overlay && detailBox) {
            detailBox.textContent = errorDetail || "Lost server connection.";
            overlay.style.display = "flex";
        }
    }

    function addHealthItem(container, title, ok, detail) {
        const item = document.createElement("div");
        item.className = "health-item";
        item.style.display = "flex";
        item.style.alignItems = "center";
        item.style.justifyContent = "space-between";
        item.style.padding = "10px 14px";
        item.style.background = "rgba(255, 255, 255, 0.03)";
        item.style.border = "1px solid var(--border)";
        item.style.borderRadius = "8px";
        item.style.fontSize = "0.9rem";

        const left = document.createElement("div");
        left.style.display = "flex";
        left.style.alignItems = "center";
        left.style.gap = "10px";

        const icon = document.createElement("i");
        if (ok) {
            icon.className = "fa-solid fa-circle-check";
            icon.style.color = "#4ade80";
        } else {
            icon.className = "fa-solid fa-circle-xmark";
            icon.style.color = "#ef4444";
        }

        const titleText = document.createElement("span");
        titleText.style.fontWeight = "600";
        titleText.textContent = title;

        left.appendChild(icon);
        left.appendChild(titleText);

        const right = document.createElement("span");
        right.style.fontSize = "0.8rem";
        right.style.color = "var(--text-muted)";
        right.textContent = detail;

        item.appendChild(left);
        item.appendChild(right);
        container.appendChild(item);
    }

    document.getElementById("btn-recheck-dependencies")?.addEventListener("click", async () => {
        const btn = document.getElementById("btn-recheck-dependencies");
        const originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Checking Dependencies...';
        
        await checkSystemDependencies();
        
        btn.disabled = false;
        btn.innerHTML = originalText;
    });

    async function loadProfileData() {
        try {
            const res = await fetch("/api/profile");
            if (res.status === 404) return;
            if (!res.ok) throw new Error("Failed to load profile");
            const profile = await res.json();
            
            document.getElementById("profile-name").value = profile.name || "";
            document.getElementById("profile-pref-name").value = profile.preferred_name || "";
            document.getElementById("profile-age").value = profile.age || "";
            document.getElementById("profile-country").value = profile.country || "";
            document.getElementById("profile-preferences").value = profile.preferences || "";
        } catch (err) {
            console.error("Error loading profile data:", err);
        }
    }

    document.querySelector('[data-tab="settings-profile"]')?.addEventListener("click", () => {
        loadProfileData();
    });

    document.getElementById("btn-save-profile")?.addEventListener("click", async () => {
        const name = document.getElementById("profile-name").value;
        const prefName = document.getElementById("profile-pref-name").value;
        const age = parseInt(document.getElementById("profile-age").value);
        const country = document.getElementById("profile-country").value;
        const preferences = document.getElementById("profile-preferences").value;
        
        if (!name || !prefName || !age || !country) {
            alert("Please fill in all required fields.");
            return;
        }
        
        try {
            const res = await fetch("/api/profile", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    name: name,
                    preferred_name: prefName,
                    age: age,
                    country: country,
                    preferences: preferences
                })
            });
            
            if (!res.ok) throw new Error("Failed to save profile");
            alert("Profile saved successfully.");
        } catch (err) {
            console.error("Error saving profile:", err);
            alert("Error saving profile: " + err.message);
        }
    });

    document.getElementById("btn-reset-profile")?.addEventListener("click", async () => {
        if (!confirm("Are you sure you want to reset ALOY? This will delete all memories, conversations, reasoning logs, and audit trails. ALOY will restart and prompt you with onboarding again.")) {
            return;
        }
        
        try {
            const res = await fetch("/api/profile/reset", { method: "POST" });
            if (!res.ok) throw new Error("Reset failed");
            alert("System reset completed. Reloading page...");
            window.location.reload();
        } catch (err) {
            console.error("Error resetting profile:", err);
            alert("Reset failed: " + err.message);
        }
    });

    document.getElementById("btn-delete-profile")?.addEventListener("click", async () => {
        if (!confirm("Are you sure you want to delete your profile? This will delete your name and preferences, and trigger onboarding on next load.")) {
            return;
        }
        
        try {
            const res = await fetch("/api/profile", { method: "DELETE" });
            if (!res.ok) throw new Error("Deletion failed");
            alert("Profile deleted. Reloading page...");
            window.location.reload();
        } catch (err) {
            console.error("Error deleting profile:", err);
            alert("Deletion failed: " + err.message);
        }
    });

    // Wizard is now handled by wizardNext() / wizardFinish() above.
    // Legacy onboarding-form listener removed — no longer needed.

    // ==========================================
    // About View & Bug Reporting Logic
    // ==========================================
    async function loadAboutMetadata() {
        try {
            const res = await fetch("/api/profile/metadata");
            if (!res.ok) throw new Error("Failed to fetch creator metadata");
            const meta = await res.json();
            
            document.getElementById("about-description").textContent = meta.description || "";
            document.getElementById("about-version").textContent = meta.version || "";
            document.getElementById("about-role").textContent = meta.role || "";
            document.getElementById("about-institution").textContent = meta.institution || "";
            
            const githubEl = document.getElementById("about-github");
            if (githubEl) {
                githubEl.href = meta.github || "#";
                githubEl.textContent = meta.github || "";
            }
            
            const emailEl = document.getElementById("about-email");
            if (emailEl) {
                emailEl.href = `mailto:${meta.email}`;
                emailEl.textContent = meta.email || "";
            }
            
            document.getElementById("about-license").textContent = meta.license || "";
        } catch (err) {
            console.error("Error loading about metadata:", err);
        }
    }

    document.querySelector('[data-view="about"]')?.addEventListener("click", () => {
        loadAboutMetadata();
    });

    function triggerBugReport() {
        const modal = document.getElementById("bug-report-modal");
        if (modal) {
            modal.style.display = "flex";
            document.getElementById("bug-title").value = "";
            document.getElementById("bug-desc").value = "";
            document.getElementById("bug-steps").value = "";
            document.getElementById("bug-expected").value = "";
            document.getElementById("bug-actual").value = "";
            document.getElementById("bug-report-status").style.display = "none";
        }
    }

    document.getElementById("btn-cancel-bug")?.addEventListener("click", () => {
        document.getElementById("bug-report-modal").style.display = "none";
    });

    document.getElementById("btn-submit-bug")?.addEventListener("click", async () => {
        const statusEl = document.getElementById("bug-report-status");
        statusEl.style.display = "block";
        statusEl.style.color = "#94a3b8";
        statusEl.textContent = "Submitting report...";

        const payload = {
            title: document.getElementById("bug-title").value || "Untitled Bug Report",
            description: document.getElementById("bug-desc").value || "No description provided.",
            steps_to_reproduce: document.getElementById("bug-steps").value || "None",
            expected_behavior: document.getElementById("bug-expected").value || "None",
            actual_behavior: document.getElementById("bug-actual").value || "None",
            system_information: navigator.userAgent
        };

        try {
            const metaRes = await fetch("/api/profile/metadata");
            if (metaRes.ok) {
                const meta = await metaRes.json();
                if (meta.version) {
                    payload.system_information = `Version: ${meta.version} | OS: ${navigator.userAgent}`;
                }
            }
        } catch (e) {
            // ignore
        }

        try {
            const res = await fetch("/api/system/report-bug", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                const data = await res.json();
                statusEl.style.color = "#4ade80";
                statusEl.innerHTML = `<i class="fa-solid fa-check"></i> ${data.message}`;
                setTimeout(() => {
                    document.getElementById("bug-report-modal").style.display = "none";
                }, 2000);
            } else {
                statusEl.style.color = "#ef4444";
                statusEl.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> Failed to submit report. Server returned error.`;
            }
        } catch (err) {
            statusEl.style.color = "#ef4444";
            statusEl.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> Network error connecting to server.`;
        }
    });

    document.getElementById("btn-report-bug-about")?.addEventListener("click", triggerBugReport);
    document.getElementById("btn-report-bug-settings")?.addEventListener("click", triggerBugReport);

    // Export profile settings
    document.getElementById("btn-export-profile")?.addEventListener("click", (e) => {
        e.preventDefault();
        window.location.href = "/api/profile/export";
    });

    // Import profile settings
    const importInput = document.getElementById("import-profile-file");
    document.getElementById("btn-import-profile")?.addEventListener("click", (e) => {
        e.preventDefault();
        importInput?.click();
    });

    importInput?.addEventListener("change", (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = async (event) => {
            try {
                const settings = JSON.parse(event.target.result);
                const res = await fetch("/api/profile/import", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        name: settings.name || "",
                        preferred_name: settings.preferred_name || "",
                        age: parseInt(settings.age) || 0,
                        country: settings.country || "",
                        preferences: settings.preferences || ""
                    })
                });
                
                if (!res.ok) throw new Error("Failed to save imported settings");
                alert("Profile settings imported successfully!");
                loadProfileData();
            } catch (err) {
                alert("Import failed: " + err.message);
            }
        };
        reader.readAsText(file);
    });

    // Recovery Screen Actions
    document.getElementById("btn-recovery-restart")?.addEventListener("click", () => {
        window.location.reload();
    });
    
    document.getElementById("btn-recovery-logs")?.addEventListener("click", () => {
        const logs = "ALOY Client Diagnostic Logs\nDate: " + new Date().toISOString() + "\nUser Agent: " + navigator.userAgent + "\n\nError state: " + document.getElementById("recovery-error-detail").textContent;
        const blob = new Blob([logs], { type: "text/plain" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "aloy_diagnostic_logs.txt";
        a.click();
    });

    document.getElementById("btn-recovery-bug")?.addEventListener("click", triggerBugReport);

    // Global Error & Promise Rejection Handlers for Crash Recovery
    window.addEventListener("error", (e) => {
        console.error("Global captured error:", e.error);
        showRecoveryScreen(e.message || "An unexpected runtime exception occurred.");
    });

    window.addEventListener("unhandledrejection", (e) => {
        console.error("Global captured promise rejection:", e.reason);
        const detail = e.reason ? (e.reason.message || e.reason.toString()) : "API request or network communication failed.";
        showRecoveryScreen(detail);
    });

    // ==========================================
    // Diagnostics Dashboard Polling & rendering
    // ==========================================
    let diagnosticsInterval = null;

    function startDiagnosticsPolling() {
        if (diagnosticsInterval) clearInterval(diagnosticsInterval);
        
        loadDiagnosticsData();
        diagnosticsInterval = setInterval(() => {
            const diagView = document.getElementById("view-diagnostics");
            if (diagView && diagView.classList.contains("active")) {
                loadDiagnosticsData();
            } else {
                clearInterval(diagnosticsInterval);
                diagnosticsInterval = null;
            }
        }, 3000);
    }

    async function loadDiagnosticsData() {
        try {
            const res = await fetch("/api/system/diagnostics");
            if (!res.ok) throw new Error("Diagnostics API unreachable");
            const data = await res.json();

            // 1. Update progress bars and values
            // CPU
            const cpuVal = document.getElementById("diag-cpu-val");
            const cpuBar = document.getElementById("diag-cpu-bar");
            if (cpuVal) cpuVal.textContent = `${Math.round(data.cpu_percent)}%`;
            if (cpuBar) cpuBar.style.width = `${data.cpu_percent}%`;

            // RAM
            const ramVal = document.getElementById("diag-ram-val");
            const ramTotal = document.getElementById("diag-ram-total");
            const ramBar = document.getElementById("diag-ram-bar");
            if (ramVal) ramVal.textContent = `${data.ram.used_gb} GB`;
            if (ramTotal) ramTotal.textContent = `/ ${data.ram.total_gb} GB`;
            if (ramBar) ramBar.style.width = `${data.ram.percent}%`;

            // GPU
            const gpuVal = document.getElementById("diag-gpu-val");
            const gpuName = document.getElementById("diag-gpu-name");
            const gpuBar = document.getElementById("diag-gpu-bar");
            if (gpuVal) gpuVal.textContent = data.gpu.detected ? `${Math.round(data.gpu.percent)}%` : "0%";
            if (gpuName) {
                gpuName.textContent = data.gpu.name;
                gpuName.title = data.gpu.name;
            }
            if (gpuBar) gpuBar.style.width = data.gpu.detected ? `${data.gpu.percent}%` : "0%";

            // VRAM
            const vramVal = document.getElementById("diag-vram-val");
            const vramTotal = document.getElementById("diag-vram-total");
            const vramBar = document.getElementById("diag-vram-bar");
            if (vramVal) vramVal.textContent = data.gpu.detected ? `${Math.round(data.gpu.vram_used_mb)} MB` : "0 MB";
            if (vramTotal) vramTotal.textContent = data.gpu.detected ? `/ ${Math.round(data.gpu.vram_total_mb)} MB` : "/ 0 MB";
            if (vramBar && data.gpu.detected && data.gpu.vram_total_mb > 0) {
                vramBar.style.width = `${(data.gpu.vram_used_mb / data.gpu.vram_total_mb) * 100}%`;
            } else if (vramBar) {
                vramBar.style.width = "0%";
            }

            // 2. Services list
            const servicesList = document.getElementById("diag-services-list");
            if (servicesList) {
                servicesList.innerHTML = "";
                const services = [
                    { name: "SQLite Database", ok: data.database.ok, desc: data.database.ok ? `Online · Size: ${data.database.size_kb} KB · Mode: WAL · Migrations: ${data.database.migrations_applied}` : "Offline" },
                    { name: "sqlite-vec Extension", ok: data.sqlite_vec.ok, desc: data.sqlite_vec.message },
                    { name: "Ollama Local API", ok: data.ollama.ok, desc: data.ollama.ok ? `Connected · URL: ${data.ollama.url}` : "Offline / Unreachable" },
                    { name: "Internet Network", ok: data.internet.ok, desc: data.internet.ok ? "Connected to public web services" : "Offline (Local-only mode active)" }
                ];

                services.forEach(s => {
                    const row = document.createElement("div");
                    row.style.cssText = "display: flex; align-items: center; gap: 10px; font-size: 0.85rem;";
                    row.innerHTML = `<i class="fa-solid ${s.ok ? "fa-circle-check" : "fa-circle-exclamation"}" style="color:${s.ok ? "#4ade80" : "#fbbf24"}; font-size: 1.1rem;"></i><div><strong>${s.name}</strong><div style="font-size:0.75rem; color:var(--text-muted); margin-top:2px;">${s.desc}</div></div>`;
                    servicesList.appendChild(row);
                });
            }

            // 3. Microkernel Subsystems list
            const subsystemsList = document.getElementById("diag-subsystems-list");
            if (subsystemsList) {
                subsystemsList.innerHTML = "";
                Object.keys(data.subsystems).forEach(k => {
                    const status = data.subsystems[k];
                    const ok = status === "active";
                    const card = document.createElement("div");
                    card.style.cssText = "background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border); border-radius: 6px; padding: 10px; display: flex; justify-content: space-between; align-items: center; font-size: 0.8rem;";
                    card.innerHTML = `<span style="font-weight:600;">${k.replace("_", " ").toUpperCase()}</span><span class="badge-status ${ok ? "status-green" : "status-gray"}" style="font-size:0.68rem; padding: 2px 6px;">${status}</span>`;
                    subsystemsList.appendChild(card);
                });
            }

        } catch (err) {
            console.error("Error loading diagnostics data:", err);
        }
    }

    // Trigger diagnostics check when view is loaded
    document.querySelector('[data-view="diagnostics"]')?.addEventListener("click", () => {
        startDiagnosticsPolling();
    });

    // Check updates handler
    async function checkUpdates(btn) {
        const updateText = document.getElementById("diag-update-text");
        const downloadBtn = document.getElementById("btn-diag-download-update");
        if (updateText) updateText.textContent = "Checking remote repository version...";
        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Checking...'; }
        if (downloadBtn) downloadBtn.style.display = "none";

        try {
            const res = await fetch("/api/system/update");
            if (!res.ok) throw new Error("Update check failed");
            const data = await res.json();

            if (updateText) {
                if (data.has_update) {
                    updateText.innerHTML = `<strong style="color:var(--accent);">Update available!</strong> Latest version is v${data.latest_version}.<br><span style="font-size:0.75rem; color:var(--text-muted);">${data.release_notes}</span>`;
                    if (downloadBtn) {
                        downloadBtn.href = data.download_url;
                        downloadBtn.style.display = "inline-flex";
                    }
                } else {
                    updateText.textContent = `ALOY is up to date (v${data.current_version}). latest: v${data.latest_version}.`;
                }
            }
        } catch (err) {
            if (updateText) updateText.textContent = "Could not verify update. Internet offline or GitHub API blocked.";
        } finally {
            if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-rotate"></i> Check for Updates'; }
        }
    }

    document.getElementById("btn-diag-check-updates")?.addEventListener("click", (e) => {
        checkUpdates(e.currentTarget);
    });

    // ==========================================================================
    // ALOY Bug Report Logic
    // ==========================================================================
    const btnBugReport = document.getElementById("bug-report-btn");
    if (btnBugReport) {
        btnBugReport.addEventListener("click", triggerBugReport);
    }

    // ==========================================================================
    // ALOY Quit Switch Logic
    // ==========================================================================
    const btnQuitAloy = document.getElementById("btn-quit-aloy");
    const modalQuitOverlay = document.getElementById("quit-modal-overlay");
    const btnCancelQuit = document.getElementById("btn-cancel-quit");
    const btnConfirmQuit = document.getElementById("btn-confirm-quit");
    const shutdownOverlay = document.getElementById("shutdown-success-overlay");

    if (btnQuitAloy && modalQuitOverlay && btnCancelQuit && btnConfirmQuit && shutdownOverlay) {
        btnQuitAloy.addEventListener("click", () => {
            modalQuitOverlay.style.display = "flex";
        });

        btnCancelQuit.addEventListener("click", () => {
            modalQuitOverlay.style.display = "none";
        });

        btnConfirmQuit.addEventListener("click", async () => {
            modalQuitOverlay.style.display = "none";
            try {
                const res = await fetch("/api/system/quit", { method: "POST" });
                shutdownOverlay.style.display = "flex";
            } catch (err) {
                console.error("Quit signal error:", err);
                shutdownOverlay.style.display = "flex";
            }
        });
    }
});


