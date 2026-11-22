import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '../../api/client';
import type { Project, ScheduleOut } from '../../api/types';
import { fmtDate } from '../../lib/format';
import Modal from '../../ui/Modal';
import { toast } from '../../ui/toast';
import { keys } from '../projects/queries';

/** Preview what a rebalance would move, then apply it. */
export default function RebalanceModal({ project, onClose }: { project: Project; onClose: () => void }) {
  const qc = useQueryClient();
  const names = new Map(project.members.map((m) => [m.user_id, m.name]));
  const preview = useQuery({
    queryKey: ['schedule-preview', project.id],
    queryFn: () => api.post<ScheduleOut>(`/api/projects/${project.id}/schedule`, { apply: false }).then((r) => r.data),
    gcTime: 0,
  });
  const apply = useMutation({
    mutationFn: () => api.post<ScheduleOut>(`/api/projects/${project.id}/schedule`, { apply: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.tasks(project.id) });
      toast('Work rebalanced');
      onClose();
    },
    onError: (error) => toast(errorMessage(error, "Couldn't rebalance.")),
  });
  const result = preview.data;

  return (
    <Modal isOpen title="Rebalance the work" onClose={onClose} size="lg">
      <div className="flex flex-col gap-4">
        <p className="text-[13px] text-ink-muted">
          Tasks nobody has started, and nobody assigned by hand, go to whoever can finish them soonest with the right skills.
        </p>
        {preview.isPending && <p className="text-[13px]">Working it out…</p>}
        {preview.isError && <p className="text-sm text-danger-text">{errorMessage(preview.error, "Couldn't work it out.")}</p>}
        {result && (
          <>
            <p className="text-[13px] font-semibold">
              {result.predicted_finish ? `Predicted finish after the change: ${fmtDate(result.predicted_finish)}.` : 'No assigned work yet.'}
              {result.at_risk > 0 && ` ${result.at_risk} at risk.`}
            </p>
            {result.moves.length === 0 ? (
              <p className="text-[13px] text-ink-muted">Everything is already with whoever finishes it soonest.</p>
            ) : (
              <div className="max-h-[50vh] overflow-y-auto">
                {result.moves.map((m) => (
                  <div key={m.task_id} className="clv-row flex-wrap">
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] font-semibold">{m.title}</div>
                      <div className="text-[12px] text-ink-muted">{m.note}</div>
                    </div>
                    <span className="text-[12px]">
                      {(m.from_assignee_id && names.get(m.from_assignee_id)) || 'Unassigned'} → <b>{(m.to_assignee_id && names.get(m.to_assignee_id)) || 'Unassigned'}</b>
                    </span>
                  </div>
                ))}
              </div>
            )}
            <div className="flex gap-2">
              <button type="button" className="clv-btn clv-btn-primary" disabled={apply.isPending || result.moves.length === 0} onClick={() => apply.mutate()}>
                {apply.isPending ? 'Applying' : `Move ${result.moves.length} ${result.moves.length === 1 ? 'task' : 'tasks'}`}
              </button>
              <button type="button" className="clv-btn clv-btn-secondary bg-ground" onClick={onClose}>Cancel</button>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}
