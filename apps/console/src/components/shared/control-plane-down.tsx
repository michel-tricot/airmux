import { useEffect, useState } from 'react';
import { Unplug, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/elements';

const RETRY_INTERVAL_SECONDS = 10;

export function ControlPlaneDown({ onRetry, isRetrying }: { onRetry: () => void; isRetrying: boolean }) {
  const [secondsLeft, setSecondsLeft] = useState(RETRY_INTERVAL_SECONDS);

  useEffect(() => {
    if (isRetrying) return;
    setSecondsLeft(RETRY_INTERVAL_SECONDS);
    const timer = setInterval(() => {
      setSecondsLeft((current) => (current > 1 ? current - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [isRetrying, onRetry]);

  useEffect(() => {
    if (secondsLeft === 0 && !isRetrying) onRetry();
  }, [secondsLeft, isRetrying, onRetry]);

  return (
    <div role="alert" className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="w-full max-w-md space-y-6 text-center">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full border border-border bg-muted">
          <Unplug className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
        </div>
        <div className="space-y-2">
          <h1 className="font-mono text-lg font-semibold uppercase tracking-wide">Control plane unreachable</h1>
          <p className="text-sm text-muted-foreground">
            The console could not reach the control plane. It may be restarting or temporarily offline. Your session and data are safe.
          </p>
        </div>
        <div className="space-y-3">
          <Button onClick={onRetry} disabled={isRetrying} className="gap-2">
            <RefreshCw className={isRetrying ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} aria-hidden="true" />
            {isRetrying ? 'Reconnecting...' : 'Retry now'}
          </Button>
          <p className="font-mono text-xs text-muted-foreground" role="status">
            {isRetrying ? 'Checking the connection...' : `Retrying automatically in ${secondsLeft}s`}
          </p>
        </div>
      </div>
    </div>
  );
}
