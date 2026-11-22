import type { ReactNode } from 'react';
import type { Milestone, Project, Task } from '../../api/types';

const DAY = 86_400_000;
const MAX_DAYS = 180;
/** An ISO date as local midnight, so a date never shows as the day before. */
const day = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00`);
const short = (d: Date) => d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });

/** The track behind every row: a line each Monday, and the deadline dashed. Positions are percentages. */
function Track({ weeks, deadline, children }: { weeks: number[]; deadline: number | null; children?: ReactNode }) {
  return (
    <div className="relative h-8 min-w-0 flex-1">
      {weeks.map((left) => <span key={left} className="absolute inset-y-0 w-px bg-line" style={{ left: `${left}%` }} />)}
      {deadline !== null && <span className="absolute inset-y-0 border-l-2 border-dashed border-ink-muted" style={{ left: `${deadline}%` }} />}
      {children}
    </div>
  );
}

/** When the open work happens, from the scheduler's forecast: a bar from planned start to finish, the due date as a line. */
export default function TaskTimeline({ project, tasks, onOpen }: { project: Project; tasks: Task[]; onOpen: (taskId: string) => void }) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const open = tasks.filter((t) => t.status !== 'done');
  const milestoneDue = new Map(project.milestones.map((m) => [m.id, m.due_date]));
  const due = (t: Task) => t.due_date ?? (t.milestone_id && milestoneDue.get(t.milestone_id)) ?? project.deadline ?? null;

  // From today to whichever is last: the deadline, a due date or a finish; at least two weeks.
  const ends = [project.deadline, ...open.map((t) => t.forecast_finish), ...open.map(due), ...project.milestones.map((m) => m.due_date)]
    .filter((d): d is string => Boolean(d))
    .map((d) => (day(d).getTime() - today.getTime()) / DAY);
  const days = Math.min(MAX_DAYS, Math.max(14, ...ends) + 2);
  const at = (iso: string) => Math.min(100, Math.max(0, (Math.round((day(iso).getTime() - today.getTime()) / DAY) / days) * 100));
  const mondays = Array.from({ length: days }, (_, i) => i).filter((i) => new Date(today.getTime() + i * DAY).getDay() === 1);
  const weeks = mondays.map((i) => (i / days) * 100);
  const deadline = project.deadline ? at(project.deadline) : null;

  const groups: { milestone: Milestone | null; tasks: Task[] }[] = [
    ...project.milestones.map((m) => ({ milestone: m, tasks: open.filter((t) => t.milestone_id === m.id) })),
    { milestone: null, tasks: open.filter((t) => !t.milestone_id || !milestoneDue.has(t.milestone_id)) },
  ].filter((g) => g.tasks.length);
  const name = (id: string | null) => project.members.find((m) => m.user_id === id)?.name.split(' ')[0];

  if (!open.length) {
    return <section className="clv-card"><p className="text-[13px] text-ink-muted">Nothing left to do.</p></section>;
  }
  return (
    <section className="clv-card">
      <div>
        <h2 className="clv-card-title">Timeline</h2>
        <p className="clv-card-sub">
          Bars run from when work is planned to start to when it should be done. The dark line is the due date; red bars finish after it.
          {project.deadline && ' The dashed line is the deadline.'}
        </p>
      </div>
      <div className="overflow-x-auto">
        <div className="min-w-[44rem]">
          <div className="flex items-end gap-3 pb-1 text-[11px] text-ink-muted">
            <span className="w-52 shrink-0">Today, {short(today)}</span>
            <div className="relative h-4 flex-1">
              {mondays.map((i) => (
                <span key={i} className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${(i / days) * 100}%` }}>
                  {short(new Date(today.getTime() + i * DAY))}
                </span>
              ))}
            </div>
          </div>
          {groups.map(({ milestone, tasks: rows }) => (
            <div key={milestone?.id ?? 'none'} className="border-t border-line py-2">
              <div className="flex items-center gap-3">
                <span className="w-52 shrink-0 truncate text-[13px] font-bold">{milestone?.title ?? 'No milestone'}</span>
                <Track weeks={weeks} deadline={deadline}>
                  {milestone?.due_date && (
                    <span className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rotate-45 bg-ink" style={{ left: `${at(milestone.due_date)}%` }}
                      title={`Milestone due ${short(day(milestone.due_date))}`} />
                  )}
                </Track>
              </div>
              {rows.map((t) => {
                const d = due(t);
                const start = t.forecast_start ?? t.forecast_finish;
                return (
                  <div key={t.id} className="flex items-center gap-3">
                    <button type="button" onClick={() => onOpen(t.id)} className="w-52 shrink-0 truncate text-left text-[13px] hover:text-primary">
                      {t.title}
                      <span className="text-ink-muted">{name(t.assignee_id) ? ` · ${name(t.assignee_id)}` : ''}</span>
                    </button>
                    <Track weeks={weeks} deadline={deadline}>
                      {start && t.forecast_finish ? (
                        <span
                          className={`absolute top-1/2 h-3 -translate-y-1/2 rounded-full ${t.at_risk ? 'bg-danger' : 'bg-primary'}`}
                          style={{ left: `${at(start)}%`, width: `max(6px, ${at(t.forecast_finish) - at(start) + 100 / days}%)` }}
                          title={`${short(day(start))} to ${short(day(t.forecast_finish))}${t.at_risk ? ', after its due date' : ''}`}
                        />
                      ) : (
                        <span className="absolute inset-y-0 flex items-center text-[11px] text-ink-muted">{t.assignee_id ? "Doesn't fit in the next year" : 'Nobody on it yet'}</span>
                      )}
                      {d && <span className="absolute inset-y-1 w-0.5 rounded bg-ink" style={{ left: `${at(d)}%` }} title={`Due ${short(day(d))}`} />}
                    </Track>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
