"""连接下的自定义参数组:增删改查。

**为什么不放在生成那组路由里**:它归连接(见 db.models.GenerationCapabilityProfile),和这条
连接下的模型、默认值走同一道归属门(`require_own_profile`)。放到 /generation 下的话,归属判定
就得再发明一遍。规则(名字不重、种类不改、有模型指着不给删)在 domain/generation/custom_profiles。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from app.core.i18n import tr
from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    GenerationCapabilityProfileCreate,
    GenerationCapabilityProfileOut,
    GenerationCapabilityProfileUpdate,
)
from app.db.models import GenerationCapabilityProfile
from app.domain.generation.custom_profiles import (
    CapabilityProfileConflict,
    CapabilityProfileError,
    create_custom_profile,
    custom_profile_in,
    custom_profiles_for,
    delete_custom_profile,
    update_custom_profile,
)
from app.domain.permissions import require_own_profile

router = APIRouter(tags=["settings"])


def _out(row: GenerationCapabilityProfile) -> GenerationCapabilityProfileOut:
    return GenerationCapabilityProfileOut(
        id=row.id,
        name=row.name,
        kind=row.kind,
        capabilities=dict(row.capabilities or {}),
        #: 选择器和模型行存的都是这个,直接给出去省得前端自己拼(拼错了是一个解析不到的 ref)。
        ref=f"profile:{row.id}",
    )


def _row(db, profile_id: str, ref_id: str) -> GenerationCapabilityProfile:
    row = custom_profile_in(db, profile_id, ref_id)
    if row is None:
        raise HTTPException(status_code=404, detail=tr("genErr_paramGroupNotFound"))
    return row


def _refused(exc: CapabilityProfileError) -> HTTPException:
    return HTTPException(status_code=409 if isinstance(exc, CapabilityProfileConflict) else 422, detail=str(exc))


@router.get(
    "/settings/providers/{profile_id}/generation-profiles",
    response_model=list[GenerationCapabilityProfileOut],
)
def list_profiles(profile_id: str, db: DbSession, user: CurrentUser, kind: str = "image"):
    require_own_profile(db, user, profile_id)
    return [_out(row) for row in custom_profiles_for(db, profile_id, kind)]


@router.post(
    "/settings/providers/{profile_id}/generation-profiles",
    response_model=GenerationCapabilityProfileOut,
)
def create_profile(profile_id: str, body: GenerationCapabilityProfileCreate, db: DbSession, user: CurrentUser):
    require_own_profile(db, user, profile_id, editing=True)
    try:
        row = create_custom_profile(db, profile_id, name=body.name, kind=body.kind, capabilities=body.capabilities)
    except CapabilityProfileError as exc:
        raise _refused(exc) from exc
    db.commit()
    db.refresh(row)
    return _out(row)


@router.patch(
    "/settings/providers/{profile_id}/generation-profiles/{ref_id}",
    response_model=GenerationCapabilityProfileOut,
)
def update_profile(
    profile_id: str, ref_id: str, body: GenerationCapabilityProfileUpdate, db: DbSession, user: CurrentUser
):
    require_own_profile(db, user, profile_id, editing=True)
    row = _row(db, profile_id, ref_id)
    try:
        update_custom_profile(db, row, name=body.name, capabilities=body.capabilities)
    except CapabilityProfileError as exc:
        raise _refused(exc) from exc
    db.commit()
    db.refresh(row)
    return _out(row)


@router.delete("/settings/providers/{profile_id}/generation-profiles/{ref_id}", status_code=204)
def delete_profile(profile_id: str, ref_id: str, db: DbSession, user: CurrentUser) -> Response:
    """删掉一份参数组。

    **还有模型指着它时不给删**(409,说出还有几个):删了的话那些行的 ref 解析不到,静默落回
    兜底 —— 用户以为还在生效的配置其实没了。先让他把模型改回"跟随目录",再删,数据里就永远
    回答得出"当时配的是什么"。数据库层也由 template_id 的 FK(RESTRICT)兜住同一个不变量。
    """
    require_own_profile(db, user, profile_id, editing=True)
    try:
        delete_custom_profile(db, _row(db, profile_id, ref_id))
    except CapabilityProfileError as exc:
        raise _refused(exc) from exc
    db.commit()
    return Response(status_code=204)
