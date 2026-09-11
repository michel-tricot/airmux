import { useState } from 'react';
import { Button, Dropdown, Modal } from '@/components/ui/elements';

export function RoleSelect({
  value,
  options,
  label,
  name,
  pending,
  onSave,
}: {
  value: string;
  options: Array<{ value: string; label: string }>;
  label: string;
  name: string;
  pending: boolean;
  onSave: (role: string) => Promise<unknown>;
}) {
  const [selectedRole, setSelectedRole] = useState<string | null>(null);
  const currentLabel = options.find((option) => option.value === value)?.label ?? value;
  const selectedLabel = options.find((option) => option.value === selectedRole)?.label;

  return (
    <>
      <Dropdown
        aria-label={label}
        value={value}
        options={options}
        className="w-auto h-auto border-transparent bg-transparent px-2 py-1 shadow-none"
        disabled={pending}
        onValueChange={(role) => {
          if (role !== value) setSelectedRole(role);
        }}
      />
      <Modal
        open={selectedRole !== null}
        onOpenChange={(open) => {
          if (!open && !pending) setSelectedRole(null);
        }}
        title="Confirm role change"
        description={`Change ${name} from ${currentLabel} to ${selectedLabel ?? currentLabel}?`}
      >
        <div className="flex justify-end gap-2">
          <Button variant="outline" disabled={pending} onClick={() => setSelectedRole(null)}>
            Cancel
          </Button>
          <Button
            disabled={pending}
            onClick={async () => {
              if (selectedRole === null) return;
              try {
                await onSave(selectedRole);
                setSelectedRole(null);
              } catch {
                return;
              }
            }}
          >
            {pending ? 'Saving...' : 'Confirm role change'}
          </Button>
        </div>
      </Modal>
    </>
  );
}
