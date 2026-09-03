from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response

from app.ai.model_catalog import fetch_models
from app.api.deps import CurrentUser, DbSession
from app.api.schemas import ProviderModelOut, ProviderModelUpdate
from app.domain import provider_models
from app.domain.provider_credentials import ResolvedConnection
from app.domain.providers import capability_ids_for_vendor, normalize_capability_ids

from .provider_profiles import _require_profile, _resolved_or_bare

router = APIRouter(tags=["settings"])
logger = logging.getLogger(__name__)

def _catalog_entries(profile: ResolvedConnection) -> dict[str, dict]:
    """该连接的**目录**(供应商说它有什么)。订阅计划的目录只有登录才知道(Copilot 随档位变、
    OpenRouter 有几百个),登录时由 pi 带回存下;API Key 档案现打 /models(带 TTL 缓存)。"""
    if profile.vendor == "comfyui":
        # ComfyUI 是工作流引擎,没有模型目录 —— 它的"目录"就是实例里保存的工作流。
        # 走同一个接缝而不是在前端分叉:这样「加入 / 启停 / 删除 / 设能力」整套交互
        # 对工作流原样成立,只有文案不同。连不上就返回空,和端点没模型是同一种表现。
        from app.ai.providers.adapters.comfyui.client import ComfyUIClient

        try:
            items = ComfyUIClient(profile.base_url or "http://127.0.0.1:8188").list_workflows()
        except Exception as exc:  # noqa: BLE001 — 连不上是常态(忘了启动),不该让设置页 500
            logger.info("ComfyUI 工作流列表获取失败(%s):%s", profile.base_url, exc)
            return {}
        return {str(item["path"]): {"context_window": None, "max_output_tokens": None} for item in items if item.get("path")}
    if profile.auth_type == "oauth":
        return {
            str(item.get("id")): {
                "context_window": item.get("contextWindow"),
                "max_output_tokens": item.get("maxTokens"),
            }
            for item in (profile.model_catalog or [])
            if isinstance(item, dict) and item.get("id")
        }
    return {
        m.id: {"context_window": m.context_window, "max_output_tokens": m.max_output_tokens}
        for m in fetch_models(profile.base_url or "", profile.api_key or "")
    }


def _is_known_model(vendor: str, model_id: str, catalog: dict[str, dict]) -> bool:
    """这个模型是不是"我们认得的"。

    「目录中已不存在」这个提示的本意是**预警**:曾经能用的模型从供应商目录里消失了(下架、
    改名),再点下去就会失败。判据原本只有一条 —— 在不在实时目录里。

    可实时目录读的是 OpenAI 兼容的 `/models`,而有些能力走供应商的原生端点、**从来就不在
    那份清单里**:百炼的万相视频就是这样。于是每一个从内置目录加进来的模型都挂着"已不存在",
    而它明明刚验证过能用(真机截图)。一个永远为真的警告等于没有警告 —— 更糟的是它会让用户
    去删一个好模型。

    所以内置目录也算数:它是**验证过的事实**,不是"端点当下报了什么"。
    """
    if model_id in catalog:
        return True
    from app.domain.generation import builtin_models_for

    return any(model_id in builtin_models_for(vendor, kind) for kind in ("image", "video"))


def _model_out(model, catalog: dict[str, dict], vendor: str = "") -> ProviderModelOut:
    entry = catalog.get(model.model_id) or {}
    catalog_window = entry.get("context_window")
    if model.context_window:
        window, source = model.context_window, "override"
    elif catalog_window:
        window, source = catalog_window, "catalog"
    else:
        window, source = None, "fallback"
    return ProviderModelOut(
        id=model.model_id,
        display_name=model.display_name or "",
        capability_ids=list(model.capability_ids or []),
        effective_capability_ids=provider_models.effective_capabilities(model),
        enabled=model.enabled,
        configured=True,
        in_catalog=_is_known_model(vendor or (model.profile.vendor if model.profile else ""), model.model_id, catalog),
        source=model.source,
        context_window=window,
        context_window_source=source,
        max_output_tokens=model.max_output_tokens or entry.get("max_output_tokens"),
        reasoning=model.reasoning,
        vision=model.vision,
        reasoning_effort=model.reasoning_effort,
        developer_role=model.developer_role,
    )


@router.get("/settings/providers/{profile_id}/models", response_model=list[ProviderModelOut])
def list_provider_models(profile_id: str, db: DbSession, user: CurrentUser) -> list[ProviderModelOut]:
    """这条连接下的模型:**已配置的行 + 实时目录 + 内置目录**。

    三者合并而不是二选一 —— 实时目录说端点现在有什么(会变),模型行说用户做过什么(不该被
    目录冲掉),内置目录补上**实时目录看不见的那些**。

    第三份不是可有可无的:实时目录读的是 OpenAI 兼容的 `/models`,而有些能力走供应商的原生
    端点、根本不在那份清单里 —— 百炼的万相视频就是这样(真机实测:那个接口对百炼只返回两个
    wan **图像**模型,一个视频模型都没有)。少了这一份,用户在设置里看不到、加不进来,于是
    生成页的下拉里那一家整个是空的,而他并不知道为什么。

    已配置的排在前面:那是用户实际在用的;其余可一键加入。
    """
    # 只读:任何登录用户都看得到这条连接下有哪些模型 —— 他要据此选自己的默认。
    profile = _require_profile(db, profile_id, user)
    catalog = _catalog_entries(_resolved_or_bare(db, profile, user))
    configured = provider_models.list_models(db, profile_id)
    rows = [_model_out(model, catalog, profile.vendor) for model in configured]
    known = {row.id for row in rows}
    for model_id, entry in catalog.items():
        if model_id in known:
            continue
        rows.append(
            ProviderModelOut(
                id=model_id,
                configured=False,
                in_catalog=True,
                enabled=False,  # 没配置过 = 还没启用,加入后才进选择器
                context_window=entry.get("context_window"),
                context_window_source="catalog" if entry.get("context_window") else "fallback",
                max_output_tokens=entry.get("max_output_tokens"),
                # 和落库后 effective_capabilities 走同一条判据 —— 否则列表里显示的能力
                # 和加进去之后的能力对不上,而用户是照着列表做的决定。
                effective_capability_ids=(
                    provider_models.infer_capabilities(profile.vendor, model_id)
                    or capability_ids_for_vendor(profile.vendor)
                ),
            )
        )
        known.add(model_id)

    # 内置目录:走原生端点、不在 /models 里的那些。能力**按 kind 给准**,而不是套用 vendor
    # 的全集 —— 一个万相视频模型不该被声明成"对话 + 图像 + 视频 + 语音"。
    from app.domain.generation import builtin_models_for

    for kind in ("image", "video"):
        for model_id in builtin_models_for(profile.vendor, kind):
            if model_id in known:
                continue
            known.add(model_id)
            rows.append(
                ProviderModelOut(
                    id=model_id,
                    configured=False,
                    # 对界面来说它和目录项是一回事:没配过、可一键加入。区别只在"这份清单
                    # 是静态的",而那是实现细节,不是用户要分辨的东西。
                    in_catalog=True,
                    enabled=False,
                    context_window=None,
                    context_window_source="fallback",
                    max_output_tokens=None,
                    effective_capability_ids=[kind],
                )
            )
    return rows


@router.post("/settings/providers/{profile_id}/models", response_model=ProviderModelOut)
def add_provider_model(
    profile_id: str, body: ProviderModelUpdate, db: DbSession, user: CurrentUser
) -> ProviderModelOut:
    """把一个模型加进这条连接。目录里选的和手填的走同一条路 —— 区别只在 source,
    手填是为了私有部署与别名:目录查不到不等于不能用。"""
    profile = _require_profile(db, profile_id, user)
    model_id = (body.model_id or "").strip()
    if not model_id:
        raise HTTPException(status_code=422, detail="模型 id 不能为空")
    catalog = _catalog_entries(_resolved_or_bare(db, profile, user))
    fields = body.model_dump(exclude_unset=True, exclude={"model_id", "capability_ids"})
    model = provider_models.upsert(
        db,
        profile,
        model_id,
        source="catalog" if model_id in catalog else "manual",
        capability_ids=body.capability_ids if body.capability_ids is not None else None,
        **fields,
    )
    db.commit()
    return _model_out(model, catalog, profile.vendor)


@router.patch("/settings/providers/{profile_id}/models/{model_id:path}", response_model=ProviderModelOut)
def update_provider_model(
    profile_id: str, model_id: str, body: ProviderModelUpdate, db: DbSession, user: CurrentUser
) -> ProviderModelOut:
    """改一行。

    **model_id 必须用 :path 转换器**:模型 id 里带斜杠是常态(kimi/kimi-k2.7-code、
    MiniMax/MiniMax-M2.5、ZHIPU/GLM-5),而普通路径参数不跨 `/`,路由直接匹配不上 ——
    表现是删除/修改一律 404,而且只有那些带斜杠的模型才复现。
    运行时项传 null 即清除、回到跟随目录 —— 与"没传"是两回事,后者不动它。"""
    profile = _require_profile(db, profile_id, user)
    model = provider_models.get_model(db, profile_id, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="该连接下没有这个模型")
    patch = body.model_dump(exclude_unset=True)
    for field in provider_models.RUNTIME_FIELDS:
        if field in patch:
            setattr(model, field, patch[field])
    if "enabled" in patch and body.enabled is not None:
        model.enabled = body.enabled
    if "display_name" in patch:
        model.display_name = body.display_name or ""
    if "capability_ids" in patch:
        model.capability_ids = normalize_capability_ids(body.capability_ids) or []
    db.commit()
    return _model_out(model, _catalog_entries(_resolved_or_bare(db, profile, user)), profile.vendor)


@router.delete("/settings/providers/{profile_id}/models/{model_id:path}", status_code=204)
def delete_provider_model(profile_id: str, model_id: str, db: DbSession, user: CurrentUser) -> Response:
    """移除一行。目录里仍有的模型移除后会回到"未配置"状态(还能再加回来),
    手填的则彻底消失 —— 它本来就只存在于这一行里。"""
    _require_profile(db, profile_id, user)  # 归属判定,和这条连接上其余操作同一道门
    model = provider_models.get_model(db, profile_id, model_id)
    if model is not None:
        db.delete(model)
        db.commit()
    return Response(status_code=204)

