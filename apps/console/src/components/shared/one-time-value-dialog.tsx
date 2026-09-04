import { useRef } from 'react';
import { Alert, AlertDescription, Modal, Button, Label } from '@/components/ui/elements';
import { AlertTriangle } from 'lucide-react';
import { InputGroup, InputGroupInput } from '@/components/ui/input-group';
import { useClipboardCopy } from '@/components/shared/use-clipboard-copy';
import { CopyButton, CopyFeedback } from '@/components/shared/copy-control';

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
  copyErrorMessage,
}: Omit<OneTimeValueDialogProps, 'value'> & { value: string }) {
  const valueInput = useRef<HTMLInputElement>(null);
  const clipboard = useClipboardCopy(value, valueInput);

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
            <CopyButton {...clipboard} label={copyLabel} className="h-7 px-3" />
          </InputGroup>
          <CopyFeedback status={clipboard.status} errorMessage={copyErrorMessage} />
        </div>

        <div className="flex justify-end pt-4">
          <Button onClick={() => onOpenChange(false)}>I have saved it</Button>
        </div>
      </div>
    </Modal>
  );
}
