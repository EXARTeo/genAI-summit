export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export interface MockContext {
  params: Record<string, string>;
  query: URLSearchParams;
  /** Parsed JSON body, the FormData, or undefined. */
  body: unknown;
  headers: Headers;
}

/** Return a plain value (sent as 200 JSON), a `MockResponse`, or throw `mockError(...)`. */
export type MockHandler = (ctx: MockContext) => unknown | Promise<unknown>;

export interface MockRoute {
  method: HttpMethod;
  /** Backend path without `/api`, e.g. `/v1/systems/:systemId/files/*path` (`*name` = rest of the path). */
  path: string;
  handler: MockHandler;
}

export class MockResponse {
  constructor(
    readonly status: number,
    readonly body: unknown,
    readonly contentType = 'application/json',
  ) {}
}

export const mockError = (status: number, detail: string) => new MockResponse(status, { detail });
