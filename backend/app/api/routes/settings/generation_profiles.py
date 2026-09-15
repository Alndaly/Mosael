"""连接下的自定义参数组:增删改查。

**为什么不放在生成那组路由里**:它归连接(见 db.models.GenerationCapabilityProfile),和这条
连接下的模型、默认值走同一道归属门(`_require_profile`)。放到 /generation 下的话,归属判定
就得再发明一遍。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    GenerationCapabilityProfileCreate,
    GenerationCapabilityProfileOut,
    GenerationCapabilityProfileUpdate,
)
from app.db.models import GenerationCapabilityProfile
from app.domain.generation.custom_profiles import (
    CapabilityProfileError,
    custom_profiles_for,
    validate_capabilities,
)

from .provider_profiles import _require_profile

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
    row = db.get(GenerationCapabilityProfile, ref_id)
    #: 跨连接取不到 —— 一份参数组只在它所属的那条连接里有意义。
    if row is None or row.provider_profile_id != profile_id:
        raise HTTPException(status_code=404, detail="这条连接下没有这个参数组")
    return row


@router.get(
    "/settings/providers/{profile_id}/generation-profiles",
    response_model=list[GenerationCapabilityProfileOut],
)
def list_profiles(profile_id: str, db: DbSession, user: CurrentUser, kind: str = "image"):
    _require_profile(db, profile_id, user)
    return [_out(row) for row in custom_profiles_for(db, profile_id, kind)]


@router.post(
    "/settings/providers/{profile_id}/generation-profiles",
    response_model=GenerationCapabilityProfileOut,
)
def create_profile(profile_id: str, body: GenerationCapabilityProfileCreate, db: DbSession, user: CurrentUser):
    _require_profile(db, profile_id, user)
    try:
        capabilities = validate_capabilities(body.capabilities, body.kind)
    except CapabilityProfileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="给这份参数组起个名字")
    if any(row.name == name for row in custom_profiles_for(db, profile_id, body.kind)):
        raise HTTPException(status_code=409, detail="这条连接下已经有同名的参数组了")
    row = GenerationCapabilityProfile(
        provider_profile_id=profile_id, name=name, kind=body.kind, capabilities=capabilities
    )
    db.add(row)
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
    _require_profile(db, profile_id, user)
    row = _row(db, profile_id, ref_id)
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="给这份参数组起个名字")
        if any(other.name == name and other.id != row.id for other in custom_profiles_for(db, profile_id, row.kind)):
            raise HTTPException(status_code=409, detail="这条连接下已经有同名的参数组了")
        row.name = name
    if body.capabilities is not None:
        try:
            #: kind 不给改 —— 图片的尺寸清单套到视频上是另一套东西,而已经指着它的那些模型行
            #: 不会跟着改。要换就新建一份。
            row.capabilities = validate_capabilities(body.capabilities, row.kind)
        except CapabilityProfileError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
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
    _require_profile(db, profile_id, user)
    row = _row(db, profile_id, ref_id)
    from app.domain.generation.resolution import template_reference_count

    count = template_reference_count(db, row.id)
    if count:
        raise HTTPException(status_code=409, detail=f"还有 {count} 个模型在使用这份参数模板，请先改回跟随目录")
    db.delete(row)
    db.commit()
    return Response(status_code=204)
