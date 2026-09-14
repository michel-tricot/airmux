import * as z from 'zod';
import type { WorkspaceOut } from '@workspace/api-client-react';
import { Dropdown, Input } from '@/components/ui/elements';
import { FormDialog } from '@/components/shared/form-dialog';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { ErrorState } from '@/components/shared/states';

const NO_WORKSPACE = '__none__';

const invitationSchema = z.object({
  email: z.string().email('Enter a valid email address'),
  orgRole: z.enum(['member', 'admin']),
  workspaceId: z.string(),
  workspaceRole: z.enum(['viewer', 'member', 'admin']),
});

export type InvitationValues = z.infer<typeof invitationSchema>;

export function InvitationDialog({
  open,
  onOpenChange,
  workspaces,
  workspacesError,
  onWorkspacesRetry,
  initialWorkspaceId,
  onSubmit,
  pending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaces: WorkspaceOut[];
  workspacesError?: unknown;
  onWorkspacesRetry?: () => void;
  initialWorkspaceId?: string;
  onSubmit: (values: InvitationValues) => Promise<unknown>;
  pending: boolean;
}) {
  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Invite a member"
      description="Create an email-bound link to share through a trusted channel."
      schema={invitationSchema}
      defaultValues={{ email: '', orgRole: 'member', workspaceId: initialWorkspaceId ?? NO_WORKSPACE, workspaceRole: 'member' }}
      onSubmit={onSubmit}
      submitLabel="Create invitation"
      pendingLabel="Creating..."
      pending={pending}
    >
      {(form) => {
        const workspaceSelected = form.watch('workspaceId') !== NO_WORKSPACE;
        return (
          <>
            {workspacesError && (
              <ErrorState
                error={workspacesError}
                message="Workspaces are unavailable. You can still create an organization-only invitation."
                onRetry={onWorkspacesRetry}
                className="p-0"
              />
            )}
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input type="email" autoComplete="off" placeholder="teammate@example.com" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="orgRole"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Organization role</FormLabel>
                  <FormControl>
                    <Dropdown
                      aria-label="Organization role"
                      value={field.value}
                      onValueChange={field.onChange}
                      options={[
                        { value: 'member', label: 'Member' },
                        { value: 'admin', label: 'Admin' },
                      ]}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="workspaceId"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Workspace</FormLabel>
                  <FormControl>
                    <Dropdown
                      aria-label="Workspace"
                      value={field.value}
                      onValueChange={field.onChange}
                      options={[
                        { value: NO_WORKSPACE, label: 'Organization only' },
                        ...workspaces.map((workspace) => ({ value: workspace.id, label: workspace.name })),
                      ]}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            {workspaceSelected && (
              <FormField
                control={form.control}
                name="workspaceRole"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Workspace role</FormLabel>
                    <FormControl>
                      <Dropdown
                        aria-label="Workspace role"
                        value={field.value}
                        onValueChange={field.onChange}
                        options={[
                          { value: 'viewer', label: 'Viewer' },
                          { value: 'member', label: 'Member' },
                          { value: 'admin', label: 'Admin' },
                        ]}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}
          </>
        );
      }}
    </FormDialog>
  );
}

export function invitationRequest(values: InvitationValues) {
  if (values.workspaceId === NO_WORKSPACE) {
    return { email: values.email, org_role: values.orgRole };
  }
  return {
    email: values.email,
    org_role: values.orgRole,
    workspace_id: values.workspaceId,
    workspace_role: values.workspaceRole,
  };
}
