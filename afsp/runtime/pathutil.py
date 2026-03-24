"""Path safety utilities for AFSP."""

import os


def safe_join(root: str, untrusted_path: str) -> str:
    """Join root with an untrusted path, raising ValueError on traversal.

    Canonicalizes both root and the joined result, then verifies the result
    stays within root. Rejects null bytes unconditionally.
    """
    if "\x00" in untrusted_path:
        raise ValueError(f"Path contains null bytes: {untrusted_path!r}")

    cleaned = untrusted_path.rstrip("/*")
    joined = os.path.join(root, cleaned)
    real = os.path.realpath(joined)
    real_root = os.path.realpath(root)

    if not (real == real_root or real.startswith(real_root + os.sep)):
        raise ValueError(f"Path traversal detected: {untrusted_path}")

    return real
