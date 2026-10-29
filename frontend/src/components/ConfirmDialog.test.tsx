import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ConfirmDialog } from './ConfirmDialog'

describe('ConfirmDialog', () => {
  it('renders title, description and action labels', () => {
    render(
      <ConfirmDialog
        open
        title="Delete incident?"
        description="This permanently removes the incident record."
        confirmLabel="Delete incident"
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    )

    expect(
      screen.getByRole('dialog', { name: 'Delete incident?' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText('This permanently removes the incident record.'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Delete incident' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
  })

  it('calls onConfirm when confirmed', async () => {
    const onConfirm = vi.fn()
    render(
      <ConfirmDialog
        open
        title="Save changes?"
        description="Update the incident."
        confirmLabel="Save changes"
        onCancel={vi.fn()}
        onConfirm={onConfirm}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('never confirms when cancelled', async () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    render(
      <ConfirmDialog
        open
        title="Delete incident?"
        description="Irreversible."
        confirmLabel="Delete"
        onCancel={onCancel}
        onConfirm={onConfirm}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('cancels on Escape', async () => {
    const onCancel = vi.fn()
    render(
      <ConfirmDialog
        open
        title="Delete incident?"
        description="Irreversible."
        confirmLabel="Delete"
        onCancel={onCancel}
        onConfirm={vi.fn()}
      />,
    )

    await userEvent.keyboard('{Escape}')

    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('blocks confirmation while busy', async () => {
    const onConfirm = vi.fn()
    render(
      <ConfirmDialog
        open
        busy
        title="Delete incident?"
        description="Irreversible."
        confirmLabel="Delete"
        onCancel={vi.fn()}
        onConfirm={onConfirm}
      />,
    )

    const confirm = screen.getByRole('button', { name: 'Delete' })
    expect(confirm).toBeDisabled()
    await userEvent.click(confirm)

    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('renders nothing when closed', () => {
    const { container } = render(
      <ConfirmDialog
        open={false}
        title="Delete incident?"
        description="Irreversible."
        confirmLabel="Delete"
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    )

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(container).toBeEmptyDOMElement()
  })
})
