import { useState } from 'react';
import type { Project, Task, TaskStatus } from '../../api/types';
import { STATUS_LABEL, STATUSES, fmtDate } from '../../lib/format';
import Avatar from '../../ui/Avatar';
import { useTaskActions } from '../projects/queries';
import { StatusSelect } from './fields';

/** Columns by status. Drag cards on a computer; every card also has a status menu, for phones and keyboards. */
export default function TaskBoard({ project, tasks, onOpen }: { project: Project; tasks: Task[]; onOpen: (id: string) => void }) {
  const actions = useTaskActions(project.id);
  const [over, setOver] = useState<TaskStatus | null>(null);
  const names = new Map(project.members.map((m) => [m.user_id, m.name]));
  const move = (task: Task, status: TaskStatus) => {
    if (task.status !== status) actions.change(task, { status }, `Moved to ${STATUS_LABEL[status].toLowerCase()}`);
  };

  return (
    <div className="grid items-start gap-3 md:grid-cols-2 xl:grid-cols-4">
      {STATUSES.map((status) => {
        const column = tasks.filter((t) => t.status === status);
        return (
          <section
            key={status}
            aria-label={STATUS_LABEL[status]}
            className={`clv-card min-h-40 gap-2 ${over === status ? 'shadow-[inset_0_0_0_2px_var(--primary)]' : ''}`}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(status);
            }}
            onDragLeave={() => setOver(null)}
            onDrop={(e) => {
              setOver(null);
              const task = tasks.find((t) => t.id === e.dataTransfer.getData('text/plain'));
              if (task) move(task, status);
            }}
          >
            <header className="flex items-center justify-between">
              <h2 className="text-[14px] font-bold">{STATUS_LABEL[status]}</h2>
              <span className="clv-chip">{column.length}</span>
            </header>
            {column.map((task) => {
              const assignee = task.assignee_id ? names.get(task.assignee_id) : undefined;
              return (
                <article
                  key={task.id}
                  draggable
                  onDragStart={(e) => e.dataTransfer.setData('text/plain', task.id)}
                  className="flex cursor-grab flex-col gap-2 rounded-lg bg-surface-sunken p-3 active:cursor-grabbing"
                >
                  <button type="button" onClick={() => onOpen(task.id)} className="text-left text-[13px] font-semibold hover:text-primary">
                    {task.title}
                  </button>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {assignee ? <Avatar name={assignee} size="sm" /> : <span className="clv-chip clv-chip-quiet">Unassigned</span>}
                    {task.due_date && <span className="clv-chip clv-chip-quiet">{fmtDate(task.due_date)}</span>}
                    {task.at_risk && status !== 'done' && <span className="clv-chip clv-chip-bad" title={task.assignment_note}>At risk</span>}
                    <StatusSelect label={`Status of ${task.title}`} className="ml-auto" value={task.status} onChange={(s) => move(task, s)} />
                  </div>
                </article>
              );
            })}
          </section>
        );
      })}
    </div>
  );
}
