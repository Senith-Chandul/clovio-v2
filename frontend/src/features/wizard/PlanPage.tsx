import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, CircleAlert, LoaderCircle, Sparkles } from 'lucide-react';
import { api, errorMessage } from '../../api/client';
import type { CountOut, Milestone, Project, ScheduleOut, Task } from '../../api/types';
import AppShell from '../../layout/AppShell';
import { fmtDate } from '../../lib/format';
import { keys } from '../projects/queries';

type RowState = 'waiting' | 'working' | 'done' | 'failed';
interface Row {
  milestone: Milestone;
  state: RowState;
  count: number;
  error?: string;
}
type Phase = 'outline' | 'tasks' | 'assigning' | 'ready';

const PHASE_TEXT: Record<Phase, string> = {
  outline: 'Drafting the milestones',
  tasks: "Planning each milestone's tasks",
  assigning: 'Giving each task to whoever can finish it soonest',
  ready: 'Your plan is ready to review',
};

/**
 * Step 3: milestones, then every milestone's tasks at once, then assignment. Safe to reload: it only does the
 * parts that are missing (no milestones yet, or milestones without tasks).
 */
export default function PlanPage() {
  const { id = '' } = useParams();
  const location = useLocation();
  const qc = useQueryClient();
  const answers = (location.state as { answers?: { question: string; answer: string }[] } | null)?.answers ?? [];
  const [rows, setRows] = useState<Row[]>([]);
  const [phase, setPhase] = useState<Phase>('outline');
  const [summary, setSummary] = useState<ScheduleOut | null>(null);
  const [name, setName] = useState('');
  const started = useRef(false);

  const setRow = (milestoneId: string, change: Partial<Row>) =>
    setRows((all) => all.map((r) => (r.milestone.id === milestoneId ? { ...r, ...change } : r)));

  const generate = async (milestone: Milestone) => {
    setRow(milestone.id, { state: 'working', error: undefined });
    try {
      const res = await api.post<CountOut>(`/api/milestones/${milestone.id}/generate`);
      setRow(milestone.id, { state: 'done', count: res.data.count });
    } catch (error) {
      setRow(milestone.id, { state: 'failed', error: errorMessage(error, "Couldn't plan this milestone.") });
    }
  };

  const assign = async () => {
    setPhase('assigning');
    const res = await api.post<ScheduleOut>(`/api/projects/${id}/schedule`, { apply: true });
    setSummary(res.data);
    setPhase('ready');
    qc.invalidateQueries({ queryKey: keys.tasks(id) });
    qc.invalidateQueries({ queryKey: keys.project(id) });
    qc.invalidateQueries({ queryKey: keys.projects });
  };

  const run = useMutation({
    mutationFn: async () => {
      setPhase('outline');
      const project = (await api.get<Project>(`/api/projects/${id}`)).data;
      setName(project.name);
      const milestones = project.milestones.length
        ? project.milestones
        : (await api.post<Milestone[]>(`/api/projects/${id}/plan/outline`, { answers })).data;
      const tasks = (await api.get<Task[]>(`/api/projects/${id}/tasks`)).data;
      const count = (m: Milestone) => tasks.filter((t) => t.milestone_id === m.id).length;
      setRows(milestones.map((m) => ({ milestone: m, state: count(m) ? 'done' : 'waiting', count: count(m) })));
      setPhase('tasks');
      await Promise.all(milestones.filter((m) => !count(m)).map(generate));
      await assign();
      setName((await api.get<Project>(`/api/projects/${id}`)).data.name);
    },
  });
  const { mutate } = run;

  useEffect(() => {
    // Once per visit, even under StrictMode's double effects: the outline must not be requested twice.
    if (!started.current) {
      started.current = true;
      mutate();
    }
  }, [mutate]);

  const retry = useMutation({
    mutationFn: async (milestone: Milestone) => {
      await generate(milestone);
      await assign();
    },
  });

  const failed = rows.filter((r) => r.state === 'failed');
  const total = rows.reduce((sum, r) => sum + r.count, 0);

  return (
    <AppShell title={name ? `Planning ${name}` : 'Planning'} subtitle="Clovio splits the work into milestones and tasks, then assigns them.">
      <section className="clv-card max-w-3xl gap-4" aria-live="polite">
        <div className="clv-assist-title">
          {phase === 'ready' ? <CheckCircle2 aria-hidden="true" className="text-secondary-text" /> : <Sparkles aria-hidden="true" className="text-secondary-text" />}
          {run.isError ? "The plan couldn't be finished" : PHASE_TEXT[phase]}
        </div>

        {run.isError && (
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-sm text-danger-text">{errorMessage(run.error, "Couldn't make the plan.")}</p>
            <button type="button" className="clv-btn clv-btn-outline" onClick={() => run.mutate()}>Try again</button>
          </div>
        )}

        {rows.map((r) => (
          <div key={r.milestone.id} className="clv-row flex-wrap">
            {r.state === 'working' || r.state === 'waiting' ? (
              <LoaderCircle aria-hidden="true" className={`h-4 w-4 text-ink-subtle ${r.state === 'working' ? 'animate-spin' : ''}`} />
            ) : r.state === 'done' ? (
              <CheckCircle2 aria-hidden="true" className="h-4 w-4 text-secondary-text" />
            ) : (
              <CircleAlert aria-hidden="true" className="h-4 w-4 text-danger-text" />
            )}
            <div className="min-w-0 flex-1">
              <div className="text-[14px] font-semibold">{r.milestone.title}</div>
              <div className="text-caption text-ink-muted">
                {r.milestone.due_date ? `Due ${fmtDate(r.milestone.due_date)}` : 'No date'}
                {r.state === 'done' && ` · ${r.count} tasks`}
                {r.state === 'working' && ' · planning tasks'}
                {r.state === 'failed' && ` · ${r.error}`}
              </div>
            </div>
            {r.state === 'failed' && (
              <button type="button" className="clv-btn clv-btn-outline" disabled={retry.isPending} onClick={() => retry.mutate(r.milestone)}>
                Retry
              </button>
            )}
          </div>
        ))}

        {phase === 'ready' && summary && (
          <div className="flex flex-col gap-3 border-t border-line pt-4">
            <p className="text-[13px] text-ink-muted">
              {total} tasks across {rows.length} milestones.
              {summary.predicted_finish && ` Predicted finish: ${fmtDate(summary.predicted_finish)}.`}
              {summary.at_risk > 0 && ` ${summary.at_risk} ${summary.at_risk === 1 ? 'task is' : 'tasks are'} at risk of missing their date.`}
              {failed.length > 0 && ` ${failed.length} ${failed.length === 1 ? "milestone still needs" : 'milestones still need'} tasks.`}
            </p>
            <Link to={`/projects/${id}`} className="clv-btn clv-btn-primary self-start">Review the plan</Link>
          </div>
        )}
      </section>
    </AppShell>
  );
}
