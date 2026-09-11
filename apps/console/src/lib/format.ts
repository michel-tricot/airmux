import { format } from 'date-fns';

export function formatDate(dateStr: string | undefined | null) {
  if (!dateStr) return 'N/A';
  return format(new Date(dateStr), 'MMM d, yyyy HH:mm');
}
