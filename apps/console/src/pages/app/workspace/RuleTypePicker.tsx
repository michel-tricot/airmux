import { Badge, Button, Modal } from '@/components/ui/elements';
import { ruleTypes, type RuleKind } from '@/features/rules/types';

export function RuleTypeChoices({ onSelect, fallbackDisabled = false }: { onSelect: (kind: RuleKind) => void; fallbackDisabled?: boolean }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {ruleTypes.map((type) => (
        <Button
          key={type.kind}
          type="button"
          variant="outline"
          aria-label={type.label}
          disabled={fallbackDisabled && type.kind === 'fallback'}
          className="h-auto min-h-16 items-start justify-start whitespace-normal px-3 py-3 text-left normal-case tracking-normal"
          onClick={() => onSelect(type.kind)}
        >
          <span>
            <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
              {type.label}
              {type.kind === 'budget' && <Badge variant="outline">Coming soon</Badge>}
            </span>
            <span className="mt-1 block text-xs font-normal text-muted-foreground">{type.description}</span>
          </span>
        </Button>
      ))}
    </div>
  );
}

export function RuleTypePicker({
  open,
  onOpenChange,
  onSelect,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (kind: RuleKind) => void;
}) {
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="Choose a rule type"
      description="Start with the control you want to apply. Each rule type has its own focused form."
    >
      <div className="pt-4">
        <RuleTypeChoices onSelect={onSelect} />
      </div>
    </Modal>
  );
}
