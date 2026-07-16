import time
from typing import Dict, Any


class WorkspacePayloadCache:
    """In-memory cache to store decompressed workspace tar files or dataset bytes, optimized for scrubbing."""

    def __init__(self, ttl: int = 120):
        self.ttl = ttl
        self._cache: Dict[str, Dict[str, Any]] = {}

    def get(self, key: str) -> Any:
        entry = self._cache.get(key)
        if entry:
            if time.time() - entry["timestamp"] < self.ttl:
                return entry["payload"]
            else:
                del self._cache[key]
        return None

    def set(self, key: str, payload: Any) -> None:
        self._cache[key] = {"timestamp": time.time(), "payload": payload}


workspace_cache = WorkspacePayloadCache()
