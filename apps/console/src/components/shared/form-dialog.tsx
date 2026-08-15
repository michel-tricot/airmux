import { useEffect, useRef, type ReactNode } from 'react';
import { useForm, type DefaultValues, type FieldValues, type Resolver, type UseFormReturn } from 'react-hook-form';
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
  onSubmit: (values: T) => Promise<unknown> | unknown;
  submitLabel: string;
  pendingLabel?: string;
  pending?: boolean;
  children: (form: UseFormReturn<T>) => ReactNode;
}

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
  const defaultValuesRef = useRef(defaultValues);
  const form = useForm<T>({
    resolver: zodResolver(schema) as Resolver<T>,
    defaultValues,
  });

  useEffect(() => {
    defaultValuesRef.current = defaultValues;
  }, [defaultValues]);

  useEffect(() => {
    if (open) form.reset(defaultValuesRef.current);
  }, [form, open]);

  const handleSubmit = form.handleSubmit(async (values) => {
    try {
      await onSubmit(values);
      onOpenChange(false);
    } catch {
      return;
    }
  });

  return (
    <Modal open={open} onOpenChange={onOpenChange} title={title} description={description}>
      <Form {...form}>
        <form onSubmit={handleSubmit} noValidate className="space-y-4 pt-4">
          {children(form)}
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending && pendingLabel ? pendingLabel : submitLabel}
            </Button>
          </div>
        </form>
      </Form>
    </Modal>
  );
}
