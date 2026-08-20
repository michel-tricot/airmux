import { useRef } from 'react';
import { Alert, AlertDescription, Modal, Button, Label } from '@/components/ui/elements';
import { Copy, CheckCircle2, AlertTriangle, Loader2 } from 'lucide-react';
import { InputGroup, InputGroupInput } from '@/components/ui/input-group';
import { useClipboardCopy } from '@/components/shared/use-clipboard-copy';

type OneTimeValueDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  value: string | null;
  title: string;
  warning: string;
  label: string;
  copyLabel: string;
  copyErrorMessage?: string;
};

export function OneTimeValueDialog(props: OneTimeValueDialogProps) {
  if (!props.value) return null;
  return <OneTimeValueDialogContent {...props} value={props.value} />;
}

function OneTimeValueDialogContent({
  open,
  onOpenChange,
  value,
  title,
  warning,
  label,
  copyLabel,
  copyErrorMessage = 'Automatic copy was blocked. Press Command+C or Ctrl+C to copy the selected value.',
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  value: string;
  title: string;
  warning: string;
  label: string;
  copyLabel: string;
  copyErrorMessage?: string;
}) {
  const valueInput = useRef<HTMLInputElement>(null);
  const { copy, status } = useClipboardCopy(value, valueInput);
  const copied = status === 'copied';
  const copying = status === 'copying';
  const copyError = status === 'manual';

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
            <InputGroupInput
              ref={valueInput}
              id="one-time-value"
              readOnly
              tabIndex={-1}
              value={value}
              className="h-7 min-w-0 px-2 font-mono text-muted-foreground"
            />
            <Button
              onClick={() => void copy()}
              variant="secondary"
              className="h-7 shrink-0 gap-2 px-3"
              disabled={copying}
              aria-label={copying ? 'Copying' : copied ? 'Copied' : copyLabel}
            >
              {copying ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Copying
                </>
              ) : copied ? (
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
