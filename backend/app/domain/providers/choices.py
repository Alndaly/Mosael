"""「我能选哪些模型、每种能力我默认用哪个」:设置页与智能体工具 `list_models` 读的是同一份。

此前这两段组装长在路由里,智能体工具只能借道调路由函数本体(`mcp_server._route`)。收进领域后两边
都直接调这里;出参形状由入口自己的 schema 决定(HTTP 的 response_model / 工具的 `out=`)。
"""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import User
from app.domain.plugins.groups import readable_group
from app.domain.providers import models as provider_models
from app.domain.providers import thinking
from app.domain.providers.defaults import DEFAULTABLE_CAPABILITIES, get_row

Surface = Literal["all", "agent", "direct", "gateway", "automation"]


class UnknownCapability(LocalizedError):
    """没有这种能力(只认 `DEFAULTABLE_CAPABILITIES`)。"""

    def __init__(self) -> None:
        super().__init__("routeErr_unknownCapability")


def defaults_of(db: Session, user: User) -> list[dict[str, Any]]:
    """**我**在每种能力下的默认连接 + 模型,每种能力一行。我没设过的就是空 —— 没有部署兜底那一档。"""
    out: list[dict[str, Any]] = []
    for capability in DEFAULTABLE_CAPABILITIES:
        row = get_row(db, capability, user.id)
        # 默认只存一处(指向模型行),连接与模型名从那一行推导出来。
        model = provider_models.model_row(db, row.provider_model_id if row else None)
        out.append(
            {
                "capability": capability,
                "provider_profile_id": model.provider_profile_id if model else None,
                "model": model.model_id if model else "",
                # 恒真:能拿到行就说明是我自己设的(get_row 只查我这一条)。它表达的是「这一格我设过没有」。
                "is_mine": row is not None,
            }
        )
    return out


def capability_models(db: Session, user: User, capability: str, surface: Surface = "all") -> list[dict[str, Any]]:
    """某能力下所有可用模型,跨连接。**任何登录用户都读得到** —— 挡住它等于让人闭着眼睛选自己的默认模型
    (见 tests/test_who_owns_each_setting.py)。"""
    if capability not in DEFAULTABLE_CAPABILITIES:
        raise UnknownCapability()
    return [
        {
            "provider_profile_id": model.provider_profile_id,
            "provider_name": model.profile.name if model.profile is not None else "",
            "model": model.model_id,
            "display_name": model.display_name or "",
            "group": readable_group(model.declared_group),
            # 思考能力跟着模型走:有的完全不思考,有的只能开 / 关,有的才分档。
            "reasoning": model.reasoning,
            "reasoning_effort": model.reasoning_effort,
            # 「会不会思考」和「我们能不能把档位传过去」是两回事:Kimi k3 会思考、也分档,但关不掉、没有「中」。
            "thinking_levels": thinking.profile_for(
                model.profile.vendor if model.profile is not None else "", model.model_id
            ).levels(),
        }
        for model in provider_models.models_for_capability(db, capability, user.id, surface=surface)
    ]
