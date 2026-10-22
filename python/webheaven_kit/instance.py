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
            return Instance(**{k: data[k] for k in ("id", "created", "mode", "visibility") if k in data})
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

    def link(self) -> dict | None:
        path = self._path("link.json")
        if self.instance.mode != "linked" or not path or not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def verify_service_token(self, token: str) -> bool:
        """True when the token is the hub's service token. A standalone instance accepts no token at all."""
        link = self.link()
        expected = (link or {}).get("service_token_sha256")
        if not token or not expected:
            return False
        return hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), expected)
