import type { ProviderOut } from '@workspace/api-client-react';
import type { UseFormReturn } from 'react-hook-form';
import * as z from 'zod';
import { ProviderIcon } from '@/components/ProviderIcon';
import { FormDialog } from '@/components/shared/form-dialog';
import { Input, Label } from '@/components/ui/elements';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';

const addSchema = z.object({
  provider: z.string().min(1, 'Pick a provider'),
  name: z.string().min(1, 'Name is required'),
  value: z.string().min(1, 'Paste the key'),
  priority: z.coerce.number().int().min(1),
});

type AddProviderCredentialValues = z.infer<typeof addSchema>;

export function AddProviderCredentialDialog({
  open,
  onOpenChange,
  providers,
  onSubmit,
  pending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  providers: ProviderOut[];
  onSubmit: (values: AddProviderCredentialValues) => Promise<unknown>;
  pending: boolean;
}) {
  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Add Provider Key"
      description="Your key is stored encrypted and never exposed again. Paste it once, and we handle the rest."
      schema={addSchema}
      defaultValues={{ provider: providers[0]?.name ?? '', name: 'default', value: '', priority: 100 }}
      onSubmit={onSubmit}
      submitLabel="Add Key"
      pending={pending}
    >
      {(form) => <ProviderCredentialFields form={form} providers={providers} />}
    </FormDialog>
  );
}

function ProviderCredentialFields({ form, providers }: { form: UseFormReturn<AddProviderCredentialValues>; providers: ProviderOut[] }) {
  return (
    <>
      <FormField
        control={form.control}
        name="provider"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Provider</FormLabel>
            <FormControl>
              <RadioGroup value={field.value} onValueChange={field.onChange} aria-label="Provider" className="flex flex-wrap gap-2">
                {providers.map((provider) => {
                  const optionId = `provider-${provider.id}`;
                  return (
                    <div key={provider.id} className="relative">
                      <RadioGroupItem id={optionId} value={provider.name} className="peer sr-only" />
                      <Label
                        htmlFor={optionId}
                        className="inline-flex h-8 cursor-pointer items-center justify-center gap-2 rounded border border-input bg-background/50 px-3 shadow-sm transition-colors hover:border-primary/50 hover:bg-primary/10 hover:text-primary peer-data-[state=checked]:border-border/50 peer-data-[state=checked]:bg-secondary peer-data-[state=checked]:text-secondary-foreground peer-focus-visible:outline-none peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2"
                      >
                        {provider.icon ? <ProviderIcon markup={provider.icon} /> : null}
                        {provider.name}
                      </Label>
                    </div>
                  );
                })}
              </RadioGroup>
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="name"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Name</FormLabel>
            <FormControl>
              <Input placeholder="e.g. prod or backup" {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="value"
        render={({ field }) => (
          <FormItem>
            <FormLabel>API key</FormLabel>
            <FormControl>
              <Input type="password" autoComplete="off" placeholder="sk-..." {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="priority"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Priority</FormLabel>
            <FormControl>
              <Input type="number" min={1} {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
    </>
  );
}
