import { useEffect } from 'react';
import { Navigate } from 'react-router';
import { signIn } from '../../api/client';

/** Where the server lands a Google or Microsoft sign-in: the login token is in the URL fragment. */
export default function AuthCallback() {
  const params = new URLSearchParams(window.location.hash.slice(1));
  const token = params.get('token');
  const next = params.get('next') ?? '/';
  // Only a path inside the app, so a crafted link can't send someone elsewhere.
  const safeNext = next.startsWith('/') && !next.startsWith('//') ? next : '/';

  useEffect(() => {
    if (token) signIn(token, safeNext);
  }, [token, safeNext]);

  return token ? null : <Navigate to="/login" replace />;
}
