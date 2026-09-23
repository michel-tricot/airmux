import type { ReactNode } from 'react';
import { Link } from 'wouter';
import { cn } from '@/lib/utils';

export function TableLink({ className, ...props }: { href: string; className?: string; title?: string; children: ReactNode }) {
  return <Link className={cn('text-primary hover:underline', className)} {...props} />;
}
