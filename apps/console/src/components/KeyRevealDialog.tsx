import { Modal, Button, Input } from '@/components/ui/elements';
import { Copy, CheckCircle2, AlertTriangle } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

export function KeyRevealDialog({ open, onOpenChange, token }: { open: boolean, onOpenChange: (open: boolean) => void, token: string | null }) {
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => () => clearTimeout(copyTimer.current), []);

  if (!token) return null;

  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(token);
      setCopied(true);
      clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy', err);
    }
  };

  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Key Generated Successfully">
      <div className="space-y-6 pt-2">
        <div className="p-4 bg-amber-500/10 border border-amber-500/20 rounded-lg flex gap-3 text-amber-400">
          <AlertTriangle className="w-5 h-5 flex-shrink-0 mt-0.5" />
          <p className="text-sm">
            Please copy this key and store it somewhere safe. <strong>You will not be able to see it again.</strong>
          </p>
        </div>

        <div className="space-y-2">
          <div className="text-sm font-medium">Key Secret</div>
          <div className="flex gap-2">
            <Input readOnly value={token} className="font-mono bg-muted text-muted-foreground" />
            <Button onClick={copyToClipboard} variant="secondary" className="w-28" aria-label={copied ? 'Copied' : 'Copy key'}>
              {copied
                ? <><CheckCircle2 className="w-4 h-4 mr-2 text-green-600" /> Copied</>
                : <><Copy className="w-4 h-4 mr-2" /> Copy</>}
            </Button>
          </div>
        </div>

        <div className="flex justify-end pt-4">
          <Button onClick={() => onOpenChange(false)}>I have saved it</Button>
        </div>
      </div>
    </Modal>
  );
}
