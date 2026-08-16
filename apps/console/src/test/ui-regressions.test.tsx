import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '@/App';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { Badge, Button, ConfirmButton } from '@/components/ui/elements';
import { ORG, WORKSPACES, server } from './msw';
import { Link } from 'wouter';

const now = '2026-01-01T00:00:00Z';
const themeCss = readFileSync(path.resolve(process.cwd(), 'src/index.css'), 'utf8');

function taxonomyProvider(id: string, name: string, icon: string | null = null) {
  return {
    id,
    name,
    kind: 'openai_compatible',
    base_url: `https://${name}.example/v1`,
    icon,
    param_aliases: {},
    accepted_params: null,
    params_closed: false,
    created_at: now,
    updated_at: now,
    deleted_at: null,
  };
}

beforeEach(() => {
  window.localStorage.setItem('airllm_org_id', ORG.id);
});

function themeValue(name: string) {
  return themeCss.match(new RegExp(`(?:^|[;{])\\s*${name}:\\s*([^;]+);`, 'm'))?.[1].trim();
}

describe('console theme', () => {
  it('keeps the violet accent across global and sidebar semantics', () => {
    expect(themeValue('--ring')).toBe('244 100% 68%');
    expect(themeValue('--primary')).toBe('244 100% 68%');
    expect(themeValue('--primary-foreground')).toBe('0 0% 100%');
    expect(themeValue('--sidebar-primary')).toBe('244 100% 68%');
    expect(themeValue('--sidebar-primary-foreground')).toBe('0 0% 100%');
    expect(themeValue('--sidebar-accent')).toBe('244 50% 16%');
    expect(themeValue('--sidebar-accent-foreground')).toBe('244 100% 85%');
    expect(themeCss).toContain('rgb(97 94 255 / 5%)');
  });

  it('keeps violet emphasis on primary controls', () => {
    render(
      <>
        <Button>Save</Button>
        <Badge>Active</Badge>
      </>,
    );

    expect(screen.getByRole('button', { name: 'Save' })).toHaveClass('shadow-[0_0_15px_rgba(97,94,255,0.4)]');
    expect(screen.getByText('Active')).toHaveClass('shadow-[0_0_8px_rgba(97,94,255,0.15)]');
  });
});

describe('provider icons', () => {
  it('removes active content from taxonomy SVG markup', async () => {
    server.use(
      http.get(`/v1/orgs/${ORG.id}/workspaces/${WORKSPACES[0].slug}/taxonomy`, () =>
        HttpResponse.json({
          models: [],
          providers: [
            taxonomyProvider(
              'provider-1',
              'malicious',
              '<svg viewBox="0 0 24 24" onload="alert(1)"><script>alert(1)</script><image href="https://tracker.example/pixel" /><path style="filter:url(https://tracker.example/filter)" d="M0 0h24v24H0z" /></svg>',
            ),
          ],
        }),
      ),
    );
    window.history.replaceState(null, '', `/org/workspaces/${WORKSPACES[0].slug}/byok`);
    render(<App />);

    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Add Key' }));
    const provider = await screen.findByRole('radio', { name: 'malicious' });
    expect(provider.querySelector('script')).toBeNull();
    expect(provider.querySelector('[onload]')).toBeNull();
    expect(provider.querySelector('[href]')).toBeNull();
    expect(provider.querySelector('[style]')).toBeNull();
  });

  it('supports arrow-key navigation between providers', async () => {
    server.use(
      http.get(`/v1/orgs/${ORG.id}/workspaces/${WORKSPACES[0].slug}/taxonomy`, () =>
        HttpResponse.json({
          models: [],
          providers: [taxonomyProvider('provider-1', 'first'), taxonomyProvider('provider-2', 'second')],
        }),
      ),
    );
    window.history.replaceState(null, '', `/org/workspaces/${WORKSPACES[0].slug}/byok`);
    render(<App />);

    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Add Key' }));
    const first = await screen.findByRole('radio', { name: 'first' });
    const second = screen.getByRole('radio', { name: 'second' });
    await user.click(first);
    expect(first).toHaveFocus();
    await user.keyboard('{ArrowRight}');

    expect(second).toHaveFocus();
  });
});

describe('show-once keys', () => {
  it('reports clipboard failures and keeps manual copy available', async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('blocked'));
    render(<KeyRevealDialog open onOpenChange={() => undefined} token="secret-token" />);

    await user.click(screen.getByRole('button', { name: 'Copy key' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not copy the key');
    expect(screen.getByDisplayValue('secret-token')).toBeInTheDocument();
  });

  it('clears stale clipboard feedback before revealing a different key', async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('blocked'));
    const dialog = render(<KeyRevealDialog open onOpenChange={() => undefined} token="first-token" />);

    await user.click(screen.getByRole('button', { name: 'Copy key' }));
    expect(await screen.findByRole('alert')).toBeInTheDocument();

    dialog.rerender(<KeyRevealDialog open={false} onOpenChange={() => undefined} token={null} />);
    dialog.rerender(<KeyRevealDialog open onOpenChange={() => undefined} token="second-token" />);

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy key' })).toBeInTheDocument();
  });
});

describe('shared controls', () => {
  it('composes button styling onto navigation without nesting interactive controls', () => {
    render(
      <Button asChild>
        <Link href="/next">Continue</Link>
      </Button>,
    );

    const link = screen.getByRole('link', { name: 'Continue' });
    expect(link.closest('button')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Continue' })).not.toBeInTheDocument();
  });

  it('uses alert-dialog semantics and stays open when confirmation fails', async () => {
    const user = userEvent.setup();
    render(
      <ConfirmButton title="Delete organization" onConfirm={() => Promise.reject(new Error('failed'))}>
        Delete
      </ConfirmButton>,
    );

    await user.click(screen.getByRole('button', { name: 'Delete' }));
    const dialog = screen.getByRole('alertdialog', { name: 'Delete organization' });
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));

    expect(screen.getByRole('alertdialog', { name: 'Delete organization' })).toBeInTheDocument();
  });
});
