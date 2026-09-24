import { useState } from 'react';
import { ArrowLeft, Pencil, Plus, Trash2 } from 'lucide-react';
import { useForm, useWatch, type Resolver, type UseFormReturn } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import type {
  InferenceKeyOut,
  PolicyCreate,
  PolicyOut,
  RuleDefinitionInput,
  TaxonomyOut,
  WorkspaceMemberCandidateOut,
} from '@workspace/api-client-react';
import { Button, CheckboxDropdown, Dropdown, Input, Modal, Switch } from '@/components/ui/elements';
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { policyDefaults, policyForm, policyFormSchema, policyPayload, type PolicyForm } from '@/features/policies/form';
import { RuleActionSummary, RuleMatchSummary } from '@/features/rules/presentation';
import { ruleType, type RuleKind } from '@/features/rules/types';
import { RuleFormContent } from './RuleEditor';
import { RuleTypeChoices } from './RuleTypePicker';

type PolicyEditorStep =
  | { kind: 'policy' }
  | { kind: 'choose_rule_type' }
  | { kind: 'create_rule'; ruleKind: RuleKind }
  | { kind: 'edit_rule'; index: number; rule: RuleDefinitionInput };

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
  users,
  onCreateRule,
  onEditRule,
}: {
  form: UseFormReturn<PolicyForm>;
  keys: InferenceKeyOut[];
  users: WorkspaceMemberCandidateOut[];
  onCreateRule: () => void;
  onEditRule: (index: number, rule: RuleDefinitionInput) => void;
}) {
  const targetKind = useWatch({ control: form.control, name: 'targetKind' });
  const rules = useWatch({ control: form.control, name: 'rules' });

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
        name="targetKind"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Applies to</FormLabel>
            <FormControl>
              <Dropdown
                aria-label="Applies to"
                value={field.value}
                onValueChange={field.onChange}
                options={[
                  { value: 'workspace', label: 'Workspace' },
                  { value: 'selected_users', label: 'Selected users' },
                  { value: 'selected_keys', label: 'Selected keys' },
                ]}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      {targetKind === 'workspace' && <p className="text-sm text-muted-foreground">Includes future inference keys and playground sessions.</p>}
      {targetKind === 'selected_users' && (
        <FormField
          control={form.control}
          name="userIds"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Users</FormLabel>
              <FormControl>
                <CheckboxDropdown
                  aria-label="Selected users"
                  label="Selected users"
                  emptyLabel="Select users"
                  values={field.value}
                  onValuesChange={field.onChange}
                  options={[
                    ...users.map((user) => ({
                      value: user.user_id,
                      label: `${user.name} (${user.service_account ? 'service account' : user.email})`,
                    })),
                    ...field.value
                      .filter((id) => !users.some((user) => user.user_id === id))
                      .map((id) => ({ value: id, label: `Unavailable user (${id})` })),
                  ]}
                />
              </FormControl>
              <FormMessage />
              <p className="text-sm text-muted-foreground">Applies to each principal's inference keys and playground sessions in this workspace.</p>
            </FormItem>
          )}
        />
      )}
      {targetKind === 'selected_keys' && (
        <FormField
          control={form.control}
          name="keyIds"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Keys</FormLabel>
              <FormControl>
                <CheckboxDropdown
                  aria-label="Selected keys"
                  label="Selected keys"
                  emptyLabel="Select keys"
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
        name="rules"
        render={() => (
          <FormItem>
            <div className="flex items-center justify-between gap-2">
              <FormLabel>Rules</FormLabel>
              <Button type="button" variant="outline" size="sm" onClick={onCreateRule}>
                <Plus className="h-4 w-4" />
                Add rule
              </Button>
            </div>
            <div className="space-y-2">
              {rules.map((rule, index) => (
                <div
                  key={`${index}:${JSON.stringify(rule)}`}
                  className="flex min-h-16 items-center gap-2 rounded border border-border bg-background/40 px-3 py-2"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium">
                      <RuleActionSummary definition={rule} />
                    </div>
                    <div className="text-xs text-muted-foreground">
                      When: <RuleMatchSummary definition={rule} />
                    </div>
                  </div>
                  <Button type="button" size="icon" variant="ghost" aria-label={`Edit rule ${index + 1}`} onClick={() => onEditRule(index, rule)}>
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    aria-label={`Remove rule ${index + 1}`}
                    onClick={() =>
                      form.setValue(
                        'rules',
                        rules.filter((_, ruleIndex) => ruleIndex !== index),
                        { shouldDirty: true, shouldValidate: true },
                      )
                    }
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
              {rules.length === 0 && (
                <p className="rounded border border-dashed border-border p-4 text-sm text-muted-foreground">Add at least one rule.</p>
              )}
            </div>
            <FormMessage />
            <p className="text-sm text-muted-foreground">Rule changes are saved only when you save this policy.</p>
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
  users,
  catalog,
}: {
  policy: PolicyOut | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (payload: PolicyCreate) => Promise<unknown>;
  pending: boolean;
  keys: InferenceKeyOut[];
  users: WorkspaceMemberCandidateOut[];
  catalog: TaxonomyOut;
}) {
  const defaultValues = policy ? policyForm(policy) : policyDefaults;
  const form = useForm<PolicyForm>({
    resolver: zodResolver(policyFormSchema) as Resolver<PolicyForm>,
    defaultValues,
  });
  const [step, setStep] = useState<PolicyEditorStep>({ kind: 'policy' });
  const rules = useWatch({ control: form.control, name: 'rules' });
  const hasFallback = rules.some((rule) => rule.action.kind === 'fallback');

  const resetEditor = () => {
    form.reset(defaultValues);
    setStep({ kind: 'policy' });
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
  const createRule = async (rule: RuleDefinitionInput) => {
    form.setValue('rules', [...form.getValues('rules'), rule], { shouldDirty: true, shouldValidate: true });
    setStep({ kind: 'policy' });
  };
  const updateRule = async (index: number, rule: RuleDefinitionInput) => {
    form.setValue(
      'rules',
      form.getValues('rules').map((current, ruleIndex) => (ruleIndex === index ? rule : current)),
      { shouldDirty: true, shouldValidate: true },
    );
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
          ? `Add ${ruleType(step.ruleKind).formName}`
          : `Edit ${ruleType(step.rule.action.kind).formName}`;
  const description =
    step.kind === 'policy'
      ? 'Choose who this policy covers and define its restrictions and fallbacks.'
      : step.kind === 'choose_rule_type'
        ? 'Start with the control you want to apply.'
        : step.kind === 'create_rule'
          ? ruleType(step.ruleKind).description
          : ruleType(step.rule.action.kind).description;

  return (
    <Modal open={open} onOpenChange={handleOpenChange} title={title} description={description} contentClassName="sm:max-w-xl">
      {step.kind === 'policy' && (
        <Form {...form}>
          <form onSubmit={submitPolicy} noValidate className="space-y-4">
            <PolicyFields
              form={form}
              keys={keys}
              users={users}
              onCreateRule={() => setStep({ kind: 'choose_rule_type' })}
              onEditRule={(index, rule) => setStep({ kind: 'edit_rule', index, rule })}
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
          <RuleTypeChoices fallbackDisabled={hasFallback} onSelect={(ruleKind) => setStep({ kind: 'create_rule', ruleKind })} />
          <Button type="button" variant="outline" onClick={() => setStep({ kind: 'policy' })}>
            <ArrowLeft className="h-4 w-4" />
            Back to policy
          </Button>
        </div>
      )}
      {step.kind === 'create_rule' && (
        <RuleFormContent
          rule={null}
          kind={step.ruleKind}
          catalog={catalog}
          pending={false}
          submitLabel="Add rule"
          onSubmit={createRule}
          onBack={() => setStep({ kind: 'policy' })}
        />
      )}
      {step.kind === 'edit_rule' && (
        <RuleFormContent
          rule={step.rule}
          kind={step.rule.action.kind}
          catalog={catalog}
          pending={false}
          submitLabel="Update rule"
          onSubmit={(rule) => updateRule(step.index, rule)}
          onBack={() => setStep({ kind: 'policy' })}
        />
      )}
    </Modal>
  );
}
