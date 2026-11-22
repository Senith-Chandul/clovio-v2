import { useState, type FormEvent } from 'react';
import { Link, Navigate } from 'react-router';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Eye, EyeOff } from 'lucide-react';
import AuthLayout from '../../brand/AuthLayout';
import { API_URL, api, errorMessage, getToken, signIn } from '../../api/client';
import type { AuthOptions, Token } from '../../api/types';

const linkClass = 'font-semibold text-primary hover:text-primary-strong';

/** Email and password sign-in, and sign-up for dev and demo accounts when the server allows it. */
export default function AuthPage({ mode }: { mode: 'login' | 'signup' }) {
  const isSignup = mode === 'signup';
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  const options = useQuery({
    queryKey: ['auth-options'],
    queryFn: () => api.get<AuthOptions>('/api/auth/options').then((r) => r.data),
  });
  const submit = useMutation({
    mutationFn: () =>
      isSignup
        ? api.post<Token>('/api/auth/signup', { name, email, password })
        : api.post<Token>('/api/auth/login', { email, password }),
    onSuccess: (res) => signIn(res.data.access_token),
  });

  if (getToken()) return <Navigate to="/" replace />;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit.mutate();
  };
  // The server sends failed Google and Microsoft sign-ins back here with the reason in the fragment.
  const oauthError = new URLSearchParams(window.location.hash.slice(1)).get('error');
  const providers = (['google', 'microsoft'] as const).filter((p) => options.data?.[p]);

  return (
    <AuthLayout>
      <h1 className="text-display text-ink">{isSignup ? 'Create a dev account' : 'Sign in'}</h1>
      <p className="mb-8 mt-1 text-[13px] text-ink-muted">
        {isSignup ? (
          <>Already have an account? <Link to="/login" className={linkClass}>Sign in</Link></>
        ) : providers.length ? (
          'Use the account your invite was sent to. Signing in also connects your calendar.'
        ) : options.data?.password_signup ? (
          <>No account yet? <Link to="/signup" className={linkClass}>Create a dev account</Link></>
        ) : (
          'Use the email and password you were given.'
        )}
      </p>

      {!isSignup && oauthError && <p role="alert" className="mb-4 text-sm text-danger-text">{oauthError}</p>}
      {!isSignup && providers.length > 0 && (
        <div className="mb-6 space-y-3">
          {providers.map((p) => (
            <a key={p} href={`${API_URL}/api/auth/${p}/start?next=/`} className="clv-btn clv-btn-secondary w-full bg-ground">
              Continue with {p === 'google' ? 'Google' : 'Microsoft'}
            </a>
          ))}
          <p className="pt-2 text-center text-[12px] text-ink-muted">
            Or with a password (dev and demo accounts)
            {options.data?.password_signup && <> · <Link to="/signup" className={linkClass}>create one</Link></>}
          </p>
        </div>
      )}

      <form className="space-y-5" onSubmit={onSubmit}>
        {isSignup && (
          <div>
            <label htmlFor="name" className="clv-field-label">Name</label>
            <input id="name" required autoComplete="name" className="clv-input" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
        )}
        <div>
          <label htmlFor="email" className="clv-field-label">Email</label>
          <input id="email" type="email" required autoComplete="email" className="clv-input" value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label htmlFor="password" className="clv-field-label">Password</label>
          <div className="relative">
            <input
              id="password"
              type={showPassword ? 'text' : 'password'}
              required
              minLength={isSignup ? 8 : undefined}
              autoComplete={isSignup ? 'new-password' : 'current-password'}
              className="clv-input pr-12"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <button
              type="button"
              onClick={() => setShowPassword((shown) => !shown)}
              className="absolute right-4 top-1/2 -translate-y-1/2 text-ink-subtle hover:text-ink-muted"
              aria-label={showPassword ? 'Hide password' : 'Show password'}
            >
              {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
          {isSignup && <p className="mt-1.5 text-caption text-ink-muted">At least 8 characters.</p>}
        </div>

        {submit.isError && (
          <p role="alert" className="text-sm text-danger-text">
            {errorMessage(submit.error, isSignup ? "Couldn't create the account." : "Couldn't sign in.")}
          </p>
        )}

        <button type="submit" className="clv-btn clv-btn-primary w-full" disabled={submit.isPending}>
          {isSignup ? (submit.isPending ? 'Creating account' : 'Create account') : submit.isPending ? 'Signing in' : 'Sign in'}
        </button>
      </form>
    </AuthLayout>
  );
}
