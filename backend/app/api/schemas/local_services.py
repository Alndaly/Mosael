"""本机服务(ADR 0041):连接背后由宿主起停的那个进程 —— 配置、状态、日志、认目录、补装、本机发现。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.api.schemas.base import ApiModel

LocalServiceState = Literal["stopped", "starting", "running", "restarting", "failed"]
LocalServiceInstallState = Literal["installing", "succeeded", "failed", "cancelled"]


class LocalServiceInstallStepOut(ApiModel):
    """安装的一步:插件说的那几步(查空间、下源码……),最后是宿主的「试起一次」。"""

    key: str
    title: str
    done: bool = False


class LocalServiceInstallOut(ApiModel):
    """这一次安装到了哪一步(内存里的;后端重启后没了,磁盘上的安装记录还在 —— 看安装计划)。"""

    state: LocalServiceInstallState
    #: 正在做(或停在)哪一步的 key。
    step: str = ""
    steps: list[LocalServiceInstallStepOut] = Field(default_factory=list)
    #: 这一步手上那个文件下了多少、一共多少(不知道就是 null)、多快(字节每秒)、是哪个(文件名或一句话)。
    done_bytes: int | None = None
    total_bytes: int | None = None
    speed: int | None = None
    item: str = ""
    #: 没装成时的原因(按看的人的语言)。
    error: str = ""
    started_at: str
    finished_at: str | None = None


class LocalServiceOut(ApiModel):
    """一个连接的本机服务:人定下的配置 + 进程此刻怎么样。界面按 1200 ms 轮询它(和引擎安装一样)。"""

    #: 清单里那种服务的 key,和给人看的名字(「本机 ComfyUI」)。
    service: str
    title: str
    #: 在哪跑:`directory`(用我自己装的)/ `managed`(让 Mosael 装,目录是宿主分的安装目录)。
    mode: Literal["directory", "managed"]
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
    #: 让 Mosael 装的那一份装好了没有(试起过、健康检查通过;「用我自己装的」总是 true)。
    installed: bool = True
    #: 它装好时建 venv 用的 Python 小版本,和现在随包的那个;对不上就是 `needs_rebuild`(起之前会拦下)。
    python_minor: str = ""
    base_python_minor: str = ""
    needs_rebuild: bool = False
    #: 这一次安装(正在装、刚装完、没装成、取消了);没有就是 null。
    install: LocalServiceInstallOut | None = None
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


class LocalServiceDownloadOut(ApiModel):
    """安装要从哪儿下一样东西(给确认页:会连哪几个站)。"""

    label: str
    url: str = ""


class LocalServicePlanOut(ApiModel):
    """让 Mosael 装之前的安装计划(插件看过这台机器):能不能装、装哪种 PyTorch、要多少空间、分几步、从哪儿下。"""

    #: 这一次能开始装:这台机器能装(`supported`),而且没有一条 error(空间不够、路径太长这类)。
    ok: bool
    #: 这台机器本身能不能装(插件对平台的结论)。
    supported: bool = False
    #: 这台机器是什么(「Apple 芯片 Mac」「Windows + NVIDIA GeForce RTX 4090(显存 24 GB,驱动 581.57)」)和为什么能 / 不能装。
    platform: str = ""
    verdict: str = ""
    #: 装哪种 PyTorch:`mps` 或某个 CUDA 源(`cu130`);不能装时是空串。给安装时原样带回来。
    flavour: str = ""
    torch: str = ""
    #: 装的 ComfyUI 版本(接着装时是已经解开的那一份)。
    version: str = ""
    #: 至少要多少剩余空间、那块盘现在还剩多少(字节)。
    disk_bytes: int = 0
    free_bytes: int = 0
    steps: list[LocalServiceInstallStepOut] = Field(default_factory=list)
    downloads: list[LocalServiceDownloadOut] = Field(default_factory=list)
    problems: list[LocalServiceProblemOut] = Field(default_factory=list)
    #: 装在哪(宿主分的安装目录)。
    directory: str = ""


class LocalServiceInstallRequest(ApiModel):
    """装、接着装、重建运行环境。界面问过人了(会在这台机器上下载、运行代码),带 `confirm_run_code: true`;`flavour` 是确认页上
    那种 PyTorch —— 插件装之前再看一次这台机器,对不上就不装。"""

    confirm_run_code: bool = False
    flavour: str = Field(min_length=1, max_length=40)


__all__ = [
    "LocalServiceAddNodesOut", "LocalServiceAddNodesRequest", "LocalServiceDetectOut", "LocalServiceDetectRequest",
    "LocalServiceDiscoveryOut", "LocalServiceDownloadOut", "LocalServiceFactOut", "LocalServiceFoundOut",
    "LocalServiceInstallOut", "LocalServiceInstallRequest", "LocalServiceInstallStepOut", "LocalServiceLogsOut",
    "LocalServiceOfferOut", "LocalServiceOut", "LocalServicePlanOut", "LocalServiceProblemOut", "LocalServiceUpdate",
]
