export const EVIDENCE_TYPES = [
    'application_log',
    'infrastructure_log',
    'metrics',
    'trace',
    'deployment_event',
    'alert',
    'configuration',
    'manual_context',
] as const

export type EvidenceType = (typeof EVIDENCE_TYPES)[number]

export const EVIDENCE_TYPE_LABELS: Record<EvidenceType, string> = {
    application_log: 'Application log',
    infrastructure_log: 'Infrastructure log',
    metrics: 'Metrics',
    trace: 'Trace',
    deployment_event: 'Deployment event',
    alert: 'Alert',
    configuration: 'Configuration',
    manual_context: 'Manual context',
}

/** Evidence metadata as returned by the API. Raw content is never part of it. */
export interface Evidence {
    id: string
    incident_id: string
    source_name: string
    /** `null` for legacy records created before evidence types existed. */
    evidence_type: string | null
    content_type: string
    content_hash?: string
    byte_size: number
    parse_status: string
    created_at: string
}

export const MAX_EVIDENCE_BYTES = 5 * 1024 * 1024
export const ALLOWED_EVIDENCE_EXTENSIONS = ['.log', '.txt'] as const

export function isEvidenceType(value: string): value is EvidenceType {
    return (EVIDENCE_TYPES as readonly string[]).includes(value)
}

/** "not_required" -> "Not required". */
export function humanize(value: string): string {
    const text = value.replace(/_/g, ' ').trim()
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : '—'
}

export function evidenceTypeLabel(value: string | null): string {
    if (value === null) return 'Unclassified'
    return isEvidenceType(value) ? EVIDENCE_TYPE_LABELS[value] : humanize(value)
}

export function formatBytes(bytes: number): string {
    if (!Number.isFinite(bytes) || bytes < 0) return '—'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`
}

/** Client-side mirror of the backend rules. Returns a message, or null when acceptable. */
export function validateEvidenceFile(file: Pick<File, 'name' | 'size'>): string | null {
    const name = file.name.toLowerCase()
    const hasAllowedExtension = ALLOWED_EVIDENCE_EXTENSIONS.some(
        (extension) => name.length > extension.length && name.endsWith(extension),
    )
    if (!hasAllowedExtension) {
        return 'Unsupported file type. Only .log and .txt files are accepted.'
    }
    if (file.size === 0) return 'The selected file is empty.'
    if (file.size > MAX_EVIDENCE_BYTES) {
        return `File is too large (${formatBytes(file.size)}). The maximum allowed size is 5 MiB.`
    }
    return null
}