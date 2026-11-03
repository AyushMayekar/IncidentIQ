import { act, cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Evidence } from '../api/evidenceTypes'
import { EvidenceManager } from './EvidenceManager'
import { ToastProvider } from './Toast'

const EMPTY_COPY =
    'No evidence attached yet. Upload logs or other diagnostic evidence to begin investigating this incident.'
const DUPLICATE_MESSAGE = 'This evidence has already been uploaded for this incident.'

function json(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
    })
}

function makeEvidence(overrides: Partial<Evidence> = {}): Evidence {
    return {
        id: 'ev-1',
        incident_id: 'inc-1',
        source_name: 'checkout.log',
        evidence_type: 'application_log',
        content_type: 'text/plain; charset=utf-8',
        content_hash: 'a'.repeat(64),
        byte_size: 2048,
        parse_status: 'not_required',
        created_at: '2026-10-31T10:00:00Z',
        ...overrides,
    }
}

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>

function installFetch(handler: Handler) {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => handler(String(input), init))
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
}

function renderManager(incidentId = 'inc-1') {
    return render(
        <ToastProvider>
            <EvidenceManager incidentId={incidentId} />
        </ToastProvider>,
    )
}

function postCalls(fetchMock: ReturnType<typeof installFetch>) {
    return fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')
}

afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
})

describe('EvidenceManager list', () => {
    it('shows metadata with readable labels and never fetches raw content for the list', async () => {
        const fetchMock = installFetch(() =>
            json([
                makeEvidence(),
                makeEvidence({
                    id: 'ev-2',
                    source_name: 'ops-notes.txt',
                    evidence_type: null,
                    byte_size: 512,
                }),
            ]),
        )

        renderManager()

        const list = await screen.findByRole('list', { name: 'Evidence records' })
        expect(within(list).getByText('checkout.log')).toBeTruthy()
        expect(within(list).getByText('Application log')).toBeTruthy()
        expect(within(list).getByText('2.0 KiB')).toBeTruthy()
        expect(within(list).getByText('Unclassified')).toBeTruthy()
        expect(within(list).getByText('512 B')).toBeTruthy()
        expect(within(list).getAllByText('text/plain; charset=utf-8')).toHaveLength(2)
        expect(within(list).getAllByText('Not required')).toHaveLength(2)
        expect(screen.getByRole('heading', { name: 'Evidence', level: 3 })).toBeTruthy()
        expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/content'))).toBe(false)
    })

    it('renders the empty state', async () => {
        installFetch(() => json([]))
        renderManager()
        expect(await screen.findByText(EMPTY_COPY)).toBeTruthy()
        expect(screen.getByRole('heading', { name: 'Evidence', level: 3 })).toBeTruthy()
    })

    it('shows an error with a retry action when listing fails, then recovers', async () => {
        let calls = 0
        installFetch(() => {
            calls += 1
            return calls === 1 ? json({ detail: 'Database unavailable' }, 500) : json([makeEvidence()])
        })
        const user = userEvent.setup({ applyAccept: false })

        renderManager()

        expect(await screen.findByText('Database unavailable')).toBeTruthy()
        await user.click(screen.getByRole('button', { name: 'Retry' }))
        const list = await screen.findByRole('list', { name: 'Evidence records' })
        expect(within(list).getByText('checkout.log')).toBeTruthy()
        expect(screen.queryByText('Database unavailable')).toBeNull()
    })
})

describe('EvidenceManager upload validation', () => {
    it('rejects unsupported extensions without sending a request', async () => {
        const fetchMock = installFetch(() => json([]))
        const user = userEvent.setup({ applyAccept: false })
        renderManager()
        await screen.findByText(EMPTY_COPY)

        await user.upload(screen.getByLabelText('Evidence file'), new File(['a,b'], 'data.csv'))
        expect(
            await screen.findByText('Unsupported file type. Only .log and .txt files are accepted.'),
        ).toBeTruthy()

        await user.selectOptions(screen.getByLabelText('Evidence type'), 'metrics')
        await user.click(screen.getByRole('button', { name: 'Upload evidence' }))

        expect(postCalls(fetchMock)).toHaveLength(0)
        expect(screen.getByText('Unsupported file type. Only .log and .txt files are accepted.')).toBeTruthy()
    })

    it('rejects files over 5 MiB without sending a request', async () => {
        const fetchMock = installFetch(() => json([]))
        const user = userEvent.setup({ applyAccept: false })
        renderManager()
        await screen.findByText(EMPTY_COPY)

        const big = new File(['x'], 'big.log')
        Object.defineProperty(big, 'size', { value: 6 * 1024 * 1024 })
        await user.upload(screen.getByLabelText('Evidence file'), big)

        expect(await screen.findByText(/maximum allowed size is 5 MiB/)).toBeTruthy()
        await user.selectOptions(screen.getByLabelText('Evidence type'), 'metrics')
        await user.click(screen.getByRole('button', { name: 'Upload evidence' }))
        expect(postCalls(fetchMock)).toHaveLength(0)
    })

    it('rejects empty files', async () => {
        installFetch(() => json([]))
        const user = userEvent.setup({ applyAccept: false })
        renderManager()
        await screen.findByText(EMPTY_COPY)

        await user.upload(screen.getByLabelText('Evidence file'), new File([], 'empty.log'))

        expect(await screen.findByText('The selected file is empty.')).toBeTruthy()
    })

    it('requires both a file and an evidence type', async () => {
        const fetchMock = installFetch(() => json([]))
        const user = userEvent.setup({ applyAccept: false })
        renderManager()
        await screen.findByText(EMPTY_COPY)

        await user.click(screen.getByRole('button', { name: 'Upload evidence' }))

        expect(await screen.findByText('Choose a .log or .txt file to upload.')).toBeTruthy()
        expect(screen.getByText('Select what kind of evidence this is.')).toBeTruthy()
        expect(postCalls(fetchMock)).toHaveLength(0)
    })

    it('offers all eight evidence types', async () => {
        installFetch(() => json([]))
        renderManager()
        await screen.findByText(EMPTY_COPY)

        const select = screen.getByLabelText('Evidence type') as HTMLSelectElement
        const values = Array.from(select.options).map((option) => option.value)
        expect(values).toEqual([
            '',
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
})

describe('EvidenceManager upload', () => {
    it('sends FormData for the current incident, refreshes the list and resets the file input', async () => {
        const stored: Evidence[] = []
        const fetchMock = installFetch((_url, init) => {
            if (init?.method === 'POST') {
                const form = init.body as FormData
                const file = form.get('file') as File
                const created = makeEvidence({
                    id: 'ev-new',
                    source_name: file.name,
                    evidence_type: String(form.get('evidence_type')),
                    byte_size: file.size,
                })
                stored.push(created)
                return json(created, 201)
            }
            return json(stored)
        })
        const user = userEvent.setup({ applyAccept: false })
        renderManager('inc-1')
        await screen.findByText(EMPTY_COPY)

        const input = screen.getByLabelText('Evidence file') as HTMLInputElement
        await user.upload(input, new File(['hello'], 'sample.log', { type: 'text/plain' }))
        await user.selectOptions(screen.getByLabelText('Evidence type'), 'alert')
        await user.click(screen.getByRole('button', { name: 'Upload evidence' }))

        const list = await screen.findByRole('list', { name: 'Evidence records' })
        expect(within(list).getByText('sample.log')).toBeTruthy()
        expect(within(list).getByText('Alert')).toBeTruthy()
        expect(await screen.findByText('Evidence uploaded')).toBeTruthy()

        const posts = postCalls(fetchMock)
        expect(posts).toHaveLength(1)
        const [url, init] = posts[0]
        expect(String(url)).toMatch(/\/incidents\/inc-1\/evidence$/)
        expect(init?.body).toBeInstanceOf(FormData)
        const form = init?.body as FormData
        expect((form.get('file') as File).name).toBe('sample.log')
        expect(form.get('evidence_type')).toBe('alert')
        expect(new Headers(init?.headers).has('content-type')).toBe(false)

        const gets = fetchMock.mock.calls.filter(([, requestInit]) => requestInit?.method !== 'POST')
        expect(gets.length).toBeGreaterThanOrEqual(2)
        expect(input.value).toBe('')
        expect(screen.queryByText(/^Selected:/)).toBeNull()
    })

    it('shows the backend error and keeps the form so the user can retry', async () => {
        installFetch((_url, init) =>
            init?.method === 'POST' ? json({ detail: DUPLICATE_MESSAGE }, 409) : json([]),
        )
        const user = userEvent.setup({ applyAccept: false })
        renderManager()
        await screen.findByText(EMPTY_COPY)

        await user.upload(screen.getByLabelText('Evidence file'), new File(['hello'], 'dup.log'))
        await user.selectOptions(screen.getByLabelText('Evidence type'), 'alert')
        await user.click(screen.getByRole('button', { name: 'Upload evidence' }))

        expect(await screen.findByText(DUPLICATE_MESSAGE)).toBeTruthy()
        expect(screen.getByText('Selected: dup.log (5 B)')).toBeTruthy()
        expect((screen.getByLabelText('Evidence type') as HTMLSelectElement).value).toBe('alert')
        const button = screen.getByRole('button', { name: 'Upload evidence' }) as HTMLButtonElement
        expect(button.disabled).toBe(false)
    })

    it('prevents duplicate submissions while an upload is in flight', async () => {
        let release!: (response: Response) => void
        const gate = new Promise<Response>((resolve) => {
            release = resolve
        })
        const fetchMock = installFetch((_url, init) => (init?.method === 'POST' ? gate : json([])))
        const user = userEvent.setup({ applyAccept: false })
        renderManager()
        await screen.findByText(EMPTY_COPY)

        await user.upload(screen.getByLabelText('Evidence file'), new File(['hello'], 'once.log'))
        await user.selectOptions(screen.getByLabelText('Evidence type'), 'trace')
        await user.dblClick(screen.getByRole('button', { name: 'Upload evidence' }))

        const busy = screen.getByRole('button', { name: 'Uploading…' }) as HTMLButtonElement
        expect(busy.disabled).toBe(true)
        expect(postCalls(fetchMock)).toHaveLength(1)

        await act(async () => {
            release(json(makeEvidence({ id: 'ev-once', source_name: 'once.log' }), 201))
        })
        expect(await screen.findByText('Evidence uploaded')).toBeTruthy()
        expect(postCalls(fetchMock)).toHaveLength(1)
    })
})

describe('EvidenceManager content viewer', () => {
    const RAW = 'line one\n  indented line\t<b>not bold</b> & <script>alert(1)</script>\nlast line'

    it('fetches content only on View, using the incident and evidence ids, and renders it as text', async () => {
        const fetchMock = installFetch((url) =>
            url.endsWith('/content')
                ? new Response(RAW, {
                    status: 200,
                    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
                })
                : json([makeEvidence()]),
        )
        const user = userEvent.setup({ applyAccept: false })
        renderManager('inc-1')
        await screen.findByRole('list', { name: 'Evidence records' })
        expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/content'))).toBe(false)

        await user.click(screen.getByRole('button', { name: 'View checkout.log' }))

        const preview = await screen.findByRole('region', { name: 'Evidence content' })
        expect(preview.textContent).toBe(RAW)
        expect(preview.querySelector('b, script')).toBeNull()
        const contentCalls = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/content'))
        expect(contentCalls).toHaveLength(1)
        expect(String(contentCalls[0][0])).toMatch(/\/incidents\/inc-1\/evidence\/ev-1\/content$/)
    })

    it('shows a content error and recovers through retry', async () => {
        let contentCalls = 0
        installFetch((url) => {
            if (!url.endsWith('/content')) return json([makeEvidence()])
            contentCalls += 1
            return contentCalls === 1
                ? json({ detail: 'Evidence not found.' }, 404)
                : new Response('recovered text', { status: 200 })
        })
        const user = userEvent.setup({ applyAccept: false })
        renderManager()
        await screen.findByRole('list', { name: 'Evidence records' })

        await user.click(screen.getByRole('button', { name: 'View checkout.log' }))
        expect(await screen.findByText('Evidence not found.')).toBeTruthy()

        await user.click(screen.getByRole('button', { name: 'Retry loading content' }))
        const preview = await screen.findByRole('region', { name: 'Evidence content' })
        expect(preview.textContent).toBe('recovered text')
    })
})

describe('EvidenceManager incident switching', () => {
    it('clears the previous incident evidence immediately and shows the new one', async () => {
        let releaseB!: (response: Response) => void
        const gateB = new Promise<Response>((resolve) => {
            releaseB = resolve
        })
        installFetch((url) =>
            url.includes('/incidents/inc-a/')
                ? json([makeEvidence({ id: 'ev-a', incident_id: 'inc-a', source_name: 'alpha.log' })])
                : gateB,
        )

        const view = renderManager('inc-a')
        expect(await screen.findByText('alpha.log')).toBeTruthy()

        view.rerender(
            <ToastProvider>
                <EvidenceManager incidentId="inc-b" />
            </ToastProvider>,
        )

        expect(screen.queryByText('alpha.log')).toBeNull()
        expect(screen.getByText('Loading evidence…')).toBeTruthy()

        await act(async () => {
            releaseB(json([makeEvidence({ id: 'ev-b', incident_id: 'inc-b', source_name: 'beta.log' })]))
        })
        expect(await screen.findByText('beta.log')).toBeTruthy()
        expect(screen.queryByText('alpha.log')).toBeNull()
    })

    it('ignores a late response from the previously selected incident', async () => {
        let releaseA!: (response: Response) => void
        const gateA = new Promise<Response>((resolve) => {
            releaseA = resolve
        })
        installFetch((url) =>
            url.includes('/incidents/inc-a/')
                ? gateA
                : json([makeEvidence({ id: 'ev-b', incident_id: 'inc-b', source_name: 'beta.log' })]),
        )

        const view = renderManager('inc-a')
        view.rerender(
            <ToastProvider>
                <EvidenceManager incidentId="inc-b" />
            </ToastProvider>,
        )
        expect(await screen.findByText('beta.log')).toBeTruthy()

        await act(async () => {
            releaseA(
                json([makeEvidence({ id: 'ev-a', incident_id: 'inc-a', source_name: 'late-alpha.log' })]),
            )
            await new Promise((resolve) => setTimeout(resolve, 20))
        })

        expect(screen.queryByText('late-alpha.log')).toBeNull()
        expect(screen.getByText('beta.log')).toBeTruthy()
    })
})