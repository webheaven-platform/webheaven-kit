import { useCallback, useEffect, useState } from "react";
import TrafficLog from "./TrafficLog.jsx";

const LEVELS = [
  ["health", "Health only — version and status"],
  ["statistics", "Statistics — also usage numbers"],
  ["full", "Full — also audit trail and users"],
];

// Managing the link happens on the instance itself (never through the hub), so this talks to the own API directly.
async function call(url, method = "GET", body, password) {
  const headers = { ...(body ? { "Content-Type": "application/json" } : {}), ...(password ? { "X-Admin-Password": password } : {}) };
  const res = await fetch(url, { method, headers, credentials: "same-origin", body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `${res.status}`);
  return data;
}

export default function LinkTab({ base, defaultHub = "https://webheaven.nl" }) {
  const [state, setState] = useState(null);
  const [form, setForm] = useState({ hub_url: defaultHub, name: "", base_url: "" });
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  const loadTraffic = useCallback(() => call(`${base}/link/traffic`), [base]);

  const act = useCallback(async (path, method, body) => {
    setBusy(true); setError(null);
    try { setState(await call(`${base}/${path}`, method, body, password)); } catch (e) { setError(e.message); }
    setBusy(false); setTick(t => t + 1);
  }, [base, password]);

  useEffect(() => { call(`${base}/link`).then(setState).catch(e => setError(e.message)); }, [base]);

  // While a code is waiting for approval, ask every 5 s whether the owner approved it on the hub.
  useEffect(() => {
    if (!state?.pending) return;
    const t = setInterval(() => call(`${base}/link/poll`, "POST").then(setState).catch(e => setError(e.message)).finally(() => setTick(x => x + 1)), 5000);
    return () => clearInterval(t);
  }, [base, state?.pending]);

  if (!state) return error ? <div className="wh-alert">{error}</div> : <p className="wh-muted">Loading…</p>;
  const set = k => e => setForm(f => ({ ...f, [k]: e.target.value }));
  const needsPassword = state.manage === "password";
  const pw = needsPassword && (
    <label className="wh-field">Admin password<input type="password" value={password} onChange={e => setPassword(e.target.value)} /></label>
  );

  return (
    <div className="wh-section">
      {error && <div className="wh-alert">{error}</div>}

      {state.mode === "linked" && (
        <>
          <p>Linked to <b>{state.hub_url}</b>{state.linked_at && <span className="wh-muted"> · since {new Date(state.linked_at).toLocaleString()}</span>}</p>
          <label className="wh-field">The hub may see
            <select value={state.visibility} disabled={busy || state.manage === "disabled"}
              onChange={e => act("visibility", "POST", { level: e.target.value })}>
              {LEVELS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          {pw}
          <button className="wh-btn" disabled={busy || state.manage === "disabled"}
            onClick={() => confirm("Unlink this instance from the hub?") && act("link/unlink", "POST")}>Unlink</button>
        </>
      )}

      {state.mode !== "linked" && state.pending && (
        <>
          <p>Go to <a href={state.pending.verification_url} target="_blank" rel="noreferrer">{state.pending.verification_url}</a> and
            approve code <b className="wh-mono">{state.pending.user_code}</b>.</p>
          <p className="wh-muted">Waiting for approval… (valid until {new Date(state.pending.expires_at).toLocaleTimeString()})</p>
          {pw}
          <button className="wh-btn" disabled={busy} onClick={() => act("link/cancel", "POST")}>Cancel</button>
        </>
      )}

      {state.mode !== "linked" && !state.pending && (
        <>
          <p>Standalone — this instance never contacts a hub. Linking gives you sign-in with your hub account,
            update notices and an overview in the hub. You choose what the hub may see; data stays here.</p>
          {state.manage === "disabled" ? <p className="wh-muted">Linking is disabled on this instance.</p> : (
            <div className="wh-form">
              <label className="wh-field">Hub address<input value={form.hub_url} onChange={set("hub_url")} /></label>
              <label className="wh-field">Name of this instance<input value={form.name} placeholder="e.g. work-laptop" onChange={set("name")} /></label>
              <label className="wh-field">Address where the hub can reach this instance (optional)
                <input value={form.base_url} placeholder="leave empty for a laptop" onChange={set("base_url")} /></label>
              {pw}
              <button className="wh-btn" disabled={busy || !form.hub_url || (needsPassword && !password)}
                onClick={() => act("link/start", "POST", form)}>{busy ? "Requesting…" : "Link to hub"}</button>
              <p className="wh-muted">This instance will contact {form.hub_url || "the hub"} to request a link code.</p>
            </div>
          )}
        </>
      )}

      <TrafficLog load={loadTraffic} refreshKey={tick} />
    </div>
  );
}
