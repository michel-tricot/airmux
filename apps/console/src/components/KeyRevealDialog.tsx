import { OneTimeValueDialog } from '@/components/shared/one-time-value-dialog';

export function KeyRevealDialog({ open, onOpenChange, token }: { open: boolean; onOpenChange: (open: boolean) => void; token: string | null }) {
  return (
    <OneTimeValueDialog
      open={open}
      onOpenChange={onOpenChange}
      value={token}
      title="Key Generated Successfully"
      warning="Please copy this key and store it somewhere safe. You will not be able to see it again."
      label="Key Secret"
      copyLabel="Copy key"
      copyErrorMessage="Could not copy the key. Select it and copy it manually."
    />
  );
}
