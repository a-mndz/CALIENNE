import { useEffect, useState, useCallback, useRef, useMemo, lazy, Suspense } from 'react';
import Sidebar from './components/Sidebar';
import ChatWindow from './components/ChatWindow';
import InputBox from './components/InputBox';
import ProviderStatusBar from './components/ProviderStatusBar';
import NotificationStack from './components/NotificationStack';
import { useChatStore } from './store/useChatStore';
import { useSettingsStore } from './store/useSettingsStore';
import { useNotificationStore } from './store/useNotificationStore';
import { useSendQuery } from './hooks/useSendQuery';
import { fetchProviderStatus, setConnectionLostCallback } from './api/client';
import { isAuthenticated, redirectToLogin } from './utils/auth';

const FONT_SIZE_MAP = { small: '14px', medium: '16px', large: '18px' };


const MissionControlPanel = lazy(() => import('./components/MissionControlPanel'));
const SettingsPanel = lazy(() => import('./components/SettingsPanel'));
const TelemetryDrawer = lazy(() => import('./components/TelemetryDrawer'));

const HEALTH_POLL_INTERVAL = 30000;

function normalizeExecutionMode(data) {
  if (data?.executionMode) return data.executionMode;

  const mode = data?.mode?.toUpperCase?.();
  const modeLabels = {
    FREE: 'Fallback',
    HYBRID: 'Multi-Agent',
    PAID: 'Multi-Agent',
    UNKNOWN: 'Multi-Agent',
  };

  return modeLabels[mode] || 'Multi-Agent';
}

function deriveTimelineEvents(agentStates) {
  const events = [];
  let baseTime = Date.now() - 10000;

  for (const [agentName, state] of Object.entries(agentStates || {})) {
    if (state.claims) {
      for (const claim of state.claims) {
        events.push({
          id: claim.id,
          timestamp: baseTime++,
          agent: agentName,
          eventType: 'claim_created',
          data: claim,
        });
      }
    }
    if (state.warnings) {
      for (const warning of state.warnings) {
        events.push({
          id: warning.id,
          timestamp: baseTime++,
          agent: agentName,
          eventType: 'warning_issued',
          data: warning,
        });
      }
    }
    if (state.status === 'complete' || state.status === 'done') {
      events.push({
        id: `${agentName}-complete`,
        timestamp: baseTime++,
        agent: agentName,
        eventType: 'complete',
        data: {},
      });
    }
  }

  return events.sort((a, b) => a.timestamp - b.timestamp);
}

function buildGraphData(agentStates) {
  const nodes = [];
  const edges = [];

  for (const [agentName, state] of Object.entries(agentStates || {})) {
    if (state.claims) {
      for (const claim of state.claims) {
        nodes.push({
          id: claim.id,
          label: claim.text || '',
          agent: agentName,
          confidence: claim.confidence || 0.5,
          validationStatus: claim.validationStatus || 'pending',
          fullText: claim.text || '',
        });
      }
    }
  }

  for (let i = 1; i < nodes.length; i++) {
    edges.push({
      id: `edge-${nodes[i - 1].id}-${nodes[i].id}`,
      source: nodes[i - 1].id,
      target: nodes[i].id,
      type: 'supports',
    });
  }

  return { nodes, edges };
}

function LoadingFallback() {
  return (
    <div className="flex items-center justify-center h-full w-full">
      <div className="h-5 w-5 border-2 border-cyan-400/30 border-t-cyan-400 rounded-full animate-spin" />
    </div>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(() => isAuthenticated());

  const conversations = useChatStore((s) => s.conversations);
  const activeId = useChatStore((s) => s.activeId);
  const telemetry = useChatStore((s) => s.telemetry);
  const providerHealth = useChatStore((s) => s.providerHealth);
  const setProviderHealth = useChatStore((s) => s.setProviderHealth);
  const newConversation = useChatStore((s) => s.newConversation);
  const selectConversation = useChatStore((s) => s.selectConversation);
  const deleteConversation = useChatStore((s) => s.deleteConversation);

  const missionControlOpen = useSettingsStore((s) => s.missionControlOpen);
  const updateSetting = useSettingsStore((s) => s.updateSetting);

  const { send, stage, agentStates, partialData, progress, elapsedMs, liveEvents } = useSendQuery();
  const [telemetryOpen, setTelemetryOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [executionMode, setExecutionMode] = useState('Multi-Agent');
  const [preservedText, setPreservedText] = useState(null);
  const [connectionLost, setConnectionLost] = useState(false);

  const fontSize = useSettingsStore((s) => s.fontSize);
  const messageDensity = useSettingsStore((s) => s.messageDensity);
  const autoExpandReasoning = useSettingsStore((s) => s.autoExpandReasoning);

  const prevProviderHealth = useRef([]);
  const prevAgentWarningsRef = useRef({});

  const activeConversation = conversations[activeId];
  const pending = stage !== 'idle' && stage !== 'done' && stage !== 'error';

  const notify = useNotificationStore((s) => s.addNotification);

  useEffect(() => {
    if (!authed) {
      redirectToLogin();
    }
  }, [authed]);

  useEffect(() => {
    document.documentElement.style.fontSize = FONT_SIZE_MAP[fontSize] || '16px';
  }, [fontSize]);

  useEffect(() => {
    setConnectionLostCallback((attempt) => {
      setConnectionLost(true);
      useNotificationStore.getState().warning(
        `Connection lost. Retrying (attempt ${attempt}/3)...`
      );
    });

    return () => setConnectionLostCallback(null);
  }, []);

  useEffect(() => {
    if (stage === 'done' || stage === 'idle') {
      setConnectionLost(false);
    }
  }, [stage]);

  useEffect(() => {
    if (!authed) return;

    let active = true;

    const poll = async () => {
      const data = await fetchProviderStatus();
      if (!active) return;

      setExecutionMode(normalizeExecutionMode(data));

      let mapped;
      if (data?.providers && Array.isArray(data.providers)) {
        mapped = data.providers.map((p) => ({
          name: typeof p === 'string' ? p : (p.name || p.provider || 'Unknown'),
          status: typeof p === 'string' ? 'online' : (p.status || 'online'),
        }));
        if (mapped.length === 0) {
          mapped = [
            { name: 'Groq', status: 'unknown' },
            { name: 'OpenRouter', status: 'unknown' },
            { name: 'Local Fallback', status: 'unknown' },
          ];
        }
      } else {
        mapped = [
          { name: 'Groq', status: 'unknown' },
          { name: 'OpenRouter', status: 'unknown' },
          { name: 'Local Fallback', status: 'unknown' },
        ];
      }

      if (prevProviderHealth.current.length > 0) {
        for (const provider of mapped) {
          const prev = prevProviderHealth.current.find((p) => p.name === provider.name);
          if (prev && prev.status === 'online' && provider.status === 'offline') {
            useNotificationStore.getState().warning(`${provider.name} went offline`);
          }
          if (prev && prev.status === 'offline' && provider.status === 'online') {
            useNotificationStore.getState().success(`${provider.name} is back online`);
            setConnectionLost(false);
          }
        }
      }

      prevProviderHealth.current = mapped;
      setProviderHealth(mapped);
    };

    poll();
    const interval = setInterval(poll, HEALTH_POLL_INTERVAL);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [authed, setProviderHealth]);

  const prevStage = useRef(stage);
  useEffect(() => {
    if (prevStage.current !== 'error' && stage === 'error') {
      useNotificationStore.getState().error('Pipeline failed. Check the chat for details.');
    }
    if (prevStage.current === 'error' && stage === 'idle') {
      useNotificationStore.getState().success('Connection restored');
    }
    prevStage.current = stage;
  }, [stage]);

  useEffect(() => {
    for (const [agentName, agentState] of Object.entries(agentStates || {})) {
      const prevWarnings = prevAgentWarningsRef.current[agentName] || 0;
      const currentWarnings = agentState?.progress?.filter?.(
        (p) => p.message?.toLowerCase?.().includes('warning')
      ).length || 0;

      if (currentWarnings > prevWarnings && agentState.status === 'running') {
        const newCount = currentWarnings - prevWarnings;
        if (newCount > 0) {
          useNotificationStore.getState().warning(
            `${agentName} agent issued ${newCount} warning${newCount > 1 ? 's' : ''}`
          );
        }
      }

      prevAgentWarningsRef.current[agentName] = currentWarnings;
    }
  }, [agentStates]);

  const handleSend = useCallback(async (text) => {
    const result = await send(activeId, text);
    if (!result?.success && !result?.aborted && result?.query) {
      setPreservedText(result.query);
    }
  }, [send, activeId]);

  const handleRetry = useCallback(() => {
    const msgs = activeConversation?.messages ?? [];
    const lastUserMessage = [...msgs].reverse().find((m) => m.role === 'user');
    if (lastUserMessage?.content) {
      send(activeId, lastUserMessage.content);
    }
  }, [send, activeId, activeConversation]);

  const closeSidebar = useCallback(() => setSidebarOpen(false), []);

  const toggleMissionControl = useCallback(() => {
    updateSetting('missionControlOpen', !missionControlOpen);
  }, [missionControlOpen, updateSetting]);

  const toggleSettings = useCallback(() => {
    setSettingsOpen((prev) => !prev);
  }, []);

  const handlePreservedTextConsumed = useCallback(() => {
    setPreservedText(null);
  }, []);

  const timelineEvents = useMemo(() => deriveTimelineEvents(agentStates), [agentStates]);
  const graphData = useMemo(() => buildGraphData(agentStates), [agentStates]);

  if (!authed) {
    return null;
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gradient-to-br from-surface-900 via-surface-900 to-[#0c0a1a] text-slate-100">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={selectConversation}
        onNew={newConversation}
        onDelete={deleteConversation}
        open={sidebarOpen}
        onClose={closeSidebar}
      />
      <div className="flex flex-1 flex-col min-w-0">
        <ProviderStatusBar
          providers={providerHealth}
          executionMode={executionMode}
          onToggleTelemetry={() => setTelemetryOpen(true)}
          onToggleSidebar={() => setSidebarOpen(true)}
          onToggleMissionControl={toggleMissionControl}
          onToggleSettings={toggleSettings}
          missionControlActive={missionControlOpen}
        />

        {connectionLost && (
          <div className="mx-4 mt-2 md:mx-8 rounded-lg border border-amber-400/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-200 flex items-center gap-2" role="alert">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-500" />
            </span>
            Connection lost — attempting to reconnect...
          </div>
        )}

        <main id="main-content" className="flex flex-1 flex-col min-h-0" tabIndex={-1}>
          <ChatWindow
            messages={activeConversation?.messages ?? []}
            currentStage={stage}
            agentStates={agentStates}
            partialData={partialData}
            onSuggestion={handleSend}
            onRetry={handleRetry}
            messageDensity={messageDensity}
            autoExpandReasoning={autoExpandReasoning}
          />
          <InputBox
            onSend={handleSend}
            disabled={pending}
            preservedText={preservedText}
            onPreservedTextConsumed={handlePreservedTextConsumed}
          />
        </main>
      </div>

      <Suspense fallback={<LoadingFallback />}>
        {missionControlOpen && (
          <MissionControlPanel
            open={missionControlOpen}
            onToggle={toggleMissionControl}
            agentStates={agentStates}
            stage={stage}
            progress={progress}
            elapsedMs={elapsedMs}
            timelineEvents={timelineEvents}
            graphData={graphData}
          />
        )}
      </Suspense>

      <Suspense fallback={<LoadingFallback />}>
        <TelemetryDrawer
          open={telemetryOpen}
          onClose={() => setTelemetryOpen(false)}
          telemetry={telemetry}
          liveEvents={liveEvents}
          providers={providerHealth}
        />
      </Suspense>

      <Suspense fallback={null}>
        <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      </Suspense>

      <NotificationStack />
    </div>
  );
}
