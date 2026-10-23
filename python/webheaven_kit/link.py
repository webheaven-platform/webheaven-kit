"""Linking an instance to a hub (contract: "Linking"). Always started by the instance: request a code, poll until
the owner approved it on the hub, store the credentials, then send a heartbeat every 15 minutes."""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import urlparse

import httpx

from .instance import InstanceStore
from .wirelog import WireLog

HEARTBEAT_SECONDS = 15 * 60


class LinkError(Exception):
    """A problem talking to the hub, with a message that can be shown to the user."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def clean_hub_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise LinkError("the hub address must start with http:// or https://")
    return url


class Linker:
    def __init__(self, store: InstanceStore, product: str, version: str,
                 status: Callable[[], str] = lambda: "ok",
                 client: Callable[[], httpx.Client] | None = None, log: WireLog | None = None):
        self.store, self.product, self.version, self.status = store, product, version, status
        self._client = client or (lambda: httpx.Client(timeout=10.0))
        self._thread: threading.Thread | None = None
        self.log = log or WireLog(store.dir)

    def _post(self, url: str, json: dict, token: str | None = None) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            with self._client() as c:
                r = c.post(url, json=json, headers=headers)
        except httpx.HTTPError as e:
            self.log.record("to-hub", "POST", url, json, None, {"error": str(e)}, headers)
            raise LinkError(f"cannot reach the hub: {e}") from e
        try:
            body = r.json() if r.content else None
        except ValueError:
            body = r.text[:2000]
        self.log.record("to-hub", "POST", url, json, r.status_code, body, headers)
        return r

    def state(self) -> dict:
        inst, link, pending = self.store.instance, self.store.link(), self.store.pending()
        out = {"mode": inst.mode, "visibility": inst.visibility}
        if link:
            out.update(hub_url=link["hub_url"], linked_at=link.get("linked_at"))
        if pending:
            out["pending"] = {k: pending[k] for k in ("hub_url", "user_code", "verification_url", "expires_at")}
        return out

    def start(self, hub_url: str, name: str, base_url: str | None = None, admin_path: str = "") -> dict:
        """base_url: where the hub can reach this instance (optional); the hub gets base_url + admin_path."""
        if self.store.instance.mode == "linked":
            raise LinkError("this instance is already linked; unlink first")
        hub_url = clean_hub_url(hub_url)
        base_url = (base_url or "").strip().rstrip("/")
        admin_url = clean_hub_url(base_url) + admin_path if base_url else None
        r = self._post(f"{hub_url}/api/products/link-requests", {
            "product": self.product, "instance_id": self.store.instance.id, "name": (name or "").strip()[:80],
            "version": self.version, "admin_url": admin_url,
        })
        if r.status_code != 200:
            raise LinkError(f"the hub refused the link request ({r.status_code})")
        d = r.json()
        self.store.set_pending({
            "hub_url": hub_url, "request_id": d["request_id"], "device_secret": d["device_secret"],
            "user_code": d["user_code"], "verification_url": d["verification_url"],
            "expires_at": (_now() + timedelta(seconds=int(d.get("expires_in", 900)))).isoformat(timespec="seconds"),
        })
        return self.state()

    def poll(self) -> str:
        pending = self.store.pending()
        if not pending:
            return "none"
        if datetime.fromisoformat(pending["expires_at"]) < _now():
            self.store.set_pending(None)
            return "expired"
        r = self._post(f"{pending['hub_url']}/api/products/link-requests/poll",
                       {"request_id": pending["request_id"], "device_secret": pending["device_secret"]})
        if r.status_code != 200:
            raise LinkError(f"the hub answered {r.status_code}")
        d = r.json()
        status = d.get("status", "pending")
        if status == "approved" and d.get("link"):
            link = d["link"]
            self.store.set_link({
                "hub_url": link.get("hub_url") or pending["hub_url"],
                "instance_key": link["instance_key"],
                "service_token_sha256": hashlib.sha256(link["service_token"].encode()).hexdigest(),
                "linked_at": _now().isoformat(timespec="seconds"),
            }, link.get("visibility", "health"))
            self.store.set_pending(None)
            self.start_heartbeat()
        elif status in ("rejected", "expired"):
            self.store.set_pending(None)
        return status

    def heartbeat(self) -> bool:
        """True while linked. A 401 means the hub unlinked us: go back to standalone."""
        link = self.store.link()
        if not link:
            return False
        try:
            r = self._post(f"{link['hub_url']}/api/products/heartbeat", {
                "version": self.version, "status": self.status(), "visibility": self.store.instance.visibility,
            }, token=link["instance_key"])
        except LinkError:
            return True   # hub unreachable: stay linked, try again later
        if r.status_code == 401:
            self.store.clear_link()
            return False
        return True

    def unlink(self) -> None:
        link = self.store.link()
        if link:
            try:
                self._post(f"{link['hub_url']}/api/products/unlink", {}, token=link["instance_key"])
            except LinkError:
                pass   # unlinking locally must always work
        self.store.set_pending(None)
        self.store.clear_link()

    def cancel(self) -> None:
        self.store.set_pending(None)

    def start_heartbeat(self, interval: float = HEARTBEAT_SECONDS) -> None:
        """Background heartbeat while linked (one thread; it stops when the instance is standalone again)."""
        if (self._thread and self._thread.is_alive()) or not self.store.link():
            return

        def run():
            while self.heartbeat():
                time.sleep(interval)

        self._thread = threading.Thread(target=run, name="hub-heartbeat", daemon=True)
        self._thread.start()
