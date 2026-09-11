import { Check, Copy } from 'lucide-react';
import { Button } from '@/components/ui/elements';
import type { ClipboardCopyStatus } from '@/components/shared/use-clipboard-copy';
import { cn } from '@/lib/utils';

export function CopyButton({
  copy,
  status,
  label = 'Copy',
  subject,
  className,
}: {
  copy: () => Promise<void>;
  status: ClipboardCopyStatus;
  label?: string;
  subject?: string;
  className?: string;
}) {
  const action = status === 'copying' ? 'Copying' : status === 'copied' ? 'Copied' : label;

  return (
    <Button
      variant="secondary"
      size="sm"
      className={cn('min-w-20 shrink-0', className)}
      onClick={() => void copy()}
      disabled={status === 'copying'}
      aria-label={subject ? `${action} ${subject}` : action}
    >
      {status === 'copied' ? <Check aria-hidden="true" className="h-4 w-4 text-success" /> : <Copy aria-hidden="true" className="h-4 w-4" />}
      {action}
    </Button>
  );
}

export function CopyFeedback({
  status,
  errorMessage = 'Automatic copy was blocked. Press Command+C or Ctrl+C to copy the selected value.',
}: {
  status: ClipboardCopyStatus;
  errorMessage?: string;
}) {
  return (
    <>
      <span role="status" className="sr-only">
        {status === 'copied' ? 'Copied to clipboard' : ''}
      </span>
      {status === 'manual' && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage}
        </p>
      )}
    </>
  );
}
