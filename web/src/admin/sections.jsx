import { Fragment } from "react";
import UpdateCheck from "./UpdateCheck.jsx";

const fmtTime = t => (t ? new Date(t).toLocaleString() : "");

export function Overview({ health, info }) {
  const inst = info.instance;
  return (
    <div className="wh-section">
      <dl className="wh-dl">
        <dt>Product</dt><dd>{info.product} {info.version}</dd>
        <dt>Status</dt><dd><span className={`wh-badge ${health.status === "ok" ? "wh-badge-ok" : "wh-badge-err"}`}>{health.status}</span></dd>
        {Object.entries(health.checks ?? {}).map(([k, v]) => (
          <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>
        ))}
        <dt>Mode</dt><dd>{inst.mode === "linked" ? "Linked to a hub" : "Standalone — never contacts a hub"}</dd>
        {inst.mode === "linked" && <><dt>Hub may see</dt><dd>{inst.visibility}</dd></>}
        <dt>Instance</dt><dd className="wh-mono">{inst.id}</dd>
        {inst.created && <><dt>Since</dt><dd>{fmtTime(inst.created)}</dd></>}
      </dl>
      {info.product_info && Object.keys(info.product_info).length > 0 && (
        <dl className="wh-dl">
          {Object.entries(info.product_info).map(([k, v]) => (
            <Fragment key={k}><dt>{k}</dt><dd>{String(v)}</dd></Fragment>
          ))}
        </dl>
      )}
      <UpdateCheck feed={info.releases?.feed} page={info.releases?.page} current={info.version} />
    </div>
  );
}

export function Usage({ data }) {
  return (
    <div className="wh-section">
      <div className="wh-metrics">
        {data.metrics.map(m => (
          <div key={m.key} className="wh-metric"><div className="wh-metric-value">{m.value}</div><div className="wh-muted">{m.label}</div></div>
        ))}
      </div>
      {data.period && <p className="wh-muted">Period: {data.period}</p>}
    </div>
  );
}

export function Audit({ data }) {
  if (!data.entries.length) return <p className="wh-muted">No entries yet.</p>;
  return (
    <table className="wh-table">
      <thead><tr><th>Time</th><th>Who</th><th>Action</th><th>Target</th><th>Detail</th></tr></thead>
      <tbody>
        {data.entries.map((e, i) => (
          <tr key={i}><td>{fmtTime(e.time)}</td><td>{e.actor}</td><td>{e.action}</td><td>{e.target}</td><td>{e.detail}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

export function Users({ data }) {
  return (
    <table className="wh-table">
      <thead><tr><th>Name</th><th>E-mail</th><th>Role</th><th>Last seen</th></tr></thead>
      <tbody>
        {data.users.map((u, i) => (
          <tr key={i}><td>{u.name}</td><td>{u.email}</td><td>{u.role}</td><td>{fmtTime(u.last_seen)}</td></tr>
        ))}
      </tbody>
    </table>
  );
}
