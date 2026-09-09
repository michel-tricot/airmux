import type { UseFormReturn } from 'react-hook-form';
import type { InferenceKeyOut, PolicyCreate, PolicyOut, TaxonomyOut } from '@workspace/api-client-react';
import { FormDialog } from '@/components/shared/form-dialog';
import { Alert, AlertDescription, CheckboxDropdown, Dropdown, Input, Switch } from '@/components/ui/elements';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { policyDefaults, policyForm, policyFormSchema, policyPayload, type PolicyForm } from '@/features/policies/form';

const actionOptions = [
  { value: 'byok', label: 'Require BYOK' },
  { value: 'models', label: 'Allowed models' },
  { value: 'providers', label: 'Allowed providers' },
  { value: 'deny', label: 'Deny matching requests' },
  { value: 'fallback', label: 'Model fallbacks' },
  { value: 'budget', label: 'Budget placeholder' },
];
const failureOptions = [
  { value: 'rate_limited', label: 'Rate limited (429)' },
  { value: 'upstream_unavailable', label: 'Upstream unavailable (5xx or connection failure)' },
  { value: 'timeout', label: 'Upstream timeout' },
];

function TextField({
  form,
  name,
  label,
  numeric = false,
}: {
  form: UseFormReturn<PolicyForm>;
  name: 'name' | 'condition' | 'priority' | 'message' | 'maxAttempts' | 'timeoutMs' | 'amount';
  label: string;
  numeric?: boolean;
}) {
  return (
    <FormField
      control={form.control}
      name={name}
      render={({ field }) => (
        <FormItem>
          <FormLabel>{label}</FormLabel>
          <FormControl>
            <Input
              {...field}
              type={numeric ? 'number' : 'text'}
              onChange={(event) => field.onChange(numeric ? Number(event.target.value) : event.target.value)}
            />
          </FormControl>
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

export function PolicyEditor({
  policy,
  open,
  onOpenChange,
  onSubmit,
  pending,
  keys,
  catalog,
}: {
  policy: PolicyOut | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (payload: PolicyCreate) => Promise<unknown>;
  pending: boolean;
  keys: InferenceKeyOut[];
  catalog: TaxonomyOut;
}) {
  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={policy ? 'Edit policy' : 'Create policy'}
      description="All matching restrictions apply. The first matching fallback policy wins, ordered by priority then policy ID."
      schema={policyFormSchema}
      defaultValues={policy ? policyForm(policy) : policyDefaults}
      onSubmit={(values) => onSubmit(policyPayload(values))}
      submitLabel="Save policy"
      pending={pending}
    >
      {(form) => {
        const kind = form.watch('kind');
        const names = form.watch('names');
        const options =
          kind === 'providers'
            ? catalog.providers.map((provider) => ({ value: provider.name, label: provider.name }))
            : catalog.models.map((model) => ({ value: model.name, label: model.name }));
        return (
          <>
            <TextField form={form} name="name" label="Policy name" />
            <FormField
              control={form.control}
              name="enabled"
              render={({ field }) => (
                <FormItem className="flex items-center justify-between">
                  <FormLabel>Enabled</FormLabel>
                  <FormControl>
                    <Switch checked={field.value} onCheckedChange={field.onChange} />
                  </FormControl>
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="target"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Applies to</FormLabel>
                  <FormControl>
                    <Dropdown
                      value={field.value}
                      onValueChange={field.onChange}
                      aria-label="Applies to"
                      options={[
                        { value: 'all_keys', label: 'All keys' },
                        { value: 'selected_keys', label: 'Selected inference keys' },
                      ]}
                    />
                  </FormControl>
                  <FormMessage />
                  {field.value === 'all_keys' && (
                    <p className="text-sm text-muted-foreground">Includes future inference keys and playground sessions.</p>
                  )}
                </FormItem>
              )}
            />
            {form.watch('target') === 'selected_keys' && (
              <FormField
                control={form.control}
                name="keyIds"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Inference keys</FormLabel>
                    <FormControl>
                      <CheckboxDropdown
                        aria-label="Inference keys"
                        label="Selected keys"
                        allLabel="Choose keys"
                        values={field.value}
                        onValuesChange={field.onChange}
                        options={keys.map((key) => ({ value: key.id, label: `${key.label}${key.revoked ? ' (revoked)' : ''}` }))}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}
            <FormField
              control={form.control}
              name="kind"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Action</FormLabel>
                  <FormControl>
                    <Dropdown
                      value={field.value}
                      onValueChange={(value) => {
                        field.onChange(value);
                        form.setValue('names', []);
                      }}
                      options={actionOptions}
                      aria-label="Action"
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            {kind === 'byok' && (
              <p className="text-sm text-muted-foreground">
                Only workspace or organization provider credentials may be used. Platform credentials are excluded.
              </p>
            )}
            {['models', 'providers', 'fallback'].includes(kind) && (
              <FormField
                control={form.control}
                name="names"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      {kind === 'fallback' ? 'Backup models, in selection order' : kind === 'models' ? 'Allowed models' : 'Allowed providers'}
                    </FormLabel>
                    <FormControl>
                      <CheckboxDropdown
                        aria-label="Allowed routes"
                        label="Selected routes"
                        allLabel="Choose routes"
                        values={field.value}
                        onValuesChange={field.onChange}
                        options={options}
                      />
                    </FormControl>
                    <FormMessage />
                    {names.length > 0 && (
                      <p className="break-words text-sm text-muted-foreground">{names.join(kind === 'fallback' ? ' → ' : ', ')}</p>
                    )}
                  </FormItem>
                )}
              />
            )}
            {kind === 'deny' && <TextField form={form} name="message" label="Denial message" />}
            {kind === 'fallback' && (
              <>
                <FormField
                  control={form.control}
                  name="reasons"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Fallback on</FormLabel>
                      <FormControl>
                        <CheckboxDropdown
                          aria-label="Fallback failures"
                          label="Failure reasons"
                          allLabel="Choose failure reasons"
                          values={field.value}
                          onValuesChange={field.onChange}
                          options={failureOptions}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <div className="grid gap-4 sm:grid-cols-2">
                  <TextField form={form} name="maxAttempts" label="Total upstream attempts" numeric />
                  <TextField form={form} name="timeoutMs" label="Time limit (milliseconds)" numeric />
                </div>
                <p className="text-sm text-muted-foreground">
                  Includes the primary call and credential retries. Every backup must pass all restrictions. Fallback ends when streaming begins.
                </p>
              </>
            )}
            {kind === 'budget' && (
              <>
                <Alert>
                  <AlertDescription>Placeholder only. This setting does not track spending or block requests.</AlertDescription>
                </Alert>
                <TextField form={form} name="amount" label="Estimated spend limit (USD)" />
                <FormField
                  control={form.control}
                  name="period"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Period</FormLabel>
                      <FormControl>
                        <Dropdown
                          value={field.value}
                          onValueChange={field.onChange}
                          options={[
                            { value: 'day', label: 'Calendar day (UTC)' },
                            { value: 'month', label: 'Calendar month (UTC)' },
                          ]}
                          aria-label="Budget period"
                        />
                      </FormControl>
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="sharing"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Allowance sharing</FormLabel>
                      <FormControl>
                        <Dropdown
                          value={field.value}
                          onValueChange={field.onChange}
                          options={[
                            { value: 'shared', label: 'Shared across matching keys' },
                            { value: 'per_key', label: 'Separate allowance per key' },
                          ]}
                          aria-label="Allowance sharing"
                        />
                      </FormControl>
                    </FormItem>
                  )}
                />
              </>
            )}
            <TextField form={form} name="condition" label="When (CEL condition)" />
            <p className="text-sm text-muted-foreground">
              Use true for every request. Available facts: request_model, request_stream, key_id, workspace_id. Example: request_stream == true
            </p>
            <TextField form={form} name="priority" label="Priority (lower runs first)" numeric />
          </>
        );
      }}
    </FormDialog>
  );
}
