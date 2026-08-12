// Renders a Report's divergence list verbatim (weaver/report.py Report.to_json()).
// No comparison or classification logic here -- every value is already
// decided by the oracle harness before it reaches this component.
export default function DivergenceTable({ report }) {
  if (!report) return null
  const rows = report.divergences || []
  const shown = rows.length
  const extra = Math.max(0, (report.divergence_count || 0) - shown)
  return (
    <div className="dv-wrap">
      <div className="dv-cap">
        <span className="cell-title">Divergences · oracle vs candidate</span>
        <span className="dv-count">{report.divergence_count}</span>
      </div>
      <div className="dv-scroll">
        <div className="dv-table" style={{ gridTemplateColumns: 'max-content max-content 1fr 1fr max-content' }}>
          <div className="dv-h">Rec</div>
          <div className="dv-h">Field</div>
          <div className="dv-h">Expected (oracle)</div>
          <div className="dv-h">Actual</div>
          <div className="dv-h">Δ</div>
          {rows.map((d, i) => {
            const last = i === rows.length - 1 && !extra
            return (
              <div key={i} className={'dv-row' + (last ? ' dv-row-last' : '')} style={{ display: 'contents' }}>
                <div className="dv-c dv-rec">{d.record_index}</div>
                <div className="dv-c dv-field">{d.field_name}</div>
                <div className="dv-c">{d.oracle_value}</div>
                <div className="dv-c">{d.candidate_value}</div>
                <div className="dv-c">{d.numeric_delta ?? '—'}</div>
              </div>
            )
          })}
        </div>
      </div>
      {extra > 0 && (
        <div className="dv-more">
          <span>
            + {extra} more (list capped{report.divergence_list_capped ? '' : ', but count above is exact'})
          </span>
        </div>
      )}
      {rows.length === 0 && report.divergence_count === 0 && (
        <div className="dv-more">0 divergences · {report.total_records} report line(s) compared · exit codes {report.exit_codes_match ? 'match' : 'differ'}</div>
      )}
    </div>
  )
}
