import { create } from 'zustand';

/**
 * Pipeline execution store for managing pipeline state and agent states
 * Requirements: 1.1-1.3, 15.1-15.3 (pipeline and agent state management)
 */
export const usePipelineStore = create((set) => ({
  // Pipeline state
  stage: 'idle', // 'idle' | 'prompt_normalizer' | 'conversation_director' | 'breaker' | 'agents' | 'judge' | 'fusion' | 'response' | 'done' | 'error'
  progress: 0, // 0-100
  startTime: null,
  elapsedMs: 0,
  
  // Agent states keyed by agent name
  agentStates: {},
  
  // Partial data received during streaming
  partialData: null,

  /**
   * Set the current pipeline stage
   * Requirements: 1.1 (pipeline stage tracking)
   */
  setStage: (stage) => {
    set({ stage });
  },

  /**
   * Update progress percentage
   * Requirements: 1.2 (progress tracking)
   */
  setProgress: (progress) => {
    set({ progress });
  },

  /**
   * Set pipeline start time
   */
  setStartTime: (startTime) => {
    set({ startTime, elapsedMs: 0 });
  },

  /**
   * Update elapsed time
   * Requirements: 1.2 (elapsed time tracking)
   */
  updateElapsed: () => {
    set((state) => {
      if (!state.startTime) return {};
      return { elapsedMs: Date.now() - state.startTime };
    });
  },

  /**
   * Update or create an agent state
   * Requirements: 1.3 (agent state management)
   * 
   * @param {string} agentName - Name of the agent (e.g., 'logician', 'creative')
   * @param {object} patch - Partial state to merge
   */
  updateAgentState: (agentName, patch) => {
    set((state) => {
      const currentAgent = state.agentStates[agentName] || {
        status: 'pending',
        progress: 0,
        startTime: null,
        duration: 0,
        summary: '',
        claims: [],
        warnings: [],
        confidence: null,
      };

      return {
        agentStates: {
          ...state.agentStates,
          [agentName]: {
            ...currentAgent,
            ...patch,
          },
        },
      };
    });
  },

  /**
   * Update partial data received during streaming
   * Requirements: 15.3 (partial response handling)
   */
  updatePartialData: (data) => {
    set((state) => ({
      partialData: state.partialData ? { ...state.partialData, ...data } : data,
    }));
  },

  /**
   * Reset pipeline to idle state
   * Should be called when starting a new query or after completion
   */
  reset: () => {
    set({
      stage: 'idle',
      progress: 0,
      startTime: null,
      elapsedMs: 0,
      agentStates: {},
      partialData: null,
    });
  },
}));
