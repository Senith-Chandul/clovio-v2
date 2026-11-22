import { useQuery } from '@tanstack/react-query';
import { api, getToken } from '../../api/client';
import type { User } from '../../api/types';

/** The signed-in user. Disabled without a stored session. */
export const useMe = () =>
  useQuery({
    queryKey: ['me'],
    queryFn: () => api.get<User>('/api/me').then((r) => r.data),
    enabled: Boolean(getToken()),
  });
