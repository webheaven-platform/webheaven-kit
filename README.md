# webheaven-kit

Building blocks for apps that **run on their own** and can optionally **link to a hub** for identity,
overview and updates. Open source (Apache-2.0).

- `docs/contract.md` — the product contract (plain HTTP + JSON; usable without this kit)
- `python/` — FastAPI: instance store and admin API
- `web/` — React: the admin module (`@webheaven/kit/admin`), the same components in the product and in a hub

## Install

Not on PyPI/npm yet; install a tagged version from git:

```
pip install "webheaven-kit @ git+https://github.com/webheaven-platform/webheaven-kit@v0.2.2#subdirectory=python"
npm install "@webheaven/kit@github:webheaven-platform/webheaven-kit#v0.2.2"
```

With Vite, add `resolve: { dedupe: ["react", "react-dom"] }` when you link the kit locally (`file:`), so the app
and the kit share one React.

```jsx
import { AdminPanel } from "@webheaven/kit/admin";
import "@webheaven/kit/admin.css";

<AdminPanel base="/api/admin" />
```

A hub shows the same panel for a linked instance by passing its own `fetchJson`, which proxies the request
to the instance with the service token.

## Status

v0.2: instance, visibility levels, admin API (health, info, usage, audit, users), admin module, update check, linking (adoption) with a hub.
Next: OIDC login via the hub.
