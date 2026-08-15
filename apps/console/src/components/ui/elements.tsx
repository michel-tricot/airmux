import React, { forwardRef } from 'react';
import { cn } from '@/lib/utils';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import * as TabsPrimitive from '@radix-ui/react-tabs';
import * as SelectPrimitive from '@radix-ui/react-select';
import { Slot } from '@radix-ui/react-slot';
import { X, Check, ChevronsUpDown } from 'lucide-react';
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
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';

export {
  Alert,
  AlertDescription,
  AlertTitle,
  Avatar,
  AvatarFallback,
  AvatarImage,
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
};

export const Button = forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: 'default' | 'outline' | 'ghost' | 'destructive' | 'secondary';
    size?: 'default' | 'sm' | 'lg' | 'icon';
    asChild?: boolean;
  }
>(({ asChild = false, className, variant = 'default', size = 'default', type = 'button', ...props }, ref) => {
  const variants = {
    default: 'bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm',
    secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80 shadow-sm border border-border/50',
    outline: 'border border-input bg-background/50 hover:border-primary/50 hover:bg-primary/10 hover:text-primary transition-all duration-200',
    ghost: 'hover:bg-primary/10 hover:text-primary',
    destructive: 'bg-destructive/10 text-destructive border border-destructive/20 hover:bg-destructive/20',
  };
  const sizes = {
    default: 'h-9 px-4 py-2 text-[12px]',
    sm: 'h-8 rounded px-3 text-[11px]',
    lg: 'h-10 rounded px-8 text-[13px]',
    icon: 'h-9 w-9',
  };
  const Component = asChild ? Slot : 'button';
  return (
    <Component
      ref={ref}
      type={asChild ? undefined : type}
      className={cn(
        'inline-flex items-center justify-center whitespace-nowrap rounded font-mono font-bold uppercase tracking-wider transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50',
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  );
});
Button.displayName = 'Button';

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, type, ...props }, ref) => {
  return (
    <input
      type={type}
      className={cn(
        'flex h-9 w-full rounded border border-input bg-background/50 px-3 py-1 text-sm font-mono shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground/50 focus-visible:outline-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      ref={ref}
      {...props}
    />
  );
});
Input.displayName = 'Input';

export const Label = forwardRef<HTMLLabelElement, React.LabelHTMLAttributes<HTMLLabelElement> & { htmlFor: string }>(
  ({ className, htmlFor, ...props }, ref) => (
    <label
      ref={ref}
      htmlFor={htmlFor}
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
  'aria-label': ariaLabel,
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: DropdownOption[];
  actions?: DropdownAction[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  'aria-label'?: string;
}) => (
  <SelectPrimitive.Root
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
    <SelectPrimitive.Trigger
      aria-label={ariaLabel}
      className={cn(
        'flex h-9 w-full items-center justify-between gap-2 rounded border border-input bg-background/50 px-3 text-[13px] font-mono shadow-sm transition-colors hover:border-primary/50 hover:bg-primary/5 focus:outline-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-50 data-[placeholder]:text-muted-foreground',
        className,
      )}
    >
      <span className="truncate text-left">
        <SelectPrimitive.Value placeholder={placeholder} />
      </span>
      <SelectPrimitive.Icon asChild>
        <ChevronsUpDown className="h-4 w-4 shrink-0 text-muted-foreground/70" />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        position="popper"
        sideOffset={6}
        className="z-50 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-md border border-border bg-card text-card-foreground shadow-xl shadow-black/50 animate-in fade-in-0 zoom-in-95"
      >
        <SelectPrimitive.Viewport className="p-1 max-h-72">
          {options.map((option) => (
            <SelectPrimitive.Item
              key={option.value}
              value={option.value}
              className="relative flex cursor-pointer select-none items-center rounded-sm px-3 py-2 pr-9 text-sm font-mono outline-none transition-colors data-[highlighted]:bg-primary/10 data-[highlighted]:text-primary data-[state=checked]:text-primary"
            >
              <SelectPrimitive.ItemText>{option.label}</SelectPrimitive.ItemText>
              <SelectPrimitive.ItemIndicator className="absolute right-3">
                <Check className="h-4 w-4" />
              </SelectPrimitive.ItemIndicator>
            </SelectPrimitive.Item>
          ))}
          {actions && actions.length > 0 && (
            <>
              {options.length > 0 && <div className="my-1 h-px bg-border" />}
              {actions.map((action, i) => (
                <SelectPrimitive.Item
                  key={i}
                  value={`${ACTION_PREFIX}${i}`}
                  className="flex cursor-pointer select-none items-center justify-between gap-3 rounded-sm px-3 py-2 text-sm font-mono outline-none transition-colors data-[highlighted]:bg-primary/10 data-[highlighted]:text-primary"
                >
                  <SelectPrimitive.ItemText>{action.label}</SelectPrimitive.ItemText>
                  {action.icon && <span className="shrink-0 opacity-70">{action.icon}</span>}
                </SelectPrimitive.Item>
              ))}
            </>
          )}
        </SelectPrimitive.Viewport>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  </SelectPrimitive.Root>
);

export const Badge = ({
  className,
  variant = 'default',
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { variant?: 'default' | 'secondary' | 'destructive' | 'outline' | 'success' | 'mono' }) => {
  const variants = {
    default: 'border-primary/30 bg-primary/10 text-primary',
    secondary: 'border-border bg-secondary text-secondary-foreground',
    destructive: 'border-destructive/30 bg-destructive/10 text-destructive',
    success: 'border-success/30 bg-success/10 text-success',
    outline: 'border-border text-foreground',
    mono: 'border-border bg-muted/50 text-muted-foreground',
  };
  return (
    <div
      className={cn(
        'inline-flex items-center rounded border px-2 py-0.5 text-[10px] font-mono font-bold uppercase tracking-wider transition-colors',
        variants[variant],
        className,
      )}
      {...props}
    />
  );
};

export const Card = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn('rounded-lg border border-card-border bg-card/80 backdrop-blur-sm text-card-foreground shadow-lg shadow-black/20', className)}
    {...props}
  />
);
export const CardHeader = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn('flex flex-col space-y-1.5 p-6', className)} {...props} />
);
export const CardTitle = ({ className, children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
  <h3 className={cn('font-semibold leading-none tracking-tight text-lg text-foreground', className)} {...props}>
    {children}
  </h3>
);
export const CardContent = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn('p-6 pt-0', className)} {...props} />
);

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
  <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
      <DialogPrimitive.Content
        className={cn(
          'fixed left-[50%] top-[50%] z-50 grid w-[calc(100%-2rem)] max-w-lg translate-x-[-50%] translate-y-[-50%] gap-6 border border-border bg-card p-6 shadow-2xl shadow-black/50 duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-[50%] data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-[50%] sm:rounded-lg',
          contentClassName,
        )}
      >
        <div className="flex flex-col space-y-2">
          <DialogPrimitive.Title className="text-xl font-semibold leading-none tracking-tight">{title}</DialogPrimitive.Title>
          {description && <DialogPrimitive.Description className="text-sm text-muted-foreground">{description}</DialogPrimitive.Description>}
        </div>
        {children}
        <DialogPrimitive.Close className="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 hover:text-primary hover:bg-primary/10 p-1 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 disabled:pointer-events-none">
          <X className="h-4 w-4" />
          <span className="sr-only">Close</span>
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  </DialogPrimitive.Root>
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

export const Table = ({ className, ...props }: React.HTMLAttributes<HTMLTableElement>) => (
  <div className="relative w-full overflow-auto rounded-md border border-border bg-card/50">
    <table className={cn('w-full caption-bottom text-sm', className)} {...props} />
  </div>
);
export const TableHeader = ({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) => (
  <thead className={cn('[&_tr]:border-b border-border bg-muted/30', className)} {...props} />
);
export const TableBody = ({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) => (
  <tbody className={cn('[&_tr:last-child]:border-0', className)} {...props} />
);
export const TableRow = ({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) => (
  <tr className={cn('border-b border-border transition-colors hover:bg-muted/50 data-[state=selected]:bg-muted', className)} {...props} />
);
export const TableHead = ({ className, ...props }: React.HTMLAttributes<HTMLTableCellElement>) => (
  <th
    className={cn(
      'h-10 px-3 text-left align-middle font-mono text-[11px] font-bold uppercase tracking-wider text-muted-foreground [&:has([role=checkbox])]:pr-0',
      className,
    )}
    {...props}
  />
);
export const TableCell = ({ className, ...props }: React.HTMLAttributes<HTMLTableCellElement>) => (
  <td className={cn('p-3 align-middle [&:has([role=checkbox])]:pr-0', className)} {...props} />
);

export const Tabs = TabsPrimitive.Root;

export const TabsList = React.forwardRef<React.ElementRef<typeof TabsPrimitive.List>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>>(
  ({ className, ...props }, ref) => (
    <TabsPrimitive.List
      ref={ref}
      className={cn(
        'inline-flex h-10 max-w-full items-center justify-start overflow-x-auto rounded bg-muted/50 p-1 text-muted-foreground',
        className,
      )}
      {...props}
    />
  ),
);
TabsList.displayName = TabsPrimitive.List.displayName;

export const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      'inline-flex items-center justify-center whitespace-nowrap rounded-sm px-4 py-1.5 text-[12px] font-mono font-bold uppercase tracking-wider ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 data-[state=active]:bg-background data-[state=active]:text-primary data-[state=active]:shadow-sm',
      className,
    )}
    {...props}
  />
));
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

export const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      'mt-4 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2',
      className,
    )}
    {...props}
  />
));
TabsContent.displayName = TabsPrimitive.Content.displayName;
