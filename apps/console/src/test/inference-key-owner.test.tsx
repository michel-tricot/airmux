import type * as Api from '@workspace/api-client-react';
import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { createQueryClient } from '@/App';
import { InferenceKeyDialog } from '@/components/shared/inference-key-dialog';
import { ORG, paged, server } from './msw';

const workspaceRef = 'production';
const currentUser = { user_id: 'user-1', name: 'Dev', email: 'dev@example.com' };

it('defaults inference-key ownership to the current principal and offers only eligible service accounts', async () => {
  let submitted: Api.InferenceKeyIn | undefined;
  server.use(
    http.get(`/api/v1/organizations/${ORG.id}/workspaces/${workspaceRef}/inference-key-owners`, () =>
      paged<Api.InferenceKeyOwnerOut>([
        { ...currentUser, service_account: false },
        { user_id: 'service-1', name: 'Production App', email: 'production@app.invalid', service_account: true },
      ]),
    ),
    http.post(`/api/v1/organizations/${ORG.id}/workspaces/${workspaceRef}/inference-keys`, async ({ request }) => {
      submitted = (await request.json()) as Api.InferenceKeyIn;
      return HttpResponse.json<{ data: Api.InferenceKeyCreatedOut }>({ data: { id: 'key-1', token: 'shown-once' } });
    }),
  );
  const onCreated = vi.fn();
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={createQueryClient()}>
      <InferenceKeyDialog orgId={ORG.id} workspaceRef={workspaceRef} open onOpenChange={() => {}} onCreated={onCreated} currentUser={currentUser} />
    </QueryClientProvider>,
  );

  const dialog = screen.getByRole('dialog');
  const owner = within(dialog).getByRole('combobox', { name: 'Owner' });
  await waitFor(() => expect(owner).toHaveTextContent('Dev (you)'));
  await user.click(owner);
  await user.click(screen.getByRole('option', { name: 'Production App (service account)' }));
  await user.type(within(dialog).getByLabelText('Label'), 'production');
  await user.click(within(dialog).getByRole('button', { name: 'Generate' }));

  await waitFor(() => expect(submitted).toEqual({ label: 'production', user_id: 'service-1' }));
  expect(onCreated).toHaveBeenCalledWith('shown-once');
  expect(screen.queryByText(/another human/i)).not.toBeInTheDocument();
});
