import { useEffect, type ReactNode } from 'react';
import { useForm, type DefaultValues, type FieldValues, type UseFormReturn } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import type * as z from 'zod';
import { Modal, Button } from '@/components/ui/elements';
import { Form } from '@/components/ui/form';

interface FormDialogProps<T extends FieldValues> {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  schema: z.ZodType<T>;
  defaultValues: DefaultValues<T>;
  /** Usually a mutateAsync call. The dialog closes and resets when it resolves. */
  onSubmit: (values: T) => Promise<unknown> | unknown;
  submitLabel: string;
  pendingLabel?: string;
  pending?: boolean;
  children: (form: UseFormReturn<T>) => ReactNode;
}

/**
 * CRUD dialog shell: react-hook-form + zod validation, cancel/submit footer,
 * pending state, and close-on-success. Errors are surfaced by the global
 * mutation error toast; the dialog simply stays open.
 */
export function FormDialog<T extends FieldValues>({
  open,
  onOpenChange,
  title,
  description,
  schema,
  defaultValues,
  onSubmit,
  submitLabel,
  pendingLabel,
  pending,
  children,
}: FormDialogProps<T>) {
  const form = useForm<T>({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    resolver: zodResolver(schema as any),
    defaultValues,
  });

  // Reopening starts from a clean slate seeded with the latest defaults.
  useEffect(() => {
    if (open) form.reset(defaultValues);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const handleSubmit = form.handleSubmit(async values => {
    try {
      await onSubmit(values);
      onOpenChange(false);
    } catch {
      // The mutation cache already toasts the failure; keep the dialog open.
    }
  });

  return (
    <Modal open={open} onOpenChange={onOpenChange} title={title} description={description}>
      <Form {...form}>
        <form onSubmit={handleSubmit} className="space-y-4 pt-4">
          {children(form)}
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={pending}>
              {pending && pendingLabel ? pendingLabel : submitLabel}
            </Button>
          </div>
        </form>
      </Form>
    </Modal>
  );
}
