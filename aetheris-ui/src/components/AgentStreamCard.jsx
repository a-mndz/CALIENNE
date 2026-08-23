import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown, Loader2, CheckCircle2, XCircle } from 'lucide-react';

/**
 * Agent persona config — emoji, gradient colors, and default icon
 */
const AGENT_CONFIG = {
  Breaker: {
    emoji: '🧨',
    gradient: 'from-emerald-500/20 to-emerald-600/10',
    ring: 'ring-emerald-400/30',
    textColor: 'text-emerald-300',
    progressBar: 'bg-gradient-to-r from-emerald-500 to-emerald-400',
    dotClass: 'bg-emerald-400',
  },
  Logician: {
    emoji: '🧠',
    gradient: 'from-cyan-500/20 to-cyan-600/10',
    ring: 'ring-cyan-400/30',
    textColor: 'text-cyan-300',
    progressBar: 'bg-gradient-to-r from-cyan-500 to-cyan-400',
    dotClass: 'bg-cyan-400',
  },
  Creative: {
    emoji: '🎨',
    gradient: 'from-violet-500/20 to-violet-600/10',
    ring: 'ring-violet-400/30',
    textColor: 'text-violet-300',
    progressBar: 'bg-gradient-to-r from-violet-500 to-violet-400',
    dotClass: 'bg-violet-400',
  },
  Judge: {
    emoji: '⚖️',
    gradient: 'from-amber-500/20 to-amber-600/10',
    ring: 'ring-amber-400/30',
    textColor: 'text-amber-300',
    progressBar: 'bg-gradient-to-r from-amber-500 to-amber-400',
    dotClass: 'bg-amber-400',
  },
};

function ConfidenceChip({ confidence }) {
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

/**
 * AgentStreamCard — live-updating card for a single agent during pipeline execution.
 *
 * Props:
 *  - name:  string (e.g. "Breaker", "Logician")
 *  - agent: { status, progress[], reasoning_summary, draft_answer, final_answer, confidence }
 */
export default function AgentStreamCard({ name, agent }) {
  const [expanded, setExpanded] = useState(false);
  const config = AGENT_CONFIG[name] || AGENT_CONFIG.Breaker;

  if (!agent || agent.status === 'idle') return null;

  const isRunning = agent.status === 'running';
  const isDone = agent.status === 'done';
  const isError = agent.status === 'error';

  // Progress percentage
  const latestProgress = agent.progress?.[agent.progress.length - 1];
  const progressPct = latestProgress
    ? Math.round((latestProgress.step / latestProgress.total_steps) * 100)
    : 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 6, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      className={`rounded-xl glass-panel ring-1 ${config.ring} overflow-hidden`}
    >
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full touch-target items-center gap-2.5 px-3.5 py-2.5 text-left hover:bg-white/[0.02] transition-colors"
        aria-expanded={expanded}
        aria-controls={`agent-stream-${name}`}
        aria-label={`${name} agent: ${isRunning ? 'running' : isDone ? 'complete' : isError ? 'failed' : 'pending'}`}
      >
        <span className="text-base flex-shrink-0" aria-hidden="true">{config.emoji}</span>
        <span className={`text-sm font-semibold ${config.textColor} flex-1`}>{name}</span>

        {isRunning && (
          <Loader2 className={`h-3.5 w-3.5 ${config.textColor} animate-spin`} aria-hidden="true" />
        )}
        {isDone && (
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />
        )}
        {isError && (
          <XCircle className="h-3.5 w-3.5 text-rose-400" aria-hidden="true" />
        )}

        <ConfidenceChip confidence={agent.confidence} />

        {isRunning && (
          <span className="text-[10px] font-mono text-slate-500" aria-label={`${progressPct}% progress`}>{progressPct}%</span>
        )}

        <ChevronDown
          className={`h-3 w-3 text-slate-500 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
          aria-hidden="true"
        />
      </button>

      {/* Progress bar */}
      {isRunning && (
        <div className="h-0.5 w-full bg-white/5 overflow-hidden">
          <motion.div
            className={`h-full ${config.progressBar}`}
            initial={{ width: '0%' }}
            animate={{ width: `${progressPct}%` }}
            transition={{ duration: 0.4, ease: 'easeOut' }}
          />
        </div>
      )}
      {isDone && (
        <div className="h-0.5 w-full bg-emerald-500/30" />
      )}

      {/* Live progress message */}
      {isRunning && latestProgress && (
        <div className="px-3.5 py-1.5 flex items-center gap-2">
          <span className="relative flex h-1.5 w-1.5">
            <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${config.dotClass} opacity-75`} />
            <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${config.dotClass}`} />
          </span>
          <span className="text-xs text-slate-400 animate-thinking-pulse">
            {latestProgress.message}
          </span>
        </div>
      )}

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            id={`agent-stream-${name}`}
            key="details"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: 'easeInOut' }}
            className="overflow-hidden"
            role="region"
            aria-label={`${name} details`}
          >
            <div className="px-3.5 pb-3 space-y-2">
              {/* Progress timeline */}
              {agent.progress.length > 0 && (
                <div className="space-y-0.5">
                  <p className="text-[9px] uppercase tracking-wider text-slate-500 font-medium mb-1">
                    Progress
                  </p>
                  {agent.progress.map((p, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs text-slate-400">
                      <span className={`h-1.5 w-1.5 rounded-full ${config.dotClass} flex-shrink-0 ${i === agent.progress.length - 1 && isRunning ? 'animate-pulse' : 'opacity-50'}`} />
                      <span className="font-mono text-[10px] text-slate-600 w-6">{p.step}/{p.total_steps}</span>
                      <span>{p.message}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Reasoning summary sections */}
              {Object.entries(agent.reasoning_summary || {}).map(([section, content]) => (
                <div key={section}>
                  <p className="text-[9px] uppercase tracking-wider text-slate-500 font-medium mb-1">
                    {section}
                  </p>
                  {Array.isArray(content) ? (
                    <div className="space-y-0.5">
                      {content.map((item, i) => (
                        <p key={i} className="text-xs text-slate-300 leading-relaxed pl-2 border-l border-white/5">
                          {item}
                        </p>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-300 leading-relaxed">{String(content)}</p>
                  )}
                </div>
              ))}

              {/* Draft / Final answer */}
              {(agent.final_answer || agent.draft_answer) && (
                <div className="bg-white/[0.03] rounded-lg p-2.5 border border-white/[0.06]">
                  <p className="text-[9px] uppercase tracking-wider text-slate-500 font-medium mb-1">
                    {agent.final_answer ? 'Conclusion' : 'Draft'}
                  </p>
                  <p className="text-xs text-slate-200 leading-relaxed whitespace-pre-wrap line-clamp-6">
                    {agent.final_answer || agent.draft_answer}
                  </p>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
