import { useEffect, useRef, useState } from 'react';
import { Alert, AlertDescription, Modal, Button, Label } from '@/components/ui/elements';
import { Copy, CheckCircle2, AlertTriangle } from 'lucide-react';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';

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
  const copied = copiedValue === value;
  const copyError = copyErrorValue === value;

  useEffect(() => () => clearTimeout(copyTimer.current), []);

  if (!value) return null;

  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopiedValue(value);
      setCopyErrorValue(null);
      clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopiedValue(null), 2000);
    } catch {
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
          <InputGroup className="bg-muted">
            <InputGroupInput id="one-time-value" readOnly value={value} className="font-mono text-muted-foreground" />
            <InputGroupAddon align="inline-end" className="pr-1">
              <Button onClick={copyToClipboard} variant="secondary" className="h-7 w-28" aria-label={copied ? 'Copied' : copyLabel}>
                {copied ? (
                  <>
                    <CheckCircle2 className="mr-2 h-4 w-4 text-success" /> Copied
                  </>
                ) : (
                  <>
                    <Copy className="mr-2 h-4 w-4" /> Copy
                  </>
                )}
              </Button>
            </InputGroupAddon>
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
