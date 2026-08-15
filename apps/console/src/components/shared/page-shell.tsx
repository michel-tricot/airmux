import type { HTMLAttributes } from 'react';
import { cn } from '@/lib/utils';

export function PageShell({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('flex-1 w-full max-w-6xl mx-auto space-y-6 px-4 py-6 sm:p-8 animate-in fade-in duration-300', className)} {...props} />;
}
