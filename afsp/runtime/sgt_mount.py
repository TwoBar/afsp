"""SGT dynamic mounting — mount/unmount paths into running containers."""

import os
import subprocess
import threading
import time
from datetime import datetime, timezone

from afsp.runtime.projection import resolve_backing_store


def get_container_pid(container_id: str) -> int:
    """Get the PID of a Docker container's init process."""
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Pid}}", container_id],
        capture_output=True, text=True, check=True,
    )
    return int(result.stdout.strip())


def mount_sgt(container_id: str, token: dict, volumes_path: str | None = None):
    """Mount an SGT-granted path into a running container without restart.

    Uses nsenter to enter the container's mount namespace and bind-mount the path.
    """
    host_path = resolve_backing_store(token["path"], volumes_path)
    container_path = f"/workspace/{token['path'].rstrip('/*')}"
    pid = get_container_pid(container_id)

    # Create mount point inside container
    subprocess.run([
        "nsenter",
        f"--mount=/proc/{pid}/ns/mnt",
        "--",
        "mkdir", "-p", container_path,
    ], check=True)

    # Bind mount
    subprocess.run([
        "nsenter",
        f"--mount=/proc/{pid}/ns/mnt",
        "--",
        "mount", "--bind",
        host_path,
        container_path,
    ], check=True)

    # Schedule unmount at expiry
    expires_at = token["expires_at"]
    if isinstance(expires_at, str):
        expires_dt = datetime.fromisoformat(expires_at)
    else:
        expires_dt = expires_at

    schedule_unmount(container_id, container_path, expires_dt)


def unmount_sgt(container_id: str, container_path: str):
    """Unmount an SGT-granted path from a running container."""
    try:
        pid = get_container_pid(container_id)
        subprocess.run([
            "nsenter",
            f"--mount=/proc/{pid}/ns/mnt",
            "--",
            "umount", container_path,
        ], check=True)
    except (subprocess.CalledProcessError, ValueError):
        # Container may have already stopped
        pass


def schedule_unmount(container_id: str, container_path: str, expires_at: datetime):
    """Schedule an unmount at the token's expiry time."""
    now = datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    delay = (expires_at - now).total_seconds()

    if delay <= 0:
        unmount_sgt(container_id, container_path)
        return

    timer = threading.Timer(delay, unmount_sgt, args=[container_id, container_path])
    timer.daemon = True
    timer.start()
    return timer


def mark_token_used(token_id: str, db):
    """Mark a single-use token as used and trigger unmount."""
    db.execute("UPDATE tokens SET used = 1 WHERE token_id = ?", (token_id,))
    db.commit()
