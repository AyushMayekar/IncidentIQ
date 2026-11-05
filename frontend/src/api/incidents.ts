import type {
  Incident,
  IncidentCreateInput,
  IncidentList,
  IncidentUpdateInput,
} from './types'

const DEFAULT_API = 'http://127.0.0.1:8000/api/v1'

/** Base URL for the API, read per call so configuration changes are picked up. */
function apiBase(): string {
  return (import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API).replace(/\/$/, '')
}

/** Turn a FastAPI error payload into a message a person can act on. */
function messageFromBody(status: number, body: unknown): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const parts = detail
        .map((entry) =>
          entry && typeof entry === 'object' && 'msg' in entry
            ? String((entry as { msg: unknown }).msg)
            : null,
        )
        .filter((entry): entry is string => Boolean(entry))
      if (parts.length) return parts.join('; ')
    }
  }
  return `Request failed (${status})`
}

/** Perform the fetch and turn failures into readable errors. Returns the OK response. */
async function send(path: string, init?: RequestInit): Promise<Response> {
  let response: Response
  try {
    response = await fetch(`${apiBase()}${path}`, {
      ...init,
      headers: {
        // JSON bodies get a JSON header. FormData must not: the browser has to
        // generate the multipart Content-Type together with its boundary.
        ...(init?.body && !(init.body instanceof FormData)
          ? { 'Content-Type': 'application/json' }
          : {}),
        ...init?.headers,
      },
    })
  } catch (error) {
    // A cancelled request is not a connectivity problem; let callers see it as is.
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new Error(
      'Could not reach the IncidentIQ API. Check that the server is running and try again.',
      { cause: error },
    )
  }

  if (!response.ok) {
    let body: unknown
    try {
      body = await response.json()
    } catch {
      body = undefined
    }
    throw new Error(messageFromBody(response.status, body))
  }

  return response
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await send(path, init)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/** Same as `request`, for endpoints that return plain text. */
export async function requestText(path: string, init?: RequestInit): Promise<string> {
  const response = await send(path, init)
  return response.text()
}

export function listIncidents(params?: { limit?: number; offset?: number }): Promise<IncidentList> {
  const limit = params?.limit ?? 20
  const offset = params?.offset ?? 0
  return request<IncidentList>(`/incidents?limit=${limit}&offset=${offset}`)
}

export function createIncident(payload: IncidentCreateInput): Promise<Incident> {
  return request<Incident>('/incidents', {
    method: 'POST',
    body: JSON.stringify({ occurred_at: null, ...payload }),
  })
}

export function getIncident(id: string): Promise<Incident> {
  return request<Incident>(`/incidents/${id}`)
}

export function updateIncident(id: string, payload: IncidentUpdateInput): Promise<Incident> {
  return request<Incident>(`/incidents/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function deleteIncident(id: string): Promise<void> {
  return request<void>(`/incidents/${id}`, { method: 'DELETE' })
}

/** `true` when the API answers its health check. */
export async function checkHealth(): Promise<boolean> {
  try {
    const base = apiBase()
    const healthUrl = `${base.replace(/\/api\/v1$/, '')}/health/live`
    const response = await fetch(healthUrl)
    if (!response.ok) return false
    const body = (await response.json()) as { status?: string }
    return body.status === 'ok'
  } catch {
    return false
  }
}