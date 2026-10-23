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

## Linking (adoption) — next version of the contract

Device-code style, always started by the instance: the instance asks the hub for a code, the owner approves it on
the hub (owner, groups, visibility), the instance polls and stores the result in `link.json` (service token,
OIDC client). Not part of v1 yet.
