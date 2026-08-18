import { ApiError } from '@workspace/api-client-react';

export function isApiErrorStatus(error: unknown, status: number): boolean {
  return error instanceof ApiError && error.status === status;
}

export function isControlPlaneUnreachable(error: unknown): boolean {
  if (error instanceof ApiError) return error.status === 502 || error.status === 503 || error.status === 504;
  return error instanceof TypeError;
}

export function queryErrorMessage(error: unknown, resource = 'data'): string {
  if (isApiErrorStatus(error, 401)) return 'Your session has expired. Sign in again.';
  if (isApiErrorStatus(error, 403)) return `You do not have access to this ${resource}.`;
  if (isApiErrorStatus(error, 404)) return `${resource[0].toUpperCase()}${resource.slice(1)} was not found.`;
  if (error instanceof ApiError && error.status >= 500) return 'Could not reach the control plane. Try again.';
  return `Could not load ${resource}. Try again.`;
}

export function queryErrorTitle(error: unknown, message?: string): string {
  if (isApiErrorStatus(error, 401)) return 'Session expired';
  if (isApiErrorStatus(error, 403) || message?.startsWith('You do not have access')) return 'Access restricted';
  if (isApiErrorStatus(error, 404) || message?.toLocaleLowerCase().includes('not found')) return 'Not found';
  if ((error instanceof ApiError && error.status >= 500) || error instanceof TypeError) return 'Control plane unavailable';
  return 'Unable to load';
}
