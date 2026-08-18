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
#: 端点不可达时也记一笔,时长短得多。**不记的话每一次都要等满 _FETCH_TIMEOUT** ——
#: 而调用方里有"每轮对话都要问一次"的那种,于是配了个连不通的地址,每句话都先卡八秒。
#: 短是因为端点恢复了不该等五分钟才发现。
_FAILURE_TTL_SECONDS = 60


@dataclass(frozen=True)
class CatalogModel:
    id: str
    context_window: int | None = None
    max_output_tokens: int | None = None
    #: 单价,**美元 / 百万 token**。端点没给就是 None(多数 OpenAI 兼容端点不报价)。
    #: 单位刻意统一成「每百万」:计价规则表里本来就有 million_* 系列,换算一次即可对上。
    input_cost: float | None = None
    output_cost: float | None = None
    cache_read_cost: float | None = None
    cache_write_cost: float | None = None


#: (取到的时刻, 模型, 这次是不是取成功了)。第三项决定用哪个 TTL —— 失败也要记,
#: 否则连不通的端点会被反复重试。
_cache: dict[tuple[str, str], tuple[float, list[CatalogModel], bool]] = {}
_cache_lock = threading.Lock()
#: 正在后台刷新的键。去重用:同一个端点没必要同时有十个线程去问。
_refreshing: set[tuple[str, str]] = set()


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _per_million(value: object) -> float | None:
    """OpenRouter 一类端点在 `pricing` 里给的是**每 token** 的美元价,而且是字符串。

    换算成每百万,和计价规则表的 million_* 单位对齐。负数/非数字/空串一律当没给。
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        amount = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return amount * 1_000_000 if amount >= 0 else None


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
        pricing = row.get("pricing") if isinstance(row.get("pricing"), dict) else {}
        models[model_id] = CatalogModel(
            id=model_id,
            # 字段名各家不一:OpenRouter 用 context_length,vLLM/部分网关用 context_window。
            context_window=_positive_int(row.get("context_length") or row.get("context_window")),
            max_output_tokens=_positive_int(row.get("max_output_tokens") or row.get("max_tokens")),
            input_cost=_per_million(pricing.get("prompt")),
            output_cost=_per_million(pricing.get("completion")),
            cache_read_cost=_per_million(pricing.get("input_cache_read")),
            cache_write_cost=_per_million(pricing.get("input_cache_write")),
        )
    return [models[key] for key in sorted(models)]


def fetch_models(base_url: str, api_key: str, *, use_cache: bool = True) -> list[CatalogModel]:
    """列出该端点的模型。**取不到时返回空列表** —— 调用方自行决定回退。"""
    base = (base_url or "").rstrip("/")
    if not base:
        return []
    key = (base, api_key or "")
    if use_cache:
        fresh = _fresh(key)
        if fresh is not None:
            return fresh
    try:
        resp = httpx.get(
            f"{base}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_FETCH_TIMEOUT,
        )
        resp.raise_for_status()
        models = _parse(resp.json().get("data"))
    except Exception:  # noqa: BLE001 - 端点不可达/不实现 /models 都只是「没有目录」,不是错误
        with _cache_lock:
            _cache[key] = (time.monotonic(), [], False)
        return []
    with _cache_lock:
        _cache[key] = (time.monotonic(), models, True)
    return models


def _fresh(key: tuple[str, str]) -> list[CatalogModel] | None:
    """缓存里还没过期的那份;没有就 None。失败记录的有效期短得多(见 _FAILURE_TTL_SECONDS)。"""
    with _cache_lock:
        hit = _cache.get(key)
    if hit is None:
        return None
    stamped, models, ok = hit
    ttl = _TTL_SECONDS if ok else _FAILURE_TTL_SECONDS
    return models if time.monotonic() - stamped < ttl else None


def cached_models(base_url: str, api_key: str) -> list[CatalogModel] | None:
    """**只看缓存,绝不在调用方线程里发请求**;缺了就在后台去取,并返回 None。

    `None` 和 `[]` 是两回事:`[]` 是「问过了,这个端点没列出模型」,`None` 是「还没问到」。
    调用方据此选保守回退,而不是把"不知道"当成"没有"。

    给的是**对话启动**这类路径用的:那里要的只是上下文窗口这种可选元数据(端点没列出来时
    本来就留空由下游回退),而一次问不通的目录请求要等满 _FETCH_TIMEOUT —— 让每一句话都先
    卡八秒去拿一个可有可无的数,不值当。设置页的模型选择器仍然用 `fetch_models`:
    那里用户正等着结果,阻塞才是对的。
    """
    base = (base_url or "").rstrip("/")
    if not base:
        return []
    key = (base, api_key or "")
    fresh = _fresh(key)
    if fresh is not None:
        return fresh
    _refresh_soon(key)
    return None


def _refresh_soon(key: tuple[str, str]) -> None:
    """在后台把这个端点的目录取回来。同一个键同时只有一个在跑。"""
    with _cache_lock:
        if key in _refreshing:
            return
        _refreshing.add(key)

    def run() -> None:
        try:
            fetch_models(key[0], key[1], use_cache=False)
        except Exception:  # noqa: BLE001 — 后台刷新失败只是"还是没有目录"
            pass
        finally:
            with _cache_lock:
                _refreshing.discard(key)

    threading.Thread(target=run, daemon=True, name="model-catalog-refresh").start()


def cached_model(base_url: str, api_key: str, model_id: str) -> CatalogModel | None:
    """目录里这一个模型的元数据。取不到(还没问到 / 端点没列出它)一律 None ——
    自定义名、私有部署、别名模型都很常见,那不是错误。"""
    target = (model_id or "").strip()
    if not target:
        return None
    models = cached_models(base_url, api_key)
    if not models:
        return None
    return next((m for m in models if m.id == target), None)


def clear_cache() -> None:
    """测试用;生产不需要 —— TTL 到了自然刷新。"""
    with _cache_lock:
        _cache.clear()
        _refreshing.clear()
