import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { Chats } from '../../api/types';

/** Your chats and unread counts. Polled, since there are no websockets; the sidebar badge reads it too. */
export const useChats = () =>
  useQuery({ queryKey: ['chats'], queryFn: () => api.get<Chats>('/api/chats').then((r) => r.data), refetchInterval: 10_000 });
