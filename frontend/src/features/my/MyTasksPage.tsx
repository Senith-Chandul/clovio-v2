import { Link } from 'react-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2 } from 'lucide-react';
import { api, errorMessage } from '../../api/client';
import type { MyTask, TaskStatus } from '../../api/types';
import AppShell from '../../layout/AppShell';
import { STATUS_LABEL, fmtDate } from '../../lib/format';
import { toast } from '../../ui/toast';
import AssistBar from '../assist/AssistBar';
import { StatusSelect } from '../project/fields';

const isoDay = (offset = 0) => {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

/** Your open work across every started project, by when it's due. Built for a phone: the mic is at the top. */
export default function MyTasksPage() {
  const qc = useQueryClient();
  const tasks = useQuery({
    queryKey: ['my-tasks'],
    queryFn: () => api.get<MyTask[]>('/api/my/tasks').then((r) => r.data),
    refetchInterval: 15_000,
  });
  const update = useMutation({
    mutationFn: ({ id, status }: { id: string; status: TaskStatus }) => api.patch(`/api/tasks/${id}`, { status }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['my-tasks'] });
      qc.invalidateQueries({ queryKey: ['tasks'] });
    },
    onError: (error) => toast(errorMessage(error, "Couldn't save that change.")),
  });
  const setStatus = (task: MyTask, status: TaskStatus) =>
    update.mutate(
      { id: task.id, status },
      { onSuccess: () => toast(`Marked ${STATUS_LABEL[status].toLowerCase()}`, { undo: () => update.mutate({ id: task.id, status: task.status }) }) },
    );

  const today = isoDay();
  const weekEnd = isoDay(7);
  const all = tasks.data ?? [];
  const groups: [string, MyTask[]][] = [
    ['Overdue', all.filter((t) => t.due && t.due < today)],
    ['Due today', all.filter((t) => t.due === today)],
    ['This week', all.filter((t) => t.due && t.due > today && t.due <= weekEnd)],
    ['Later', all.filter((t) => t.due && t.due > weekEnd)],
    ['No date', all.filter((t) => !t.due)],
  ];

  return (
    <AppShell title="My tasks" subtitle="Your open work in every project. Say what changed and Clovio updates it.">
      <AssistBar />
      {tasks.isError && <p className="text-sm text-danger-text">{errorMessage(tasks.error, "Couldn't load your tasks.")}</p>}
      {tasks.data && all.length === 0 && (
        <section className="clv-card items-center py-12 text-center">
          <CheckCircle2 aria-hidden="true" className="h-6 w-6 text-secondary-text" />
          <h2 className="clv-card-title">Nothing on your plate</h2>
          <p className="text-[13px] text-ink-muted">Tasks given to you in started projects show up here.</p>
        </section>
      )}
      {groups.map(([label, group]) =>
        group.length ? (
          <section key={label} className="clv-card gap-0">
            <h2 className={`pb-2 text-[14px] font-bold ${label === 'Overdue' ? 'text-danger-text' : ''}`}>{label} · {group.length}</h2>
            {group.map((t) => (
              <div key={t.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line py-3">
                <div className="min-w-48 flex-1">
                  <Link to={`/projects/${t.project_id}?task=${t.id}`} className="text-[14px] font-semibold hover:text-primary">{t.title}</Link>
                  <div className="text-[12px] text-ink-muted">
                    {t.project_name}
                    {t.due && ` · due ${fmtDate(t.due)}`}
                    {t.estimate_hours ? ` · ${t.estimate_hours} h` : ''}
                  </div>
                </div>
                <StatusSelect label={`Status of ${t.title}`} value={t.status} onChange={(s) => setStatus(t, s)} />
              </div>
            ))}
          </section>
        ) : null,
      )}
    </AppShell>
  );
}
