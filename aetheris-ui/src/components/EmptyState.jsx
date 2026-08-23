import { motion } from 'framer-motion';
import { Brain, Palette, Scale, GitBranch, ArrowRight, Sparkles } from 'lucide-react';
import TriadMark from './TriadMark';
import { useSettingsStore } from '../store/useSettingsStore';

const SUGGESTIONS = [
  {
    text: 'Should a startup prioritize speed or correctness in its MVP?',
    icon: '🚀',
  },
  {
    text: 'Is it rational to trust your gut over data when both disagree?',
    icon: '🧠',
  },
  {
    text: 'Design a fair way to split rent between roommates with unequal incomes.',
    icon: '⚖️',
  },
  {
    text: 'Compare microservices vs monolith architecture for a 10-person team.',
    icon: '🏗️',
  },
];

const PIPELINE_STEPS = [
  { icon: GitBranch, label: 'Breaker', color: 'text-emerald-400', desc: 'Knowledge gate' },
  { icon: Brain, label: 'Logician', color: 'text-cyan-400', desc: 'Strict logic' },
  { icon: Palette, label: 'Creative', color: 'text-violet-400', desc: 'Alternatives' },
  { icon: Scale, label: 'Judge', color: 'text-amber-400', desc: 'Synthesis' },
];

/**
 * EmptyState — onboarding view shown when a conversation has no messages.
 *
 * Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7
 */
export default function EmptyState({ onSuggestion }) {
  const animationsEnabled = useSettingsStore((state) => state.animationsEnabled);

  return (
    <motion.div
      key="empty-state"
      initial={animationsEnabled ? { opacity: 0, y: 12 } : false}
      animate={{ opacity: 1, y: 0 }}
      exit={animationsEnabled ? { opacity: 0, y: -12, transition: { duration: 0.25 } } : false}
      transition={{ duration: 0.3, ease: 'easeOut' }}
      className="flex h-full flex-col items-center justify-center px-6 text-center"
      role="region"
      aria-label="Welcome"
    >
      <motion.div
        initial={animationsEnabled ? { opacity: 0, scale: 0.8 } : false}
        animate={animationsEnabled ? { opacity: 1, scale: 1 } : false}
        transition={{ duration: 0.5, ease: 'easeOut' }}
        className="mb-6 flex h-20 w-20 items-center justify-center rounded-2xl bg-gradient-to-br from-cyan-500/10 to-violet-500/10 ring-1 ring-white/10 animate-float shadow-glow"
        aria-hidden="true"
      >
        <TriadMark size={40} active />
      </motion.div>

      <motion.h2
        initial={animationsEnabled ? { opacity: 0, y: 8 } : false}
        animate={animationsEnabled ? { opacity: 1, y: 0 } : false}
        transition={{ delay: 0.1 }}
        className="text-xl font-bold text-slate-100"
      >
        Calienne is ready
      </motion.h2>

      <motion.p
        initial={animationsEnabled ? { opacity: 0, y: 8 } : false}
        animate={animationsEnabled ? { opacity: 1, y: 0 } : false}
        transition={{ delay: 0.2 }}
        className="mt-2 max-w-md text-sm text-slate-400 leading-relaxed"
      >
        Ask anything. Two competing reasoning agents — logical and creative — 
        will debate, and a judge synthesizes the best answer.
      </motion.p>

      {/* Pipeline Visualization */}
      <motion.div
        initial={animationsEnabled ? { opacity: 0, y: 10 } : false}
        animate={animationsEnabled ? { opacity: 1, y: 0 } : false}
        transition={{ delay: 0.3 }}
        className="mt-6 flex items-center gap-1.5 sm:gap-2 rounded-xl glass-panel px-3 sm:px-4 py-3 overflow-x-auto max-w-full"
      >
        {PIPELINE_STEPS.map((step, i) => {
          const Icon = step.icon;
          return (
            <div key={step.label} className="flex items-center gap-1 sm:gap-2 flex-shrink-0">
              <div className="flex flex-col items-center gap-1">
                <div className={`flex h-8 w-8 sm:h-9 sm:w-9 items-center justify-center rounded-lg bg-white/5 ring-1 ring-white/10 ${step.color}`}>
                  <Icon className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
                </div>
                <span className="text-[9px] sm:text-[10px] text-slate-500 font-medium">{step.label}</span>
              </div>
              {i < PIPELINE_STEPS.length - 1 && (
                <ArrowRight className="h-2.5 w-2.5 sm:h-3 sm:w-3 text-slate-600 flex-shrink-0" />
              )}
            </div>
          );
        })}
      </motion.div>

      {/* Suggestion Cards */}
      <motion.div
        initial={animationsEnabled ? { opacity: 0, y: 10 } : false}
        animate={animationsEnabled ? { opacity: 1, y: 0 } : false}
        transition={{ delay: 0.4 }}
        className="mt-8 grid w-full max-w-lg gap-2 grid-cols-1 sm:grid-cols-2"
      >
        {SUGGESTIONS.map((s) => (
          <button
            key={s.text}
            onClick={() => onSuggestion(s.text)}
            className="group touch-target rounded-xl glass-panel px-3.5 py-3 text-left text-sm text-slate-300 hover:bg-white/5 transition-all hover:ring-1 hover:ring-white/10 hover:shadow-lg"
            aria-label={`Send suggestion: ${s.text}`}
          >
            <span className="mr-2" aria-hidden="true">{s.icon}</span>
            {s.text}
            <Sparkles className="inline-block ml-1 h-3 w-3 text-slate-600 opacity-0 group-hover:opacity-100 transition-opacity" aria-hidden="true" />
          </button>
        ))}
      </motion.div>
    </motion.div>
  );
}
