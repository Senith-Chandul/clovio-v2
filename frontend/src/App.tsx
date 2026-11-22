import { useEffect } from 'react';
import { Navigate, Outlet, Route, Routes } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { api, errorMessage, getToken } from './api/client';
import AuthCallback from './features/auth/AuthCallback';
import AuthPage from './features/auth/AuthPage';
import ChatPage from './features/chat/ChatPage';
import { useMe } from './features/auth/useMe';
import MyTasksPage from './features/my/MyTasksPage';
import ProjectPage from './features/project/ProjectPage';
import ProjectsPage from './features/projects/ProjectsPage';
import NewProjectPage from './features/wizard/NewProjectPage';
import PlanPage from './features/wizard/PlanPage';
import SettingsPage from './features/settings/SettingsPage';
import Toaster from './ui/Toaster';

/** Pages behind sign-in. An expired session is sent back to /login by the API client. */
function RequireAuth() {
  const me = useMe();
  const qc = useQueryClient();
  // Working hours and meeting times are worked out in the person's own zone, which the browser knows.
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const stored = me.data?.timezone;
  useEffect(() => {
    if (stored && zone && stored !== zone) {
      api.patch('/api/me', { timezone: zone }).then(() => qc.invalidateQueries({ queryKey: ['me'] }), () => {});
    }
  }, [stored, zone, qc]);

  if (!getToken()) return <Navigate to="/login" replace />;
  if (me.isPending) return null;
  if (me.isError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-ground p-4">
        <div className="clv-card max-w-sm items-center text-center">
          <p className="text-sm text-ink">{errorMessage(me.error, "Couldn't load your account.")}</p>
          <button type="button" className="clv-btn clv-btn-primary" onClick={() => me.refetch()}>Try again</button>
        </div>
      </div>
    );
  }
  return <Outlet />;
}

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/login" element={<AuthPage key="login" mode="login" />} />
        <Route path="/signup" element={<AuthPage key="signup" mode="signup" />} />
        <Route path="/auth/callback" element={<AuthCallback />} />
        <Route element={<RequireAuth />}>
          <Route path="/" element={<ProjectsPage />} />
          <Route path="/my" element={<MyTasksPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/chat/:id" element={<ChatPage />} />
          <Route path="/projects/new" element={<NewProjectPage />} />
          <Route path="/projects/:id" element={<ProjectPage />} />
          <Route path="/projects/:id/plan" element={<PlanPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <Toaster />
    </>
  );
}
