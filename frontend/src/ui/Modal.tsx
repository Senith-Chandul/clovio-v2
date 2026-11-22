import { useEffect, useRef, type MouseEvent, type ReactNode } from 'react';
import { X } from 'lucide-react';

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
}

const SIZE_CLASS = { sm: 'max-w-md', md: 'max-w-2xl', lg: 'max-w-4xl', xl: 'max-w-6xl' };

export default function Modal({ isOpen, onClose, title, children, size = 'md' }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    // No scrolling the page behind the modal.
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const onBackdropClick = (e: MouseEvent) => {
    if (panelRef.current && !panelRef.current.contains(e.target as Node)) onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-scrim/50 p-4 backdrop-blur-sm animate-fade-in"
      onClick={onBackdropClick}
      role="dialog"
      aria-modal="true"
      aria-labelledby={title ? 'modal-title' : undefined}
    >
      <div ref={panelRef} className={`relative max-h-[90vh] w-full overflow-y-auto rounded-2xl bg-surface text-ink shadow-float animate-slide-up ${SIZE_CLASS[size]}`}>
        {title && (
          <div className="flex items-center justify-between gap-3 border-b border-line px-6 py-4">
            <h2 id="modal-title" className="text-title text-ink">{title}</h2>
            <button type="button" onClick={onClose} className="clv-icon-btn bg-ground" aria-label="Close">
              <X aria-hidden="true" />
            </button>
          </div>
        )}
        <div className="px-6 py-6">{children}</div>
      </div>
    </div>
  );
}
