import { ChevronLeftIcon, ChevronDownIcon, PlusIcon, TreeIcon, GaugeIcon, GearIcon, SearchIcon, SunIcon, MoonIcon, CheckIcon, RunIcon, WarnIcon, CritIcon } from './Icons.jsx'

function statusIcon(lifecycle, committedCount, unitCount) {
  if (lifecycle === 'RUNNING' || lifecycle === 'CREATED') return <span className="stat-ico run"><RunIcon /></span>
  if (lifecycle === 'FAILED' || lifecycle === 'CANCELLED') return <span className="stat-ico crit"><CritIcon /></span>
  if (lifecycle === 'INTERRUPTED') return <span className="stat-ico warn"><WarnIcon /></span>
  if (lifecycle === 'PARTIAL') return <span className="stat-ico warn"><WarnIcon /></span>
  if (unitCount && committedCount === unitCount) return <span className="stat-ico ok"><CheckIcon width={15} height={15} /></span>
  return <span className="stat-ico ok"><CheckIcon width={15} height={15} /></span>
}

function relTime(ts) {
  if (!ts) return ''
  const s = Math.max(0, Date.now() / 1000 - ts)
  if (s < 60) return 'just now'
  if (s < 3600) return Math.floor(s / 60) + 'm ago'
  if (s < 86400) return Math.floor(s / 3600) + 'h ago'
  return Math.floor(s / 86400) + 'd ago'
}

export default function Sidebar({ runs, currentRunId, onSelectRun, onNewProgram, theme, onSetTheme, collapsed, onToggleCollapse, runsOpen, onToggleRunsGroup }) {
  return (
    <aside className={'sidebar' + (collapsed ? ' collapsed' : '')} id="sidebar">
      <div className="brand-row">
        <div className="brand">
          <div className="brand-mark">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round">
              <circle cx="12" cy="12" r="7.5" opacity=".45" />
              <path d="M4.5 12c3.2-3.4 5.4 3.4 8.6 0s2.9-3.4 6.4 0" />
            </svg>
          </div>
          <div className="brand-name">zuse</div>
        </div>
        <button className="chevron-btn" onClick={onToggleCollapse} aria-label="Toggle sidebar" aria-expanded={!collapsed} id="chevronBtn">
          <ChevronLeftIcon />
        </button>
      </div>

      <div className="side-search" role="button" tabIndex={0}>
        <SearchIcon />
        <span className="search-text">Search programs</span>
      </div>

      <div className="side-scroll">
        <div className="nav-row" onClick={onNewProgram}>
          <span className="nav-ico"><PlusIcon /></span>
          <span className="nav-text">New program</span>
        </div>

        <div className={'nav-group' + (runsOpen ? ' open' : '')} id="runsGroup">
          <div className="nav-row active" onClick={onToggleRunsGroup}>
            <span className="disclosure"><ChevronDownIcon style={{ transform: runsOpen ? 'none' : 'rotate(-90deg)' }} /></span>
            <span className="nav-ico"><TreeIcon /></span>
            <span className="nav-text">Migrations</span>
          </div>

          {runsOpen && (
            <div className="tree" id="runsTree">
              {runs.length === 0 && (
                <div className="tree-empty" style={{ padding: '8px 14px', fontSize: '11.5px', color: 'var(--ink-3)' }}>No runs yet</div>
              )}
              {runs.map((r) => (
                <div
                  key={r.run_id}
                  className={'tree-item' + (r.run_id === currentRunId ? ' active' : '')}
                  title={`${r.run_id} — ${r.lifecycle}`}
                  onClick={() => onSelectRun(r.run_id)}
                >
                  {statusIcon(r.lifecycle, r.committed_count, r.unit_count)}
                  <span className="tree-text">
                    <span className="tree-name mono">{r.run_id.slice(0, 12)}</span>
                    <span className="tree-meta">
                      {(r.lifecycle || '').toLowerCase()} · {r.committed_count}/{r.unit_count} · {relTime(r.created_at)}
                    </span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="side-label">Workspace</div>
        <div className="nav-row" title="Metrics">
          <span className="nav-ico"><GaugeIcon /></span>
          <span className="nav-text">Metrics</span>
        </div>
        <div className="nav-row" title="Settings">
          <span className="nav-ico"><GearIcon /></span>
          <span className="nav-text">Settings</span>
        </div>
      </div>

      <div className="side-foot">
        <div className="theme-switch">
          <button className={'seg' + (theme === 'light' ? ' on' : '')} id="segLight" onClick={() => onSetTheme('light')}>
            <SunIcon />
            <span className="seg-label">Light</span>
          </button>
          <button className={'seg' + (theme === 'dark' ? ' on' : '')} id="segDark" onClick={() => onSetTheme('dark')}>
            <MoonIcon />
            <span className="seg-label">Dark</span>
          </button>
        </div>
      </div>
    </aside>
  )
}
