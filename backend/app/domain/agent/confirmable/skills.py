"""智能体改技能的确认卡(ADR 0043):新建、改、复制成我的、开关、删、从链接导入。

**每一张都要人点头**(`always_asks`):技能会影响以后的每一次对话,一次放行不该让它以后随便改自己的做法 ——
「本会话始终允许」、放行准则、判断者、bypass 都放不过这几张(判定见 autopilot.decide)。

卡上要摆的事实(全文、改之前 → 改之后、指纹)和批了之后怎么落地都在技能域(skills/managing,经 use_cases 过权限闸);
这里只是把它们接到卡的生命周期上,外加一句摘要。

**在用某个技能时提出的**(这一轮 use_skill 读过、或用户用「/」点了),卡上写明是哪几个:那份名单由工具在开卡时
放进 payload 的 `_skills_in_use`(见 mcp_server 的技能那一组;这一轮在用什么只有工具那头知道),这里把它变成摘要里
单独成行的那句提示(`warning`)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import fragment
from app.db.models import User
from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError
from app.domain.agent.skills.catalog import SkillDomainError
from app.domain.permissions import PermissionDenied


def _user(db: Session, actor: str | None) -> User:
    user = db.get(User, actor) if actor else None
    if user is None:
        raise ConfirmationError("confirmErr_noActor")
    return user


def _validator(action: str):
    def validate(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
        from app.domain.agent.skills import use_cases

        try:
            facts = use_cases.review(db, _user(db, actor), workspace_id, action, payload)
        except SkillDomainError as exc:
            raise ConfirmationError.relay(exc) from exc
        payload.update(facts)
        payload["_skills_in_use"] = _in_use(db, workspace_id, payload.get("_skills_in_use"))

    return validate


def _executor(action: str):
    def execute(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
        from app.domain.agent.skills import use_cases

        try:
            return use_cases.apply(db, _user(db, actor), confirmation.workspace_id, action, dict(confirmation.payload or {}),
                                   session_id=confirmation.session_id)
        except (SkillDomainError, PermissionDenied) as exc:
            raise ConfirmationError.relay(exc) from exc

    return execute


def _in_use(db: Session, workspace_id: str, raw: Any) -> list[dict[str, str]]:
    """「在用的技能」名单 → 卡上要说的名字(显示名;找不到了就用原名)。"""
    from app.domain.agent.skills import catalog

    refs = [str(one) for one in raw if isinstance(one, str) and one.strip()] if isinstance(raw, list) else []
    out = []
    for ref in list(dict.fromkeys(refs))[:5]:
        skill = catalog.find(db, workspace_id, ref)
        out.append({"ref": ref, "title": skill.title if skill is not None else ref})
    return out


def _warning(payload: dict[str, Any]) -> Any:
    named = [one.get("title") or one.get("ref") for one in payload.get("_skills_in_use") or [] if isinstance(one, dict)]
    if not named:
        return ""
    return fragment("confirm_skillInUse", skills="、".join(f"『{name}』" for name in named))


def _title(payload: dict[str, Any]) -> str:
    return str(payload.get("_title") or payload.get("name") or "")


def _summarize_create(db: Session, payload: dict[str, Any]) -> Summary:
    return "confirm_createSkill", {"title": _title(payload), "name": str(payload.get("name") or ""), "warning": _warning(payload)}


def _summarize_update(db: Session, payload: dict[str, Any]) -> Summary:
    changes = payload.get("_changes") or []
    return "confirm_updateSkill", {
        "title": _title(payload), "count": len(changes), "paths": "、".join(str(one.get("path")) for one in changes[:4]),
        "warning": _warning(payload),
    }


def _summarize_copy(db: Session, payload: dict[str, Any]) -> Summary:
    return "confirm_copySkill", {
        "source": str(payload.get("_source_title") or payload.get("name") or ""),
        "name": str(payload.get("new_name") or ""),
        "warning": _warning(payload),
    }


def _summarize_enable(db: Session, payload: dict[str, Any]) -> Summary:
    if payload.get("enabled"):
        return "confirm_enableSkill", {"title": _title(payload), "warning": _warning(payload)}
    return "confirm_disableSkill", {"title": _title(payload), "warning": _warning(payload)}


def _summarize_delete(db: Session, payload: dict[str, Any]) -> Summary:
    size = int(payload.get("_bytes") or 0)
    return "confirm_deleteSkill", {
        "title": _title(payload), "files": int(payload.get("_files") or 0),
        "size": f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB",
        "warning": _warning(payload),
    }


def _summarize_import(db: Session, payload: dict[str, Any]) -> Summary:
    skills = payload.get("_skills") or []
    return "confirm_importSkill", {
        "source": str(payload.get("_source_name") or payload.get("url") or ""),
        "count": len(skills),
        "names": "、".join(str(one.get("title") or one.get("name")) for one in skills[:5]),
        "warning": _warning(payload),
    }


def _card(name: str, action: str, summarize, *, permission: str = "edit", choices: tuple[str, ...] = ()) -> None:
    confirmable_tool(ConfirmableTool(
        name=name,
        permission=permission,
        cost="none",
        summarize=summarize,
        execute=_executor(action),
        validate=_validator(action),
        always_asks=True,
        choices=choices,
    ))


#: 新建和复制:卡上「建好就启用」默认勾着(拍板 5,人在卡上已经看过全文);导入默认不勾(和设置页导入一样:
#: 那是别人写的做法,开它是另一个信任决定)。缺省值是工具开卡时放进 payload 的 `enable`。
_card("create_skill", "create", _summarize_create, choices=("enable",))
_card("update_skill", "update", _summarize_update)
_card("copy_skill", "copy", _summarize_copy, choices=("enable",))
_card("set_skill_enabled", "enable", _summarize_enable)
#: 删了就没了 —— 文件夹一起删,没有回收站(撤不回的那一档)。
_card("delete_skill", "delete", _summarize_delete, permission="destroy")
_card("import_skill", "import", _summarize_import, choices=("enable",))
