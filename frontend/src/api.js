// Thin client over the six-endpoint run service (BACKEND_PLAN.md §4.1).
// No value is computed here -- every field is passed through verbatim from
// the backend response, which itself only echoes/relays the agent's own
// output (CLAUDE.md: "backend contains no domain logic").

async function asJson(res) {
  if (!res.ok) {
    let body
    try {
      body = await res.json()
    } catch {
      throw new Error(`${res.status} ${res.statusText}`)
    }
    throw new Error(body.message || `${res.status} ${res.statusText}`)
  }
  return res.json()
}

export function getHealth() {
  return fetch('/health').then(asJson)
}

export function createRun(payload) {
  return fetch('/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(asJson)
}

export function listRuns() {
  return fetch('/runs').then(asJson)
}

export function getRun(runId) {
  return fetch(`/runs/${runId}`).then(asJson)
}

export function getUnitCode(runId, unitId) {
  return fetch(`/runs/${runId}/units/${encodeURIComponent(unitId)}/code`).then(asJson)
}

// Multi-program (leaf-first DAG) runs, 2026-08-26 -- a paragraph id like
// MAIN-PARA is not unique across programs in a directory run, so these
// take a nested path segment instead of overloading unitId with a
// composite string (backend/app.py's /programs/{program}/... routes).
export function getUnitCodeInProgram(runId, program, unitId) {
  return fetch(`/runs/${runId}/programs/${encodeURIComponent(program)}/units/${encodeURIComponent(unitId)}/code`).then(asJson)
}

export function getDivergencesInProgram(runId, program, unitId) {
  return fetch(`/runs/${runId}/programs/${encodeURIComponent(program)}/divergences/${encodeURIComponent(unitId)}`).then(asJson)
}

export function getDivergences(runId, unitId) {
  return fetch(`/runs/${runId}/divergences/${encodeURIComponent(unitId)}`).then(asJson)
}

export function cancelRun(runId) {
  return fetch(`/runs/${runId}/cancel`, { method: 'POST' }).then(asJson)
}

export function resumeRun(runId) {
  return fetch(`/runs/${runId}/resume`, { method: 'POST' }).then(asJson)
}

export function postEscalationDecision(runId, unitId, decision, body) {
  return fetch(`/runs/${runId}/escalations/${encodeURIComponent(unitId)}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision, body: body ?? null }),
  }).then(asJson)
}

// Multi-program (leaf-first DAG) escalation decisions, 2026-08-26.
export function postEscalationDecisionInProgram(runId, program, unitId, decision, body) {
  return fetch(`/runs/${runId}/programs/${encodeURIComponent(program)}/escalations/${encodeURIComponent(unitId)}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision, body: body ?? null }),
  }).then(asJson)
}

// SSE stream, forwarded verbatim by the backend (BACKEND_PLAN.md §4.3).
// Returns an EventSource; caller owns its lifecycle (close on unmount/run change).
export function streamRunEvents(runId, onEvent, onError) {
  const source = new EventSource(`/runs/${runId}/events`)
  source.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data))
    } catch {
      // malformed event frame -- ignore rather than crash the stream handler
    }
  }
  source.onerror = (e) => {
    if (onError) onError(e)
  }
  return source
}
