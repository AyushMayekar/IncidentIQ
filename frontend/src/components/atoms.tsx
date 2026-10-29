import type { Incident, IncidentStatus } from '../api/types'
import { SEVERITIES, STATUSES } from '../api/types'

export const SEVERITY_LABEL: Record<string, string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  critical: 'Critical',
}

export const STATUS_LABEL: Record<string, string> = {
  open: 'Open',
  investigating: 'Investigating',
  resolved: 'Resolved',
  closed: 'Closed',
}

export function Pill({ kind, value }: { kind: 'severity' | 'status'; value: string }) {
  return (
    <span className={`pill pill--${kind} pill--${value}`}>
      {kind === 'severity' ? SEVERITY_LABEL[value] : STATUS_LABEL[value]}
    </span>
  )
}

export function Stat({
  label,
  value,
  detail,
  tone,
}: {
  label: string
  value: number
  detail: string
  tone: 'cyan' | 'sky' | 'amethyst' | 'wisteria'
}) {
  return (
    <article className={`stat stat--${tone}`}>
      <span className="stat__label">{label}</span>
      <strong className="stat__value">{value}</strong>
      <small className="stat__detail">{detail}</small>
    </article>
  )
}

export function Fact({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="fact">
      <small>{label}</small>
      <b className={mono ? 'mono' : ''} title={value}>
        {value}
      </b>
    </div>
  )
}

/** Local, human readable timestamp — falls back to a neutral placeholder. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return 'Not recorded'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Not recorded'
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function statusCounts(items: Incident[]) {
  const counts = Object.fromEntries(STATUSES.map((s) => [s, 0])) as Record<
    IncidentStatus,
    number
  >
  for (const item of items) counts[item.status] += 1
  return counts
}

export { SEVERITIES, STATUSES }
