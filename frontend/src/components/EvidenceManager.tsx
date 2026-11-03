import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { getEvidenceContent, listEvidence, uploadEvidence } from '../api/evidence'
import {
    EVIDENCE_TYPES,
    EVIDENCE_TYPE_LABELS,
    evidenceTypeLabel,
    formatBytes,
    humanize,
    isEvidenceType,
    validateEvidenceFile,
} from '../api/evidenceTypes'
import type { Evidence, EvidenceType } from '../api/evidenceTypes'
import { Modal } from './Modal'
import { useToast } from './Toast'
import { formatDate } from './atoms'
import './EvidenceManager.css'

interface EvidenceManagerProps {
    incidentId: string
}

/** List state is tagged with the incident it belongs to, so it can never leak across incidents. */
type ListState =
    | { forId: string; status: 'loading' }
    | { forId: string; status: 'ready'; items: Evidence[]; refreshing: boolean }
    | { forId: string; status: 'error'; message: string }

type ContentState =
    | { status: 'idle' }
    | { status: 'loading' }
    | { status: 'ready'; text: string }
    | { status: 'error'; message: string }

function errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : 'Unexpected error.'
}

export function EvidenceManager({ incidentId }: EvidenceManagerProps) {
    const { push } = useToast()
    const headingId = useId()
    const fileId = useId()
    const fileHelpId = useId()
    const fileErrorId = useId()
    const typeId = useId()
    const typeErrorId = useId()

    const [list, setList] = useState<ListState>({ forId: incidentId, status: 'loading' })
    const [reloadToken, setReloadToken] = useState(0)

    const [file, setFile] = useState<File | null>(null)
    const [evidenceType, setEvidenceType] = useState<EvidenceType | ''>('')
    const [fileError, setFileError] = useState<string | null>(null)
    const [typeError, setTypeError] = useState<string | null>(null)
    const [submitError, setSubmitError] = useState<string | null>(null)
    const [uploading, setUploading] = useState(false)
    const uploadingRef = useRef(false)
    const mountedRef = useRef(true)
    const fileInputRef = useRef<HTMLInputElement>(null)

    const [viewing, setViewing] = useState<Evidence | null>(null)
    const [content, setContent] = useState<ContentState>({ status: 'idle' })
    const viewerAbortRef = useRef<AbortController | null>(null)

    useEffect(() => {
        mountedRef.current = true
        return () => {
            mountedRef.current = false
        }
    }, [])

    // Load the list for the current incident. Switching incidents (or reloading)
    // aborts the previous request, and an aborted request can never write state.
    useEffect(() => {
        const controller = new AbortController()
        listEvidence(incidentId, controller.signal)
            .then((items) => {
                if (controller.signal.aborted) return
                setList({ forId: incidentId, status: 'ready', items, refreshing: false })
            })
            .catch((error: unknown) => {
                if (controller.signal.aborted) return
                setList({ forId: incidentId, status: 'error', message: errorMessage(error) })
            })
        return () => controller.abort()
    }, [incidentId, reloadToken])

    const abortViewer = useCallback(() => {
        viewerAbortRef.current?.abort()
        viewerAbortRef.current = null
    }, [])

    useEffect(() => abortViewer, [abortViewer])

    const reload = useCallback(() => {
        setList((current) =>
            current.forId === incidentId && current.status === 'ready'
                ? { ...current, refreshing: true }
                : { forId: incidentId, status: 'loading' },
        )
        setReloadToken((token) => token + 1)
    }, [incidentId])

    // Never show another incident's records, even for a single render.
    const view: ListState =
        list.forId === incidentId ? list : { forId: incidentId, status: 'loading' }
    const listBusy = view.status === 'loading' || (view.status === 'ready' && view.refreshing)

    function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
        const selected = event.target.files?.[0] ?? null
        setFile(selected)
        setSubmitError(null)
        setFileError(selected ? validateEvidenceFile(selected) : null)
    }

    function handleTypeChange(event: ChangeEvent<HTMLSelectElement>) {
        const value = event.target.value
        setEvidenceType(isEvidenceType(value) ? value : '')
        setTypeError(null)
        setSubmitError(null)
    }

    async function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (uploadingRef.current) return

        const nextFileError = file ? validateEvidenceFile(file) : 'Choose a .log or .txt file to upload.'
        const nextTypeError = evidenceType ? null : 'Select what kind of evidence this is.'
        setFileError(nextFileError)
        setTypeError(nextTypeError)
        setSubmitError(null)
        if (nextFileError || nextTypeError || !file || !evidenceType) return

        uploadingRef.current = true
        setUploading(true)
        try {
            const created = await uploadEvidence(incidentId, file, evidenceType)
            push({
                kind: 'success',
                title: 'Evidence uploaded',
                message: `${created.source_name} added as ${evidenceTypeLabel(created.evidence_type)}.`,
            })
            if (mountedRef.current) {
                setFile(null)
                setFileError(null)
                if (fileInputRef.current) fileInputRef.current.value = ''
                reload()
            }
        } catch (error) {
            // Keep the file and type so the user can retry without re-selecting.
            if (mountedRef.current) setSubmitError(errorMessage(error))
        } finally {
            uploadingRef.current = false
            if (mountedRef.current) setUploading(false)
        }
    }

    function openViewer(item: Evidence) {
        abortViewer()
        const controller = new AbortController()
        viewerAbortRef.current = controller
        setViewing(item)
        setContent({ status: 'loading' })
        getEvidenceContent(incidentId, item.id, controller.signal)
            .then((text) => {
                if (controller.signal.aborted) return
                setContent({ status: 'ready', text })
            })
            .catch((error: unknown) => {
                if (controller.signal.aborted) return
                setContent({ status: 'error', message: errorMessage(error) })
            })
    }

    function closeViewer() {
        abortViewer()
        setViewing(null)
        setContent({ status: 'idle' })
    }

    return (
        <section className="detail-section evidence" aria-labelledby={headingId}>
            <div className="evidence__header">
                <div className="evidence__title">
                    <h3 id={headingId}>Evidence</h3>
                    {view.status === 'ready' && (
                        <span className="evidence__count">
                            {view.items.length} {view.items.length === 1 ? 'record' : 'records'}
                        </span>
                    )}
                </div>
                <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    onClick={reload}
                    disabled={listBusy}
                    aria-label="Refresh evidence"
                >
                    {listBusy && <span className="btn__spinner" aria-hidden="true" />}
                    Refresh
                </button>
            </div>

            <form className="evidence-upload" onSubmit={(event) => void handleSubmit(event)} noValidate aria-label="Upload evidence">
                <div className="field">
                    <label className="field__label" htmlFor={fileId}>
                        Evidence file
                    </label>
                    <input
                        ref={fileInputRef}
                        id={fileId}
                        type="file"
                        accept=".log,.txt"
                        onChange={handleFileChange}
                        disabled={uploading}
                        aria-invalid={fileError ? true : undefined}
                        aria-describedby={fileError ? `${fileHelpId} ${fileErrorId}` : fileHelpId}
                    />
                    <small id={fileHelpId} className="evidence-help">
                        Accepted: .log and .txt (UTF-8 text), up to 5 MiB.
                    </small>
                    {file && !fileError && (
                        <small className="evidence-selected">
                            {`Selected: ${file.name} (${formatBytes(file.size)})`}
                        </small>
                    )}
                    {fileError && (
                        <small id={fileErrorId} className="evidence-error" role="alert">
                            {fileError}
                        </small>
                    )}
                </div>

                <div className="field">
                    <label className="field__label" htmlFor={typeId}>
                        Evidence type
                    </label>
                    <select
                        id={typeId}
                        value={evidenceType}
                        onChange={handleTypeChange}
                        disabled={uploading}
                        aria-required="true"
                        aria-invalid={typeError ? true : undefined}
                        aria-describedby={typeError ? typeErrorId : undefined}
                    >
                        <option value="">Select evidence type…</option>
                        {EVIDENCE_TYPES.map((type) => (
                            <option key={type} value={type}>
                                {EVIDENCE_TYPE_LABELS[type]}
                            </option>
                        ))}
                    </select>
                    <small className="evidence-help">Required. Describes what the file contains.</small>
                    {typeError && (
                        <small id={typeErrorId} className="evidence-error" role="alert">
                            {typeError}
                        </small>
                    )}
                </div>

                {submitError && (
                    <div className="evidence-banner evidence-upload__banner" role="alert">
                        <b>Upload failed</b>
                        <span>{submitError}</span>
                    </div>
                )}

                <div className="evidence-upload__actions">
                    <button type="submit" className="btn btn--primary btn--sm" disabled={uploading}>
                        {uploading && <span className="btn__spinner" aria-hidden="true" />}
                        {uploading ? 'Uploading…' : 'Upload evidence'}
                    </button>
                </div>
            </form>

            {view.status === 'loading' && (
                <div className="evidence-state" role="status">
                    <span className="evidence-spinner" aria-hidden="true" />
                    <span>Loading evidence…</span>
                </div>
            )}

            {view.status === 'error' && (
                <div className="evidence-state evidence-state--error" role="alert">
                    <b>Could not load evidence</b>
                    <p>{view.message}</p>
                    <button type="button" className="btn btn--ghost btn--sm" onClick={reload}>
                        Retry
                    </button>
                </div>
            )}

            {view.status === 'ready' && view.items.length === 0 && (
                <div className="evidence-state">
                    <span className="evidence-state__glyph" aria-hidden="true">
                        ▤
                    </span>
                    <p>
                        No evidence attached yet. Upload logs or other diagnostic evidence to begin
                        investigating this incident.
                    </p>
                </div>
            )}

            {view.status === 'ready' && view.items.length > 0 && (
                <ul className="evidence-list" aria-label="Evidence records">
                    {view.items.map((item) => (
                        <li key={item.id} className="evidence-item">
                            <div className="evidence-item__top">
                                <div className="evidence-item__heading">
                                    <b className="evidence-item__name">{item.source_name}</b>
                                    <span className="evidence-badge">{evidenceTypeLabel(item.evidence_type)}</span>
                                </div>
                                <button
                                    type="button"
                                    className="btn btn--ghost btn--sm"
                                    onClick={() => openViewer(item)}
                                    aria-label={`View ${item.source_name}`}
                                >
                                    View
                                </button>
                            </div>
                            <dl className="evidence-item__meta">
                                <div>
                                    <dt>MIME type</dt>
                                    <dd>{item.content_type}</dd>
                                </div>
                                <div>
                                    <dt>Size</dt>
                                    <dd>{formatBytes(item.byte_size)}</dd>
                                </div>
                                <div>
                                    <dt>Added</dt>
                                    <dd>{formatDate(item.created_at)}</dd>
                                </div>
                                <div>
                                    <dt>Parse status</dt>
                                    <dd>{humanize(item.parse_status)}</dd>
                                </div>
                            </dl>
                        </li>
                    ))}
                </ul>
            )}

            <Modal
                open={viewing !== null}
                eyebrow="Evidence content"
                title={viewing?.source_name ?? 'Evidence preview'}
                subtitle={
                    viewing
                        ? `${evidenceTypeLabel(viewing.evidence_type)} · ${formatBytes(viewing.byte_size)}`
                        : ''
                }
                onClose={closeViewer}
            >
                {content.status === 'loading' && (
                    <div className="evidence-state" role="status">
                        <span className="evidence-spinner" aria-hidden="true" />
                        <span>Loading content…</span>
                    </div>
                )}
                {content.status === 'error' && (
                    <div className="evidence-state evidence-state--error" role="alert">
                        <b>Could not load content</b>
                        <p>{content.message}</p>
                        <button
                            type="button"
                            className="btn btn--ghost btn--sm"
                            onClick={() => viewing && openViewer(viewing)}
                        >
                            Retry loading content
                        </button>
                    </div>
                )}
                {content.status === 'ready' && (
                    // Rendered as a plain text child: React escapes it, nothing is parsed as HTML.
                    <pre className="evidence-preview" role="region" aria-label="Evidence content" tabIndex={0}>
                        {content.text}
                    </pre>
                )}
            </Modal>
        </section>
    )
}