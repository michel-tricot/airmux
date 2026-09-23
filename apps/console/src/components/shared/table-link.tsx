import type { ReactNode } from 'react';
import { Link } from 'wouter';
import { cn } from '@/lib/utils';

export function TableLink({ className, ...props }: { href: string; className?: string; title?: string; children: ReactNode }) {
  return (
    <Link
      className={cn(
        'text-primary transition-colors hover:text-primary/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        className,
      )}
      {...props}
    />
  );
}
