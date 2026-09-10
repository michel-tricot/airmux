import { ArrowDown, ArrowUp, Trash2 } from 'lucide-react';
import type { UseFormReturn } from 'react-hook-form';
import type { InferenceKeyOut, PolicyCreate, PolicyOut, RuleOut } from '@workspace/api-client-react';
import { FormDialog } from '@/components/shared/form-dialog';
import { Button, CheckboxDropdown, Dropdown, Input, Switch } from '@/components/ui/elements';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { policyDefaults, policyForm, policyFormSchema, policyPayload, type PolicyForm } from '@/features/policies/form';
import { actionSummary } from '@/features/rules/presentation';

function TextField({
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

function PolicyFields({ form, keys, rules }: { form: UseFormReturn<PolicyForm>; keys: InferenceKeyOut[]; rules: RuleOut[] }) {
  const selectedRuleIds = form.watch('ruleIds');
  const availableRules = rules.filter((rule) => !selectedRuleIds.includes(rule.id));
  const move = (index: number, offset: number) => {
    const nextRuleIds = [...selectedRuleIds];
    [nextRuleIds[index], nextRuleIds[index + offset]] = [nextRuleIds[index + offset], nextRuleIds[index]];
    form.setValue('ruleIds', nextRuleIds, { shouldDirty: true, shouldValidate: true });
  };
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
      <FormField
        control={form.control}
        name="ruleIds"
        render={() => (
          <FormItem>
            <FormLabel>Rules, in evaluation order</FormLabel>
            <div className="space-y-2">
              {selectedRuleIds.map((ruleId, index) => {
                const rule = rules.find((candidate) => candidate.id === ruleId);
                return (
                  <div key={ruleId} className="flex items-center gap-2 rounded border border-border bg-background/40 px-3 py-2">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{rule?.name ?? 'Unavailable rule'}</p>
                      {rule && <p className="truncate text-xs text-muted-foreground">{actionSummary(rule)}</p>}
                    </div>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      disabled={index === 0}
                      aria-label={`Move ${rule?.name ?? 'rule'} up`}
                      onClick={() => move(index, -1)}
                    >
                      <ArrowUp className="h-4 w-4" />
                    </Button>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      disabled={index === selectedRuleIds.length - 1}
                      aria-label={`Move ${rule?.name ?? 'rule'} down`}
                      onClick={() => move(index, 1)}
                    >
                      <ArrowDown className="h-4 w-4" />
                    </Button>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      aria-label={`Remove ${rule?.name ?? 'rule'}`}
                      onClick={() =>
                        form.setValue(
                          'ruleIds',
                          selectedRuleIds.filter((id) => id !== ruleId),
                          { shouldDirty: true, shouldValidate: true },
                        )
                      }
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                );
              })}
            </div>
            <Dropdown
              value=""
              onValueChange={(ruleId) => form.setValue('ruleIds', [...selectedRuleIds, ruleId], { shouldDirty: true, shouldValidate: true })}
              options={availableRules.map((rule) => ({ value: rule.id, label: rule.name }))}
              placeholder={availableRules.length ? 'Add a shared rule…' : 'All rules selected'}
              disabled={!availableRules.length}
              aria-label="Add rule"
            />
            <FormMessage />
            <p className="text-sm text-muted-foreground">Editing a shared rule updates every policy that uses it.</p>
          </FormItem>
        )}
      />
      <TextField form={form} name="priority" label="Priority (lower runs first)" numeric />
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
  rules,
}: {
  policy: PolicyOut | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (payload: PolicyCreate) => Promise<unknown>;
  pending: boolean;
  keys: InferenceKeyOut[];
  rules: RuleOut[];
}) {
  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={policy ? 'Edit policy' : 'Create policy'}
      description="Choose which keys this policy covers, then attach reusable rules in evaluation order."
      schema={policyFormSchema}
      defaultValues={policy ? policyForm(policy) : policyDefaults}
      onSubmit={(values) => onSubmit(policyPayload(values))}
      submitLabel="Save policy"
      pending={pending}
    >
      {(form) => <PolicyFields form={form} keys={keys} rules={rules} />}
    </FormDialog>
  );
}
