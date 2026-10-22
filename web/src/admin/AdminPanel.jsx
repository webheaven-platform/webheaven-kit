import { useEffect, useState } from "react";
import { Audit, Overview, Usage, Users } from "./sections.jsx";

const LABELS = { overview: "Overview", usage: "Usage", audit: "Audit", users: "Users & roles" };
const VIEWS = { usage: Usage, audit: Audit, users: Users };

async function defaultFetch(url) {
  const res = await fetch(url, { credentials: "same-origin" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `${res.status}`);
  return data;
}

// `base`: where the admin API lives (for example "/api/admin"). A hub passes its own `fetchJson`
// that proxies to the instance with the service token; the components stay the same.
export default function AdminPanel({ base = "/api/admin", fetchJson = defaultFetch, extraTabs = [] }) {
  const [core, setCore] = useState(null);
  const [tab, setTab] = useState("overview");
  const [data, setData] = useState({});
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([fetchJson(`${base}/health`), fetchJson(`${base}/info`)])
      .then(([health, info]) => setCore({ health, info }))
      .catch(e => setError(e.message));
  }, [base, fetchJson]);

  useEffect(() => {
    if (!VIEWS[tab] || data[tab]) return;
    fetchJson(`${base}/${tab}`).then(d => setData(prev => ({ ...prev, [tab]: d }))).catch(e => setError(e.message));
  }, [tab, base, fetchJson, data]);

  if (error) return <div className="wh-admin"><div className="wh-alert">Admin: {error}</div></div>;
  if (!core) return <div className="wh-admin wh-muted">Loading…</div>;

  const tabs = [...core.info.sections.map(id => ({ id, label: LABELS[id] })), ...extraTabs];
  const View = VIEWS[tab];
  const extra = extraTabs.find(t => t.id === tab);
  return (
    <div className="wh-admin">
      <div className="wh-tabs">
        {tabs.map(t => <button key={t.id} className={t.id === tab ? "wh-tab active" : "wh-tab"} onClick={() => setTab(t.id)}>{t.label}</button>)}
      </div>
      {tab === "overview" && <Overview health={core.health} info={core.info} />}
      {View && (data[tab] ? <View data={data[tab]} /> : <p className="wh-muted">Loading…</p>)}
      {extra && extra.render()}
    </div>
  );
}
