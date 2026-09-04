import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';

describe('show-once clipboard', () => {
  it('reports success only after the clipboard contains the key', async () => {
    const user = userEvent.setup();
    let clipboard = '';
    let complete: () => void = () => undefined;
    vi.spyOn(navigator.clipboard, 'writeText').mockImplementation(
      (value) =>
        new Promise<void>((resolve) => {
          complete = () => {
            clipboard = value;
            resolve();
          };
        }),
    );
    render(<KeyRevealDialog open onOpenChange={() => undefined} token="secret-token" />);

    await user.click(screen.getByRole('button', { name: 'Copy key' }));

    expect(screen.queryByRole('button', { name: 'Copied' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copying' })).toBeDisabled();
    expect(clipboard).toBe('');
    await act(async () => complete());
    expect(clipboard).toBe('secret-token');
    expect(screen.getByRole('button', { name: 'Copied' })).toBeEnabled();
    expect(screen.getByDisplayValue('secret-token')).not.toHaveFocus();
  });

  it.each(['unavailable', 'rejected'])('offers manual copy when the clipboard is %s', async (failure) => {
    const user = userEvent.setup();
    if (failure === 'unavailable') {
      vi.stubGlobal('navigator', { clipboard: undefined });
    } else {
      vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('blocked'));
    }
    render(<KeyRevealDialog open onOpenChange={() => undefined} token="secret-token" />);

    await user.click(screen.getByRole('button', { name: 'Copy key' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Press Command+C or Ctrl+C');
    expect(screen.getByDisplayValue('secret-token')).toHaveFocus();
    expect(screen.getByDisplayValue('secret-token')).toHaveSelection('secret-token');
    expect(screen.queryByRole('button', { name: 'Copied' })).not.toBeInTheDocument();
  });

  it('does not carry a pending copy result into a different key', async () => {
    const user = userEvent.setup();
    let reject: (reason: Error) => void = () => undefined;
    vi.spyOn(navigator.clipboard, 'writeText').mockImplementation(
      () =>
        new Promise<void>((_, fail) => {
          reject = fail;
        }),
    );
    const view = render(<KeyRevealDialog open onOpenChange={() => undefined} token="first-token" />);
    await user.click(screen.getByRole('button', { name: 'Copy key' }));

    view.rerender(<KeyRevealDialog open onOpenChange={() => undefined} token="second-token" />);
    await act(async () => reject(new Error('blocked')));

    expect(screen.getByRole('button', { name: 'Copy key' })).toBeEnabled();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByDisplayValue('second-token')).not.toHaveFocus();
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
