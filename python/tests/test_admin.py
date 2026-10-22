import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from webheaven_kit import AdminProvider, InstanceStore, admin_router, allows


class Demo(AdminProvider):
    product, version = "demo", "1.2.0"
    features = frozenset({"usage", "audit"})
    releases_feed = "https://hub.example/api/public/releases/demo"

    def checks(self):
        return {"storage": "ok"}

    def info(self):
        return {"items": 3}

    def usage(self):
        return {"metrics": [{"key": "items", "label": "Items", "value": 3}], "period": "now"}

    def audit(self, limit):
        return [{"time": "2026-10-22T10:00:00Z", "actor": "bart", "action": "commit", "target": "ws", "detail": "x"}][:limit]


def link(store: InstanceStore, token: str, visibility: str) -> None:
    store.instance.mode = "linked"
    store.set_visibility(visibility)
    (store.dir / "link.json").write_text(json.dumps(
        {"hub": "https://hub.example", "service_token_sha256": hashlib.sha256(token.encode()).hexdigest()}))


def client(store, local=True) -> TestClient:
    app = FastAPI()
    app.include_router(admin_router(Demo(), store, prefix="/api/admin", local_access=lambda r: local))
    return TestClient(app)


def test_levels():
    assert allows("full", "health") and allows("statistics", "statistics")
    assert not allows("health", "statistics") and not allows("bogus", "health")


def test_instance_is_created_once(tmp_path):
    first = InstanceStore(tmp_path).instance
    again = InstanceStore(tmp_path).instance
    assert first.id == again.id and first.mode == "standalone" and first.visibility == "health"


def test_instance_in_memory_without_data_dir():
    assert InstanceStore(None).instance.id


def test_own_ui_sees_everything_it_supports(tmp_path):
    c = client(InstanceStore(tmp_path))
    info = c.get("/api/admin/info").json()
    assert info["sections"] == ["overview", "usage", "audit"]
    assert info["product_info"] == {"items": 3}
    assert info["releases"]["feed"].endswith("/demo")
    assert c.get("/api/admin/health").json()["status"] == "ok"
    assert c.get("/api/admin/audit?limit=1").json()["entries"][0]["actor"] == "bart"
    assert c.get("/api/admin/users").status_code == 404   # not supported by this product


def test_without_local_access_and_token_is_401(tmp_path):
    assert client(InstanceStore(tmp_path), local=False).get("/api/admin/health").status_code == 401


def test_standalone_accepts_no_service_token(tmp_path):
    c = client(InstanceStore(tmp_path))
    assert c.get("/api/admin/health", headers={"Authorization": "Bearer anything"}).status_code == 401


@pytest.mark.parametrize("visibility,sections", [
    ("health", ["overview"]),
    ("statistics", ["overview", "usage"]),
    ("full", ["overview", "usage", "audit"]),
])
def test_hub_sees_up_to_the_visibility_level(tmp_path, visibility, sections):
    store = InstanceStore(tmp_path)
    link(store, "s3cret", visibility)
    c = client(store, local=False)
    auth = {"Authorization": "Bearer s3cret"}
    info = c.get("/api/admin/info", headers=auth).json()
    assert info["sections"] == sections
    assert (info["product_info"] is None) == (visibility == "health")
    assert c.get("/api/admin/usage", headers=auth).status_code == (200 if "usage" in sections else 403)
    assert c.get("/api/admin/audit", headers=auth).status_code == (200 if "audit" in sections else 403)
    assert c.get("/api/admin/health", headers={"Authorization": "Bearer wrong"}).status_code == 401
