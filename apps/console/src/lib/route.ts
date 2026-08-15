import { useParams } from 'wouter';

export function useRequiredParam(name: string): string {
  const params = useParams<Record<string, string | undefined>>();
  const value = params[name];
  if (!value) throw new Error(`Missing route parameter: ${name}`);
  return value;
}
