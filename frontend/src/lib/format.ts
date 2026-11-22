import type { Role, TaskStatus } from '../api/types';

export const STATUS_LABEL: Record<TaskStatus, string> = {
  todo: 'To do',
  in_progress: 'In progress',
  blocked: 'Blocked',
  done: 'Done',
};
export const STATUSES = Object.keys(STATUS_LABEL) as TaskStatus[];

export const ROLE_LABEL: Record<Role, string> = { owner: 'Owner', manager: 'Manager', member: 'Member' };

/** "Thu 3 Dec" from an ISO date. Read as local midnight, so it never shows the day before. */
export const fmtDate = (iso?: string | null): string =>
  iso ? new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' }) : '';

export const splitSkills = (text: string): string[] =>
  text.split(',').map((s) => s.trim()).filter(Boolean);

export const isManager = (role?: Role) => role === 'owner' || role === 'manager';
