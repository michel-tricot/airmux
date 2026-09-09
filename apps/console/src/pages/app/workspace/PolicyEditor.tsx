import { Plus, Trash2 } from 'lucide-react';
import { useFieldArray, type UseFormReturn } from 'react-hook-form';
import type { InferenceKeyOut, PolicyCreate, PolicyOut, TaxonomyOut } from '@workspace/api-client-react';
import { FormDialog } from '@/components/shared/form-dialog';
import {
  Alert,
  AlertDescription,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CheckboxDropdown,
  Dropdown,
  Input,
  Switch,
} from '@/components/ui/elements';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { policyDefaults, policyForm, policyFormSchema, policyPayload, policyRuleDefaults, type PolicyForm } from '@/features/policies/form';

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

function PolicyTextField({
  form,
  name,
  label,
  numeric = false,
}: {
  form: UseFormReturn<PolicyForm>;
  name: 'name' | 'priority';
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

type RuleTextFieldName = 'message' | 'maxAttempts' | 'timeoutMs' | 'amount' | 'maxInputPrice' | 'maxOutputPrice' | 'maxOutputTokens';

function RuleTextField({
  form,
  index,
  name,
  label,
  numeric = false,
}: {
  form: UseFormReturn<PolicyForm>;
  index: number;
  name: RuleTextFieldName;
  label: string;
  numeric?: boolean;
}) {
  return (
    <FormField
      control={form.control}
      name={`rules.${index}.${name}` as const}
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

function RuleFields({ form, index, catalog }: { form: UseFormReturn<PolicyForm>; index: number; catalog: TaxonomyOut }) {
  const kind = form.watch(`rules.${index}.kind` as const);
  const match = form.watch(`rules.${index}.match` as const);
  const names = form.watch(`rules.${index}.names` as const);
  const options =
    kind === 'providers'
      ? catalog.providers.map((provider) => ({ value: provider.name, label: provider.name }))
      : catalog.models.map((model) => ({ value: model.name, label: model.name }));
  return (
    <div className="space-y-4">
      <FormField
        control={form.control}
        name={`rules.${index}.match` as const}
        render={({ field }) => (
          <FormItem>
            <FormLabel>Applies when</FormLabel>
            <FormControl>
              <Dropdown
                value={field.value}
                onValueChange={field.onChange}
                aria-label={`Rule ${index + 1} applies when`}
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
            name={`rules.${index}.matchModels` as const}
            render={({ field }) => (
              <FormItem>
                <FormLabel>Requested models</FormLabel>
                <FormControl>
                  <CheckboxDropdown
                    aria-label={`Rule ${index + 1} requested models`}
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
            name={`rules.${index}.matchStream` as const}
            render={({ field }) => (
              <FormItem>
                <FormLabel>Response mode</FormLabel>
                <FormControl>
                  <Dropdown
                    value={field.value}
                    onValueChange={field.onChange}
                    aria-label={`Rule ${index + 1} response mode`}
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
            name={`rules.${index}.matchCapabilities` as const}
            render={({ field }) => (
              <FormItem>
                <FormLabel>Request capabilities</FormLabel>
                <FormControl>
                  <CheckboxDropdown
                    aria-label={`Rule ${index + 1} request capabilities`}
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
        name={`rules.${index}.kind` as const}
        render={({ field }) => (
          <FormItem>
            <FormLabel>Action</FormLabel>
            <FormControl>
              <Dropdown
                value={field.value}
                onValueChange={(value) => {
                  field.onChange(value);
                  form.setValue(`rules.${index}.names`, []);
                }}
                options={actionOptions}
                aria-label={`Rule ${index + 1} action`}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      {kind === 'strict_parameters' && (
        <p className="text-sm text-muted-foreground">Rejects requests when the selected model or provider would drop an unsupported parameter.</p>
      )}
      {kind === 'price_limit' && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <RuleTextField form={form} index={index} name="maxInputPrice" label="Maximum input USD / 1M tokens" />
            <RuleTextField form={form} index={index} name="maxOutputPrice" label="Maximum output USD / 1M tokens" />
          </div>
          <p className="text-sm text-muted-foreground">Every selected primary and fallback model must stay within both catalog rates.</p>
        </>
      )}
      {kind === 'request_limits' && (
        <RuleTextField form={form} index={index} name="maxOutputTokens" label="Maximum requested output tokens" numeric />
      )}
      {kind === 'credential_access' && (
        <FormField
          control={form.control}
          name={`rules.${index}.credentialScopes` as const}
          render={({ field }) => (
            <FormItem>
              <FormLabel>Allowed credential scopes</FormLabel>
              <FormControl>
                <CheckboxDropdown
                  aria-label={`Rule ${index + 1} allowed credential scopes`}
                  label="Selected scopes"
                  allLabel="Choose scopes"
                  values={field.value}
                  onValuesChange={field.onChange}
                  options={credentialScopeOptions}
                />
              </FormControl>
              <FormMessage />
              <p className="text-sm text-muted-foreground">
                The most specific allowed scope with credentials is used: workspace, organization, then platform.
              </p>
            </FormItem>
          )}
        />
      )}
      {['models', 'providers', 'fallback'].includes(kind) && (
        <FormField
          control={form.control}
          name={`rules.${index}.names` as const}
          render={({ field }) => (
            <FormItem>
              <FormLabel>
                {kind === 'fallback' ? 'Backup models, in selection order' : kind === 'models' ? 'Allowed models' : 'Allowed providers'}
              </FormLabel>
              <FormControl>
                <CheckboxDropdown
                  aria-label={`Rule ${index + 1} allowed routes`}
                  label="Selected routes"
                  allLabel="Choose routes"
                  values={field.value}
                  onValuesChange={field.onChange}
                  options={options}
                />
              </FormControl>
              <FormMessage />
              {names.length > 0 && <p className="break-words text-sm text-muted-foreground">{names.join(kind === 'fallback' ? ' → ' : ', ')}</p>}
            </FormItem>
          )}
        />
      )}
      {kind === 'deny' && <RuleTextField form={form} index={index} name="message" label="Denial message" />}
      {kind === 'fallback' && (
        <>
          <FormField
            control={form.control}
            name={`rules.${index}.reasons` as const}
            render={({ field }) => (
              <FormItem>
                <FormLabel>Fallback on</FormLabel>
                <FormControl>
                  <CheckboxDropdown
                    aria-label={`Rule ${index + 1} fallback failures`}
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
            <RuleTextField form={form} index={index} name="maxAttempts" label="Total upstream attempts" numeric />
            <RuleTextField form={form} index={index} name="timeoutMs" label="Time limit (milliseconds)" numeric />
          </div>
          <p className="text-sm text-muted-foreground">Includes the primary call and credential retries. Every backup must pass all restrictions.</p>
        </>
      )}
      {kind === 'budget' && (
        <>
          <Alert>
            <AlertDescription>Budget enforcement is not available yet. This rule does not track spending or block requests.</AlertDescription>
          </Alert>
          <RuleTextField form={form} index={index} name="amount" label="Estimated spend limit (USD)" />
          <FormField
            control={form.control}
            name={`rules.${index}.period` as const}
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
                    aria-label={`Rule ${index + 1} budget period`}
                  />
                </FormControl>
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name={`rules.${index}.sharing` as const}
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
                    aria-label={`Rule ${index + 1} allowance sharing`}
                  />
                </FormControl>
              </FormItem>
            )}
          />
        </>
      )}
    </div>
  );
}

function PolicyFields({ form, keys, catalog }: { form: UseFormReturn<PolicyForm>; keys: InferenceKeyOut[]; catalog: TaxonomyOut }) {
  const { fields, append, remove } = useFieldArray({ control: form.control, name: 'rules', keyName: 'fieldId' });
  return (
    <>
      <PolicyTextField form={form} name="name" label="Policy name" />
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
            {field.value === 'all_keys' && <p className="text-sm text-muted-foreground">Includes future inference keys and playground sessions.</p>}
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
      <div className="space-y-3">
        {fields.map((field, index) => (
          <Card key={field.fieldId}>
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <CardTitle>Rule {index + 1}</CardTitle>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                disabled={fields.length === 1}
                aria-label={`Remove rule ${index + 1}`}
                onClick={() => remove(index)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </CardHeader>
            <CardContent>
              <RuleFields form={form} index={index} catalog={catalog} />
            </CardContent>
          </Card>
        ))}
        <Button type="button" variant="outline" disabled={fields.length >= 100} onClick={() => append({ ...policyRuleDefaults })}>
          <Plus className="mr-1 h-4 w-4" />
          Add rule
        </Button>
      </div>
      <PolicyTextField form={form} name="priority" label="Priority (lower runs first)" numeric />
    </>
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
      description="A policy applies an ordered collection of rules to its targeted keys. All matching restrictions apply."
      schema={policyFormSchema}
      defaultValues={policy ? policyForm(policy) : policyDefaults}
      onSubmit={(values) => onSubmit(policyPayload(values))}
      submitLabel="Save policy"
      pending={pending}
    >
      {(form) => <PolicyFields form={form} keys={keys} catalog={catalog} />}
    </FormDialog>
  );
}
