import type { ReactNode } from 'react';
import { useForm, type Resolver, type UseFormReturn } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import type { RuleCreate, RuleOut, TaxonomyOut } from '@workspace/api-client-react';
import { CatalogOptionLabel } from '@/components/shared/catalog-option-label';
import { FormDialog } from '@/components/shared/form-dialog';
import { SearchPicker } from '@/components/shared/search-picker';
import { Button, CheckboxDropdown, Dropdown, Input } from '@/components/ui/elements';
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { ruleDefaults, ruleForm, ruleFormSchema, rulePayload, type RuleForm } from '@/features/rules/form';
import { ModelBadges } from '@/features/rules/presentation';
import { ruleType, type RuleKind } from '@/features/rules/types';
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

type TextFieldName = 'name' | 'message' | 'maxAttempts' | 'timeoutMs' | 'maxInputPrice' | 'maxOutputPrice' | 'maxOutputTokens';

function TextField({
  form,
  name,
  label,
  numeric = false,
  min,
  max,
}: {
  form: UseFormReturn<RuleForm>;
  name: TextFieldName;
  label: string;
  numeric?: boolean;
  min?: number;
  max?: number;
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
              stepperLabel={label}
              min={min}
              max={max}
              onChange={(event) => field.onChange(numeric ? Number(event.target.value) : event.target.value)}
            />
          </FormControl>
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

function RuleFields({ form, catalog, kind }: { form: UseFormReturn<RuleForm>; catalog: TaxonomyOut; kind: RuleKind }) {
  const match = form.watch('match');
  const names = form.watch('names');
  const providerById = new Map(catalog.providers.map((provider) => [provider.id, provider]));
  const modelOptions = catalog.models.map((model) => {
    const provider = providerById.get(model.provider_id);
    return {
      value: model.name,
      label: <CatalogOptionLabel name={model.name} providerName={provider?.name} providerIcon={provider?.icon} />,
      searchText: `${model.name} ${provider?.name ?? ''}`,
    };
  });
  const providerOptions = catalog.providers.map((provider) => ({
    value: provider.name,
    label: <CatalogOptionLabel name={provider.name} providerIcon={provider.icon} />,
  }));
  return (
    <>
      <TextField form={form} name="name" label="Rule name" />
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
                aria-label="Rule applies when"
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
                  <SearchPicker
                    mode="multiple"
                    aria-label="Requested models"
                    emptyLabel="Any model"
                    title="Select requested models"
                    description="Search by model or provider name"
                    searchLabel="Search requested models"
                    searchPlaceholder="Search models or providers..."
                    emptyMessage="No matching models"
                    selectionNoun="model"
                    values={field.value}
                    onValuesChange={field.onChange}
                    options={modelOptions}
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
                    label="Selected capabilities"
                    allLabel="Any capabilities"
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
      {kind === 'strict_parameters' && (
        <p className="text-sm text-muted-foreground">Rejects requests when the selected route would drop an unsupported parameter.</p>
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
      {kind === 'request_limits' && <TextField form={form} name="maxOutputTokens" label="Maximum requested output tokens" numeric min={1} />}
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
                  emptyLabel="Choose scopes"
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
          name="names"
          render={({ field }) => (
            <FormItem>
              <FormLabel>
                {kind === 'fallback' ? 'Backup models, in selection order' : kind === 'models' ? 'Allowed models' : 'Allowed providers'}
              </FormLabel>
              <FormControl>
                {kind === 'providers' ? (
                  <CheckboxDropdown
                    aria-label="Allowed routes"
                    label="Selected routes"
                    emptyLabel="Choose routes"
                    values={field.value}
                    onValuesChange={field.onChange}
                    options={providerOptions}
                  />
                ) : (
                  <SearchPicker
                    mode="multiple"
                    aria-label="Allowed routes"
                    emptyLabel="Choose routes"
                    title={kind === 'fallback' ? 'Select backup models' : 'Select allowed models'}
                    description="Search by model or provider name"
                    searchLabel="Search allowed routes"
                    searchPlaceholder="Search models or providers..."
                    emptyMessage="No matching models"
                    selectionNoun="model"
                    values={field.value}
                    onValuesChange={field.onChange}
                    options={modelOptions}
                  />
                )}
              </FormControl>
              <FormMessage />
              {names.length > 0 && kind !== 'providers' && (
                <div className="text-sm text-muted-foreground">
                  <ModelBadges names={names} ordered={kind === 'fallback'} />
                </div>
              )}
              {names.length > 0 && kind === 'providers' && <p className="break-words text-sm text-muted-foreground">{names.join(', ')}</p>}
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
                    emptyLabel="Choose failure reasons"
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
            <TextField form={form} name="maxAttempts" label="Total upstream attempts" numeric min={2} max={5} />
            <TextField form={form} name="timeoutMs" label="Time limit (milliseconds)" numeric min={100} max={120000} />
          </div>
          <p className="text-sm text-muted-foreground">Includes the primary call and credential retries. Every backup must pass all restrictions.</p>
        </>
      )}
    </>
  );
}

export function RuleFormContent({
  rule,
  kind,
  catalog,
  pending,
  submitLabel,
  onSubmit,
  onBack,
  intro,
}: {
  rule: RuleOut | null;
  kind: RuleKind;
  catalog: TaxonomyOut;
  pending: boolean;
  submitLabel: string;
  onSubmit: (payload: RuleCreate) => Promise<unknown>;
  onBack: () => void;
  intro?: ReactNode;
}) {
  const form = useForm<RuleForm>({
    resolver: zodResolver(ruleFormSchema) as Resolver<RuleForm>,
    defaultValues: rule ? ruleForm(rule) : { ...ruleDefaults, kind },
  });
  const handleSubmit = form.handleSubmit(async (values) => {
    try {
      await onSubmit(rulePayload(values));
    } catch {
      return;
    }
  });

  return (
    <Form {...form}>
      <form onSubmit={handleSubmit} noValidate className="space-y-4">
        {intro}
        <RuleFields form={form} catalog={catalog} kind={kind} />
        <div className="flex justify-between gap-2 pt-4">
          <Button type="button" variant="outline" onClick={onBack}>
            Back to policy
          </Button>
          <Button type="submit" disabled={pending}>
            {submitLabel}
          </Button>
        </div>
      </form>
    </Form>
  );
}

export function RuleEditor({
  rule,
  kind,
  open,
  onOpenChange,
  onSubmit,
  pending,
  catalog,
}: {
  rule: RuleOut | null;
  kind: RuleKind;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (payload: RuleCreate) => Promise<unknown>;
  pending: boolean;
  catalog: TaxonomyOut;
}) {
  const type = ruleType(kind);
  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`${rule ? 'Edit' : 'Create'} ${type.formName}`}
      description={`${type.description} Rules are reusable across policies.`}
      schema={ruleFormSchema}
      defaultValues={rule ? ruleForm(rule) : { ...ruleDefaults, kind }}
      onSubmit={(values) => onSubmit(rulePayload(values))}
      submitLabel="Save rule"
      pending={pending}
    >
      {(form) => <RuleFields form={form} catalog={catalog} kind={kind} />}
    </FormDialog>
  );
}
