"""Online backup to the hub (contract: "Backup", kit 0.4). Encrypted on the instance: the hub stores blobs it cannot
read, under ids it cannot link to content.

- The **key** (32 random bytes) lives in the data directory (backup-key.json). The owner gets it once as a
  **recovery code**; without it a backup cannot be restored (the hub never has it).
- Every file is one **blob**: AES-256-GCM with a random nonce, the blob id as associated data. The id is
  HMAC-SHA256(key, content), so unchanged files are not sent again and the hub learns nothing from the id.
- The **manifest** (which path is which blob) is a blob too. The hub only gets the list of blob ids per backup, to
  know what it may delete when it drops an old backup.
- **Restore** works offline from a bundle the owner downloads from the hub (zip: backup.json + blobs/<id>), so a
  new machine needs nothing but the bundle and the recovery code.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .instance import InstanceStore
from .link import Linker

BACKUP_SECONDS = 24 * 3600
FORMAT = 1
CHECK_BATCH = 500

# A product hands over what to back up: (path inside the backup, file on disk). It makes a consistent copy of a
# live database itself (sqlite backup API) before returning it.
Source = Callable[[], list[tuple[str, Path]]]


class BackupError(Exception):
    """A problem with the backup that can be shown to the owner."""


def recovery_code(key: bytes) -> str:
    raw = base64.b32encode(key).decode().rstrip("=")
    return "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def key_from_code(code: str) -> bytes:
    raw = "".join(ch for ch in code.upper() if ch.isalnum())
    try:
        key = base64.b32decode(raw + "=" * (-len(raw) % 8))
    except ValueError as e:
        raise BackupError("this is not a recovery code") from e
    if len(key) != 32:
        raise BackupError("this is not a recovery code")
    return key


def blob_id(key: bytes, data: bytes) -> str:
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def seal(key: bytes, bid: str, data: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, bid.encode())


def unseal(key: bytes, bid: str, payload: bytes) -> bytes:
    try:
        return AESGCM(key).decrypt(payload[:12], payload[12:], bid.encode())
    except Exception as e:  # noqa: BLE001 - wrong key or damaged blob: same message for the owner
        raise BackupError("cannot decrypt: wrong recovery code or a damaged backup") from e


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Backupper:
    def __init__(self, store: InstanceStore, linker: Linker, source: Source, product: str, version: str):
        self.store, self.linker, self.source = store, linker, source
        self.product, self.version = product, version
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # -- state in the data directory -------------------------------------------------------------------------------
    def _key(self) -> bytes | None:
        data = self.store._read("backup-key.json")
        return base64.b64decode(data["key"]) if data else None

    def state(self) -> dict:
        data = self.store._read("backup.json") or {}
        return {"enabled": bool(data.get("enabled")), "last": data.get("last"), "has_key": self._key() is not None}

    def _save(self, **changes) -> None:
        data = {**(self.store._read("backup.json") or {}), **changes}
        self.store._write("backup.json", data)

    def enable(self) -> str:
        """Turn backups on; returns the recovery code (a key is made the first time and then kept)."""
        key = self._key()
        if key is None:
            key = os.urandom(32)
            self.store._write("backup-key.json", {"key": base64.b64encode(key).decode(), "created": _now()})
        self._save(enabled=True)
        return recovery_code(key)

    def disable(self) -> None:
        self._save(enabled=False)

    # -- talking to the hub ----------------------------------------------------------------------------------------
    def _call(self, method: str, path: str, *, json_body=None, content: bytes | None = None):
        link = self.store.link()
        if not link:
            raise BackupError("not linked to a hub")
        headers = {"Authorization": f"Bearer {link['instance_key']}"}
        if content is not None:
            headers["Content-Type"] = "application/octet-stream"
        url = f"{link['hub_url']}/api/products/backups{path}"
        try:
            with self.linker._client() as c:
                r = c.request(method, url, json=json_body, content=content, headers=headers, timeout=120.0)
        except Exception as e:  # noqa: BLE001
            self.linker.log.record("to-hub", method, url, None, None, {"error": str(e)}, headers)
            raise BackupError(f"cannot reach the hub: {e}") from e
        shown = json_body if content is None else {"bytes": len(content)}   # never the content in the log
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
        self.linker.log.record("to-hub", method, url, shown, r.status_code, body, headers)
        if r.status_code == 403:
            raise BackupError("the hub owner has not switched online backup on for this installation")
        if r.status_code == 413:
            raise BackupError("the backup quota on the hub is full")
        if r.status_code >= 400:
            raise BackupError(f"the hub answered {r.status_code}")
        return body

    # -- making a backup -------------------------------------------------------------------------------------------
    def run(self) -> dict:
        """One backup now. Only new blobs are sent."""
        with self._lock:
            key = self._key()
            if not self.state()["enabled"] or key is None:
                raise BackupError("online backup is off on this installation")
            started = time.monotonic()
            try:
                files, blobs = [], {}
                for path, source in self.source():
                    data = Path(source).read_bytes()
                    bid = blob_id(key, data)
                    files.append({"path": path, "size": len(data), "blob": bid})
                    blobs[bid] = source
                manifest = json.dumps({"format": FORMAT, "product": self.product, "version": self.version,
                                       "created": _now(), "files": files}).encode()
                manifest_id = blob_id(key, manifest)
                ids = list(blobs)
                missing: list[str] = []
                for i in range(0, len(ids), CHECK_BATCH):
                    missing += self._call("POST", "/check", json_body={"blobs": ids[i:i + CHECK_BATCH]})["missing"]
                sent = 0
                for bid in missing:
                    payload = seal(key, bid, Path(blobs[bid]).read_bytes())
                    self._call("PUT", f"/blobs/{bid}", content=payload)
                    sent += len(payload)
                self._call("PUT", f"/blobs/{manifest_id}", content=seal(key, manifest_id, manifest))
                result = self._call("POST", "", json_body={
                    "manifest": manifest_id, "blobs": ids, "files": len(files),
                    "size": sum(f["size"] for f in files)})
                last = {"at": _now(), "ok": True, "files": len(files), "new_blobs": len(missing), "sent_bytes": sent,
                        "seconds": round(time.monotonic() - started, 1), "backup_id": (result or {}).get("id")}
            except BackupError as e:
                last = {"at": _now(), "ok": False, "error": str(e)}
                self._save(last=last)
                raise
            self._save(last=last)
            return last

    def run_in_background(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False
        self._thread = threading.Thread(target=self._run_quietly, name="hub-backup", daemon=True)
        self._thread.start()
        return True

    def _run_quietly(self) -> None:
        try:
            self.run()
        except BackupError:
            pass   # in backup.json (last) and the traffic log

    def start_schedule(self, interval: float = BACKUP_SECONDS, check: float = 3600) -> None:
        """Once a day while enabled and linked; checks every hour whether a backup is due."""
        def loop():
            while True:
                last = (self.state().get("last") or {})
                due = not last.get("ok") or (datetime.now(timezone.utc)
                                             - datetime.fromisoformat(last["at"])).total_seconds() >= interval
                if self.state()["enabled"] and self.store.link() and due:
                    self._run_quietly()
                time.sleep(check)
        threading.Thread(target=loop, name="hub-backup-schedule", daemon=True).start()


def restore_bundle(bundle: Path | bytes, code: str, target: Path) -> dict:
    """Decrypt a downloaded bundle into `target` (an empty directory). Checks every file against its blob id."""
    key = key_from_code(code)
    target = Path(target)
    if target.exists() and any(target.iterdir()):
        raise BackupError(f"{target} is not empty")
    with zipfile.ZipFile(io.BytesIO(bundle) if isinstance(bundle, bytes) else bundle) as z:
        info = json.loads(z.read("backup.json"))
        manifest = json.loads(unseal(key, info["manifest"], z.read(f"blobs/{info['manifest']}")))
        for f in manifest["files"]:
            data = unseal(key, f["blob"], z.read(f"blobs/{f['blob']}"))
            if blob_id(key, data) != f["blob"]:
                raise BackupError(f"{f['path']} does not match its checksum")
            out = (target / f["path"]).resolve()
            if target.resolve() not in out.parents:
                raise BackupError(f"unsafe path in backup: {f['path']}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
    return {"files": len(manifest["files"]), "created": manifest["created"], "product": manifest["product"],
            "version": manifest["version"]}

