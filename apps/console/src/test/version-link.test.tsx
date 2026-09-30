import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import App from '@/App';

it('links the displayed build version to its release', () => {
  vi.stubEnv('VITE_AIRMUX_VERSION', '1.2.3');
  render(<App />);

  expect(screen.getByRole('link', { name: 'v1.2.3' })).toHaveAttribute('href', 'https://github.com/michel-tricot/airmux/releases/tag/v1.2.3');
});

it('links a development build to the releases list', () => {
  vi.stubEnv('VITE_AIRMUX_VERSION', '');
  render(<App />);

  expect(screen.getByRole('link', { name: 'dev' })).toHaveAttribute('href', 'https://github.com/michel-tricot/airmux/releases');
});
