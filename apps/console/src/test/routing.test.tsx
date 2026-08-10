import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import App from '@/App';
import { ORG, WORKSPACES } from './msw';

// The console keys the org selection off localStorage; the tests sign in as a
// member of ORG so the app section renders instead of the org picker.
beforeEach(() => {
  localStorage.setItem('airllm_org_id', ORG.id);
});

function renderAt(path: string) {
  window.history.replaceState(null, '', path);
  return render(<App />);
}

const WS = WORKSPACES[0];

// Every sidebar section has its own URL. Each case visits the deep link
// directly and asserts the section's page renders — this catches route
// shadowing if the wouter routes are ever reordered (e.g. the bare
// `/org/workspaces/:workspaceRef` route capturing `/keys`).
const SECTIONS: Array<{ suffix: string; heading: string | RegExp }> = [
  { suffix: '', heading: WS.name }, // Overview shows the workspace name
  { suffix: '/keys', heading: 'API Keys' },
  { suffix: '/byok', heading: 'Provider Keys' },
  { suffix: '/routing', heading: 'Routing' },
  { suffix: '/policies', heading: 'Policies' },
  { suffix: '/settings', heading: 'Workspace Settings' },
];

describe('workspace section deep links', () => {
  it.each(SECTIONS)('renders the right page for /org/workspaces/:id$suffix', async ({ suffix, heading }) => {
    renderAt(`/org/workspaces/${WS.slug}${suffix}`);
    expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeInTheDocument();
    // The workspace dropdown reflects the workspace from the URL.
    expect(await screen.findByRole('combobox', { name: 'Workspace' })).toHaveTextContent(WS.name);
  });

  it('keeps /org/settings out of the workspace routes', async () => {
    renderAt('/org/settings');
    // /org/settings must not be captured by the workspace routes.
    await waitFor(() => {
      expect(window.location.pathname).toBe('/org/settings');
    });
    expect(await screen.findByRole('combobox', { name: 'Workspace' })).toBeInTheDocument();
    expect(screen.queryByText('API Keys', { selector: 'h1' })).not.toBeInTheDocument();
  });
});

describe('default workspace selection', () => {
  it('redirects /org to the first workspace when none was selected before', async () => {
    renderAt('/org');
    await waitFor(() => {
      expect(window.location.pathname).toBe(`/org/workspaces/${WORKSPACES[0].slug}`);
    });
    expect(await screen.findByRole('heading', { level: 1, name: WORKSPACES[0].name })).toBeInTheDocument();
  });

  it('redirects /org to the last-selected workspace', async () => {
    localStorage.setItem(`airllm_last_ws_${ORG.id}`, WORKSPACES[1].slug);
    renderAt('/org');
    await waitFor(() => {
      expect(window.location.pathname).toBe(`/org/workspaces/${WORKSPACES[1].slug}`);
    });
    expect(await screen.findByRole('heading', { level: 1, name: WORKSPACES[1].name })).toBeInTheDocument();
  });

  it('remembers the workspace visited via a deep link', async () => {
    renderAt(`/org/workspaces/${WORKSPACES[1].slug}/keys`);
    await screen.findByRole('heading', { level: 1, name: 'API Keys' });
    await waitFor(() => {
      expect(localStorage.getItem(`airllm_last_ws_${ORG.id}`)).toBe(WORKSPACES[1].slug);
    });
  });
});

describe('workspace switching keeps the active section', () => {
  it.each(SECTIONS)('stays on $suffix when switching workspaces', async ({ suffix, heading }) => {
    const user = userEvent.setup();
    renderAt(`/org/workspaces/${WORKSPACES[0].slug}${suffix}`);
    await screen.findByRole('heading', { level: 1, name: heading });

    // The picker is a Radix Select: open the trigger, then click the option.
    const dropdown = await screen.findByRole('combobox', { name: 'Workspace' });
    await user.click(dropdown);
    await user.click(await screen.findByRole('option', { name: WORKSPACES[1].name }));

    // URL keeps the section suffix, only the workspace id changes.
    await waitFor(() => {
      expect(window.location.pathname).toBe(`/org/workspaces/${WORKSPACES[1].slug}${suffix}`);
    });

    // The section's page renders for the new workspace.
    const expectedHeading = suffix === '' ? WORKSPACES[1].name : heading;
    expect(await screen.findByRole('heading', { level: 1, name: expectedHeading })).toBeInTheDocument();

    // The sidebar marks that section as active for the new workspace.
    const active = document.querySelector(`a[href="/org/workspaces/${WORKSPACES[1].slug}${suffix}"]`);
    expect(active).not.toBeNull();
    expect(active).toHaveClass('text-primary');
    expect(active).toHaveTextContent(sectionLabel(suffix));
  });
});

describe('workspace URL compatibility', () => {
  it('redirects a legacy UUID URL to the workspace slug', async () => {
    renderAt(`/org/workspaces/${WORKSPACES[0].id}`);
    expect(await screen.findByRole('heading', { level: 1, name: WORKSPACES[0].name })).toBeInTheDocument();
    await waitFor(() => {
      expect(window.location.pathname).toBe(`/org/workspaces/${WORKSPACES[0].slug}`);
    });
  });
});

function sectionLabel(suffix: string): string {
  return {
    '': 'Overview',
    '/keys': 'API Keys',
    '/byok': 'BYOK',
    '/routing': 'Routing',
    '/policies': 'Policies',
    '/settings': 'Settings',
  }[suffix]!;
}
