"""资产库(ADR 0027)的请求与响应体。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.api.schemas.base import ApiModel


class EntityKindOut(ApiModel):
    kind: str
    label: str


class EntityRoleOut(ApiModel):
    role: str
    label: str


class EntityConsentKindOut(ApiModel):
    kind: str
    label: str
    #: 这一项是什么意思 —— 声明界面上挨着选项写出来。
    help: str


class EntityCatalogOut(ApiModel):
    """资产的词表,按请求方的语言翻好:几种资产、参考图的角度、授权声明的选项、生成时挑图的先后。"""

    kinds: list[EntityKindOut]
    #: 全部角度的名字;每一种资产用得上哪几种、按什么顺序列,见 roles_by_kind。
    roles: list[EntityRoleOut]
    #: 每一种资产的参考图能标成什么(人物有表情,场景的角度是全景 / 反打 / 俯视)。
    roles_by_kind: dict[str, list[str]]
    consent_kinds: list[EntityConsentKindOut]
    #: 生成时挑参考图的先后,按种类(人物:三视图 > 正面 > 全身 > 其余)。
    attach_priority: dict[str, list[str]]
    #: 每种资产有哪些专有字段。
    attributes: dict[str, list[str]]


class EntityReferenceOut(ApiModel):
    asset_id: str
    role: str
    position: int
    asset_kind: str
    asset_name: str


class EntityLostReferenceOut(ApiModel):
    """随素材一起删掉的一张参考图:当时叫什么、是什么角度、什么时候。"""

    name: str
    role: str
    at: str


class EntitySummaryOut(ApiModel):
    id: str
    kind: str
    parent_id: str | None = None
    #: 变体的母体叫什么(「张三 · 冬装」的「张三」)。母体自己是空串。
    parent_name: str = ""
    name: str
    #: 卡片上画的那张:设过封面就是它,没设就是第一张参考图,都没有是空。
    cover_asset_id: str | None = None
    tags: list[str]
    reference_count: int
    variant_count: int
    updated_at: datetime


class EntityOut(ApiModel):
    id: str
    workspace_id: str
    kind: str
    parent_id: str | None = None
    parent_name: str = ""
    name: str
    description: str
    prompt: str
    #: 设成封面的那张(没设是空)。卡片上画的是 `display_cover_asset_id`。
    cover_asset_id: str | None = None
    display_cover_asset_id: str | None = None
    attributes: dict[str, Any]
    tags: list[str]
    lost_references: list[EntityLostReferenceOut]
    references: list[EntityReferenceOut]
    variants: list[EntitySummaryOut]
    #: 能不能用于数字人功能(真人要有本人或已获授权的声明,见 domain/entities/catalog)。
    usable_for_digital_human: bool
    created_at: datetime
    updated_at: datetime


class EntityCreate(ApiModel):
    workspace_id: str
    kind: str = Field(pattern="^(character|location|prop)$")
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    prompt: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    #: 给了就是那个资产的一个变体(种类跟着母体走)。
    parent_id: str | None = None


class EntityVariantCreate(ApiModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    #: 变体**在母体的提示词描述之上**多出来的那一句(服装、年龄……),生成时两句拼在一起。
    prompt: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)


class EntityDrawRequest(ApiModel):
    """资产详情页上的「补全多角度」「生成表情」(ADR 0027 阶段 4)和「让它说话」(ADR 0028):和画板上资产格的那几项能力是同一件事。"""

    ability: Literal["angles", "expressions", "speak"]
    #: 用哪个图片模型(生成选项 id,见 field_options 的 reference_image_models);空着用他设的默认。
    model: str = Field(default="", max_length=512)
    #: 补全多角度:只补还没有的(missing),还是每个角度都重画(all)。
    scope: Literal["missing", "all"] = "missing"
    #: 生成表情:画哪几种,逗号分开;空着画缺省的五种。
    expressions: str = Field(default="", max_length=400)
    #: 让它说话:要说的那段话(ADR 0028)。
    text: str = Field(default="", max_length=4000)


class EntityUpdate(ApiModel):
    """没写的字段不动。`cover_asset_id` 写空串 = 不要封面了(退回第一张参考图)。"""

    name: str | None = Field(default=None, max_length=160)
    description: str | None = None
    prompt: str | None = None
    attributes: dict[str, Any] | None = None
    tags: list[str] | None = None
    cover_asset_id: str | None = None


class EntityReferenceAdd(ApiModel):
    asset_id: str = Field(min_length=1, max_length=64)
    #: 空 = 按种类的缺省(人物 / 道具是正面,场景是设定图)。
    role: str = ""
    #: 顺手设成封面。
    cover: bool = False


class EntityReferenceUpdate(ApiModel):
    role: str = Field(min_length=1, max_length=24)


class EntityReferenceOrder(ApiModel):
    asset_ids: list[str]


class AssetEntityOut(ApiModel):
    """一份素材是哪个资产的参考图(素材详情里的「属于哪些资产」)。"""

    id: str
    kind: str
    name: str
    parent_id: str | None = None
    parent_name: str = ""
    role: str


class EntityUsageBoardOut(ApiModel):
    id: str
    name: str
    #: `cell`:板上有它的资产格;`mention`:某一格的提示词里 @ 了它。
    how: str


class EntityUsageGenerationOut(ApiModel):
    id: str
    session_id: str | None = None
    kind: str
    #: 用的哪条连接上的哪个模型:界面拿它们查生成选项,写和别处一样的两层名字(主名、副名),不写 `model` 这串编号(D65)
    provider_profile_id: str | None = None
    model: str
    prompt: str
    result_asset_id: str | None = None
    created_at: datetime


class EntityUsageWorkflowOut(ApiModel):
    id: str
    name: str


class EntityUsageOut(ApiModel):
    boards: list[EntityUsageBoardOut]
    generations: list[EntityUsageGenerationOut]
    workflows: list[EntityUsageWorkflowOut]
