"""本机服务(ADR 0041):连接背后由宿主起停的那个进程 —— 配置、状态、日志、认目录、补装、本机发现。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.api.schemas.base import ApiModel

LocalServiceState = Literal["stopped", "starting", "running", "restarting", "failed"]


class LocalServiceOut(ApiModel):
    """一个连接的本机服务:人定下的配置 + 进程此刻怎么样。界面按 1200 ms 轮询它(和引擎安装一样)。"""

    #: 清单里那种服务的 key,和给人看的名字(「本机 ComfyUI」)。
    service: str
    title: str
    #: 在哪跑。第一步只有 `directory`(用我自己装的);第二步加 `managed`(让 Mosael 装)。
    mode: Literal["directory"]
    directory: str
    #: 用户指定的解释器;空 = 由插件按目录自己认。
    python: str = ""
    port: int
    #: 写进连接 `server_url` 的地址。
    url: str
    listen_lan: bool = False
    keep_running: bool = False
    extra_args: list[str] = Field(default_factory=list)
    state: LocalServiceState
    #: 进程在的时候是它的 pid、什么时候起的(ISO 8601,UTC)。
    pid: int | None = None
    started_at: str | None = None
    #: 上一次从起到就绪用了几秒(第一次启动要解包前端、加载自定义节点,会慢一些)。
    ready_seconds: float | None = None
    #: 这个进程是上一个后端起的、这次启动接回来的。
    adopted: bool = False
    #: 最近 5 分钟里自动重启了几次。
    restarts: int = 0
    #: 停在「起不来」时的原因(按看的人的语言)和最后几行日志。
    error: str = ""
    failure_lines: list[str] = Field(default_factory=list)
    #: 看的人能不能动它(建、改、起、停都要部署管理员)。
    can_manage: bool = False


class LocalServiceUpdate(ApiModel):
    """建或改。没给的不动。换一个要运行的东西(目录、解释器)要带 `confirm_run_code: true` —— 界面先问过人。"""

    mode: Literal["directory"] | None = None
    directory: str | None = Field(default=None, max_length=2000)
    python: str | None = Field(default=None, max_length=2000)
    listen_lan: bool | None = None
    keep_running: bool | None = None
    #: 附加参数,一整行(空白分隔,带空格的一项用双引号括起来;反斜杠原样)。
    extra_args: str | None = Field(default=None, max_length=4000)
    port: int | None = None
    confirm_run_code: bool = False


class LocalServiceDetectRequest(ApiModel):
    """认一个目录。会试跑一次插件说的那几行(比如 `import torch`),所以要带 `confirm_run_code: true`。"""

    directory: str = Field(min_length=1, max_length=2000)
    python: str = Field(default="", max_length=2000)
    confirm_run_code: bool = False


class LocalServiceFactOut(ApiModel):
    label: str
    value: str


class LocalServiceProblemOut(ApiModel):
    level: Literal["error", "warning"]
    text: str


class LocalServiceOfferOut(ApiModel):
    """插件说可以补装的东西(ComfyUI:模型库要的 pysssss)。界面给一颗「补装」,确认框里摆 description。"""

    title: str
    description: str = ""


class LocalServiceDetectOut(ApiModel):
    #: 认出来了、能起(插件说能,而且没有一条 error)。
    ok: bool
    facts: list[LocalServiceFactOut] = Field(default_factory=list)
    problems: list[LocalServiceProblemOut] = Field(default_factory=list)
    add_nodes: LocalServiceOfferOut | None = None


class LocalServiceLogsOut(ApiModel):
    lines: list[str] = Field(default_factory=list)
    #: 完整日志在这台机器上的哪个文件。
    path: str = ""


class LocalServiceAddNodesRequest(ApiModel):
    #: 界面问过人了:会往那个目录里写东西、要从网上下载。
    confirm: bool = False


class LocalServiceAddNodesOut(ApiModel):
    installed: list[str] = Field(default_factory=list)
    #: 装到了哪儿(写明给人看)。
    path: str = ""
    message: str = ""


class LocalServiceFoundOut(ApiModel):
    url: str
    label: str


class LocalServiceDiscoveryOut(ApiModel):
    """本机已经在跑的(插件知道去哪几个端口问)。建的是「连一台服务器」那一种,Mosael 不去起停它。"""

    servers: list[LocalServiceFoundOut] = Field(default_factory=list)


__all__ = [
    "LocalServiceAddNodesOut", "LocalServiceAddNodesRequest", "LocalServiceDetectOut", "LocalServiceDetectRequest",
    "LocalServiceDiscoveryOut", "LocalServiceFactOut", "LocalServiceFoundOut", "LocalServiceLogsOut",
    "LocalServiceOfferOut", "LocalServiceOut", "LocalServiceProblemOut", "LocalServiceUpdate",
]
