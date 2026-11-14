/**
 * Mock mode (`VITE_USE_MOCKS=true`): the API client calls `mockFetch` instead of `fetch`.
 *
 * Add mocks for a feature by dropping a file in `./handlers/` that exports
 * `routes: MockRoute[]`; it is picked up automatically (no edit here needed).
 * The router is loaded lazily so production bundles only pay for it in mock mode.
 */
export type { MockContext, MockRoute } from './types';
export { MockResponse, mockError } from './types';

export async function mockFetch(url: string, init: RequestInit): Promise<Response> {
  const { handleMockRequest } = await import('./router');
  return handleMockRequest(url, init);
}
