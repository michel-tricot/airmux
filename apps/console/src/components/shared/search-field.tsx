import { Search } from 'lucide-react';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { cn } from '@/lib/utils';

export function SearchField({
  value,
  onValueChange,
  label,
  placeholder,
  className,
}: {
  value: string;
  onValueChange: (value: string) => void;
  label: string;
  placeholder: string;
  className?: string;
}) {
  return (
    <InputGroup className={cn('max-w-sm flex-1 bg-background/50', className)}>
      <InputGroupAddon>
        <Search />
      </InputGroupAddon>
      <InputGroupInput
        aria-label={label}
        placeholder={placeholder}
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
        className="font-mono"
      />
    </InputGroup>
  );
}
