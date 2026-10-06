"""本机服务(ADR 0041):插件声明的一个常驻进程,宿主替它起停、看健康、收日志。一行对一个插件连接。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.db.model_base import now


class LocalService(Base):
    """这个连接背后由宿主管的那个进程:在哪跑、用哪个解释器、哪个端口、听不听局域网、要不要一直开着。

    **进程本身的状态(启动中、运行中、起不来)不在这里** —— 那是这一次后端进程里的事(见 domain/local_services),
    重启就重新起或者接回来。这里只存人定下的东西,以及建连接时选定、以后一直用的端口:插件按服务器地址分文件存
    每台服务器的本地数据,端口一变就对不上(ADR 0041 §1)。
    """

    __tablename__ = "local_services"

    instance_id: Mapped[str] = mapped_column(ForeignKey("plugin_instances.id", ondelete="CASCADE"), primary_key=True)
    #: 清单里那种服务的 key(`services[].key`)。
    service: Mapped[str] = mapped_column(String(40), nullable=False)
    #: 在哪跑。`directory` = 用我自己装的(选一个目录);第二步加 `managed`(让 Mosael 装)。
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="directory")
    #: 用户选的目录,原样存(插件认得出便携版外层那一层,宿主不替它改)。
    directory: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: 用户指定的解释器。空 = 由插件按目录自己认(便携版自带的、目录里或上一层的 venv)。
    python: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: 建的时候选定(从 8189 往上找第一个空的),写进连接的 `server_url`。两个连接不会用同一个。
    port: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    #: 听局域网(`0.0.0.0`)还是只听本机(缺省,拍板 6)。
    listen_lan: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Mosael 一启动就起,不等用到(拍板 4);退出 Mosael 时照样停。
    keep_running: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: 附加的启动参数(「高级」里填的,如 `--lowvram`),一项一个。
    extra_args: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)
