import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { mockFetch } from '../test/mockFetch'
import {
  createIncident,
  deleteIncident,
  getIncident,
  listIncidents,
  updateIncident,
  checkHealth,
} from './incidents'

const API = 'http://127.0.0.1:8000/api/v1'

const incident = {
  id: '3f1a4c1e-0000-4000-8000-000000000001',
  title: 'Checkout API elevated 5xx errors',
  description: 'Checkout requests are failing with HTTP 502.',
  service: 'checkout-api',
  severity: 'high',
  status: 'open',
  occurred_at: null,
  created_at: '2026-01-05T09:30:00Z',
  updated_at: '2026-01-05T09:30:00Z',
}

describe('API client', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', API)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
  })

  describe('listIncidents', () => {
    it('requests the incidents collection with pagination', async () => {
      const fetchMock = mockFetch(() => ({
        body: { items: [incident], total: 1, limit: 20, offset: 0 },
      }))

      const result = await listIncidents({ limit: 20, offset: 0 })

      expect(fetchMock).toHaveBeenCalledTimes(1)
      expect(fetchMock.mock.calls[0][0]).toBe(`${API}/incidents?limit=20&offset=0`)
      expect(result.total).toBe(1)
      expect(result.items).toHaveLength(1)
      expect(result.items[0].id).toBe(incident.id)
    })

    it('defaults to the first page', async () => {
      const fetchMock = mockFetch(() => ({
        body: { items: [], total: 0, limit: 20, offset: 0 },
      }))

      await listIncidents()

      expect(fetchMock.mock.calls[0][0]).toBe(`${API}/incidents?limit=20&offset=0`)
    })
  })

  describe('createIncident', () => {
    it('POSTs the payload as JSON and returns the created incident', async () => {
      const fetchMock = mockFetch((_, init) => {
        expect(init?.method).toBe('POST')
        expect(init?.headers).toMatchObject({ 'Content-Type': 'application/json' })
        return { status: 201, body: incident }
      })

      const created = await createIncident({
        title: incident.title,
        description: incident.description,
        service: incident.service,
        severity: 'high',
      })

      expect(fetchMock).toHaveBeenCalledTimes(1)
      expect(fetchMock.mock.calls[0][0]).toBe(`${API}/incidents`)
      const sent = JSON.parse(String(fetchMock.mock.calls[0][1]?.body))
      expect(sent).toEqual({
        title: incident.title,
        description: incident.description,
        service: incident.service,
        severity: 'high',
        occurred_at: null,
      })
      expect(created.id).toBe(incident.id)
    })

    it('omits occurred_at when not provided', async () => {
      const fetchMock = mockFetch(() => ({ status: 201, body: incident }))

      await createIncident({
        title: 't',
        description: 'd',
        service: null,
        severity: 'low',
      })

      const sent = JSON.parse(String(fetchMock.mock.calls[0][1]?.body))
      expect('occurred_at' in sent).toBe(true)
      expect(sent.occurred_at).toBeNull()
    })
  })

  describe('getIncident', () => {
    it('GETs a single incident by id', async () => {
      const fetchMock = mockFetch(() => ({ body: incident }))

      const result = await getIncident(incident.id)

      expect(fetchMock.mock.calls[0][0]).toBe(`${API}/incidents/${incident.id}`)
      expect(result.id).toBe(incident.id)
    })
  })

  describe('updateIncident', () => {
    it('PATCHes only the provided fields', async () => {
      const fetchMock = mockFetch((_, init) => {
        expect(init?.method).toBe('PATCH')
        return { body: { ...incident, status: 'investigating' } }
      })

      const result = await updateIncident(incident.id, { status: 'investigating' })

      expect(fetchMock.mock.calls[0][0]).toBe(`${API}/incidents/${incident.id}`)
      expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
        status: 'investigating',
      })
      expect(result.status).toBe('investigating')
    })
  })

  describe('deleteIncident', () => {
    it('DELETEs and resolves on 204 without parsing a body', async () => {
      const fetchMock = mockFetch((_, init) => {
        expect(init?.method).toBe('DELETE')
        return { status: 204 }
      })

      await expect(deleteIncident(incident.id)).resolves.toBeUndefined()
      expect(fetchMock.mock.calls[0][0]).toBe(`${API}/incidents/${incident.id}`)
    })
  })

  describe('checkHealth', () => {
    it('reports healthy when the health endpoint responds', async () => {
      mockFetch(() => ({ body: { status: 'ok' } }))

      await expect(checkHealth()).resolves.toBe(true)
    })

    it('reports unhealthy when the endpoint is unreachable', async () => {
      mockFetch(() => new Error('connection refused'))

      await expect(checkHealth()).resolves.toBe(false)
    })
  })

  describe('error handling', () => {
    it('surfaces a FastAPI string detail message', async () => {
      mockFetch(() => ({ status: 404, body: { detail: 'Incident not found.' } }))

      await expect(getIncident('missing')).rejects.toThrow('Incident not found.')
    })

    it('joins FastAPI 422 field errors into one readable message', async () => {
      mockFetch(() => ({
        status: 422,
        body: {
          detail: [
            { msg: 'Field required', loc: ['body', 'title'] },
            { msg: 'Input should be less than 200', loc: ['body', 'title'] },
          ],
        },
      }))

      await expect(
        createIncident({ title: '', description: 'd', service: null, severity: 'low' }),
      ).rejects.toThrow('Field required; Input should be less than 200')
    })

    it('falls back to a status message when the body is not JSON', async () => {
      mockFetch(() => ({ status: 500, body: undefined }))

      await expect(listIncidents()).rejects.toThrow('Request failed (500)')
    })

    it('wraps network failures in a friendly message', async () => {
      mockFetch(() => new Error('Failed to fetch'))

      await expect(listIncidents()).rejects.toThrow(
        /Could not reach the IncidentIQ API/,
      )
    })
  })
})
