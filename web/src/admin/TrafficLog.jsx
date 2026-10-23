import { useCallback, useEffect, useState } from "react";

const ARROW = { "to-hub": "→ hub", "from-hub": "← hub", "to-instance": "→ instance", "from-instance": "← instance" };

const pretty = v => (v === null || v === undefined ? "—" : typeof v === "string" ? v : JSON.stringify(v, null, 2));

// Every call between instance and hub with all data that went over the wire (secrets masked).
// The same component runs on the instance and in the hub; only `load` differs.
export default function TrafficLog({ load, refreshKey }) {
  const [entries, setEntries] = useState(null);
  const [error, setError] = useState(null);

  const reload = useCallback(() => load().then(d => { setEntries(d.entries); setError(null); }).catch(e => setError(e.message)), [load]);
  useEffect(() => { reload(); }, [reload, refreshKey]);

  return (
    <div className="wh-section">
      <div className="wh-row">
        <h4 className="wh-h">Traffic</h4>
        <button className="wh-btn" onClick={reload}>Refresh</button>
      </div>
      <p className="wh-muted">Every call between this instance and the hub, with all data that went over the wire.
        Secrets are shown as their first characters and a hash, never in full.</p>
      {error && <div className="wh-alert">{error}</div>}
      {entries && entries.length === 0 && <p className="wh-muted">No traffic yet.</p>}
      {entries && entries.map((e, i) => (
        <details key={i} className="wh-traffic">
          <summary>
            <span className="wh-mono">{new Date(e.at).toLocaleString()}</span>
            <span className="wh-dir">{ARROW[e.direction] ?? e.direction}</span>
            <span className="wh-mono">{e.method} {e.url}</span>
            <span className={`wh-badge ${e.status && e.status < 400 ? "wh-badge-ok" : "wh-badge-err"}`}>{e.status ?? "no answer"}</span>
          </summary>
          {e.request_headers && Object.keys(e.request_headers).some(k => e.request_headers[k]) && (
            <><div className="wh-muted">Request headers</div><pre className="wh-pre">{pretty(e.request_headers)}</pre></>
          )}
          <div className="wh-muted">Request body</div><pre className="wh-pre">{pretty(e.request)}</pre>
          <div className="wh-muted">Response</div><pre className="wh-pre">{pretty(e.response)}</pre>
        </details>
      ))}
    </div>
  );
}
