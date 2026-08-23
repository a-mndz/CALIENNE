import { useState } from 'react';
import { motion } from 'framer-motion';
import { ChevronDown } from 'lucide-react';
import { cardExpandVariants, timelineEntryVariants } from '../utils/animations';
import { useSettingsStore } from '../store/useSettingsStore';

/**
 * AgentThinkingCard — displays a single agent's reasoning output
 * with a timeline visualization of reasoning steps.
 *
 * Props:
 *  - icon: Lucide icon component
 *  - title: agent name string
 *  - accentClass: CSS class for card styling (e.g., 'agent-card-logician')
 *  - dotClass: CSS class for timeline dots (e.g., 'timeline-step-cyan')
 *  - agent: { reasoning_steps: string[], answer: string, confidence: number }
 *  - defaultExpanded: boolean
 */
export default function AgentThinkingCard({
  icon: Icon,
  title,
  accentClass = '',
  dotClass = '',
  agent,
  defaultExpanded = false,
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const animationsEnabled = useSettingsStore((state) => state.animationsEnabled);

  if (!agent) {
    return (
      <div className={`rounded-xl p-4 glass-panel ${accentClass} text-xs text-slate-500`}>
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 text-slate-500" />
          <span>{title} output not available</span>
        </div>
      </div>
    );
  }

  const hasSteps = Array.isArray(agent.reasoning_steps) && agent.reasoning_steps.length > 0;
  const confidencePct = typeof agent.confidence === 'number' ? (agent.confidence * 100).toFixed(0) : null;

  return (
    <div className={`rounded-xl glass-panel ${accentClass} overflow-hidden`}>
      {/* Header */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 p-4 pb-3 text-left hover:bg-white/[0.02] transition-colors"
      >
        <Icon className="h-4 w-4 flex-shrink-0" style={{ color: 'inherit' }} />
        <h4 className="text-sm font-semibold text-slate-200 flex-1">{title}</h4>
        {confidencePct !== null && (
          <span className="text-xs text-slate-400 font-mono mr-2">
            {confidencePct}%
          </span>
        )}
        <ChevronDown
          className={`h-3.5 w-3.5 text-slate-400 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
        />
      </button>

      {/* Expandable Content */}
      <motion.div
        initial={false}
        animate={expanded ? 'expanded' : 'collapsed'}
        variants={animationsEnabled ? cardExpandVariants : undefined}
        className="overflow-hidden"
      >
        <div className="px-4 pb-4">
          {/* Reasoning Steps Timeline */}
          {hasSteps && (
            <div className="mb-3">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2 font-medium">
                Reasoning Process
              </p>
              <div className="space-y-0.5">
                {agent.reasoning_steps.map((step, i) => (
                  <motion.div
                    key={i}
                    className={`timeline-step ${dotClass}`}
                    initial={animationsEnabled ? 'hidden' : false}
                    animate={animationsEnabled ? 'visible' : false}
                    variants={timelineEntryVariants}
                    custom={i}
                  >
                    <p className="text-[13px] text-slate-300 leading-relaxed py-1">
                      {step}
                    </p>
                  </motion.div>
                ))}
              </div>
            </div>
          )}

          {/* Agent Answer */}
          {agent.answer && (
            <div className="bg-white/[0.03] rounded-lg p-3 border border-white/[0.06]">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5 font-medium">
                Conclusion
              </p>
              <p className="text-sm text-slate-100 leading-relaxed whitespace-pre-wrap">
                {agent.answer}
              </p>
            </div>
          )}
        </div>
      </motion.div>
    </div>
  );
}
