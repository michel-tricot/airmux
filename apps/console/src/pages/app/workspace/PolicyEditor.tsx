import { useState } from 'react';
import { ArrowLeft, Pencil, Plus, Trash2 } from 'lucide-react';
import { useForm, type Resolver, type UseFormReturn } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import type { InferenceKeyOut, PolicyCreate, PolicyOut, RuleCreate, RuleOut, TaxonomyOut } from '@workspace/api-client-react';
import { SearchPicker } from '@/components/shared/search-picker';
import { Alert, AlertDescription, Badge, Button, CheckboxDropdown, Input, Modal, Switch } from '@/components/ui/elements';
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { policyDefaults, policyForm, policyFormSchema, policyPayload, type PolicyForm } from '@/features/policies/form';
import { RuleActionSummary } from '@/features/rules/presentation';
import { ruleType, type RuleKind } from '@/features/rules/types';
import { RuleFormContent } from './RuleEditor';
import { RuleTypeChoices } from './RuleTypePicker';

interface PolicyRuleComposer {
  catalog: TaxonomyOut;
  usageByRuleId: ReadonlyMap<string, number> | null;
  createPending: boolean;
  updatePending: boolean;
  create: (payload: RuleCreate) => Promise<RuleOut>;
  update: (rule: RuleOut, payload: RuleCreate) => Promise<RuleOut>;
}

type PolicyEditorStep =
  { kind: 'policy' } | { kind: 'choose_rule_type' } | { kind: 'create_rule'; ruleKind: RuleKind } | { kind: 'edit_rule'; rule: RuleOut };

function ruleUsageLabel(usageByRuleId: ReadonlyMap<string, number> | null, ruleId: string) {
  if (usageByRuleId === null) return 'Policy usage is unavailable';
  const usage = usageByRuleId.get(ruleId) ?? 0;
  return `Used by ${usage} ${usage === 1 ? 'policy' : 'policies'}`;
}

function TextField({ form, label }: { form: UseFormReturn<PolicyForm>; label: string }) {
  return (
    <FormField
      control={form.control}
      name="name"
      render={({ field }) => (
        <FormItem>
          <FormLabel>{label}</FormLabel>
          <FormControl>
            <Input {...field} />
          </FormControl>
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

function PolicyFields({
  form,
  keys,
  rules,
  newRuleIds,
  ruleNotice,
  canComposeRules,
  onCreateRule,
  onEditRule,
}: {
  form: UseFormReturn<PolicyForm>;
  keys: InferenceKeyOut[];
  rules: RuleOut[];
  newRuleIds: readonly string[];
  ruleNotice: string | null;
  canComposeRules: boolean;
  onCreateRule: () => void;
  onEditRule: (rule: RuleOut) => void;
}) {
  const selectedRuleIds = form.watch('ruleIds');
  const selectedRules = selectedRuleIds
    .map((ruleId) => ({ ruleId, rule: rules.find((candidate) => candidate.id === ruleId) }))
    .sort((left, right) => (left.rule?.name ?? '').localeCompare(right.rule?.name ?? ''));
  const hasFallback = selectedRules.some(({ rule }) => rule?.definition.action.kind === 'fallback');
  const availableRules = rules.filter((rule) => !selectedRuleIds.includes(rule.id) && (!hasFallback || rule.definition.action.kind !== 'fallback'));
  const attachRule = (ruleId: string) => form.setValue('ruleIds', [...selectedRuleIds, ruleId], { shouldDirty: true, shouldValidate: true });

  return (
    <>
      <TextField form={form} label="Policy name" />
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
        name="keyIds"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Applies to</FormLabel>
            <FormControl>
              <CheckboxDropdown
                aria-label="Applies to"
                label="Selected keys"
                allLabel="All keys"
                values={field.value}
                onValuesChange={field.onChange}
                options={keys.map((key) => ({ value: key.id, label: `${key.label}${key.revoked ? ' (revoked)' : ''}` }))}
              />
            </FormControl>
            <FormMessage />
            {field.value.length === 0 && <p className="text-sm text-muted-foreground">Includes future inference keys and playground sessions.</p>}
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="ruleIds"
        render={() => (
          <FormItem>
            <FormLabel>Rules</FormLabel>
            {ruleNotice && (
              <Alert>
                <AlertDescription>{ruleNotice}</AlertDescription>
              </Alert>
            )}
            <div className="space-y-2">
              {selectedRules.map(({ ruleId, rule }) => (
                <div key={ruleId} className="flex min-h-14 items-center gap-2 rounded border border-border bg-background/40 px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm font-medium">{rule?.name ?? 'Unavailable rule'}</p>
                      {newRuleIds.includes(ruleId) && <Badge variant="success">New</Badge>}
                    </div>
                    {rule && (
                      <div className="text-xs text-muted-foreground">
                        <RuleActionSummary rule={rule} />
                      </div>
                    )}
                  </div>
                  {rule && (
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      aria-label={`Edit ${rule.name}`}
                      disabled={!canComposeRules}
                      onClick={() => onEditRule(rule)}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                  )}
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
              ))}
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <SearchPicker
                value=""
                onValueChange={attachRule}
                options={availableRules.map((rule) => ({
                  value: rule.id,
                  searchText: rule.name,
                  label: (
                    <span className="flex min-w-0 flex-col items-start">
                      <span className="truncate text-sm font-medium">{rule.name}</span>
                      <span className="text-xs text-muted-foreground">
                        <RuleActionSummary rule={rule} />
                      </span>
                    </span>
                  ),
                }))}
                placeholder={availableRules.length ? 'Search or add an existing rule…' : 'All available rules selected'}
                disabled={!availableRules.length}
                aria-label="Add existing rule"
                title="Add existing rule"
                description="Search reusable Rules from this workspace."
                searchLabel="Search shared rules"
                searchPlaceholder="Search rules..."
                emptyMessage="No matching rules"
                className="sm:flex-1"
              />
              <Button type="button" variant="outline" disabled={!canComposeRules} onClick={onCreateRule}>
                <Plus className="mr-1 h-4 w-4" />
                Create rule
              </Button>
            </div>
            <FormMessage />
            <p className="text-sm text-muted-foreground">Rules are shared. Editing one updates every policy that uses it.</p>
          </FormItem>
        )}
      />
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
  ruleComposer,
}: {
  policy: PolicyOut | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (payload: PolicyCreate) => Promise<unknown>;
  pending: boolean;
  keys: InferenceKeyOut[];
  rules: RuleOut[];
  ruleComposer?: PolicyRuleComposer;
}) {
  const defaultValues = policy ? policyForm(policy) : policyDefaults;
  const form = useForm<PolicyForm>({
    resolver: zodResolver(policyFormSchema) as Resolver<PolicyForm>,
    defaultValues,
  });
  const [step, setStep] = useState<PolicyEditorStep>({ kind: 'policy' });
  const [ruleOverrides, setRuleOverrides] = useState<RuleOut[]>([]);
  const [newRuleIds, setNewRuleIds] = useState<string[]>([]);
  const [ruleNotice, setRuleNotice] = useState<string | null>(null);
  const rulesById = new Map([...rules, ...ruleOverrides].map((rule) => [rule.id, rule]));
  const visibleRules = Array.from(rulesById.values());

  const resetEditor = () => {
    form.reset(defaultValues);
    setStep({ kind: 'policy' });
    setRuleOverrides([]);
    setNewRuleIds([]);
    setRuleNotice(null);
  };
  const closeEditor = () => {
    resetEditor();
    onOpenChange(false);
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen && step.kind !== 'policy') {
      setStep({ kind: 'policy' });
      return;
    }
    if (nextOpen) onOpenChange(true);
    else closeEditor();
  };
  const submitPolicy = form.handleSubmit(async (values) => {
    try {
      await onSubmit(policyPayload(values));
      closeEditor();
    } catch {
      return;
    }
  });
  const storeRule = (rule: RuleOut) => setRuleOverrides((current) => [...current.filter((candidate) => candidate.id !== rule.id), rule]);
  const createRule = async (payload: RuleCreate) => {
    if (!ruleComposer) return;
    const rule = await ruleComposer.create(payload);
    storeRule(rule);
    const selectedRuleIds = form.getValues('ruleIds');
    form.setValue('ruleIds', [...selectedRuleIds, rule.id], { shouldDirty: true, shouldValidate: true });
    setNewRuleIds((current) => [...current, rule.id]);
    setRuleNotice(`${rule.name} was created in the Rule library and added to this policy.`);
    setStep({ kind: 'policy' });
  };
  const updateRule = async (rule: RuleOut, payload: RuleCreate) => {
    if (!ruleComposer) return;
    const updatedRule = await ruleComposer.update(rule, payload);
    storeRule(updatedRule);
    setRuleNotice(`${updatedRule.name} was updated everywhere it is used.`);
    setStep({ kind: 'policy' });
  };

  const title =
    step.kind === 'policy'
      ? policy
        ? 'Edit policy'
        : 'Create policy'
      : step.kind === 'choose_rule_type'
        ? 'Choose a rule type'
        : step.kind === 'create_rule'
          ? `Create and add ${ruleType(step.ruleKind).formName}`
          : `Edit ${ruleType(step.rule.definition.action.kind).formName}`;
  const description =
    step.kind === 'policy'
      ? 'Choose which keys this policy covers, then attach reusable rules.'
      : step.kind === 'choose_rule_type'
        ? 'Start with the control you want to apply. Each rule type has its own focused form.'
        : step.kind === 'create_rule'
          ? `${ruleType(step.ruleKind).description} This Rule will be shared across policies.`
          : `${ruleType(step.rule.definition.action.kind).description} This Rule is shared across policies.`;
  const editingUsage = step.kind === 'edit_rule' && ruleComposer ? ruleUsageLabel(ruleComposer.usageByRuleId, step.rule.id) : null;

  return (
    <Modal open={open} onOpenChange={handleOpenChange} title={title} description={description} contentClassName="sm:max-w-xl">
      {step.kind === 'policy' && (
        <Form {...form}>
          <form onSubmit={submitPolicy} noValidate className="space-y-4">
            <PolicyFields
              form={form}
              keys={keys}
              rules={visibleRules}
              newRuleIds={newRuleIds}
              ruleNotice={ruleNotice}
              canComposeRules={ruleComposer !== undefined}
              onCreateRule={() => setStep({ kind: 'choose_rule_type' })}
              onEditRule={(rule) => setStep({ kind: 'edit_rule', rule })}
            />
            <div className="flex justify-end gap-2 pt-4">
              <Button type="button" variant="outline" onClick={closeEditor}>
                Cancel
              </Button>
              <Button type="submit" disabled={pending}>
                Save policy
              </Button>
            </div>
          </form>
        </Form>
      )}
      {step.kind === 'choose_rule_type' && (
        <div className="space-y-4">
          <RuleTypeChoices onSelect={(ruleKind) => setStep({ kind: 'create_rule', ruleKind })} />
          <Button type="button" variant="outline" onClick={() => setStep({ kind: 'policy' })}>
            <ArrowLeft className="mr-1 h-4 w-4" />
            Back to policy
          </Button>
        </div>
      )}
      {step.kind === 'create_rule' && ruleComposer && (
        <RuleFormContent
          rule={null}
          kind={step.ruleKind}
          catalog={ruleComposer.catalog}
          pending={ruleComposer.createPending}
          submitLabel="Create and add rule"
          onSubmit={createRule}
          onBack={() => setStep({ kind: 'policy' })}
          intro={
            <Alert>
              <AlertDescription>
                This Rule is saved to the Rule library immediately and can be reused by other Policies. It remains there if you cancel this Policy.
              </AlertDescription>
            </Alert>
          }
        />
      )}
      {step.kind === 'edit_rule' && ruleComposer && (
        <RuleFormContent
          rule={step.rule}
          kind={step.rule.definition.action.kind}
          catalog={ruleComposer.catalog}
          pending={ruleComposer.updatePending}
          submitLabel="Save rule"
          onSubmit={(payload) => updateRule(step.rule, payload)}
          onBack={() => setStep({ kind: 'policy' })}
          intro={
            <Alert>
              <AlertDescription className="space-y-1">
                <p className="font-medium">{editingUsage}</p>
                <p>Saving this Rule updates every policy that uses it.</p>
              </AlertDescription>
            </Alert>
          }
        />
      )}
    </Modal>
  );
}
