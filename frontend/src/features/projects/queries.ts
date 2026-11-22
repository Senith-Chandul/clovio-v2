import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '../../api/client';
import type { Project, ProjectSummary, Task, TaskEvent, TaskIn, TaskPatch } from '../../api/types';
import { toast } from '../../ui/toast';

export const keys = {
  projects: ['projects'] as const,
  project: (id: string) => ['project', id] as const,
  tasks: (id: string) => ['tasks', id] as const,
  events: (taskId: string) => ['events', taskId] as const,
};

export const useProjects = () =>
  useQuery({ queryKey: keys.projects, queryFn: () => api.get<ProjectSummary[]>('/api/projects').then((r) => r.data) });

export const useProject = (id: string) =>
  useQuery({
    queryKey: keys.project(id),
    queryFn: () => api.get<Project>(`/api/projects/${id}`).then((r) => r.data),
    refetchInterval: 30_000,
  });

/** Polled, so other people's changes show up within seconds. */
export const useTasks = (projectId: string) =>
  useQuery({
    queryKey: keys.tasks(projectId),
    queryFn: () => api.get<Task[]>(`/api/projects/${projectId}/tasks`).then((r) => r.data),
    refetchInterval: 10_000,
  });

export const useTaskEvents = (taskId: string) =>
  useQuery({ queryKey: keys.events(taskId), queryFn: () => api.get<TaskEvent[]>(`/api/tasks/${taskId}/events`).then((r) => r.data) });

/** Task changes: shown at once, rolled back if the server refuses, each with an Undo. */
export function useTaskActions(projectId: string) {
  const qc = useQueryClient();
  const key = keys.tasks(projectId);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: keys.projects });
  };
  const optimistic = async (apply: (tasks: Task[]) => Task[]) => {
    await qc.cancelQueries({ queryKey: key });
    const before = qc.getQueryData<Task[]>(key);
    qc.setQueryData<Task[]>(key, (tasks) => (tasks ? apply(tasks) : tasks));
    return { before };
  };
  const rollback = (error: unknown, fallback: string, context?: { before?: Task[] }) => {
    qc.setQueryData(key, context?.before);
    toast(errorMessage(error, fallback));
  };

  const update = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: TaskPatch }) => api.patch<Task>(`/api/tasks/${id}`, patch).then((r) => r.data),
    onMutate: ({ id, patch }) => optimistic((tasks) => tasks.map((t) => (t.id === id ? ({ ...t, ...patch } as Task) : t))),
    onError: (error, _vars, context) => rollback(error, "Couldn't save that change.", context),
    onSettled: (_data, _error, { id }) => {
      refresh();
      qc.invalidateQueries({ queryKey: keys.events(id) });
    },
  });

  const create = useMutation({
    // Fields with server defaults (status, description, skills) may be left out.
    mutationFn: (body: Partial<TaskIn> & Pick<TaskIn, 'title'>) => api.post<Task>(`/api/projects/${projectId}/tasks`, body).then((r) => r.data),
    onError: (error) => toast(errorMessage(error, "Couldn't add the task.")),
    onSettled: refresh,
  });

  const remove = useMutation({
    mutationFn: (ids: string[]) => api.post(`/api/projects/${projectId}/tasks/bulk`, { ids, delete: true }),
    onMutate: (ids) => optimistic((tasks) => tasks.filter((t) => !ids.includes(t.id))),
    onError: (error, _ids, context) => rollback(error, "Couldn't delete that.", context),
    onSettled: refresh,
  });

  const bulk = useMutation({
    mutationFn: ({ ids, patch }: { ids: string[]; patch: TaskPatch }) => api.post(`/api/projects/${projectId}/tasks/bulk`, { ids, changes: patch }),
    onMutate: ({ ids, patch }) => optimistic((tasks) => tasks.map((t) => (ids.includes(t.id) ? ({ ...t, ...patch } as Task) : t))),
    onError: (error, _vars, context) => rollback(error, "Couldn't change those tasks.", context),
    onSettled: refresh,
  });

  /** Change one task; Undo puts back what the changed fields were. */
  const change = (task: Task, patch: TaskPatch, message = 'Saved') => {
    const previous = Object.fromEntries(Object.keys(patch).map((k) => [k, task[k as keyof Task]])) as TaskPatch;
    update.mutate(
      { id: task.id, patch },
      { onSuccess: () => toast(message, { undo: () => update.mutate({ id: task.id, patch: previous }) }) },
    );
  };

  return { change, update, create, remove, bulk };
}
