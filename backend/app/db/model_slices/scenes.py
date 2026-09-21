from datetime import datetime
from typing import Any
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base
from app.db.model_base import new_id, now


class Scene3D(Base):
    __tablename__ = "scenes_3d"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), default="Untitled scene")
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Scene3DRevision(Base):
    __tablename__ = "scene_3d_revisions"
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes_3d.id", ondelete="CASCADE"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Scene3DModel(Base):
    """一份导入的 3D 模型。**归工作区,不归某个场景。**

    此前它挂在 `scene_id` 上,于是同一件道具在每个场景里都要重新导一份,而**工作流每跑一次
    都建一个新场景** —— 在 Blender 里建好的产品模型因此永远进不了自动成片:那个场景还不存在,
    模型就没处挂。`create_scene` 里那句"建完场景再导模型"也是这么来的。

    归工作区之后这些一起消失:一件道具导一次、处处能摆;场景删了模型还在(它是素材,不是
    场景的一部分);校验从"属于这个场景"变成"属于这个工作区",而那本来就是真正的边界。
    """

    __tablename__ = "scene_3d_models"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    format: Mapped[str] = mapped_column(String(10))
    #: 字节在磁盘上(media/scene-models/…),这里只留指路的 key —— 和字体、LUT 同一套。
    #: 此前是一列 LargeBinary:一份 100 MB 的模型进出一次要 400 MB 峰值内存,而下载那条
    #: `Response(model.data)` 是整份进内存、每个并发请求各付一次。
    file_key: Mapped[str] = mapped_column(String(512), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
