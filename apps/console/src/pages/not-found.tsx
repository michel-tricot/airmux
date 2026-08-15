import { Card } from '@/components/ui/elements';
import { AlertCircle } from 'lucide-react';
import { Link } from 'wouter';

export default function NotFound() {
  return (
    <div className="flex min-h-full w-full items-center justify-center p-4">
      <Card className="w-full max-w-md p-6">
        <div className="mb-4 flex items-center gap-3">
          <AlertCircle className="h-8 w-8 text-destructive" />
          <h1 className="text-2xl font-bold text-foreground">Page not found</h1>
        </div>
        <p className="mb-6 text-sm text-muted-foreground">The address may be outdated or you may not have access to this page.</p>
        <Link
          href="/"
          className="inline-flex h-9 items-center justify-center rounded bg-primary px-4 py-2 font-mono text-[12px] font-bold uppercase tracking-wider text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          Return home
        </Link>
      </Card>
    </div>
  );
}
