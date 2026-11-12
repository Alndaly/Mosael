"""结果文件存储。生产可以替换成 R2/S3;本地实现保证原子落盘和稳定 key。"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from cloud.generation.adapters import AdapterArtifact


@dataclass(frozen=True)
class StoredArtifact:
    storage_key: str
    size: int
    sha256: str


class LocalArtifactStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, *, user_id: str, job_id: str, artifact: AdapterArtifact) -> StoredArtifact:
        digest = hashlib.sha256(artifact.data).hexdigest()
        relative = Path(user_id) / job_id / f"{digest[:16]}-{artifact.filename}"
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".part")
        temporary.write_bytes(artifact.data)
        os.replace(temporary, target)
        return StoredArtifact(storage_key=str(relative), size=len(artifact.data), sha256=digest)

    def path(self, storage_key: str) -> Path:
        candidate = (self.root / storage_key).resolve()
        root = self.root.resolve()
        if root not in candidate.parents and candidate != root:
            raise ValueError("artifact path escapes storage root")
        return candidate
