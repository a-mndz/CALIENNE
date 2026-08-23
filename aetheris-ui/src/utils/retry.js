const DEFAULT_MAX_ATTEMPTS = 3;
const DEFAULT_BASE_DELAY_MS = 1000;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Retries an async function with exponential backoff.
 * Delays: 1s, 2s, 4s (max 3 attempts by default).
 *
 * @param {Function} fn - Async function to retry
 * @param {Object} options
 * @param {number} options.maxAttempts - Maximum retry attempts (default 3)
 * @param {number} options.baseDelayMs - Base delay in ms (default 1000)
 * @param {Function} options.onRetry - Callback invoked before each retry (attempt, error)
 * @param {AbortSignal} options.signal - AbortSignal to cancel retries
 * @returns {Promise} Result of the function call
 */
export async function retryWithBackoff(fn, {
  maxAttempts = DEFAULT_MAX_ATTEMPTS,
  baseDelayMs = DEFAULT_BASE_DELAY_MS,
  onRetry,
  signal,
} = {}) {
  let lastError;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    if (signal?.aborted) {
      throw new DOMException('Aborted', 'AbortError');
    }

    try {
      return await fn(attempt);
    } catch (error) {
      lastError = error;

      if (error?.name === 'AbortError') throw error;

      if (attempt < maxAttempts) {
        const delay = baseDelayMs * Math.pow(2, attempt - 1);
        if (onRetry) onRetry(attempt, error);

        await sleep(delay);
      }
    }
  }

  throw lastError;
}

/**
 * Checks if an error is a network error (no response received).
 */
export function isNetworkError(error) {
  if (!error) return false;
  if (error?.code === 'ERR_NETWORK') return true;
  if (error?.message?.includes('Network Error')) return true;
  if (!error?.response && error?.request) return true;
  if (error?.name === 'TypeError' && error?.message?.includes('fetch')) return true;
  return false;
}

/**
 * Checks if an error is a timeout error.
 */
export function isTimeoutError(error) {
  if (!error) return false;
  if (error?.code === 'ECONNABORTED') return true;
  if (error?.message?.includes('timeout')) return true;
  return false;
}
