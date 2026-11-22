import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Bell } from 'lucide-react';
import { api } from '../api/client';
import type { Notification, Notifications } from '../api/types';

const KEY = ['notifications'];

/** The header bell: what was given to you, what's blocked (for managers), and projects that started. */
export default function NotificationBell() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const { data } = useQuery({
    queryKey: KEY,
    queryFn: () => api.get<Notifications>('/api/notifications').then((r) => r.data),
    refetchInterval: 20_000,
  });
  // Items keep their unread look while the list is open; only the count clears.
  const markRead = useMutation({
    mutationFn: () => api.post('/api/notifications/read'),
    onSuccess: () => qc.setQueryData<Notifications>(KEY, (d) => d && { ...d, unread: 0 }),
  });

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    const onClick = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onClick);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onClick);
    };
  }, [open]);

  // The bell can wrap anywhere in the header, so the panel is placed from where it is, kept 16px inside the screen.
  const [place, setPlace] = useState({ left: 0, width: 352 });
  const toggle = () => {
    if (!open && box.current) {
      const r = box.current.getBoundingClientRect();
      const width = Math.min(352, window.innerWidth - 32);
      setPlace({ left: Math.min(Math.max(16, r.right - width), window.innerWidth - 16 - width) - r.left, width });
    }
    if (!open && data?.unread) markRead.mutate();
    setOpen(!open);
  };
  const go = (n: Notification) => {
    setOpen(false);
    if (n.project_id) navigate(`/projects/${n.project_id}${n.task_id ? `?task=${n.task_id}` : ''}`);
  };
  const unread = data?.unread ?? 0;

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        className="clv-icon-btn"
        aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}
        aria-expanded={open}
        onClick={toggle}
      >
        <Bell aria-hidden="true" />
        {unread > 0 && <span className="clv-dot" />}
      </button>
      {open && (
        <div className="absolute top-full z-40 mt-2 rounded-2xl bg-surface p-2 shadow-float" style={place}>
          <h2 className="px-2 pb-1 pt-1.5 text-[14px] font-bold">Notifications</h2>
          {!data?.items.length ? (
            <p className="px-2 pb-2 text-[13px] text-ink-muted">Nothing yet. You'll hear here when work is given to you.</p>
          ) : (
            <ul className="max-h-96 overflow-y-auto">
              {data.items.map((n) => (
                <li key={n.id}>
                  <button
                    type="button"
                    onClick={() => go(n)}
                    className={`flex w-full gap-2 rounded-xl px-2 py-2 text-left text-[13px] hover:bg-surface-sunken ${n.read_at ? 'text-ink-muted' : 'text-ink'}`}
                  >
                    <span aria-hidden="true" className={`mt-1.5 h-2 w-2 flex-none rounded-full ${n.read_at ? '' : 'bg-primary'}`} />
                    <span className="min-w-0 flex-1">
                      <span className={n.read_at ? '' : 'font-semibold'}>{n.text}</span>
                      <span className="block text-[11px] text-ink-subtle">
                        {new Date(n.created_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
