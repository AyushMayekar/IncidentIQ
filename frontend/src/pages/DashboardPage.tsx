import { useCallback, useEffect, useMemo, useState } from 'react'
import { createIncident, listIncidents } from '../api/incidents'
import type { Incident, IncidentCreateInput, IncidentStatus } from '../api/types'
import { IncidentForm } from '../components/IncidentForm'
import { Modal } from '../components/Modal'
import { useToast } from '../components/Toast'
import { Pill, Stat, formatDate, statusCounts } from '../components/atoms'

const PAGE_SIZE = 20

interface DashboardPageProps {
  onOpenIncident: (id: string) => void
  onTotalChange: (total: number) => void
}

/** Navigational overview: counts, filters, pagination and incident cards only. */
export function DashboardPage({
  onOpenIncident,
  onTotalChange,
}: DashboardPageProps) {
  const { push } = useToast()
  const [items, setItems] = useState<Incident[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [creating, setCreating] = useState(false)
  const [formOpen, setFormOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | IncidentStatus>('all')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listIncidents({ limit: PAGE_SIZE, offset: 0 })
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      push({
        kind: 'error',
        title: 'Could not load incidents',
        message:
          error instanceof Error ? error.message : 'Unexpected error.',
      })
    } finally {
      setLoading(false)
    }
  }, [push])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [load])

  useEffect(() => {
    onTotalChange(total)
  }, [total, onTotalChange])

  async function loadMore() {
    setLoadingMore(true)
    try {
      const result = await listIncidents({
        limit: PAGE_SIZE,
        offset: items.length,
      })
      setItems((current) => {
        const seen = new Set(current.map((incident) => incident.id))
        return [
          ...current,
          ...result.items.filter((incident) => !seen.has(incident.id)),
        ]
      })
      setTotal(result.total)
    } catch (error) {
      push({
        kind: 'error',
        title: 'Could not load more incidents',
        message:
          error instanceof Error ? error.message : 'Unexpected error.',
      })
    } finally {
      setLoadingMore(false)
    }
  }

  async function handleCreate(values: IncidentCreateInput) {
    setCreating(true)
    try {
      const created = await createIncident(values)
      push({ kind: 'success', title: 'Incident created', message: created.title })
      setFormOpen(false)
      onOpenIncident(created.id)
    } catch (error) {
      push({
        kind: 'error',
        title: 'Could not create the incident',
        message:
          error instanceof Error ? error.message : 'Unexpected error.',
      })
    } finally {
      setCreating(false)
    }
  }

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

  return (
    <div className="content">
      <section className="heading">
        <div>
          <small className="eyebrow">Incident management</small>
          <h1>Incidents</h1>
          <p>Track service disruptions, assign severity and drive them to resolution.</p>
        </div>
        <div className="heading__actions">
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => void load()}
            disabled={loading}
          >
            {loading && <span className="btn__spinner" aria-hidden="true" />}
            Refresh
          </button>
          <button
            type="button"
            className="btn btn--primary btn--sm"
            onClick={() => setFormOpen(true)}
          >
            + New incident
          </button>
        </div>
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

      <section className="list-panel dashboard-panel">
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
          <div className="state" role="status">
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
                onClick={() => setFormOpen(true)}
              >
                Create incident
              </button>
            )}
          </div>
        ) : (
          <>
            <ul className="incident-grid" aria-label="Incidents">
              {visible.map((incident) => (
                <li key={incident.id}>
                  <button
                    type="button"
                    className={`incident-card incident-card--${incident.severity}`}
                    onClick={() => onOpenIncident(incident.id)}
                    aria-label={`Open incident: ${incident.title}`}
                  >
                    <span
                      className={`severity-bar severity-bar--${incident.severity}`}
                      aria-hidden="true"
                    />
                    <span className="incident-card__body">
                      <b className="incident-card__title">{incident.title}</b>
                      <small className="incident-card__service">
                        {incident.service || 'Unassigned service'}
                      </small>
                      <span className="tags">
                        <Pill kind="status" value={incident.status} />
                        <Pill kind="severity" value={incident.severity} />
                      </span>
                      <small className="incident-card__date">
                        Updated {formatDate(incident.updated_at)}
                      </small>
                    </span>
                    <span className="incident-card__chevron" aria-hidden="true">
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
      </section>

      <Modal
        open={formOpen}
        eyebrow="Incident record"
        title="Create incident"
        subtitle="Capture the initial details of the disruption."
        onClose={() => !creating && setFormOpen(false)}
      >
        <IncidentForm
          mode="create"
          busy={creating}
          onSubmit={(values) => void handleCreate(values)}
          onCancel={() => setFormOpen(false)}
        />
      </Modal>
    </div>
  )
}
