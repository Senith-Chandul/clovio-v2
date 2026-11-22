import { Link, NavLink, useNavigate, useParams } from 'react-router';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, FolderKanban } from 'lucide-react';
import { api, errorMessage } from '../../api/client';
import AppShell from '../../layout/AppShell';
import Avatar from '../../ui/Avatar';
import { toast } from '../../ui/toast';
import ChatThread from './ChatThread';
import { useChats } from './queries';

/** Every chat you're in: project team chats and direct messages. On a phone, the list or one chat at a time. */
export default function ChatPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const chats = useChats();
  const open = chats.data?.chats.find((c) => c.id === id);

  const direct = useMutation({
    mutationFn: (userId: string) => api.post<{ id: string }>('/api/chats/direct', { user_id: userId }).then((r) => r.data.id),
    onSuccess: (chatId) => {
      qc.invalidateQueries({ queryKey: ['chats'] });
      navigate(`/chat/${chatId}`);
    },
    onError: (error) => toast(errorMessage(error, "Couldn't start that chat.")),
  });

  return (
    <AppShell title="Chat" subtitle="Project team chats and direct messages">
      {chats.isError && <p className="text-sm text-danger-text">{errorMessage(chats.error, "Couldn't load your chats.")}</p>}
      <div className="grid items-start gap-4 lg:grid-cols-[20rem_minmax(0,1fr)]">
        <section className={`clv-card gap-0 ${id ? 'hidden lg:flex' : ''}`} aria-label="Your chats">
          {!!chats.data?.people.length && (
            <select
              aria-label="Message someone"
              className="clv-select mb-3 w-full"
              value=""
              disabled={direct.isPending}
              onChange={(e) => e.target.value && direct.mutate(e.target.value)}
            >
              <option value="">Message someone…</option>
              {chats.data.people.map((p) => <option key={p.user_id} value={p.user_id}>{p.name}</option>)}
            </select>
          )}
          {chats.data?.chats.length === 0 && <p className="text-[13px] text-ink-muted">No chats yet. Each project you join has one.</p>}
          {chats.data?.chats.map((c) => (
            <NavLink key={c.id} to={`/chat/${c.id}`} className="clv-nav-item h-auto min-h-14 gap-3 py-2">
              {c.kind === 'project' ? (
                <span className="clv-stat-icon"><FolderKanban aria-hidden="true" /></span>
              ) : (
                <Avatar name={c.title} />
              )}
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-semibold text-ink">{c.title}</span>
                <span className="block truncate text-[12px]">
                  {c.last_body ? `${c.last_sender ? `${c.last_sender.split(' ')[0]}: ` : ''}${c.last_body}` : 'No messages yet'}
                </span>
              </span>
              {c.unread > 0 && <span className="clv-nav-count" aria-label={`${c.unread} unread`}>{c.unread}</span>}
            </NavLink>
          ))}
        </section>

        <section className={`clv-card ${id ? '' : 'hidden lg:flex'}`}>
          {open ? (
            <>
              <div className="flex items-center gap-2">
                <Link to="/chat" className="clv-icon-btn h-9 w-9 bg-ground lg:hidden" aria-label="All chats">
                  <ArrowLeft aria-hidden="true" />
                </Link>
                <h2 className="clv-card-title min-w-0 flex-1 truncate">{open.title}</h2>
                {open.project_id && <Link to={`/projects/${open.project_id}`} className="clv-btn clv-btn-outline">Open project</Link>}
              </div>
              <ChatThread key={open.id} chatId={open.id} className="h-[calc(100vh-17rem)] min-h-64" />
            </>
          ) : (
            <p className="py-12 text-center text-[13px] text-ink-muted">
              {id && chats.data ? "This chat isn't available to you." : 'Pick a chat, or message someone.'}
            </p>
          )}
        </section>
      </div>
    </AppShell>
  );
}
