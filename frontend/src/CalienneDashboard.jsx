import { useState, useEffect, useRef, useCallback } from "react";
import "./dashboard.css";

import { AGENTS } from "./constants/agents.js";
import { INIT_MODELS } from "./constants/models.js";
import { SEED_CONVERSATIONS } from "./constants/conversations.js";
import { LOADING_DELAY, PANEL_LOAD_DELAY, TOAST_DISMISS_DELAY } from "./constants/timing.js";
import { MAX_MESSAGE_CHARS } from "./constants/input.js";
import { randId } from "./utils/id.js";
import { truncate } from "./utils/format.js";
import { createLatestQueue } from "./utils/latestQueue.js";
import { useKeyboardShortcut } from "./hooks/useKeyboardShortcut.js";
import { useEscapeKey } from "./hooks/useEscapeKey.js";

import Header from "./components/Header.jsx";
import Sidebar from "./components/Sidebar.jsx";
import HomeHero from "./components/HomeHero.jsx";
import ChatThread from "./components/ChatThread.jsx";
import PlaceholderView from "./components/PlaceholderView.jsx";
import ChatInputBar from "./components/ChatInputBar.jsx";
import RightPanel from "./components/RightPanel.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import ToastStack from "./components/ToastStack.jsx";
import ModelApiStudioModal from "./components/ModelApiStudioModal.jsx";

/**
 * Three tiers, not two. The previous version only distinguished "<900px:
 * overlay drawers" from ">=900px: full desktop, both panels open by default."
 * That's wrong for the 900\u20131199px band \u2014 landscape tablets and small
 * laptops \u2014 where "both panels open" reserves 272+312=584px for chrome and
 * leaves as little as ~316px for actual content. That's not broken the way
 * "both" is broken below 900px (no backdrop trap here, both panels can
 * genuinely coexist), it's just a bad default. Pick a better one.
 */
function computeInitialLayoutMode() {
  if (typeof window === "undefined") return "both";
  const w = window.innerWidth;
  if (w < 900) return "hidden";
  if (w < 1200) return "left";
  return "both";
}

export default function CalienneDashboard({ onExitLanding = null }) {
  const [isNarrow, setIsNarrow] = useState(() =>
    typeof window !== "undefined" && window.matchMedia("(max-width: 900px)").matches
  );
  // Below 900px both rails become position:fixed overlays with a full-viewport
  // backdrop (see .backdrop in CSS). "both" at that width means two overlays
  // stacked on top of the chat input with no way to reach it underneath \u2014
  // that combination is simply not a legal state, not just an unlikely one.
  const [layoutMode, setLayoutModeRaw] = useState(computeInitialLayoutMode); // left | right | both | hidden

  useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia("(max-width: 900px)");
    function handle(e) {
      setIsNarrow(e.matches);
      // Crossing into narrow while sitting on "both" would otherwise strand the
      // user behind an opaque backdrop with no visible control to dismiss it.
      if (e.matches) setLayoutModeRaw((prev) => (prev === "both" ? "hidden" : prev));
    }
    mq.addEventListener("change", handle);
    return () => mq.removeEventListener("change", handle);
  }, []);

  const changeLayoutMode = useCallback((mode) => {
    setLayoutModeRaw(isNarrow && mode === "both" ? "hidden" : mode);
  }, [isNarrow]);

  const sidebarOpen = layoutMode === "both" || layoutMode === "left";
  const rightOpen = layoutMode === "both" || layoutMode === "right";

  const [view, setView] = useState("home");
  const [search, setSearch] = useState("");
  const searchRef = useRef(null);
  const [loadingConversations, setLoadingConversations] = useState(true);

  useEffect(() => {
    const t = setTimeout(() => setLoadingConversations(false), LOADING_DELAY);
    return () => clearTimeout(t);
  }, []);

  const [conversations, setConversations] = useState(() => {
    if (typeof window === "undefined") return SEED_CONVERSATIONS;
    try {
      const saved = localStorage.getItem("calienne_saved_conversations");
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed;
      }
    } catch {
      // Ignore malformed saved conversations.
    }
    return SEED_CONVERSATIONS;
  });
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [typingAgent, setTypingAgent] = useState(null);
  const [streaming, setStreaming] = useState(false);
  const sendingRef = useRef(false);
  const abortRef = useRef(null);
  const activeConversationRef = useRef(null);
  const dbLoadedRef = useRef(false);
  const statusInFlightRef = useRef(false);
  const saveQueuesRef = useRef(new Map());
  const queueConversationSave = useCallback((conversation) => {
    let queue = saveQueuesRef.current.get(conversation.id);
    if (!queue) {
      queue = createLatestQueue(async (latestConversation) => {
        const response = await fetch("/api/conversations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({
            id: String(latestConversation.id),
            title: latestConversation.title || "Conversation",
            mode: latestConversation.mode || "HYBRID",
            transcript: latestConversation.transcript || [],
          }),
        });
        if (!response.ok) throw new Error(`Conversation save failed (${response.status})`);
      });
      saveQueuesRef.current.set(conversation.id, queue);
    }
    return queue(conversation);
  }, []);

  const [authVerified, setAuthVerified] = useState(false);
  const [dbHydrated, setDbHydrated] = useState(false);
  const [currentUser, setCurrentUser] = useState(null);

  useEffect(() => {
    if (typeof window !== "undefined") {
      try {
        localStorage.setItem("calienne_saved_conversations", JSON.stringify(conversations));
      } catch {
        // Ignore storage write failures.
      }
    }
    if (conversations.length > 0 && authVerified && dbHydrated) {
      const active = conversations.find((c) => c.id === activeId);
      if (active && active.id) {
        queueConversationSave(active).catch(() => {});
      }
    }
  }, [conversations, activeId, authVerified, dbHydrated, queueConversationSave]);

  useEffect(() => {
    if (!activeId) return;
    setConversations((prev) =>
      prev.map((c) => (c.id === activeId ? { ...c, transcript: messages } : c))
    );
  }, [activeId, messages]);

  const fetchStatus = useCallback(async () => {
    if (statusInFlightRef.current) return;
    statusInFlightRef.current = true;
    try {
      const res = await fetch("/api/status", { credentials: "include" });
      if (res.status === 401) {
        localStorage.removeItem("access_token");
        localStorage.removeItem("user_email");
        localStorage.removeItem("refresh_token");
        window.location.href = "/login";
        return;
      }
      if (!res.ok) {
        setAuthVerified(true);
        setStats((prev) => ({ ...prev, agentsOnline: "Offline" }));
        return;
      }
      setAuthVerified(true);
      if (!dbLoadedRef.current) {
        dbLoadedRef.current = true;
        try {
          const conversationsResponse = await fetch("/api/conversations", { credentials: "include" });
          if (!conversationsResponse.ok) throw new Error("Conversation hydration failed");
          const convData = await conversationsResponse.json();
          if (!Array.isArray(convData?.conversations)) throw new Error("Invalid conversation payload");
          setConversations(convData.conversations);
          setActiveId(null);
          activeConversationRef.current = null;
          setMessages([]);
          setDbHydrated(true);
        } catch {
          dbLoadedRef.current = false;
        }
      }
      const data = await res.json();
      if (data) {
        setCurrentUser(data.user || null);
        if (data.providers && Array.isArray(data.providers)) {
          const onlineCount = data.providers.filter((p) => p.status === "healthy" || (p.status === "degraded" && p.is_available !== false)).length;
          setStats((prev) => ({
            ...prev,
            agentsOnline: `${onlineCount}/${data.providers.length || 6}`,
            tokens: data.telemetry?.total_tokens ?? prev.tokens,
            avgResponse: data.telemetry?.avg_response_s ?? prev.avgResponse,
            successRate: data.telemetry?.success_rate ?? prev.successRate,
            sparkline: data.telemetry?.sparkline ?? prev.sparkline,
          }));
        }
        if (data.models && Array.isArray(data.models) && data.models.length > 0) {
          setModels(data.models);
        }
      }
    } catch {
      setAuthVerified(true);
      setStats((prev) => ({ ...prev, agentsOnline: "Offline" }));
    } finally {
      statusInFlightRef.current = false;
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const iv = setInterval(fetchStatus, 5000);
    return () => clearInterval(iv);
  }, [fetchStatus]);

  const [models, setModels] = useState(INIT_MODELS);
  const [inputValue, setInputValue] = useState("");
  const inputRef = useRef(null);

  const [stats, setStats] = useState({ agentsOnline: "6/6", tokens: 0, avgResponse: "—", successRate: "—", sparkline: [] });
  const [rightPanelLoaded, setRightPanelLoaded] = useState(false);
  const [studioOpen, setStudioOpen] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setRightPanelLoaded(true), PANEL_LOAD_DELAY);
    return () => clearTimeout(t);
  }, []);

  const [notifications, setNotifications] = useState([
    { id: "n1", text: "Judge flagged confirmation bias in 2 responses", time: "12m ago", read: false },
    { id: "n2", text: "mistral-large deactivated \u2014 rate limit", time: "1h ago", read: false },
    { id: "n3", text: "Weekly telemetry report is ready", time: "Yesterday", read: true },
  ]);

  const [toasts, setToasts] = useState([]);
  // Stable across renders (empty dep array, closes over nothing but setState
  // setters, which React itself guarantees are stable). Every handler below
  // that calls pushToast can safely depend on it without that dependency
  // forcing the handler to be recreated on every render.
  const pushToast = useCallback((text, kind = "success", action = null) => {
    const id = randId();
    setToasts((t) => [...t, { id, text, kind, action }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), TOAST_DISMISS_DELAY);
  }, []);

  const toggleModel = useCallback(async (id) => {
    const target = models.find((model) => model.full_id === id);
    if (!target) return;
    const activeCount = models.filter((model) => model.active).length;
    if (target.active && activeCount === 1) {
      pushToast("At least one model must stay active", "error");
      return;
    }
    try {
      const response = await fetch("/api/models/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ id, active: !target.active }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Model update failed (${response.status})`);
      setModels(data.models || models);
    } catch (error) {
      pushToast(error.message, "error");
    }
  }, [models, pushToast]);

  const addModel = useCallback(async (name) => {
    const exists = models.some((m) => m.name.toLowerCase() === name.toLowerCase());
    if (exists) {
      pushToast(`${name} is already active`);
      return;
    }
    const cleanId = name.split("/").pop().replace(/\./g, "").replace(/-/g, "");
    const newModel = { id: cleanId || randId(), name: name.split("/").pop(), latency: "—", active: true };
    try {
      const response = await fetch("/api/models/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ model: name, role: "generation" }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Model registration failed (${response.status})`);
      setModels(data.models || [...models, newModel]);
      pushToast(`${name} added to orchestrator`);
      return true;
    } catch (error) {
      pushToast(error.message, "error");
      return false;
    }
  }, [models, pushToast]);

  const cancelActiveStream = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    sendingRef.current = false;
    setStreaming(false);
    setTypingAgent(null);
  }, []);

  const openConversation = useCallback((conv) => {
    cancelActiveStream();
    activeConversationRef.current = conv.id;
    setActiveId(conv.id);
    setMessages((conv.transcript || []).map((m) => ({ ...m, id: randId() })));
    setView("home");
  }, [cancelActiveStream]);

  const newConversation = useCallback(() => {
    cancelActiveStream();
    activeConversationRef.current = null;
    setActiveId(null);
    setMessages([]);
    setView("home");
    setInputValue("");
  }, [cancelActiveStream]);

  const deleteConversation = useCallback(async (convId) => {
    if (activeConversationRef.current === convId) cancelActiveStream();
    try {
      await saveQueuesRef.current.get(convId)?.flush().catch(() => {});
      const response = await fetch(`/api/conversations/${encodeURIComponent(convId)}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!response.ok) throw new Error(`Delete failed (${response.status})`);
    } catch (error) {
      pushToast(error.message, "error");
      return;
    }
    saveQueuesRef.current.delete(convId);
    setConversations((prev) => prev.filter((c) => c.id !== convId));
    if (activeId === convId) {
      pendingTimeouts.current.forEach(clearTimeout);
      pendingTimeouts.current = [];
      sendingRef.current = false;
      setActiveId(null);
      activeConversationRef.current = null;
      setMessages([]);
      setTypingAgent(null);
      setStreaming(false);
    }
    pushToast("Conversation deleted");
  }, [activeId, cancelActiveStream, pushToast]);

  const pendingTimeouts = useRef([]);
  useEffect(() => () => pendingTimeouts.current.forEach(clearTimeout), []);

  function handleSend(text) {
    const finalText = (text ?? inputValue).trim();
    if (!finalText || streaming || sendingRef.current) return;
    if (finalText.length > MAX_MESSAGE_CHARS) {
      pushToast(`Messages are limited to ${MAX_MESSAGE_CHARS} characters`, "error");
      return;
    }
    sendingRef.current = true;
    let convId = activeId;
    if (!convId) {
      convId = randId();
      const conv = { id: convId, title: truncate(finalText, 48), time: "Just now", mode: "Automatic", agentsCount: AGENTS.length, score: null, transcript: [] };
      setConversations((prev) => [conv, ...prev]);
      setActiveId(convId);
    }
    activeConversationRef.current = convId;

    setMessages((m) => [...m, { id: randId(), role: "user", text: finalText }]);
    setInputValue("");
    setStreaming(true);
    setView("home");
    setTimeout(() => inputRef.current?.focus(), 0);

    const abortController = new AbortController();
    abortRef.current = abortController;

    (async () => {
      try {
        const headers = { "Content-Type": "application/json" };

        const response = await fetch("/api/query/stream", {
          method: "POST",
          headers,
          credentials: "include",
          body: JSON.stringify({ query: finalText }),
          signal: abortController.signal,
        });

        if (!response.ok) {
          if (response.status === 401) {
            pushToast("Authentication required. Redirecting to login...");
            setTimeout(() => { window.location.href = "/login"; }, 1500);
            return;
          }
          const errText = await response.text().catch(() => "");
          throw new Error(`Server error (${response.status}): ${errText || response.statusText}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed.startsWith("data: ")) continue;

            try {
              const envelope = JSON.parse(trimmed.slice(6));
               const eventType = envelope.event;
               const payload = envelope.data || {};
               if (activeConversationRef.current !== convId) continue;

              if (eventType === "agent_started" || eventType === "progress") {
                const agentName = payload.agent || payload.agent_name;
                if (agentName) setTypingAgent(agentName);
              } else if (eventType === "agent_completed" || eventType === "draft_answer") {
                const agentName = payload.agent || payload.agent_name || "Agent";
                const content = payload.final_answer || payload.content || payload.answer;
                if (content && typeof content === "string") {
                  setMessages((prev) => {
                    let lastUserIdx = -1;
                    for (let i = prev.length - 1; i >= 0; i--) {
                      if (prev[i].role === "user") { lastUserIdx = i; break; }
                    }
                    const existingIdx = prev.findIndex((msg, i) => i > lastUserIdx && msg.role === "agent" && (msg.agentId || "").toLowerCase() === agentName.toLowerCase());
                    if (existingIdx !== -1) {
                      const updated = [...prev];
                      updated[existingIdx] = { ...updated[existingIdx], text: content };
                      return updated;
                    }
                    return [...prev, { id: randId(), role: "agent", agentId: agentName, text: content }];
                  });
                }
              } else if (eventType === "result") {
                const resData = payload.payload || payload;
                const finalAnswer = resData.answer ?? resData.final_answer;
                if (finalAnswer) {
                  setMessages((prev) => {
                    let lastUserIdx = -1;
                    for (let i = prev.length - 1; i >= 0; i--) {
                      if (prev[i].role === "user") { lastUserIdx = i; break; }
                    }
                    const existingIdx = prev.findIndex((msg, i) => i > lastUserIdx && msg.role === "agent" && (msg.agentId || "").toLowerCase() === "synthesis");
                    if (existingIdx !== -1) {
                      const updated = [...prev];
                      updated[existingIdx] = { ...updated[existingIdx], text: finalAnswer };
                      return updated;
                    }
                    return [...prev, { id: randId(), role: "agent", agentId: "Synthesis", text: finalAnswer }];
                  });
                }
              } else if (eventType === "error") {
                pushToast(`Pipeline Error: ${payload.message || "Unknown error"}`);
              }
            } catch {
              // Ignore partial or unparseable JSON line
            }
          }
        }
      } catch (err) {
        if (err.name !== "AbortError" && activeConversationRef.current === convId) {
          pushToast(`Backend error: ${err.message}`);
          setMessages((m) => [...m, { id: randId(), role: "agent", agentId: "System", text: `Could not reach backend: ${err.message}` }]);
        }
      } finally {
        if (abortRef.current === abortController) {
          sendingRef.current = false;
          setStreaming(false);
          setTypingAgent(null);
          abortRef.current = null;
          fetchStatus();
        }
      }
    })();
  }

  const stopGeneration = useCallback(() => {
    cancelActiveStream();
    pendingTimeouts.current.forEach(clearTimeout);
    pendingTimeouts.current = [];
    pushToast("Generation stopped");
  }, [cancelActiveStream, pushToast]);

  const markAllRead = useCallback(() => {
    setNotifications((n) => n.map((x) => ({ ...x, read: true })));
  }, []);

  const onLogout = useCallback(async () => {
    try {
      await fetch("/auth/logout", {
        method: "POST",
        credentials: "include",
      });
    } finally {
      localStorage.removeItem("access_token");
      localStorage.removeItem("user_email");
      localStorage.removeItem("refresh_token");
      window.location.href = "/login";
    }
  }, []);

  const ensurePanels = useCallback((which) => {
    if (which === "sidebar" && (layoutMode === "right" || layoutMode === "hidden")) {
      changeLayoutMode(isNarrow ? "left" : "both");
    }
    if (which === "right" && (layoutMode === "left" || layoutMode === "hidden")) {
      changeLayoutMode(isNarrow ? "right" : "both");
    }
  }, [layoutMode, isNarrow, changeLayoutMode]);

  const openSettingsView = useCallback(() => setView("settings"), []);
  const openBothPanels = useCallback(() => changeLayoutMode("both"), [changeLayoutMode]);
  const openTelemetryPanel = useCallback(() => ensurePanels("right"), [ensurePanels]);
  const goBackToConversationList = useCallback(() => {
    if (isNarrow) changeLayoutMode("left");
  }, [changeLayoutMode, isNarrow]);
  const toggleSidebarMobile = useCallback(
    () => changeLayoutMode(sidebarOpen ? "hidden" : "left"),
    [changeLayoutMode, sidebarOpen]
  );
  const closeMobilePanels = useCallback(() => {
    if (isNarrow && (sidebarOpen || rightOpen)) {
      changeLayoutMode("hidden");
    }
  }, [changeLayoutMode, isNarrow, rightOpen, sidebarOpen]);

  useEscapeKey(closeMobilePanels);

  useKeyboardShortcut("k", useCallback(() => {
    if (!sidebarOpen) changeLayoutMode(isNarrow ? "left" : "both");
    setTimeout(() => searchRef.current?.focus(), 50);
  }, [sidebarOpen, changeLayoutMode, isNarrow]));
  useKeyboardShortcut("n", useCallback(() => newConversation(), [newConversation]));
  useKeyboardShortcut("/", useCallback(() => {
    inputRef.current?.focus();
  }, []), { meta: false, allowInInput: false });

  const activeConv = conversations.find((c) => c.id === activeId);

  if (!authVerified) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        backgroundColor: '#0a0a0a',
        color: '#8f8f8f',
        fontFamily: 'system-ui, sans-serif'
      }}>
        <span>Verifying secure session...</span>
      </div>
    );
  }

  return (
    <div className="calienne-app">
      <div className="fx-scanlines" aria-hidden="true" />
      <div className="fx-noise" aria-hidden="true" />

      <Header
        models={models} toggleModel={toggleModel} addModel={addModel}
        isAdmin={!currentUser || currentUser?.role === "admin" || currentUser?.role === "user"} userEmail={currentUser?.email}
        onOpenSettings={openSettingsView}
        onOpenStudio={() => setStudioOpen(true)}
        layoutMode={layoutMode} setLayoutMode={changeLayoutMode} isNarrow={isNarrow}
        notifications={notifications} markAllRead={markAllRead}
        onMissionControl={openBothPanels}
        onTelemetry={openTelemetryPanel}
        onLogout={onLogout}
        onOpenSidebarMobile={toggleSidebarMobile}
        onExitLanding={onExitLanding}
      />

      <div className="body">
        <Sidebar
          open={sidebarOpen} conversations={conversations} activeId={activeId}
          onSelect={openConversation} onDelete={deleteConversation} onNew={newConversation}
          search={search} setSearch={setSearch} view={view} setView={setView}
          searchRef={searchRef} loading={loadingConversations} isNarrow={isNarrow} streaming={streaming}
          onClose={closeMobilePanels}
        />

        <main className="center">
          <ErrorBoundary>
            {view === "home" ? (
              activeId ? (
                <div key={activeId} className="thread-enter">
                <ChatThread
                  messages={messages}
                  typingAgent={typingAgent}
                  title={activeConv?.title || ""}
                  mode={activeConv?.mode || "Automatic"}
                  agentsCount={activeConv?.agentsCount ?? AGENTS.length}
                  pushToast={pushToast}
                  onBack={goBackToConversationList}
                  isNarrow={isNarrow}
                />
                </div>
              ) : (
                <HomeHero
                  onQuickPrompt={(t) => handleSend(t)}
                  onFocusInput={() => inputRef.current?.focus()}
                  onOpenSettings={openSettingsView}
                  onOpenTelemetry={openTelemetryPanel}
                />
              )
            ) : view === "settings" || view === "integrations" ? (
              <div className="settings-page-wrapper">
                <ModelApiStudioModal
                  inline={true}
                  isOpen={true}
                  models={models}
                  onToggleModel={toggleModel}
                  onRefresh={fetchStatus}
                  onClose={() => setView("home")}
                />
              </div>
            ) : (
              <PlaceholderView view={view} />
            )}
          </ErrorBoundary>

          {view === "home" && (
            <ChatInputBar
              value={inputValue} onChange={setInputValue} onSend={() => handleSend()} onStop={stopGeneration}
              streaming={streaming} inputRef={inputRef}
            />
          )}
        </main>

        <ErrorBoundary>
          <RightPanel
            open={rightOpen} stats={stats} models={models}
            conversations={conversations} activeId={activeId} onSelect={openConversation}
            isNarrow={isNarrow} isLoaded={rightPanelLoaded} onClose={closeMobilePanels}
          />
        </ErrorBoundary>
      </div>

      {(sidebarOpen || rightOpen) && <div className="backdrop" onClick={closeMobilePanels} aria-hidden="true" />}
      <ModelApiStudioModal
        isOpen={studioOpen && (!currentUser || currentUser?.role === "admin")}
        onClose={() => setStudioOpen(false)}
        models={models}
        onToggleModel={toggleModel}
        onRefresh={fetchStatus}
      />
      <ToastStack toasts={toasts} />
    </div>
  );
}
