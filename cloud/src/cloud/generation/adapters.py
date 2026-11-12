"""JobAdapter 契约。厂商差异只在这里和 capability/config 里,核心不判断厂商名。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class AdapterArtifact:
    filename: str
    mime: str
    data: bytes


@dataclass(frozen=True)
class AdapterResult:
    """提交 / 轮询 / 取消的统一结果。"""

    status: str  # pending / running / succeeded / failed / cancelled
    provider_job_id: str | None = None
    artifacts: list[AdapterArtifact] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class JobContext:
    job_id: str
    model_id: str
    input: dict[str, object]
    capability: dict[str, object]
    base_url: str
    upstream_model: str
    api_key: str


class JobAdapter(Protocol):
    name: str

    def submit(self, job: JobContext) -> AdapterResult: ...

    def poll(self, job: JobContext, provider_job_id: str) -> AdapterResult: ...

    def cancel(self, job: JobContext, provider_job_id: str) -> None: ...


_ADAPTERS: dict[str, JobAdapter] = {}


def register(adapter: JobAdapter) -> None:
    _ADAPTERS[adapter.name] = adapter


def get(name: str) -> JobAdapter | None:
    return _ADAPTERS.get(name)


def names() -> list[str]:
    return sorted(_ADAPTERS)


def all() -> dict[str, JobAdapter]:
    return dict(_ADAPTERS)
