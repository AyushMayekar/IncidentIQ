import { request, requestText } from './incidents'
import type { Evidence, EvidenceType } from './evidenceTypes'

function evidencePath(incidentId: string): string {
    return `/incidents/${encodeURIComponent(incidentId)}/evidence`
}

function signalInit(signal?: AbortSignal): RequestInit {
    return signal ? { signal } : {}
}

/** Evidence metadata for one incident, newest first. An empty array is valid. */
export function listEvidence(incidentId: string, signal?: AbortSignal): Promise<Evidence[]> {
    return request<Evidence[]>(evidencePath(incidentId), signalInit(signal))
}

/** Upload one file as multipart form data. Content-Type is left to the browser. */
export function uploadEvidence(
    incidentId: string,
    file: File,
    evidenceType: EvidenceType,
    signal?: AbortSignal,
): Promise<Evidence> {
    const form = new FormData()
    form.append('file', file)
    form.append('evidence_type', evidenceType)
    return request<Evidence>(evidencePath(incidentId), {
        method: 'POST',
        body: form,
        ...signalInit(signal),
    })
}

/** Original raw text of one evidence record. */
export function getEvidenceContent(
    incidentId: string,
    evidenceId: string,
    signal?: AbortSignal,
): Promise<string> {
    return requestText(
        `${evidencePath(incidentId)}/${encodeURIComponent(evidenceId)}/content`,
        signalInit(signal),
    )
}

/** Idempotently requeue failed processing for one evidence file. */
export function retryEvidence(
    incidentId: string,
    evidenceId: string,
    signal?: AbortSignal,
): Promise<Evidence> {
    return request<Evidence>(
        `${evidencePath(incidentId)}/${encodeURIComponent(evidenceId)}/retry`,
        { method: 'POST', ...signalInit(signal) },
    )
}

/** Remove evidence, its processing job and its derived records. */
export function deleteEvidence(
    incidentId: string,
    evidenceId: string,
    signal?: AbortSignal,
): Promise<void> {
    return request<void>(
        `${evidencePath(incidentId)}/${encodeURIComponent(evidenceId)}`,
        { method: 'DELETE', ...signalInit(signal) },
    )
}