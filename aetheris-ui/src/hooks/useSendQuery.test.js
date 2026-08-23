import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useSendQuery } from './useSendQuery';
import { useChatStore } from '../store/useChatStore';
import * as usePipelineStagesModule from './usePipelineStages';

vi.mock('../store/useChatStore');
vi.mock('./usePipelineStages');

describe('useSendQuery', () => {
  let mockAddMessage;
  let mockUpdateMessage;
  let mockAddTelemetryEntry;
  let mockGetActiveConversation;
  let mockRun;
  let mockReset;
  let mockAbort;

  beforeEach(() => {
    vi.clearAllMocks();

    mockAddMessage = vi.fn();
    mockUpdateMessage = vi.fn();
    mockAddTelemetryEntry = vi.fn();
    mockGetActiveConversation = vi.fn(() => ({
      id: 'conv-1',
      messages: [],
    }));
    mockRun = vi.fn();
    mockReset = vi.fn();
    mockAbort = vi.fn();

    vi.mocked(useChatStore).mockImplementation((selector) => {
      const store = {
        addMessage: mockAddMessage,
        updateMessage: mockUpdateMessage,
        addTelemetryEntry: mockAddTelemetryEntry,
        getActiveConversation: mockGetActiveConversation,
      };
      return selector(store);
    });

    vi.mocked(usePipelineStagesModule.usePipelineStages).mockReturnValue({
      stage: 'idle',
      agentStates: {
        Breaker: { status: 'idle' },
        Logician: { status: 'idle' },
        Creative: { status: 'idle' },
        Judge: { status: 'idle' },
      },
      partialData: null,
      progress: 0,
      elapsedMs: 0,
      run: mockRun,
      reset: mockReset,
      abort: mockAbort,
    });
  });

  it('should return pipeline state and functions', () => {
    const { result } = renderHook(() => useSendQuery());

    expect(result.current.stage).toBe('idle');
    expect(result.current.agentStates).toBeDefined();
    expect(result.current.partialData).toBeNull();
    expect(result.current.progress).toBe(0);
    expect(result.current.elapsedMs).toBe(0);
    expect(typeof result.current.send).toBe('function');
    expect(typeof result.current.abort).toBe('function');
  });

  it('should not send empty or whitespace-only queries', async () => {
    const { result } = renderHook(() => useSendQuery());

    await act(async () => {
      await result.current.send('conv-1', '');
    });

    expect(mockAddMessage).not.toHaveBeenCalled();

    await act(async () => {
      await result.current.send('conv-1', '   ');
    });

    expect(mockAddMessage).not.toHaveBeenCalled();
  });

  it('should send query and create user and assistant messages', async () => {
    mockRun.mockResolvedValue({
      data: { answer: 'Test response', confidence_score: 0.95 },
      latencyMs: 1500,
      error: null,
      aborted: false,
    });

    const { result } = renderHook(() => useSendQuery());

    await act(async () => {
      await result.current.send('conv-1', 'What is AI?');
    });

    // Should add user message
    expect(mockAddMessage).toHaveBeenCalledWith(
      'conv-1',
      expect.objectContaining({
        role: 'user',
        content: 'What is AI?',
      })
    );

    // Should add assistant message with pending status
    expect(mockAddMessage).toHaveBeenCalledWith(
      'conv-1',
      expect.objectContaining({
        role: 'assistant',
        status: 'pending',
      })
    );

    // Should call run with query and history
    expect(mockRun).toHaveBeenCalledWith('What is AI?', []);

    // Should update assistant message with response
    await waitFor(() => {
      expect(mockUpdateMessage).toHaveBeenCalledWith(
        'conv-1',
        expect.any(String),
        expect.objectContaining({
          status: 'done',
          response: expect.objectContaining({
            answer: 'Test response',
            confidence_score: 0.95,
          }),
        })
      );
    });
  });

  it('should build conversation history for multi-turn context', async () => {
    mockGetActiveConversation.mockReturnValue({
      id: 'conv-1',
      messages: [
        { role: 'user', content: 'Hello', createdAt: 1000 },
        {
          role: 'assistant',
          status: 'done',
          response: { answer: 'Hi there!' },
          createdAt: 1100,
        },
        { role: 'user', content: 'How are you?', createdAt: 1200 },
      ],
    });

    mockRun.mockResolvedValue({
      data: { answer: 'I am doing well' },
      latencyMs: 1000,
      error: null,
      aborted: false,
    });

    const { result } = renderHook(() => useSendQuery());

    await act(async () => {
      await result.current.send('conv-1', 'Tell me more');
    });

    expect(mockRun).toHaveBeenCalledWith('Tell me more', [
      { role: 'user', content: 'Hello' },
      { role: 'assistant', content: 'Hi there!' },
      { role: 'user', content: 'How are you?' },
    ]);
  });

  it('should limit conversation history to last 10 messages', async () => {
    const messages = [];
    for (let i = 0; i < 25; i++) {
      messages.push({
        role: 'user',
        content: `Message ${i}`,
        createdAt: 1000 + i,
      });
      messages.push({
        role: 'assistant',
        status: 'done',
        response: { answer: `Response ${i}` },
        createdAt: 1000 + i + 0.5,
      });
    }

    mockGetActiveConversation.mockReturnValue({
      id: 'conv-1',
      messages,
    });

    mockRun.mockResolvedValue({
      data: { answer: 'Test' },
      latencyMs: 1000,
      error: null,
      aborted: false,
    });

    const { result } = renderHook(() => useSendQuery());

    await act(async () => {
      await result.current.send('conv-1', 'New query');
    });

    const historyArg = mockRun.mock.calls[0][1];
    expect(historyArg).toHaveLength(10);
  });

  it('should handle pipeline errors', async () => {
    const error = new Error('Pipeline failed');
    mockRun.mockResolvedValue({
      data: null,
      latencyMs: 0,
      error,
      aborted: false,
    });

    const { result } = renderHook(() => useSendQuery());

    await act(async () => {
      await result.current.send('conv-1', 'Test query');
    });

    await waitFor(() => {
      expect(mockUpdateMessage).toHaveBeenCalledWith(
        'conv-1',
        expect.any(String),
        expect.objectContaining({
          status: 'error',
          error: expect.any(String),
        })
      );
    });
  });

  it('should handle stream errors with stage information', async () => {
    const error = {
      isStreamError: true,
      stage: 'judge',
      message: 'Judge validation failed',
    };
    mockRun.mockResolvedValue({
      data: null,
      latencyMs: 500,
      error,
      aborted: false,
    });

    const { result } = renderHook(() => useSendQuery());

    await act(async () => {
      await result.current.send('conv-1', 'Test query');
    });

    await waitFor(() => {
      expect(mockUpdateMessage).toHaveBeenCalledWith(
        'conv-1',
        expect.any(String),
        expect.objectContaining({
          status: 'error',
          error: 'Pipeline failed at judge: Judge validation failed',
        })
      );
    });
  });

  it('should handle network errors', async () => {
    const error = { message: 'Network error' };
    mockRun.mockResolvedValue({
      data: null,
      latencyMs: 0,
      error,
      aborted: false,
    });

    const { result } = renderHook(() => useSendQuery());

    await act(async () => {
      await result.current.send('conv-1', 'Test query');
    });

    await waitFor(() => {
      expect(mockUpdateMessage).toHaveBeenCalledWith(
        'conv-1',
        expect.any(String),
        expect.objectContaining({
          status: 'error',
          error: expect.stringContaining('Could not reach the calienne backend'),
        })
      );
    });
  });

  it('should handle HTTP 500 errors', async () => {
    const error = {
      response: { status: 500 },
    };
    mockRun.mockResolvedValue({
      data: null,
      latencyMs: 0,
      error,
      aborted: false,
    });

    const { result } = renderHook(() => useSendQuery());

    await act(async () => {
      await result.current.send('conv-1', 'Test query');
    });

    await waitFor(() => {
      expect(mockUpdateMessage).toHaveBeenCalledWith(
        'conv-1',
        expect.any(String),
        expect.objectContaining({
          status: 'error',
          error: expect.stringContaining('Backend error (500)'),
        })
      );
    });
  });

  it('should handle HTTP 422 errors', async () => {
    const error = {
      response: { status: 422 },
    };
    mockRun.mockResolvedValue({
      data: null,
      latencyMs: 0,
      error,
      aborted: false,
    });

    const { result } = renderHook(() => useSendQuery());

    await act(async () => {
      await result.current.send('conv-1', 'Test query');
    });

    await waitFor(() => {
      expect(mockUpdateMessage).toHaveBeenCalledWith(
        'conv-1',
        expect.any(String),
        expect.objectContaining({
          status: 'error',
          error: expect.stringContaining('422'),
        })
      );
    });
  });

  it('should add telemetry entry on successful completion', async () => {
    mockRun.mockResolvedValue({
      data: {
        answer: 'Test response',
        confidence_score: 0.88,
        bias_risk: 'low',
      },
      latencyMs: 2500,
      error: null,
      aborted: false,
    });

    const { result } = renderHook(() => useSendQuery());

    await act(async () => {
      await result.current.send('conv-1', 'What is quantum computing?');
    });

    await waitFor(() => {
      expect(mockAddTelemetryEntry).toHaveBeenCalledWith(
        expect.objectContaining({
          query: 'What is quantum computing?',
          latencyMs: 2500,
          confidence: 0.88,
          biasRisk: 'low',
        })
      );
    });
  });

  it('should handle aborted requests', async () => {
    mockRun.mockResolvedValue({
      data: null,
      latencyMs: 0,
      error: null,
      aborted: true,
    });

    const { result } = renderHook(() => useSendQuery());

    await act(async () => {
      await result.current.send('conv-1', 'Test query');
    });

    // Should not update message or add telemetry for aborted requests
    expect(mockUpdateMessage).not.toHaveBeenCalled();
    expect(mockAddTelemetryEntry).not.toHaveBeenCalled();
  });

  it('should trim whitespace from queries', async () => {
    mockRun.mockResolvedValue({
      data: { answer: 'Response' },
      latencyMs: 1000,
      error: null,
      aborted: false,
    });

    const { result } = renderHook(() => useSendQuery());

    await act(async () => {
      await result.current.send('conv-1', '  What is AI?  \n');
    });

    expect(mockRun).toHaveBeenCalledWith('What is AI?', []);
    expect(mockAddMessage).toHaveBeenCalledWith(
      'conv-1',
      expect.objectContaining({
        content: 'What is AI?',
      })
    );
  });

  it('should filter out incomplete assistant messages from history', async () => {
    mockGetActiveConversation.mockReturnValue({
      id: 'conv-1',
      messages: [
        { role: 'user', content: 'First question', createdAt: 1000 },
        {
          role: 'assistant',
          status: 'pending',
          response: null,
          createdAt: 1100,
        },
        { role: 'user', content: 'Second question', createdAt: 1200 },
        {
          role: 'assistant',
          status: 'error',
          error: 'Failed',
          createdAt: 1300,
        },
      ],
    });

    mockRun.mockResolvedValue({
      data: { answer: 'Response' },
      latencyMs: 1000,
      error: null,
      aborted: false,
    });

    const { result } = renderHook(() => useSendQuery());

    await act(async () => {
      await result.current.send('conv-1', 'Third question');
    });

    // History should only include completed messages
    expect(mockRun).toHaveBeenCalledWith('Third question', [
      { role: 'user', content: 'First question' },
      { role: 'user', content: 'Second question' },
    ]);
  });
});
