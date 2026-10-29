import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { IncidentForm } from './IncidentForm'
import type { Incident } from '../api/types'

const editing: Incident = {
  id: '3f1a4c1e-0000-4000-8000-000000000001',
  title: 'Checkout API elevated 5xx errors',
  description: 'Checkout requests are failing with HTTP 502.',
  service: 'checkout-api',
  severity: 'high',
  status: 'open',
  occurred_at: '2026-01-05T09:30:00Z',
  created_at: '2026-01-05T09:30:00Z',
  updated_at: '2026-01-05T09:30:00Z',
}

describe('IncidentForm', () => {
  it('starts blank when creating', () => {
    render(<IncidentForm mode="create" onSubmit={vi.fn()} onCancel={vi.fn()} />)

    expect(screen.getByLabelText(/incident title/i)).toHaveValue('')
    expect(screen.getByLabelText(/^description/i)).toHaveValue('')
    expect(screen.getByLabelText(/service/i)).toHaveValue('')
    expect(screen.getByLabelText(/severity/i)).toHaveValue('medium')
  })

  it('prefills every field when editing', () => {
    render(<IncidentForm mode="edit" incident={editing} onSubmit={vi.fn()} onCancel={vi.fn()} />)

    expect(screen.getByLabelText(/incident title/i)).toHaveValue(editing.title)
    expect(screen.getByLabelText(/^description/i)).toHaveValue(editing.description)
    expect(screen.getByLabelText(/service/i)).toHaveValue('checkout-api')
    expect(screen.getByLabelText(/severity/i)).toHaveValue('high')
  })

  it('blocks submission and explains a blank title', async () => {
    const onSubmit = vi.fn()
    render(<IncidentForm mode="create" onSubmit={onSubmit} onCancel={vi.fn()} />)

    await userEvent.type(screen.getByLabelText(/incident title/i), '   ')
    await userEvent.click(screen.getByRole('button', { name: /create incident/i }))

    expect(onSubmit).not.toHaveBeenCalled()
    expect(await screen.findByRole('alert')).toHaveTextContent(/title/i)
  })

  it('blocks submission when the description is blank', async () => {
    const onSubmit = vi.fn()
    render(<IncidentForm mode="create" onSubmit={onSubmit} onCancel={vi.fn()} />)

    await userEvent.type(screen.getByLabelText(/incident title/i), 'Payments latency spike')
    await userEvent.click(screen.getByRole('button', { name: /create incident/i }))

    expect(onSubmit).not.toHaveBeenCalled()
    expect(await screen.findByRole('alert')).toHaveTextContent(/description/i)
  })

  it('submits a trimmed payload with ISO occurred_at', async () => {
    const onSubmit = vi.fn()
    render(<IncidentForm mode="create" onSubmit={onSubmit} onCancel={vi.fn()} />)

    await userEvent.type(screen.getByLabelText(/incident title/i), '  Payments latency spike  ')
    await userEvent.type(
      screen.getByLabelText(/^description/i),
      '  p99 latency above 4s.  ',
    )
    await userEvent.type(screen.getByLabelText(/service/i), ' payments-api ')
    await userEvent.selectOptions(screen.getByLabelText(/severity/i), 'critical')
    await userEvent.type(screen.getByLabelText(/when did it occur/i), '2026-01-05T09:30')
    await userEvent.click(screen.getByRole('button', { name: /create incident/i }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit).toHaveBeenCalledWith({
      title: 'Payments latency spike',
      description: 'p99 latency above 4s.',
      service: 'payments-api',
      severity: 'critical',
      occurred_at: expect.stringMatching(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/),
    })
    // The local wall-clock time the operator picked is preserved exactly.
    expect(new Date(onSubmit.mock.calls[0][0].occurred_at as string).getTime()).toBe(
      new Date('2026-01-05T09:30').getTime(),
    )
  })

  it('sends occurred_at as null when left empty', async () => {
    const onSubmit = vi.fn()
    render(<IncidentForm mode="create" onSubmit={onSubmit} onCancel={vi.fn()} />)

    await userEvent.type(screen.getByLabelText(/incident title/i), 'No timestamp')
    await userEvent.type(screen.getByLabelText(/^description/i), 'Details here')
    await userEvent.click(screen.getByRole('button', { name: /create incident/i }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit.mock.calls[0][0].occurred_at).toBeNull()
  })

  it('cancels without submitting', async () => {
    const onSubmit = vi.fn()
    const onCancel = vi.fn()
    render(<IncidentForm mode="create" onSubmit={onSubmit} onCancel={onCancel} />)

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('locks the form while busy', async () => {
    const onSubmit = vi.fn()
    render(
      <IncidentForm mode="create" busy onSubmit={onSubmit} onCancel={vi.fn()} />,
    )

    await userEvent.type(screen.getByLabelText(/incident title/i), 'Locked')
    await userEvent.type(screen.getByLabelText(/^description/i), 'Still locked')
    await userEvent.click(screen.getByRole('button', { name: /create incident/i }))

    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /create incident/i })).toBeDisabled()
  })
})
