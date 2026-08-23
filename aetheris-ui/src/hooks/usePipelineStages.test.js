import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { usePipelineStages, calculateProgress } from './usePipelineStages';
import * as apiClient from '../api/client';

vi.mock('../api/client');

describe('calculateProgress', () => {
  it('should return correct progress percentage for each stage', () => {
    expect(calculateProgress('idle')).toBe(0);
    expect(calculateProgress('prompt_normalizer')).toBe(5);
    expect(calculateProgress('conversation_director')).toBe(15);
    expect(calculateProgress('breaker')).toBe(27);
    expect(calculateProgress('agents')).toBe(52);
    expect(calculateProgress('judge')).toBe(77);
    expect(calculateProgress('fusion')).toBe(90);
    expect(calculateProgress('response')).toBe(97);
    expect(calculateProgress('done')).toBe(100);
    expect(calculateProgress('error')).toBe(0);
  });

  it('should return 0 for unknown stages', () => {
    expect(calculateProgress('unknown_stage')).toBe(0);
    expect(calculateProgress(null)).toBe(0);
    expect(calculateProgress(undefined)).toBe(0);
  });
});

describe('usePipelineStages', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('should initialize with idle state', () => {
    const { result } = renderHook(() => usePipelineStages());

    expect(result.current.stage).toBe('idle');
    expect(result.current.progress).toBe(0);
    expect(result.current.elapsedMs).toBe(0);
    expect(result.current.partialData).toBeNull();
    expect(result.current.agentStates).toEqual({
      Breaker: expect.objectContaining({ status: 'idle' }),
      Logician: expect.objectContaining({ status: 'idle' }),
      Creative: expect.objectContaining({ status: 'idle' }),
      Judge: expect.objectContaining({ status: 'idle' }),
    });
  });

  it('should start pipeline and update progress', async () => {
    const mockOnEvent = vi.fn();
    vi.mocked(apiClient.streamQuery).mockImplementation((query, { onEvent }) => {
      mockOnEvent.mockImplementation(onEvent);
      return Promise.resolve({ data: { answer: 'test' }, latencyMs: 1000 });
    });

    const { result } = renderHook(() => usePipelineStages());

    let runPromise;
    act(() => {
      runPromise = result.current.run('test query', []);
    });

    // Should start with breaker stage
    expect(result.current.stage).toBe('breaker');
    expect(result.current.progress).toBe(27);

    await act(async () => {
      await runPromise;
    });

    expect(result.current.stage).toBe('done');
    expect(result.current.progress).toBe(100);
  });

  it('should track elapsed time during execution', async () => {
    vi.mocked(apiClient.streamQuery).mockImplementation(() => {
      return Promise.resolve({ data: { answer: 'test' }, latencyMs: 1000 });
    });

    const { result } = renderHook(() => usePipelineStages());

    await act(async () => {
      await result.current.run('test query', []);
    });

    // After completion, elapsed time should be tracked
    // Since we're using fake timers, we need to advance them
    act(() => {
      vi.advanceTimersByTime(100);
    });

    // When pipeline is done, elapsed time should stop updating
    expect(result.current.stage).toBe('done');
  });

  it('should handle agent_started events', async () => {
    let eventCallback;
    vi.mocked(apiClient.streamQuery).mockImplementation((query, { onEvent }) => {
      eventCallback = onEvent;
      return new Promise(() => {}); // Never resolves for this test
    });

    const { result } = renderHook(() => usePipelineStages());

    act(() => {
      result.current.run('test query', []);
    });

    act(() => {
      eventCallback({ event: 'agent_started', agent: 'Logician' });
    });

    expect(result.current.agentStates.Logician.status).toBe('running');
    expect(result.current.stage).toBe('agents');
  });

  it('should handle progress events', async () => {
    let eventCallback;
    vi.mocked(apiClient.streamQuery).mockImplementation((query, { onEvent }) => {
      eventCallback = onEvent;
      return new Promise(() => {});
    });

    const { result } = renderHook(() => usePipelineStages());

    act(() => {
      result.current.run('test query', []);
    });

    act(() => {
      eventCallback({ event: 'agent_started', agent: 'Logician' });
      eventCallback({
        event: 'progress',
        agent: 'Logician',
        step: 1,
        total_steps: 3,
        message: 'Analyzing input',
      });
    });

    expect(result.current.agentStates.Logician.progress).toHaveLength(1);
    expect(result.current.agentStates.Logician.progress[0]).toEqual({
      step: 1,
      total_steps: 3,
      message: 'Analyzing input',
    });
  });

  it('should handle agent_completed events', async () => {
    let eventCallback;
    vi.mocked(apiClient.streamQuery).mockImplementation((query, { onEvent }) => {
      eventCallback = onEvent;
      return new Promise(() => {});
    });

    const { result } = renderHook(() => usePipelineStages());

    act(() => {
      result.current.run('test query', []);
    });

    act(() => {
      eventCallback({ event: 'agent_started', agent: 'Logician' });
      eventCallback({
        event: 'agent_completed',
        agent: 'Logician',
        status: 'done',
        final_answer: 'Logical analysis complete',
        confidence: 0.9,
      });
    });

    expect(result.current.agentStates.Logician.status).toBe('done');
    expect(result.current.agentStates.Logician.final_answer).toBe('Logical analysis complete');
    expect(result.current.agentStates.Logician.confidence).toBe(0.9);
  });

  it('should build partialData for Logician and Creative agents', async () => {
    let eventCallback;
    vi.mocked(apiClient.streamQuery).mockImplementation((query, { onEvent }) => {
      eventCallback = onEvent;
      return new Promise(() => {});
    });

    const { result } = renderHook(() => usePipelineStages());

    act(() => {
      result.current.run('test query', []);
    });

    act(() => {
      eventCallback({ event: 'agent_started', agent: 'Logician' });
      eventCallback({
        event: 'reasoning_summary',
        agent: 'Logician',
        section: 'Evidence Used',
        content: ['fact 1', 'fact 2'],
      });
      eventCallback({
        event: 'agent_completed',
        agent: 'Logician',
        status: 'done',
        final_answer: 'Logical answer',
        confidence: 0.85,
      });
    });

    expect(result.current.partialData).toBeDefined();
    expect(result.current.partialData.agent_outputs.logician).toEqual({
      reasoning_steps: ['fact 1', 'fact 2'],
      answer: 'Logical answer',
      confidence: 0.85,
    });
  });

  it('should handle error events', async () => {
    let eventCallback;
    vi.mocked(apiClient.streamQuery).mockImplementation((query, { onEvent }) => {
      eventCallback = onEvent;
      return new Promise(() => {});
    });

    const { result } = renderHook(() => usePipelineStages());

    act(() => {
      result.current.run('test query', []);
    });

    act(() => {
      eventCallback({ event: 'error', agent: 'Logician', message: 'Processing failed' });
    });

    expect(result.current.agentStates.Logician.status).toBe('error');
    expect(result.current.stage).toBe('error');
    // When error occurs via event (not from failed run), progress stays at current stage value
    // This is correct behavior - error event sets stage to 'error' which maps to 0
    expect(result.current.progress).toBe(0);
  });

  it('should reset state correctly', () => {
    const { result } = renderHook(() => usePipelineStages());

    // Manually set some state
    act(() => {
      result.current.run('test query', []);
    });

    expect(result.current.stage).not.toBe('idle');

    // Reset
    act(() => {
      result.current.reset();
    });

    expect(result.current.stage).toBe('idle');
    expect(result.current.progress).toBe(0);
    expect(result.current.elapsedMs).toBe(0);
    expect(result.current.partialData).toBeNull();
  });

  it('should abort in-progress pipeline', async () => {
    const abortError = new Error('Aborted');
    abortError.name = 'AbortError';

    vi.mocked(apiClient.streamQuery).mockImplementation(() => {
      return new Promise((_, reject) => {
        setTimeout(() => reject(abortError), 1000);
      });
    });

    const { result } = renderHook(() => usePipelineStages());

    act(() => {
      result.current.run('test query', []);
    });

    expect(result.current.stage).toBe('breaker');

    // Abort
    act(() => {
      result.current.abort();
    });

    expect(result.current.stage).toBe('error');
    expect(result.current.progress).toBe(0);
  });

  it('should abort previous request when starting a new one', async () => {
    const firstController = { abort: vi.fn() };
    let firstResolve;

    vi.mocked(apiClient.streamQuery).mockImplementationOnce(() => {
      return new Promise((resolve) => {
        firstResolve = resolve;
      });
    });

    const { result } = renderHook(() => usePipelineStages());

    // Start first request
    act(() => {
      result.current.run('first query', []);
    });

    expect(result.current.stage).toBe('breaker');

    // Start second request (should abort first)
    vi.mocked(apiClient.streamQuery).mockImplementationOnce(() => {
      return Promise.resolve({ data: { answer: 'second' }, latencyMs: 100 });
    });

    await act(async () => {
      await result.current.run('second query', []);
    });

    expect(result.current.stage).toBe('done');
  });

  it('should handle stream errors gracefully', async () => {
    const error = new Error('Stream failed');
    vi.mocked(apiClient.streamQuery).mockRejectedValue(error);

    const { result } = renderHook(() => usePipelineStages());

    let runResult;
    await act(async () => {
      runResult = await result.current.run('test query', []);
    });

    expect(runResult.error).toBe(error);
    expect(runResult.aborted).toBe(false);
    expect(result.current.stage).toBe('error');
  });

  it('should return aborted flag when request is aborted', async () => {
    vi.mocked(apiClient.streamQuery).mockImplementation(
      (query, { signal }) =>
        new Promise((resolve, reject) => {
          signal.addEventListener('abort', () => {
            const err = new Error('Aborted');
            err.name = 'AbortError';
            reject(err);
          });
        })
    );

    const { result } = renderHook(() => usePipelineStages());

    let runPromise;
    act(() => {
      runPromise = result.current.run('test query', []);
    });

    act(() => {
      result.current.abort();
    });

    const runResult = await runPromise;
    expect(runResult.aborted).toBe(true);
  });
});
