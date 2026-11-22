import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Trash2, X } from 'lucide-react';
import { api, errorMessage } from '../../api/client';
import type { Project, Task, TaskEvent } from '../../api/types';
import { STATUS_LABEL, fmtDate, splitSkills } from '../../lib/format';
import { DateField, EditableText, HoursField } from '../../ui/Editable';
import { toast } from '../../ui/toast';
import { keys, useTaskActions, useTaskEvents } from '../projects/queries';
import { MemberSelect, StatusSelect } from './fields';

const FIELD_LABEL: Record<string, string> = {
  title: 'the title', description: 'the description', estimate_hours: 'the estimate', due_date: 'the due date',
  required_skills: 'the skills', milestone_id: 'the milestone', position: 'the order', depends_on: 'what it waits on',
};

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[12px] font-semibold text-ink-muted">{label}</span>
      {children}
    </div>
  );
}

/** One line of history, in words. */
function describe(event: TaskEvent, names: Map<string, string>): string {
  const who = event.source === 'ai' ? 'Clovio' : event.actor_name ?? 'Someone';
  const data = event.data as Record<string, unknown>;
  switch (event.kind) {
    case 'created':
      return event.source === 'ai' ? 'Added by the AI plan' : `${who} added it`;
    case 'status':
      return `${who} moved it to ${STATUS_LABEL[data.to as Task['status']]?.toLowerCase() ?? data.to}`;
    case 'assigned':
      return data.to ? `${who} gave it to ${names.get(data.to as string) ?? 'someone who left'}` : `${who} unassigned it`;
    case 'edited':
      return `${who} changed ${Object.keys(data.fields as object).map((f) => FIELD_LABEL[f] ?? f).join(', ')}`;
    case 'deleted':
      return `${who} deleted it`;
    default:
      return '';
  }
}

export default function TaskDrawer({ task, project, tasks, canManage, onClose }: {
  task: Task; project: Project; tasks: Task[]; canManage: boolean; onClose: () => void;
}) {
  const actions = useTaskActions(project.id);
  const events = useTaskEvents(task.id);
  const qc = useQueryClient();
  const [note, setNote] = useState('');
  const names = new Map(project.members.map((m) => [m.user_id, m.name]));
  const others = tasks.filter((t) => t.id !== task.id && !task.depends_on.includes(t.id));
  const change = actions.change.bind(null, task);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const addNote = useMutation({
    mutationFn: (text: string) => api.post(`/api/tasks/${task.id}/notes`, { text }),
    onSuccess: () => {
      setNote('');
      qc.invalidateQueries({ queryKey: keys.events(task.id) });
    },
    onError: (error) => toast(errorMessage(error, "Couldn't add the note.")),
  });
  const submitNote = (e: FormEvent) => {
    e.preventDefault();
    if (note.trim()) addNote.mutate(note.trim());
  };

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-scrim/30" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside role="dialog" aria-modal="true" aria-label={task.title} className="flex h-full w-full max-w-lg flex-col gap-5 overflow-y-auto bg-surface p-6 shadow-float">
        <div className="flex items-start gap-2">
          <EditableText ariaLabel="Title" className="min-w-0 flex-1 rounded-md bg-transparent text-title font-bold focus:bg-surface-sunken" value={task.title} onSave={(title) => change({ title }, 'Renamed')} />
          {canManage && (
            <button
              type="button"
              className="clv-icon-btn h-9 w-9 bg-ground"
              aria-label="Delete this task"
              onClick={() => {
                if (window.confirm(`Delete "${task.title}"? This can't be undone.`)) {
                  actions.remove.mutate([task.id], { onSuccess: () => toast('Task deleted') });
                  onClose();
                }
              }}
            >
              <Trash2 aria-hidden="true" />
            </button>
          )}
          <button type="button" className="clv-icon-btn h-9 w-9 bg-ground" aria-label="Close" onClick={onClose}>
            <X aria-hidden="true" />
          </button>
        </div>

        {task.status !== 'done' && (task.at_risk || task.forecast_finish) && (
          <p className={`rounded-lg px-3 py-2 text-[12px] ${task.at_risk ? 'bg-danger-soft text-danger-text' : 'bg-surface-sunken text-ink-muted'}`}>
            {task.forecast_finish ? `Should be done ${fmtDate(task.forecast_finish)}` : "Doesn't fit in anyone's time yet"}
            {task.at_risk && task.due_date && `, after its due date (${fmtDate(task.due_date)})`}.
          </p>
        )}

        <div className="grid grid-cols-2 gap-3">
          <Field label="Status"><StatusSelect value={task.status} onChange={(status) => change({ status }, `Marked ${STATUS_LABEL[status].toLowerCase()}`)} /></Field>
          <Field label="Assignee"><MemberSelect className="max-w-none" value={task.assignee_id} members={project.members} onChange={(assignee_id) => change({ assignee_id }, 'Reassigned')} /></Field>
          <Field label="Due"><DateField ariaLabel="Due date" className="clv-select" value={task.due_date} onSave={(due_date) => change({ due_date }, 'Due date changed')} /></Field>
          <Field label="Hours of work"><HoursField ariaLabel="Hours of work" className="clv-select" value={task.estimate_hours} onSave={(estimate_hours) => change({ estimate_hours }, 'Estimate changed')} /></Field>
          <Field label="Milestone">
            <select aria-label="Milestone" className="clv-select" value={task.milestone_id ?? ''} onChange={(e) => change({ milestone_id: e.target.value || null }, 'Moved')}>
              <option value="">No milestone</option>
              {project.milestones.map((m) => <option key={m.id} value={m.id}>{m.title}</option>)}
            </select>
          </Field>
          <Field label="Skills">
            <EditableText ariaLabel="Skills, comma-separated" className="clv-select" placeholder="e.g. catering" allowEmpty value={task.required_skills.join(', ')} onSave={(v) => change({ required_skills: splitSkills(v) }, 'Skills changed')} />
          </Field>
        </div>

        {task.assignment_note && <p className="text-[12px] text-ink-muted">Why this person: {task.assignment_note}</p>}

        <Field label="Description">
          <EditableText multiline allowEmpty ariaLabel="Description" className="clv-input" placeholder="What does done look like?" value={task.description} onSave={(description) => change({ description }, 'Description saved')} />
        </Field>

        <Field label="Waits on">
          <div className="flex flex-wrap gap-1.5">
            {task.depends_on.map((id) => (
              <span key={id} className="clv-chip">
                {tasks.find((t) => t.id === id)?.title ?? 'A deleted task'}
                <button type="button" aria-label="Stop waiting on this" onClick={() => change({ depends_on: task.depends_on.filter((d) => d !== id) }, 'Updated')}>
                  <X aria-hidden="true" />
                </button>
              </span>
            ))}
            {!task.depends_on.length && <span className="text-[12px] text-ink-muted">Nothing; it can start any time.</span>}
          </div>
          {others.length > 0 && (
            <select aria-label="Add a task this one waits on" className="clv-select mt-1" value="" onChange={(e) => change({ depends_on: [...task.depends_on, e.target.value] }, 'Updated')}>
              <option value="" disabled>Add a task it waits on</option>
              {others.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
            </select>
          )}
        </Field>

        <section className="flex flex-col gap-3 border-t border-line pt-4">
          <h3 className="text-[14px] font-bold">Notes and history</h3>
          <form onSubmit={submitNote} className="flex gap-2">
            <input aria-label="Add a note" className="clv-input" placeholder="Add a note, e.g. supplies are delivered" value={note} onChange={(e) => setNote(e.target.value)} />
            <button type="submit" className="clv-btn clv-btn-secondary bg-ground" disabled={addNote.isPending}>Add</button>
          </form>
          {events.data?.map((event) => (
            <div key={event.id} className="text-[12px]">
              {event.kind === 'note' ? (
                <div className="rounded-lg bg-surface-sunken px-3 py-2">
                  <div className="font-semibold">{event.actor_name ?? 'Someone'}{event.source === 'voice' && ' (by voice)'}</div>
                  <div className="whitespace-pre-wrap text-[13px]">{String((event.data as { text?: string }).text ?? '')}</div>
                </div>
              ) : (
                <span className="text-ink-muted">{describe(event, names)}{event.source === 'voice' && ' (by voice)'}</span>
              )}
              <span className="ml-2 text-ink-subtle">{new Date(event.created_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}</span>
            </div>
          ))}
        </section>
      </aside>
    </div>
  );
}
