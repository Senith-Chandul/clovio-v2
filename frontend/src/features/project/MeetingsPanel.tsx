import { useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CalendarPlus, X } from 'lucide-react';
import { api, errorMessage } from '../../api/client';
import type { Meeting, MeetingIn, Project, SuggestOut } from '../../api/types';
import Modal from '../../ui/Modal';
import { toast } from '../../ui/toast';
import { useMe } from '../auth/useMe';

const LENGTHS = [15, 30, 45, 60, 90, 120];
const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
/** The value a datetime-local input wants: local time, to the minute. */
const localInput = (iso: string) => {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

function NewMeeting({ project, onClose }: { project: Project; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: me } = useMe();
  const others = project.members.filter((m) => m.user_id !== me?.id);
  const [title, setTitle] = useState('');
  const [invited, setInvited] = useState<string[]>(others.map((m) => m.user_id));
  const [minutes, setMinutes] = useState(30);
  const [start, setStart] = useState('');
  const [location, setLocation] = useState('');

  const suggest = useMutation({
    mutationFn: () =>
      api.post<SuggestOut>(`/api/projects/${project.id}/meetings/suggest`, { attendee_ids: invited, minutes }).then((r) => r.data),
  });
  const create = useMutation({
    mutationFn: (body: MeetingIn) => api.post(`/api/projects/${project.id}/meetings`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['meetings', project.id] });
      toast('Added to your calendar. Invites are on their way.');
      onClose();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate({ title, starts_at: new Date(start).toISOString(), minutes, attendee_ids: invited, location, description: '' });
  };
  const toggle = (id: string) => {
    setInvited((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));
    suggest.reset();
  };

  return (
    <Modal isOpen onClose={onClose} title="New meeting" size="sm">
      <form className="space-y-4" onSubmit={submit}>
        <div>
          <label htmlFor="meeting-title" className="clv-field-label">What's it about</label>
          <input id="meeting-title" required className="clv-input" placeholder="e.g. Venue walk-through" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <fieldset>
          <legend className="clv-field-label">Who</legend>
          {others.length === 0 && <p className="text-[13px] text-ink-muted">Nobody else is in this project yet.</p>}
          <div className="flex flex-wrap gap-2">
            {others.map((m) => (
              <label key={m.user_id} className={`clv-chip cursor-pointer ${invited.includes(m.user_id) ? 'clv-chip-info' : ''}`}>
                <input type="checkbox" className="sr-only" checked={invited.includes(m.user_id)} onChange={() => toggle(m.user_id)} />
                {m.name}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="flex flex-wrap items-start gap-3">
          <div>
            <label htmlFor="meeting-length" className="clv-field-label">How long</label>
            <select id="meeting-length" className="clv-select" value={minutes} onChange={(e) => { setMinutes(Number(e.target.value)); suggest.reset(); }}>
              {LENGTHS.map((n) => <option key={n} value={n}>{n < 60 ? `${n} min` : `${n / 60} h`}</option>)}
            </select>
          </div>
          <div className="min-w-48 flex-1">
            <label htmlFor="meeting-start" className="clv-field-label">When</label>
            <input id="meeting-start" type="datetime-local" required className="clv-input" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
        </div>
        <div className="space-y-2">
          <button type="button" className="clv-btn clv-btn-secondary clv-btn-sm bg-ground" disabled={suggest.isPending} onClick={() => suggest.mutate()}>
            {suggest.isPending ? 'Checking calendars' : 'Suggest a time'}
          </button>
          {suggest.isError && <p className="text-[13px] text-danger-text">{errorMessage(suggest.error, "Couldn't check calendars.")}</p>}
          {suggest.data && (
            <>
              {suggest.data.slots.length === 0 && <p className="text-[13px] text-ink-muted">No time in the next two weeks suits everyone.</p>}
              <div className="flex flex-wrap gap-2">
                {suggest.data.slots.map((s) => (
                  <button key={s} type="button" aria-pressed={start === localInput(s)}
                    className={`clv-chip cursor-pointer ${start === localInput(s) ? 'clv-chip-info' : ''}`} onClick={() => setStart(localInput(s))}>
                    {when(s)}
                  </button>
                ))}
              </div>
              {suggest.data.unknown.length > 0 && (
                <p className="text-[12px] text-ink-muted">
                  These don't account for {suggest.data.unknown.map((n) => (n === me?.name ? 'you' : n)).join(', ')}: no calendar connected.
                </p>
              )}
            </>
          )}
        </div>
        <div>
          <label htmlFor="meeting-where" className="clv-field-label">Where (optional)</label>
          <input id="meeting-where" className="clv-input" placeholder="A room, an address or a call link" value={location} onChange={(e) => setLocation(e.target.value)} />
        </div>
        {create.isError && (
          <p role="alert" className="text-sm text-danger-text">
            {errorMessage(create.error, "Couldn't set up the meeting.")}{' '}
            {errorMessage(create.error, '').includes('Settings') && <Link to="/settings" className="font-semibold underline">Open Settings</Link>}
          </p>
        )}
        <button type="submit" className="clv-btn clv-btn-primary w-full" disabled={create.isPending}>
          {create.isPending ? 'Sending invites' : 'Send invites'}
        </button>
      </form>
    </Modal>
  );
}

/** Upcoming meetings for the project. Each lives in its organiser's calendar, which sends the invites. */
export default function MeetingsPanel({ project }: { project: Project }) {
  const qc = useQueryClient();
  const { data: me } = useMe();
  const [creating, setCreating] = useState(false);
  const meetings = useQuery({
    queryKey: ['meetings', project.id],
    queryFn: () => api.get<Meeting[]>(`/api/projects/${project.id}/meetings`).then((r) => r.data),
    refetchInterval: 30_000,
  });
  const cancel = useMutation({
    mutationFn: (m: Meeting) => api.delete(`/api/meetings/${m.id}`),
    onSuccess: () => toast('Cancelled. Everyone invited has been told.'),
    onError: (error) => toast(errorMessage(error, "Couldn't cancel it.")),
    onSettled: () => qc.invalidateQueries({ queryKey: ['meetings', project.id] }),
  });
  const names = new Map(project.members.map((m) => [m.email, m.name]));

  return (
    <section className="clv-card">
      <div className="clv-card-head">
        <div>
          <h2 className="clv-card-title">Meetings</h2>
          <p className="clv-card-sub">They go into your calendar, and your calendar sends the invites.</p>
        </div>
        <button type="button" className="clv-btn clv-btn-primary clv-btn-sm" onClick={() => setCreating(true)}>
          <CalendarPlus aria-hidden="true" /> New meeting
        </button>
      </div>
      {meetings.isError && <p className="text-sm text-danger-text">{errorMessage(meetings.error, "Couldn't load meetings.")}</p>}
      {meetings.data?.length === 0 && <p className="text-[13px] text-ink-muted">No meetings coming up.</p>}
      <div className="grid gap-3 md:grid-cols-2">
        {meetings.data?.map((m) => (
          <article key={m.id} className="clv-event">
            <div className="clv-event-head">
              <div className="min-w-0">
                <h3 className="truncate">{m.title}</h3>
                <div className="clv-event-when">
                  {when(m.starts_at)} – {new Date(m.ends_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
                </div>
              </div>
              {m.organizer_id === me?.id && (
                <button type="button" className="clv-event-open" aria-label={`Cancel ${m.title}`} title="Cancel the meeting"
                  disabled={cancel.isPending} onClick={() => window.confirm(`Cancel “${m.title}” for everyone?`) && cancel.mutate(m)}>
                  <X aria-hidden="true" />
                </button>
              )}
            </div>
            {m.location && <div className="clv-event-where">{m.location}</div>}
            <div className="clv-event-where">
              {m.organizer_name ?? 'Someone'} with {m.attendee_emails.map((e) => names.get(e) ?? e).join(', ') || 'nobody else'}
            </div>
          </article>
        ))}
      </div>
      {creating && <NewMeeting project={project} onClose={() => setCreating(false)} />}
    </section>
  );
}
