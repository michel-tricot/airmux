import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useRef } from 'react';
import { CopyButton, CopyFeedback } from '@/components/shared/copy-control';
import { useClipboardCopy } from '@/components/shared/use-clipboard-copy';

function CopyExample({ value, multiline = false, resetKey }: { value: string; multiline?: boolean; resetKey?: unknown }) {
  const inputTarget = useRef<HTMLInputElement>(null);
  const codeTarget = useRef<HTMLPreElement>(null);
  const clipboard = useClipboardCopy(value, multiline ? codeTarget : inputTarget, resetKey);
  return (
    <>
      {multiline ? (
        <pre ref={codeTarget} tabIndex={-1} aria-label="Copy source">
          {value}
        </pre>
      ) : (
        <input ref={inputTarget} readOnly value={value} aria-label="Copy source" />
      )}
      <CopyButton {...clipboard} />
      <CopyFeedback status={clipboard.status} />
    </>
  );
}

afterEach(() => vi.useRealTimers());

describe('copy controls', () => {
  it('announces success only after copying completes, then clears the feedback', async () => {
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
    render(<CopyExample value="example-value" />);

    await user.click(screen.getByRole('button', { name: 'Copy' }));

    expect(screen.getByRole('button', { name: 'Copying' })).toBeDisabled();
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
    expect(clipboard).toBe('');
    vi.useFakeTimers();
    await act(async () => complete());
    expect(clipboard).toBe('example-value');
    expect(screen.getByRole('button', { name: 'Copied' })).toBeEnabled();
    expect(screen.getByRole('status')).toHaveTextContent('Copied to clipboard');
    expect(screen.getByLabelText('Copy source')).not.toHaveFocus();

    act(() => vi.advanceTimersByTime(2_000));
    expect(screen.getByRole('button', { name: 'Copy' })).toBeEnabled();
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
  });

  it.each([
    { failure: 'unavailable', multiline: false },
    { failure: 'rejected', multiline: false },
    { failure: 'unavailable', multiline: true },
    { failure: 'rejected', multiline: true },
  ])('selects the source for manual copying when $failure, multiline=$multiline', async ({ failure, multiline }) => {
    const user = userEvent.setup();
    if (failure === 'unavailable') {
      vi.stubGlobal('navigator', { clipboard: undefined });
    } else {
      vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('blocked'));
    }
    const value = multiline ? 'first line\nsecond line' : 'example-value';
    render(<CopyExample value={value} multiline={multiline} />);

    await user.click(screen.getByRole('button', { name: 'Copy' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Press Command+C or Ctrl+C');
    expect(screen.getByLabelText('Copy source')).toHaveFocus();
    expect(screen.getByLabelText('Copy source')).toHaveSelection(value);
    expect(screen.getByRole('button', { name: 'Copy' })).toBeEnabled();
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
  });

  it('does not carry a pending failure into a different value', async () => {
    const user = userEvent.setup();
    let reject: (reason: Error) => void = () => undefined;
    vi.spyOn(navigator.clipboard, 'writeText').mockImplementation(
      () =>
        new Promise<void>((_, fail) => {
          reject = fail;
        }),
    );
    const view = render(<CopyExample value="first-value" />);
    await user.click(screen.getByRole('button', { name: 'Copy' }));

    view.rerender(<CopyExample value="second-value" />);
    await act(async () => reject(new Error('blocked')));

    expect(screen.getByRole('button', { name: 'Copy' })).toBeEnabled();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByDisplayValue('second-value')).not.toHaveFocus();
  });

  it('ignores a pending success after switching requests with identical text', async () => {
    const user = userEvent.setup();
    let complete: () => void = () => undefined;
    vi.spyOn(navigator.clipboard, 'writeText').mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          complete = resolve;
        }),
    );
    const view = render(<CopyExample value="same command" multiline resetKey={{}} />);
    await user.click(screen.getByRole('button', { name: 'Copy' }));

    view.rerender(<CopyExample value="same command" multiline resetKey={{}} />);
    await act(async () => complete());

    expect(screen.getByRole('button', { name: 'Copy' })).toBeEnabled();
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
  });
});
