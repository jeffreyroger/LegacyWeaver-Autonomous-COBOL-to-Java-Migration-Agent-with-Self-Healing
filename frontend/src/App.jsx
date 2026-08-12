import { useEffect, useRef, useState, useCallback } from 'react'
import Sidebar from './Sidebar.jsx'
import SplashForm from './SplashForm.jsx'
import DivergenceTable from './DivergenceTable.jsx'
import { tokenizeCobolLine, toSourceRows } from './cobol.js'
import { tokenizeJavaLine } from './java.js'
import { ArrowIcon, CheckIcon, ShieldIcon, ShieldWarnIcon, ChevronDownIcon } from './Icons.jsx'
import * as api from './api.js'

const ACTIVE_LIFECYCLES = new Set(['CREATED', 'RUNNING'])
const TERMINAL_LIFECYCLES = new Set(['COMPLETED', 'PARTIAL', 'FAILED', 'CANCELLED'])
const POLL_MS = 1200

// The "plan" trace event's outcome is a Python list repr, e.g.
// "units=['CALCULATE-INTEREST-PARA', 'APPLY-ROUNDING-RULE']" -- the only
// place the backend exposes the planned unit list ahead of completion
// (BACKEND_PLAN.md §4.3: events are forwarded verbatim, never reshaped).
function parsePlannedUnits(outcome) {
  const m = String(outcome || '').match(/units=\[(.*)\]/)
  if (!m) return []
  return [...m[1].matchAll(/'([^']*)'/g)].map((x) => x[1])
}

function renderJavaRows(body) {
  return body.split('\n').map((line, i) => (
    <div className="cl" key={i}>
      <span className="ln">{i + 1}</span>
      <span className="src">
        {tokenizeJavaLine(line).map((t, j) => (t.cls ? <span key={j} className={t.cls}>{t.text}</span> : <span key={j}>{t.text}</span>))}
      </span>
    </div>
  ))
}

function renderCobolRows(rows) {
  return rows.map((row, i) => (
    <div className="cl" key={i}>
      <span className="ln">{row.seq}</span>
      <span className="src">
        {tokenizeCobolLine(row.text).map((t, j) => (t.cls ? <span key={j} className={t.cls}>{t.text}</span> : <span key={j}>{t.text}</span>))}
      </span>
    </div>
  ))
}

export default function App() {
  const [theme, setThemeState] = useState('light')
  const [collapsed, setCollapsed] = useState(false)
  const [runsOpen, setRunsOpen] = useState(true)
  const [health, setHealth] = useState(null)
  const [runs, setRuns] = useState([])

  const [currentRunId, setCurrentRunId] = useState(null)
  const [runState, setRunState] = useState(null) // GET /runs/{id} response
  const [starting, setStarting] = useState(false)
  const [formError, setFormError] = useState('')

  const [traceEvents, setTraceEvents] = useState([])
  const [plannedUnits, setPlannedUnits] = useState([])

  const [selectedUnitId, setSelectedUnitId] = useState(null)
  const [unitCodeCache, setUnitCodeCache] = useState({})
  const [divergenceCache, setDivergenceCache] = useState({})
  const [decisionBusy, setDecisionBusy] = useState(false)

  const sseRef = useRef(null)
  const pollRef = useRef(null)

  function setTheme(mode) {
    setThemeState(mode)
    document.documentElement.setAttribute('data-theme', mode)
  }

  const refreshRuns = useCallback(() => {
    api.listRuns().then(setRuns).catch(() => {})
  }, [])

  useEffect(() => {
    api.getHealth().then(setHealth).catch((e) => setHealth({ status: 'error', toolchain_available: false, toolchain_detail: e.message, inference_available: false, bind_host: '?' }))
    refreshRuns()
  }, [refreshRuns])

  // ---- SSE + polling lifecycle for the currently open run ----
  const teardownLive = useCallback(() => {
    if (sseRef.current) { sseRef.current.close(); sseRef.current = null }
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }, [])

  const openRun = useCallback((runId) => {
    teardownLive()
    setCurrentRunId(runId)
    setRunState(null)
    setTraceEvents([])
    setPlannedUnits([])
    setSelectedUnitId(null)
    setUnitCodeCache({})
    setDivergenceCache({})

    // Two GET /runs/{id} requests in flight (a poll tick + a slow network
    // hiccup) have no ordering guarantee -- a stale RUNNING/empty-units
    // response arriving *after* the COMPLETED one would silently overwrite
    // the correct terminal state, and with the interval already cleared by
    // the (earlier-arriving, correct) terminal response, nothing would ever
    // poll again to fix it. Guard with a monotonic sequence number so only
    // the most-recently-*issued* request's response is ever applied.
    let seq = 0
    let latestApplied = -1
    let sseOpened = false

    const poll = () => {
      const mySeq = ++seq
      api.getRun(runId).then((rs) => {
        if (mySeq <= latestApplied) return // superseded by a later request that already resolved
        latestApplied = mySeq
        setRunState(rs)
        if (TERMINAL_LIFECYCLES.has(rs.lifecycle)) {
          teardownLive()
        } else if (!sseOpened && (ACTIVE_LIFECYCLES.has(rs.lifecycle) || rs.lifecycle === 'INTERRUPTED')) {
          // Open the live stream off the same response used for state, rather
          // than a second independent fetch -- one source of truth per tick.
          sseOpened = true
          sseRef.current = api.streamRunEvents(runId, (evt) => {
            setTraceEvents((prev) => [...prev.slice(-499), evt])
            if (evt.node === 'plan') setPlannedUnits(parsePlannedUnits(evt.outcome))
          })
        }
      }).catch(() => {})
    }
    poll()
    pollRef.current = setInterval(poll, POLL_MS)
  }, [teardownLive])

  useEffect(() => () => teardownLive(), [teardownLive])

  function resetToSplash() {
    teardownLive()
    setCurrentRunId(null)
    setRunState(null)
    setFormError('')
  }

  function startRun(payload) {
    setStarting(true)
    setFormError('')
    api.createRun(payload)
      .then((res) => {
        setStarting(false)
        refreshRuns()
        openRun(res.run_id)
      })
      .catch((e) => {
        setStarting(false)
        setFormError(e.message)
      })
  }

  function selectRun(runId) {
    if (runId === currentRunId) return
    openRun(runId)
  }

  function cancelActiveRun() {
    if (!currentRunId) return
    api.cancelRun(currentRunId).catch(() => {})
  }

  function resumeInterruptedRun() {
    if (!currentRunId) return
    api.resumeRun(currentRunId).then(() => openRun(currentRunId)).catch((e) => setFormError(e.message))
  }

  // ---- unit selection: fetch code + divergences on demand ----
  const units = runState?.units || []
  useEffect(() => {
    if (!selectedUnitId || !currentRunId) return
    const unit = units.find((u) => u.unit_id === selectedUnitId)
    if (!unit) return
    if (!unitCodeCache[selectedUnitId]) {
      api.getUnitCode(currentRunId, selectedUnitId)
        .then((code) => setUnitCodeCache((c) => ({ ...c, [selectedUnitId]: code })))
        .catch((e) => setUnitCodeCache((c) => ({ ...c, [selectedUnitId]: { error: e.message } })))
    }
    if (divergenceCache[selectedUnitId] === undefined) {
      api.getDivergences(currentRunId, selectedUnitId)
        .then((rep) => setDivergenceCache((c) => ({ ...c, [selectedUnitId]: rep })))
        .catch(() => setDivergenceCache((c) => ({ ...c, [selectedUnitId]: null })))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedUnitId, currentRunId, units.length])

  // auto-select something useful once units exist and nothing is selected
  useEffect(() => {
    if (selectedUnitId || units.length === 0) return
    const escalated = units.find((u) => u.status === 'escalated')
    setSelectedUnitId((escalated || units[units.length - 1]).unit_id)
  }, [units, selectedUnitId])

  function decide(decision, body) {
    if (!currentRunId || !selectedUnitId) return
    setDecisionBusy(true)
    api.postEscalationDecision(currentRunId, selectedUnitId, decision, body)
      .then(() => api.getRun(currentRunId))
      .then((rs) => { setRunState(rs); setDecisionBusy(false) })
      .catch((e) => { setFormError(e.message); setDecisionBusy(false) })
  }

  // ---- derived progress for the running panel ----
  const lifecycle = runState?.lifecycle
  const committedCount = units.filter((u) => u.status === 'committed').length
  const totalKnown = Math.max(units.length, plannedUnits.length)
  const pct = totalKnown ? Math.round((100 * units.length) / totalKnown) : 0
  const BAR_COUNT = 32
  const barsOn = Math.round((pct / 100) * BAR_COUNT)

  function unitRowStatus(unitId) {
    const done = units.find((u) => u.unit_id === unitId)
    if (done) return done.status // committed | escalated
    const lastEvt = [...traceEvents].reverse().find((e) => e.unit === unitId)
    if (lastEvt) return `${lastEvt.node}…`
    return 'queued'
  }

  const selectedUnit = units.find((u) => u.unit_id === selectedUnitId)
  const selectedCode = selectedUnitId ? unitCodeCache[selectedUnitId] : null
  const selectedDivergence = selectedUnitId ? divergenceCache[selectedUnitId] : null
  const unitTrace = selectedUnitId ? traceEvents.filter((e) => e.unit === selectedUnitId) : []

  const activeRunListItem = runs.find((r) => r.run_id === currentRunId)

  return (
    <div className="app">
      <Sidebar
        runs={runs}
        currentRunId={currentRunId}
        onSelectRun={selectRun}
        onNewProgram={resetToSplash}
        theme={theme}
        onSetTheme={setTheme}
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed((c) => !c)}
        runsOpen={runsOpen}
        onToggleRunsGroup={() => setRunsOpen((o) => !o)}
      />

      {/* design.css's .panel-results is flex:0 0 0px/opacity:0/pointer-events:none by
          default -- only .stage.split makes it a real, visible, clickable 45/55 split.
          Without this class the results panel (Java output, everything) is permanently
          zero-width and unclickable, which is exactly what was happening. */}
      <div className={'stage' + (currentRunId ? ' split' : '')} id="stage" style={{ display: 'flex' }}>
        {!currentRunId && <SplashForm health={health} onStart={startRun} starting={starting} error={formError} />}

        {currentRunId && (
          <>
            <section className="panel panel-source" id="sourcePanel" style={{ display: 'flex' }}>
              <div className="panel-head">
                <div className="head-left">
                  <div className="head-title mono">{selectedUnitId || currentRunId.slice(0, 12)}</div>
                  <div className="head-meta">
                    {selectedCode?.cobol ? `${selectedCode.cobol.source_path}:${selectedCode.cobol.start_line}-${selectedCode.cobol.end_line}` : (lifecycle || '—')}
                  </div>
                </div>
                {ACTIVE_LIFECYCLES.has(lifecycle) && (
                  <button className="btn-migrate busy" id="migrateBtn" onClick={cancelActiveRun}>
                    <span id="migrateLabel">Cancel</span>
                  </button>
                )}
                {lifecycle === 'INTERRUPTED' && (
                  <button className="btn-migrate" id="migrateBtn" onClick={resumeInterruptedRun}>
                    <span id="migrateLabel">Resume</span>
                  </button>
                )}
              </div>
              <div className="code-wrap">
                <div className="code" id="cobolCode">
                  {selectedCode?.error && <div style={{ padding: 14, fontSize: 12, color: 'var(--crit)' }}>{selectedCode.error}</div>}
                  {selectedCode?.cobol && renderCobolRows(toSourceRows(selectedCode.cobol.text))}
                  {!selectedCode && <div className="prov-hint" style={{ display: 'flex' }}>Select a unit from the list to view its COBOL source and generated Java side by side.</div>}
                </div>
              </div>
            </section>

            <div className="resizer" id="resizer" title="Drag to resize" />

            <section className="panel panel-results" id="resultsPanel">
              {!runState && <div style={{ padding: 20, fontSize: 12.5, color: 'var(--ink-3)' }}>Loading run…</div>}

              {runState && (ACTIVE_LIFECYCLES.has(lifecycle) || (lifecycle === 'INTERRUPTED' && units.length === 0)) && (
                <div id="runningView" style={{ display: 'flex', flexDirection: 'column', minHeight: 0, flex: 1 }}>
                  <div className="panel-head">
                    <div className="head-left">
                      <div className="head-title">Migration</div>
                      <div className="head-meta mono">{activeRunListItem ? activeRunListItem.run_id.slice(0, 12) : currentRunId.slice(0, 12)}</div>
                    </div>
                    <span className="tag">{lifecycle}</span>
                  </div>
                  <div className="run-body">
                    <div className="progress-card">
                      <div className="chip-row">
                        <span className="chip">synthesis</span>
                        <span className="chip">repair loop</span>
                        <span className="chip">oracle verify</span>
                      </div>
                      <div className="progress-title">Migrating…</div>
                      <div className="rule" />
                      <div className="pct-row">
                        <div className="pct">{pct}%</div>
                        <div className="delta">
                          <ArrowIcon width={11} height={11} />
                          <span>{units.length} of {totalKnown || '?'}</span>
                        </div>
                        <div className="pct-cap">units committed</div>
                      </div>
                      <div className="bars">
                        {Array.from({ length: BAR_COUNT }, (_, i) => (
                          <div key={i} className={'bar' + (i < barsOn ? ' on' : '')} />
                        ))}
                      </div>
                    </div>

                    <div className="unit-list">
                      {plannedUnits.length === 0 && units.length === 0 && (
                        <div style={{ fontSize: 12, color: 'var(--ink-3)' }}>Waiting for the plan step…</div>
                      )}
                      {(plannedUnits.length ? plannedUnits : units.map((u) => u.unit_id)).map((unitId) => {
                        const status = unitRowStatus(unitId)
                        const done = status === 'committed' || status === 'escalated'
                        return (
                          <div key={unitId} className={'unit-row' + (done ? ' done' : '')} onClick={() => setSelectedUnitId(unitId)}>
                            <span className="unit-ico">{done ? <CheckIcon width={15} height={15} /> : status === 'queued' ? <span className="pending" /> : <span className="spinner" />}</span>
                            <span className="unit-name">{unitId}</span>
                            <span className="unit-status">{status}</span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                </div>
              )}

              {runState && !ACTIVE_LIFECYCLES.has(lifecycle) && lifecycle !== 'INTERRUPTED' && (
                <div id="completeView" style={{ display: 'flex', flexDirection: 'column', minHeight: 0, flex: 1 }}>
                  <div className="panel-head">
                    <div className="head-left">
                      <div className="head-title">Unit detail</div>
                      <div className="head-meta mono">{selectedUnitId || '—'}</div>
                    </div>
                    <span className={'tag ' + (selectedUnit?.status === 'escalated' ? 'tag-warn' : lifecycle === 'FAILED' ? 'tag-crit' : 'tag-ok')}>
                      {selectedUnit ? selectedUnit.status : lifecycle}
                    </span>
                    <button id="runAnotherBtn" className="btn-pill btn-solid" style={{ marginLeft: 10 }} onClick={resetToSplash}>Run another migration</button>
                  </div>

                  {units.length > 1 && (
                    <div className="unit-list" style={{ padding: '10px 14px', borderBottom: '1px solid var(--line)' }}>
                      {units.map((u) => (
                        <div key={u.unit_id} className={'unit-row' + (u.unit_id === selectedUnitId ? ' selected' : '')} onClick={() => setSelectedUnitId(u.unit_id)}>
                          <span className="unit-ico">{u.status === 'committed' ? <CheckIcon width={15} height={15} /> : <span className="pending" />}</span>
                          <span className="unit-name">{u.unit_id}</span>
                          <span className="unit-status">{u.status}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="bento-stack">
                    <details className="acc-item" open>
                      <summary>
                        <span className="cell-title">Java output</span>
                        <span className="acc-summary-right">
                          <span className="rev-tag ok">{selectedUnit?.model_calls ?? 0} model call(s)</span>
                          <ChevronDownIcon className="acc-chev" />
                        </span>
                      </summary>
                      <div className="acc-body" style={{ padding: 0 }}>
                        <div className="java-code">
                          <div className="code">
                            {selectedCode?.error && <div style={{ padding: 14, fontSize: 12, color: 'var(--crit)' }}>{selectedCode.error}</div>}
                            {selectedCode?.java?.available && renderJavaRows(selectedCode.java.body)}
                            {selectedCode?.java && !selectedCode.java.available && <div style={{ padding: 14, fontSize: 12, color: 'var(--ink-3)' }}>No committed body for this unit.</div>}
                          </div>
                        </div>
                        <div className={'receipt ' + (selectedDivergence?.verified ? 'ok' : selectedDivergence ? 'bad' : '')}>
                          {selectedDivergence?.verified ? <ShieldIcon /> : <ShieldWarnIcon />}
                          <div className="receipt-main">
                            <div className="receipt-line">
                              {selectedDivergence
                                ? `${selectedDivergence.total_records - selectedDivergence.divergence_count} / ${selectedDivergence.total_records} report lines byte-identical to oracle`
                                : 'No divergence report available for this unit.'}
                            </div>
                          </div>
                        </div>
                        {selectedDivergence && <div style={{ padding: 12 }}><DivergenceTable report={selectedDivergence} /></div>}
                      </div>
                    </details>

                    <details className="acc-item">
                      <summary>
                        <span className="cell-title">Diagnostic</span>
                        <ChevronDownIcon className="acc-chev" />
                      </summary>
                      <div className="acc-body">
                        {selectedUnit?.diagnostic ? (
                          <div className="diag-grid">
                            <div className="diag-k">Defect class</div>
                            <div className="diag-v">
                              {selectedUnit.diagnostic.defect_class
                                ? <span className={'dvc dvc-' + selectedUnit.diagnostic.defect_class}>{selectedUnit.diagnostic.defect_class.replace('_', ' ')}</span>
                                : <span className="dvc dvc-UNKNOWN">UNKNOWN</span>}
                              {selectedUnit.diagnostic.confidence != null && (
                                <span style={{ marginLeft: 8, color: 'var(--ink-3)' }}>confidence {(selectedUnit.diagnostic.confidence * 100).toFixed(0)}%</span>
                              )}
                            </div>

                            <div className="diag-k">Values</div>
                            <div className="diag-v diag-compare">
                              <code>{selectedUnit.diagnostic.oracle_value ?? '—'}</code>
                              <ArrowIcon className="diag-arrow" width={12} height={12} />
                              <code>{selectedUnit.diagnostic.candidate_value ?? '—'}</code>
                              {selectedUnit.diagnostic.delta != null && <span style={{ color: 'var(--ink-3)' }}>delta {selectedUnit.diagnostic.delta}</span>}
                            </div>

                            {selectedUnit.diagnostic.failing_input_record && (
                              <>
                                <div className="diag-k">Failing record</div>
                                <div className="diag-v"><code>{selectedUnit.diagnostic.failing_input_record}</code></div>
                              </>
                            )}

                            {selectedUnit.diagnostic.suspected_source_lines && (
                              <>
                                <div className="diag-k">Suspected lines</div>
                                <div className="diag-v">{selectedUnit.diagnostic.suspected_source_lines}</div>
                              </>
                            )}

                            {selectedUnit.diagnostic.assumptions?.length > 0 && (
                              <>
                                <div className="diag-k">Assumptions</div>
                                <div className="diag-v">
                                  <ul className="diag-assumptions">
                                    {selectedUnit.diagnostic.assumptions.map((a, i) => <li key={i}>{a}</li>)}
                                  </ul>
                                </div>
                              </>
                            )}

                            {selectedUnit.diagnostic.decision_requested && (
                              <>
                                <div className="diag-k">Decision requested</div>
                                <div className="diag-v">{selectedUnit.diagnostic.decision_requested}</div>
                              </>
                            )}
                          </div>
                        ) : (
                          <div className="diag-empty">
                            <CheckIcon width={14} height={14} />
                            <span>No diagnostic — unit committed without escalation.</span>
                          </div>
                        )}
                      </div>
                    </details>

                    <details className="acc-item">
                      <summary>
                        <span className="cell-title">Trace</span>
                        <ChevronDownIcon className="acc-chev" />
                      </summary>
                      <div className="acc-body">
                        {unitTrace.length === 0 && <div style={{ fontSize: 12, color: 'var(--ink-3)' }}>No live trace for this unit in the current session (see the run's trace.jsonl on disk).</div>}
                        {unitTrace.map((e, i) => (
                          <div className="act-row" key={i}>
                            <span className="act-tool">{e.node}</span>
                            <span className="act-arg">{e.action} · {e.outcome}</span>
                            <span className="act-res tag tag-ok">{e.duration_seconds}s</span>
                          </div>
                        ))}
                      </div>
                    </details>

                    <details className="acc-item">
                      <summary>
                        <span className="cell-title">Run</span>
                        <ChevronDownIcon className="acc-chev" />
                      </summary>
                      <div className="acc-body">
                        <div className="kv-grid">
                          <div><div className="kv-k">Lifecycle</div><div className="kv-v">{lifecycle}</div></div>
                          <div><div className="kv-k">Repairs</div><div className="kv-v">{selectedUnit?.model_calls ?? '—'}</div></div>
                          <div><div className="kv-k">Memory hit</div><div className="kv-v">{selectedUnit ? String(selectedUnit.memory_hit) : '—'}</div></div>
                          <div><div className="kv-k">Duration</div><div className="kv-v">{selectedUnit ? selectedUnit.duration_seconds.toFixed(1) + 's' : '—'}</div></div>
                          {runState.metrics && (
                            <>
                              <div><div className="kv-k">Equiv. rate</div><div className="kv-v">{runState.metrics.equivalence_rate_post_repair.toFixed(1)}%</div></div>
                              <div><div className="kv-k">Model calls</div><div className="kv-v">{runState.metrics.model_calls_total}</div></div>
                            </>
                          )}
                        </div>
                      </div>
                    </details>
                  </div>

                  {selectedUnit?.status === 'escalated' && (
                    <div className="decision-bar" style={{ display: 'flex' }}>
                      <span className="decision-note">Accepting re-verifies against the oracle before committing and stores the repair in failure memory.</span>
                      <button className="btn-sm ghost" disabled={decisionBusy} onClick={() => decide('reject')}>Reject</button>
                      <button className="btn-sm solid" disabled={decisionBusy} onClick={() => decide('accept')}>Accept repair</button>
                    </div>
                  )}
                </div>
              )}

              {runState?.error && <div className="form-error" style={{ margin: 14 }}>{runState.error}</div>}
            </section>
          </>
        )}
      </div>
    </div>
  )
}
