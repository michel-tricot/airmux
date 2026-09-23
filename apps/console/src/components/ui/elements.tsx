import React, { forwardRef } from 'react';
import { Check, ChevronDown, ChevronUp } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge as BadgePrimitive } from '@/components/ui/badge';
import { Button as ButtonPrimitive, type ButtonProps as ButtonPrimitiveProps } from '@/components/ui/button';
import { Card as CardPrimitive, CardContent as CardContentPrimitive, CardHeader as CardHeaderPrimitive } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItemIndicator,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input as InputPrimitive } from '@/components/ui/input';
import { Label as LabelPrimitive } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectSeparator, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import {
  Table as TablePrimitive,
  TableBody as TableBodyPrimitive,
  TableCell as TableCellPrimitive,
  TableHead as TableHeadPrimitive,
  TableHeader as TableHeaderPrimitive,
  TableRow as TableRowPrimitive,
} from '@/components/ui/table';
import {
  Tabs as TabsPrimitive,
  TabsContent as TabsContentPrimitive,
  TabsList as TabsListPrimitive,
  TabsTrigger as TabsTriggerPrimitive,
} from '@/components/ui/tabs';

export { Alert, AlertDescription, AlertTitle, Avatar, AvatarFallback, Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle };

type ButtonVariant = 'default' | 'outline' | 'ghost' | 'destructive' | 'secondary';
type ButtonSize = 'default' | 'sm' | 'lg' | 'icon';
type ButtonProps = Omit<ButtonPrimitiveProps, 'variant' | 'size'> & { variant?: ButtonVariant; size?: ButtonSize };

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ asChild = false, className, variant = 'default', size = 'default', type = 'button', ...props }, ref) => {
    const variants = {
      default: 'border-0 bg-primary text-primary-foreground shadow-[0_0_15px] shadow-primary/40 hover:bg-primary/90',
      secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80 shadow-sm border border-border/50',
      outline: 'border border-input bg-background/50 hover:border-primary/50 hover:bg-primary/10 hover:text-primary transition-all duration-200',
      ghost: 'border-0 hover:bg-primary/10 hover:text-primary',
      destructive: 'bg-destructive/10 text-destructive border border-destructive/20 hover:bg-destructive/20',
    };
    const sizes = {
      default: 'h-9 px-4 text-[12px]',
      sm: 'h-8 rounded px-3 text-[11px]',
      lg: 'h-10 rounded px-8 text-[13px]',
      icon: 'h-9 w-9',
    };
    return (
      <ButtonPrimitive
        ref={ref}
        asChild={asChild}
        type={asChild ? undefined : type}
        variant={variant}
        size={size}
        className={cn(
          'min-h-0 gap-2 rounded py-0 text-center font-mono font-bold uppercase leading-none tracking-wider focus-visible:ring-2',
          variants[variant],
          sizes[size],
          className,
        )}
        {...props}
      />
    );
  },
);
Button.displayName = 'Button';

export const Switch = forwardRef<
  HTMLButtonElement,
  Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'onChange' | 'onClick'> & { checked: boolean; onCheckedChange: (checked: boolean) => void }
>(({ checked, className, onCheckedChange, type = 'button', ...props }, ref) => (
  <button
    ref={ref}
    type={type}
    role="switch"
    aria-checked={checked}
    className={cn(
      'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full bg-muted transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
      checked && 'bg-primary',
      className,
    )}
    onClick={() => onCheckedChange(!checked)}
    {...props}
  >
    <span
      className={cn(
        'pointer-events-none block h-3.5 w-3.5 translate-x-1 rounded-full bg-white shadow transition-transform',
        checked && 'translate-x-4.5',
      )}
    />
  </button>
));
Switch.displayName = 'Switch';

type InputProps = React.ComponentPropsWithoutRef<typeof InputPrimitive> & { stepperLabel?: string };

export const Input = forwardRef<HTMLInputElement, InputProps>(({ className, stepperLabel = 'value', type, disabled, ...props }, ref) => {
  const inputRef = React.useRef<HTMLInputElement | null>(null);
  const setRef = (input: HTMLInputElement | null) => {
    inputRef.current = input;
    if (typeof ref === 'function') ref(input);
    else if (ref) ref.current = input;
  };
  const step = (direction: 'up' | 'down') => {
    const input = inputRef.current;
    if (!input) return;
    if (direction === 'up') input.stepUp();
    else input.stepDown();
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.focus();
  };
  const input = (
    <InputPrimitive
      ref={setRef}
      type={type}
      disabled={disabled}
      className={cn(
        'rounded bg-background/50 text-sm font-mono placeholder:text-muted-foreground/50 focus-visible:border-primary focus-visible:ring-primary',
        type === 'number' && 'pr-8',
        type === 'date' &&
          'relative [color-scheme:dark] [&::-webkit-calendar-picker-indicator]:absolute [&::-webkit-calendar-picker-indicator]:right-3 [&::-webkit-calendar-picker-indicator]:top-1/2 [&::-webkit-calendar-picker-indicator]:-translate-y-1/2 [&::-webkit-calendar-picker-indicator]:cursor-pointer',
        className,
      )}
      {...props}
    />
  );
  if (type !== 'number') return input;
  return (
    <div className="relative">
      {input}
      <div className="absolute inset-y-px right-px flex w-7 flex-col overflow-hidden rounded-r border-l border-border bg-muted/40">
        <button
          type="button"
          aria-label={`Increase ${stepperLabel}`}
          disabled={disabled}
          className={cn(
            'flex min-h-0 flex-1 items-center justify-center text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary',
            'focus-visible:z-10 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-primary',
            'disabled:cursor-not-allowed disabled:opacity-50',
          )}
          onClick={() => step('up')}
        >
          <ChevronUp className="h-3 w-3" />
        </button>
        <button
          type="button"
          aria-label={`Decrease ${stepperLabel}`}
          disabled={disabled}
          className={cn(
            'flex min-h-0 flex-1 items-center justify-center border-t border-border text-muted-foreground transition-colors',
            'hover:bg-primary/10 hover:text-primary focus-visible:z-10 focus-visible:outline-none focus-visible:ring-1',
            'focus-visible:ring-inset focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-50',
          )}
          onClick={() => step('down')}
        >
          <ChevronDown className="h-3 w-3" />
        </button>
      </div>
    </div>
  );
});
Input.displayName = 'Input';

export const Label = forwardRef<React.ElementRef<typeof LabelPrimitive>, React.ComponentPropsWithoutRef<typeof LabelPrimitive> & { htmlFor: string }>(
  ({ className, ...props }, ref) => (
    <LabelPrimitive
      ref={ref}
      className={cn(
        'text-[11px] font-mono font-bold uppercase tracking-wider leading-none text-muted-foreground peer-disabled:cursor-not-allowed peer-disabled:opacity-70',
        className,
      )}
      {...props}
    />
  ),
);
Label.displayName = 'Label';

const ACTION_PREFIX = '__action__:';

type DropdownOption = { value: string; label: React.ReactNode };
type DropdownAction = { label: React.ReactNode; icon?: React.ReactNode; onSelect: () => void };

export const Dropdown = ({
  value,
  onValueChange,
  options,
  actions,
  placeholder = 'Select…',
  disabled,
  className,
  id,
  'aria-label': ariaLabel,
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: DropdownOption[];
  actions?: DropdownAction[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  id?: string;
  'aria-label'?: string;
}) => (
  <Select
    value={value}
    onValueChange={(v) => {
      if (v.startsWith(ACTION_PREFIX)) {
        actions?.[Number(v.slice(ACTION_PREFIX.length))]?.onSelect();
        return;
      }
      onValueChange(v);
    }}
    disabled={disabled}
  >
    <SelectTrigger
      id={id}
      aria-label={ariaLabel}
      className={cn(
        'flex h-9 w-full items-center justify-between gap-2 rounded border border-input bg-background/50 px-3 text-[13px] font-mono leading-none shadow-sm transition-colors hover:border-primary/50 hover:bg-primary/5 focus:outline-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-50 data-[placeholder]:text-muted-foreground',
        className,
      )}
    >
      <SelectValue placeholder={placeholder} />
    </SelectTrigger>
    <SelectContent
      position="popper"
      sideOffset={6}
      className="z-50 min-w-[var(--radix-select-trigger-width)] border-border bg-card text-card-foreground shadow-xl shadow-black/50 [&_[data-radix-select-viewport]]:h-auto [&_[data-radix-select-viewport]]:max-h-72"
    >
      {options.map((option) => (
        <SelectItem
          key={option.value}
          value={option.value}
          className="cursor-pointer px-3 py-2 pr-9 font-mono data-[highlighted]:bg-primary/10 data-[highlighted]:text-primary data-[state=checked]:text-primary"
        >
          {option.label}
        </SelectItem>
      ))}
      {actions && actions.length > 0 && (
        <>
          {options.length > 0 && <SelectSeparator className="bg-border" />}
          {actions.map((action, i) => (
            <SelectItem
              key={`${ACTION_PREFIX}${i}`}
              value={`${ACTION_PREFIX}${i}`}
              className="cursor-pointer px-3 py-2 font-mono data-[highlighted]:bg-primary/10 data-[highlighted]:text-primary"
            >
              <span className="flex w-full items-center justify-between gap-3">
                {action.label}
                {action.icon && <span className="shrink-0 opacity-70">{action.icon}</span>}
              </span>
            </SelectItem>
          ))}
        </>
      )}
    </SelectContent>
  </Select>
);

type CheckboxDropdownOption = { value: string; label: React.ReactNode };
type CheckboxDropdownEmptyState = { allLabel: string; emptyLabel?: never } | { allLabel?: never; emptyLabel: string };

export const CheckboxDropdown = ({
  label,
  allLabel,
  emptyLabel,
  values,
  onValuesChange,
  options,
  disabled,
  className,
  'aria-label': ariaLabel,
}: {
  label: string;
  values: readonly string[];
  onValuesChange: (values: string[]) => void;
  options: CheckboxDropdownOption[];
  disabled?: boolean;
  className?: string;
  'aria-label': string;
} & CheckboxDropdownEmptyState) => (
  <DropdownMenu>
    <DropdownMenuTrigger asChild>
      <Button
        variant="outline"
        size="sm"
        aria-label={ariaLabel}
        disabled={disabled}
        className={cn('h-9 w-full justify-between gap-2 px-3 text-[13px] normal-case tracking-normal', className)}
      >
        <span className="truncate">{values.length === 0 ? (allLabel ?? emptyLabel) : `${label} (${values.length})`}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      </Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent
      align="start"
      className="z-50 max-h-[var(--radix-dropdown-menu-content-available-height)] min-w-[var(--radix-dropdown-menu-trigger-width)] overflow-y-auto rounded border border-border bg-card p-1 text-card-foreground shadow-xl shadow-black/50"
    >
      {allLabel !== undefined && (
        <>
          <DropdownMenuCheckboxItem
            checked={values.length === 0}
            onCheckedChange={() => onValuesChange([])}
            onSelect={(event) => event.preventDefault()}
            className="relative flex cursor-default select-none items-center rounded py-2 pl-8 pr-3 text-[13px] font-mono outline-none transition-colors data-[highlighted]:bg-primary/10 data-[highlighted]:text-primary"
          >
            <span className="absolute left-2 flex h-4 w-4 items-center justify-center">
              <DropdownMenuItemIndicator>
                <Check className="h-3.5 w-3.5" />
              </DropdownMenuItemIndicator>
            </span>
            {allLabel}
          </DropdownMenuCheckboxItem>
          <DropdownMenuSeparator className="my-1 h-px bg-border" />
        </>
      )}
      {options.map((option) => {
        const checked = values.includes(option.value);
        return (
          <DropdownMenuCheckboxItem
            key={option.value}
            checked={checked}
            onCheckedChange={(next) => onValuesChange(next ? [...values, option.value] : values.filter((value) => value !== option.value))}
            onSelect={(event) => event.preventDefault()}
            className="relative flex cursor-default select-none items-center rounded py-2 pl-8 pr-3 text-[13px] font-mono outline-none transition-colors data-[highlighted]:bg-primary/10 data-[highlighted]:text-primary data-[state=checked]:text-primary"
          >
            <span className="absolute left-2 flex h-4 w-4 items-center justify-center">
              <DropdownMenuItemIndicator>
                <Check className="h-3.5 w-3.5" />
              </DropdownMenuItemIndicator>
            </span>
            {option.label}
          </DropdownMenuCheckboxItem>
        );
      })}
    </DropdownMenuContent>
  </DropdownMenu>
);

export const Badge = ({
  className,
  variant = 'default',
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { variant?: 'default' | 'secondary' | 'destructive' | 'outline' | 'success' | 'warning' | 'mono' }) => {
  const variants = {
    default: 'border-primary/30 bg-primary/10 text-primary shadow-[0_0_8px] shadow-primary/15',
    secondary: 'border-border bg-secondary text-secondary-foreground',
    destructive: 'border-destructive/30 bg-destructive/10 text-destructive',
    success: 'border-success/30 bg-success/10 text-success',
    warning: 'border-warning/30 bg-warning/10 text-warning',
    outline: 'border-border text-foreground',
    mono: 'border-border bg-muted/50 text-muted-foreground',
  };
  return (
    <BadgePrimitive
      variant={variant === 'success' || variant === 'warning' || variant === 'mono' ? 'outline' : variant}
      className={cn(
        'inline-flex h-5 items-center justify-center rounded border px-2 pb-0 pt-0.5 text-[10px] leading-none font-mono font-bold uppercase tracking-wider transition-colors',
        variants[variant],
        className,
      )}
      {...props}
    />
  );
};

export const Card = forwardRef<React.ElementRef<typeof CardPrimitive>, React.ComponentPropsWithoutRef<typeof CardPrimitive>>(
  ({ className, ...props }, ref) => (
    <CardPrimitive
      ref={ref}
      className={cn('rounded-lg border-card-border bg-card/80 backdrop-blur-sm shadow-lg shadow-black/20', className)}
      {...props}
    />
  ),
);
Card.displayName = 'Card';

export const CardHeader = CardHeaderPrimitive;

export const CardTitle = forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(({ className, children, ...props }, ref) => (
  <h3 ref={ref} className={cn('text-lg font-semibold leading-none tracking-tight text-foreground', className)} {...props}>
    {children}
  </h3>
));
CardTitle.displayName = 'CardTitle';

export const CardContent = CardContentPrimitive;

export const Modal = ({
  open,
  onOpenChange,
  title,
  description,
  children,
  contentClassName,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  contentClassName?: string;
}) => (
  <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent
      className={cn(
        'w-[calc(100%-2rem)] grid-cols-1 gap-6 border-border bg-card text-card-foreground shadow-2xl shadow-black/50 data-[state=closed]:slide-out-to-top-[50%] data-[state=open]:slide-in-from-top-[50%]',
        contentClassName,
      )}
    >
      <DialogHeader className="space-y-2">
        <DialogTitle className="text-xl">{title}</DialogTitle>
        {description && <DialogDescription>{description}</DialogDescription>}
      </DialogHeader>
      {children}
    </DialogContent>
  </Dialog>
);

export const ConfirmButton = ({
  title,
  description,
  confirmLabel = 'Delete',
  onConfirm,
  pending,
  variant = 'ghost',
  size = 'icon',
  className,
  children,
  ...props
}: {
  title: string;
  description?: string;
  confirmLabel?: string;
  onConfirm: () => Promise<unknown> | unknown;
  pending?: boolean;
  children: React.ReactNode;
} & Omit<React.ComponentProps<typeof Button>, 'onClick' | 'title'>) => {
  const [open, setOpen] = React.useState(false);
  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger asChild>
        <Button variant={variant} size={size} className={cn('text-destructive hover:bg-destructive/10 hover:text-destructive', className)} {...props}>
          {children}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description ?? 'This action cannot be undone.'}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </AlertDialogCancel>
          <Button
            variant="destructive"
            disabled={pending}
            onClick={async () => {
              try {
                await onConfirm();
                setOpen(false);
              } catch {
                return;
              }
            }}
          >
            {confirmLabel}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};

type TableProps = React.ComponentPropsWithoutRef<typeof TablePrimitive> & { clipOverflow?: boolean };

export const Table = forwardRef<React.ElementRef<typeof TablePrimitive>, TableProps>(({ className, clipOverflow = false, ...props }, ref) => (
  <div
    data-slot="table-surface"
    className={cn(
      'relative w-full rounded-md border border-border bg-card/50',
      clipOverflow ? 'overflow-hidden [&>div]:overflow-hidden' : 'overflow-auto',
    )}
  >
    <TablePrimitive ref={ref} className={className} {...props} />
  </div>
));
Table.displayName = 'Table';

export const TableHeader = forwardRef<React.ElementRef<typeof TableHeaderPrimitive>, React.ComponentPropsWithoutRef<typeof TableHeaderPrimitive>>(
  ({ className, ...props }, ref) => <TableHeaderPrimitive ref={ref} className={cn('border-border bg-muted/30', className)} {...props} />,
);
TableHeader.displayName = 'TableHeader';

export const TableBody = TableBodyPrimitive;

export const TableRow = forwardRef<React.ElementRef<typeof TableRowPrimitive>, React.ComponentPropsWithoutRef<typeof TableRowPrimitive>>(
  ({ className, ...props }, ref) => <TableRowPrimitive ref={ref} className={cn('border-border', className)} {...props} />,
);
TableRow.displayName = 'TableRow';

export const TableHead = forwardRef<React.ElementRef<typeof TableHeadPrimitive>, React.ComponentPropsWithoutRef<typeof TableHeadPrimitive>>(
  ({ className, ...props }, ref) => (
    <TableHeadPrimitive
      ref={ref}
      className={cn('px-3 font-mono text-[11px] font-bold uppercase tracking-wider [&>[role=checkbox]]:translate-y-0', className)}
      {...props}
    />
  ),
);
TableHead.displayName = 'TableHead';

export const TableCell = forwardRef<React.ElementRef<typeof TableCellPrimitive>, React.ComponentPropsWithoutRef<typeof TableCellPrimitive>>(
  ({ className, ...props }, ref) => <TableCellPrimitive ref={ref} className={cn('p-3 [&>[role=checkbox]]:translate-y-0', className)} {...props} />,
);
TableCell.displayName = 'TableCell';

export const Tabs = TabsPrimitive;

export const TabsList = React.forwardRef<React.ElementRef<typeof TabsListPrimitive>, React.ComponentPropsWithoutRef<typeof TabsListPrimitive>>(
  ({ className, ...props }, ref) => (
    <TabsListPrimitive
      ref={ref}
      className={cn(
        'inline-flex h-10 max-w-full items-center justify-start overflow-x-auto rounded bg-muted/50 p-1 text-muted-foreground',
        className,
      )}
      {...props}
    />
  ),
);
TabsList.displayName = 'TabsList';

export const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsTriggerPrimitive>,
  React.ComponentPropsWithoutRef<typeof TabsTriggerPrimitive>
>(({ className, ...props }, ref) => (
  <TabsTriggerPrimitive
    ref={ref}
    className={cn(
      'inline-flex items-center justify-center min-h-8 whitespace-nowrap rounded-sm px-4 py-1.5 text-center text-[12px] leading-none font-mono font-bold uppercase tracking-wider ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 data-[state=active]:bg-background data-[state=active]:text-primary data-[state=active]:shadow-sm',
      className,
    )}
    {...props}
  />
));
TabsTrigger.displayName = 'TabsTrigger';

export const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsContentPrimitive>,
  React.ComponentPropsWithoutRef<typeof TabsContentPrimitive>
>(({ className, ...props }, ref) => (
  <TabsContentPrimitive
    ref={ref}
    className={cn(
      'mt-4 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2',
      className,
    )}
    {...props}
  />
));
TabsContent.displayName = 'TabsContent';
