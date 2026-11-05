import { useCallback, useEffect, useState } from 'react'
import { deleteIncident, getIncident, updateIncident } from '../api/incidents'
import type { Incident, IncidentCreateInput, IncidentStatus, Severity } from '../api/types'
import { SEVERITIES, STATUSES } from '../api/types'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EvidenceManager } from '../components/EvidenceManager'
import { IncidentForm } from '../components/IncidentForm'
import { Modal } from '../components/Modal'
import { useToast } from '../components/Toast'
import { Fact, Pill, formatDate } from '../components/atoms'

type Tab = 'overview' | 'evidence'

interface IncidentWorkspacePageProps {
  incidentId: string
  onBack: () => void
  onDeleted: () => void
}

function label(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1)
}

/** Every incident-specific action lives here, behind a dedicated URL. */
export function IncidentWorkspacePage({
  incidentId,
  onBack,
  onDeleted,
}: IncidentWorkspacePageProps) {
  const { push } = useToast()
  const [incident, setIncident] = useState<Incident | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('overview')
  const [editOpen, setEditOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [updating, setUpdating] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      setIncident(await getIncident(incidentId))
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Unexpected error.')
    } finally {
      setLoading(false)
    }
  }, [incidentId])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [load])

  async function handleSave(values: IncidentCreateInput) {
    if (!incident) return
    setBusy(true)
    try {
      const updated = await updateIncident(incident.id, values)
      setIncident(updated)
      setEditOpen(false)
      push({ kind: 'success', title: 'Changes saved', message: updated.title })
    } catch (error) {
      push({
        kind: 'error',
        title: 'Could not save your changes',
        message: error instanceof Error ? error.message : 'Unexpected error.',
      })
    } finally {
      setBusy(false)
    }
  }

  async function handleStatus(next: IncidentStatus) {
    if (!incident || next === incident.status || updating) return
    setUpdating(true)
    try {
      const updated = await updateIncident(incident.id, { status: next })
      setIncident(updated)
      push({
        kind: 'success',
        title: 'Status updated',
        message: `Now ${label(updated.status)}.`,
      })
    } catch (error) {
      push({
        kind: 'error',
        title: 'Could not update the status',
        message: error instanceof Error ? error.message : 'Unexpected error.',
      })
    } finally {
      setUpdating(false)
    }
  }

  async function handleSeverity(next: Severity) {
    if (!incident || next === incident.severity || updating) return
    setUpdating(true)
    try {
      const updated = await updateIncident(incident.id, { severity: next })
      setIncident(updated)
      push({
        kind: 'success',
        title: 'Severity updated',
        message: `Now ${label(updated.severity)}.`,
      })
    } catch (error) {
      push({
        kind: 'error',
        title: 'Could not update the severity',
        message: error instanceof Error ? error.message : 'Unexpected error.',
      })
    } finally {
      setUpdating(false)
    }
  }

  async function handleDelete() {
    if (!incident) return
    setBusy(true)
    try {
      await deleteIncident(incident.id)
      push({ kind: 'success', title: 'Incident deleted', message: incident.title })
      setDeleteOpen(false)
      onDeleted()
    } catch (error) {
      push({
        kind: 'error',
        title: 'Could not delete the incident',
        message: error instanceof Error ? error.message : 'Unexpected error.',
      })
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return (
      <div className="content">
        <div className="state" role="status">
          <span className="spinner" />
          <b>Loading incident</b>
          <p>Fetching the workspace…</p>
        </div>
      </div>
    )
  }

  if (!incident) {
    return (
      <div className="content">
        <div className="state">
          <span className="state__glyph" aria-hidden="true">
            ▧
          </span>
          <b>Incident unavailable</b>
          <p>{loadError ?? 'This incident could not be loaded.'}</p>
          <div className="heading__actions">
            <button type="button" className="btn btn--ghost btn--sm" onClick={onBack}>
              ← Back to incidents
            </button>
            <button type="button" className="btn btn--primary btn--sm" onClick={() => void load()}>
              Try again
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="content">
      <section className="heading workspace-heading">
        <div>
          <button type="button" className="back-link" onClick={onBack}>
            ← Back to incidents
          </button>
          <small className="eyebrow">Incident workspace</small>
          <h1>{incident.title}</h1>
          <div className="detail-meta">
            <Pill kind="status" value={incident.status} />
            <Pill kind="severity" value={incident.severity} />
            <span className="service">{incident.service || 'No service assigned'}</span>
            {updating && <span className="detail-loading">Updating…</span>}
          </div>
        </div>
        <div className="heading__actions">
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => setEditOpen(true)}
          >
            Edit incident
          </button>
          <button
            type="button"
            className="btn btn--danger btn--sm"
            onClick={() => setDeleteOpen(true)}
          >
            Delete
          </button>
        </div>
      </section>

      <div className="workspace-tabs" role="tablist" aria-label="Incident sections">
        <button
          type="button"
          role="tab"
          id="tab-overview"
          aria-selected={tab === 'overview'}
          aria-controls="panel-overview"
          className={`workspace-tab ${tab === 'overview' ? 'workspace-tab--active' : ''}`}
          onClick={() => setTab('overview')}
        >
          Overview
        </button>
        <button
          type="button"
          role="tab"
          id="tab-evidence"
          aria-selected={tab === 'evidence'}
          aria-controls="panel-evidence"
          className={`workspace-tab ${tab === 'evidence' ? 'workspace-tab--active' : ''}`}
          onClick={() => setTab('evidence')}
        >
          Evidence
        </button>
      </div>

      {tab === 'overview' ? (
        <section
          id="panel-overview"
          role="tabpanel"
          aria-labelledby="tab-overview"
          className="workspace-panel"
        >
          <div className="detail-panel workspace-panel__card">
            <div className="status-control status-control--grid">
              <label className="field">
                <span className="field__label">Status</span>
                <select
                  aria-label="Change status"
                  value={incident.status}
                  disabled={updating}
                  onChange={(event) =>
                    void handleStatus(event.target.value as IncidentStatus)
                  }
                >
                  {STATUSES.map((status) => (
                    <option key={status} value={status}>
                      {label(status)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field__label">Severity</span>
                <select
                  aria-label="Change severity"
                  value={incident.severity}
                  disabled={updating}
                  onChange={(event) =>
                    void handleSeverity(event.target.value as Severity)
                  }
                >
                  {SEVERITIES.map((severity) => (
                    <option key={severity} value={severity}>
                      {label(severity)}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <section className="detail-section">
              <h3>Description</h3>
              <p>{incident.description || 'No description provided.'}</p>
            </section>

            <section className="detail-section">
              <h3>Incident details</h3>
              <div className="facts">
                <Fact label="Incident ID" value={incident.id} mono />
                <Fact label="Occurred at" value={formatDate(incident.occurred_at)} />
                <Fact label="Created" value={formatDate(incident.created_at)} />
                <Fact label="Last updated" value={formatDate(incident.updated_at)} />
              </div>
            </section>
          </div>
        </section>
      ) : (
        <section
          id="panel-evidence"
          role="tabpanel"
          aria-labelledby="tab-evidence"
          className="workspace-panel"
        >
          <div className="workspace-panel__card">
            <EvidenceManager key={incident.id} incidentId={incident.id} />
          </div>
        </section>
      )}

      <Modal
        open={editOpen}
        eyebrow="Incident record"
        title="Edit incident"
        subtitle="Changes are applied immediately."
        onClose={() => !busy && setEditOpen(false)}
      >
        <IncidentForm
          mode="edit"
          incident={incident}
          busy={busy}
          onSubmit={(values) => void handleSave(values)}
          onCancel={() => setEditOpen(false)}
        />
      </Modal>

      <ConfirmDialog
        open={deleteOpen}
        tone="danger"
        title="Delete this incident?"
        description={`"${incident.title}" will be permanently removed together with its evidence and parsed records. This cannot be undone.`}
        confirmLabel="Delete incident"
        busy={busy}
        onCancel={() => setDeleteOpen(false)}
        onConfirm={() => void handleDelete()}
      />
    </div>
  )
}
