/** Severity levels accepted by the API. */
export type Severity = 'low' | 'medium' | 'high' | 'critical'

/** Lifecycle statuses accepted by the API. */
export type IncidentStatus = 'open' | 'investigating' | 'resolved' | 'closed'

/** An incident as returned by the API. */
export interface Incident {
  id: string
  title: string
  description: string
  service: string | null
  severity: Severity
  status: IncidentStatus
  occurred_at: string | null
  created_at: string
  updated_at: string
}

/** Paginated list envelope. */
export interface IncidentList {
  items: Incident[]
  total: number
  limit: number
  offset: number
}

/** Fields accepted when creating an incident. */
export interface IncidentCreateInput {
  title: string
  description: string
  service: string | null
  severity: Severity
  occurred_at?: string | null
}

/** Partial update accepted by `PATCH /incidents/{id}`. */
export interface IncidentUpdateInput {
  title?: string
  description?: string
  service?: string | null
  severity?: Severity
  status?: IncidentStatus
  occurred_at?: string | null
}

/** Severities in escalation order, used for sorting and labels. */
export const SEVERITIES: Severity[] = ['low', 'medium', 'high', 'critical']

/** Statuses in workflow order. */
export const STATUSES: IncidentStatus[] = ['open', 'investigating', 'resolved', 'closed']
