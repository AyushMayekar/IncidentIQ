import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  checkHealth,
  createIncident,
  deleteIncident,
  getIncident,
  listIncidents,
  updateIncident,
} from './api/incidents'
import type { Incident, IncidentCreateInput, IncidentStatus } from './api/types'
import { ConfirmDialog } from './components/ConfirmDialog'
import { IncidentForm } from './components/IncidentForm'
import { Modal } from './components/Modal'
import { ToastProvider, useToast } from './components/Toast'
import { Fact, Pill, Stat, formatDate, statusCounts } from './components/atoms'
import logoUrl from '../logo.svg'
import './App.css'

const PAGE_SIZE = 20

type Pending =
  | { kind: 'create'; values: IncidentCreateInput }
  | { kind: 'edit'; id: string; values: IncidentCreateInput }
  | { kind: 'status'; id: string; status: IncidentStatus; title: string }
  | { kind: 'delete'; id: string; title: string }
  | null

function Workspace() {
  const { push } = useToast()

  const [items, setItems] = useState<Incident[]>([])
  const [total, setTotal] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | IncidentStatus>('all')
  const [formOpen, setFormOpen] = useState<null | 'create' | 'edit'>(null)
  const [pending, setPending] = useState<Pending>(null)
  const [apiOnline, setApiOnline] = useState<boolean | null>(null)

  const fail = useCallback((error: unknown, fallback: string) => {
    push({
      kind: 'error',
      title: fallback,
      message: error instanceof Error ? error.message : 'Unexpected error.',
    })
  }, [push])

  const load = useCallback(async () => {
    try {
      const result = await listIncidents({ limit: PAGE_SIZE, offset: 0 })
      setItems(result.items)
      setTotal(result.total)
      setSelectedId((current) =>
        current && result.items.some((i) => i.id === current)
          ? current
          : (result.items[0]?.id ?? null),
      )
    } catch (error) {
      fail(error, 'Could not load incidents')
    } finally {
      setLoading(false)
    }
  }, [fail])

  const loadMore = useCallback(async () => {
    setLoadingMore(true)
    try {
      const offset = items.length
      const result = await listIncidents({ limit: PAGE_SIZE, offset })
      setItems((current) => {
        const seen = new Set(current.map((i) => i.id))
        return [...current, ...result.items.filter((i) => !seen.has(i.id))]
      })
      setTotal(result.total)
    } catch (error) {
      fail(error, 'Could not load more incidents')
    } finally {
      setLoadingMore(false)
    }
  }, [items.length, fail])

  useEffect(() => {
    // First page load on mount; the skeleton comes from the initial state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [load])

  useEffect(() => {
    let cancelled = false
    const ping = async () => {
      const online = await checkHealth()
      if (!cancelled) setApiOnline(online)
    }
    void ping()
    const timer = setInterval(() => void ping(), 30000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  const selected = useMemo(
    () => items.find((i) => i.id === selectedId) ?? null,
    [items, selectedId],
  )

  const visible = useMemo(() => {
    const query = search.trim().toLowerCase()
    return items.filter(
      (incident) =>
        (statusFilter === 'all' || incident.status === statusFilter) &&
        (!query ||
          `${incident.title} ${incident.service ?? ''} ${incident.description}`
            .toLowerCase()
            .includes(query)),
    )
  }, [items, search, statusFilter])

  const counts = useMemo(() => statusCounts(items), [items])

  // Fresh detail whenever the selection changes — the list row is a cached view.
  useEffect(() => {
    if (!selectedId) return
    let cancelled = false
    // The flag flips here so the panel shows "Updating…" during the round trip.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDetailLoading(true)
    getIncident(selectedId)
      .then((fresh) => {
        if (cancelled) return
        setItems((current) => current.map((i) => (i.id === fresh.id ? fresh : i)))
      })
      .catch((error) => {
        if (!cancelled) fail(error, 'Could not load the incident')
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [selectedId, fail])

  function selectRow(id: string) {
    setSelectedId(id)
  }

  function merge(updated: Incident) {
    setItems((current) => {
      const exists = current.some((i) => i.id === updated.id)
      return exists
        ? current.map((i) => (i.id === updated.id ? updated : i))
        : [updated, ...current]
    })
    setTotal((n) => (items.some((i) => i.id === updated.id) ? n : n + 1))
  }

  async function runPending(task: NonNullable<Pending>) {
    setBusy(true)
    try {
      if (task.kind === 'create') {
        const created = await createIncident(task.values)
        setItems((current) => [created, ...current])
        setTotal((n) => n + 1)
        setSelectedId(created.id)
        push({ kind: 'success', title: 'Incident created', message: created.title })
      } else if (task.kind === 'edit') {
        const updated = await updateIncident(task.id, task.values)
        merge(updated)
        push({ kind: 'success', title: 'Changes saved', message: updated.title })
      } else if (task.kind === 'status') {
        const updated = await updateIncident(task.id, { status: task.status })
        merge(updated)
        push({
          kind: 'success',
          title: 'Status updated',
          message: `Now ${updated.status}.`,
        })
      } else if (task.kind === 'delete') {
        await deleteIncident(task.id)
        const next = items.filter((i) => i.id !== task.id)
        setItems(next)
        setSelectedId((sel) => (sel === task.id ? (next[0]?.id ?? null) : sel))
        setTotal((n) => Math.max(0, n - 1))
        push({ kind: 'success', title: 'Incident deleted', message: task.title })
      }
      setFormOpen(null)
      setPending(null)
    } catch (error) {
      const title =
        task.kind === 'delete'
          ? 'Could not delete the incident'
          : task.kind === 'status'
            ? 'Could not update the status'
            : task.kind === 'edit'
              ? 'Could not save your changes'
              : 'Could not create the incident'
      fail(error, title)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <img className="brand__mark" src={logoUrl} alt="IncidentIQ logo" width={40} height={40} />
          <div className="brand__copy">
            <b>IncidentIQ</b>
            <small>Incident command</small>
          </div>
        </div>

        <p className="nav-caption">Workspace</p>
        <nav className="nav">
          <button type="button" className="nav__item nav__item--active" aria-current="page">
            <span className="nav__icon" aria-hidden="true">
              ▦
            </span>
            <span className="nav__label">Incidents</span>
            <b className="nav__count">{total}</b>
          </button>
        </nav>

        <div className="sidebar__status">
          <span className={`dot dot--${apiOnline === null ? 'pending' : apiOnline ? 'online' : 'offline'}`} />
          <div>
            <b>{apiOnline === null ? 'Connecting' : apiOnline ? 'Systems nominal' : 'API unreachable'}</b>
            <small>{apiOnline === null ? 'Handshake in progress' : 'Live health check'}</small>
          </div>
        </div>

        <div className="profile">
          <span className="profile__avatar">IQ</span>
          <div>
            <b>Incident response</b>
            <small>Operator console</small>
          </div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <span className="crumbs">
            Workspace <i>/</i> Incidents
          </span>
          <div className="topbar__actions">
            <span
              className={`conn conn--${apiOnline === null ? 'pending' : apiOnline ? 'online' : 'offline'}`}
              role="status"
            >
              <span
                className={`dot dot--${apiOnline === null ? 'pending' : apiOnline ? 'online' : 'offline'}`}
              />
              {apiOnline === null ? 'Checking API' : apiOnline ? 'API online' : 'API offline'}
            </span>
            <button
              type="button"
              className="btn btn--primary btn--sm"
              onClick={() => setFormOpen('create')}
            >
              + New incident
            </button>
          </div>
        </header>

        <div className="content">
          <section className="heading">
            <div>
              <small className="eyebrow">Incident management</small>
              <h1>Incidents</h1>
              <p>Track service disruptions, assign severity and drive them to resolution.</p>
            </div>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => {
                setLoading(true)
                void load()
              }}
              disabled={loading}
            >
              {loading && <span className="btn__spinner" aria-hidden="true" />}
              Refresh
            </button>
          </section>

          <section className="stats" aria-label="Incident summary">
            <Stat label="Total incidents" value={total} detail="Tracked records" tone="cyan" />
            <Stat label="Open" value={counts.open} detail="Awaiting triage" tone="sky" />
            <Stat
              label="Investigating"
              value={counts.investigating}
              detail="Work in progress"
              tone="amethyst"
            />
            <Stat
              label="Resolved / closed"
              value={counts.resolved + counts.closed}
              detail="No longer active"
              tone="wisteria"
            />
          </section>

          <section className="workspace">
            <div className="list-panel">
              <div className="panel-title">
                <div>
                  <b>All incidents</b>
                  <small>
                    {visible.length} shown · {total} total
                  </small>
                </div>
              </div>

              <div className="filters">
                <input
                  aria-label="Search incidents"
                  placeholder="Search title, service or description"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
                <select
                  aria-label="Filter by status"
                  value={statusFilter}
                  onChange={(event) =>
                    setStatusFilter(event.target.value as 'all' | IncidentStatus)
                  }
                >
                  <option value="all">All statuses</option>
                  <option value="open">Open</option>
                  <option value="investigating">Investigating</option>
                  <option value="resolved">Resolved</option>
                  <option value="closed">Closed</option>
                </select>
              </div>

              {loading ? (
                <div className="state">
                  <span className="spinner" />
                  <b>Loading incidents</b>
                  <p>Synchronising with the incident store…</p>
                </div>
              ) : visible.length === 0 ? (
                <div className="state">
                  <span className="state__glyph" aria-hidden="true">
                    ⌕
                  </span>
                  <b>{items.length ? 'No matching incidents' : 'No incidents yet'}</b>
                  <p>
                    {items.length
                      ? 'Adjust the search or status filter.'
                      : 'Record your first incident to start tracking it.'}
                  </p>
                  {!items.length && (
                    <button
                      type="button"
                      className="btn btn--primary btn--sm"
                      onClick={() => setFormOpen('create')}
                    >
                      Create incident
                    </button>
                  )}
                </div>
              ) : (
                <>
                  <ul className="incident-list">
                    {visible.map((incident) => (
                      <li key={incident.id}>
                        <button
                          type="button"
                          className={`incident-row ${
                            incident.id === selectedId ? 'incident-row--selected' : ''
                          }`}
                          onClick={() => selectRow(incident.id)}
                          aria-pressed={incident.id === selectedId}
                        >
                          <span
                            className={`severity-bar severity-bar--${incident.severity}`}
                            aria-hidden="true"
                          />
                          <span className="incident-row__body">
                            <b>{incident.title}</b>
                            <small>
                              {incident.service || 'Unassigned service'} ·{' '}
                              {formatDate(incident.created_at)}
                            </small>
                            <span className="tags">
                              <Pill kind="status" value={incident.status} />
                              <Pill kind="severity" value={incident.severity} />
                            </span>
                          </span>
                          <span className="incident-row__chevron" aria-hidden="true">
                            ›
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>

                  <div className="list-footer">
                    <small>
                      Showing {items.length} of {total}
                    </small>
                    {items.length < total && (
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm"
                        onClick={() => void loadMore()}
                        disabled={loadingMore}
                      >
                        {loadingMore ? 'Loading…' : 'Load more'}
                      </button>
                    )}
                  </div>
                </>
              )}
            </div>

            <div className="detail-panel">
              {selected ? (
                <>
                  <small className="eyebrow">Incident overview</small>
                  <div className="detail-title">
                    <h2>{selected.title}</h2>
                    <Pill kind="severity" value={selected.severity} />
                  </div>

                  <div className="detail-meta">
                    <Pill kind="status" value={selected.status} />
                    <span className="service">{selected.service || 'No service assigned'}</span>
                    {detailLoading && <span className="detail-loading">Updating…</span>}
                  </div>

                  <div className="status-control">
                    <label className="field">
                      <span className="field__label">Change status</span>
                      <select
                        aria-label="Change status"
                        value={selected.status}
                        onChange={(event) => {
                          const next = event.target.value as IncidentStatus
                          if (next === selected.status) return
                          setPending({
                            kind: 'status',
                            id: selected.id,
                            status: next,
                            title: selected.title,
                          })
                        }}
                      >
                        {(['open', 'investigating', 'resolved', 'closed'] as IncidentStatus[]).map(
                          (option) => (
                            <option key={option} value={option}>
                              {option.charAt(0).toUpperCase() + option.slice(1)}
                            </option>
                          ),
                        )}
                      </select>
                    </label>
                  </div>

                  <section className="detail-section">
                    <h3>Description</h3>
                    <p>{selected.description || 'No description provided.'}</p>
                  </section>

                  <section className="detail-section">
                    <h3>Incident details</h3>
                    <div className="facts">
                      <Fact label="Incident ID" value={selected.id} mono />
                      <Fact label="Occurred at" value={formatDate(selected.occurred_at)} />
                      <Fact label="Created" value={formatDate(selected.created_at)} />
                      <Fact label="Last updated" value={formatDate(selected.updated_at)} />
                    </div>
                  </section>

                  <div className="detail-actions">
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      onClick={() => setFormOpen('edit')}
                    >
                      Edit incident
                    </button>
                    <button
                      type="button"
                      className="btn btn--danger btn--sm"
                      onClick={() =>
                        setPending({ kind: 'delete', id: selected.id, title: selected.title })
                      }
                    >
                      Delete
                    </button>
                  </div>

                  <footer className="detail-footer">
                    <span>
                      <span className="dot dot--online" /> All changes synced
                    </span>
                    <span>Human-controlled workflow</span>
                  </footer>
                </>
              ) : (
                <div className="state">
                  <span className="state__glyph" aria-hidden="true">
                    ▧
                  </span>
                  <b>Select an incident</b>
                  <p>Choose a record from the list to review and act on it.</p>
                </div>
              )}
            </div>
          </section>

          <footer className="footer">
            <span>IncidentIQ v0.1.0</span>
            <span>Incident management workspace</span>
          </footer>
        </div>
      </main>

      <Modal
        open={formOpen !== null}
        eyebrow="Incident record"
        title={formOpen === 'edit' ? 'Edit incident' : 'Create incident'}
        subtitle={
          formOpen === 'edit'
            ? 'Saving asks for confirmation before it is applied.'
            : 'Capture the initial details of the disruption.'
        }
        onClose={() => !busy && !pending && setFormOpen(null)}
      >
        <IncidentForm
          mode={formOpen === 'edit' ? 'edit' : 'create'}
          incident={formOpen === 'edit' ? (selected ?? undefined) : undefined}
          busy={busy}
          onSubmit={(values) => {
            if (formOpen === 'edit' && selected) {
              setPending({ kind: 'edit', id: selected.id, values })
            } else {
              setPending({ kind: 'create', values })
            }
          }}
          onCancel={() => setFormOpen(null)}
        />
      </Modal>

      <ConfirmDialog
        open={pending?.kind === 'create'}
        title="Create this incident?"
        description="It will be stored as an open incident and appear in the workspace immediately."
        confirmLabel="Create incident"
        busy={busy}
        onCancel={() => setPending(null)}
        onConfirm={() => pending && void runPending(pending)}
      />

      <ConfirmDialog
        open={pending?.kind === 'edit'}
        title="Save your changes?"
        description="The incident record will be updated with the values you entered."
        confirmLabel="Save changes"
        busy={busy}
        onCancel={() => setPending(null)}
        onConfirm={() => pending && void runPending(pending)}
      />

      <ConfirmDialog
        open={pending?.kind === 'status'}
        title="Change status?"
        description={
          pending?.kind === 'status'
            ? `"${pending.title}" will move to ${pending.status}.`
            : ''
        }
        confirmLabel="Change status"
        busy={busy}
        onCancel={() => setPending(null)}
        onConfirm={() => pending && void runPending(pending)}
      />

      <ConfirmDialog
        open={pending?.kind === 'delete'}
        tone="danger"
        title="Delete this incident?"
        description={
          pending?.kind === 'delete'
            ? `"${pending.title}" will be permanently removed. This cannot be undone.`
            : ''
        }
        confirmLabel="Delete incident"
        busy={busy}
        onCancel={() => setPending(null)}
        onConfirm={() => pending && void runPending(pending)}
      />
    </div>
  )
}

export default function App() {
  return (
    <ToastProvider>
      <Workspace />
    </ToastProvider>
  )
}
