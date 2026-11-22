import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { UserMinus } from 'lucide-react';
import { api, errorMessage } from '../../api/client';
import type { Member, MemberIn, MemberPatch, Project, Role } from '../../api/types';
import { ROLE_LABEL, splitSkills } from '../../lib/format';
import Avatar from '../../ui/Avatar';
import { EditableText } from '../../ui/Editable';
import { toast } from '../../ui/toast';
import { useMe } from '../auth/useMe';
import { keys } from '../projects/queries';

const ROLES: Role[] = ['member', 'manager', 'owner'];

/** Who's in the project, their skills and hours (what the scheduler works from), and invites. */
export default function PeoplePanel({ project, canManage }: { project: Project; canManage: boolean }) {
  const qc = useQueryClient();
  const { data: me } = useMe();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: keys.project(project.id) });
    qc.invalidateQueries({ queryKey: ['me'] });
    qc.invalidateQueries({ queryKey: keys.tasks(project.id) });
  };
  const fail = (fallback: string) => (error: unknown) => toast(errorMessage(error, fallback));

  const edit = useMutation({
    // Your own profile goes through /me; an invitee's (until they sign in) through the project.
    mutationFn: ({ member, patch }: { member: Member; patch: MemberPatch }) =>
      member.user_id === me?.id && !patch.role
        ? api.patch('/api/me', patch)
        : api.patch(`/api/projects/${project.id}/members/${member.user_id}`, patch),
    onSuccess: () => toast('Saved'),
    onError: fail("Couldn't save that."),
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: (member: Member) => api.delete(`/api/projects/${project.id}/members/${member.user_id}`),
    onSuccess: () => toast('Removed. Their open tasks are unassigned.'),
    onError: fail("Couldn't remove them."),
    onSettled: refresh,
  });

  const [invite, setInvite] = useState({ email: '', name: '', skills: '', hours: '', role: 'member' as Role });
  const add = useMutation({
    mutationFn: (body: MemberIn) => api.post(`/api/projects/${project.id}/members`, body),
    onSuccess: () => {
      setInvite({ email: '', name: '', skills: '', hours: '', role: 'member' });
      toast('Added');
    },
    onError: fail("Couldn't add them."),
    onSettled: refresh,
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate({
      email: invite.email.trim(),
      name: invite.name.trim() || null,
      role: invite.role,
      skills: splitSkills(invite.skills),
      weekly_hours: invite.hours ? Number(invite.hours) : null,
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <section className="clv-card gap-0">
        <div className="pb-2">
          <h2 className="clv-card-title">People</h2>
          <p className="clv-card-sub">Skills and weekly hours decide who gets which task. People keep their own once they sign in.</p>
        </div>
        {project.members.map((m) => {
          const editable = m.user_id === me?.id || (canManage && m.invited);
          return (
            <div key={m.user_id} className="clv-row flex-wrap">
              <Avatar name={m.name} />
              <div className="min-w-40 flex-1">
                <div className="flex items-center gap-2 text-[14px] font-semibold">
                  {m.name}
                  {m.invited && <span className="clv-chip clv-chip-warn">Not signed in yet</span>}
                </div>
                <div className="text-[12px] text-ink-muted">{m.email}</div>
              </div>
              {editable ? (
                <>
                  <EditableText ariaLabel={`Skills for ${m.name}`} className="clv-select w-48" placeholder="Skills, comma-separated" allowEmpty value={m.skills.join(', ')} onSave={(v) => edit.mutate({ member: m, patch: { skills: splitSkills(v) } })} />
                  <EditableText ariaLabel={`Hours a week for ${m.name}`} className="clv-select w-20 text-center" value={String(m.weekly_hours)} onSave={(v) => Number.isFinite(Number(v)) && edit.mutate({ member: m, patch: { weekly_hours: Number(v) } })} />
                  <span className="text-[12px] text-ink-muted">h / week</span>
                </>
              ) : (
                <span className="text-[12px] text-ink-muted">{m.skills.join(', ') || 'No skills listed'} · {m.weekly_hours} h / week</span>
              )}
              {canManage && m.user_id !== me?.id ? (
                <>
                  <select aria-label={`Role for ${m.name}`} className="clv-select" value={m.role} onChange={(e) => edit.mutate({ member: m, patch: { role: e.target.value as Role } })}>
                    {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                  </select>
                  <button type="button" className="clv-icon-btn h-9 w-9 bg-ground" aria-label={`Remove ${m.name}`} onClick={() => window.confirm(`Remove ${m.name} from the project? Their open tasks become unassigned.`) && remove.mutate(m)}>
                    <UserMinus aria-hidden="true" />
                  </button>
                </>
              ) : (
                <span className="clv-chip">{ROLE_LABEL[m.role]}</span>
              )}
            </div>
          );
        })}
      </section>

      {canManage && (
        <form onSubmit={submit} className="clv-card gap-3">
          <h2 className="clv-card-title">Add someone</h2>
          <div className="grid gap-2 sm:grid-cols-[1.4fr_1fr_1.4fr_6rem_8rem]">
            <input aria-label="Email" type="email" required className="clv-input" placeholder="Email" value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} />
            <input aria-label="Name" className="clv-input" placeholder="Name" value={invite.name} onChange={(e) => setInvite({ ...invite, name: e.target.value })} />
            <input aria-label="Skills" className="clv-input" placeholder="Skills, comma-separated" value={invite.skills} onChange={(e) => setInvite({ ...invite, skills: e.target.value })} />
            <input aria-label="Hours a week" type="number" min={0} max={100} className="clv-input" placeholder="h / wk" value={invite.hours} onChange={(e) => setInvite({ ...invite, hours: e.target.value })} />
            <select aria-label="Role" className="clv-input" value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value as Role })}>
              {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
            </select>
          </div>
          <p className="text-caption text-ink-muted">They sign in with this email to join. You can give them work before they do.</p>
          <button type="submit" className="clv-btn clv-btn-primary self-start" disabled={add.isPending}>Add to the project</button>
        </form>
      )}
    </div>
  );
}
