import type { ReactNode } from 'react';

// Task statuses use the backend's values as is (todo, in_progress, blocked, done).
type BadgeVariant = 'todo' | 'in_progress' | 'blocked' | 'done' | 'info' | 'good' | 'warning' | 'critical';

// Design-system chips: the word carries the meaning, the tint backs it up.
const CHIP: Record<BadgeVariant, string> = {
  todo: 'clv-chip',
  in_progress: 'clv-chip clv-chip-info',
  blocked: 'clv-chip clv-chip-warn',
  done: 'clv-chip clv-chip-good',
  info: 'clv-chip clv-chip-info',
  good: 'clv-chip clv-chip-good',
  warning: 'clv-chip clv-chip-warn',
  critical: 'clv-chip clv-chip-bad',
};

export default function Badge({ variant, children, className = '' }: { variant: BadgeVariant; children: ReactNode; className?: string }) {
  return <span className={`${CHIP[variant]} ${className}`}>{children}</span>;
}
