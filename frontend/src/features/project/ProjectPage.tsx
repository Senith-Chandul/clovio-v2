import { useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Play, Shuffle, Sparkles } from 'lucide-react';
import { api, errorMessage } from '../../api/client';
import AppShell from '../../layout/AppShell';
import AssistBar from '../assist/AssistBar';
import { ProjectChat } from '../chat/ChatThread';
import { fmtDate, isManager } from '../../lib/format';
import { EditableText } from '../../ui/Editable';
import { toast } from '../../ui/toast';
import { keys, useProject, useTasks } from '../projects/queries';
import MeetingsPanel from './MeetingsPanel';
import OverviewPanel from './OverviewPanel';
import PeoplePanel from './PeoplePanel';
import RebalanceModal from './RebalanceModal';
import TaskBoard from './TaskBoard';
import TaskDrawer from './TaskDrawer';
import TaskList from './TaskList';
import TaskTimeline from './TaskTimeline';

const VIEWS = [
  { id: 'list', label: 'List' },
  { id: 'board', label: 'Board' },
  { id: 'timeline', label: 'Timeline' },
  { id: 'overview', label: 'Overview' },
  { id: 'meetings', label: 'Meetings' },
  { id: 'chat', label: 'Chat' },
  { id: 'people', label: 'People' },
] as const;

export default function ProjectPage() {
  const { id = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const view = params.get('view') ?? 'list';
  const taskId = params.get('task');
  const project = useProject(id);
  const tasks = useTasks(id);
  const qc = useQueryClient();
  const [rebalancing, setRebalancing] = useState(false);

  const setParam = (key: string, value: string | null) =>
    setParams((p) => {
      if (value) p.set(key, value);
      else p.delete(key);
      return p;
    });

  const rename = useMutation({
    mutationFn: (name: string) => api.patch(`/api/projects/${id}`, { name }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.project(id) });
      qc.invalidateQueries({ queryKey: keys.projects });
    },
    onError: (error) => toast(errorMessage(error, "Couldn't rename the project.")),
  });

  const start = useMutation({
    mutationFn: () => api.patch(`/api/projects/${id}`, { status: 'active' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.project(id) });
      qc.invalidateQueries({ queryKey: keys.projects });
      toast('Project started');
    },
    onError: (error) => toast(errorMessage(error, "Couldn't start the project.")),
  });

  if (project.isError) {
    return (
      <AppShell title="Project not found">
        <section className="clv-card">
          <p className="text-[13px] text-ink-muted">{errorMessage(project.error, "This project doesn't exist, or you're not in it.")}</p>
          <Link to="/" className="clv-btn clv-btn-secondary self-start bg-ground">Back to projects</Link>
        </section>
      </AppShell>
    );
  }
  if (tasks.isError) {
    return (
      <AppShell title={project.data?.name || 'Project'}>
        <section className="clv-card">
          <p className="text-[13px] text-danger-text">{errorMessage(tasks.error, "Couldn't load the project tasks.")}</p>
          <button type="button" className="clv-btn clv-btn-secondary self-start bg-ground" onClick={() => tasks.refetch()}>
            Try again
          </button>
        </section>
      </AppShell>
    );
  }
  if (!project.data || !tasks.data) {
    return (
      <AppShell title="Loading project…">
        <section className="clv-card">
          <p className="text-[13px] text-ink-muted">Loading workspace and tasks…</p>
        </section>
      </AppShell>
    );
  }

  const p = project.data;
  const all = tasks.data;
  const canManage = isManager(p.role);
  const open = all.filter((t) => t.status !== 'done');
  const atRisk = open.filter((t) => t.at_risk).length;
  const finishes = open.map((t) => t.forecast_finish).filter((d): d is string => Boolean(d)).sort();
  const predicted = finishes.at(-1);
  const late = Boolean(predicted && p.deadline && predicted > p.deadline);
  const openTask = all.find((t) => t.id === taskId);

  const subtitle = [
    p.status === 'planning' ? 'Draft plan' : p.status === 'active' ? 'Active' : p.status === 'done' ? 'Done' : 'Archived',
    p.deadline && `due ${fmtDate(p.deadline)}`,
    predicted && `predicted finish ${fmtDate(predicted)}${late ? ', after the deadline' : ''}`,
    atRisk > 0 && `${atRisk} at risk`,
  ].filter(Boolean).join(' · ');

  return (
    <AppShell
      title={
        canManage ? (
          <EditableText ariaLabel="Project name" className="w-full min-w-0 rounded-md bg-transparent focus:bg-surface" placeholder="Untitled project" value={p.name} onSave={(name) => rename.mutate(name)} />
        ) : (
          p.name || 'Untitled project'
        )
      }
      subtitle={subtitle}
      actions={
        <>
          <div className="clv-tabs" role="tablist" aria-label="Views">
            {VIEWS.map((v) => (
              <button key={v.id} type="button" role="tab" aria-selected={view === v.id} className="clv-tab" onClick={() => setParam('view', v.id === 'list' ? null : v.id)}>
                {v.label}
              </button>
            ))}
          </div>
          {canManage && all.length > 0 && (
            <button type="button" className="clv-btn clv-btn-secondary" onClick={() => setRebalancing(true)}>
              <Shuffle aria-hidden="true" /> Rebalance
            </button>
          )}
          {canManage && p.status === 'planning' && all.length > 0 && (
            <button type="button" className="clv-btn clv-btn-primary" disabled={start.isPending} onClick={() => start.mutate()}>
              <Play aria-hidden="true" /> Start the project
            </button>
          )}
        </>
      }
    >
      {p.status === 'planning' && (
        <section className="clv-card gap-2">
          {all.length === 0 && p.milestones.length === 0 ? (
            <>
              <p className="text-[13px] text-ink-muted">There's no plan yet.</p>
              {canManage && (
                <Link to={`/projects/${id}/plan`} className="clv-btn clv-btn-primary self-start">
                  <Sparkles aria-hidden="true" /> Make the plan with Clovio
                </Link>
              )}
            </>
          ) : (
            <p className="text-[13px] text-ink-muted">
              This plan is a draft. Change anything you like: rename, re-date, reassign, add or delete tasks.
              {canManage ? ' When it looks right, start the project.' : ' A manager starts the project when it looks right.'}
            </p>
          )}
        </section>
      )}

      {(view === 'list' || view === 'board' || view === 'timeline') && (
        <AssistBar
          projectId={id}
          placeholder={p.status === 'planning' ? 'Ask Clovio to change the plan, e.g. add a task to book a photographer' : 'Tell Clovio what changed, e.g. supplies are delivered'}
        />
      )}

      {view === 'board' ? (
        <TaskBoard project={p} tasks={all} onOpen={(t) => setParam('task', t)} />
      ) : view === 'timeline' ? (
        <TaskTimeline project={p} tasks={all} onOpen={(t) => setParam('task', t)} />
      ) : view === 'people' ? (
        <PeoplePanel project={p} canManage={canManage} />
      ) : view === 'overview' ? (
        <OverviewPanel projectId={id} />
      ) : view === 'meetings' ? (
        <MeetingsPanel project={p} />
      ) : view === 'chat' ? (
        <ProjectChat projectId={id} />
      ) : (
        <TaskList project={p} tasks={all} canManage={canManage} onOpen={(t) => setParam('task', t)} />
      )}

      {openTask && <TaskDrawer task={openTask} project={p} tasks={all} canManage={canManage} onClose={() => setParam('task', null)} />}
      {rebalancing && <RebalanceModal project={p} onClose={() => setRebalancing(false)} />}
    </AppShell>
  );
}
