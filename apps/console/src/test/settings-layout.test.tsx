import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { SettingsLayout } from '@/components/shared/settings-layout';
import { TabsContent } from '@/components/ui/elements';

it('switches settings categories with the keyboard and recovers when a category is removed', async () => {
  const user = userEvent.setup();
  const content = (
    <>
      <TabsContent value="general">General settings</TabsContent>
      <TabsContent value="members">Member settings</TabsContent>
    </>
  );
  const view = render(
    <SettingsLayout
      header={<h1>Settings</h1>}
      categories={[
        { id: 'general', label: 'General' },
        { id: 'members', label: 'Members' },
      ]}
    >
      {content}
    </SettingsLayout>,
  );
  expect(screen.getByRole('tablist', { name: 'Settings categories' })).toHaveAttribute('aria-orientation', 'vertical');
  expect(screen.getByRole('tabpanel')).toHaveTextContent('General settings');
  await user.click(screen.getByRole('tab', { name: 'General' }));
  await user.keyboard('{ArrowDown}');
  expect(screen.getByRole('tabpanel')).toHaveTextContent('Member settings');
  view.rerender(
    <SettingsLayout header={<h1>Settings</h1>} categories={[{ id: 'general', label: 'General' }]}>
      {content}
    </SettingsLayout>,
  );
  expect(screen.getByRole('tabpanel')).toHaveTextContent('General settings');
});
