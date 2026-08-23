const TOKEN_KEY = 'access_token';
const EMAIL_KEY = 'user_email';
const REFRESH_KEY = 'refresh_token';
const LOGIN_PATH = '/login';

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function getUserEmail() {
  return localStorage.getItem(EMAIL_KEY);
}

export function setUserEmail(email) {
  localStorage.setItem(EMAIL_KEY, email);
}

export function getRefreshToken() {
  return localStorage.getItem(REFRESH_KEY);
}

export function setRefreshToken(token) {
  localStorage.setItem(REFRESH_KEY, token);
}

export function isAuthenticated() {
  return true;
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(EMAIL_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export function logout() {
  clearAuth();
  redirectToLogin();
}

export function redirectToLogin() {
  // Standalone preview: no redirect needed
}

export function handleUnauthorized() {
  clearAuth();
  redirectToLogin();
}

/**
 * Refresh the access token via the backend `/auth/refresh` endpoint (MED-020).
 *
 * The endpoint honours the httpOnly `calienne_AUTH_COOKIE` (HIGH-013), so the
 * browser sends credentials automatically when `credentials: 'include'` is
 * set on the request.  Falls back to a hard `handleUnauthorized()` when the
 * backend rejects the refresh attempt.
 *
 * @returns {Promise<boolean>} ``true`` when a fresh token was stored.
 */
export async function refreshAccessToken() {
  try {
    const response = await fetch('/auth/refresh', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!response.ok) {
      handleUnauthorized();
      return false;
    }
    const payload = await response.json();
    if (payload?.access_token) {
      setToken(payload.access_token);
      return true;
    }
    handleUnauthorized();
    return false;
  } catch (_err) {
    handleUnauthorized();
    return false;
  }
}
