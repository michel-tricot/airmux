import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';

describe('show-once clipboard', () => {
  it('copies the displayed key and announces success', async () => {
    const user = userEvent.setup();
    render(<KeyRevealDialog open onOpenChange={() => undefined} token="secret-token" />);

    await user.click(screen.getByRole('button', { name: 'Copy key' }));

    expect(await navigator.clipboard.readText()).toBe('secret-token');
    expect(screen.getByRole('button', { name: 'Copied' })).toBeEnabled();
    expect(screen.getByRole('status')).toHaveTextContent('Copied to clipboard');
    expect(screen.getByDisplayValue('secret-token')).not.toHaveFocus();
  });

  it('removes the key after explicit dismissal, including a pending copy result', async () => {
    const user = userEvent.setup();
    let complete: () => void = () => undefined;
    vi.spyOn(navigator.clipboard, 'writeText').mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          complete = resolve;
        }),
    );
    function Reveal() {
      const [token, setToken] = useState<string | null>('secret-token');
      return <KeyRevealDialog open={token !== null} onOpenChange={(open) => !open && setToken(null)} token={token} />;
    }
    render(<Reveal />);
    await user.click(screen.getByRole('button', { name: 'Copy key' }));
    await user.click(screen.getByRole('button', { name: 'I have saved it' }));
    await act(async () => complete());

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue('secret-token')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Copied' })).not.toBeInTheDocument();
  });
});
