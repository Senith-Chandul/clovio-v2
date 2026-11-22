import type { ReactNode } from 'react';
import { Link } from 'react-router';
import ClovioMark from './ClovioMark';
import CoverArt from './CoverArt';

/** Sign-in pages: the form on a white panel, the cover art beside it. */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-ground p-4">
      <div className="grid w-full max-w-5xl overflow-hidden rounded-2xl bg-surface md:grid-cols-2">
        <div className="flex flex-col justify-center p-8 sm:p-12">
          <Link to="/" className="mb-10 flex items-center gap-2.5 self-start text-ink">
            <span className="flex h-[34px] w-[34px] items-center justify-center rounded-[11px] bg-primary-soft text-primary">
              <ClovioMark className="h-5 w-5" strokeWidth={10} />
            </span>
            <span className="text-[18px] font-bold tracking-tight">clovio</span>
          </Link>
          {children}
        </div>
        <div className="hidden flex-col justify-between gap-8 bg-surface-sunken p-10 md:flex">
          <CoverArt className="w-full" />
          <div>
            <p className="text-display text-ink">Plans that finish on time.</p>
            <p className="mt-2 text-sm text-ink-muted">
              Turn a brief into a plan, give each task to whoever can finish it soonest, and see what's at risk before it slips.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
