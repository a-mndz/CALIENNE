import { describe, it, expect, beforeEach } from 'vitest';
import { usePipelineStore } from './usePipelineStore.js';

describe('usePipelineStore', () => {
  beforeEach(() => {
    // Reset store to initial state before each test
    usePipelineStore.getState().reset();
  });

  describe('initialization', () => {
    it('should initialize with idle state', () => {
      const state = usePipelineStore.getState();
      
      expect(state.stage).toBe('idle');
      expect(state.progress).toBe(0);
      expect(state.startTime).toBeNull();
      expect(state.elapsedMs).toBe(0);
      expect(state.agentStates).toEqual({});
      expect(state.partialData).toBeNull();
    });
  });

  describe('setStage', () => {
    it('should update pipeline stage', () => {
      const { setStage } = usePipelineStore.getState();
      
      setStage('breaker');
      
      expect(usePipelineStore.getState().stage).toBe('breaker');
    });

    it('should handle all valid pipeline stages', () => {
      const { setStage } = usePipelineStore.getState();
      const stages = [
        'idle',
        'prompt_normalizer',
        'conversation_director',
        'breaker',
        'agents',
        'judge',
        'fusion',
        'response',
        'done',
        'error',
      ];
      
      stages.forEach((stage) => {
        setStage(stage);
        expect(usePipelineStore.getState().stage).toBe(stage);
      });
    });
  });

  describe('setProgress', () => {
    it('should update progress percentage', () => {
      const { setProgress } = usePipelineStore.getState();
      
      setProgress(45);
      
      expect(usePipelineStore.getState().progress).toBe(45);
    });

    it('should handle progress from 0 to 100', () => {
      const { setProgress } = usePipelineStore.getState();
      
      setProgress(0);
      expect(usePipelineStore.getState().progress).toBe(0);
      
      setProgress(50);
      expect(usePipelineStore.getState().progress).toBe(50);
      
      setProgress(100);
      expect(usePipelineStore.getState().progress).toBe(100);
    });
  });

  describe('setStartTime', () => {
    it('should set start time and reset elapsed time', () => {
      const { setStartTime } = usePipelineStore.getState();
      const timestamp = Date.now();
      
      setStartTime(timestamp);
      
      const state = usePipelineStore.getState();
      expect(state.startTime).toBe(timestamp);
      expect(state.elapsedMs).toBe(0);
    });
  });

  describe('updateElapsed', () => {
    it('should update elapsed time based on start time', () => {
      const { setStartTime, updateElapsed } = usePipelineStore.getState();
      const startTime = Date.now() - 1000; // 1 second ago
      
      setStartTime(startTime);
      updateElapsed();
      
      const elapsed = usePipelineStore.getState().elapsedMs;
      expect(elapsed).toBeGreaterThanOrEqual(1000);
      expect(elapsed).toBeLessThan(1100); // Allow small margin
    });

    it('should not update elapsed if no start time is set', () => {
      const { updateElapsed } = usePipelineStore.getState();
      
      updateElapsed();
      
      expect(usePipelineStore.getState().elapsedMs).toBe(0);
    });
  });

  describe('updateAgentState', () => {
    it('should create new agent state if not exists', () => {
      const { updateAgentState } = usePipelineStore.getState();
      
      updateAgentState('logician', {
        status: 'running',
        progress: 25,
      });
      
      const state = usePipelineStore.getState();
      expect(state.agentStates.logician).toBeDefined();
      expect(state.agentStates.logician.status).toBe('running');
      expect(state.agentStates.logician.progress).toBe(25);
    });

    it('should merge updates into existing agent state', () => {
      const { updateAgentState } = usePipelineStore.getState();
      
      updateAgentState('logician', {
        status: 'running',
        progress: 25,
        summary: 'Initial summary',
      });
      
      updateAgentState('logician', {
        progress: 75,
        summary: 'Updated summary',
      });
      
      const state = usePipelineStore.getState();
      expect(state.agentStates.logician.status).toBe('running');
      expect(state.agentStates.logician.progress).toBe(75);
      expect(state.agentStates.logician.summary).toBe('Updated summary');
    });

    it('should handle multiple agents independently', () => {
      const { updateAgentState } = usePipelineStore.getState();
      
      updateAgentState('logician', {
        status: 'running',
        progress: 50,
      });
      
      updateAgentState('creative', {
        status: 'complete',
        progress: 100,
      });
      
      const state = usePipelineStore.getState();
      expect(state.agentStates.logician.status).toBe('running');
      expect(state.agentStates.logician.progress).toBe(50);
      expect(state.agentStates.creative.status).toBe('complete');
      expect(state.agentStates.creative.progress).toBe(100);
    });

    it('should handle claims array updates', () => {
      const { updateAgentState } = usePipelineStore.getState();
      const claims = [
        { id: '1', text: 'Claim 1', confidence: 0.9 },
        { id: '2', text: 'Claim 2', confidence: 0.8 },
      ];
      
      updateAgentState('logician', { claims });
      
      const state = usePipelineStore.getState();
      expect(state.agentStates.logician.claims).toEqual(claims);
    });

    it('should handle warnings array updates', () => {
      const { updateAgentState } = usePipelineStore.getState();
      const warnings = [
        { id: '1', type: 'bias', message: 'Potential bias detected', severity: 'warning' },
      ];
      
      updateAgentState('logician', { warnings });
      
      const state = usePipelineStore.getState();
      expect(state.agentStates.logician.warnings).toEqual(warnings);
    });

    it('should handle confidence tier updates', () => {
      const { updateAgentState } = usePipelineStore.getState();
      
      updateAgentState('logician', { confidence: 'high' });
      
      const state = usePipelineStore.getState();
      expect(state.agentStates.logician.confidence).toBe('high');
    });
  });

  describe('updatePartialData', () => {
    it('should set partial data when none exists', () => {
      const { updatePartialData } = usePipelineStore.getState();
      const data = { answer: 'Partial answer...' };
      
      updatePartialData(data);
      
      expect(usePipelineStore.getState().partialData).toEqual(data);
    });

    it('should merge partial data updates', () => {
      const { updatePartialData } = usePipelineStore.getState();
      
      updatePartialData({ answer: 'Partial answer...' });
      updatePartialData({ confidence: 0.75 });
      
      const state = usePipelineStore.getState();
      expect(state.partialData).toEqual({
        answer: 'Partial answer...',
        confidence: 0.75,
      });
    });

    it('should handle nested object updates', () => {
      const { updatePartialData } = usePipelineStore.getState();
      
      updatePartialData({ metadata: { stage: 'breaker' } });
      updatePartialData({ metadata: { agents: ['logician', 'creative'] } });
      
      const state = usePipelineStore.getState();
      expect(state.partialData.metadata).toEqual({
        agents: ['logician', 'creative'],
      });
    });
  });

  describe('reset', () => {
    it('should reset all pipeline state to initial values', () => {
      const {
        setStage,
        setProgress,
        setStartTime,
        updateAgentState,
        updatePartialData,
        reset,
      } = usePipelineStore.getState();
      
      // Set some state
      setStage('agents');
      setProgress(50);
      setStartTime(Date.now());
      updateAgentState('logician', { status: 'running', progress: 50 });
      updatePartialData({ answer: 'Partial...' });
      
      // Reset
      reset();
      
      const state = usePipelineStore.getState();
      expect(state.stage).toBe('idle');
      expect(state.progress).toBe(0);
      expect(state.startTime).toBeNull();
      expect(state.elapsedMs).toBe(0);
      expect(state.agentStates).toEqual({});
      expect(state.partialData).toBeNull();
    });
  });

  describe('complex pipeline flow', () => {
    it('should handle complete pipeline execution flow', () => {
      const {
        setStage,
        setProgress,
        setStartTime,
        updateAgentState,
        updatePartialData,
        updateElapsed,
      } = usePipelineStore.getState();
      
      // Start pipeline with a time in the past to ensure elapsed time
      setStartTime(Date.now() - 100);
      setStage('prompt_normalizer');
      setProgress(10);
      
      // Breaker stage
      setStage('breaker');
      setProgress(20);
      
      // Agents stage
      setStage('agents');
      updateAgentState('logician', {
        status: 'running',
        progress: 30,
        startTime: Date.now(),
      });
      
      updateAgentState('creative', {
        status: 'running',
        progress: 30,
        startTime: Date.now(),
      });
      
      // Update agent progress
      updateAgentState('logician', { progress: 75 });
      updateAgentState('creative', { progress: 60 });
      
      // Complete agents
      updateAgentState('logician', {
        status: 'complete',
        progress: 100,
        summary: 'Logical analysis complete',
        confidence: 'high',
      });
      
      updateAgentState('creative', {
        status: 'complete',
        progress: 100,
        summary: 'Creative exploration complete',
        confidence: 'medium',
      });
      
      setProgress(70);
      
      // Judge stage
      setStage('judge');
      setProgress(85);
      
      // Partial response
      updatePartialData({ answer: 'Based on analysis...' });
      
      // Complete
      setStage('done');
      setProgress(100);
      updateElapsed();
      
      const state = usePipelineStore.getState();
      expect(state.stage).toBe('done');
      expect(state.progress).toBe(100);
      expect(state.agentStates.logician.status).toBe('complete');
      expect(state.agentStates.creative.status).toBe('complete');
      expect(state.partialData.answer).toBeDefined();
      expect(state.elapsedMs).toBeGreaterThan(0);
    });
  });
});
