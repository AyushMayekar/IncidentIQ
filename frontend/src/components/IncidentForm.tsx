import { useState } from 'react'
import type { FormEvent } from 'react'
import { SEVERITIES } from '../api/types'
import type { Incident, IncidentCreateInput, Severity } from '../api/types'

/** `datetime-local` needs a local `YYYY-MM-DDTHH:mm` value, not an ISO string. */
function toLocalInputValue(value: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`
}

const SEVERITY_LABEL: Record<Severity, string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  critical: 'Critical',
}

export interface IncidentFormProps {
  mode: 'create' | 'edit'
  /** Incident being edited; ignored in `create` mode. */
  incident?: Incident
  busy?: boolean
  onSubmit: (values: IncidentCreateInput) => void
  onCancel: () => void
}

/**
 * Shared create/edit form. Validation is ours (not the browser's) so the same
 * messages appear in every browser and in tests.
 */
export function IncidentForm({
  mode,
  incident,
  busy = false,
  onSubmit,
  onCancel,
}: IncidentFormProps) {
  const [title, setTitle] = useState(incident?.title ?? '')
  const [description, setDescription] = useState(incident?.description ?? '')
  const [service, setService] = useState(incident?.service ?? '')
  const [severity, setSeverity] = useState<Severity>(incident?.severity ?? 'medium')
  const [occurredAt, setOccurredAt] = useState(toLocalInputValue(incident?.occurred_at ?? null))
  const [error, setError] = useState('')

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return

    if (!title.trim()) {
      setError('Incident title is required.')
      return
    }
    if (!description.trim()) {
      setError('Description is required — capture what users are experiencing.')
      return
    }

    setError('')
    onSubmit({
      title: title.trim(),
      description: description.trim(),
      service: service.trim() || null,
      severity,
      occurred_at: occurredAt ? new Date(occurredAt).toISOString() : null,
    })
  }

  const submitLabel = mode === 'create' ? 'Create incident' : 'Save changes'

  return (
    <form className="form" onSubmit={handleSubmit} noValidate>
      {error && (
        <div className="form__alert" role="alert">
          <span aria-hidden="true">!</span>
          {error}
        </div>
      )}

      <label className="field">
        <span className="field__label">
          Incident title <em>required</em>
        </span>
        <input
          name="title"
          maxLength={200}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="e.g. Checkout API elevated 5xx errors"
          autoFocus
        />
      </label>

      <label className="field">
        <span className="field__label">
          Description <em>required</em>
        </span>
        <textarea
          name="description"
          rows={4}
          maxLength={20000}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="What happened? What are users experiencing?"
        />
      </label>

      <div className="form-grid">
        <label className="field">
          <span className="field__label">Service</span>
          <input
            name="service"
            maxLength={200}
            value={service}
            onChange={(event) => setService(event.target.value)}
            placeholder="e.g. checkout-api"
          />
        </label>

        <label className="field">
          <span className="field__label">Severity</span>
          <select
            name="severity"
            value={severity}
            onChange={(event) => setSeverity(event.target.value as Severity)}
          >
            {SEVERITIES.map((level) => (
              <option key={level} value={level}>
                {SEVERITY_LABEL[level]}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="field">
        <span className="field__label">
          When did it occur? <small>optional</small>
        </span>
        <input
          name="occurred_at"
          type="datetime-local"
          value={occurredAt}
          onChange={(event) => setOccurredAt(event.target.value)}
        />
      </label>

      <div className="form-actions">
        <button type="button" className="btn btn--ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button type="submit" className="btn btn--primary" disabled={busy} aria-busy={busy}>
          {busy && <span className="btn__spinner" aria-hidden="true" />}
          {submitLabel}
        </button>
      </div>
    </form>
  )
}
