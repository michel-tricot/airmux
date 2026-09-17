import type { InfiniteData } from '@tanstack/react-query';
import { getNextPageParam, type Page } from '@workspace/api-client-react';

export const paginatedQueryOptions = {
  initialPageParam: undefined,
  getNextPageParam,
};

export function flattenPages<T>(data: InfiniteData<Page<T>>): T[] {
  return data.pages.flatMap((page) => page.items);
}
