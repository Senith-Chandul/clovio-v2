import { useSyncExternalStore } from 'react';

export interface Toast {
  id: number;
  text: string;
  undo?: () => void;
}

let toasts: Toast[] = [];
let nextId = 1;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());

export function dismiss(id: number) {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

/** A short message at the bottom of the screen, with an optional Undo. At most three at once. */
export function toast(text: string, options: { undo?: () => void } = {}) {
  const id = nextId++;
  toasts = [...toasts.slice(-2), { id, text, ...options }];
  emit();
  window.setTimeout(() => dismiss(id), 6000);
}

export function useToasts(): Toast[] {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => toasts,
  );
}
