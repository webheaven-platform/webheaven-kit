import hashlib
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from webheaven_kit import AdminProvider, InstanceStore, Linker, admin_router


class FakeHub:
    """Just enough of a hub: link requests, approval, heartbeat, unlink."""

    def __init__(self):
        self.status = "pending"
        self.known = True
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content or b"{}")
        self.calls.append((path, body, request.headers.get("authorization")))
        if path == "/api/products/link-requests":
            return httpx.Response(200, json={"request_id": 7, "device_secret": "dev", "user_code": "7KQ-4MZ",
                                             "verification_url": "https://hub.test/admin/products/link?code=7KQ-4MZ",
                                             "expires_in": 900, "interval": 5})
        if path == "/api/products/link-requests/poll":
            assert body == {"request_id": 7, "device_secret": "dev"}
            out = {"status": self.status}
            if self.status == "approved":
                out["link"] = {"hub_url": "https://hub.test", "instance_key": "ik", "service_token": "st",
                               "visibility": "statistics"}
            return httpx.Response(200, json=out)
        if path == "/api/products/heartbeat":
            return httpx.Response(200 if self.known and request.headers["authorization"] == "Bearer ik" else 401)
        if path == "/api/products/unlink":
            return httpx.Response(204)
        return httpx.Response(404)


class Demo(AdminProvider):
    product, version = "demo", "1.0.0"


@pytest.fixture
def hub():
    return FakeHub()


def make(tmp_path, hub, manage="open", password=None):
    store = InstanceStore(tmp_path)
    linker = Linker(store, "demo", "1.0.0", client=lambda: httpx.Client(transport=httpx.MockTransport(hub.handler)))
    app = FastAPI()
    app.include_router(admin_router(Demo(), store, prefix="/api/admin", linker=linker,
                                    manage=manage, manage_password=password))
    return store, linker, TestClient(app)


def test_full_link_flow(tmp_path, hub):
    store, linker, c = make(tmp_path, hub)
    assert c.get("/api/admin/link").json()["mode"] == "standalone"
    started = c.post("/api/admin/link/start", json={"hub_url": "https://hub.test/", "name": "laptop"}).json()
    assert started["pending"]["user_code"] == "7KQ-4MZ" and "device_secret" not in json.dumps(started)
    assert hub.calls[0][1]["instance_id"] == store.instance.id and hub.calls[0][1]["admin_url"] is None
    assert c.post("/api/admin/link/poll").json()["status"] == "pending"

    hub.status = "approved"
    linker.start_heartbeat = lambda interval=0: None   # no background thread in tests
    polled = c.post("/api/admin/link/poll").json()
    assert polled["status"] == "approved" and polled["mode"] == "linked" and polled["visibility"] == "statistics"
    link = json.loads((tmp_path / "link.json").read_text())
    assert link["instance_key"] == "ik" and link["service_token_sha256"] == hashlib.sha256(b"st").hexdigest()
    assert "service_token" not in link   # only the hash is kept
    assert not (tmp_path / "link-pending.json").exists()

    # the hub can now read the admin API with its service token, up to the visibility
    info = c.get("/api/admin/info", headers={"Authorization": "Bearer st"}).json()
    assert "link" not in info["sections"]   # the hub never manages the link
    assert c.post("/api/admin/link/unlink", headers={"Authorization": "Bearer st"}).status_code == 403
    assert "link" in c.get("/api/admin/info").json()["sections"]


def test_heartbeat_and_unlinked_by_the_hub(tmp_path, hub):
    store, linker, c = make(tmp_path, hub)
    store.set_link({"hub_url": "https://hub.test", "instance_key": "ik", "service_token_sha256": "x"}, "health")
    assert linker.heartbeat() is True
    assert hub.calls[-1][1] == {"version": "1.0.0", "status": "ok", "visibility": "health"}
    hub.known = False
    assert linker.heartbeat() is False
    assert store.instance.mode == "standalone" and not (tmp_path / "link.json").exists()


def test_unlink_works_even_if_the_hub_is_down(tmp_path):
    def down(request):
        raise httpx.ConnectError("down")
    store = InstanceStore(tmp_path)
    store.set_link({"hub_url": "https://hub.test", "instance_key": "ik", "service_token_sha256": "x"}, "full")
    Linker(store, "demo", "1", client=lambda: httpx.Client(transport=httpx.MockTransport(down))).unlink()
    assert store.instance.mode == "standalone"


def test_admin_url_is_base_plus_admin_path(tmp_path, hub):
    _, _, c = make(tmp_path, hub)
    c.post("/api/admin/link/start", json={"hub_url": "https://hub.test", "base_url": "http://10.1.2.3:8484/"})
    assert hub.calls[0][1]["admin_url"] == "http://10.1.2.3:8484/api/admin"


def test_rejected_and_bad_hub_url(tmp_path, hub):
    store, linker, c = make(tmp_path, hub)
    assert c.post("/api/admin/link/start", json={"hub_url": "ftp://x"}).status_code == 502
    c.post("/api/admin/link/start", json={"hub_url": "https://hub.test"})
    hub.status = "rejected"
    assert c.post("/api/admin/link/poll").json()["status"] == "rejected"
    assert "pending" not in c.get("/api/admin/link").json()


@pytest.mark.parametrize("manage,password,header,code", [
    ("password", "s3cret", None, 403),
    ("password", "s3cret", "wrong", 403),
    ("password", "s3cret", "s3cret", 200),
    ("password", None, "anything", 403),    # password mode without a password = disabled
    ("disabled", None, None, 403),
])
def test_who_may_manage(tmp_path, hub, manage, password, header, code):
    _, _, c = make(tmp_path, hub, manage=manage, password=password)
    headers = {"X-Admin-Password": header} if header else {}
    assert c.post("/api/admin/link/start", json={"hub_url": "https://hub.test"}, headers=headers).status_code == code
    assert c.get("/api/admin/link").status_code == 200   # reading the state is always allowed locally


def test_visibility_can_be_changed_locally(tmp_path, hub):
    store, _, c = make(tmp_path, hub)
    assert c.post("/api/admin/visibility", json={"level": "full"}).json()["visibility"] == "full"
    assert c.post("/api/admin/visibility", json={"level": "everything"}).status_code == 422


def test_traffic_log_shows_every_call_with_secrets_masked(tmp_path, hub):
    store, linker, c = make(tmp_path, hub)
    linker.start_heartbeat = lambda interval=0: None
    c.post("/api/admin/link/start", json={"hub_url": "https://hub.test", "name": "laptop"})
    hub.status = "approved"
    c.post("/api/admin/link/poll")
    c.get("/api/admin/info", headers={"Authorization": "Bearer st"})        # the hub reads us
    c.get("/api/admin/usage", headers={"Authorization": "Bearer st"})       # not allowed at "statistics"? usage is
    c.get("/api/admin/info", headers={"Authorization": "Bearer wrong"})     # unknown token

    entries = c.get("/api/admin/link/traffic").json()["entries"]            # newest first
    text = json.dumps(entries)
    assert '"dev"' not in text and '"ik"' not in text and '"st"' not in text   # no working secret in the log
    assert "Bearer st" not in text and "sha256" in text

    to_hub = [e for e in entries if e["direction"] == "to-hub"]
    assert [e["url"] for e in reversed(to_hub)] == ["https://hub.test/api/products/link-requests",
                                                    "https://hub.test/api/products/link-requests/poll"]
    request_call = to_hub[-1]
    assert request_call["request"]["name"] == "laptop" and request_call["status"] == 200
    assert request_call["response"]["user_code"] == "7KQ-4MZ"            # exactly what came back

    from_hub = [e for e in entries if e["direction"] == "from-hub"]
    assert [e["status"] for e in reversed(from_hub)] == [200, 404, 401]   # usage: demo has no usage section
    assert from_hub[-1]["response"]["product"] == "demo"                 # exactly what left the instance
    assert c.get("/api/admin/link/traffic", headers={"Authorization": "Bearer st"}).status_code == 403
    assert (tmp_path / "link-traffic.jsonl").exists()


def test_mask():
    from webheaven_kit.wirelog import mask, redact
    long_key = "whi_" + "a" * 40
    assert mask("Bearer " + long_key).startswith("Bearer whi_") and long_key not in mask("Bearer " + long_key)
    assert "abc" not in mask("abc") and "sha256" in mask("abc")          # short values: nothing visible
    assert redact({"a": 1, "instance_key": "x", "nested": [{"service_token": "y"}]})["nested"][0]["service_token"] != "y"
