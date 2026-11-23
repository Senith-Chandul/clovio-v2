import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, CalendarCheck, CheckCircle2, Clock, Timer } from 'lucide-react';
import type { ReactNode } from 'react';
import { api, errorMessage } from '../../api/client';
import type { Overview } from '../../api/types';
import { fmtDate } from '../../lib/format';
import Badge from '../../ui/Badge';
import Ring from '../../ui/Ring';

const DAY = 86_400_000;
const daysBetween = (a: string, b: string) => Math.round((Date.parse(b) - Date.parse(a)) / DAY);
const pct = (x: number) => `${Math.round(x * 100)}%`;

function Stat({ label, icon, value, sub, tone }: { label: string; icon: ReactNode; value: ReactNode; sub: string; tone?: 'spotlight' | 'positive' }) {
  return (
    <div className={`clv-stat ${tone ? `clv-stat-${tone}` : ''}`}>
      <div className="clv-stat-label">
        {label}
        <span className="clv-stat-icon">{icon}</span>
      </div>
      <div className="clv-stat-value">{value}</div>
      <p className="text-[12px] text-ink-muted">{sub}</p>
    </div>
  );
}

/** How the project is going. Everything here is worked out by the server from the tasks and the scheduler. */
export default function OverviewPanel({ projectId }: { projectId: string }) {
  // Under the tasks key, so every task change refreshes it too.
  const query = useQuery({
    queryKey: ['tasks', projectId, 'overview'],
    queryFn: () => api.get<Overview>(`/api/projects/${projectId}/overview`).then((r) => r.data),
    refetchInterval: 15_000,
  });
  if (query.isError) return <p className="text-sm text-danger-text">{errorMessage(query.error, "Couldn't load the overview.")}</p>;
  if (!query.data) {
    return (
      <section className="clv-card">
        <p className="text-[13px] text-ink-muted">Loading overview…</p>
      </section>
    );
  }
  const o = query.data;

  const margin = o.predicted_finish && o.deadline ? daysBetween(o.predicted_finish, o.deadline) : null;
  const finishSub =
    o.tasks_done === o.tasks_total && o.tasks_total > 0
      ? 'Everything is done'
      : margin === null
        ? o.deadline ? 'Assign the open tasks to get a forecast' : 'No deadline set'
        : margin >= 0
          ? `${margin} day${margin === 1 ? '' : 's'} before the deadline`
          : `${-margin} day${margin === -1 ? '' : 's'} after the deadline`;
  const warnings = [
    o.at_risk && `${o.at_risk} task${o.at_risk === 1 ? '' : 's'} won't make ${o.at_risk === 1 ? 'its' : 'their'} due date`,
    o.blocked && `${o.blocked} blocked`,
    o.unassigned && `${o.unassigned} with nobody on ${o.unassigned === 1 ? 'it' : 'them'}, so not in the forecast`,
  ].filter(Boolean);
  const scale = Math.max(1, ...o.people.map((p) => Math.max(p.open_hours, p.free_hours ?? 0)));
  const bottlenecks = o.people.filter((p) => p.bottleneck);

  return (
    <>
      <div className="clv-stat-grid">
        <Stat
          tone="spotlight"
          label="Predicted finish"
          icon={<CalendarCheck aria-hidden="true" />}
          value={o.predicted_finish ? fmtDate(o.predicted_finish) : '–'}
          sub={finishSub}
        />
        <Stat
          label="Done"
          icon={<CheckCircle2 aria-hidden="true" />}
          value={pct(o.progress)}
          sub={`${o.tasks_done} of ${o.tasks_total} tasks, by estimated hours`}
        />
        <Stat
          tone={o.on_time_rate !== null && o.on_time_rate >= 0.8 ? 'positive' : undefined}
          label="On time"
          icon={<Clock aria-hidden="true" />}
          value={o.on_time_rate === null ? '–' : pct(o.on_time_rate)}
          sub={o.on_time_of ? `of ${o.on_time_of} finished task${o.on_time_of === 1 ? '' : 's'} with a due date` : 'Nothing finished yet'}
        />
        <Stat
          label="Overdue"
          icon={<AlertTriangle aria-hidden="true" />}
          value={o.overdue}
          sub={o.overdue ? 'open past their due date' : 'Nothing past its due date'}
        />
        <Stat
          label="Cycle time"
          icon={<Timer aria-hidden="true" />}
          value={o.cycle_days === null ? '–' : `${o.cycle_days} d`}
          sub="median, in progress to done"
        />
      </div>

      {warnings.length > 0 && (
        <p className="rounded-2xl bg-warning-soft px-4 py-3 text-[13px] text-ink">{warnings.join(' · ')}</p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="clv-card">
          <div>
            <h2 className="clv-card-title">Workload</h2>
            <p className="clv-card-sub">
              Open hours per person. The dashed line is the time they have free {o.deadline ? `before ${fmtDate(o.deadline)}` : '(set a deadline to see it)'}.
            </p>
          </div>
          {o.people.length === 0 ? (
            <p className="text-[13px] text-ink-muted">No one in the project yet.</p>
          ) : (
            <div className="overflow-x-auto overflow-y-hidden">
              <div className="clv-bars mt-6" style={{ minWidth: o.people.length * 72 }} role="list">
                {o.people.map((p) => (
                  <div
                    key={p.user_id}
                    role="listitem"
                    className="relative h-full"
                    aria-label={`${p.name}: ${p.open_hours} hours open${p.free_hours !== null ? `, ${p.free_hours} free` : ''}`}
                  >
                    <div className="absolute inset-x-0 bottom-0 flex justify-center">
                      <div className={`clv-bar ${p.bottleneck ? 'clv-bar-over' : ''}`} style={{ height: `${(p.open_hours / scale) * 108}px` }}>
                        <span className="clv-bar-value">{p.open_hours} h</span>
                      </div>
                    </div>
                    {p.free_hours !== null && <div className="clv-fair-line mx-2" style={{ bottom: `${(p.free_hours / scale) * 108}px` }} />}
                    <span className="clv-bar-name max-w-[68px] truncate">{/^(dr|prof|mr|ms|mrs)\.?$/i.test(p.name.split(' ')[0]) && p.name.split(' ')[1] ? `${p.name.split(' ')[0]} ${p.name.split(' ')[1]}` : p.name.split(' ')[0]}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {bottlenecks.map((p) => (
            <p key={p.user_id} className="text-[13px] text-ink">
              <strong>{p.name}</strong> has {p.open_hours} h of work here and {p.free_hours} h free before the deadline. Rebalance, or give them fewer tasks.
            </p>
          ))}
        </section>

        <section className="clv-card gap-0">
          <h2 className="clv-card-title pb-2">Milestones</h2>
          {o.milestones.length === 0 && <p className="text-[13px] text-ink-muted">No milestones yet.</p>}
          {o.milestones.map((m) => {
            const finished = m.total > 0 && m.done === m.total;
            return (
              <div key={m.id} className="clv-row">
                <Ring percent={m.total ? (m.done / m.total) * 100 : 0} label={`${m.done} of ${m.total} done`} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[14px] font-semibold">{m.title}</div>
                  <div className="text-[12px] text-ink-muted">
                    {m.done} of {m.total} done
                    {m.due_date && ` · due ${fmtDate(m.due_date)}`}
                    {!finished && m.forecast_finish && ` · finishes ${fmtDate(m.forecast_finish)}`}
                  </div>
                </div>
                {finished ? <Badge variant="good">Done</Badge> : m.late ? <Badge variant="critical">Late</Badge> : <Badge variant="info">On track</Badge>}
              </div>
            );
          })}
        </section>
      </div>
    </>
  );
}
