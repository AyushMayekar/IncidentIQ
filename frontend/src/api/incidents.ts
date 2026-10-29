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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBase()}${path}`, {
      ...init,
      headers: {
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    })
  } catch {
    throw new Error(
      'Could not reach the IncidentIQ API. Check that the server is running and try again.',
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

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
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
