"""Local disk backing store adapter."""

import os

from afsp.runtime.pathutil import safe_join


class LocalStore:
    def __init__(self, root: str):
        self.root = root
        self.type = "local"

    def resolve(self, path: str) -> str:
        return safe_join(self.root, path)

    def exists(self, path: str) -> bool:
        return os.path.exists(self.resolve(path))

    def as_dict(self) -> dict:
        return {"type": "local", "root": self.root}
