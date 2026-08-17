import { useEffect, useState } from 'react';
import { Unplug, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/elements';

const RETRY_INTERVAL_SECONDS = 10;

function RetryCountdown({ onRetry }: { onRetry: () => void }) {
  const [secondsLeft, setSecondsLeft] = useState(RETRY_INTERVAL_SECONDS);

  useEffect(() => {
    const timer = setInterval(() => {
      setSecondsLeft((current) => (current > 1 ? current - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (secondsLeft === 0) onRetry();
  }, [secondsLeft, onRetry]);

  return (
    <p className="font-mono text-xs text-muted-foreground" role="status">
      Retrying automatically in {secondsLeft}s
    </p>
  );
}

export function ControlPlaneDown({ onRetry, isRetrying }: { onRetry: () => void; isRetrying: boolean }) {
  return (
    <div role="alert" className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="w-full max-w-md space-y-6 text-center">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full border border-border bg-muted">
          <Unplug className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
        </div>
        <div className="space-y-2">
          <h1 className="font-mono text-lg font-semibold uppercase tracking-wide">Control plane unreachable</h1>
          <p className="text-sm text-muted-foreground">
            The console could not reach the control plane. It may be restarting or temporarily offline. We’ll keep trying to reconnect.
          </p>
        </div>
        <div className="space-y-3">
          <Button onClick={onRetry} disabled={isRetrying} className="gap-2">
            <RefreshCw className={isRetrying ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} aria-hidden="true" />
            {isRetrying ? 'Reconnecting...' : 'Retry now'}
          </Button>
          {isRetrying ? (
            <p className="font-mono text-xs text-muted-foreground" role="status">
              Checking the connection...
            </p>
          ) : (
            <RetryCountdown onRetry={onRetry} />
          )}
        </div>
      </div>
    </div>
  );
}
