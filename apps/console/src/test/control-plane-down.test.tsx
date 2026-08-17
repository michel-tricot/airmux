import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlPlaneDown } from '@/components/shared/control-plane-down';

afterEach(() => vi.useRealTimers());

describe('control-plane reconnect screen', () => {
  it('retries automatically and resets the countdown after a failed check', () => {
    vi.useFakeTimers();
    const retry = vi.fn();
    const view = render(<ControlPlaneDown onRetry={retry} isRetrying={false} />);

    expect(screen.getByRole('status')).toHaveTextContent('Retrying automatically in 10s');
    act(() => vi.advanceTimersByTime(10_000));
    expect(retry).toHaveBeenCalledTimes(1);

    view.rerender(<ControlPlaneDown onRetry={retry} isRetrying />);
    expect(screen.getByRole('status')).toHaveTextContent('Checking the connection');

    view.rerender(<ControlPlaneDown onRetry={retry} isRetrying={false} />);
    expect(screen.getByRole('status')).toHaveTextContent('Retrying automatically in 10s');
  });
});
