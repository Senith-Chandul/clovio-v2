import { X } from 'lucide-react';
import { dismiss, useToasts } from './toast';

export default function Toaster() {
  const toasts = useToasts();
  return (
    <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-4 z-[60] flex flex-col items-center gap-2 px-4">
      {toasts.map((t) => (
        <div key={t.id} className="pointer-events-auto flex items-center gap-3 rounded-full bg-inverse py-2 pl-5 pr-2 text-[13px] text-on-inverse shadow-float animate-slide-up">
          <span>{t.text}</span>
          {t.undo && (
            <button
              type="button"
              className="rounded-full px-3 py-1 font-semibold text-on-inverse underline-offset-2 hover:underline"
              onClick={() => {
                t.undo?.();
                dismiss(t.id);
              }}
            >
              Undo
            </button>
          )}
          <button type="button" aria-label="Dismiss" className="rounded-full p-1.5 opacity-70 hover:opacity-100" onClick={() => dismiss(t.id)}>
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      ))}
    </div>
  );
}
