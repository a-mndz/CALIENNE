import { motion } from 'framer-motion';
import {
  MessageSquare,
  Route,
  GitBranch,
  Users,
  Scale,
  Merge,
  Zap,
  CheckCircle2,
  XCircle,
  Clock,
  Timer,
} from 'lucide-react';
import { useSettingsStore } from '../store/useSettingsStore';

const STAGES = [
  { key: 'prompt_normalizer', label: 'Prompt Normalizer', mobileLabel: 'Norm', icon: MessageSquare, agents: [] },
  { key: 'conversation_director', label: 'Conversation Director', mobileLabel: 'Dir', icon: Route, agents: [] },
  { key: 'breaker', label: 'Breaker', mobileLabel: 'Break', icon: GitBranch, agents: ['Breaker'] },
  { key: 'agents', label: 'Agents', mobileLabel: 'Agents', icon: Users, agents: ['Logician', 'Creative'] },
  { key: 'judge', label: 'Judge', mobileLabel: 'Judge', icon: Scale, agents: ['Judge_Logic', 'Judge_Factual'] },
  { key: 'fusion', label: 'Fusion', mobileLabel: 'Fusion', icon: Merge, agents: [] },
  { key: 'response', label: 'Response', mobileLabel: 'Resp', icon: Zap, agents: [] },
];

function stageIndex(stage) {
  if (stage === 'idle' || stage === 'error') return -1;
  if (stage === 'done') return STAGES.length;
  return STAGES.findIndex((s) => s.key === stage);
}

function formatElapsed(ms) {
  if (!ms || ms < 0) return '';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatEstimated(ms) {
  if (!ms || ms <= 0) return null;
  if (ms < 1000) return `${Math.round(ms)}ms remaining`;
  return `~${(ms / 1000).toFixed(1)}s remaining`;
}

function calculateProgress(stage) {
  const progressMap = {
    idle: 0,
    prompt_normalizer: 5,
    conversation_director: 15,
    breaker: 27,
    agents: 52,
    judge: 77,
    fusion: 90,
    response: 97,
    done: 100,
    error: 0,
  };
  return progressMap[stage] ?? 0;
}

function StageBox({ stage, index, currentIndex, isError, isDone, animationsEnabled }) {
  const Icon = stage.icon;
  const active = index === currentIndex;
  const complete = currentIndex > index || isDone;
  const isPending = currentIndex < index && !isDone;

  let borderClasses = '';
  let bgClasses = '';
  let textClasses = '';

  if (isError && active) {
    borderClasses = 'border-rose-400/40';
    bgClasses = 'bg-rose-500/10';
    textClasses = 'text-rose-300';
  } else if (complete) {
    borderClasses = 'border-emerald-400/30';
    bgClasses = 'bg-emerald-500/10';
    textClasses = 'text-emerald-300';
  } else if (active) {
    borderClasses = 'border-cyan-400/50';
    bgClasses = 'bg-cyan-500/10';
    textClasses = 'text-cyan-200';
  } else {
    borderClasses = 'border-dashed border-slate-600/30';
    bgClasses = 'bg-white/[0.02]';
    textClasses = 'text-slate-500';
  }

  return (
    <div className="flex flex-col items-center gap-1 min-w-[4.5rem] sm:min-w-[6.5rem]">
      <motion.div
        className={`flex items-center justify-center gap-1.5 rounded-lg px-2 sm:px-3 py-2 text-[10px] sm:text-xs font-medium border ${borderClasses} ${bgClasses} ${textClasses} ${active && !isError ? 'shadow-glow-cyan' : ''}`}
        animate={active && !isError && animationsEnabled ? { scale: [1, 1.03, 1] } : {}}
        transition={{ duration: 1.5, repeat: Infinity, ease: 'easeInOut' }}
        aria-label={`${stage.label}: ${complete ? 'complete' : active ? 'active' : 'pending'}`}
      >
        <Icon className="h-3 w-3 flex-shrink-0" aria-hidden="true" />
        <span className="hidden sm:inline">{stage.label}</span>
        <span className="sm:hidden">{stage.mobileLabel}</span>
      </motion.div>

      <div className="h-4 flex items-center justify-center">
        {complete && !isError && (
          <CheckCircle2 className="h-3 w-3 text-emerald-400" aria-label="Complete" />
        )}
        {active && !isError && (
          <motion.div
            className="h-1 w-6 rounded-full bg-cyan-400/30 overflow-hidden"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
          >
            <motion.div
              className="h-full bg-cyan-400"
              animate={{ width: ['0%', '100%', '0%'] }}
              transition={{ duration: 1.5, repeat: Infinity, ease: 'easeInOut' }}
            />
          </motion.div>
        )}
        {isError && active && (
          <XCircle className="h-3 w-3 text-rose-400" aria-label="Error" />
        )}
        {isPending && (
          <div className="h-1.5 w-1.5 rounded-full bg-slate-600/50" aria-hidden="true" />
        )}
      </div>
    </div>
  );
}

function Connector({ complete, active, animationsEnabled }) {
  return (
    <div className="flex items-center justify-center w-4 sm:w-6 flex-shrink-0">
      <div className="h-px w-full bg-slate-600/30 relative overflow-hidden">
        <motion.div
          className="absolute inset-y-0 left-0 bg-gradient-to-r from-cyan-400/60 to-violet-400/60"
          initial={{ width: '0%' }}
          animate={{ width: complete || active ? '100%' : '0%' }}
          transition={{ duration: animationsEnabled ? 0.4 : 0.01, ease: 'easeOut' }}
        />
      </div>
      <div className="text-slate-600/50 text-[10px]">▶</div>
    </div>
  );
}

/**
 * PipelineStatus — visualizes all 7 pipeline stages with connectors, progress,
 * elapsed time, and estimated remaining time.
 *
 * Props:
 *  - stage: string (legacy)
 *  - currentStage: string (preferred)
 *  - progress: number (0-100, optional)
 *  - elapsedMs: number (optional)
 *  - estimatedMs: number | null (optional)
 *  - agentStates: object (optional, for dynamic messages)
 *
 * Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
 */
export default function PipelineStatus({
  stage,
  currentStage,
  progress,
  elapsedMs,
  estimatedMs,
  agentStates,
}) {
  const stageName = currentStage || stage || 'idle';
  const currentIndex = stageIndex(stageName);
  const isError = stageName === 'error';
  const isDone = stageName === 'done';
  const isActive = !isDone && !isError && currentIndex >= 0;
  const animationsEnabled = useSettingsStore((s) => s.animationsEnabled);

  // Compute progress if not provided
  const displayProgress = typeof progress === 'number' ? progress : calculateProgress(stageName);

  // Compute elapsed if not provided
  const displayElapsed = elapsedMs || 0;

  // Estimate remaining time
  const displayEstimated = estimatedMs || (
    isActive && displayProgress > 0 && displayProgress < 100
      ? (displayElapsed / displayProgress) * (100 - displayProgress)
      : null
  );

  return (
    <div className="space-y-3" aria-live="polite" aria-atomic="true">
      {/* Stage Grid */}
      <div className="flex flex-wrap items-start justify-center gap-y-2">
        {STAGES.map((s, i) => (
          <div key={s.key} className="flex items-center">
            <StageBox
              stage={s}
              index={i}
              currentIndex={currentIndex}
              isError={isError}
              isDone={isDone}
              animationsEnabled={animationsEnabled}
            />
            {i < STAGES.length - 1 && (
              <Connector
                complete={currentIndex > i || isDone}
                active={i === currentIndex}
                animationsEnabled={animationsEnabled}
              />
            )}
            {/* Line break after stage 3 for two-row layout */}
            {i === 3 && (
              <div className="w-full sm:hidden" />
            )}
          </div>
        ))}
      </div>

      {/* Progress Info */}
      <div className="flex items-center justify-between text-xs">
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-slate-400">
            <span className="font-mono text-cyan-300">{displayProgress}%</span> complete
          </span>
          {displayElapsed > 0 && (
            <span className="inline-flex items-center gap-1 text-slate-500">
              <Clock className="h-3 w-3" />
              {formatElapsed(displayElapsed)} elapsed
            </span>
          )}
          {displayEstimated && (
            <span className="inline-flex items-center gap-1 text-slate-500">
              <Timer className="h-3 w-3" />
              {formatEstimated(displayEstimated)}
            </span>
          )}
        </div>
        {isActive && (
          <span className="inline-flex items-center gap-1.5 text-[10px] text-cyan-400/80 font-medium uppercase tracking-wider">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-cyan-500" />
            </span>
            Live
          </span>
        )}
        {isDone && (
          <span className="text-emerald-400 text-[10px] font-medium uppercase tracking-wider">
            Complete
          </span>
        )}
        {isError && (
          <span className="text-rose-300 text-[10px] font-medium uppercase tracking-wider">
            Failed
          </span>
        )}
      </div>
    </div>
  );
}
