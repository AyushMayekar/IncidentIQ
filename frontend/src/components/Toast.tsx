import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { ReactNode } from 'react'

export type ToastKind = 'success' | 'error' | 'info'

export interface ToastInput {
  kind: ToastKind
  title: string
  message?: string
  /**
   * Stable identifier used to suppress duplicates (for example
   * `evidence:<id>:failed`). Repeated pushes are ignored while visible.
   */
  key?: string
}

interface ToastItem extends ToastInput {
  id: number
}

interface ToastContextValue {
  push: (toast: ToastInput) => void
  dismiss: (id: number) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

/** Errors stay longer — they usually need a decision from the operator. */
const DEFAULT_VISIBLE_MS: Record<ToastKind, number> = {
  success: 4500,
  info: 5000,
  error: 8000,
}

const ROLE: Record<ToastKind, 'status' | 'alert'> = {
  success: 'status',
  info: 'status',
  error: 'alert',
}

const MAX_VISIBLE = 3

let nextId = 1

export function ToastProvider({
  children,
  durationMs,
}: {
  children: ReactNode
  /** Override auto-dismiss timing — used by tests to keep them fast. */
  durationMs?: number
}) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>())
  const keys = useRef(new Set<string>())

  const dismiss = useCallback((id: number) => {
    const timer = timers.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.current.delete(id)
    }
    setToasts((current) => {
      const target = current.find((toast) => toast.id === id)
      if (target?.key) keys.current.delete(target.key)
      return current.filter((toast) => toast.id !== id)
    })
  }, [])

  const push = useCallback(
    (input: ToastInput) => {
      // A duplicate key is dropped while its toast is still visible. This is
      // what stops polling or repeated failures from flooding the operator.
      if (input.key && keys.current.has(input.key)) return
      if (input.key) keys.current.add(input.key)

      const id = nextId++
      setToasts((current) => {
        const next = [...current, { ...input, id }]
        while (next.length > MAX_VISIBLE) {
          const dropped = next.shift()
          if (dropped?.key) keys.current.delete(dropped.key)
          if (dropped) {
            const droppedTimer = timers.current.get(dropped.id)
            if (droppedTimer) {
              clearTimeout(droppedTimer)
              timers.current.delete(dropped.id)
            }
          }
        }
        return next
      })
      const timer = setTimeout(
        () => dismiss(id),
        durationMs ?? DEFAULT_VISIBLE_MS[input.kind],
      )
      timers.current.set(id, timer)
    },
    [dismiss, durationMs],
  )

  useEffect(() => {
    const pending = timers.current
    return () => {
      pending.forEach((timer) => clearTimeout(timer))
      pending.clear()
    }
  }, [])

  const value = useMemo(() => ({ push, dismiss }), [push, dismiss])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-region" aria-live="polite">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`toast toast--${toast.kind}`}
            role={ROLE[toast.kind]}
            data-testid={`toast-${toast.kind}`}
          >
            <span className="toast__glyph" aria-hidden="true">
              {toast.kind === 'success' ? '✓' : toast.kind === 'error' ? '!' : 'i'}
            </span>
            <div className="toast__body">
              <b>{toast.title}</b>
              {toast.message && <p>{toast.message}</p>}
            </div>
            <button
              type="button"
              className="toast__close"
              aria-label="Dismiss notification"
              onClick={() => dismiss(toast.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext)
  if (!context) {
    throw new Error('useToast must be used inside a <ToastProvider>.')
  }
  return context
}
