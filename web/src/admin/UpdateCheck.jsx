import { useState } from "react";
import { compareVersions } from "./semver.js";

// Only on click, the browser fetches the public release feed: no cookies, no referrer, nothing about
// this instance. A standalone instance therefore never contacts the hub itself.
async function fetchFeed(url) {
  const res = await fetch(url, {
    credentials: "omit", referrerPolicy: "no-referrer", cache: "no-store",
    signal: AbortSignal.timeout(8000),   // a blocked network must not leave the button spinning
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export default function UpdateCheck({ feed, page, current }) {
  const [state, setState] = useState({ status: "idle" });
  if (!feed && !page) return null;

  const check = async () => {
    setState({ status: "busy" });
    try {
      const data = await fetchFeed(feed);
      const newer = (data.releases ?? []).filter(r => compareVersions(r.version, current) > 0);
      setState({ status: "done", newer, update: data.update });
    } catch (e) {
      setState({ status: "failed", error: e.message });
    }
  };

  return (
    <div className="wh-update">
      {feed && <button className="wh-btn" disabled={state.status === "busy"} onClick={check}>
        {state.status === "busy" ? "Checking…" : "Check for updates"}
      </button>}
      {state.status === "done" && state.newer.length === 0 && <span className="wh-ok">You run the latest version ({current}).</span>}
      {state.status === "done" && state.newer.length > 0 && (
        <div className="wh-newer">
          <strong>You run {current} · latest {state.newer[0].version}</strong>
          {state.newer.some(r => r.security) && <span className="wh-badge wh-badge-err">security update</span>}
          <ul>
            {state.newer.map(r => (
              <li key={r.version}>
                <b>{r.version}</b> {r.date && <span className="wh-muted">· {r.date}</span>}
                {r.security && <span className="wh-badge wh-badge-err">security</span>}
                {r.notes && <div className="wh-notes">{r.notes}</div>}
                {r.url && <a href={r.url} target="_blank" rel="noreferrer">release notes</a>}
              </li>
            ))}
          </ul>
          {state.update && <div>Update: <code>{state.update}</code></div>}
        </div>
      )}
      {(state.status === "failed" || !feed) && (
        <span className="wh-muted">
          {state.status === "failed" && "Could not fetch the release feed. "}
          {page && <a href={page} target="_blank" rel="noreferrer">See the releases page</a>}
        </span>
      )}
    </div>
  );
}
