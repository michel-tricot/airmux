import '@testing-library/jest-dom/vitest';

// jsdom lacks the pointer-capture and scroll APIs Radix Select relies on.
window.HTMLElement.prototype.hasPointerCapture = () => false;
window.HTMLElement.prototype.setPointerCapture = () => {};
window.HTMLElement.prototype.releasePointerCapture = () => {};
window.HTMLElement.prototype.scrollIntoView = () => {};
import { afterAll, afterEach, beforeAll } from 'vitest';
import { cleanup } from '@testing-library/react';
import { queryClient } from '@/App';
import { server } from './msw';

// jsdom lacks these APIs that Radix Select relies on.
Element.prototype.scrollIntoView ??= () => {};
Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.setPointerCapture ??= () => {};
Element.prototype.releasePointerCapture ??= () => {};

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  localStorage.clear();
  // The app's query client is a module-level singleton; without this, cached
  // rows from one test leak into the next (same org id, different handlers).
  queryClient.clear();
});
afterAll(() => server.close());
