import { useEffect, useState } from 'react'

/**
 * A deliberately tiny History API router.
 *
 * No dependency is added: the app has exactly two routes, both support direct
 * URLs, refresh, back and forward, and tests can drive `popstate` normally.
 */
export type Route =
  | { name: 'dashboard' }
  | { name: 'incident'; incidentId: string }

export function parsePath(pathname: string): Route {
  const match = /^\/incidents\/([^/]+)\/?$/.exec(pathname)
  if (match) {
    let incidentId = match[1]
    try {
      incidentId = decodeURIComponent(match[1])
    } catch {
      // Keep the raw segment if it is not valid percent-encoding.
    }
    if (incidentId) return { name: 'incident', incidentId }
  }
  return { name: 'dashboard' }
}

export function navigate(path: string, options?: { replace?: boolean }): void {
  if (window.location.pathname === path) return
  if (options?.replace) {
    window.history.replaceState({}, '', path)
  } else {
    window.history.pushState({}, '', path)
  }
  window.dispatchEvent(new PopStateEvent('popstate'))
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() =>
    parsePath(window.location.pathname),
  )

  useEffect(() => {
    const onPopState = () => setRoute(parsePath(window.location.pathname))
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  return route
}
