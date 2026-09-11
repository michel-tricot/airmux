import { Link } from 'wouter';
import { Avatar, AvatarFallback, Badge } from '@/components/ui/elements';
import { cn } from '@/lib/utils';

export function AccountIdentity({ name, href }: { name: string; href?: string }) {
  const className = cn('flex min-w-0 items-center gap-2', href && 'transition-colors hover:text-primary');
  const identity = (
    <>
      <Avatar aria-hidden="true" className="h-6 w-6 shrink-0">
        <AvatarFallback className="bg-primary/10 text-xs font-bold text-primary">{name.charAt(0)}</AvatarFallback>
      </Avatar>
      <span className="truncate" title={name}>
        {name}
      </span>
    </>
  );
  return href ? (
    <Link href={href} className={className}>
      {identity}
    </Link>
  ) : (
    <span className={className}>{identity}</span>
  );
}

export function AccountKindBadge({ serviceAccount }: { serviceAccount: boolean }) {
  return <Badge variant={serviceAccount ? 'secondary' : 'outline'}>{serviceAccount ? 'SERVICE' : 'HUMAN'}</Badge>;
}
