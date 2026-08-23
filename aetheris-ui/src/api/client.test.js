import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { apiClient, postQuery, streamQuery, fetchProviderStatus } from './client';

describe('API Client', () => {
  beforeEach(() => {
    // Clear all mocks before each test
    vi.clearAllMocks();
    localStorage.clear();
    // Reset window.location
    window.location.href = '';
    window.location.pathname = '/';
  });

  describe('apiClient axios instance', () => {
    it('should have correct base configuration', () => {
      expect(apiClient.defaults.baseURL).toBeDefined();
      expect(apiClient.defaults.timeout).toBe(900000);
      expect(apiClient.defaults.headers['Content-Type']).toBe('application/json');
    });

    it('should attach Authorization header when token exists', async () => {
      localStorage.getItem.mockReturnValue('test-token-123');
      
      // Mock the request to capture the config
      const mockRequestInterceptor = apiClient.interceptors.request.handlers[0];
      const config = { headers: {} };
      const result = await mockRequestInterceptor.fulfilled(config);
      
      expect(result.headers.Authorization).toBe('Bearer test-token-123');
    });

    it('should not attach Authorization header when token does not exist', async () => {
      localStorage.getItem.mockReturnValue(null);
      
      const mockRequestInterceptor = apiClient.interceptors.request.handlers[0];
      const config = { headers: {} };
      const result = await mockRequestInterceptor.fulfilled(config);
      
      expect(result.headers.Authorization).toBeUndefined();
    });

    it('should handle 401 response by clearing tokens and redirecting', async () => {
      window.location.pathname = '/chat';
      
      const mockResponseInterceptor = apiClient.interceptors.response.handlers[0];
      const error = {
        response: { status: 401 }
      };
      
      try {
        await mockResponseInterceptor.rejected(error);
      } catch (e) {
        // Expected to reject
      }
      
      expect(localStorage.removeItem).toHaveBeenCalledWith('access_token');
      expect(localStorage.removeItem).toHaveBeenCalledWith('user_email');
      expect(window.location.href).toBe('/login');
    });

    it('should not redirect when already on login page', async () => {
      window.location.pathname = '/login';
      const originalHref = window.location.href;
      
      const mockResponseInterceptor = apiClient.interceptors.response.handlers[0];
      const error = {
        response: { status: 401 }
      };
      
      try {
        await mockResponseInterceptor.rejected(error);
      } catch (e) {
        // Expected to reject
      }
      
      expect(localStorage.removeItem).toHaveBeenCalledWith('access_token');
      expect(window.location.href).toBe(originalHref);
    });

    it('should pass through non-401 errors', async () => {
      const mockResponseInterceptor = apiClient.interceptors.response.handlers[0];
      const error = {
        response: { status: 500 }
      };
      
      await expect(mockResponseInterceptor.rejected(error)).rejects.toEqual(error);
    });

    it('should pass through successful responses', async () => {
      const mockResponseInterceptor = apiClient.interceptors.response.handlers[0];
      const response = { status: 200, data: { success: true } };
      
      const result = await mockResponseInterceptor.fulfilled(response);
      expect(result).toEqual(response);
    });
  });

  describe('postQuery', () => {
    beforeEach(() => {
      vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { answer: 'test response' } });
      vi.spyOn(performance, 'now').mockReturnValueOnce(0).mockReturnValueOnce(100);
    });

    it('should post query without history', async () => {
      const result = await postQuery('test query');
      
      expect(apiClient.post).toHaveBeenCalledWith(
        '/api/query',
        { query: 'test query' },
        { signal: undefined }
      );
      expect(result.data).toEqual({ answer: 'test response' });
      expect(result.latencyMs).toBe(100);
    });

    it('should post query with history', async () => {
      const history = [
        { role: 'user', content: 'previous query' },
        { role: 'assistant', content: 'previous response' }
      ];
      
      const result = await postQuery('test query', { history });
      
      expect(apiClient.post).toHaveBeenCalledWith(
        '/api/query',
        { query: 'test query', history },
        { signal: undefined }
      );
      expect(result.data).toEqual({ answer: 'test response' });
    });

    it('should support abort signal', async () => {
      const abortController = new AbortController();
      
      await postQuery('test query', { signal: abortController.signal });
      
      expect(apiClient.post).toHaveBeenCalledWith(
        '/api/query',
        { query: 'test query' },
        { signal: abortController.signal }
      );
    });

    it('should not include history if empty array', async () => {
      await postQuery('test query', { history: [] });
      
      expect(apiClient.post).toHaveBeenCalledWith(
        '/api/query',
        { query: 'test query' },
        { signal: undefined }
      );
    });

    it('should measure latency correctly', async () => {
      // Clear previous mock setup
      vi.restoreAllMocks();
      vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { answer: 'test response' } });
      
      vi.spyOn(performance, 'now')
        .mockReturnValueOnce(1000)
        .mockReturnValueOnce(1234.5);
      
      const result = await postQuery('test query');
      
      expect(result.latencyMs).toBe(235); // Math.round(234.5)
    });
  });

  describe('streamQuery', () => {
    let mockReader;
    let mockResponse;

    beforeEach(() => {
      localStorage.getItem.mockReturnValue('test-token');
      
      // Mock the ReadableStream reader
      mockReader = {
        read: vi.fn(),
      };
      
      mockResponse = {
        ok: true,
        body: {
          getReader: () => mockReader,
        },
      };
      
      global.fetch = vi.fn().mockResolvedValue(mockResponse);
      vi.spyOn(performance, 'now').mockReturnValue(0);
    });

    afterEach(() => {
      vi.restoreAllMocks();
    });

    it('should send correct request with authorization', async () => {
      mockReader.read
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode('data: {"event":"result","payload":{"answer":"test"}}\n\n') })
        .mockResolvedValueOnce({ done: true });
      
      await streamQuery('test query');
      
      const fetchCall = global.fetch.mock.calls[0];
      expect(fetchCall[0]).toContain('/api/query/stream');
      expect(fetchCall[1].method).toBe('POST');
      expect(fetchCall[1].headers['Content-Type']).toBe('application/json');
      expect(fetchCall[1].headers.Authorization).toBe('Bearer test-token');
      expect(fetchCall[1].body).toBe(JSON.stringify({ query: 'test query' }));
    });

    it('should send history if provided', async () => {
      mockReader.read
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode('data: {"event":"result","payload":{"answer":"test"}}\n\n') })
        .mockResolvedValueOnce({ done: true });
      
      const history = [{ role: 'user', content: 'previous' }];
      await streamQuery('test query', { history });
      
      expect(global.fetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          body: JSON.stringify({ query: 'test query', history }),
        })
      );
    });

    it('should parse and emit SSE events', async () => {
      const events = [
        'data: {"event":"stage_start","stage":"breaker"}\n\n',
        'data: {"event":"agent_progress","agent":"logician","progress":50}\n\n',
        'data: {"event":"result","payload":{"answer":"final answer"}}\n\n',
      ];
      
      mockReader.read
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode(events.join('')) })
        .mockResolvedValueOnce({ done: true });
      
      const onEvent = vi.fn();
      const result = await streamQuery('test query', { onEvent });
      
      expect(onEvent).toHaveBeenCalledTimes(3);
      expect(onEvent).toHaveBeenNthCalledWith(1, { event: 'stage_start', stage: 'breaker' });
      expect(onEvent).toHaveBeenNthCalledWith(2, { event: 'agent_progress', agent: 'logician', progress: 50 });
      expect(onEvent).toHaveBeenNthCalledWith(3, { event: 'result', payload: { answer: 'final answer' } });
      expect(result.data).toEqual({ answer: 'final answer' });
    });

    it('should handle result event and resolve', async () => {
      mockReader.read
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode('data: {"event":"result","payload":{"answer":"test answer"}}\n\n') })
        .mockResolvedValueOnce({ done: true });
      
      vi.spyOn(performance, 'now')
        .mockReturnValueOnce(1000)
        .mockReturnValueOnce(1500);
      
      const result = await streamQuery('test query');
      
      expect(result.data).toEqual({ answer: 'test answer' });
      expect(result.latencyMs).toBe(500);
    });

    it('should handle error event and reject', async () => {
      mockReader.read
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode('data: {"event":"error","stage":"judge","message":"timeout"}\n\n') })
        .mockResolvedValueOnce({ done: true });
      
      await expect(streamQuery('test query')).rejects.toMatchObject({
        isStreamError: true,
        stage: 'judge',
        message: 'timeout',
      });
    });

    it('should handle multi-line chunked data', async () => {
      // Simulate data arriving in chunks that split across lines
      mockReader.read
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode('data: {"event":"stage_st') })
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode('art","stage":"breaker"}\n\n') })
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode('data: {"event":"result","payload":{"answer":"test"}}\n\n') })
        .mockResolvedValueOnce({ done: true });
      
      const onEvent = vi.fn();
      const result = await streamQuery('test query', { onEvent });
      
      expect(onEvent).toHaveBeenCalledTimes(2);
      expect(result.data).toEqual({ answer: 'test' });
    });

    it('should skip malformed JSON lines', async () => {
      const events = [
        'data: {"event":"stage_start","stage":"breaker"}\n\n',
        'data: {invalid json}\n\n',
        'data: {"event":"result","payload":{"answer":"test"}}\n\n',
      ];
      
      mockReader.read
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode(events.join('')) })
        .mockResolvedValueOnce({ done: true });
      
      const onEvent = vi.fn();
      const result = await streamQuery('test query', { onEvent });
      
      // Should skip the malformed line
      expect(onEvent).toHaveBeenCalledTimes(2);
      expect(result.data).toEqual({ answer: 'test' });
    });

    it('should skip empty lines and non-data lines', async () => {
      const events = [
        '\n',
        ': comment line\n',
        'data: {"event":"stage_start","stage":"breaker"}\n\n',
        '\n\n',
        'data: {"event":"result","payload":{"answer":"test"}}\n\n',
      ];
      
      mockReader.read
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode(events.join('')) })
        .mockResolvedValueOnce({ done: true });
      
      const onEvent = vi.fn();
      await streamQuery('test query', { onEvent });
      
      expect(onEvent).toHaveBeenCalledTimes(2);
    });

    it('should support AbortController signal', async () => {
      const abortController = new AbortController();
      
      mockReader.read
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode('data: {"event":"result","payload":{"answer":"test"}}\n\n') })
        .mockResolvedValueOnce({ done: true });
      
      await streamQuery('test query', { signal: abortController.signal });
      
      expect(global.fetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          signal: abortController.signal,
        })
      );
    });

    it('should reject on network error', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));
      
      await expect(streamQuery('test query')).rejects.toThrow('Network error');
    });

    it('should reject when response is not ok', async () => {
      mockResponse.ok = false;
      mockResponse.status = 500;
      mockResponse.text = vi.fn().mockResolvedValue('Internal Server Error');
      
      await expect(streamQuery('test query')).rejects.toThrow('Stream request failed (500): Internal Server Error');
    });

    it('should resolve with null data if stream ends without result event', async () => {
      mockReader.read.mockResolvedValueOnce({ done: true });
      
      const result = await streamQuery('test query');
      
      expect(result.data).toBeNull();
      expect(result.latencyMs).toBeGreaterThanOrEqual(0);
    });

    it('should not send Authorization header when token is missing', async () => {
      localStorage.getItem.mockReturnValue(null);
      
      mockReader.read
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode('data: {"event":"result","payload":{"answer":"test"}}\n\n') })
        .mockResolvedValueOnce({ done: true });
      
      await streamQuery('test query');
      
      const fetchCall = global.fetch.mock.calls[0];
      expect(fetchCall[1].headers.Authorization).toBeUndefined();
    });

    it('should handle abort signal rejection', async () => {
      const abortController = new AbortController();
      const abortError = new Error('Aborted');
      abortError.name = 'AbortError';
      
      global.fetch = vi.fn().mockRejectedValue(abortError);
      
      await expect(streamQuery('test query', { signal: abortController.signal })).rejects.toThrow('Aborted');
    });
  });

  describe('fetchProviderStatus', () => {
    beforeEach(() => {
      vi.spyOn(apiClient, 'get');
    });

    it('should fetch provider status successfully', async () => {
      const mockStatus = {
        providers: [
          { name: 'Groq', status: 'online' },
          { name: 'OpenRouter', status: 'online' },
        ],
        executionMode: 'Multi-Agent',
      };
      
      apiClient.get.mockResolvedValue({ data: mockStatus });
      
      const result = await fetchProviderStatus();
      
      expect(apiClient.get).toHaveBeenCalledWith('/api/status', { signal: undefined });
      expect(result).toEqual(mockStatus);
    });

    it('should support abort signal', async () => {
      apiClient.get.mockResolvedValue({ data: {} });
      const abortController = new AbortController();
      
      await fetchProviderStatus({ signal: abortController.signal });
      
      expect(apiClient.get).toHaveBeenCalledWith('/api/status', { signal: abortController.signal });
    });

    it('should return null on error', async () => {
      apiClient.get.mockRejectedValue(new Error('Network error'));
      
      const result = await fetchProviderStatus();
      
      expect(result).toBeNull();
    });

    it('should handle 404 gracefully', async () => {
      const error = new Error('Not Found');
      error.response = { status: 404 };
      apiClient.get.mockRejectedValue(error);
      
      const result = await fetchProviderStatus();
      
      expect(result).toBeNull();
    });

    it('should handle timeout gracefully', async () => {
      const timeoutError = new Error('Timeout');
      timeoutError.code = 'ECONNABORTED';
      apiClient.get.mockRejectedValue(timeoutError);
      
      const result = await fetchProviderStatus();
      
      expect(result).toBeNull();
    });
  });
});
