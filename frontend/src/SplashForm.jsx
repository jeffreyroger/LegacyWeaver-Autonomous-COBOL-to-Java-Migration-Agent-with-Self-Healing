import { useState } from 'react'

const DEFAULTS = {
  cobolSource: 'fixtures/cobol/interest.cob',
  copybookDir: '',
  dataFile: 'fixtures/data/accounts.dat',
  seed: 42,
  modelName: 'qwen2.5-coder:7b',
  maxRepairs: 3,
  replay: false,
  synthesisMode: true,
  candidatePath: '',
}

// Advisory only, not authoritative -- the backend's real per-program
// pairing lives in weaver/agent/program_profiles.py's _PROGRAM_PATHS. This
// just stops the single most common mistake: switching COBOL source but
// leaving a stale data file behind, which silently feeds one program's
// record layout the wrong bytes (a real repro: WHSEPROC run against
// interest.cob's accounts.dat produced spurious CONTROL_FLOW escalations
// on every record -- the harness worked correctly on genuinely wrong input).
const KNOWN_PAIRS = {
  'fixtures/cobol/interest.cob': 'fixtures/data/accounts.dat',
  'fixtures/cobol/asdf.cob': 'fixtures/data_whseproc/orders.dat',
}

export default function SplashForm({ health, onStart, starting, error }) {
  const [f, setF] = useState(DEFAULTS)
  const [dataFileTouched, setDataFileTouched] = useState(false)

  const set = (k) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    if (k === 'dataFile') setDataFileTouched(true)
    setF((s) => {
      const next = { ...s, [k]: value }
      // Only auto-sync the data file while the user hasn't hand-edited it --
      // once they have, their choice is never silently overwritten.
      if (k === 'cobolSource' && !dataFileTouched) {
        const known = KNOWN_PAIRS[value.trim()]
        if (known) next.dataFile = known
      }
      return next
    })
  }

  const mismatch = KNOWN_PAIRS[f.cobolSource.trim()] && KNOWN_PAIRS[f.cobolSource.trim()] !== f.dataFile.trim()

  function submit() {
    onStart({
      cobol_source: f.cobolSource.trim(),
      copybook_dir: f.copybookDir.trim() || null,
      data_file: f.dataFile.trim(),
      synthesis_mode: f.synthesisMode,
      candidate_path: f.synthesisMode ? null : f.candidatePath.trim() || null,
      seed: Number(f.seed),
      model_name: f.modelName.trim(),
      model_digest: '',
      max_repair_attempts: Number(f.maxRepairs),
      replay: f.replay,
    })
  }

  const toolchainOk = health?.toolchain_available
  return (
    <section className="panel splash" id="splashView">
      <div className="splash-inner">
        <div className="splash-head">
          <h1 className="splash-title">Configure a migration run</h1>
          <p className="splash-sub">
            Paths are read from the machine running the backend service (127.0.0.1). LegacyWeaver migrates the
            program to Java and verifies every line against the oracle, byte for byte.
          </p>
        </div>

        <div className="upload-card">
          <div className="health-row">
            {health ? (
              <>
                <span className={'health-dot' + (toolchainOk ? ' ok' : ' bad')} />
                <span>toolchain {toolchainOk ? 'available' : `unavailable (${health.toolchain_detail})`}</span>
                <span className={'health-dot' + (health.inference_available ? ' ok' : ' bad')} />
                <span>inference {health.inference_available ? 'reachable' : 'unreachable (required unless replay=true)'}</span>
                <span style={{ color: 'var(--ink-4)' }}>bound to {health.bind_host}</span>
              </>
            ) : (
              <span>Checking backend health…</span>
            )}
          </div>
        </div>

        <div className="upload-card">
          <div className="field-row">
            <label className="field-label" htmlFor="fCobolSource">COBOL source path *</label>
            <input className="field-input mono" id="fCobolSource" type="text" value={f.cobolSource} onChange={set('cobolSource')} />
          </div>
          <div className="field-row">
            <label className="field-label" htmlFor="fCopybookDir">Copybook directory (optional)</label>
            <input className="field-input mono" id="fCopybookDir" type="text" value={f.copybookDir} onChange={set('copybookDir')} placeholder="none" />
          </div>
          <div className="field-row">
            <label className="field-label" htmlFor="fDataFile">Input data file path *</label>
            <input className="field-input mono" id="fDataFile" type="text" value={f.dataFile} onChange={set('dataFile')} />
            {mismatch && (
              <div className="field-warning">
                This doesn't look like {f.cobolSource.trim()}'s data file — its record layout expects{' '}
                <code>{KNOWN_PAIRS[f.cobolSource.trim()]}</code>. A mismatched pair still runs, just against
                the wrong bytes, and reads as spurious escalations rather than a clear error.
              </div>
            )}
          </div>

          <details className="advanced">
            <summary>Advanced run parameters</summary>
            <div className="field-grid">
              <div className="field-row">
                <label className="field-label" htmlFor="fSeed">Seed</label>
                <input className="field-input mono" id="fSeed" type="number" value={f.seed} onChange={set('seed')} />
              </div>
              <div className="field-row">
                <label className="field-label" htmlFor="fModel">Model name</label>
                <input className="field-input mono" id="fModel" type="text" value={f.modelName} onChange={set('modelName')} />
              </div>
              <div className="field-row">
                <label className="field-label" htmlFor="fMaxRepairs">Max repair attempts</label>
                <input className="field-input mono" id="fMaxRepairs" type="number" value={f.maxRepairs} onChange={set('maxRepairs')} />
              </div>
              <div className="field-row">
                <label className="field-label" htmlFor="fReplay">
                  <input type="checkbox" id="fReplay" checked={f.replay} onChange={set('replay')} /> Replay (deterministic, no live inference)
                </label>
              </div>
              <div className="field-row">
                <label className="field-label" htmlFor="fSynthesisMode">
                  <input type="checkbox" id="fSynthesisMode" checked={f.synthesisMode} onChange={set('synthesisMode')} /> Synthesis mode
                </label>
              </div>
              {!f.synthesisMode && (
                <div className="field-row">
                  <label className="field-label" htmlFor="fCandidatePath">Candidate Java body path</label>
                  <input className="field-input mono" id="fCandidatePath" type="text" value={f.candidatePath} onChange={set('candidatePath')} placeholder="path to a Java method body file" />
                </div>
              )}
            </div>
          </details>
        </div>

        <div className="splash-actions">
          <button className="btn-pill btn-solid" id="startRunBtn" onClick={submit} disabled={starting || !f.cobolSource.trim() || !f.dataFile.trim()}>
            {starting ? 'Starting…' : 'Start migration'}
          </button>
        </div>
        {error && <div className="form-error">{error}</div>}
      </div>
    </section>
  )
}
