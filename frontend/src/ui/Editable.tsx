import { useRef, useState, type KeyboardEvent } from 'react';

interface EditableProps {
  value: string;
  onSave: (value: string) => void;
  ariaLabel: string;
  className?: string;
  placeholder?: string;
  /** Allow saving an empty value (otherwise empty input puts the old value back). */
  allowEmpty?: boolean;
  multiline?: boolean;
  /** 'date' saves on blur too: Chrome reports a half-typed date as empty, which must not clear it. */
  type?: 'text' | 'date';
}

/**
 * Text that saves on Enter or when focus leaves, and Escape cancels. While focused it shows what you typed,
 * so a background refetch can't overwrite it mid-edit.
 */
export function EditableText({ value, onSave, ariaLabel, className = '', placeholder, allowEmpty = false, multiline = false, type = 'text' }: EditableProps) {
  const [draft, setDraft] = useState<string | null>(null);
  const cancelled = useRef(false);

  const commit = () => {
    const next = draft?.trim();
    if (!cancelled.current && draft !== null && next !== value.trim() && (allowEmpty || next)) onSave(next ?? '');
    cancelled.current = false;
    setDraft(null);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (!multiline || e.metaKey || e.ctrlKey)) e.currentTarget.blur();
    if (e.key === 'Escape') {
      cancelled.current = true;
      e.currentTarget.blur();
    }
  };
  const shared = {
    'aria-label': ariaLabel,
    className,
    placeholder,
    value: draft ?? value,
    onFocus: () => setDraft(value),
    onChange: (e: { target: { value: string } }) => setDraft(e.target.value),
    onBlur: commit,
    onKeyDown,
  };
  return multiline ? <textarea rows={3} {...shared} /> : <input type={type} {...shared} />;
}

/** A due date: saved when you leave the field or press Enter; emptying it clears the date. */
export function DateField({ value, onSave, ariaLabel, className = '' }: { value: string | null; onSave: (v: string | null) => void; ariaLabel: string; className?: string }) {
  return <EditableText type="date" allowEmpty ariaLabel={ariaLabel} className={className} value={value ?? ''} onSave={(v) => onSave(v || null)} />;
}

/** A number of hours, saved like EditableText. Empty clears it. */
export function HoursField({ value, onSave, ariaLabel, className = '' }: { value: number | null; onSave: (v: number | null) => void; ariaLabel: string; className?: string }) {
  return (
    <EditableText
      ariaLabel={ariaLabel}
      className={className}
      placeholder="h"
      allowEmpty
      value={value == null ? '' : String(value)}
      onSave={(text) => {
        const hours = Number(text);
        if (text === '') onSave(null);
        else if (Number.isFinite(hours) && hours > 0) onSave(hours);
      }}
    />
  );
}
