import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { Check, ChevronDown, Search } from 'lucide-react';
import { Button, Input } from '@/components/ui/elements';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { cn } from '@/lib/utils';

export interface ModelPickerOption {
  value: string;
  label: ReactNode;
  searchText: string;
}

interface ModelPickerBaseProps {
  options: ModelPickerOption[];
  disabled?: boolean;
  className?: string;
  id?: string;
  'aria-label'?: string;
}

interface SingleModelPickerProps extends ModelPickerBaseProps {
  mode?: 'single';
  value: string;
  onValueChange: (value: string) => void;
  onSelectionComplete?: () => void;
  placeholder?: string;
}

interface MultipleModelPickerProps extends ModelPickerBaseProps {
  mode: 'multiple';
  values: readonly string[];
  onValuesChange: (values: string[]) => void;
  emptyLabel: string;
  title: string;
  description: string;
  searchLabel: string;
}

type ModelPickerProps = SingleModelPickerProps | MultipleModelPickerProps;

export function ModelPicker(props: ModelPickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const selectionCompleted = useRef(false);
  const listboxId = useId();
  const multiple = props.mode === 'multiple';
  const selected = multiple ? undefined : props.options.find((option) => option.value === props.value);
  const visibleOptions = props.options.filter((option) => option.searchText.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const highlightedIndex = Math.min(activeIndex, Math.max(visibleOptions.length - 1, 0));
  const highlightedOption = visibleOptions[highlightedIndex];
  const firstSelected = multiple ? props.options.find((option) => option.value === props.values[0]) : undefined;

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
      multiple
        ? 0
        : Math.max(
            0,
            props.options.findIndex((option) => option.value === props.value),
          ),
    );
  };

  const selectOption = (option: ModelPickerOption) => {
    if (multiple) {
      const selected = props.values.includes(option.value);
      props.onValuesChange(selected ? props.values.filter((value) => value !== option.value) : [...props.values, option.value]);
      return;
    }
    selectionCompleted.current = true;
    props.onValueChange(option.value);
    onOpenChange(false);
  };

  const triggerLabel = multiple ? (
    props.values.length === 0 ? (
      props.emptyLabel
    ) : (
      <span className="flex min-w-0 flex-1 items-center gap-2">
        {firstSelected?.label ?? props.values[0]}
        {props.values.length > 1 && <span className="shrink-0 text-muted-foreground">+{props.values.length - 1} more</span>}
      </span>
    )
  ) : (
    (selected?.label ?? props.placeholder ?? 'Select model')
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button
          id={props.id}
          variant="outline"
          className={cn('h-9 w-full justify-between px-3 text-left text-[13px] normal-case tracking-normal', props.className)}
          aria-label={props['aria-label']}
          disabled={props.disabled}
        >
          <span className="flex min-w-0 flex-1 items-center overflow-hidden">{triggerLabel}</span>
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        </Button>
      </DialogTrigger>
      <DialogContent
        className="w-[calc(100%-2rem)] max-w-lg gap-4 border-border bg-card p-4 text-card-foreground"
        onCloseAutoFocus={(event) => {
          const selectedOption = selectionCompleted.current;
          selectionCompleted.current = false;
          if (multiple || !selectedOption || !props.onSelectionComplete) return;
          event.preventDefault();
          props.onSelectionComplete();
        }}
      >
        <DialogHeader className="space-y-1">
          <DialogTitle className="text-base">{multiple ? props.title : 'Select model'}</DialogTitle>
          <DialogDescription>{multiple ? props.description : 'Search by model or provider name'}</DialogDescription>
        </DialogHeader>
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type={multiple ? 'search' : 'text'}
            role={multiple ? undefined : 'combobox'}
            aria-label={multiple ? props.searchLabel : undefined}
            aria-controls={multiple ? undefined : listboxId}
            aria-expanded={multiple ? undefined : true}
            aria-activedescendant={!multiple && highlightedOption ? `${listboxId}-${highlightedIndex}` : undefined}
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
            placeholder={multiple ? 'Search models or providers...' : 'Search models...'}
            className="pl-9"
          />
        </div>
        <div id={listboxId} role="listbox" aria-multiselectable={multiple || undefined} className="max-h-72 space-y-1 overflow-y-auto pr-1">
          {visibleOptions.map((option, index) => {
            const optionSelected = multiple ? props.values.includes(option.value) : option.value === props.value;
            return (
              <Button
                key={option.value}
                id={`${listboxId}-${index}`}
                variant="ghost"
                role="option"
                aria-selected={optionSelected}
                tabIndex={-1}
                className={cn(
                  'h-auto w-full justify-start px-3 py-2 text-left normal-case tracking-normal',
                  multiple && 'gap-2 font-mono text-[13px]',
                  index === highlightedIndex && 'bg-primary/10 text-primary',
                )}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => selectOption(option)}
              >
                {multiple && (
                  <span className="flex h-4 w-4 shrink-0 items-center justify-center">{optionSelected && <Check className="h-3.5 w-3.5" />}</span>
                )}
                {option.label}
              </Button>
            );
          })}
          {visibleOptions.length === 0 && <p className="px-3 py-6 text-center text-sm text-muted-foreground">No matching models</p>}
        </div>
        {multiple && (
          <div className="flex justify-end">
            <Button onClick={() => onOpenChange(false)}>Done</Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
