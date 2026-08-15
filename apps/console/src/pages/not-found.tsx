import { Button, Card } from '@/components/ui/elements';
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
        <Button asChild>
          <Link href="/">Return home</Link>
        </Button>
      </Card>
    </div>
  );
}
