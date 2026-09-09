import type { UseFormReturn } from 'react-hook-form';
import type { InferenceKeyOut, PolicyCreate, PolicyOut, TaxonomyOut } from '@workspace/api-client-react';
import { FormDialog } from '@/components/shared/form-dialog';
import { Alert, AlertDescription, CheckboxDropdown, Dropdown, Input, Switch } from '@/components/ui/elements';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { policyDefaults, policyForm, policyFormSchema, policyPayload, type PolicyForm } from '@/features/policies/form';

const actionOptions = [
  { value: 'models', label: 'Allowed models' },
  { value: 'providers', label: 'Allowed providers' },
  { value: 'strict_parameters', label: 'Require parameter support' },
  { value: 'price_limit', label: 'Model price limit' },
  { value: 'request_limits', label: 'Request limits' },
  { value: 'credential_access', label: 'Credential access' },
  { value: 'deny', label: 'Deny matching requests' },
  { value: 'fallback', label: 'Model fallbacks' },
  { value: 'budget', label: 'Budget' },
];
const failureOptions = [
  { value: 'rate_limited', label: 'Rate limited (429)' },
  { value: 'upstream_unavailable', label: 'Upstream unavailable (5xx or connection failure)' },
  { value: 'timeout', label: 'Upstream timeout' },
];
const capabilityOptions = [
  { value: 'tools', label: 'Tools' },
  { value: 'reasoning', label: 'Reasoning' },
  { value: 'structured_output', label: 'Structured output' },
];
const credentialScopeOptions = [
  { value: 'workspace', label: 'Workspace credentials' },
  { value: 'org', label: 'Organization credentials' },
  { value: 'platform', label: 'Platform credentials' },
];

function TextField({
  form,
  name,
  label,
  numeric = false,
}: {
  form: UseFormReturn<PolicyForm>;
  name: 'name' | 'priority' | 'message' | 'maxAttempts' | 'timeoutMs' | 'amount' | 'maxInputPrice' | 'maxOutputPrice' | 'maxOutputTokens';
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
        const match = form.watch('match');
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
              name="match"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Applies when</FormLabel>
                  <FormControl>
                    <Dropdown
                      value={field.value}
                      onValueChange={field.onChange}
                      aria-label="Applies when"
                      options={[
                        { value: 'all_requests', label: 'Every request' },
                        { value: 'request', label: 'Request matches' },
                      ]}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            {match === 'request' && (
              <>
                <FormField
                  control={form.control}
                  name="matchModels"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Requested models</FormLabel>
                      <FormControl>
                        <CheckboxDropdown
                          aria-label="Requested models"
                          label="Any model"
                          allLabel="Choose models"
                          values={field.value}
                          onValuesChange={field.onChange}
                          options={catalog.models.map((model) => ({ value: model.name, label: model.name }))}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="matchStream"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Response mode</FormLabel>
                      <FormControl>
                        <Dropdown
                          value={field.value}
                          onValueChange={field.onChange}
                          aria-label="Response mode"
                          options={[
                            { value: 'any', label: 'Streaming or non-streaming' },
                            { value: 'streaming', label: 'Streaming only' },
                            { value: 'non_streaming', label: 'Non-streaming only' },
                          ]}
                        />
                      </FormControl>
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="matchCapabilities"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Request capabilities</FormLabel>
                      <FormControl>
                        <CheckboxDropdown
                          aria-label="Request capabilities"
                          label="Any capabilities"
                          allLabel="Choose capabilities"
                          values={field.value}
                          onValuesChange={field.onChange}
                          options={capabilityOptions}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <p className="text-sm text-muted-foreground">All selected request criteria must match.</p>
              </>
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
            {kind === 'strict_parameters' && (
              <p className="text-sm text-muted-foreground">
                Rejects requests when the selected model or provider would drop an unsupported parameter.
              </p>
            )}
            {kind === 'price_limit' && (
              <>
                <div className="grid gap-4 sm:grid-cols-2">
                  <TextField form={form} name="maxInputPrice" label="Maximum input USD / 1M tokens" />
                  <TextField form={form} name="maxOutputPrice" label="Maximum output USD / 1M tokens" />
                </div>
                <p className="text-sm text-muted-foreground">Every selected primary and fallback model must stay within both catalog rates.</p>
              </>
            )}
            {kind === 'request_limits' && <TextField form={form} name="maxOutputTokens" label="Maximum requested output tokens" numeric />}
            {kind === 'credential_access' && (
              <FormField
                control={form.control}
                name="credentialScopes"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Allowed credential scopes</FormLabel>
                    <FormControl>
                      <CheckboxDropdown
                        aria-label="Allowed credential scopes"
                        label="Selected scopes"
                        allLabel="Choose scopes"
                        values={field.value}
                        onValuesChange={field.onChange}
                        options={credentialScopeOptions}
                      />
                    </FormControl>
                    <FormMessage />
                    <p className="text-sm text-muted-foreground">
                      The most specific allowed scope with credentials is used: workspace, then organization, then platform.
                    </p>
                  </FormItem>
                )}
              />
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
                  <AlertDescription>
                    Budget enforcement is not available yet. This setting does not track spending or block requests.
                  </AlertDescription>
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
            <TextField form={form} name="priority" label="Priority (lower runs first)" numeric />
          </>
        );
      }}
    </FormDialog>
  );
}
