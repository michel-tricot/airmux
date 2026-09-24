import { Avatar, AvatarFallback, Badge } from '@/components/ui/elements';
import { TableLink } from '@/components/shared/table-link';

export function AccountIdentity({ name, href }: { name: string; href?: string }) {
  const className = 'flex min-w-0 items-center gap-2';
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
    <TableLink href={href} className={className}>
      {identity}
    </TableLink>
  ) : (
    <span className={className}>{identity}</span>
  );
}

export function AccountKindBadge({ serviceAccount }: { serviceAccount: boolean }) {
  return <Badge variant={serviceAccount ? 'secondary' : 'outline'}>{serviceAccount ? 'SERVICE' : 'HUMAN'}</Badge>;
}
