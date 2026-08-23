import { useState, useCallback, useMemo, useRef, useEffect, lazy, Suspense } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import FocusTrap from 'focus-trap-react';
import {
  X,
  Pin,
  PinOff,
  ChevronLeft,
  ChevronRight,
  GitBranch,
  Users,
  Clock,
  Network,
  BarChart3,
  Loader2,
} from 'lucide-react';
import PipelineStatus from './PipelineStatus';
import AgentCard from './AgentCard';
import ReasoningTimeline from './ReasoningTimeline';
import { useSettingsStore } from '../store/useSettingsStore';

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < 768);
  useEffect(() => {
    const handler = () => setIsMobile(window.innerWidth < 768);
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);
  return isMobile;
}

const ReasoningGraph = lazy(() => import('./ReasoningGraph'));

const TABS = [
  { key: 'pipeline', label: 'Pipeline', icon: GitBranch },
  { key: 'agents', label: 'Agents', icon: Users },
  { key: 'timeline', label: 'Timeline', icon: Clock },
  { key: 'graph', label: 'Graph', icon: Network },
  { key: 'metrics', label: 'Metrics', icon: BarChart3 },
];

const MIN_WIDTH = 300;
const MAX_WIDTH = 600;
const DEFAULT_WIDTH = 420;

function GraphFallback() {
  return (
    <div className="flex items-center justify-center h-64">
      <Loader2 className="h-5 w-5 text-cyan-400 animate-spin" />
    </div>
  );
}

function PipelineTab({ stage, progress, elapsedMs, agentStates }) {
  return (
    <div className="space-y-4 p-4">
      <PipelineStatus
        currentStage={stage}
        progress={progress}
        elapsedMs={elapsedMs}
        agentStates={agentStates}
      />

      <div className="rounded-xl glass-panel p-3">
        <p className="text-[10px] uppercase tracking-wider text-slate-500 font-medium mb-2">
          Stage Duration Breakdown
        </p>
        <div className="space-y-1.5">
          {Object.entries(agentStates || {}).map(([name, state]) => (
            <div key={name} className="flex items-center gap-2 text-xs">
              <span className="text-slate-400 w-20 flex-shrink-0 truncate">{name}</span>
              <div className="flex-1 h-2 bg-white/5 rounded-full overflow-hidden">
                <div
                  className="h-full bg-cyan-400/50 rounded-full transition-all duration-300"
                  style={{ width: `${typeof state.progress === 'number' ? state.progress : 0}%` }}
                />
              </div>
              <span className="text-slate-500 font-mono w-10 text-right">
                {typeof state.progress === 'number' ? `${state.progress}%` : '\u2014'}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function AgentsTab({ agentStates }) {
  const [expanded, setExpanded] = useState({});

  const toggle = useCallback((name) => {
    setExpanded((prev) => ({ ...prev, [name]: !prev[name] }));
  }, []);

  const entries = Object.entries(agentStates || {});

  return (
    <div className="p-4 space-y-3 overflow-y-auto">
      {entries.length === 0 && (
        <div className="text-center py-8">
          <p className="text-sm text-slate-500">No agent data</p>
          <p className="text-xs text-slate-600 mt-1">Agents will appear here during pipeline execution</p>
        </div>
      )}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {entries.map(([name, state]) => (
          <AgentCard
            key={name}
            name={name}
            state={state}
            expanded={!!expanded[name]}
            onToggle={() => toggle(name)}
          />
        ))}
      </div>
    </div>
  );
}

function TimelineTab({ timelineEvents }) {
  const [filter, setFilter] = useState(null);

  return (
    <div className="p-4">
      <ReasoningTimeline
        events={timelineEvents}
        filterAgent={filter}
        onFilterChange={setFilter}
      />
    </div>
  );
}

function GraphTab({ graphData }) {
  return (
    <div className="p-4">
      <Suspense fallback={<GraphFallback />}>
        <ReasoningGraph nodes={graphData?.nodes || []} edges={graphData?.edges || []} />
      </Suspense>
    </div>
  );
}

function MetricsTab({ stage, progress, elapsedMs, agentStates }) {
  const totalAgents = Object.keys(agentStates || {}).length;
  const completedAgents = Object.values(agentStates || {}).filter(
    (s) => s.status === 'complete' || s.status === 'done'
  ).length;
  const totalClaims = Object.values(agentStates || {}).reduce(
    (sum, s) => sum + (s.claims?.length || 0), 0
  );
  const totalWarnings = Object.values(agentStates || {}).reduce(
    (sum, s) => sum + (s.warnings?.length || 0), 0
  );

  return (
    <div className="p-4 space-y-3">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <div className="rounded-xl glass-panel p-3">
          <p className="text-[10px] text-slate-500 mb-1">Pipeline Stage</p>
          <p className="text-sm font-semibold text-cyan-300 capitalize">{stage.replace(/_/g, ' ')}</p>
        </div>
        <div className="rounded-xl glass-panel p-3">
          <p className="text-[10px] text-slate-500 mb-1">Progress</p>
          <p className="text-sm font-semibold text-slate-100 font-mono">{progress}%</p>
        </div>
        <div className="rounded-xl glass-panel p-3">
          <p className="text-[10px] text-slate-500 mb-1">Elapsed Time</p>
          <p className="text-sm font-semibold text-slate-100 font-mono">
            {elapsedMs > 0 ? `${(elapsedMs / 1000).toFixed(1)}s` : '\u2014'}
          </p>
        </div>
        <div className="rounded-xl glass-panel p-3">
          <p className="text-[10px] text-slate-500 mb-1">Agents</p>
          <p className="text-sm font-semibold text-slate-100 font-mono">
            {completedAgents}/{totalAgents}
          </p>
        </div>
      </div>

      <div className="rounded-xl glass-panel p-3">
        <p className="text-[10px] uppercase tracking-wider text-slate-500 font-medium mb-2">
          Execution Summary
        </p>
        <div className="space-y-2 text-xs">
          <div className="flex justify-between">
            <span className="text-slate-400">Total Claims</span>
            <span className="text-slate-200 font-mono">{totalClaims}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Total Warnings</span>
            <span className={`font-mono ${totalWarnings > 0 ? 'text-amber-300' : 'text-slate-200'}`}>
              {totalWarnings}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Pipeline Status</span>
            <span className={`font-mono ${
              stage === 'done' ? 'text-emerald-300' :
              stage === 'error' ? 'text-rose-300' :
              'text-cyan-300'
            }`}>
              {stage === 'idle' ? 'Idle' : stage === 'done' ? 'Complete' : stage === 'error' ? 'Error' : 'Running'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function MissionControlPanel({
  open,
  onToggle,
  agentStates,
  stage,
  progress,
  elapsedMs,
  timelineEvents,
  graphData,
}) {
  const pinned = useSettingsStore((s) => s.missionControlPinned);
  const updateSetting = useSettingsStore((s) => s.updateSetting);
  const animationsEnabled = useSettingsStore((s) => s.animationsEnabled);
  const isMobile = useIsMobile();

  const [activeTab, setActiveTab] = useState('pipeline');
  const [panelWidth, setPanelWidth] = useState(DEFAULT_WIDTH);
  const [isResizing, setIsResizing] = useState(false);
  const resizeRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (e.key === 'Escape' && !pinned) onToggle();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, pinned, onToggle]);

  const handleResizeStart = useCallback((e) => {
    e.preventDefault();
    setIsResizing(true);
    const startX = e.clientX;
    const startWidth = panelWidth;

    const handleMove = (moveEvent) => {
      const delta = startX - moveEvent.clientX;
      const newWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth + delta));
      setPanelWidth(newWidth);
    };

    const handleUp = () => {
      setIsResizing(false);
      document.removeEventListener('mousemove', handleMove);
      document.removeEventListener('mouseup', handleUp);
    };

    document.addEventListener('mousemove', handleMove);
    document.addEventListener('mouseup', handleUp);
  }, [panelWidth]);

  if (!open) return null;

  const tabContent = (
    <>
      <div className="flex items-center justify-between p-3 border-b border-white/[0.06]">
        <h3 className="text-xs font-semibold text-slate-200 uppercase tracking-wider">Mission Control</h3>
        <div className="flex items-center gap-1">
          {!isMobile && (
            <button
              onClick={() => updateSetting('missionControlPinned', !pinned)}
              aria-label={pinned ? 'Unpin panel' : 'Pin panel'}
              className={`btn-icon touch-target ${
                pinned ? 'text-cyan-400 bg-cyan-500/10' : ''
              }`}
            >
              {pinned ? <Pin className="h-3.5 w-3.5" /> : <PinOff className="h-3.5 w-3.5" />}
            </button>
          )}
          <button
            onClick={onToggle}
            aria-label="Close Mission Control"
            className="btn-icon touch-target text-slate-500"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div role="tablist" aria-label="Mission Control sections" className="flex border-b border-white/[0.06] px-1 overflow-x-auto">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              role="tab"
              id={`tab-${tab.key}`}
              aria-selected={isActive}
              aria-controls={`mc-panel-${tab.key}`}
              onClick={() => setActiveTab(tab.key)}
              onKeyDown={(e) => {
                const idx = TABS.findIndex((t) => t.key === tab.key);
                if (e.key === 'ArrowRight') {
                  e.preventDefault();
                  const next = TABS[(idx + 1) % TABS.length];
                  setActiveTab(next.key);
                  document.getElementById(`tab-${next.key}`)?.focus();
                }
                if (e.key === 'ArrowLeft') {
                  e.preventDefault();
                  const prev = TABS[(idx - 1 + TABS.length) % TABS.length];
                  setActiveTab(prev.key);
                  document.getElementById(`tab-${prev.key}`)?.focus();
                }
              }}
              className={`flex items-center gap-1 px-2.5 py-2.5 text-[10px] font-medium border-b-2 transition-colors whitespace-nowrap focus:outline-none focus:ring-2 focus:ring-accent-cyan focus:ring-inset ${
                isActive
                  ? 'border-cyan-400 text-cyan-300'
                  : 'border-transparent text-slate-500 hover:text-slate-300'
              }`}
            >
              <Icon className="h-3 w-3" aria-hidden="true" />
              {tab.label}
            </button>
          );
        })}
      </div>

      <div className="flex-1 overflow-y-auto">
        <div role="tabpanel" id={`mc-panel-${activeTab}`} aria-labelledby={`tab-${activeTab}`} tabIndex={0}>
          {activeTab === 'pipeline' && (
            <PipelineTab stage={stage} progress={progress} elapsedMs={elapsedMs} agentStates={agentStates} />
          )}
          {activeTab === 'agents' && <AgentsTab agentStates={agentStates} />}
          {activeTab === 'timeline' && <TimelineTab timelineEvents={timelineEvents} />}
          {activeTab === 'graph' && <GraphTab graphData={graphData} />}
          {activeTab === 'metrics' && (
            <MetricsTab stage={stage} progress={progress} elapsedMs={elapsedMs} agentStates={agentStates} />
          )}
        </div>
      </div>
    </>
  );

  if (isMobile) {
    return (
      <AnimatePresence>
        <FocusTrap active={open}>
          <div>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={onToggle}
              className="fixed inset-0 z-40 bg-black/50"
              aria-hidden="true"
            />
            <motion.aside
              role="complementary"
              aria-label="Mission Control Panel"
              initial={animationsEnabled ? { y: '100%' } : false}
              animate={{ y: 0 }}
              exit={animationsEnabled ? { y: '100%' } : undefined}
              transition={{ type: 'spring', stiffness: 300, damping: 32 }}
              className="fixed inset-0 z-50 flex flex-col bg-surface-800/98 backdrop-blur-xl"
            >
              {tabContent}
            </motion.aside>
          </div>
        </FocusTrap>
      </AnimatePresence>
    );
  }

  return (
    <motion.aside
      role="complementary"
      aria-label="Mission Control Panel"
      initial={animationsEnabled ? { x: '100%', opacity: 0 } : false}
      animate={{ x: 0, opacity: 1 }}
      exit={animationsEnabled ? { x: '100%', opacity: 0 } : undefined}
      transition={{ type: 'spring', stiffness: 300, damping: 32 }}
      style={{ width: panelWidth }}
      className="hidden md:flex flex-col h-full border-l border-white/10 bg-surface-800/95 backdrop-blur-xl flex-shrink-0 relative"
    >
      <div
        ref={resizeRef}
        onMouseDown={handleResizeStart}
        className="absolute left-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-accent-cyan/30 transition-colors z-10"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize panel"
        tabIndex={0}
      />
      {tabContent}
    </motion.aside>
  );
}
