import { useCallback, useRef, useState, useEffect } from 'react';
import { streamQuery } from '../api/client';

const PIPELINE_TIMEOUT_MS = 900000;

function createAgentState() {
  return {
    status: 'idle',
    progress: [],
    reasoning_summary: {},
    draft_answer: null,
    final_answer: null,
    confidence: null,
  };
}

function derivePipelineStage(agents) {
  if (agents.Judge.status === 'done') return 'done';
  if (agents.Judge.status === 'running') return 'judge';
  if (agents.Logician.status !== 'idle' || agents.Creative.status !== 'idle') return 'agents';
  if (agents.Breaker.status !== 'idle') return 'breaker';
  return 'idle';
}

export function calculateProgress(stage) {
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

/**
 * usePipelineStages — drives the pipeline progress indicator using
 * real-time granular per-agent SSE events from the backend.
 *
 * Returns:
 *   stage       – coarse pipeline stage
 *   agentStates – per-agent state object
 *   partialData – partial results streamed mid-pipeline
 *   progress    – overall progress percentage (0-100)
 *   elapsedMs   – elapsed time in milliseconds since pipeline start
 *   run(query, history) – starts the streaming pipeline
 *   reset()     – resets everything to idle
 *   abort()     – aborts the current pipeline execution
 */
export function usePipelineStages() {
  const [stage, setStage] = useState('idle');
  const [agentStates, setAgentStates] = useState({
    Breaker: createAgentState(),
    Logician: createAgentState(),
    Creative: createAgentState(),
    Judge: createAgentState(),
  });
  const [partialData, setPartialData] = useState(null);
  const [progress, setProgress] = useState(0);
  const [startTime, setStartTime] = useState(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [liveEvents, setLiveEvents] = useState([]);
  const abortRef = useRef(null);
  const timeoutRef = useRef(null);

  useEffect(() => {
    if (!startTime || stage === 'idle' || stage === 'done' || stage === 'error') {
      return;
    }

    const interval = setInterval(() => {
      setElapsedMs(Date.now() - startTime);
    }, 100);

    return () => clearInterval(interval);
  }, [startTime, stage]);

  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  const run = useCallback(async (query, history) => {
    if (abortRef.current) abortRef.current.abort();
    if (timeoutRef.current) clearTimeout(timeoutRef.current);

    const controller = new AbortController();
    abortRef.current = controller;

    const freshAgents = {
      Breaker: createAgentState(),
      Logician: createAgentState(),
      Creative: createAgentState(),
      Judge: createAgentState(),
    };
    setAgentStates(freshAgents);
    setStage('breaker');
    setPartialData(null);
    setProgress(calculateProgress('breaker'));
    setStartTime(Date.now());
    setElapsedMs(0);
    setLiveEvents([]);

    timeoutRef.current = setTimeout(() => {
      if (!controller.signal.aborted) {
        controller.abort();
        setStage('error');
        setProgress(0);
      }
    }, PIPELINE_TIMEOUT_MS);

    const agentsRef = { ...freshAgents };

    const updateAgent = (agentName, patch) => {
      if (!agentsRef[agentName]) return;
      agentsRef[agentName] = { ...agentsRef[agentName], ...patch };
      const nextAgents = { ...agentsRef };
      setAgentStates(nextAgents);
      const derivedStage = derivePipelineStage(nextAgents);
      setStage(derivedStage);
      setProgress(calculateProgress(derivedStage));
    };

    const onEvent = (event) => {
      if (controller.signal.aborted) return;

      setLiveEvents((prev) => [...prev, { timestamp: Date.now(), event: event.event, payload: event }]);

      switch (event.event) {
        case 'agent_started': {
          updateAgent(event.agent, { status: 'running' });
          break;
        }

        case 'progress': {
          const agent = agentsRef[event.agent];
          if (!agent) break;
          const progress = [
            ...agent.progress,
            { step: event.step, total_steps: event.total_steps, message: event.message },
          ];
          updateAgent(event.agent, { progress });
          break;
        }

        case 'reasoning_summary': {
          const agent = agentsRef[event.agent];
          if (!agent) break;
          updateAgent(event.agent, {
            reasoning_summary: {
              ...agent.reasoning_summary,
              [event.section]: event.content,
            },
          });
          break;
        }

        case 'draft_answer': {
          updateAgent(event.agent, { draft_answer: event.content });
          break;
        }

        case 'agent_completed': {
          const completedStatus = event.status === 'aborted' ? 'error' : 'done';
          updateAgent(event.agent, {
            status: completedStatus,
            final_answer: event.final_answer,
            confidence: event.confidence,
          });

          if (event.agent === 'Logician' || event.agent === 'Creative') {
            const agentKey = event.agent.toLowerCase();
            const agentData = agentsRef[event.agent];
            setPartialData((prev) => ({
              ...prev,
              agent_outputs: {
                ...(prev?.agent_outputs || {}),
                [agentKey]: {
                  reasoning_steps: agentData.reasoning_summary?.['Evidence Used'] || [],
                  answer: agentData.final_answer || agentData.draft_answer || '',
                  confidence: agentData.confidence,
                },
              },
            }));
          }
          break;
        }

        case 'error': {
          if (event.agent) {
            updateAgent(event.agent, { status: 'error' });
          }
          setStage('error');
          setProgress(0);
          break;
        }

        case 'stage': {
          if (event.status === 'running') {
            setStage(event.stage);
          } else if (event.status === 'done') {
            if (event.partial) {
              setPartialData((prev) => ({ ...prev, ...event.partial }));
            }
          } else if (event.status === 'aborted') {
            setStage('error');
          }
          break;
        }

        default:
          break;
      }
    };

    try {
      const { data, latencyMs } = await streamQuery(query, {
        signal: controller.signal,
        history,
        onEvent,
      });
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      if (controller.signal.aborted) {
        return { data: null, latencyMs: 0, error: null, aborted: true };
      }
      setStage('done');
      setProgress(100);
      return { data, latencyMs, error: null, aborted: false };
    } catch (error) {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      if (controller.signal.aborted) {
        return { data: null, latencyMs: 0, error: null, aborted: true };
      }
      setStage('error');
      setProgress(0);
      return { data: null, latencyMs: 0, error, aborted: false };
    }
  }, []);

  const reset = useCallback(() => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    setStage('idle');
    setPartialData(null);
    setProgress(0);
    setStartTime(null);
    setElapsedMs(0);
    setLiveEvents([]);
    setAgentStates({
      Breaker: createAgentState(),
      Logician: createAgentState(),
      Creative: createAgentState(),
      Judge: createAgentState(),
    });
  }, []);

  const abort = useCallback(() => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setStage('error');
    setProgress(0);
  }, []);

  return { stage, agentStates, partialData, progress, elapsedMs, liveEvents, run, reset, abort };
}
