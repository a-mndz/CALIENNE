import { useChatStore } from '../store/useChatStore';
import { useNotificationStore } from '../store/useNotificationStore';
import { usePipelineStages } from './usePipelineStages';
import { isNetworkError } from '../utils/retry';

function createId() {
  return typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function deriveErrorMessage(error) {
  if (error?.isStreamError) {
    return `Pipeline failed at ${error.stage}: ${error.message}`;
  }
  if (error?.name === 'AbortError') {
    return 'Pipeline timed out after 15 minutes. Please try a simpler query or check the backend status.';
  }
  if (isNetworkError(error)) {
    return 'Could not reach the calienne backend. Check that the server is running at the configured API base URL and that CORS is enabled for this origin.';
  }
  if (!error?.response) {
    return 'Could not reach the calienne backend. Check that the server is running at the configured API base URL and that CORS is enabled for this origin.';
  }
  const status = error.response.status;
  if (status >= 500) return `Backend error (${status}). The orchestrator failed while processing this query.`;
  if (status === 422) return 'The backend rejected the request payload (422). Verify the query field matches the expected schema.';
  return `Request failed with status ${status}.`;
}

export function useSendQuery() {
  const addMessage = useChatStore((s) => s.addMessage);
  const updateMessage = useChatStore((s) => s.updateMessage);
  const addTelemetryEntry = useChatStore((s) => s.addTelemetryEntry);
  const getActiveConversation = useChatStore((s) => s.getActiveConversation);
  const { stage, agentStates, partialData, progress, elapsedMs, liveEvents, run, reset, abort } = usePipelineStages();

  const send = async (conversationId, query) => {
    const trimmed = query.trim();
    if (!trimmed) return { success: true };

    const userMessage = { id: createId(), role: 'user', content: trimmed, createdAt: Date.now() };
    const assistantMessage = {
      id: createId(),
      role: 'assistant',
      status: 'pending',
      createdAt: Date.now(),
      response: null,
      error: null,
    };

    addMessage(conversationId, userMessage);
    addMessage(conversationId, assistantMessage);

    const conversation = getActiveConversation();
    const history = (conversation?.messages ?? [])
      .filter((m) => m.role === 'user' || (m.role === 'assistant' && m.status === 'done'))
      .map((m) => ({
        role: m.role,
        content: m.role === 'user' ? m.content : (m.response?.answer ?? ''),
      }))
      .filter((m) => m.content)
      .slice(-10);

    const { data, latencyMs, error, aborted } = await run(trimmed, history);

    if (aborted) return { success: false, aborted: true, query: trimmed };

    if (error) {
      const errorMessage = deriveErrorMessage(error);
      updateMessage(conversationId, assistantMessage.id, { status: 'error', error: errorMessage });

      addTelemetryEntry({
        id: createId(),
        timestamp: Date.now(),
        query: trimmed,
        latencyMs: error?.latencyMs || latencyMs || 0,
        confidence: null,
        biasRisk: null,
        provider: null,
        cost: null,
        error: errorMessage,
      });

      useNotificationStore.getState().error(errorMessage);

      setTimeout(() => reset(), 100);
      return { success: false, error: errorMessage, query: trimmed };
    }

    updateMessage(conversationId, assistantMessage.id, { status: 'done', response: data });

    addTelemetryEntry({
      id: createId(),
      timestamp: Date.now(),
      query: trimmed,
      latencyMs,
      confidence: data?.confidence_score ?? null,
      biasRisk: data?.bias_risk ?? null,
      provider: null,
      cost: null,
    });

    setTimeout(() => reset(), 1500);
    return { success: true };
  };

  return { send, stage, agentStates, partialData, progress, elapsedMs, liveEvents, abort };
}
