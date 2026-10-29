import { vi } from 'vitest'

/**
 * Deterministic `fetch` double.
 *
 * `json` responses resolve with the parsed body, `204` responses resolve with
 * `undefined`, and network failures reject — mirroring the real client.
 */
export function mockFetch(
  handler: (url: string, init?: RequestInit) => { status?: number; body?: unknown } | Error,
): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const result = handler(url, init)
    if (result instanceof Error) throw result

    const status = result.status ?? 200
    if (status === 204) {
      return {
        ok: status >= 200 && status < 300,
        status,
        json: async () => {
          throw new Error('No content')
        },
      } as unknown as Response
    }
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => result.body,
    } as unknown as Response
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}
