import axios from 'axios';

const TOKEN_KEY = 'clovio_token';

export const getToken = () => localStorage.getItem(TOKEN_KEY);

export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

/** Store the session and reload, so no earlier user's data stays in memory. */
export const signIn = (token: string, next = '/') => {
  localStorage.setItem(TOKEN_KEY, token);
  window.location.assign(next);
};

export const signOut = () => {
  localStorage.removeItem(TOKEN_KEY);
  window.location.assign('/login');
};

export const api = axios.create({ baseURL: API_URL });

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(undefined, (error) => {
  // The session expired or was revoked: back to the sign-in page.
  if (axios.isAxiosError(error) && error.response?.status === 401 && getToken()) signOut();
  return Promise.reject(error);
});

/** The server's own message (FastAPI's `detail`), or the fallback. */
export const errorMessage = (error: unknown, fallback: string): string => {
  if (!axios.isAxiosError(error)) return fallback;
  if (!error.response) return "Can't reach the server. Check your connection and try again.";
  const detail = error.response.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join(', ') || fallback;
  return fallback;
};
