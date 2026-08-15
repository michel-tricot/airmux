import { ApiError } from '@workspace/api-client-react';

export function isApiErrorStatus(error: unknown, status: number): boolean {
  return error instanceof ApiError && error.status === status;
}

export function queryErrorMessage(error: unknown, resource = 'data'): string {
  if (isApiErrorStatus(error, 401)) return 'Your session has expired. Sign in again.';
  if (isApiErrorStatus(error, 403)) return `You do not have access to this ${resource}.`;
  if (isApiErrorStatus(error, 404)) return `${resource[0].toUpperCase()}${resource.slice(1)} was not found.`;
  if (error instanceof ApiError && error.status >= 500) return 'Could not reach the control plane. Try again.';
  return `Could not load ${resource}. Try again.`;
}
