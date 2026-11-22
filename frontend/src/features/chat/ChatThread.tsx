import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { SendHorizontal } from 'lucide-react';
import { api, errorMessage } from '../../api/client';
import type { ChatMessage } from '../../api/types';
import { toast } from '../../ui/toast';
import { useMe } from '../auth/useMe';
import { useChats } from './queries';

const stamp = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

/** One chat: its messages (polled every few seconds, which also marks them read) and a box to write in. */
export default function ChatThread({ chatId, className = 'h-[60vh]' }: { chatId: string; className?: string }) {
  const qc = useQueryClient();
  const { data: me } = useMe();
  const [text, setText] = useState('');
  const list = useRef<HTMLDivElement>(null);
  const messages = useQuery({
    queryKey: ['chat', chatId],
    queryFn: () => api.get<ChatMessage[]>(`/api/chats/${chatId}/messages`).then((r) => r.data),
    refetchInterval: 3_000,
  });
  const send = useMutation({
    mutationFn: (body: string) => api.post<ChatMessage>(`/api/chats/${chatId}/messages`, { body }),
    onSuccess: () => {
      setText('');
      qc.invalidateQueries({ queryKey: ['chat', chatId] });
    },
    onError: (error) => toast(errorMessage(error, "Couldn't send that.")),
  });

  // New message: show it, and refresh the unread counts (reading it marked it read).
  const lastId = messages.data?.at(-1)?.id;
  useEffect(() => {
    if (list.current) list.current.scrollTop = list.current.scrollHeight;
    qc.invalidateQueries({ queryKey: ['chats'] });
  }, [lastId, qc]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim()) send.mutate(text);
  };

  return (
    <div className="flex min-h-0 flex-col gap-3">
      <div ref={list} className={`flex flex-col gap-3 overflow-y-auto pr-1 ${className}`} aria-live="polite">
        {messages.isError && <p className="text-sm text-danger-text">{errorMessage(messages.error, "Couldn't load the messages.")}</p>}
        {messages.data?.length === 0 && <p className="m-auto text-[13px] text-ink-muted">No messages yet. Say hello.</p>}
        {messages.data?.map((m) => {
          const mine = m.sender_id === me?.id;
          return (
            <div key={m.id} className={`flex max-w-[80%] flex-col gap-1 ${mine ? 'items-end self-end' : 'items-start'}`}>
              <span className="text-[11px] text-ink-muted">{mine ? 'You' : m.sender_name ?? 'Someone who left'} · {stamp(m.created_at)}</span>
              <p className={`whitespace-pre-wrap break-words rounded-2xl px-3.5 py-2 text-[14px] ${mine ? 'bg-primary-soft' : 'bg-ground'}`}>{m.body}</p>
            </div>
          );
        })}
      </div>
      <form className="flex items-center gap-2" onSubmit={submit}>
        <input aria-label="Message" className="clv-input flex-1" placeholder="Write a message" maxLength={4000} value={text} onChange={(e) => setText(e.target.value)} />
        <button type="submit" className="clv-icon-btn bg-primary text-on-primary hover:text-on-primary" aria-label="Send" disabled={send.isPending || !text.trim()}>
          <SendHorizontal aria-hidden="true" />
        </button>
      </form>
    </div>
  );
}

/** The project's team chat, for the project page. */
export function ProjectChat({ projectId }: { projectId: string }) {
  const chats = useChats();
  const chat = chats.data?.chats.find((c) => c.project_id === projectId);
  return (
    <section className="clv-card">
      <div>
        <h2 className="clv-card-title">Team chat</h2>
        <p className="clv-card-sub">Everyone in the project can read and write here.</p>
      </div>
      {chats.isError && <p className="text-sm text-danger-text">{errorMessage(chats.error, "Couldn't load the chat.")}</p>}
      {chat && <ChatThread chatId={chat.id} />}
      {chats.data && !chat && <p className="text-[13px] text-ink-muted">This project has no chat.</p>}
    </section>
  );
}
