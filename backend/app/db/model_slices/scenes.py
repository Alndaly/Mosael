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
    __tablename__ = "scene_3d_models"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes_3d.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    format: Mapped[str] = mapped_column(String(10))
    #: 字节在磁盘上(media/scene-models/…),这里只留指路的 key —— 和字体、LUT 同一套。
    #: 此前是一列 LargeBinary:一份 100 MB 的模型进出一次要 400 MB 峰值内存,而下载那条
    #: `Response(model.data)` 是整份进内存、每个并发请求各付一次。
    file_key: Mapped[str] = mapped_column(String(512), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
