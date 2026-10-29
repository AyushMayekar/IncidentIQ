import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import {
  checkHealth,
  createIncident,
  deleteIncident,
  getIncident,
  listIncidents,
  updateIncident,
} from './api/incidents'
import type { Incident } from './api/types'

vi.mock('./api/incidents', () => ({
  listIncidents: vi.fn(),
  createIncident: vi.fn(),
  getIncident: vi.fn(),
  updateIncident: vi.fn(),
  deleteIncident: vi.fn(),
  checkHealth: vi.fn(),
}))

const mocked = {
  listIncidents: vi.mocked(listIncidents),
  createIncident: vi.mocked(createIncident),
  getIncident: vi.mocked(getIncident),
  updateIncident: vi.mocked(updateIncident),
  deleteIncident: vi.mocked(deleteIncident),
  checkHealth: vi.mocked(checkHealth),
}

function makeIncident(overrides: Partial<Incident> = {}): Incident {
  return {
    id: '3f1a4c1e-0000-4000-8000-000000000001',
    title: 'Checkout API elevated 5xx errors',
    description: 'Checkout requests are failing with HTTP 502 for ~12% of sessions.',
    service: 'checkout-api',
    severity: 'high',
    status: 'open',
    occurred_at: null,
    created_at: '2026-01-05T09:30:00Z',
    updated_at: '2026-01-05T09:30:00Z',
    ...overrides,
  }
}

const first = makeIncident()
const second = makeIncident({
  id: '3f1a4c1e-0000-4000-8000-000000000002',
  title: 'Payments latency spike',
  service: 'payments-api',
  severity: 'medium',
  status: 'investigating',
})

function givenIncidents(items: Incident[], total = items.length) {
  mocked.listIncidents.mockResolvedValue({ items, total, limit: 20, offset: 0 })
  mocked.getIncident.mockImplementation(async (id) => {
    const found = items.find((i) => i.id === id)
    if (!found) throw new Error('Incident not found.')
    return found
  })
}

async function renderApp() {
  const view = render(<App />)
  await waitFor(() => expect(mocked.listIncidents).toHaveBeenCalled())
  return view
}

/** The incident title renders in the list row *and* the detail panel. */
const list = () => screen.getByRole('list')
const inList = (text: string) => within(list()).getByText(text)
const missingFromList = (text: string) =>
  expect(within(list()).queryByText(text)).not.toBeInTheDocument()
const successToast = () => screen.findByTestId('toast-success')
const errorToast = () => screen.findByTestId('toast-error')

beforeEach(() => {
  vi.clearAllMocks()
  mocked.checkHealth.mockResolvedValue(true)
})

describe('App — workspace', () => {
  it('renders incidents, stats and an online API badge', async () => {
    givenIncidents([first, second])

    await renderApp()

    expect(await waitFor(() => inList(first.title))).toBeInTheDocument()
    expect(inList(second.title)).toBeInTheDocument()
    expect(screen.getByText('API online')).toBeInTheDocument()
  })

  it('offers a healthy empty state when there are no incidents', async () => {
    givenIncidents([])

    await renderApp()

    expect(await screen.findByText('No incidents yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create incident' })).toBeInTheDocument()
  })

  it('never renders development-stage copy', async () => {
    givenIncidents([first])

    const { container } = await renderApp()
    await waitFor(() => inList(first.title))

    const text = container.textContent ?? ''
    expect(text).not.toMatch(/MVP/i)
    expect(text).not.toMatch(/vertical slice/i)
    expect(text).not.toMatch(/Development environment/i)
    expect(text).not.toMatch(/next build slices/i)
    expect(text).not.toMatch(/API-connected/i)
    expect(text).not.toMatch(/PostgreSQL/i)
  })

  it('shows the product logo in the sidebar', async () => {
    givenIncidents([first])

    await renderApp()

    const logo = await screen.findByAltText('IncidentIQ logo')
    expect(logo).toBeInTheDocument()
    expect(logo.getAttribute('src')).toContain('logo.svg')
  })

  it('filters the list by search text', async () => {
    givenIncidents([first, second])
    const user = userEvent.setup()
    await renderApp()
    await waitFor(() => inList(first.title))

    await user.type(screen.getByLabelText('Search incidents'), 'payments')

    await waitFor(() => missingFromList(first.title))
    expect(inList(second.title)).toBeInTheDocument()
  })

  it('filters the list by status', async () => {
    givenIncidents([first, second])
    const user = userEvent.setup()
    await renderApp()
    await waitFor(() => inList(first.title))

    await user.selectOptions(screen.getByLabelText('Filter by status'), 'investigating')

    await waitFor(() => missingFromList(first.title))
    expect(inList(second.title)).toBeInTheDocument()
  })

  it('loads the next page with offset', async () => {
    givenIncidents([first], 40)
    const user = userEvent.setup()
    await renderApp()
    await waitFor(() => inList(first.title))

    await user.click(screen.getByRole('button', { name: 'Load more' }))

    await waitFor(() =>
      expect(mocked.listIncidents).toHaveBeenCalledWith({ limit: 20, offset: 1 }),
    )
  })

  it('reports a failure when the list cannot be loaded', async () => {
    mocked.listIncidents.mockRejectedValue(new Error('Could not reach the IncidentIQ API.'))
    const { container } = render(<App />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load incidents')
    expect(container.textContent).toContain('Could not reach the IncidentIQ API.')
  })
})

describe('App — create incident', () => {
  it('creates an incident after confirmation and confirms success', async () => {
    const created = makeIncident({
      id: 'new-1',
      title: 'Search cluster degraded',
      description: 'Queries timing out.',
      severity: 'critical',
      status: 'open',
    })
    givenIncidents([])
    mocked.createIncident.mockResolvedValue(created)
    mocked.getIncident.mockResolvedValue(created)
    const user = userEvent.setup()
    await renderApp()

    await user.click(await screen.findByRole('button', { name: '+ New incident' }))
    const form = await screen.findByRole('dialog', { name: 'Create incident' })
    await user.type(within(form).getByLabelText(/incident title/i), 'Search cluster degraded')
    await user.type(within(form).getByLabelText(/^description/i), 'Queries timing out.')
    await user.selectOptions(within(form).getByLabelText(/severity/i), 'critical')
    await user.click(within(form).getByRole('button', { name: 'Create incident' }))

    // confirmation step
    const confirm = await screen.findByRole('dialog', { name: 'Create this incident?' })
    await user.click(within(confirm).getByRole('button', { name: 'Create incident' }))

    await waitFor(() => expect(mocked.createIncident).toHaveBeenCalledTimes(1))
    expect(mocked.createIncident).toHaveBeenCalledWith({
      title: 'Search cluster degraded',
      description: 'Queries timing out.',
      service: null,
      severity: 'critical',
      occurred_at: null,
    })
    expect(await successToast()).toHaveTextContent('Incident created')
    expect(await waitFor(() => inList('Search cluster degraded'))).toBeInTheDocument()
  })

  it('keeps the form open and shows an error when creation fails', async () => {
    givenIncidents([])
    mocked.createIncident.mockRejectedValue(new Error('Title is already in use.'))
    const user = userEvent.setup()
    await renderApp()

    await user.click(await screen.findByRole('button', { name: '+ New incident' }))
    const form = await screen.findByRole('dialog', { name: 'Create incident' })
    await user.type(within(form).getByLabelText(/incident title/i), 'Duplicate title')
    await user.type(within(form).getByLabelText(/^description/i), 'Something broke.')
    await user.click(within(form).getByRole('button', { name: 'Create incident' }))
    const confirm = await screen.findByRole('dialog', { name: 'Create this incident?' })
    await user.click(within(confirm).getByRole('button', { name: 'Create incident' }))

    const alert = await errorToast()
    expect(alert).toHaveTextContent('Could not create the incident')
    expect(alert).toHaveTextContent('Title is already in use.')
    // the record must not appear in the workspace
    expect(screen.queryByText('Duplicate title')).not.toBeInTheDocument()
  })
})

describe('App — edit incident', () => {
  it('saves edits after confirmation', async () => {
    const updated = { ...first, title: 'Checkout API — mitigated' }
    givenIncidents([first, second])
    mocked.updateIncident.mockResolvedValue(updated)
    const user = userEvent.setup()
    await renderApp()
    await waitFor(() => inList(first.title))

    await user.click(screen.getByRole('button', { name: 'Edit incident' }))
    const form = await screen.findByRole('dialog', { name: 'Edit incident' })
    const titleInput = within(form).getByLabelText(/incident title/i)
    await user.clear(titleInput)
    await user.type(titleInput, 'Checkout API — mitigated')
    await user.click(within(form).getByRole('button', { name: 'Save changes' }))

    const confirm = await screen.findByRole('dialog', { name: 'Save your changes?' })
    await user.click(within(confirm).getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(mocked.updateIncident).toHaveBeenCalledTimes(1))
    expect(mocked.updateIncident).toHaveBeenCalledWith('3f1a4c1e-0000-4000-8000-000000000001', {
      title: 'Checkout API — mitigated',
      description: first.description,
      service: 'checkout-api',
      severity: 'high',
      occurred_at: null,
    })
    expect(await successToast()).toHaveTextContent('Changes saved')
    expect(await waitFor(() => inList('Checkout API — mitigated'))).toBeInTheDocument()
  })

  it('does not call the API when the save is cancelled', async () => {
    givenIncidents([first, second])
    const user = userEvent.setup()
    await renderApp()
    await waitFor(() => inList(first.title))

    await user.click(screen.getByRole('button', { name: 'Edit incident' }))
    const form = await screen.findByRole('dialog', { name: 'Edit incident' })
    await user.click(within(form).getByRole('button', { name: 'Save changes' }))
    const confirm = await screen.findByRole('dialog', { name: 'Save your changes?' })
    await user.click(within(confirm).getByRole('button', { name: 'Cancel' }))

    expect(mocked.updateIncident).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog', { name: 'Save your changes?' })).not.toBeInTheDocument()
  })
})

describe('App — change status', () => {
  it('moves an incident to a new status after confirmation', async () => {
    const updated = { ...first, status: 'investigating' as const }
    givenIncidents([first, second])
    mocked.updateIncident.mockResolvedValue(updated)
    const user = userEvent.setup()
    await renderApp()
    await waitFor(() => inList(first.title))

    await user.selectOptions(screen.getByLabelText('Change status'), 'investigating')

    const confirm = await screen.findByRole('dialog', { name: 'Change status?' })
    expect(confirm).toHaveTextContent('will move to investigating')
    await user.click(within(confirm).getByRole('button', { name: 'Change status' }))

    await waitFor(() =>
      expect(mocked.updateIncident).toHaveBeenCalledWith(first.id, {
        status: 'investigating',
      }),
    )
    expect(await successToast()).toHaveTextContent('Status updated')
  })

  it('reverts the selector when the change is cancelled', async () => {
    givenIncidents([first, second])
    const user = userEvent.setup()
    await renderApp()
    await waitFor(() => inList(first.title))

    await user.selectOptions(screen.getByLabelText('Change status'), 'closed')
    const confirm = await screen.findByRole('dialog', { name: 'Change status?' })
    await user.click(within(confirm).getByRole('button', { name: 'Cancel' }))

    expect(mocked.updateIncident).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Change status')).toHaveValue('open')
  })

  it('surfaces a failure when the status cannot be changed', async () => {
    givenIncidents([first, second])
    mocked.updateIncident.mockRejectedValue(new Error('Incident not found.'))
    const user = userEvent.setup()
    await renderApp()
    await waitFor(() => inList(first.title))

    await user.selectOptions(screen.getByLabelText('Change status'), 'closed')
    const confirm = await screen.findByRole('dialog', { name: 'Change status?' })
    await user.click(within(confirm).getByRole('button', { name: 'Change status' }))

    expect(await errorToast()).toHaveTextContent('Could not update the status')
  })
})

describe('App — delete incident', () => {
  it('deletes after confirmation and confirms success', async () => {
    givenIncidents([first, second])
    mocked.deleteIncident.mockResolvedValue(undefined)
    const user = userEvent.setup()
    await renderApp()
    await waitFor(() => inList(first.title))

    await user.click(screen.getByRole('button', { name: 'Delete' }))

    const confirm = await screen.findByRole('dialog', { name: 'Delete this incident?' })
    expect(confirm).toHaveTextContent('cannot be undone')
    await user.click(within(confirm).getByRole('button', { name: 'Delete incident' }))

    await waitFor(() => expect(mocked.deleteIncident).toHaveBeenCalledWith(first.id))
    expect(await successToast()).toHaveTextContent('Incident deleted')
    await waitFor(() => missingFromList(first.title))
  })

  it('keeps the incident when deletion is cancelled', async () => {
    givenIncidents([first, second])
    const user = userEvent.setup()
    await renderApp()
    await waitFor(() => inList(first.title))

    await user.click(screen.getByRole('button', { name: 'Delete' }))
    const confirm = await screen.findByRole('dialog', { name: 'Delete this incident?' })
    await user.click(within(confirm).getByRole('button', { name: 'Cancel' }))

    expect(mocked.deleteIncident).not.toHaveBeenCalled()
    expect(inList(first.title)).toBeInTheDocument()
  })

  it('shows an error when deletion fails', async () => {
    givenIncidents([first, second])
    mocked.deleteIncident.mockRejectedValue(new Error('Incident not found.'))
    const user = userEvent.setup()
    await renderApp()
    await waitFor(() => inList(first.title))

    await user.click(screen.getByRole('button', { name: 'Delete' }))
    const confirm = await screen.findByRole('dialog', { name: 'Delete this incident?' })
    await user.click(within(confirm).getByRole('button', { name: 'Delete incident' }))

    expect(await errorToast()).toHaveTextContent('Could not delete the incident')
    expect(inList(first.title)).toBeInTheDocument()
  })
})
