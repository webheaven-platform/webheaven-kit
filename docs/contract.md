# Product contract (v1)

How a product (an app that runs on its own) talks to a **hub** (an optional central place for identity,
overview and updates). The contract is plain HTTP and JSON: a product can implement it without this kit.
This kit is the reference implementation.

## Principles

1. **A product always works on its own.** The hub is optional, and an unreachable hub never breaks the product.
2. **Data stays in the product.** The hub reads what the product allows; it copies nothing.
3. **A standalone product never contacts a hub.** Not even to check for updates (that check is a user action
   in the browser, see "Releases").
4. **The product decides how much the hub may see** (the visibility level). The hub can only lower it.

## Instance

Every installation is an **instance** with a random id, created on first start and kept in the data directory:

```
<data>/instance.json   {"id": "…", "created": "…", "mode": "standalone" | "linked", "visibility": "health"}
<data>/link.json       only when linked: hub URL, service-token hash, OIDC client (later)
```

The data directory holds no content: content stays where the product keeps it (a database, git, files).

## Visibility levels

| Level | The hub may read |
|---|---|
| `health` | `/health` and the instance part of `/info` |
| `statistics` | + the product part of `/info` and `/usage` |
| `full` | + `/audit` and `/users` |

## Admin API

Mounted by the product under a base path it chooses (for example `/api/admin`); the hub stores that base URL when linking.

| Method + path | Level | Returns |
|---|---|---|
| `GET /health` | health | `{contract, product, version, status: "ok"\|"degraded", checks: {name: "ok"\|message}, instance: {id, mode}}` |
| `GET /info` | health | `{contract, product, version, instance: {id, mode, visibility, created}, sections: [...], releases: {feed, page}, product_info: {...}\|null}` — `product_info` from level `statistics` |
| `GET /usage` | statistics | `{metrics: [{key, label, value}], period: "…"}` |
| `GET /audit?limit=50` | full | `{entries: [{time, actor, action, target, detail}]}` |
| `GET /users` | full | `{users: [{name, email, role, last_seen}]}` |

- `sections` lists what the caller may open: `overview` always, then `usage`, `audit`, `users` when the product
  supports them and the caller's level allows them.
- A product that does not support a section answers `404`; a level that is too low answers `403`.
- `contract` is the contract version (now `1`). A hub reads the current and the previous version.

### Who is calling

- **The product's own UI**: the product's own authentication decides (a product without login, used locally, allows all).
  The own UI always gets level `full`.
- **The hub**: `Authorization: Bearer <service token>`, issued when linking. The level is the instance's visibility.
- Anything else: `401`.

## Releases

A product publishes a **release feed**: public JSON, anonymous, cacheable.

```json
{
  "product": "railvane",
  "releases": [
    {"version": "0.5.0", "date": "2026-10-23", "security": false,
     "notes": "Markdown text", "url": "https://…/releases/v0.5.0"}
  ],
  "update": "docker compose pull && docker compose up -d"
}
```

Newest first, no drafts or pre-releases. `security` is true when the release notes have a
`## Security` heading (that is how a hub derives it from GitHub Releases). Also offered as RSS (`…/rss`).
The feed is served with `Access-Control-Allow-Origin: *` and without cookies.

The admin overview has a **Check for updates** button: only on click, the **browser** fetches the feed
(no cookies, no referrer, nothing about the instance) and compares the versions itself. If the fetch fails it shows
a link to the release page. A standalone instance therefore never contacts the hub itself.

## Linking (adoption)

Device-code style and **always started by the instance**, so it also works behind a firewall. The hub never
initiates contact with an instance that did not link itself.

```
instance                                   hub                                       owner
POST /api/products/link-requests  ───────► request + user code (15 min)
show code + verification URL                                                     ──► opens URL, logged in as admin
                                           shows product, name, version, base URL
                                           owner picks visibility (default health)  ◄── approves / rejects
POST /api/products/link-requests/poll ───► approved: credentials, delivered once
store link.json, mode = linked
POST /api/products/heartbeat (15 min) ───► last seen, version, status
```

### Hub endpoints (instance-facing, no user login)

| Method + path | Auth | Body → result |
|---|---|---|
| `POST /api/products/link-requests` | none (rate limited) | `{product, instance_id, name, version, admin_url?}` → `{request_id, device_secret, user_code, verification_url, expires_in, interval}` |
| `POST /api/products/link-requests/poll` | `device_secret` in body | `{request_id, device_secret}` → `{status: pending\|approved\|rejected\|expired, link?}` |
| `POST /api/products/heartbeat` | `Bearer <instance key>` | `{version, status, visibility, catalog_hash?}` → `200` (`{catalog: "send"\|"ok"}` for products with a catalog); `401` = the hub no longer knows this instance |
| `POST /api/products/catalog` | `Bearer <instance key>` | `{hash, items}` → `204` (see "Catalog") |
| `POST /api/products/unlink` | `Bearer <instance key>` | → `204` |

`link` (only once, on the first poll after approval): `{hub_url, instance_key, service_token, visibility}`.

### Credentials

- **Instance key**: the instance authenticates to the hub (heartbeat, unlink). The hub keeps only a hash.
- **Service token**: the hub authenticates to the instance's admin API. The instance keeps only a hash
  (`service_token_sha256` in `link.json`); the hub keeps it encrypted, because it has to send it.

### Instance side

- `link.json`: `{hub_url, instance_key, service_token_sha256, linked_at}`; `instance.json` gets `mode: linked` and the
  visibility chosen at approval. The owner can change the visibility on the instance afterwards.
- A heartbeat answered with `401` means the hub unlinked the instance: it deletes `link.json` and goes back to standalone.
- `admin_url` (the full URL of the admin API, e.g. `http://host:8484/api/admin`) is optional. When set, the hub
  reads the admin API there (only the fixed admin paths); when not set (a laptop), the hub only knows what the
  heartbeats tell it.

### Managing the link on the instance

The admin API gets these local-only endpoints (never callable with the service token):

| Method + path | Body → result |
|---|---|
| `GET /link` | `{mode, manage: open\|password\|disabled, hub_url?, linked_at?, visibility, pending?: {user_code, verification_url, expires_at}}` |
| `POST /link/start` | `{hub_url, name, base_url?}` → pending |
| `POST /link/poll` | → `{status}` |
| `POST /link/unlink` | → standalone |
| `POST /visibility` | `{level}` |
| `GET /catalog` | → `{enabled, items}`: exactly what the hub would get (only for products with a catalog) |
| `POST /catalog` | `{enabled}` → share the catalog or stop sharing it |

`manage` tells the UI who may change the link: `open` (local tool), `password` (header `X-Admin-Password`, for
example a product in server mode without accounts) or `disabled`.

## Catalog (optional, kit 0.3)

A product can share a **catalog** with the hub: a list of its main items (for example the dossiers of a
case-management app) so the owner gets one overview across instances. It is metadata only: the product decides what
is in an item, and never puts content in it.

- **Pushed by the instance**, never read by the hub, so it also works for an instance the hub cannot reach (a laptop).
- Every heartbeat carries `catalog_hash` (sha256 of the canonical JSON of the items). The hub answers
  `{"catalog": "send"}` when it has another hash and the owner allowed the catalog; the instance then posts the items.
  An unchanged catalog costs one hash per heartbeat.
- `catalog_hash: null` means the instance stopped sharing: the hub deletes what it has. A heartbeat without the field
  (older kit, or the catalog could not be built this time) leaves the hub's copy as it is.
- **Item**: `{id, title, ...}`. `id` and `title` are required (title at most 200 characters); everything else is
  product-defined, for example `group`, `status`, `updated`, `counts: {name: number}`, `flags: {name: bool}`.
  At most 2000 items.
- **Who decides**: the instance (`instance.json` → `catalog`, default on for products that offer one, `POST /catalog`
  to change it) and the hub owner (on or off at approval, can be switched off later). Both must allow it.
- Unlinking deletes the catalog on the hub.

## Backup (optional, kit 0.4)

A linked instance can keep an **encrypted backup on the hub**. The hub stores blobs it cannot read.

- **Key and recovery code**: the instance makes a random 256-bit key (`backup-key.json` in the data directory) and shows
  it once as a recovery code (base32, groups of four). The hub never sees it; without it a backup cannot be restored.
- **Blobs**: one per file, AES-256-GCM with a random nonce and the blob id as associated data. Blob id =
  HMAC-SHA256(key, content): unchanged files are not sent again and the id reveals nothing to the hub.
- **Manifest**: the list of paths and their blobs, encrypted as a blob too. The hub only learns the blob ids per backup,
  so it knows which blobs it may delete when it drops an old backup.
- **Who decides**: the instance (`POST /backup/enable`, off by default) and the hub owner (off by default, per
  installation). Both must allow it; the hub answers `403` otherwise and `413` when the quota is full.
- **Schedule**: daily while enabled, plus `POST /backup/run`.

### Hub endpoints (instance-facing, `Bearer <instance key>`)

| Method + path | Body → result |
|---|---|
| `POST /api/products/backups/check` | `{blobs: [id]}` → `{missing: [id]}` |
| `PUT /api/products/backups/blobs/{id}` | encrypted bytes → `204` |
| `POST /api/products/backups` | `{manifest, blobs: [id], files, size}` → `{id}` |

The hub keeps backups per its own schedule (for example 7 daily and 4 weekly) and deletes blobs no remaining backup uses.

### Restore

The owner downloads a backup from the hub as a **bundle** (zip: `backup.json` with the manifest id, plus
`blobs/<id>` for every blob of that backup) and restores it anywhere with the recovery code
(`webheaven_kit.restore_bundle`), without a link to the hub: every file is checked against its blob id.

### Local endpoints (admin API, never with the service token)

| Method + path | Body → result |
|---|---|
| `GET /backup` | `{enabled, has_key, last}` |
| `POST /backup/enable` | → `{…, recovery_code}` |
| `POST /backup/disable` | → state |
| `POST /backup/run` | → `{started}` |
