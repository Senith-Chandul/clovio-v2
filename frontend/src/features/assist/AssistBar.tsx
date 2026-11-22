import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowUp, LoaderCircle, Mic, Sparkles, Square, X } from 'lucide-react';
import { api, errorMessage } from '../../api/client';
import type { Applied, AssistOut } from '../../api/types';
import { toast } from '../../ui/toast';
import { useRecorder } from './useRecorder';

interface Send {
  text?: string;
  audio?: Blob;
  filename?: string;
  taskId?: string;
}

/**
 * Say or type what changed ("supplies are delivered") and Clovio updates the task. Without a project it works
 * across all your projects. Every change can be undone; when it can't tell which task you meant, it asks.
 */
export default function AssistBar({ projectId, placeholder = 'Tell Clovio what changed, e.g. supplies are delivered' }: { projectId?: string; placeholder?: string }) {
  const qc = useQueryClient();
  const [text, setText] = useState('');
  const [result, setResult] = useState<AssistOut | null>(null);
  const refresh = () => ['tasks', 'my-tasks', 'projects', 'project', 'events'].forEach((key) => qc.invalidateQueries({ queryKey: [key] }));

  const send = useMutation({
    mutationFn: ({ text: words, audio, filename, taskId }: Send) => {
      const form = new FormData();
      if (audio) form.append('audio', audio, filename);
      if (words) form.append('text', words);
      if (projectId) form.append('project_id', projectId);
      if (taskId) form.append('task_id', taskId);
      return api.post<AssistOut>('/api/assist', form).then((r) => r.data);
    },
    onSuccess: (data) => {
      setResult(data);
      setText('');
      refresh();
    },
    onError: (error) => toast(errorMessage(error, "Clovio couldn't do that.")),
  });
  const recorder = useRecorder((audio, filename) => send.mutate({ audio, filename }));

  const undo = useMutation({
    mutationFn: (change: Applied) => api.patch(`/api/tasks/${change.task_id}`, change.previous),
    onSuccess: (_res, change) => {
      setResult((r) => r && { ...r, applied: r.applied.filter((a) => a !== change) });
      refresh();
      toast(`Undid the change to ${change.title}`);
    },
    onError: (error) => toast(errorMessage(error, "Couldn't undo that.")),
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim()) send.mutate({ text: text.trim() });
  };
  const toggleMic = async () => {
    if (recorder.recording) return recorder.stop();
    try {
      await recorder.start();
    } catch {
      toast('Clovio needs your microphone. Allow it in the browser, or type instead.');
    }
  };

  return (
    <section className="clv-card gap-3" aria-label="Tell Clovio what changed">
      <form onSubmit={onSubmit} className="flex items-center gap-2">
        <Sparkles aria-hidden="true" className="h-4 w-4 shrink-0 text-secondary-text" />
        <input
          aria-label="What changed"
          className="clv-input min-w-0 flex-1"
          placeholder={recorder.recording ? 'Listening… tap stop when you’re done' : placeholder}
          value={text}
          disabled={recorder.recording}
          onChange={(e) => setText(e.target.value)}
        />
        {recorder.supported && (
          <button
            type="button"
            onClick={toggleMic}
            disabled={send.isPending}
            aria-label={recorder.recording ? 'Stop recording' : 'Speak instead'}
            className={`clv-icon-btn shrink-0 ${recorder.recording ? 'bg-danger-soft text-danger-text' : 'bg-ground'}`}
          >
            {recorder.recording ? <Square aria-hidden="true" /> : <Mic aria-hidden="true" />}
          </button>
        )}
        <button type="submit" aria-label="Send" className="clv-icon-btn shrink-0 bg-primary text-on-primary hover:text-on-primary" disabled={send.isPending || !text.trim()}>
          {send.isPending ? <LoaderCircle aria-hidden="true" className="animate-spin" /> : <ArrowUp aria-hidden="true" />}
        </button>
      </form>

      {result && (
        <div className="flex flex-col gap-2 border-t border-line pt-3 text-[13px]" aria-live="polite">
          <div className="flex items-start gap-2">
            <p className="flex-1">
              <span className="text-ink-muted">You said “{result.transcript}”. </span>
              {result.reply}
            </p>
            <button type="button" aria-label="Dismiss" className="rounded-full p-1 text-ink-subtle hover:text-ink" onClick={() => setResult(null)}>
              <X size={14} aria-hidden="true" />
            </button>
          </div>
          {result.choices.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {result.choices.map((c) => (
                <button key={c.task_id} type="button" className="clv-btn clv-btn-outline" disabled={send.isPending} onClick={() => send.mutate({ text: result.transcript, taskId: c.task_id })}>
                  {c.title}{!projectId && <span className="text-ink-subtle"> · {c.project_name}</span>}
                </button>
              ))}
            </div>
          )}
          {result.applied.filter((a) => Object.keys(a.previous).length > 0).map((a) => (
            <button key={a.task_id} type="button" className="clv-btn clv-btn-outline self-start" disabled={undo.isPending} onClick={() => undo.mutate(a)}>
              Undo the change to {a.title}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
