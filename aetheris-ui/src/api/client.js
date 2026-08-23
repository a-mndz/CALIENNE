import axios from 'axios';
import { retryWithBackoff, isNetworkError } from '../utils/retry';
import {
  getToken,
  handleUnauthorized,
  refreshAccessToken,
  setToken,
} from '../utils/auth';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 900000,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true,
});

apiClient.interceptors.request.use(
  (config) => {
    const token = getToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401 && !error.config?._retry) {
      const refreshed = await refreshAccessToken();
      if (refreshed) {
        error.config._retry = true;
        const fresh = getToken();
        if (fresh) {
          error.config.headers.Authorization = `Bearer ${fresh}`;
        }
        return apiClient.request(error.config);
      }
    }
    if (error.response?.status === 401) {
      handleUnauthorized();
    }
    return Promise.reject(error);
  }
);

let _connectionLostCallback = null;

export function setConnectionLostCallback(cb) {
  _connectionLostCallback = cb;
}

export function postQuery(query, { signal, history } = {}) {
  const startedAt = performance.now();
  const payload = { query };
  if (Array.isArray(history) && history.length > 0) {
    payload.history = history;
  }

  return retryWithBackoff(
    async () => {
      const response = await apiClient.post('/api/query', payload, { signal });
      const latencyMs = Math.round(performance.now() - startedAt);
      return { data: response.data, latencyMs };
    },
    {
      maxAttempts: 3,
      baseDelayMs: 1000,
      signal,
      onRetry: (attempt, error) => {
        if (isNetworkError(error) && _connectionLostCallback) {
          _connectionLostCallback(attempt);
        }
      },
    }
  );
}

export function streamQuery(query, { signal, history, onEvent, onConnectionLost } = {}) {
  const startedAt = performance.now();
  const payload = { query };
  if (Array.isArray(history) && history.length > 0) {
    payload.history = history;
  }

  return new Promise(async (resolve, reject) => {
    try {
      const token = getToken();
      const headers = { 'Content-Type': 'application/json' };
      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }

      const response = await fetch(`${API_BASE_URL}/api/query/stream`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
        signal,
      });

      if (!response.ok) {
        if (response.status === 401) {
          handleUnauthorized();
          reject(new Error('Authentication expired. Please log in again.'));
          return;
        }
        if (response.status >= 500 && onConnectionLost) {
          onConnectionLost(response.status);
        }
        const text = await response.text().catch(() => '');
        reject(new Error(`Stream request failed (${response.status}): ${text}`));
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || !trimmed.startsWith('data: ')) continue;

          try {
            const envelope = JSON.parse(trimmed.slice(6));
            const eventData = envelope.data || {};
            const event = {
              event: envelope.event,
              timestamp: envelope.timestamp,
              agent: eventData.agent || eventData.agent_name || null,
              ...eventData,
            };
            if (onEvent) onEvent(event);

            if (event.event === 'result') {
              const latencyMs = Math.round(performance.now() - startedAt);
              resolve({ data: event.payload, latencyMs });
            } else if (event.event === 'error') {
              const latencyMs = Math.round(performance.now() - startedAt);
              reject({
                isStreamError: true,
                stage: event.stage,
                message: event.message,
                latencyMs,
              });
            }
          } catch {
            // Skip malformed JSON lines
          }
        }
      }

      const latencyMs = Math.round(performance.now() - startedAt);
      resolve({ data: null, latencyMs });
    } catch (err) {
      if (signal?.aborted) {
        reject(err);
      } else if (isNetworkError(err) && onConnectionLost) {
        onConnectionLost(0);
        reject(err);
      } else {
        reject(err);
      }
    }
  });
}

export async function fetchProviderStatus({ signal } = {}) {
  try {
    const response = await apiClient.get('/api/status', { signal });
    return response.data;
  } catch {
    return null;
  }
}
