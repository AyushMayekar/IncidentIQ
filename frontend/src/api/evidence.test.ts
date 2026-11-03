import { afterEach, describe, expect, it, vi } from 'vitest'
import { getEvidenceContent, listEvidence, uploadEvidence } from './evidence'
import {
    EVIDENCE_TYPES,
    MAX_EVIDENCE_BYTES,
    evidenceTypeLabel,
    formatBytes,
    validateEvidenceFile,
} from './evidenceTypes'

function jsonResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
    })
}

function stubFetch(response: Response) {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(response)
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
}

const record = {
    id: 'ev-1',
    incident_id: 'inc-1',
    source_name: 'sample.log',
    evidence_type: 'application_log',
    content_type: 'text/plain; charset=utf-8',
    content_hash: 'a'.repeat(64),
    byte_size: 5,
    parse_status: 'not_required',
    created_at: '2026-10-31T10:00:00Z',
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe('listEvidence', () => {
    it('requests the incident evidence endpoint and returns the records', async () => {
        const fetchMock = stubFetch(jsonResponse([record]))

        const result = await listEvidence('inc-1')

        expect(result).toEqual([record])
        expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/incidents\/inc-1\/evidence$/)
    })

    it('returns an empty array for an incident without evidence', async () => {
        stubFetch(jsonResponse([]))
        expect(await listEvidence('inc-1')).toEqual([])
    })

    it('encodes the incident id in the path', async () => {
        const fetchMock = stubFetch(jsonResponse([]))
        await listEvidence('a/b')
        expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/incidents\/a%2Fb\/evidence$/)
    })

    it('passes the abort signal to fetch', async () => {
        const fetchMock = stubFetch(jsonResponse([]))
        const controller = new AbortController()
        await listEvidence('inc-1', controller.signal)
        expect(fetchMock.mock.calls[0][1]?.signal).toBe(controller.signal)
    })

    it('lets an abort surface as an AbortError, not a connectivity error', async () => {
        const fetchMock = vi.fn<typeof fetch>().mockRejectedValue(new DOMException('Aborted', 'AbortError'))
        vi.stubGlobal('fetch', fetchMock)
        await expect(listEvidence('inc-1')).rejects.toMatchObject({ name: 'AbortError' })
    })

    it('reports an unreachable API in plain language', async () => {
        const fetchMock = vi.fn<typeof fetch>().mockRejectedValue(new TypeError('Failed to fetch'))
        vi.stubGlobal('fetch', fetchMock)
        await expect(listEvidence('inc-1')).rejects.toThrow(/Could not reach the IncidentIQ API/)
    })
})

describe('uploadEvidence', () => {
    it('posts FormData with the file and evidence_type, without a manual Content-Type', async () => {
        const fetchMock = stubFetch(jsonResponse(record, 201))
        const file = new File(['hello'], 'sample.log', { type: 'text/plain' })

        const created = await uploadEvidence('inc-1', file, 'application_log')

        expect(created).toEqual(record)
        const [url, init] = fetchMock.mock.calls[0]
        expect(String(url)).toMatch(/\/incidents\/inc-1\/evidence$/)
        expect(init?.method).toBe('POST')
        expect(init?.body).toBeInstanceOf(FormData)
        const form = init?.body as FormData
        expect((form.get('file') as File).name).toBe('sample.log')
        expect(form.get('evidence_type')).toBe('application_log')
        expect(new Headers(init?.headers).has('content-type')).toBe(false)
    })

    it('surfaces the backend message for a duplicate upload', async () => {
        stubFetch(
            jsonResponse({ detail: 'This evidence has already been uploaded for this incident.' }, 409),
        )
        const file = new File(['hello'], 'sample.log')
        await expect(uploadEvidence('inc-1', file, 'alert')).rejects.toThrow(
            'This evidence has already been uploaded for this incident.',
        )
    })

    it('surfaces the backend message for an oversized upload', async () => {
        stubFetch(jsonResponse({ detail: 'File exceeds the maximum size of 5 MiB.' }, 413))
        const file = new File(['hello'], 'sample.log')
        await expect(uploadEvidence('inc-1', file, 'alert')).rejects.toThrow(
            'File exceeds the maximum size of 5 MiB.',
        )
    })
})

describe('getEvidenceContent', () => {
    it('requests the content endpoint with both ids and returns the exact text', async () => {
        const raw = 'line one\r\n  indented\t<b>tag</b>\n'
        const fetchMock = stubFetch(
            new Response(raw, { status: 200, headers: { 'Content-Type': 'text/plain; charset=utf-8' } }),
        )

        const text = await getEvidenceContent('inc-1', 'ev-9')

        expect(text).toBe(raw)
        expect(String(fetchMock.mock.calls[0][0])).toMatch(
            /\/incidents\/inc-1\/evidence\/ev-9\/content$/,
        )
    })

    it('surfaces a 404 message', async () => {
        stubFetch(jsonResponse({ detail: 'Evidence not found.' }, 404))
        await expect(getEvidenceContent('inc-1', 'missing')).rejects.toThrow('Evidence not found.')
    })
})

describe('evidence helpers', () => {
    it('knows all eight backend evidence types', () => {
        expect([...EVIDENCE_TYPES]).toEqual([
            'application_log',
            'infrastructure_log',
            'metrics',
            'trace',
            'deployment_event',
            'alert',
            'configuration',
            'manual_context',
        ])
    })

    it('labels evidence types readably, including legacy and unknown values', () => {
        expect(evidenceTypeLabel('deployment_event')).toBe('Deployment event')
        expect(evidenceTypeLabel(null)).toBe('Unclassified')
        expect(evidenceTypeLabel('custom_type')).toBe('Custom type')
    })

    it('formats byte sizes', () => {
        expect(formatBytes(0)).toBe('0 B')
        expect(formatBytes(512)).toBe('512 B')
        expect(formatBytes(2048)).toBe('2.0 KiB')
        expect(formatBytes(3 * 1024 * 1024)).toBe('3.0 MiB')
    })

    it.each(['app.log', 'NOTES.TXT', 'Mixed.Log'])('accepts %s', (name) => {
        expect(validateEvidenceFile({ name, size: 10 })).toBeNull()
    })

    it.each(['data.csv', 'script.sh', 'README', '.log', 'app.log.exe'])('rejects %s', (name) => {
        expect(validateEvidenceFile({ name, size: 10 })).toMatch(/Unsupported file type/)
    })

    it('rejects empty files', () => {
        expect(validateEvidenceFile({ name: 'a.log', size: 0 })).toMatch(/empty/)
    })

    it('accepts exactly 5 MiB and rejects one byte more', () => {
        expect(validateEvidenceFile({ name: 'a.log', size: MAX_EVIDENCE_BYTES })).toBeNull()
        expect(validateEvidenceFile({ name: 'a.log', size: MAX_EVIDENCE_BYTES + 1 })).toMatch(
            /maximum allowed size is 5 MiB/,
        )
    })
})