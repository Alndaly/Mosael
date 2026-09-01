from pydantic import BaseModel, Field

from app.ai.providers.contracts.generation import FIRST_FRAME, SOURCE_ROLES


class SourceAssetRef(BaseModel):
    """一份输入素材及其在生成请求中的用途。"""

    asset_id: str = Field(min_length=1, max_length=64)
    # 角色值由 provider contract 生成，避免 schema 与 adapter 能力表各维护一份。
    role: str = Field(default=FIRST_FRAME, pattern=f"^({'|'.join(SOURCE_ROLES)})$")
