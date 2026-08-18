import { useEffect, useRef, useState } from 'react';
import { Alert, AlertDescription, Modal, Button, Label } from '@/components/ui/elements';
import { Copy, CheckCircle2, AlertTriangle } from 'lucide-react';
import { InputGroup, InputGroupInput } from '@/components/ui/input-group';

export function OneTimeValueDialog({
  open,
  onOpenChange,
  value,
  title,
  warning,
  label,
  copyLabel,
  copyErrorMessage = 'Could not copy the value. Select it and copy it manually.',
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  value: string | null;
  title: string;
  warning: string;
  label: string;
  copyLabel: string;
  copyErrorMessage?: string;
}) {
  const [copiedValue, setCopiedValue] = useState<string | null>(null);
  const [copyErrorValue, setCopyErrorValue] = useState<string | null>(null);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const copyAttempt = useRef(0);
  const copied = copiedValue === value;
  const copyError = copyErrorValue === value;

  useEffect(
    () => () => {
      copyAttempt.current += 1;
      clearTimeout(copyTimer.current);
    },
    [],
  );

  if (!value) return null;

  const copyToClipboard = async () => {
    const attempt = ++copyAttempt.current;
    setCopiedValue(value);
    setCopyErrorValue(null);
    clearTimeout(copyTimer.current);
    try {
      await navigator.clipboard.writeText(value);
      if (copyAttempt.current !== attempt) return;
      copyTimer.current = setTimeout(() => setCopiedValue(null), 2000);
    } catch {
      if (copyAttempt.current !== attempt) return;
      setCopiedValue(null);
      setCopyErrorValue(value);
    }
  };

  return (
    <Modal open={open} onOpenChange={onOpenChange} title={title}>
      <div className="space-y-6 pt-2">
        <Alert role="note" variant="warning">
          <AlertTriangle />
          <AlertDescription>{warning}</AlertDescription>
        </Alert>

        <div className="space-y-2">
          <Label htmlFor="one-time-value">{label}</Label>
          <InputGroup className="min-w-0 gap-1 bg-muted p-1">
            <InputGroupInput id="one-time-value" readOnly tabIndex={-1} value={value} className="h-7 min-w-0 px-2 font-mono text-muted-foreground" />
            <Button onClick={copyToClipboard} variant="secondary" className="h-7 shrink-0 gap-2 px-3" aria-label={copied ? 'Copied' : copyLabel}>
              {copied ? (
                <>
                  <CheckCircle2 className="h-4 w-4 text-success" /> Copied
                </>
              ) : (
                <>
                  <Copy className="h-4 w-4" /> {copyLabel}
                </>
              )}
            </Button>
          </InputGroup>
          {copyError && (
            <p role="alert" className="text-sm text-destructive">
              {copyErrorMessage}
            </p>
          )}
        </div>

        <div className="flex justify-end pt-4">
          <Button onClick={() => onOpenChange(false)}>I have saved it</Button>
        </div>
      </div>
    </Modal>
  );
}
