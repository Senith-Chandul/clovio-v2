import { Link } from 'react-router';
import { FolderKanban, Plus } from 'lucide-react';
import { errorMessage } from '../../api/client';
import type { ProjectSummary } from '../../api/types';
import AppShell from '../../layout/AppShell';
import { ROLE_LABEL, fmtDate } from '../../lib/format';
import Ring from '../../ui/Ring';
import { useProjects } from './queries';

const STATUS_CHIP: Record<ProjectSummary['status'], [string, string]> = {
  planning: ['Draft plan', 'clv-chip clv-chip-warn'],
  active: ['Active', 'clv-chip clv-chip-good'],
  done: ['Done', 'clv-chip'],
  archived: ['Archived', 'clv-chip clv-chip-quiet'],
};

const newProject = (
  <Link to="/projects/new" className="clv-btn clv-btn-primary">
    <Plus aria-hidden="true" /> New project
  </Link>
);

export default function ProjectsPage() {
  const projects = useProjects();

  return (
    <AppShell title="Projects" subtitle="Everything you're working on" actions={newProject}>
      {projects.isError && <p className="text-sm text-danger-text">{errorMessage(projects.error, "Couldn't load your projects.")}</p>}
      {projects.data?.length === 0 && (
        <section className="clv-card items-center py-16 text-center">
          <span className="clv-stat-icon">
            <FolderKanban aria-hidden="true" />
          </span>
          <h2 className="clv-card-title">No projects yet</h2>
          <p className="max-w-sm text-[13px] text-ink-muted">Start one from a brief, or wait for someone to add you to theirs.</p>
          {newProject}
        </section>
      )}
      {!!projects.data?.length && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {projects.data.map((p) => {
            const [label, chip] = STATUS_CHIP[p.status];
            const percent = p.tasks_total ? (p.tasks_done / p.tasks_total) * 100 : 0;
            return (
              <Link key={p.id} to={`/projects/${p.id}`} className="clv-card transition-shadow hover:shadow-float">
                <div className="clv-card-head">
                  <div className="min-w-0">
                    <h2 className="clv-card-title truncate">{p.name || 'Untitled project'}</h2>
                    <p className="clv-card-sub">{p.deadline ? `Due ${fmtDate(p.deadline)}` : 'No deadline'} · {ROLE_LABEL[p.role]}</p>
                  </div>
                  <Ring percent={percent} label={`${Math.round(percent)}% of tasks done`} />
                </div>
                <div className="flex flex-wrap gap-2">
                  <span className={chip}>{label}</span>
                  <span className="clv-chip">{p.tasks_done} of {p.tasks_total} tasks done</span>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </AppShell>
  );
}
