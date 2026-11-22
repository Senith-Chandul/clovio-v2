import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '../../api/client';
import type { Member, Milestone, Project, Task, TaskStatus } from '../../api/types';
import { STATUS_LABEL, STATUSES, fmtDate } from '../../lib/format';
import { DateField, EditableText, HoursField } from '../../ui/Editable';
import { toast } from '../../ui/toast';
import { keys, useTaskActions } from '../projects/queries';
import { MemberSelect, StatusSelect } from './fields';

interface Props {
  project: Project;
  tasks: Task[];
  canManage: boolean;
  onOpen: (taskId: string) => void;
}

/** Tasks grouped by milestone. Every field edits in place; tick tasks to change several at once. */
export default function TaskList({ project, tasks, canManage, onOpen }: Props) {
  const actions = useTaskActions(project.id);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const toggle = (id: string) =>
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const groups: { milestone: Milestone | null; tasks: Task[] }[] = [
    ...project.milestones.map((m) => ({ milestone: m, tasks: tasks.filter((t) => t.milestone_id === m.id) })),
    { milestone: null, tasks: tasks.filter((t) => !t.milestone_id || !project.milestones.some((m) => m.id === t.milestone_id)) },
  ];
  const ids = [...selected].filter((id) => tasks.some((t) => t.id === id));

  const bulk = (patch: Parameters<typeof actions.bulk.mutate>[0]['patch'], message: string) =>
    actions.bulk.mutate({ ids, patch }, { onSuccess: () => toast(message) });

  return (
    <div className="flex flex-col gap-4">
      {groups.map(({ milestone, tasks: group }) =>
        // "No milestone" shows when it has tasks, or when there are no milestones to add tasks to.
        milestone || group.length || !project.milestones.length ? (
          <MilestoneGroup
            key={milestone?.id ?? 'none'}
            project={project}
            milestone={milestone}
            tasks={group}
            canManage={canManage}
            selected={selected}
            onToggle={toggle}
            onOpen={onOpen}
          />
        ) : null,
      )}
      {canManage && <AddMilestone projectId={project.id} />}

      {ids.length > 0 && (
        <div className="sticky bottom-4 z-10 flex flex-wrap items-center gap-2 self-center rounded-[22px] bg-inverse px-4 py-2 text-on-inverse shadow-float">
          <span className="px-1 text-[13px] font-semibold">{ids.length} selected</span>
          <select aria-label="Set the status of the selected tasks" className="clv-select" value="" onChange={(e) => bulk({ status: e.target.value as TaskStatus }, `Moved ${ids.length} to ${STATUS_LABEL[e.target.value as TaskStatus].toLowerCase()}`)}>
            <option value="" disabled>Status</option>
            {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select>
          <select aria-label="Assign the selected tasks" className="clv-select" value="" onChange={(e) => bulk({ assignee_id: e.target.value === 'none' ? null : e.target.value }, `Reassigned ${ids.length}`)}>
            <option value="" disabled>Assign to</option>
            <option value="none">Unassigned</option>
            {project.members.map((m) => <option key={m.user_id} value={m.user_id}>{m.name}</option>)}
          </select>
          <DateField ariaLabel="Due date for the selected tasks" className="clv-select" value={null} onSave={(d) => d && bulk({ due_date: d }, `Moved ${ids.length} to ${fmtDate(d)}`)} />
          {canManage && (
            <button
              type="button"
              className="clv-btn clv-btn-sm bg-danger-soft text-danger-text"
              onClick={() => {
                if (window.confirm(`Delete ${ids.length} ${ids.length === 1 ? 'task' : 'tasks'}? This can't be undone.`)) {
                  actions.remove.mutate(ids, { onSuccess: () => toast(`Deleted ${ids.length}`) });
                  setSelected(new Set());
                }
              }}
            >
              Delete
            </button>
          )}
          <button type="button" className="clv-btn clv-btn-sm clv-btn-inverse" onClick={() => setSelected(new Set())}>Clear</button>
        </div>
      )}
    </div>
  );
}

function MilestoneGroup({ project, milestone, tasks, canManage, selected, onToggle, onOpen }: {
  project: Project; milestone: Milestone | null; tasks: Task[]; canManage: boolean; selected: Set<string>;
  onToggle: (id: string) => void; onOpen: (id: string) => void;
}) {
  const actions = useTaskActions(project.id);
  const qc = useQueryClient();
  const [title, setTitle] = useState('');
  const editMilestone = useMutation({
    mutationFn: (patch: { title?: string; due_date?: string | null }) => api.patch(`/api/milestones/${milestone!.id}`, patch),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.project(project.id) }),
    onError: (error) => toast(errorMessage(error, "Couldn't save the milestone.")),
  });
  const done = tasks.filter((t) => t.status === 'done').length;

  const addTask = (e: FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    actions.create.mutate({ id: crypto.randomUUID(), title: title.trim(), milestone_id: milestone?.id ?? null });
    setTitle('');
  };

  return (
    <section className="clv-card gap-1">
      <div className="clv-card-head flex-wrap pb-2">
        <div className="min-w-48 flex-1">
          {milestone && canManage ? (
            <EditableText ariaLabel="Milestone title" className="w-full rounded-md bg-transparent text-title font-bold focus:bg-surface-sunken" value={milestone.title} onSave={(v) => editMilestone.mutate({ title: v })} />
          ) : (
            <h2 className="clv-card-title">{milestone?.title ?? 'No milestone'}</h2>
          )}
          <p className="clv-card-sub">{done}/{tasks.length} done{milestone?.description ? ` · ${milestone.description}` : ''}</p>
        </div>
        {milestone && (canManage ? (
          <DateField ariaLabel="Milestone due date" className="clv-select" value={milestone.due_date} onSave={(d) => editMilestone.mutate({ due_date: d })} />
        ) : (
          milestone.due_date && <span className="clv-chip">Due {fmtDate(milestone.due_date)}</span>
        ))}
      </div>

      {tasks.map((t) => (
        <TaskRow key={t.id} task={t} members={project.members} checked={selected.has(t.id)} onToggle={onToggle} onOpen={onOpen} actions={actions} />
      ))}

      <form onSubmit={addTask} className="border-t border-line pt-3">
        <input aria-label={`Add a task to ${milestone?.title ?? 'no milestone'}`} className="clv-select h-9 w-full text-[13px]" placeholder="Add a task, then press Enter" value={title} onChange={(e) => setTitle(e.target.value)} />
      </form>
    </section>
  );
}

function TaskRow({ task, members, checked, onToggle, onOpen, actions }: {
  task: Task; members: Member[]; checked: boolean; onToggle: (id: string) => void; onOpen: (id: string) => void;
  actions: ReturnType<typeof useTaskActions>;
}) {
  const done = task.status === 'done';
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line py-2.5">
      <input type="checkbox" aria-label={`Select ${task.title}`} className="h-4 w-4 accent-primary" checked={checked} onChange={() => onToggle(task.id)} />
      <button type="button" onClick={() => onOpen(task.id)} className={`min-w-40 flex-1 text-left text-[14px] font-semibold hover:text-primary ${done ? 'text-ink-muted line-through' : ''}`}>
        {task.title}
      </button>
      <div className="flex flex-wrap items-center gap-2">
        {task.at_risk && !done && <span className="clv-chip clv-chip-bad" title={task.assignment_note}>At risk</span>}
        <StatusSelect label={`Status of ${task.title}`} value={task.status} onChange={(status) => actions.change(task, { status }, `Marked ${STATUS_LABEL[status].toLowerCase()}`)} />
        <MemberSelect label={`Assignee of ${task.title}`} value={task.assignee_id} members={members} onChange={(assignee_id) => actions.change(task, { assignee_id }, 'Reassigned')} />
        <DateField ariaLabel={`Due date for ${task.title}`} className="clv-select" value={task.due_date} onSave={(due_date) => actions.change(task, { due_date }, 'Due date changed')} />
        <HoursField ariaLabel={`Hours for ${task.title}`} className="clv-select w-16 text-center" value={task.estimate_hours} onSave={(estimate_hours) => actions.change(task, { estimate_hours }, 'Estimate changed')} />
      </div>
    </div>
  );
}

function AddMilestone({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState('');
  const add = useMutation({
    mutationFn: () => api.post(`/api/projects/${projectId}/milestones`, { title: title.trim() }),
    onSuccess: () => {
      setTitle('');
      qc.invalidateQueries({ queryKey: keys.project(projectId) });
    },
    onError: (error) => toast(errorMessage(error, "Couldn't add the milestone.")),
  });
  return (
    <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (title.trim()) add.mutate(); }}>
      <input aria-label="New milestone" className="clv-input max-w-sm bg-surface" placeholder="Add a milestone" value={title} onChange={(e) => setTitle(e.target.value)} />
      <button type="submit" className="clv-btn clv-btn-secondary" disabled={add.isPending}>Add</button>
    </form>
  );
}
