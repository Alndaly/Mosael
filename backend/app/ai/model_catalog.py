"""供应商端点上的模型目录:打一次 OpenAI 兼容的 `/models`,拿到 id 与上下文/输出上限。

为什么单独成模块:这份数据有**两个消费方** —— 设置页的模型选择器,和智能体启动一轮前需要
知道的 contextWindow / maxTokens。同一个 HTTP 响应各取一次是「同一效果两条链路」的经典形态,
所以放在这里一处实现、带短 TTL 缓存(一轮对话不该为了拿元数据再打一次网络)。

**端点没给的字段一律留空,不猜。**曾经智能体侧硬编 `contextWindow: 128000`,配 8k 上下文的
本地模型时会以为还有 128k 可用,请求直到服务端才被拒。留空比编一个大数安全:调用方可以选择
一个保守回退,但没法从一个编出来的数里recover。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import httpx

#: 目录变动很慢(供应商上新模型),但也不能永不刷新。
_TTL_SECONDS = 300
_FETCH_TIMEOUT = 8


@dataclass(frozen=True)
class CatalogModel:
    id: str
    context_window: int | None = None
    max_output_tokens: int | None = None


_cache: dict[tuple[str, str], tuple[float, list[CatalogModel]]] = {}
_cache_lock = threading.Lock()


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _parse(rows: object) -> list[CatalogModel]:
    if not isinstance(rows, list):
        return []
    models: dict[str, CatalogModel] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = str(row.get("id") or "").strip()
        if not model_id or model_id in models:
            continue
        models[model_id] = CatalogModel(
            id=model_id,
            # 字段名各家不一:OpenRouter 用 context_length,vLLM/部分网关用 context_window。
            context_window=_positive_int(row.get("context_length") or row.get("context_window")),
            max_output_tokens=_positive_int(row.get("max_output_tokens") or row.get("max_tokens")),
        )
    return [models[key] for key in sorted(models)]


def fetch_models(base_url: str, api_key: str, *, use_cache: bool = True) -> list[CatalogModel]:
    """列出该端点的模型。**取不到时返回空列表** —— 调用方自行决定回退。"""
    base = (base_url or "").rstrip("/")
    if not base:
        return []
    key = (base, api_key or "")
    now = time.monotonic()
    if use_cache:
        with _cache_lock:
            hit = _cache.get(key)
        if hit and now - hit[0] < _TTL_SECONDS:
            return hit[1]
    try:
        resp = httpx.get(
            f"{base}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_FETCH_TIMEOUT,
        )
        resp.raise_for_status()
        models = _parse(resp.json().get("data"))
    except Exception:  # noqa: BLE001 - 端点不可达/不实现 /models 都只是「没有目录」,不是错误
        return []
    with _cache_lock:
        _cache[key] = (now, models)
    return models


def find_model(base_url: str, api_key: str, model_id: str) -> CatalogModel | None:
    """目录里这一个模型的元数据;端点没列出它就是 None(自定义/别名模型很常见)。"""
    target = (model_id or "").strip()
    if not target:
        return None
    return next((m for m in fetch_models(base_url, api_key) if m.id == target), None)


def clear_cache() -> None:
    """测试用;生产不需要 —— TTL 到了自然刷新。"""
    with _cache_lock:
        _cache.clear()
