import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import App from '@/App';
import { ORG, WORKSPACES } from './msw';

beforeEach(() => {
  window.localStorage.setItem('airmux_org_id', ORG.id);
});

function renderAt(path: string) {
  window.history.replaceState(null, '', path);
  return render(<App />);
}

const WS = WORKSPACES[0];

const SECTIONS: Array<{ suffix: string; heading: string | RegExp }> = [
  { suffix: '', heading: WS.name },
  { suffix: '/requests', heading: `${WS.name} Requests` },
  { suffix: '/inference-keys', heading: 'Inference Keys' },
  { suffix: '/byok', heading: 'Provider Keys' },
  { suffix: '/settings', heading: 'Workspace Settings' },
];

describe('workspace section deep links', () => {
  it.each(SECTIONS)('renders the right page for /org/workspaces/:id$suffix', async ({ suffix, heading }) => {
    renderAt(`/org/workspaces/${WS.slug}${suffix}`);
    expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeInTheDocument();
    expect(await screen.findByRole('combobox', { name: 'Workspace' })).toHaveTextContent(WS.name);
  });

  it('keeps /org/settings out of the workspace routes', async () => {
    renderAt('/org/settings');
    await waitFor(() => {
      expect(window.location.pathname).toBe('/org/settings');
    });
    expect(await screen.findByRole('heading', { level: 1, name: 'Organization Settings' })).toBeInTheDocument();
    expect(await screen.findByRole('combobox', { name: 'Workspace' })).toBeInTheDocument();
    expect(screen.queryByText('Inference Keys', { selector: 'h1' })).not.toBeInTheDocument();
  });
});

describe('organization section deep links', () => {
  it('renders models outside the workspace routes', async () => {
    renderAt('/org/models');
    expect(await screen.findByRole('heading', { level: 1, name: 'Models' })).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Models' })).toHaveAttribute('aria-current', 'page');
    expect(screen.queryByRole('combobox', { name: 'Workspace' })).toBeInTheDocument();
  });

  it('selects all workspaces while navigating organization pages', async () => {
    const user = userEvent.setup();
    renderAt(`/org/workspaces/${WS.slug}`);
    await screen.findByRole('heading', { level: 1, name: WS.name });
    expect(screen.getByRole('combobox', { name: 'Workspace' })).toHaveTextContent(WS.name);

    await user.click(screen.getByRole('link', { name: 'Models' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Models' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Workspace' })).toHaveTextContent('All workspaces');

    await user.click(screen.getAllByRole('link', { name: 'Settings' }).find((link) => link.getAttribute('href') === '/org/settings')!);
    expect(await screen.findByRole('heading', { level: 1, name: 'Organization Settings' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Workspace' })).toHaveTextContent('All workspaces');
  });
});

describe('default workspace selection', () => {
  it('keeps /org on the all-workspaces overview when none was selected before', async () => {
    renderAt('/org');
    await waitFor(() => {
      expect(window.location.pathname).toBe('/org');
    });
    expect(await screen.findByRole('heading', { level: 1, name: 'Organization Overview' })).toBeInTheDocument();
    expect(await screen.findByRole('combobox', { name: 'Workspace' })).toHaveTextContent('All workspaces');
  });

  it('keeps the last concrete workspace without redirecting the organization overview', async () => {
    window.localStorage.setItem(`airmux_last_ws_${ORG.id}`, WORKSPACES[1].slug);
    renderAt('/org');
    await waitFor(() => {
      expect(window.location.pathname).toBe('/org');
    });
    expect(window.localStorage.getItem(`airmux_last_ws_${ORG.id}`)).toBe(WORKSPACES[1].slug);
    expect(await screen.findByRole('combobox', { name: 'Workspace' })).toHaveTextContent('All workspaces');
  });

  it('remembers the workspace visited via a deep link', async () => {
    renderAt(`/org/workspaces/${WORKSPACES[1].slug}/inference-keys`);
    await screen.findByRole('heading', { level: 1, name: 'Inference Keys' });
    await waitFor(() => {
      expect(window.localStorage.getItem(`airmux_last_ws_${ORG.id}`)).toBe(WORKSPACES[1].slug);
    });
  });

  it('navigates explicitly to all workspaces and preserves the last concrete workspace', async () => {
    const user = userEvent.setup();
    renderAt(`/org/workspaces/${WS.slug}`);
    await screen.findByRole('heading', { level: 1, name: WS.name });
    await user.click(screen.getByRole('combobox', { name: 'Workspace' }));
    await user.click(await screen.findByRole('option', { name: 'All workspaces' }));

    await waitFor(() => expect(window.location.pathname).toBe('/org'));
    expect(await screen.findByRole('heading', { level: 1, name: 'Organization Overview' })).toBeInTheDocument();
    expect(window.localStorage.getItem(`airmux_last_ws_${ORG.id}`)).toBe(WS.slug);
  });
});

describe('workspace switching keeps the active section', () => {
  it.each(SECTIONS)('stays on $suffix when switching workspaces', async ({ suffix, heading }) => {
    const user = userEvent.setup();
    renderAt(`/org/workspaces/${WORKSPACES[0].slug}${suffix}`);
    await screen.findByRole('heading', { level: 1, name: heading });

    const dropdown = await screen.findByRole('combobox', { name: 'Workspace' });
    await user.click(dropdown);
    await user.click(await screen.findByRole('option', { name: WORKSPACES[1].name }));

    await waitFor(() => {
      expect(window.location.pathname).toBe(`/org/workspaces/${WORKSPACES[1].slug}${suffix}`);
    });

    const expectedHeading = suffix === '' ? WORKSPACES[1].name : suffix === '/requests' ? `${WORKSPACES[1].name} Requests` : heading;
    expect(await screen.findByRole('heading', { level: 1, name: expectedHeading })).toBeInTheDocument();

    const active = document.querySelector(`a[href="/org/workspaces/${WORKSPACES[1].slug}${suffix}"]`);
    expect(active).not.toBeNull();
    expect(active).toHaveAttribute('aria-current', 'page');
    expect(active).toHaveTextContent(sectionLabel(suffix));
  });

  it('preserves request filters while dropping scope-invalid values', async () => {
    const user = userEvent.setup();
    renderAt('/org/requests?range=30d&timezone=UTC&workspace=ws-1&provider=openai&as_of=org-snapshot');
    await screen.findByRole('heading', { level: 1, name: 'Organization Requests' });

    await user.click(screen.getByRole('combobox', { name: 'Workspace' }));
    await user.click(await screen.findByRole('option', { name: WORKSPACES[0].name }));

    await waitFor(() => expect(window.location.pathname).toBe(`/org/workspaces/${WORKSPACES[0].slug}/requests`));
    let search = new URLSearchParams(window.location.search);
    expect(search.get('range')).toBe('30d');
    expect(search.get('timezone')).toBe('UTC');
    expect(search.get('provider')).toBe('openai');
    expect(search.has('workspace')).toBe(false);
    expect(search.has('request')).toBe(false);
    expect(search.has('as_of')).toBe(false);

    await user.click(screen.getByRole('combobox', { name: 'Workspace' }));
    await user.click(await screen.findByRole('option', { name: 'All workspaces' }));

    await waitFor(() => expect(window.location.pathname).toBe('/org/requests'));
    search = new URLSearchParams(window.location.search);
    expect(search.get('range')).toBe('30d');
    expect(search.get('provider')).toBe('openai');
  });
});

describe('workspace route state', () => {
  it('resets unsaved settings when switching workspaces', async () => {
    const user = userEvent.setup();
    renderAt(`/org/workspaces/${WORKSPACES[0].slug}/settings`);

    const name = await screen.findByLabelText('Workspace name');
    await user.clear(name);
    await user.type(name, 'Unsaved production name');

    await user.click(screen.getByRole('combobox', { name: 'Workspace' }));
    await user.click(await screen.findByRole('option', { name: WORKSPACES[1].name }));

    await waitFor(() => {
      expect(window.location.pathname).toBe(`/org/workspaces/${WORKSPACES[1].slug}/settings`);
    });
    expect(await screen.findByLabelText('Workspace name')).toHaveValue(WORKSPACES[1].name);
  });
});

function sectionLabel(suffix: string): string {
  return {
    '': 'Overview',
    '/requests': 'Requests',
    '/inference-keys': 'Inference Keys',
    '/byok': 'BYOK',
    '/settings': 'Settings',
  }[suffix]!;
}
