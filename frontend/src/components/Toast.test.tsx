import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { ToastProvider, useToast } from './Toast'
import type { ToastInput } from './Toast'

function Harness({ onFire }: { onFire: (push: (toast: ToastInput) => void) => void }) {
  const { push } = useToast()
  return <button onClick={() => onFire(push)}>fire</button>
}

/** Render the provider with a button that pushes whatever the test needs. */
function renderToasts(toasts: ToastInput[], durationMs?: number) {
  return render(
    <ToastProvider durationMs={durationMs}>
      <Harness onFire={(push) => toasts.forEach((toast) => push(toast))} />
    </ToastProvider>,
  )
}

describe('Toast', () => {
  it('shows a success toast announced politely', async () => {
    renderToasts([{ kind: 'success', title: 'Incident created' }])
    await userEvent.click(screen.getByRole('button', { name: 'fire' }))

    const toast = await screen.findByRole('status')
    expect(toast).toHaveTextContent('Incident created')
  })

  it('shows an error toast with its message and asserts it to AT', async () => {
    renderToasts([
      { kind: 'error', title: 'Could not save', message: 'Incident not found.' },
    ])
    await userEvent.click(screen.getByRole('button', { name: 'fire' }))

    const toast = await screen.findByRole('alert')
    expect(toast).toHaveTextContent('Could not save')
    expect(toast).toHaveTextContent('Incident not found.')
  })

  it('stacks multiple toasts', async () => {
    renderToasts([
      { kind: 'success', title: 'One' },
      { kind: 'success', title: 'Two' },
    ])
    await userEvent.click(screen.getByRole('button', { name: 'fire' }))

    await waitFor(() => expect(screen.getAllByRole('status')).toHaveLength(2))
    expect(screen.getByText('One')).toBeInTheDocument()
    expect(screen.getByText('Two')).toBeInTheDocument()
  })

  it('dismisses automatically', async () => {
    renderToasts([{ kind: 'success', title: 'Auto' }], 80)
    await userEvent.click(screen.getByRole('button', { name: 'fire' }))

    expect(screen.getByRole('status')).toBeInTheDocument()

    await waitFor(
      () => expect(screen.queryByRole('status')).not.toBeInTheDocument(),
      { timeout: 2000, interval: 50 },
    )
  })

  it('can be dismissed manually', async () => {
    renderToasts([{ kind: 'error', title: 'Sticky failure' }])
    await userEvent.click(screen.getByRole('button', { name: 'fire' }))

    await userEvent.click(await screen.findByRole('button', { name: /dismiss/i }))

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
