/** Build-time flags. */
export const env = {
  /** Answer /api calls from in-browser fixtures (src/shared/lib/mocks). */
  useMocks: import.meta.env.VITE_USE_MOCKS === 'true' || import.meta.env.MODE === 'mocks',
  apiBase: '/api',
} as const;
