import { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import PipelineStatus from './PipelineStatus';
import AgentCard from './AgentCard';
import ReasoningTimeline from './ReasoningTimeline';
import ConfidenceBadge from './ConfidenceBadge';
import BiasRiskBadge from './BiasRiskBadge';
import { useSettingsStore } from '../store/useSettingsStore';

/**
 * Convert agent outputs from backend response to agentStates format.
 */
function normalizeAgentOutputs(agentOutputs, decision) {
  const states = {};
  if (!agentOutputs) return states;

  const config = {
    logician: { name: 'Logician', role: 'Logical reasoning and analysis' },
    creative: { name: 'Creative', role: 'Creative exploration and alternatives' },
  };

  for (const [key, data] of Object.entries(agentOutputs)) {
    const info = config[key];
    if (!info) continue;

    const confidenceNum = typeof data.confidence === 'number' ? data.confidence : 0.5;
    states[info.name] = {
      status: 'complete',
      progress: 100,
      startTime: 0,
      duration: 0,
      summary: data.answer || '',
      claims: (data.reasoning_steps || []).map((step, i) => ({
        id: `${key}-claim-${i}`,
        text: step,
        confidence: confidenceNum,
        validationStatus: 'validated',
      })),
      warnings: [],
      confidence: confidenceNum >= 0.8 ? 'high' : confidenceNum >= 0.5 ? 'medium' : 'low',
    };
  }

  if (decision) {
    const parsedConfidence = parseConfidence(decision.justification);
    states['Judge'] = {
      status: 'complete',
      progress: 100,
      startTime: 0,
      duration: 0,
      summary: decision.verdict || '',
      claims: [],
      warnings: [],
      confidence: parsedConfidence,
    };
  }

  return states;
}

function parseConfidence(justification) {
  if (!justification) return 'medium';
  const match = justification.match(/Confidence:\s*([^|]+)/i);
  if (!match) return 'medium';
  const level = match[1].trim().toLowerCase();
  if (level === 'high') return 'high';
  if (level === 'low') return 'low';
  return 'medium';
}

function parseBiasRisk(justification) {
  if (!justification) return null;
  const match = justification.match(/Bias Risk:\s*([^|]+)/i);
  if (!match) return null;
  return match[1].trim();
}

function deriveTimelineEvents(agentStates) {
  const events = [];
  let baseTime = Date.now() - 10000;

  for (const [agentName, state] of Object.entries(agentStates)) {
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
    if (state.status === 'complete') {
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

/**
 * ReasoningPanel — integrates PipelineStatus, AgentCard list, ReasoningTimeline,
 * and ConfidenceSummary into a collapsible panel.
 *
 * Props:
 *  - response: { confidence_score, bias_risk, reasoning_summary, metadata }
 *  - agentStates: Record<string, AgentState>
 *  - expanded: boolean
 *  - onToggle: () => void (optional)
 *  - Backward compatibility: open, agentOutputs, decision
 *
 * Requirements: 1.4, 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7
 */
export default function ReasoningPanel({
  response,
  agentStates,
  expanded,
  onToggle,
  // Backward compatibility
  open,
  agentOutputs,
  decision,
}) {
  const isExpanded = expanded ?? open ?? false;
  const animationsEnabled = useSettingsStore((s) => s.animationsEnabled);

  // Extract agent_outputs from response if available
  const outputsFromResponse = response?.agent_outputs;
  const effectiveAgentOutputs = agentOutputs || outputsFromResponse;

  const effectiveAgentStates = useMemo(() => {
    if (agentStates && Object.keys(agentStates).length > 0) return agentStates;
    return normalizeAgentOutputs(effectiveAgentOutputs, decision || response?.decision);
  }, [agentStates, effectiveAgentOutputs, decision, response]);

  const effectiveResponse = response || {
    confidence_score: null,
    bias_risk: null,
    reasoning_summary: '',
    metadata: {
      pipeline_stage: 'done',
      agents_used: Object.keys(effectiveAgentStates),
      execution_time_ms: 0,
    },
  };

  const [agentExpanded, setAgentExpanded] = useState({});
  const [timelineFilter, setTimelineFilter] = useState(null);

  const timelineEvents = useMemo(() => {
    return deriveTimelineEvents(effectiveAgentStates);
  }, [effectiveAgentStates]);

  const toggleAgent = (name) => {
    setAgentExpanded((prev) => ({ ...prev, [name]: !prev[name] }));
  };

  const confidenceScore = effectiveResponse.confidence_score;
  const biasRisk = effectiveResponse.bias_risk || parseBiasRisk(response?.decision?.justification);
  const metadata = effectiveResponse.metadata || {};
  const executionTime = metadata.execution_time_ms || 0;

  return (
    <AnimatePresence initial={false}>
      {isExpanded && (
        <motion.div
          key="reasoning"
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{
            duration: animationsEnabled ? 0.3 : 0.01,
            ease: 'easeInOut',
          }}
          className="overflow-hidden"
          role="region"
          aria-label="Multi-agent reasoning details"
        >
          <div className="mt-4 space-y-4">
            <div className="flex items-center gap-2">
              <div className="h-px flex-1 bg-gradient-to-r from-transparent via-white/10 to-transparent" aria-hidden="true" />
              <span className="text-[10px] uppercase tracking-widest text-slate-500 font-medium">
                Multi-Agent Reasoning
              </span>
              <div className="h-px flex-1 bg-gradient-to-r from-transparent via-white/10 to-transparent" aria-hidden="true" />
            </div>

            {/* Pipeline Status */}
            <div className="bg-white/[0.02] rounded-xl p-3 border border-white/[0.06]">
              <PipelineStatus
                currentStage="done"
                progress={100}
                elapsedMs={executionTime}
              />
            </div>

            {/* Confidence & Bias Summary */}
            <div className="flex flex-wrap items-center gap-2">
              {typeof confidenceScore === 'number' && (
                <ConfidenceBadge score={confidenceScore} />
              )}
              <BiasRiskBadge risk={biasRisk} />
              {effectiveResponse.reasoning_summary && (
                <p className="text-xs text-slate-400 w-full mt-1">
                  {effectiveResponse.reasoning_summary}
                </p>
              )}
            </div>

            {/* Agent Cards Grid */}
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {Object.entries(effectiveAgentStates).map(([name, state]) => (
                <AgentCard
                  key={name}
                  name={name}
                  state={state}
                  expanded={!!agentExpanded[name]}
                  onToggle={() => toggleAgent(name)}
                />
              ))}
            </div>

            {/* Reasoning Timeline */}
            {timelineEvents.length > 0 && (
              <div className="bg-white/[0.02] rounded-xl p-3 border border-white/[0.06]">
                <ReasoningTimeline
                  events={timelineEvents}
                  filterAgent={timelineFilter}
                  onFilterChange={setTimelineFilter}
                />
              </div>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
