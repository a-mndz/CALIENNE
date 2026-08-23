import { useState, useRef, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Filter, Clock, CheckCircle2, AlertTriangle, Zap, GitCommit } from 'lucide-react';
import { useSettingsStore } from '../store/useSettingsStore';

const AGENT_COLORS = {
  Logician: '#22d3ee',
  Creative: '#8b5cf6',
  Judge: '#f59e0b',
  Breaker: '#34d399',
};

const EVENT_ICONS = {
  claim_created: GitCommit,
  warning_issued: AlertTriangle,
  progress_update: Zap,
  complete: CheckCircle2,
  stage_start: Zap,
  stage_complete: CheckCircle2,
};

function formatRelativeTime(timestamp) {
  const now = Date.now();
  const diff = now - timestamp;
  if (diff < 1000) return 'Just now';
  if (diff < 60000) return `${(diff / 1000).toFixed(1)}s ago`;
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  return `${Math.floor(diff / 3600000)}h ago`;
}

function eventTypeLabel(type) {
  const labels = {
    claim_created: 'Created claim',
    warning_issued: 'Issued warning',
    progress_update: 'Progress update',
    complete: 'Completed',
    stage_start: 'Stage started',
    stage_complete: 'Stage completed',
  };
  return labels[type] || type;
}

/**
 * ReasoningTimeline — chronological visualization of reasoning events.
 *
 * Props:
 *  - events: TimelineEvent[]
 *  - filterAgent: string | null
 *  - onFilterChange: (agent: string | null) => void
 *
 * Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7
 */
export default function ReasoningTimeline({ events, filterAgent, onFilterChange }) {
  const animationsEnabled = useSettingsStore((s) => s.animationsEnabled);
  const scrollRef = useRef(null);
  const [highlightedId, setHighlightedId] = useState(null);

  const filteredEvents = filterAgent ? events.filter((e) => e.agent === filterAgent) : events;

  // Auto-highlight most recent event
  useEffect(() => {
    if (filteredEvents.length > 0) {
      const mostRecent = filteredEvents[filteredEvents.length - 1];
      setHighlightedId(mostRecent.id);
    }
  }, [filteredEvents]);

  // Scroll to most recent event
  useEffect(() => {
    if (scrollRef.current && highlightedId) {
      const el = scrollRef.current.querySelector(`[data-event-id="${highlightedId}"]`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }
  }, [highlightedId]);

  const agents = [...new Set(events.map((e) => e.agent))];

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-[10px] uppercase tracking-wider text-slate-500 font-medium">
          Reasoning Timeline
        </p>
        <div className="flex items-center gap-1.5">
          <Filter className="h-3 w-3 text-slate-500" aria-hidden="true" />
          <select
            value={filterAgent || ''}
            onChange={(e) => onFilterChange(e.target.value || null)}
            className="touch-target text-xs bg-surface-800 border border-surface-600 rounded-md px-2 py-1 text-slate-300 focus:outline-none focus:ring-1 focus:ring-accent-cyan"
            aria-label="Filter timeline by agent"
          >
            <option value="">All agents</option>
            {agents.map((agent) => (
              <option key={agent} value={agent}>
                {agent}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div
        ref={scrollRef}
        className="relative max-h-64 overflow-y-auto pr-1"
        role="list"
        aria-label="Reasoning events timeline"
      >
        <div className="absolute left-[0.6rem] top-2 bottom-2 w-px bg-gradient-to-b from-white/10 via-white/5 to-transparent" aria-hidden="true" />

        <div className="space-y-0">
          {filteredEvents.map((event, index) => {
            const color = AGENT_COLORS[event.agent] || '#94a3b8';
            const isHighlighted = event.id === highlightedId;
            const EventIcon = EVENT_ICONS[event.eventType] || GitCommit;

            return (
              <motion.div
                key={event.id}
                data-event-id={event.id}
                role="listitem"
                initial={animationsEnabled ? { opacity: 0, x: -8 } : false}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.2, delay: index * 0.03 }}
                className={`relative flex items-start gap-3 py-2 pl-6 pr-2 rounded-lg cursor-pointer transition-colors ${
                  isHighlighted ? 'bg-white/[0.04]' : 'hover:bg-white/[0.02]'
                }`}
                onClick={() => setHighlightedId(event.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setHighlightedId(event.id);
                  }
                }}
                tabIndex={0}
                aria-label={`${event.agent}: ${eventTypeLabel(event.eventType)} at ${formatRelativeTime(event.timestamp)}`}
              >
                <div
                  className="absolute left-[0.35rem] top-3 h-2.5 w-2.5 rounded-full border flex-shrink-0"
                  style={{ backgroundColor: `${color}40`, borderColor: `${color}80` }}
                  aria-hidden="true"
                />

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-medium" style={{ color }}>
                      {event.agent}
                    </span>
                    <span className="text-[10px] text-slate-500 flex items-center gap-1">
                      <Clock className="h-2.5 w-2.5" aria-hidden="true" />
                      {formatRelativeTime(event.timestamp)}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <EventIcon className="h-3 w-3 text-slate-500 flex-shrink-0" aria-hidden="true" />
                    <p className="text-xs text-slate-300">{eventTypeLabel(event.eventType)}</p>
                  </div>
                  {event.data?.text && (
                    <p className="text-[11px] text-slate-400 mt-0.5 line-clamp-2">
                      {event.data.text}
                    </p>
                  )}
                </div>
              </motion.div>
            );
          })}
        </div>

        {filteredEvents.length === 0 && (
          <p className="text-xs text-slate-500 py-4 text-center" role="status">No events to display</p>
        )}
      </div>
    </div>
  );
}
