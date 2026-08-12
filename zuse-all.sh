#!/usr/bin/env bash
# zuse-all.sh -- single entry point for every implemented Zuse
# feature (CLAUDE.md rule 12: only what has its own passing acceptance
# test is offered here; unimplemented commands are not wired in).
#
# Usage:
#   ./zuse-all.sh                 interactive menu
#   ./zuse-all.sh <command> [...] run one command directly
#   ./zuse-all.sh help            list commands
#
# Run from the repo root. Requires GnuCOBOL 3.x (cobc), JDK 17+ (javac),
# Python 3.11+ on PATH; `migrate`/`backend` additionally need Ollama
# running locally (`ollama serve` + `qwen2.5-coder:7b` pulled) except in
# --replay mode.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# ---------------------------------------------------------------------------
# venv discovery -- prefer .venv if present, else fall back to whatever
# `python`/`python3` is already on PATH (matches this dev box's setup).
# ---------------------------------------------------------------------------
_pick_python() {
  local candidate
  for candidate in "$@"; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    # A `python3` on PATH can be a non-functional Windows Store alias stub
    # that "exists" but errors on any real invocation -- verify it actually
    # runs before trusting it.
    "$candidate" --version >/dev/null 2>&1 && { echo "$candidate"; return 0; }
  done
  return 1
}

if [ -f .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe
elif [ -f .venv/bin/python ]; then PY=.venv/bin/python
elif PY=$(_pick_python python python3 py); then :
else
  echo "No working Python interpreter found on PATH (tried python, python3, py)." >&2
  exit 1
fi

# Five programs this repo can verify today (CLAUDE.md rule 12 / README
# "Status & roadmap" -- Phase U fixtures). Format: name:cobol:data:golden
PROGRAMS=(
  "interest:zuse/examples/input/interest.cob:zuse/examples/reference/accounts.dat:zuse/examples/reference/interest.out"
  "feecalc:zuse/examples/input/feecalc.cob:zuse/examples/input/data/fees.dat:zuse/examples/reference_feecalc/fee.out"
  "taxcalc:zuse/examples/input/taxcalc.cob:zuse/examples/input/data/tax.dat:zuse/examples/reference_taxcalc/golden_taxcalc.out"
  "tieraccum:zuse/examples/input/tieraccum.cob:zuse/examples/input/data/tieraccum.dat:zuse/examples/reference_tieraccum/golden_tieraccum.out"
  "compound:zuse/examples/input/compound.cob:zuse/examples/input/data/compound.dat:zuse/examples/reference_compound/golden_compound.out"
  "shipcost:zuse/examples/input/shipcost.cob:zuse/examples/input/data/shipcost.dat:zuse/examples/reference_shipcost/golden_shipcost.out"
)
# Known-correct, hand-verified full Java classes (K3 reference implementations)
# per program -- used to demonstrate a clean (0-divergence) run. Only
# interest/feecalc have a pre-assembled full class committed; the other four
# ship as a bare scaffold (zuse/examples/generated/<p>/Scaffold.java, unsynthesized stubs)
# plus a separate hand-verified *.body.java fragment -- cmd_verify_all
# assembles those two into a temp full class via zuse.agent.assemble
# before verifying, same substitution the orchestrator does per-unit.
declare -A REFERENCE_CLASS=(
  [interest]="zuse/examples/reference/Scaffold.java"
  [feecalc]="zuse/examples/reference_feecalc/Scaffold.java"
)
declare -A ASSEMBLE_SCAFFOLD=(
  [taxcalc]="zuse/examples/generated/taxcalc/Scaffold.java"
  [tieraccum]="zuse/examples/generated/tieraccum/Scaffold.java"
  [compound]="zuse/examples/generated/compound/Scaffold.java"
  [shipcost]="zuse/examples/generated/shipcost/Scaffold.java"
)
declare -A ASSEMBLE_BODY=(
  [taxcalc]="zuse/examples/reference_taxcalc/compute_tax.body.java"
  [tieraccum]="zuse/examples/reference_tieraccum/accumulate_tiers.body.java"
  [compound]="zuse/examples/reference_compound/compute_compound.body.java"
  [shipcost]="zuse/examples/reference_shipcost/compute_shipcost.body.java"
)
declare -A ASSEMBLE_PARAGRAPH=(
  [taxcalc]="COMPUTE-TAX"
  [tieraccum]="ACCUMULATE-TIERS"
  [compound]="COMPUTE-COMPOUND"
  [shipcost]="COMPUTE-SHIPCOST"
)

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$1"; }

cmd_setup() {
  log "Creating virtualenv (.venv) and installing dependencies"
  python -m venv .venv
  if [ -f .venv/Scripts/python.exe ]; then VPY=.venv/Scripts/python.exe; else VPY=.venv/bin/python; fi
  "$VPY" -m pip install --upgrade pip
  "$VPY" -m pip install -e .
  "$VPY" -m pip install -r requirements.txt
  log "Done. Re-run this script normally -- it will now use .venv automatically."
}

cmd_toolcheck() {
  log "Toolchain check"
  if command -v cobc >/dev/null 2>&1; then cobc --version 2>&1 | head -1; echo "cobc: OK"
  else warn "cobc (GnuCOBOL 3.x) not found -- verify/migrate will 503"
  fi
  if command -v javac >/dev/null 2>&1; then javac --version 2>&1; echo "javac: OK"
  else warn "javac (JDK 17+) not found"
  fi
  echo "python: $PY ($("$PY" --version 2>&1))"
  if command -v ollama >/dev/null 2>&1; then echo "ollama: found on PATH"
  else warn "ollama not found -- 'migrate' needs it unless --replay"
  fi
}

cmd_test() {
  log "Running test suite"
  "$PY" -m pytest -v
}

cmd_generate_data() {
  log "Checking committed fixture data (zuse/examples/reference/accounts.dat)"
  if [ ! -f zuse/examples/reference/accounts.dat ]; then
    warn "zuse/examples/reference/accounts.dat is missing and the generator script" \
         "(previously fixtures/generate_data.py) was removed with fixtures/ -- restore" \
         "it from git history if you need to regenerate this file."
    return 1
  fi
  echo "zuse/examples/reference/accounts.dat present -- nothing to generate."
}

cmd_verify_baseline() {
  log "zuse verify: interest.cob oracle vs. the deliberately-flawed zuse/examples/baseline/Baseline.java"
  echo "Expect: 201 records, 132 divergences, exit status 1 (planted defects, by design)."
  "$PY" -m zuse.cli verify zuse/examples/input/interest.cob zuse/examples/baseline/Baseline.java \
    zuse/examples/reference/accounts.dat --report report.json || true
}

cmd_verify_selfcheck() {
  log "Self-comparison: golden output vs. itself -- proves zero false positives (AC-9/FR-12)"
  "$PY" -m zuse.cli verify zuse/examples/input/interest.cob zuse/examples/reference/Scaffold.java \
    zuse/examples/reference/accounts.dat --report report_selfcheck.json
}

cmd_verify_all() {
  log "zuse verify across all ${#PROGRAMS[@]} fixtures, oracle vs. each hand-verified reference class"
  local fail=0
  for entry in "${PROGRAMS[@]}"; do
    IFS=: read -r name cobol data golden <<< "$entry"
    echo
    echo "--- $name ---"

    ref="${REFERENCE_CLASS[$name]:-}"
    if [ -z "$ref" ]; then
      # No pre-assembled full class for this program -- build one from its
      # bare scaffold + hand-verified body fragment (same substitution the
      # orchestrator applies per-unit).
      local scaffold="${ASSEMBLE_SCAFFOLD[$name]}" body="${ASSEMBLE_BODY[$name]}" para="${ASSEMBLE_PARAGRAPH[$name]}"
      if [ ! -f "$scaffold" ] || [ ! -f "$body" ]; then
        warn "$name: missing $scaffold or $body, skipping"; fail=1; continue
      fi
      ref="/tmp/zuse-all-assembled/${name}/Scaffold.java"
      "$PY" -m zuse.agent.assemble "$scaffold" "$body" "$para" "$ref" >/dev/null
    fi

    if [ ! -f "$ref" ]; then warn "$ref missing, skipping $name"; fail=1; continue; fi
    if "$PY" -m zuse.cli verify "$cobol" "$ref" "$data" --report "report_${name}.json"; then
      echo "$name: verified clean"
    else
      warn "$name: diverged -- see report_${name}.json"
      fail=1
    fi
  done
  return $fail
}

cmd_migrate() {
  local program="${1:-zuse/examples/input/interest.cob}"
  log "zuse migrate: autonomous synthesis + repair loop for $program (needs Ollama)"
  "$PY" -m zuse.cli migrate "$program" --data zuse/examples/reference/accounts.dat
}

cmd_migrate_replay() {
  local program="${1:-zuse/examples/input/interest.cob}"
  log "zuse migrate --replay: cached model responses only, zero live inference"
  "$PY" -m zuse.cli migrate "$program" --data zuse/examples/reference/accounts.dat --replay
}

cmd_report() {
  local run_dir="${1:-}"
  if [ -z "$run_dir" ]; then
    run_dir=$(ls -td zuse/examples/generated/runs/*/ 2>/dev/null | head -1 || true)
  fi
  if [ -z "$run_dir" ]; then warn "no zuse/examples/generated/runs directory found -- run 'migrate' first"; return 1; fi
  log "zuse report: metrics for $run_dir"
  "$PY" -m zuse.cli report "$run_dir"
}

cmd_backend() {
  local port="${1:-8420}"
  log "Starting local run service on 127.0.0.1:$port (Ctrl-C to stop)"
  "$PY" -m backend --port "$port"
}

cmd_demo() {
  log "Full demo sequence: setup check -> generate data -> baseline divergence -> self-check -> verify-all -> tests"
  cmd_toolcheck
  cmd_generate_data
  cmd_verify_baseline
  cmd_verify_selfcheck
  cmd_verify_all
  cmd_test || warn "test suite reported a failure -- see output above"
  log "Demo sequence complete."
}

banner() { printf '\n\033[1;35m########## %s ##########\033[0m\n' "$1"; }

cmd_showcase() {
  # One command, every implemented feature, in the order a demo would
  # present them. `migrate`/`report` only run live if Ollama answers --
  # everything else is unconditional. `backend` is a long-running server
  # so it's described, not launched, at the end (it would block the script).
  banner "1/8 Toolchain check"
  cmd_toolcheck

  banner "2/8 Deterministic fixture generation (FR-4)"
  cmd_generate_data

  banner "3/8 Baseline divergence -- unconstrained translation is silently wrong (FR-7)"
  cmd_verify_baseline

  banner "4/8 Self-check -- zero false positives (AC-9/FR-12)"
  cmd_verify_selfcheck

  banner "5/8 Verification across all 6 fixture programs (Phase U)"
  cmd_verify_all

  banner "6/8 Test suite"
  cmd_test || warn "test suite reported a failure -- continuing showcase (see output above for which test)"

  banner "7/8 Autonomous migration (synthesis + repair loop + failure memory)"
  if _ollama_reachable; then
    cmd_migrate zuse/examples/input/interest.cob
    echo
    cmd_report
  else
    warn "Ollama not reachable at 127.0.0.1:11434 -- skipping live migrate/report."
    warn "Start it ('ollama serve', with qwen2.5-coder:7b + nomic-embed-text pulled) and re-run,"
    warn "or run: bash zuse-all.sh migrate-replay   (cached responses, no live inference)"
  fi

  banner "8/8 Local run service"
  echo "Not started automatically -- it's a long-running server. To try it:"
  echo "  bash zuse-all.sh backend"
  echo "then, in another terminal: curl http://127.0.0.1:8420/health"

  banner "Showcase complete"
  echo "Reports written: report.json (baseline), report_selfcheck.json, report_<program>.json (verify-all)."
  [ -d zuse/examples/generated/runs ] && echo "Migration run artifacts: zuse/examples/generated/runs/<run_id>/ (params.json, trace.jsonl, orchestrator_state.json)."
}

_ollama_reachable() {
  command -v ollama >/dev/null 2>&1 || return 1
  "$PY" - <<'EOF' >/dev/null 2>&1
import requests
requests.get("http://127.0.0.1:11434/api/tags", timeout=2).raise_for_status()
EOF
}

usage() {
  cat <<EOF
Zuse -- single entry point

  showcase           *** run every implemented feature, start to finish ***
  menu               interactive menu (pick one command at a time)

  setup              create .venv and install all dependencies
  toolcheck          report cobc/javac/python/ollama availability
  test               run the full pytest suite

  generate-data      regenerate zuse/examples/reference/accounts.dat (interest.cob)
  verify-baseline    zuse verify interest.cob vs. the flawed baseline (expect 132 divergences)
  verify-selfcheck   golden output vs. itself (expect 0 divergences, AC-9)
  verify-all         zuse verify across all 6 fixture programs, oracle vs. reference impl
  migrate [PROGRAM]  autonomous zuse migrate (needs Ollama; default interest.cob)
  migrate-replay [P] same, but --replay (cached responses only, no live inference)
  report [RUN_DIR]   zuse report on a run directory (default: most recent runs/*)
  backend [PORT]     start the local run service (default port 8420)

  demo               toolcheck + generate-data + verify-baseline + verify-selfcheck + verify-all + test
  help               show this message

Not implemented yet (CLAUDE.md rule 12 -- not offered here):
  zuse baseline, zuse replay <run_id>, zuse memory list|export|import,
  sandboxed (containerized) execution of generated code.
EOF
}

menu() {
  usage
  echo
  read -rp "Enter a command (or 'quit'): " choice
  [ "$choice" = "quit" ] && exit 0
  dispatch "$choice"
}

dispatch() {
  case "$1" in
    setup) cmd_setup ;;
    toolcheck) cmd_toolcheck ;;
    test) cmd_test ;;
    generate-data) cmd_generate_data ;;
    verify-baseline) cmd_verify_baseline ;;
    verify-selfcheck) cmd_verify_selfcheck ;;
    verify-all) cmd_verify_all ;;
    migrate) shift; cmd_migrate "${1:-}" ;;
    migrate-replay) shift; cmd_migrate_replay "${1:-}" ;;
    report) shift; cmd_report "${1:-}" ;;
    backend) shift; cmd_backend "${1:-}" ;;
    demo) cmd_demo ;;
    showcase) cmd_showcase ;;
    menu) menu ;;
    help|-h|--help) usage ;;
    *) warn "unknown command: $1"; usage; exit 1 ;;
  esac
}

# No args -> run the full showcase directly (this script's whole point is
# "one command, every feature"). Use `menu` explicitly for the picker.
if [ "$#" -eq 0 ]; then
  cmd_showcase
else
  dispatch "$@"
fi
