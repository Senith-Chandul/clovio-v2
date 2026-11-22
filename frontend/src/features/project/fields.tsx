import type { Member, TaskStatus } from '../../api/types';
import { STATUS_LABEL, STATUSES } from '../../lib/format';

// `label` names the task, so a screen reader hears "Status of Book the venue", not ten identical "Status" menus.
export function StatusSelect({ value, onChange, label = 'Status', className = '' }: { value: TaskStatus; onChange: (s: TaskStatus) => void; label?: string; className?: string }) {
  return (
    <select aria-label={label} className={`clv-select ${className}`} value={value} onChange={(e) => onChange(e.target.value as TaskStatus)}>
      {STATUSES.map((s) => (
        <option key={s} value={s}>{STATUS_LABEL[s]}</option>
      ))}
    </select>
  );
}

export function MemberSelect({ value, members, onChange, label = 'Assignee', className = '' }: { value: string | null; members: Member[]; onChange: (id: string | null) => void; label?: string; className?: string }) {
  return (
    <select aria-label={label} className={`clv-select max-w-40 ${className}`} value={value ?? ''} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">Unassigned</option>
      {members.map((m) => (
        <option key={m.user_id} value={m.user_id}>{m.name}</option>
      ))}
    </select>
  );
}
