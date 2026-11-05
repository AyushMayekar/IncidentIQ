import { useEffect, useState } from 'react'
import { checkHealth } from './api/incidents'
import { ToastProvider } from './components/Toast'
import { DashboardPage } from './pages/DashboardPage'
import { IncidentWorkspacePage } from './pages/IncidentWorkspacePage'
import { navigate, useRoute } from './router'
import logoUrl from '../logo.svg'
import './App.css'

function Shell() {
  const route = useRoute()
  const [total, setTotal] = useState(0)
  const [apiOnline, setApiOnline] = useState<boolean | null>(null)

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

  const goDashboard = () => navigate('/')
  const connectionLabel =
    apiOnline === null ? 'Checking API' : apiOnline ? 'API online' : 'API offline'

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
          <button
            type="button"
            className={`nav__item ${route.name === 'dashboard' ? 'nav__item--active' : ''}`}
            aria-current={route.name === 'dashboard' ? 'page' : undefined}
            onClick={goDashboard}
          >
            <span className="nav__icon" aria-hidden="true">
              ▦
            </span>
            <span className="nav__label">Incidents</span>
            <b className="nav__count">{total}</b>
          </button>
        </nav>

        <div className="sidebar__status">
          <span
            className={`dot dot--${apiOnline === null ? 'pending' : apiOnline ? 'online' : 'offline'}`}
          />
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
            {route.name === 'incident' && (
              <>
                {' '}
                <i>/</i> {route.incidentId.slice(0, 8)}
              </>
            )}
          </span>
          <div className="topbar__actions">
            <span
              className={`conn conn--${apiOnline === null ? 'pending' : apiOnline ? 'online' : 'offline'}`}
              role="status"
            >
              <span
                className={`dot dot--${apiOnline === null ? 'pending' : apiOnline ? 'online' : 'offline'}`}
              />
              {connectionLabel}
            </span>
          </div>
        </header>

        {route.name === 'dashboard' ? (
          <DashboardPage
            onOpenIncident={(id) => navigate(`/incidents/${encodeURIComponent(id)}`)}
            onTotalChange={setTotal}
          />
        ) : (
          <IncidentWorkspacePage
            key={route.incidentId}
            incidentId={route.incidentId}
            onBack={goDashboard}
            onDeleted={goDashboard}
          />
        )}

        <footer className="footer">
          <span>IncidentIQ v0.1.0</span>
          <span>Incident management workspace</span>
        </footer>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <ToastProvider>
      <Shell />
    </ToastProvider>
  )
}
