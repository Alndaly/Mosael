"""这台机器上的配置:本机运行时、网络出口、TTS,以及几种引擎/模型的安装状态。"""

from __future__ import annotations

from pydantic import Field
from app.api.schemas.base import ApiModel

class NetworkConfigOut(ApiModel):
    """出站代理设置。空 proxy_url = 直连。"""

    proxy_url: str = ""
    no_proxy: str = ""


class NetworkConfigUpdate(ApiModel):
    proxy_url: str | None = None
    no_proxy: str | None = None


class AiRuntimeConfigOut(ApiModel):
    max_retries: int = 3


class AiRuntimeConfigUpdate(ApiModel):
    # 供应商瞬断时的最大重试次数(不含首次);0 表示不重试。
    max_retries: int = Field(ge=0, le=10)


class TtsEngineOut(ApiModel):
    id: str
    label: str
    detail: str
    status: str
    downloaded_bytes: int = 0
    total_bytes: int = 0
    expected_bytes: int = 0
    #: 上面那个体积是**问下载源问出来的**,还是目录里写死的估算。
    #: 界面据此决定要不要说「约」—— 把一个猜出来的数字显示成实测值,用户会拿它当准数
    #: (然后发现进度条走到 93% 就完成了,或者反过来永远差最后几个百分点)。
    total_is_estimate: bool = True
    speed_bps: float = 0.0
    eta_seconds: float | None = None
    message: str = ""
    # Fish Speech only: the source checkout is separate from the weights, so surface it
    # on its own (weights can be "installed" while the source is still missing).
    needs_source: bool = False
    source_ready: bool = False
    source_dir: str = ""
    #: 这个引擎**真的**能用的下载源,按顺序给。界面据此渲染,而不是自己猜哪个引擎配哪些源
    #: —— 让界面猜的下场就是「ModelScope」最早的样子:列在那里、选得中、却什么都不改变。
    sources: list[str] = []
    #: 这个引擎吃不吃语速。界面据此决定显不显示那个下拉 —— 摆一个拨不动的旋钮比不摆更糟。
    supports_speed: bool = False
    #: **权重在不在盘上,和跑不跑得起来是两件事。** status 说前者,这个说后者:有没有一个
    #: Python 解释器能 import 这个引擎。两者完全可以一真一假(权重是别的工具下的、或者
    #: 托管 venv 被删了),而把它们合成一句「已安装,声音克隆可用」正是这一页说谎的方式。
    runtime_ready: bool = False
    #: 探过了没有。**"还没测过"和"测过了、跑不起来"是两回事** —— 探测要起子进程 import
    #: torch,不能卡在请求里,所以列状态时可能还没有答案。把未知说成"未就绪"就是拿一个未知
    #: 冒充一个结论。
    runtime_checked: bool = True


class TtsEngineChoiceOut(ApiModel):
    """An engine the配音 UI can offer. Distinct from TtsEngineOut, which describes a downloadable
    LOCAL model — same word, different thing, and defining both as TtsEngineOut silently
    shadowed the older one and broke /tts/models' response validation."""

    id: str
    label: str
    needs_key: bool
    needs_voice_id: bool
    voices: list[str] = []
    #: 这个引擎接不接语速。接不了就别在界面上摆那个旋钮 —— 拨得动却不生效,
    #: 比没有更糟(配音要的正是"塞进原时长",用户会以为自己调过了)。
    supports_speed: bool = True
    note: str = ""
    #: 这台机器上现在就能跑吗。远程引擎恒真(能不能跑取决于档案,那是另一件事);
    #: 本地克隆按解释器探测结果给,好让界面在**挑引擎**时就说清楚。
    ready: bool = True


class TtsConfigOut(ApiModel):
    engine: str
    python_path: str = ""
    source: str = "hf-mirror"
    pip_index: str = ""  # 空 = 官方 PyPI
    fish_repo_dir: str = ""  # Fish Speech source checkout
    fish_model_dir: str = ""  # Fish Speech weights dir (contains codec.pth)
    worker_ready: bool = False  # an interpreter with the engine installed was found
    worker_python: str = ""  # the resolved interpreter path (for display)
    #: 探过了没有。**「还没测过」和「测过了、跑不起来」是两回事** —— 探测要起子进程
    #: import f5_tts(连带 torch,实测 7 秒),所以这个接口不等它。同 AsrModelOut.runtime_checked。
    worker_checked: bool = True


class TtsConfigUpdate(ApiModel):
    engine: str = Field(pattern="^(f5-tts|fish-speech)$")
    python_path: str = ""
    source: str = Field(default="hf-mirror", pattern="^(hf|hf-mirror|modelscope)$")
    #: 没有 pip_index:它不属于克隆 —— 转写和人声分离装依赖时读的也是它,所以它有自己的接口
    #: (`PUT /settings/install-source`)。留在这里的话,克隆表单不发它时默认成 "",每保存一次
    #: 克隆设置,镜像就被悄悄重置回官方 PyPI。
    fish_repo_dir: str = ""
    fish_model_dir: str = ""


class InstallSourceOut(ApiModel):
    """本机引擎装依赖时用哪个 pip 索引。转写、声音克隆、人声分离三个引擎共用这一份。"""

    #: 预设 key(pypi/tsinghua/aliyun/tencent)或自定义 index URL;空 = 官方 PyPI。
    pip_index: str = ""


class InstallSourceUpdate(ApiModel):
    pip_index: str = Field(default="", max_length=200)


class DenoiseEngineOut(ApiModel):
    """一个降噪引擎:它是什么、现在能不能用、要不要装。

    界面**不认识任何引擎**,所以要显示的话都由这里给:`description` 说适合什么、代价是什么,
    `setup_hint` 说没准备好时去哪儿准备,`removes_music` 让界面把"会去掉音乐"单独标出来。
    `strengths` 为空 = 这个引擎没有档位,界面不摆那个旋钮。

    `installable` 的引擎要下载一次,`status` 是 installed / missing / installing / failed /
    unsupported(这个平台没有发布文件);其余引擎的 `status` 只有 ready / unavailable。
    """

    engine: str
    label: str
    description: str
    setup_hint: str = ""
    ready: bool
    strengths: list[str]
    removes_music: bool
    installable: bool = False
    status: str
    message: str = ""
    size_bytes: int = 0


class SeparationEngineOut(ApiModel):
    """一个人声/背景音分离引擎装没装。

    和转写模型那一页同一条区分:**文件在不在盘上**和**跑不跑得起来**是两件事。这里只有后者
    有意义 —— 权重是第一次分离时引擎自己拉的,所以 `status` 说的是"这个引擎 import 得进来吗"。

    `runtime_checked` 是第三种答案:**还没测过**。探一次要起子进程 import torch,而列状态是
    一次纯读的请求,所以它不等 —— 界面据此接着轮询,而不是把"未知"画成"没装"。
    """

    engine: str
    label: str
    status: str  # "installed" | "missing" | "installing" | "failed"
    runtime_ready: bool = False
    runtime_checked: bool = False
    #: 正在装的哪一步,或者失败的原因。空串 = 没什么要说的。
    message: str = ""


class AsrModelOut(ApiModel):
    id: str
    engine: str
    label: str
    detail: str
    status: str  # "installed" | "missing" | "downloading" | "failed"
    #: **模型文件在不在盘上,和跑不跑得起来是两件事。** status 说前者,这个说后者:有没有一个
    #: Python 解释器装了 funasr/whisperx。两者完全可以一真一假(模型缓存是别的工具下的),
    #: 而把它们合成一个「已安装」正是这一页此前说谎的原因。
    runtime_ready: bool = False
    #: 探过了没有。**"还没测过"和"测过了、跑不起来"是两回事** —— 探测要起子进程 import
    #: torch,不能卡在请求里,所以列状态时可能还没有答案。把未知说成"未就绪"就是拿一个未知
    #: 冒充一个结论。
    runtime_checked: bool = True
    downloaded_bytes: int = 0
    total_bytes: int = 0
    expected_bytes: int = 0
    #: 上面那个体积是问下载源问出来的,还是写死的估算(同 TtsEngineOut.total_is_estimate)。
    total_is_estimate: bool = True
    speed_bps: float = 0.0
    eta_seconds: float | None = None
    message: str = ""
