import io
import json
import zipfile

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from webheaven_kit import AdminProvider, BackupError, Backupper, InstanceStore, Linker, admin_router, restore_bundle
from webheaven_kit.backup import key_from_code, recovery_code


class BackupHub:
    """Just enough of a hub for backups: which blobs are missing, store blobs, register a backup."""

    def __init__(self):
        self.blobs: dict[str, bytes] = {}
        self.backups: list[dict] = []
        self.allowed = True
        self.puts = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if not self.allowed:
            return httpx.Response(403, json={"detail": "off"})
        path = request.url.path.removeprefix("/api/products/backups")
        if path == "/check":
            wanted = json.loads(request.content)["blobs"]
            return httpx.Response(200, json={"missing": [b for b in wanted if b not in self.blobs]})
        if path.startswith("/blobs/") and request.method == "PUT":
            self.blobs[path[7:]] = request.content
            self.puts.append(path[7:])
            return httpx.Response(204)
        if path == "" and request.method == "POST":
            self.backups.append(json.loads(request.content))
            return httpx.Response(200, json={"id": len(self.backups)})
        return httpx.Response(404)

    def bundle(self, index=-1) -> bytes:
        """What the owner downloads: backup.json + every blob of that backup."""
        b = self.backups[index]
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("backup.json", json.dumps({"manifest": b["manifest"]}))
            for bid in b["blobs"] + [b["manifest"]]:
                z.writestr(f"blobs/{bid}", self.blobs[bid])
        return out.getvalue()


class Demo(AdminProvider):
    product, version = "demo", "1.0.0"


@pytest.fixture
def setup(tmp_path):
    hub = BackupHub()
    data = tmp_path / "content"
    data.mkdir()
    (data / "db.sqlite").write_bytes(b"SQLite format 3 secret dossier text")
    (data / "a.pdf").write_bytes(b"%PDF loonstrook BSN 123456789")
    store = InstanceStore(tmp_path / "instance")
    store.set_link({"hub_url": "https://hub.test", "instance_key": "ik", "service_token_sha256": "x"}, "health")
    linker = Linker(store, "demo", "1.0.0", client=lambda: httpx.Client(transport=httpx.MockTransport(hub.handler)))
    source = lambda: [("db/binnacle.sqlite", data / "db.sqlite"), ("files/a.pdf", data / "a.pdf")]  # noqa: E731
    return hub, Backupper(store, linker, source, "demo", "1.0.0"), data, tmp_path


def test_backup_is_encrypted_deduplicated_and_restorable(setup):
    hub, backupper, data, tmp_path = setup
    code = backupper.enable()
    assert backupper.run()["ok"] is True
    stored = b"".join(hub.blobs.values())
    assert b"secret" not in stored and b"BSN" not in stored and b"a.pdf" not in stored   # nothing readable
    assert len(hub.backups[0]["blobs"]) == 2

    (data / "db.sqlite").write_bytes(b"SQLite format 3 changed")
    hub.puts.clear()
    last = backupper.run()
    assert last["new_blobs"] == 1 and len(hub.puts) == 2        # changed db + the new manifest, not the pdf

    restored = restore_bundle(hub.bundle(), code, tmp_path / "restore")
    assert restored["files"] == 2
    assert (tmp_path / "restore" / "db" / "binnacle.sqlite").read_bytes() == b"SQLite format 3 changed"
    assert (tmp_path / "restore" / "files" / "a.pdf").read_bytes() == (data / "a.pdf").read_bytes()


def test_wrong_code_or_damaged_backup_fails(setup):
    hub, backupper, _, tmp_path = setup
    backupper.enable()
    backupper.run()
    with pytest.raises(BackupError):
        restore_bundle(hub.bundle(), recovery_code(b"\0" * 32), tmp_path / "r1")
    with pytest.raises(BackupError):
        restore_bundle(hub.bundle(), "not-a-code", tmp_path / "r2")


def test_off_on_the_instance_or_the_hub(setup):
    hub, backupper, _, _ = setup
    with pytest.raises(BackupError, match="off on this installation"):
        backupper.run()
    backupper.enable()
    hub.allowed = False
    with pytest.raises(BackupError, match="hub owner"):
        backupper.run()
    assert backupper.state()["last"]["ok"] is False


def test_recovery_code_round_trip_and_key_kept(setup):
    _, backupper, _, _ = setup
    code = backupper.enable()
    assert backupper.enable() == code                            # the key is made once
    assert recovery_code(key_from_code(code.lower().replace("-", " "))) == code


def test_local_endpoints(setup):
    hub, backupper, _, _ = setup
    app = FastAPI()
    app.include_router(admin_router(Demo(), backupper.store, prefix="/api/admin", linker=backupper.linker,
                                    backupper=backupper))
    c = TestClient(app)
    assert c.get("/api/admin/backup").json()["enabled"] is False
    assert c.post("/api/admin/backup/run").status_code == 409
    enabled = c.post("/api/admin/backup/enable").json()
    assert enabled["enabled"] is True and len(enabled["recovery_code"]) > 40
    assert c.post("/api/admin/backup/enable", headers={"Authorization": "Bearer st"}).status_code == 403
    assert c.post("/api/admin/backup/disable").json()["enabled"] is False
