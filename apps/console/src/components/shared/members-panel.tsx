import { useState, type ReactNode } from 'react';
import * as z from 'zod';
import { Card, Button, Dropdown, ConfirmButton } from '@/components/ui/elements';
import { Plus, UserMinus } from 'lucide-react';
import { DataTable, type Column } from '@/components/shared/data-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';

interface MemberRow {
  user_id: string;
  name?: string | null;
  email?: string | null;
}

const addMemberSchema = z.object({ userId: z.string().min(1, 'Select a user') });

interface MembersPanelProps<T extends MemberRow> {
  heading: ReactNode;
  members: T[] | undefined;
  isLoading?: boolean;
  isError?: boolean;
  error?: unknown;
  onRetry?: () => void;
  emptyText: string;
  renderName?: (member: T) => ReactNode;
  renderEmail?: (member: T) => ReactNode;
  add?: {
    candidates: Array<{ value: string; label: string }>;
    dialogTitle: string;
    dialogDescription?: string;
    placeholder: string;
    onAdd: (userId: string) => Promise<unknown>;
    pending: boolean;
  };
  remove?: {
    title: (member: T) => string;
    description: string;
    onRemove: (member: T) => Promise<unknown>;
    pending: boolean;
  };
}

export function MembersPanel<T extends MemberRow>({
  heading,
  members,
  isLoading,
  isError,
  error,
  onRetry,
  emptyText,
  renderName,
  renderEmail,
  add,
  remove,
}: MembersPanelProps<T>) {
  const [addOpen, setAddOpen] = useState(false);

  const columns: Array<Column<T>> = [
    {
      key: 'name',
      header: 'User',
      cellClassName: 'font-medium',
      cell: (member) => (renderName ? renderName(member) : (member.name ?? 'Member')),
    },
    {
      key: 'email',
      header: 'Email',
      cellClassName: 'text-muted-foreground',
      cell: (member) => (renderEmail ? renderEmail(member) : (member.email ?? member.user_id)),
    },
  ];
  if (remove) {
    columns.push({
      key: 'actions',
      header: 'Actions',
      headClassName: 'text-right',
      cellClassName: 'text-right',
      cell: (member) => (
        <ConfirmButton
          title={remove.title(member)}
          description={remove.description}
          confirmLabel="Remove member"
          pending={remove.pending}
          aria-label="Remove member"
          onConfirm={() => remove.onRemove(member)}
        >
          <UserMinus className="w-4 h-4" />
        </ConfirmButton>
      ),
    });
  }

  return (
    <>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold">{heading}</h2>
        {add && (
          <Button onClick={() => setAddOpen(true)} size="sm" disabled={add.pending || add.candidates.length === 0}>
            <Plus className="w-4 h-4 mr-1" /> Add Member
          </Button>
        )}
      </div>
      <Card>
        <DataTable
          columns={columns}
          rows={members}
          rowKey={(member) => member.user_id}
          isLoading={isLoading}
          isError={isError}
          error={error}
          resource="members"
          onRetry={onRetry}
          empty={emptyText}
        />
      </Card>

      {add && (
        <FormDialog
          open={addOpen}
          onOpenChange={setAddOpen}
          title={add.dialogTitle}
          description={add.dialogDescription}
          schema={addMemberSchema}
          defaultValues={{ userId: '' }}
          onSubmit={(values) => add.onAdd(values.userId)}
          submitLabel="Add"
          pending={add.pending}
        >
          {(form) => (
            <FormField
              control={form.control}
              name="userId"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>User</FormLabel>
                  <FormControl>
                    <Dropdown
                      aria-label="User"
                      value={field.value}
                      onValueChange={field.onChange}
                      placeholder={add.placeholder}
                      options={add.candidates}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          )}
        </FormDialog>
      )}
    </>
  );
}
