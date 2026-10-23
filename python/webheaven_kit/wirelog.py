"""Traffic log of the link: every call between instance and hub, with all data that went over the wire, so the
owner can see exactly what happens. Secrets (device secret, instance key, service token, Authorization) are
shown as a prefix plus the start of their sha256, never in full: a log must not hold working credentials."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

SECRET_KEYS = {"device_secret", "instance_key", "service_token", "authorization", "x-admin-password", "password"}
KEEP = 200


def mask(value: str) -> str:
    value = str(value)
    prefix = value.split(" ", 1)[0] + " " if value.lower().startswith("bearer ") else ""
    secret = value[len(prefix):]
    visible = secret[:4] if len(secret) >= 16 else ""   # the start of a short value would reveal too much
    return f"{prefix}{visible}… (sha256 {hashlib.sha256(secret.encode()).hexdigest()[:8]})"


def redact(data):
    """Copy of `data` with secret values masked (nested dicts and lists too)."""
    if isinstance(data, dict):
        return {k: (mask(v) if k.lower() in SECRET_KEYS and v else redact(v)) for k, v in data.items()}
    if isinstance(data, list):
        return [redact(v) for v in data]
    return data


class WireLog:
    """Last KEEP entries, in memory and (with a data directory) in link-traffic.jsonl."""

    def __init__(self, data_dir: str | Path | None):
        self.path = Path(data_dir) / "link-traffic.jsonl" if data_dir else None
        self._lock = threading.Lock()
        self._entries: list[dict] = []
        if self.path and self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines()[-KEEP:]:
                try:
                    self._entries.append(json.loads(line))
                except ValueError:
                    pass

    def record(self, direction: str, method: str, url: str, request: dict | None, status: int | None,
               response, headers: dict | None = None) -> None:
        """direction: "to-hub" (this instance calls the hub) or "from-hub" (the hub calls this instance)."""
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "direction": direction,
                 "method": method, "url": url, "request_headers": redact(headers or {}),
                 "request": redact(request), "status": status, "response": redact(response)}
        with self._lock:
            self._entries = (self._entries + [entry])[-KEEP:]
            if self.path:
                self.path.write_text("".join(json.dumps(e) + "\n" for e in self._entries), encoding="utf-8")

    def entries(self) -> list[dict]:
        with self._lock:
            return list(reversed(self._entries))   # newest first
