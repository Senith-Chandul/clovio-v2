import type { ReactNode } from 'react';
import { NavLink } from 'react-router';
import { FolderKanban, ListChecks, LogOut, MessagesSquare, Settings } from 'lucide-react';
import { signOut } from '../api/client';
import { useMe } from '../features/auth/useMe';
import { useChats } from '../features/chat/queries';
import { useProjects } from '../features/projects/queries';
import ClovioMark from '../brand/ClovioMark';
import Avatar from '../ui/Avatar';
import NotificationBell from './NotificationBell';

const NAV = [
  { to: '/', label: 'Projects', icon: FolderKanban },
  { to: '/my', label: 'My tasks', icon: ListChecks },
  { to: '/chat', label: 'Chat', icon: MessagesSquare },
  { to: '/settings', label: 'Settings', icon: Settings },
];
// Each project keeps one dot colour everywhere, picked from its id.
const DOTS = ['var(--primary)', 'var(--secondary)', 'var(--warning)', 'var(--inverse)'];
const dot = (id: string) => DOTS[parseInt(id.slice(0, 8), 16) % DOTS.length];

interface AppShellProps {
  title: ReactNode;
  subtitle?: ReactNode;
  /** Header controls on the right: search, icon buttons, then the one primary action. */
  actions?: ReactNode;
  children: ReactNode;
}

/** The app frame: a floating sidebar panel and a content column on the ground. */
export default function AppShell({ title, subtitle, actions, children }: AppShellProps) {
  const { data: me } = useMe();
  const { data: projects } = useProjects();
  const unread = useChats().data?.chats.reduce((sum, c) => sum + c.unread, 0) ?? 0;

  return (
    <div className="flex min-h-screen flex-col items-stretch gap-4 bg-ground p-4 lg:flex-row lg:items-start">
      <aside className="clv-sidebar w-full shrink-0 lg:sticky lg:top-4 lg:h-[calc(100vh-2rem)] lg:w-60 lg:overflow-y-auto">
        <div className="flex items-center gap-2.5 px-2 pt-0.5">
          <span className="flex h-[34px] w-[34px] items-center justify-center rounded-[11px] bg-primary-soft text-primary">
            <ClovioMark className="h-5 w-5" strokeWidth={10} />
          </span>
          <span className="text-[18px] font-bold leading-tight tracking-tight">clovio</span>
        </div>

        <nav className="clv-nav" aria-label="Main">
          <div className="clv-nav-label">Main</div>
          {NAV.map(({ to, label, icon: Icon }) => (
            // NavLink sets aria-current="page" on the active item, which the design system styles.
            <NavLink key={to} to={to} end={to === '/'} className="clv-nav-item">
              <Icon aria-hidden="true" />
              {label}
              {to === '/chat' && unread > 0 && <span className="clv-nav-count" aria-label={`${unread} unread`}>{unread}</span>}
            </NavLink>
          ))}
        </nav>

        {!!projects?.length && (
          <nav className="clv-nav" aria-label="Your projects">
            <div className="clv-nav-label">Your projects</div>
            {projects.map((p) => (
              <NavLink key={p.id} to={`/projects/${p.id}`} className="clv-nav-item">
                <span className="clv-nav-dot" style={{ background: dot(p.id) }} />
                <span className="flex-1 truncate">{p.name || 'Untitled project'}</span>
              </NavLink>
            ))}
          </nav>
        )}

        {me && (
          <div className="mt-auto flex items-center gap-2.5 border-t border-line px-2 pt-3">
            <Avatar name={me.name} size="lg" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] font-semibold">{me.name}</div>
              <div className="truncate text-[11px] text-ink-muted">{me.email}</div>
            </div>
            <button type="button" className="clv-icon-btn h-9 w-9" onClick={signOut} aria-label="Sign out" title="Sign out">
              <LogOut aria-hidden="true" />
            </button>
          </div>
        )}
      </aside>

      <main className="flex min-w-0 flex-1 flex-col gap-4">
        <header className="flex flex-wrap items-center justify-between gap-3 pt-1">
          <div className="min-w-0">
            <h1 className="text-display text-ink">{title}</h1>
            {subtitle && <p className="mt-0.5 text-[13px] text-ink-muted">{subtitle}</p>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {actions}
            <NotificationBell />
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}
