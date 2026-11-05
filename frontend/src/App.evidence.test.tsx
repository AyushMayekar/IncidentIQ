import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

function json(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
    })
}

function makeIncident(id: string, title: string) {
    return {
        id,
        title,
        description: `${title} description`,
        service: 'checkout',
        severity: 'high',
        status: 'open',
        occurred_at: null,
        created_at: '2026-10-31T10:00:00Z',
        updated_at: '2026-10-31T10:00:00Z',
    }
}

const incidents = [makeIncident('inc-1', 'First incident'), makeIncident('inc-2', 'Second incident')]

function evidenceFor(incidentId: string, name: string) {
    return {
        id: `ev-${incidentId}`,
        incident_id: incidentId,
        source_name: name,
        evidence_type: 'application_log',
        content_type: 'text/plain; charset=utf-8',
        content_hash: 'b'.repeat(64),
        byte_size: 100,
        parse_status: 'parsed',
        record_count: 2,
        error_message: null,
        processed_at: '2026-10-31T10:01:00Z',
        processing_duration_ms: 12,
        created_at: '2026-10-31T10:00:00Z',
    }
}

const evidenceByIncident: Record<string, unknown[]> = {
    'inc-1': [evidenceFor('inc-1', 'first-only.log')],
    'inc-2': [evidenceFor('inc-2', 'second-only.log')],
}

function route(url: string): Response {
    if (url.endsWith('/health/live')) return json({ status: 'ok' })
    if (/\/incidents\?/.test(url)) {
        return json({ items: incidents, total: incidents.length, limit: 20, offset: 0 })
    }
    const evidence = url.match(/\/incidents\/([^/?]+)\/evidence$/)
    if (evidence) return json(evidenceByIncident[evidence[1]] ?? [])
    const detail = url.match(/\/incidents\/([^/?]+)$/)
    if (detail) {
        const found = incidents.find((incident) => incident.id === detail[1])
        return found ? json(found) : json({ detail: 'Incident not found.' }, 404)
    }
    return json({ detail: 'Not found' }, 404)
}

afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    window.history.replaceState({}, '', '/')
})

describe('App evidence integration', () => {
    it('shows evidence only inside each incident workspace', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn<typeof fetch>(async (input) => route(String(input))),
        )
        const user = userEvent.setup({ applyAccept: false })

        render(<App />)

        // The dashboard is navigational: no evidence UI lives there.
        await user.click(await screen.findByRole('button', { name: 'Open incident: First incident' }))
        expect(await screen.findByRole('heading', { name: 'First incident' })).toBeTruthy()
        expect(screen.queryByRole('heading', { name: 'Evidence', level: 3 })).toBeNull()

        await user.click(screen.getByRole('tab', { name: 'Evidence' }))
        expect(await screen.findByText('first-only.log')).toBeTruthy()
        expect(await screen.findByText('Ready for chunking')).toBeTruthy()
        expect(screen.getByText('2 records · processed in 12 ms')).toBeTruthy()

        await user.click(screen.getByRole('button', { name: '← Back to incidents' }))
        await user.click(await screen.findByRole('button', { name: 'Open incident: Second incident' }))
        await user.click(await screen.findByRole('tab', { name: 'Evidence' }))

        expect(await screen.findByText('second-only.log')).toBeTruthy()
        expect(screen.queryByText('first-only.log')).toBeNull()
        expect(await screen.findByRole('heading', { name: 'Second incident' })).toBeTruthy()
    })

    it('loads a workspace from a direct URL', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn<typeof fetch>(async (input) => route(String(input))),
        )
        window.history.replaceState({}, '', '/incidents/inc-2')

        render(<App />)

        expect(await screen.findByRole('heading', { name: 'Second incident' })).toBeTruthy()
        await userEvent.setup({ applyAccept: false }).click(
            screen.getByRole('tab', { name: 'Evidence' }),
        )
        expect(await screen.findByText('second-only.log')).toBeTruthy()
    })
})
