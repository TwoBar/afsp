"""Local materialisation — fetches remote-backed paths to local cache."""

import hashlib
import os
import shutil
import time

CACHE_PATH = os.environ.get("AFSP_CACHE_PATH", "/var/afsp/cache")
CACHE_TTL = int(os.environ.get("AFSP_CACHE_TTL", "300"))


def materialise_path(path: str, backing_store: dict, cache_path: str | None = None) -> str:
    """Materialise a path from a backing store to local storage.

    For local backing store, returns the direct path.
    For remote stores, fetches to cache and returns cache path.
    """
    cache_root = cache_path or CACHE_PATH

    if backing_store["type"] == "local":
        return os.path.join(backing_store["root"], path.rstrip("/*"))

    if backing_store["type"] == "s3":
        raise NotImplementedError("S3 backing store is not implemented in MVP")

    raise ValueError(f"Unknown backing store type: {backing_store['type']}")


def _cache_key(path: str) -> str:
    return hashlib.sha256(path.encode()).hexdigest()


def get_cached_path(path: str, cache_path: str | None = None) -> str | None:
    """Check if a path is cached and still valid. Returns cached path or None."""
    cache_root = cache_path or CACHE_PATH
    key = _cache_key(path)
    cached = os.path.join(cache_root, key)

    if not os.path.exists(cached):
        return None

    # Check TTL
    mtime = os.path.getmtime(cached)
    if time.time() - mtime > CACHE_TTL:
        # Stale — remove
        if os.path.isdir(cached):
            shutil.rmtree(cached)
        else:
            os.remove(cached)
        return None

    return cached


def cache_path_for(path: str, source_path: str, cache_path: str | None = None) -> str:
    """Cache a local file/directory for a given path."""
    cache_root = cache_path or CACHE_PATH
    os.makedirs(cache_root, exist_ok=True)
    key = _cache_key(path)
    cached = os.path.join(cache_root, key)

    if os.path.isdir(source_path):
        if os.path.exists(cached):
            shutil.rmtree(cached)
        shutil.copytree(source_path, cached)
    else:
        shutil.copy2(source_path, cached)

    return cached


def warm_view(view_entries: list[dict], backing_store: dict, cache_path: str | None = None):
    """Materialise all paths in a view before container start.

    This eliminates cold-start latency on first file access.
    """
    materialised = []
    for entry in view_entries:
        path = entry["path"]
        local_path = materialise_path(path, backing_store, cache_path)
        if os.path.exists(local_path):
            materialised.append({"path": path, "local_path": local_path})
    return materialised
