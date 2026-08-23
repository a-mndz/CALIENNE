import { useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Brain, Palette, Scale, Shield, ChevronDown, AlertTriangle, CheckCircle2, XCircle, Clock, Loader2 } from 'lucide-react';
import { useSettingsStore } from '../store/useSettingsStore';

const AGENT_CONFIG = {
  Logician: {
    icon: Brain,
    role: 'Logical reasoning and analysis',
    accentClass: 'agent-card-logician',
    textColor: 'text-cyan-300',
    bgColor: 'bg-cyan-500/10',
    ringColor: 'ring-cyan-400/30',
    dotClass: 'bg-cyan-400',
    borderColor: 'border-cyan-400/20',
  },
  Creative: {
    icon: Palette,
    role: 'Creative exploration and alternatives',
    accentClass: 'agent-card-creative',
    textColor: 'text-violet-300',
    bgColor: 'bg-violet-500/10',
    ringColor: 'ring-violet-400/30',
    dotClass: 'bg-violet-400',
    borderColor: 'border-violet-400/20',
  },
  Judge: {
    icon: Scale,
    role: 'Synthesis and validation',
    accentClass: 'agent-card-judge',
    textColor: 'text-amber-300',
    bgColor: 'bg-amber-500/10',
    ringColor: 'ring-amber-400/30',
    dotClass: 'bg-amber-400',
    borderColor: 'border-amber-400/20',
  },
  Breaker: {
    icon: Shield,
    role: 'Knowledge gate check',
    accentClass: 'agent-card-breaker',
    textColor: 'text-emerald-300',
    bgColor: 'bg-emerald-500/10',
    ringColor: 'ring-emerald-400/30',
    dotClass: 'bg-emerald-400',
    borderColor: 'border-emerald-400/20',
  },
};

function StatusBadge({ status }) {
  if (status === 'running') {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-medium text-cyan-300 bg-cyan-500/10 ring-1 ring-cyan-400/20 px-2 py-0.5 rounded-full">
        <Loader2 className="h-2.5 w-2.5 animate-spin" />
        Running
      </span>
    );
  }
  if (status === 'complete') {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-medium text-emerald-300 bg-emerald-500/10 ring-1 ring-emerald-400/20 px-2 py-0.5 rounded-full">
        <CheckCircle2 className="h-2.5 w-2.5" />
        Complete
      </span>
    );
  }
  if (status === 'failed') {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-medium text-rose-300 bg-rose-500/10 ring-1 ring-rose-400/20 px-2 py-0.5 rounded-full">
        <XCircle className="h-2.5 w-2.5" />
        Failed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-[10px] font-medium text-slate-400 bg-white/5 ring-1 ring-white/10 px-2 py-0.5 rounded-full">
      Pending
    </span>
  );
}

function ConfidenceTierBadge({ confidence }) {
  if (!confidence) return null;
  const level = typeof confidence === 'string' ? confidence.toLowerCase() : '';
  const color =
    level === 'high'
      ? 'text-emerald-300 bg-emerald-500/10 ring-emerald-400/20'
      : level === 'medium'
      ? 'text-amber-300 bg-amber-500/10 ring-amber-400/20'
      : 'text-rose-300 bg-rose-500/10 ring-rose-400/20';
  return (
    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ring-1 uppercase tracking-wide ${color}`}>
      {confidence}
    </span>
  );
}

function ValidationBadge({ status }) {
  const colors = {
    validated: 'text-emerald-300 bg-emerald-500/10 ring-emerald-400/20',
    pending: 'text-amber-300 bg-amber-500/10 ring-amber-400/20',
    rejected: 'text-rose-300 bg-rose-500/10 ring-rose-400/20',
  };
  return (
    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ring-1 ${colors[status] || colors.pending}`}>
      {status}
    </span>
  );
}

function SeverityBadge({ severity }) {
  const colors = {
    info: 'text-blue-300 bg-blue-500/10 ring-blue-400/20',
    warning: 'text-amber-300 bg-amber-500/10 ring-amber-400/20',
    error: 'text-rose-300 bg-rose-500/10 ring-rose-400/20',
  };
  return (
    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ring-1 ${colors[severity] || colors.info}`}>
      {severity}
    </span>
  );
}

/**
 * AgentCard — displays a single agent's status, claims, warnings, and confidence.
 *
 * Props:
 *  - name: string (e.g. "Logician", "Creative", "Judge", "Breaker")
 *  - role: string (optional role description)
 *  - state: AgentState object (status, progress, duration, summary, claims, warnings, confidence)
 *  - expanded: boolean
 *  - onToggle: () => void
 *
 * Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7
 */
export default function AgentCard({ name, role, state, expanded, onToggle }) {
  const config = AGENT_CONFIG[name] || AGENT_CONFIG.Breaker;
  const Icon = config.icon;
  const animationsEnabled = useSettingsStore((s) => s.animationsEnabled);

  // Normalize state to handle both usePipelineStore and usePipelineStages formats
  const normalizedState = useMemo(() => {
    if (!state) return null;

    const normalizedStatus = state.status === 'done' ? 'complete' : state.status === 'error' ? 'failed' : state.status || 'pending';

    const progress = Array.isArray(state.progress)
      ? state.progress.length > 0
        ? Math.round((state.progress[state.progress.length - 1].step / state.progress[state.progress.length - 1].total_steps) * 100)
        : 0
      : typeof state.progress === 'number' ? state.progress : 0;

    const summary = state.summary || state.final_answer || state.draft_answer || '';

    let claims = state.claims || [];
    if (claims.length === 0 && state.reasoning_summary) {
      const sections = Object.entries(state.reasoning_summary);
      for (const [section, content] of sections) {
        if (Array.isArray(content)) {
          for (let i = 0; i < content.length; i++) {
            claims.push({
              id: `${section}-${i}`,
              text: content[i],
              confidence: 0.5,
              validationStatus: 'validated',
            });
          }
        }
      }
    }

    const warnings = state.warnings || [];

    let confidence = state.confidence;
    if (typeof confidence === 'number') {
      confidence = confidence >= 0.8 ? 'high' : confidence >= 0.5 ? 'medium' : 'low';
    } else if (!confidence) {
      confidence = 'medium';
    }

    return {
      ...state,
      status: normalizedStatus,
      progress,
      summary,
      claims,
      warnings,
      confidence,
    };
  }, [state]);

  if (!normalizedState) {
    return (
      <div className={`rounded-xl glass-panel ${config.accentClass} p-4 text-xs text-slate-500`}>
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 text-slate-500" />
          <span>{name} output not available</span>
        </div>
      </div>
    );
  }

  const isRunning = normalizedState.status === 'running';
  const isComplete = normalizedState.status === 'complete';
  const isFailed = normalizedState.status === 'failed';

  return (
    <div className={`rounded-xl glass-panel ${config.accentClass} overflow-hidden ring-1 ${config.ringColor}`}>
      {/* Header */}
      <button
        onClick={onToggle}
        aria-expanded={expanded}
        aria-controls={`agent-card-${name}`}
        aria-label={`${expanded ? 'Collapse' : 'Expand'} ${name} details`}
        className="flex w-full touch-target items-center gap-2.5 px-4 py-3 text-left hover:bg-white/[0.02] transition-colors focus:outline-none focus:ring-2 focus:ring-accent-cyan focus:ring-offset-2 focus:ring-offset-surface-900"
      >
        <Icon className={`h-4 w-4 flex-shrink-0 ${config.textColor}`} />
        <div className="flex-1 min-w-0">
          <h4 className={`text-sm font-semibold ${config.textColor}`}>{name}</h4>
          <p className="text-[10px] text-slate-500">{role || config.role}</p>
        </div>

        <div className="flex items-center gap-1.5 flex-shrink-0">
          <StatusBadge status={normalizedState.status} />
          <ConfidenceTierBadge confidence={normalizedState.confidence} />

          {/* Warning count */}
          {normalizedState.warnings && normalizedState.warnings.length > 0 && (
            <span className="inline-flex items-center gap-1 text-[10px] font-medium text-amber-300 bg-amber-500/10 ring-1 ring-amber-400/20 px-2 py-0.5 rounded-full">
              <AlertTriangle className="h-2.5 w-2.5" />
              {normalizedState.warnings.length}
            </span>
          )}

          <ChevronDown
            className={`h-3.5 w-3.5 text-slate-400 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
          />
        </div>
      </button>

      {/* Progress bar */}
      {isRunning && (
        <div className="h-0.5 w-full bg-white/5 overflow-hidden">
          <motion.div
            className={`h-full ${config.dotClass}`}
            initial={{ width: '0%' }}
            animate={{ width: `${normalizedState.progress}%` }}
            transition={{ duration: 0.4, ease: 'easeOut' }}
          />
        </div>
      )}

      {/* Expandable content */}
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            id={`agent-card-${name}`}
            key="details"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: animationsEnabled ? 0.25 : 0.01, ease: 'easeInOut' }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 space-y-3">
              {/* Duration */}
              {isComplete && typeof normalizedState.duration === 'number' && normalizedState.duration > 0 && (
                <div className="flex items-center gap-1.5 text-xs text-slate-500">
                  <Clock className="h-3 w-3" />
                  <span>{(normalizedState.duration / 1000).toFixed(1)}s</span>
                </div>
              )}

              {/* Summary */}
              {normalizedState.summary && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-slate-500 font-medium mb-1.5">
                    Summary
                  </p>
                  <p className="text-sm text-slate-200 leading-relaxed">{normalizedState.summary}</p>
                </div>
              )}

              {/* Claims */}
              {normalizedState.claims && normalizedState.claims.length > 0 && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-slate-500 font-medium mb-1.5">
                    Claims ({normalizedState.claims.length})
                  </p>
                  <div className="space-y-1.5">
                    {normalizedState.claims.map((claim) => (
                      <div
                        key={claim.id}
                        className="flex items-start gap-2 bg-white/[0.03] rounded-lg p-2.5 border border-white/[0.06]"
                      >
                        <div className="flex-1 min-w-0">
                          <p className="text-xs text-slate-300 leading-relaxed">{claim.text}</p>
                          {typeof claim.confidence === 'number' && (
                            <p className="text-[10px] text-slate-500 mt-0.5">
                              Confidence: {(claim.confidence * 100).toFixed(0)}%
                            </p>
                          )}
                        </div>
                        <ValidationBadge status={claim.validationStatus || 'pending'} />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Warnings */}
              {normalizedState.warnings && normalizedState.warnings.length > 0 && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-slate-500 font-medium mb-1.5">
                    Warnings
                  </p>
                  <div className="space-y-1.5">
                    {normalizedState.warnings.map((warning) => (
                      <div
                        key={warning.id}
                        className="flex items-start gap-2 bg-amber-500/[0.06] rounded-lg p-2.5 border border-amber-400/10"
                      >
                        <AlertTriangle className="h-3 w-3 text-amber-400 flex-shrink-0 mt-0.5" />
                        <div className="flex-1 min-w-0">
                          <p className="text-xs text-amber-200/80 leading-relaxed">{warning.message}</p>
                          {warning.type && (
                            <p className="text-[10px] text-amber-400/60 mt-0.5">{warning.type}</p>
                          )}
                        </div>
                        <SeverityBadge severity={warning.severity || 'warning'} />
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
