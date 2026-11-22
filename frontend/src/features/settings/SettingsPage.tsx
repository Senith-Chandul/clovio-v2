import { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CalendarDays } from 'lucide-react';
import { api, errorMessage } from '../../api/client';
import type { Calendars, MeIn, Provider } from '../../api/types';
import AppShell from '../../layout/AppShell';
import { splitSkills } from '../../lib/format';
import Badge from '../../ui/Badge';
import { EditableText } from '../../ui/Editable';
import { toast } from '../../ui/toast';
import { useMe } from '../auth/useMe';

const LABEL: Record<Provider, string> = { google: 'Google Calendar', microsoft: 'Outlook calendar' };

/** Your profile (what the scheduler plans with) and your connected calendars. */
export default function SettingsPage() {
  const qc = useQueryClient();
  const { data: me } = useMe();
  const cals = useQuery({ queryKey: ['calendars'], queryFn: () => api.get<Calendars>('/api/calendars').then((r) => r.data) });

  const save = useMutation({
    mutationFn: (patch: MeIn) => api.patch('/api/me', patch),
    onSuccess: () => toast('Saved'),
    onError: (error) => toast(errorMessage(error, "Couldn't save that.")),
    onSettled: () => qc.invalidateQueries({ queryKey: ['me'] }),
  });
  const connect = useMutation({
    mutationFn: (provider: Provider) => api.post<{ url: string }>(`/api/calendars/${provider}/connect`).then((r) => r.data.url),
    onSuccess: (url) => window.location.assign(url),
    onError: (error) => toast(errorMessage(error, "Couldn't start connecting.")),
  });
  const disconnect = useMutation({
    mutationFn: (provider: Provider) => api.delete(`/api/calendars/${provider}`),
    onSuccess: () => toast('Disconnected'),
    onError: (error) => toast(errorMessage(error, "Couldn't disconnect it.")),
    onSettled: () => qc.invalidateQueries({ queryKey: ['calendars'] }),
  });

  // Coming back from Google or Microsoft: say how it went, then tidy the URL.
  useEffect(() => {
    const back = new URLSearchParams(window.location.hash.slice(1));
    const connected = back.get('connected') as Provider | null;
    if (connected) toast(`${LABEL[connected] ?? 'Calendar'} connected`);
    if (back.get('error')) toast(back.get('error')!);
    if (connected || back.get('error')) window.history.replaceState(null, '', window.location.pathname);
  }, []);

  return (
    <AppShell title="Settings" subtitle="Your profile and calendars">
      {me && (
        <section className="clv-card gap-0">
          <h2 className="clv-card-title pb-1">Profile</h2>
          <p className="clv-card-sub pb-2">Clovio plans work around your skills and the hours you can give each week.</p>
          <div className="clv-row">
            <span className="w-36 text-[13px] text-ink-muted">Name</span>
            <EditableText ariaLabel="Your name" className="clv-select min-w-0 flex-1" value={me.name} onSave={(name) => save.mutate({ name })} />
          </div>
          <div className="clv-row">
            <span className="w-36 text-[13px] text-ink-muted">Email</span>
            <span className="min-w-0 flex-1 truncate text-[13px]">{me.email}</span>
          </div>
          <div className="clv-row">
            <span className="w-36 text-[13px] text-ink-muted">Hours a week</span>
            <EditableText
              ariaLabel="Hours you can give each week"
              className="clv-select w-24 text-center"
              value={String(me.weekly_hours)}
              onSave={(v) => Number.isFinite(Number(v)) && save.mutate({ weekly_hours: Number(v) })}
            />
          </div>
          <div className="clv-row">
            <span className="w-36 text-[13px] text-ink-muted">Skills</span>
            <EditableText
              ariaLabel="Your skills"
              className="clv-select min-w-0 flex-1"
              placeholder="Comma-separated, e.g. catering, design"
              allowEmpty
              value={me.skills.join(', ')}
              onSave={(v) => save.mutate({ skills: splitSkills(v) })}
            />
          </div>
          <div className="clv-row">
            <span className="w-36 text-[13px] text-ink-muted">Time zone</span>
            <span className="text-[13px]">{me.timezone} <span className="text-ink-muted">(from this browser)</span></span>
          </div>
        </section>
      )}

      <section className="clv-card gap-0">
        <h2 className="clv-card-title pb-1">Connected calendars</h2>
        <p className="clv-card-sub pb-2">
          Clovio reads only when you're busy, not what your events are, to plan your work and suggest meeting times. Meetings you
          set up in Clovio go into your calendar, and your calendar sends the invites.
        </p>
        {cals.isError && <p className="py-2 text-sm text-danger-text">{errorMessage(cals.error, "Couldn't load your calendars.")}</p>}
        {cals.data && cals.data.available.length === 0 && (
          <p className="py-2 text-[13px] text-ink-muted">Calendar connections aren't set up on this server yet.</p>
        )}
        {cals.data?.available.map((provider) => {
          const account = cals.data.accounts.find((a) => a.provider === provider);
          return (
            <div key={provider} className="clv-row flex-wrap">
              <span className="clv-stat-icon"><CalendarDays aria-hidden="true" /></span>
              <div className="min-w-0 flex-1">
                <div className="text-[14px] font-semibold">{LABEL[provider]}</div>
                <div className="truncate text-[12px] text-ink-muted">{account ? account.email : 'Not connected'}</div>
              </div>
              {account?.needs_reconnect && <Badge variant="warning">Needs reconnecting</Badge>}
              {account && !account.needs_reconnect && <Badge variant="good">Connected</Badge>}
              {(!account || account.needs_reconnect) && (
                <button type="button" className="clv-btn clv-btn-primary clv-btn-sm" disabled={connect.isPending} onClick={() => connect.mutate(provider)}>
                  {account ? 'Reconnect' : 'Connect'}
                </button>
              )}
              {account && (
                <button type="button" className="clv-btn clv-btn-outline" disabled={disconnect.isPending} onClick={() => disconnect.mutate(provider)}>
                  Disconnect
                </button>
              )}
            </div>
          );
        })}
      </section>
    </AppShell>
  );
}
