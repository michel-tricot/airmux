import { Alert, AlertDescription, Modal, Button, Input, Label } from '@/components/ui/elements';
import { Copy, CheckCircle2, AlertTriangle } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

export function KeyRevealDialog({ open, onOpenChange, token }: { open: boolean; onOpenChange: (open: boolean) => void; token: string | null }) {
  const [copiedToken, setCopiedToken] = useState<string | null>(null);
  const [copyErrorToken, setCopyErrorToken] = useState<string | null>(null);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const copied = copiedToken === token;
  const copyError = copyErrorToken === token;

  useEffect(() => () => clearTimeout(copyTimer.current), []);

  if (!token) return null;

  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(token);
      setCopiedToken(token);
      setCopyErrorToken(null);
      clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopiedToken(null), 2000);
    } catch {
      setCopiedToken(null);
      setCopyErrorToken(token);
    }
  };

  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Key Generated Successfully">
      <div className="space-y-6 pt-2">
        <Alert role="note" variant="warning">
          <AlertTriangle />
          <AlertDescription>
            Please copy this key and store it somewhere safe. <strong>You will not be able to see it again.</strong>
          </AlertDescription>
        </Alert>

        <div className="space-y-2">
          <Label htmlFor="generated-key">Key Secret</Label>
          <div className="flex gap-2">
            <Input id="generated-key" readOnly value={token} className="font-mono bg-muted text-muted-foreground" />
            <Button onClick={copyToClipboard} variant="secondary" className="w-28" aria-label={copied ? 'Copied' : 'Copy key'}>
              {copied ? (
                <>
                  <CheckCircle2 className="w-4 h-4 mr-2 text-success" /> Copied
                </>
              ) : (
                <>
                  <Copy className="w-4 h-4 mr-2" /> Copy
                </>
              )}
            </Button>
          </div>
          {copyError && (
            <p role="alert" className="text-sm text-destructive">
              Could not copy the key. Select it and copy it manually.
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
