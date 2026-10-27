"""The instance: a random id and the link state, kept in a small data directory (no content)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .contract import LEVELS

MODES = ("standalone", "linked")


@dataclass
class Instance:
    id: str
    created: str
    mode: str = "standalone"
    visibility: str = "health"
    catalog: bool = True   # share the catalog with the hub (only for products that offer one, see Linker)


def _write_json(path: Path, data: dict) -> None:
    # Write to a temp file first: a crash never leaves half a file behind
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class InstanceStore:
    """Reads and writes instance.json and link.json. Without a data directory everything stays in memory
    (the id then changes on every start, which is fine for a local tool)."""

    def __init__(self, data_dir: str | Path | None):
        self.dir = Path(data_dir) if data_dir else None
        self.instance = self._load_instance()

    def _path(self, name: str) -> Path | None:
        return self.dir / name if self.dir else None

    def _load_instance(self) -> Instance:
        path = self._path("instance.json")
        if path and path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return Instance(**{k: data[k] for k in ("id", "created", "mode", "visibility", "catalog") if k in data})
        inst = Instance(id=uuid.uuid4().hex, created=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        if path:
            self.dir.mkdir(parents=True, exist_ok=True)
            _write_json(path, asdict(inst))
        return inst

    def save(self) -> None:
        if path := self._path("instance.json"):
            _write_json(path, asdict(self.instance))

    def set_visibility(self, level: str) -> None:
        if level not in LEVELS:
            raise ValueError(f"unknown visibility level: {level}")
        self.instance.visibility = level
        self.save()

    def set_catalog(self, enabled: bool) -> None:
        self.instance.catalog = bool(enabled)
        self.save()

    # Small JSON files next to instance.json; in memory without a data directory.
    def _read(self, name: str) -> dict | None:
        if not self.dir:
            return self._memory.get(name)
        path = self.dir / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def _write(self, name: str, data: dict | None) -> None:
        if not self.dir:
            self._memory[name] = data
            return
        path = self.dir / name
        if data is None:
            path.unlink(missing_ok=True)
        else:
            _write_json(path, data)

    @property
    def _memory(self) -> dict:
        if not hasattr(self, "_mem"):
            self._mem = {}
        return self._mem

    def link(self) -> dict | None:
        return self._read("link.json") if self.instance.mode == "linked" else None

    def set_link(self, link: dict, visibility: str) -> None:
        """Store the credentials from the hub and switch to linked."""
        self._write("link.json", link)
        self.instance.mode = "linked"
        self.set_visibility(visibility)   # also saves instance.json

    def clear_link(self) -> None:
        """Back to standalone: forget the hub."""
        self._write("link.json", None)
        self.instance.mode = "standalone"
        self.save()

    def pending(self) -> dict | None:
        return self._read("link-pending.json")

    def set_pending(self, pending: dict | None) -> None:
        self._write("link-pending.json", pending)

    def verify_service_token(self, token: str) -> bool:
        """True when the token is the hub's service token. A standalone instance accepts no token at all."""
        link = self.link()
        expected = (link or {}).get("service_token_sha256")
        if not token or not expected:
            return False
        return hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), expected)
