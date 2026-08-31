from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CacheEntry:
    data: Any
    created_at: datetime
    expires_at: datetime


class JsonFileCache:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / digest[:2] / f"{digest}.json"

    def get(self, key: str) -> Any | None:
        entry = self.get_entry(key)
        return entry.data if entry else None

    def get_entry(self, key: str) -> CacheEntry | None:
        path = self._path(key)
        if not path.exists(): return None
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            created_at = datetime.fromisoformat(envelope["created_at"])
            expires_at = datetime.fromisoformat(envelope["expires_at"])
            if expires_at <= datetime.now(UTC):
                return None
            return CacheEntry(data=envelope["data"], created_at=created_at, expires_at=expires_at)
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def set(self, key: str, data: Any, ttl_seconds: int, *, created_at: datetime | None = None) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        created_at = created_at or datetime.now(UTC)
        envelope = {"created_at": created_at.isoformat(), "expires_at": (created_at + timedelta(seconds=ttl_seconds)).isoformat(), "data": data}
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(envelope, separators=(",", ":"), default=str), encoding="utf-8")
        temporary.replace(path)
