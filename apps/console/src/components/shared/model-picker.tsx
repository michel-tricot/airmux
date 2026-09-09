import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { ChevronDown, Search } from 'lucide-react';
import { Button, Input } from '@/components/ui/elements';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { cn } from '@/lib/utils';

interface ModelPickerOption {
  value: string;
  label: ReactNode;
  searchText: string;
}

export function ModelPicker({
  value,
  onValueChange,
  onSelectionComplete,
  options,
  placeholder = 'Select model',
  disabled,
  className,
  id,
  'aria-label': ariaLabel,
}: {
  value: string;
  onValueChange: (value: string) => void;
  onSelectionComplete?: () => void;
  options: ModelPickerOption[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  id?: string;
  'aria-label'?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const selectionCompleted = useRef(false);
  const listboxId = useId();
  const selected = options.find((option) => option.value === value);
  const visibleOptions = options.filter((option) => option.searchText.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const highlightedIndex = Math.min(activeIndex, Math.max(visibleOptions.length - 1, 0));
  const highlightedOption = visibleOptions[highlightedIndex];

  useEffect(() => {
    if (open) document.getElementById(`${listboxId}-${highlightedIndex}`)?.scrollIntoView?.({ block: 'nearest' });
  }, [highlightedIndex, listboxId, open]);

  const onOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      setQuery('');
      setActiveIndex(0);
      return;
    }
    setActiveIndex(
      Math.max(
        0,
        options.findIndex((option) => option.value === value),
      ),
    );
  };

  const selectOption = (option: ModelPickerOption) => {
    selectionCompleted.current = true;
    onValueChange(option.value);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button
          id={id}
          variant="outline"
          className={cn('h-9 w-full justify-between px-3 text-left text-[13px] normal-case', className)}
          aria-label={ariaLabel}
          disabled={disabled}
        >
          <span className="min-w-0 truncate">{selected?.label ?? placeholder}</span>
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        </Button>
      </DialogTrigger>
      <DialogContent
        className="w-[calc(100%-2rem)] max-w-lg gap-4 border-border bg-card p-4 text-card-foreground"
        onCloseAutoFocus={(event) => {
          const selectedOption = selectionCompleted.current;
          selectionCompleted.current = false;
          if (!selectedOption || !onSelectionComplete) return;
          event.preventDefault();
          onSelectionComplete();
        }}
      >
        <DialogHeader className="space-y-1">
          <DialogTitle className="text-base">Select model</DialogTitle>
          <DialogDescription>Search by model or provider name</DialogDescription>
        </DialogHeader>
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            role="combobox"
            aria-controls={listboxId}
            aria-expanded
            aria-activedescendant={highlightedOption ? `${listboxId}-${highlightedIndex}` : undefined}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActiveIndex(0);
            }}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault();
                setActiveIndex((index) => Math.min(index + 1, Math.max(visibleOptions.length - 1, 0)));
              } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                setActiveIndex((index) => Math.max(index - 1, 0));
              } else if (event.key === 'Home') {
                event.preventDefault();
                setActiveIndex(0);
              } else if (event.key === 'End') {
                event.preventDefault();
                setActiveIndex(Math.max(visibleOptions.length - 1, 0));
              } else if (event.key === 'Enter' && highlightedOption) {
                event.preventDefault();
                selectOption(highlightedOption);
              } else if (event.key === 'Escape') {
                event.preventDefault();
                onOpenChange(false);
              }
            }}
            placeholder="Search models..."
            className="pl-9"
          />
        </div>
        <div id={listboxId} role="listbox" className="max-h-72 space-y-1 overflow-y-auto pr-1">
          {visibleOptions.map((option, index) => (
            <Button
              key={option.value}
              id={`${listboxId}-${index}`}
              variant="ghost"
              role="option"
              aria-selected={option.value === value}
              tabIndex={-1}
              className={cn(
                'h-auto w-full justify-start px-3 py-2 text-left normal-case',
                index === highlightedIndex && 'bg-primary/10 text-primary',
              )}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => selectOption(option)}
            >
              {option.label}
            </Button>
          ))}
          {visibleOptions.length === 0 && <p className="px-3 py-6 text-center text-sm text-muted-foreground">No matching models</p>}
        </div>
      </DialogContent>
    </Dialog>
  );
}
