"""ASR model download manager.

funasr / whisperx download their weights *implicitly* inside the library on
first use (`AutoModel(...)`, `whisperx.load_model(...)`), printing progress bars
to stdout that the worker swallows — so a first transcribe silently blocks while
~2GB downloads. This module makes those downloads visible and manually
triggerable:

- a catalog of downloadable models (funasr bundle + whisperx sizes),
- install detection by probing the shared library caches on disk,
- deliberate download via the ASR worker's `warmup` action (runs in the external
  ASR interpreter, same as transcription), while a watcher thread polls the
  cache directory byte-size to report percentage, **speed and ETA**.

Progress is computed from bytes on disk vs. an expected total — robust and
cross-process (the download runs in a foreign interpreter), no tqdm parsing.
"""
from __future__ import annotations

import logging

import hashlib
import json
import os
import subprocess
import threading
from functools import lru_cache
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.ai.runtime import remote_size
from app.ai.runtime import workers
from app.core import interpreter, pip_install, run_log
from app.core.child_process import ChildProcess, popen_text, run_logged
from app.core.transfer_rate import DownloadRate
from app.core.config import settings
from app.core.text import blame_line

from app.ai.runtime.download_state import DownloadProgress, DownloadStore, ProbeCache
from app.ai.runtime.errors import RuntimeSetupError, failure_message, venv_failure, with_log
from app.core.i18n import tr

logger = logging.getLogger(__name__)

WORKER_PATH = workers.asr_script()
WARMUP_TIMEOUT_SECONDS = 3600
_POLL_SECONDS = 1.5
# A model counts as installed once its on-disk size reaches this fraction of the
# expected total — tolerates version drift and metadata files we don't count.
_INSTALLED_FRACTION = 0.6
#: 流式取权重时一次读多少字节。**流式是有意的**:239MB 先读进内存再落盘,内存峰值就是这个数
#: 而不是这一小块。
_DOWNLOAD_CHUNK = 256 * 1024
#: 取权重给的长超时。这是一次性的、用户已经在屏幕前等着的事,而慢链路上 239MB 可以很久。
_DOWNLOAD_TIMEOUT = 600.0


@dataclass(frozen=True)
class PinnedFile:
    """一个**钉死的下载**:URL 指向具体的一次提交,字节数与 sha256 一起写下来。

    别的引擎把"下什么"交给 funasr / whisperx / huggingface_hub 自己决定,我们只能事后看盘上有多大
    (见 `measured_total`)。sherpa-onnx 没有这种"库替我下"的一步 —— 权重是几个普通的 ONNX 文件,
    由 worker 自己按 URL 取 —— 于是"下哪一份"第一次成了我们自己要回答的问题。

    那就答得死一点:URL 带提交哈希(上游再往前推也不会改变我们拿到的那一份),字节数当分母,
    sha256 在落盘前校验。三者都对不上就当这次下载失败,而不是让一个改了半个字节的模型静默上桌。
    """

    #: 落盘的文件名。worker 按它拼路径,因此这个字段同时是"文件叫什么"的唯一来源。
    name: str
    #: 这个文件是干什么的:"model"(识别权重)、"tokens"(词表)、"vad"(断句)。
    #: worker 按它取文件,**不按文件名猜** —— 猜的话"哪个 onnx 是识别器、哪个是 VAD"就成了一条
    #: 隐含约定,而它会在下一次换模型时静默失效(VAD 当成识别器加载,报的是一句和原因无关的话)。
    role: str
    url: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class SubModel:
    """One weight repo that a catalog entry pulls. `cache_dir` is the directory
    name the library materialises under its cache root."""

    cache_dir: str
    #: 体积**问源要**时用的那个仓库 id(见 ai/runtime/remote_size)。`cache_dir` 是库在本地
    #: 摊开成的目录名,不一定等于仓库 id —— HuggingFace 那边是 `models--A--B` 这种转写。
    repo: str
    #: 源:"modelscope" 或 "hf"。
    source: str
    #: 问不到时退回的估算。写死的数会随上游改文件而失准,所以它只是兜底。
    #: **`pinned` 非空时它必须等于那些 pin 的字节和**(见 tests/test_asr_models 的棘轮):
    #: 那时它不再是"估算",而是这次要下的准确总量。
    expected_bytes: int
    #: 钉死的下载清单。非空 = 这一份**不问源**:URL 指向具体一次提交,而源上"当前 revision"
    #: 的大小恰恰可能不是我们要下的那一份。
    pinned: tuple[PinnedFile, ...] = ()


@dataclass(frozen=True)
class ModelEntry:
    id: str
    engine: str  # "funasr" | "sherpa-onnx" | "whisperx"
    label: str
    detail: str
    sub_models: tuple[SubModel, ...]
    # extra request params passed to the warmup worker (e.g. whisper_model)
    request: dict[str, Any]

    @property
    def expected_bytes(self) -> int:
        """问不到源时的兜底总量。**优先用 `measured_total`** —— 那才是实际要下多少。"""
        return sum(sub.expected_bytes for sub in self.sub_models)


#: 每个引擎的运行依赖。装到托管 venv 里 —— 重的那些(torch 2GB+)落在用户数据目录而不是安装包里。
#: 和 TTS 那边同一个做法(见 ai/runtime/tts_models.ensure_engine_runtime),理由也同一条:让用户
#: **不必**去设置里指定 Python 解释器。
ENGINE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "funasr": ("funasr", "torch", "torchaudio", "modelscope"),
    #: **只有预编译轮子,没有 torch。** 快和轻就是从这儿来的:同一个 SenseVoice 权重,
    #: 跑在 onnxruntime 上而不是 PyTorch 上 —— 依赖从 2GB+ 掉到约 12MB,起进程从"读一遍
    #: torch + 建图"掉到"读一遍 ONNX"。sherpa-onnx 为自己的每个 Python 版本发轮子
    #: (实测 3.10–3.14 都有 macOS arm64 轮子),所以托管 venv 用哪个解释器都装得上。
    "sherpa-onnx": ("sherpa-onnx",),
    "whisperx": ("whisperx",),
}


def _import_name(engine: str) -> str:
    """引擎名 → 能 `import` 的那个模块名。

    引擎名同时是 pip 名(连字符合法)和探测时 `import` 的目标(只能是下划线)。funasr 和
    whisperx 两边写法一致,所以此前不需要这一步;`sherpa-onnx` 是第一个不一致的。
    探测写错这个名字的表现是"环境永远装不上":pip 装成功了,`import` 还是报 ModuleNotFoundError。
    """
    return engine.replace("-", "_")

#: 托管的 ASR 运行环境。和 TTS 那个分开:两边的依赖会打架(不同的 torch 版本),而共用一个
#: venv 意味着装一边可能弄坏另一边。
#:
#: **这句话此前只写在注释里,没有兑现**:funasr 和 whisperx 仍然共用同一个 venv,而它们
#: 正是"两边依赖会打架"的两边。克隆那边差点为此付账(fish 钉 torch==2.8,f5 装的是 2.13),
#: 所以这里也按引擎分开。
MANAGED_ASR_ROOT = settings.data_dir / "asr"

def _venv_python(venv: Path) -> Path:
    windows = os.name == "nt"
    return venv / ("Scripts" if windows else "bin") / ("python.exe" if windows else "python")


def managed_venv_dir(engine: str) -> Path:
    safe = engine.replace("/", "-").replace("..", "-")
    return MANAGED_ASR_ROOT / f"venv-{safe}"


def managed_venv_python(engine: str) -> Path:
    return _venv_python(managed_venv_dir(engine))


# funasr aliases → their ModelScope cache directory names (funasr materialises
# under <modelscope_cache>/**/iic/<dir>). Sizes are approximate — used only for
# the percentage denominator.
_FUNASR_BUNDLE = ModelEntry(
    id="funasr",
    engine="funasr",
    label="asrLabel_funasr",
    detail="asrDetail_funasr",
    sub_models=(
        # SenseVoice:按官方说明「超过 40 万小时数据训练,支持超过 50 种语言,识别效果上优于 Whisper」,
        # 标点与逆文本规整都在模型内部。体积现在**问 ModelScope 要**(见 ai/runtime/remote_size);
        # 这里的数字只是问不到时的兜底,而它注定会随上游改文件而失准。
        SubModel("SenseVoiceSmall", "iic/SenseVoiceSmall", "modelscope", 937_000_000),
        # VAD 断句与说话人分离是**独立阶段**,与识别模型无关:它们按音频切段/聚类,换识别模型照样用。
        # 说话人分离不能丢 —— 转写面板的说话人标签、按人筛选都靠它。
        SubModel("speech_fsmn_vad_zh-cn-16k-common-pytorch",
                 "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch", "modelscope", 5_000_000),
        SubModel("speech_campplus_sv_zh-cn_16k-common",
                 "iic/speech_campplus_sv_zh-cn_16k-common", "modelscope", 30_000_000),
    ),
    request={"provider": "funasr", "action": "warmup"},
)


# ---------------------------------------------------------------------------
# sherpa-onnx(SenseVoice 的 ONNX 运行时)
# ---------------------------------------------------------------------------
#: sherpa-onnx 的权重放在应用自己的数据目录下(理由见 `_cache_roots` 里这一家那一支)。
SHERPA_MODEL_DIR_NAME = "sherpa-onnx"

_SHERPA_SENSE_VOICE_REV = "2365baeacb507f821a0c8120fcee3d484dba7a07"
_SHERPA_VAD_REV = "fba88cd2e921609e7675c3aaf51e0b9b295da4bc"
_SHERPA_SENSE_VOICE_REPO = "csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"

#: **钉死的三个文件。** 与 DSH 那个语音输入插件用的是同一套资产:同一个仓库、同一个提交、
#: 同一份 sha256(见它的 `runtime/assets.json`)。抄过来而不是"照名字重新下一份"是有意的 ——
#: 同一个模型名下的文件会变,而"我们验过的到底是哪一份权重"必须是一个能写下来的事实。
#:
#: **只留 int8,不做 fp32 档。** 这是本仓库里已经付过一次账的那个形状:目录里放两个 FunASR
#: 会逼用户回答一个他不该被问的问题("我该装哪套权重"),而"哪个精度"对用户是同一个问题 ——
#: 他没听过这段音频,也就无从判断 int8 够不够。何况:
#:   - int8 239 MB 对 fp32 938 MB,是**四分之一**,而这个引擎存在的全部理由就是轻和快;
#:   - SenseVoice 是编码器-解码器里对量化不敏感的一类,本机实测(见报告)中英文两段的
#:     文本与 fp32 **逐字相同**,耗时也相近。
#: 真要 fp32 时它仍然是一个普通的 ONNX 文件,加一个 catalog 条目即可 —— 那时才需要回答
#: "为什么要两个",而不是现在先替用户猜一个。
_SHERPA_PINNED: tuple[PinnedFile, ...] = (
    PinnedFile(
        name="model.int8.onnx",
        role="model",
        url=f"https://huggingface.co/{_SHERPA_SENSE_VOICE_REPO}/resolve/{_SHERPA_SENSE_VOICE_REV}/model.int8.onnx",
        bytes=239_233_841,
        sha256="c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51",
    ),
    PinnedFile(
        name="tokens.txt",
        role="tokens",
        url=f"https://huggingface.co/{_SHERPA_SENSE_VOICE_REPO}/resolve/{_SHERPA_SENSE_VOICE_REV}/tokens.txt",
        bytes=315_894,
        sha256="f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc",
    ),
    # VAD:长音频靠它切成一句一句。**不是可选项** —— 不切的话整段音频一次喂给识别器,
    # 中间几分钟的静默也会跟着一起编码,而且产出的 segments 只有一段(时间轴信息全丢)。
    PinnedFile(
        name="silero_vad.onnx",
        role="vad",
        url=f"https://huggingface.co/csukuangfj/vad/resolve/{_SHERPA_VAD_REV}/silero_vad.onnx",
        bytes=1_807_522,
        sha256="a35ebf52fd3ce5f1469b2a36158dba761bc47b973ea3382b3186ca15b1f5af28",
    ),
)


def sherpa_model_dir() -> Path:
    """sherpa-onnx 的权重落在哪个目录。**worker 也按这一份拼路径**,所以只有这一处定义。"""
    return MANAGED_ASR_ROOT / SHERPA_MODEL_DIR_NAME


def _sha256_of(path: Path) -> str:
    """盘上这个文件的 sha256(流式,不把文件读进内存)。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_DOWNLOAD_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def pinned_target(one: PinnedFile) -> Path:
    """一个 pin 该落在哪个路径上。**取文件的人和 worker 都从这里推**,不各拼一份。

    (worker 拿到的是 `sherpa_request` 里的 `sherpa_dir`,而它就是 `sherpa_model_dir()` ——
    与 `SubModel.cache_dir` 是同一个目录名,有一条测试钉着这一点。)
    """
    return sherpa_model_dir() / one.name


def pinned_url(one: PinnedFile) -> str:
    """按当前配的**模型源**换掉主机名,路径原样保留。

    这一步不是锦上添花:应用默认的模型源就是 `hf-mirror`(见 ai/runtime/config._from_env 与
    db/model_slices/runtime_config 那一列),而那个人群里 huggingface.co 往往是**不可达**的。
    钉死 URL 却写死主机名,等于"这个引擎在你的机器上一次都下不下来"。

    hf-mirror 就是同一套路径的镜像,所以一个 pin 在两种源上都能下,而 sha256 仍然照着同一份验 ——
    **pin 校验的正是"换了个地方拿到的是不是同一份东西"**。

    ModelScope 不在这一支:它不是 HF 兼容端点,这几个文件在那边也没有对应仓库,选了它照样走 HF
    (和 config.HF_ENDPOINTS 上面那段注释同一条道理)。
    """
    from app.ai.runtime import config as tts_config

    endpoint = tts_config.HF_ENDPOINTS.get(tts_config.get().source)
    if not endpoint:
        return one.url
    _scheme, rest = one.url.split("://", 1)
    _host, path = rest.split("/", 1)
    return f"{endpoint}/{path}"


def _fetch_pinned(one: PinnedFile, target: Path, *, on_block: Callable[[], None] | None = None) -> None:
    """取一个文件:流式写 `.part`,校验 sha256,**再**改成正式名。

    顺序不能反。先落成正式名再校验的话,一次断线就在盘上留下一个"名字对、内容截断"的模型,
    而下一轮"文件在,跳过"会直接放行它 —— 症状要到识别出一串乱码才看得见。半截的 `.part`
    留在目录里也是有意的:下载进度量的是这个目录的字节数(见 `_measure`),不留就只剩一根
    不动的进度条。

    **走 `RetryingClient`,也就是走出站检查**(core/outbound_guard)。URL 是代码里钉死的,但
    "允许往哪走"仍然只由那一道闸回答:一个把外网关掉的部署,这里该报出来的是那句"出站被拒",
    而不是一个 URLError。重试也在这一层(慢链路上一次 502 不该让用户白等 239MB)。
    """
    from app.core.http_retry import RetryingClient

    partial = target.with_name(target.name + ".part")
    partial.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with RetryingClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        with client.stream("GET", pinned_url(one)) as response:
            response.raise_for_status()
            with partial.open("wb") as handle:
                for block in response.iter_bytes(_DOWNLOAD_CHUNK):
                    digest.update(block)
                    handle.write(block)
                    if on_block is not None:
                        on_block()
    actual = digest.hexdigest()
    if actual != one.sha256:
        partial.unlink(missing_ok=True)
        raise RuntimeSetupError("asrErr_weightChecksum", name=one.name,
                                expected=one.sha256[:12], actual=actual[:12])
    os.replace(partial, target)


def _report_download(model_id: str, entry: ModelEntry, rate: DownloadRate, total: int,
                     started: float, now: float) -> None:
    """把这一刻的下载进度写进 store。**"等 worker"和"宿主自己取"两条路共用这一份** ——
    各写一遍的话,界面上的速度与剩余时间会有两种算法。"""
    current = _measure(entry)
    speed = rate.update(current, at=now)
    eta = rate.eta(remaining=max(0, total - current))
    # 有的后端(HuggingFace)是最后一下才把大文件落到位,字节数于是只在末尾跳 ——
    # 退回一个"已经等了多少"的心跳,界面就不会看着像卡死了。
    key, params = _fmt_eta(eta)
    if not key:
        elapsed = int(now - started)
        key, params = "dlMsg_elapsed", {"m": str(elapsed // 60), "s": f"{elapsed % 60:02d}"}
    _store.set(model_id, DownloadProgress(
        status="downloading", downloaded=current, total=total, speed=speed, eta=eta,
        message=key, params=params))


def ensure_pinned_files(entry: ModelEntry, *, model_id: str = "", verify: bool = False) -> None:
    """按 pin 把缺的文件取齐。齐了就立刻返回(**不发任何请求**)。

    这一家是唯一"权重由我们自己下"的(见 `PinnedFile`),而**取文件在宿主进程里做**:worker 跑在
    外来的解释器里,够不到本进程那道出站闸(见 asr_models 里 `_cache_roots` 那一段与
    core/outbound_guard)。于是两条路都走它:

    - 管理页点「下载」:走 `_download_body`,带进度;
    - 首次转写时权重还没下:走 `transcribe_with_engine` —— 和 funasr / whisperx "库自己在下"
      对应的是同一件事,只是下什么由 pin 说了算。

    `verify=True`(点下载)时对**已经在盘上的**文件也算一遍 sha256:用户点那个按钮的意思是
    "把这一套装对",不是"文件在就当我没来过"。`verify=False`(转写)只比字节数 —— 每说一句话
    就给 239MB 算一次哈希,是拿实打实的耗时换一个几乎不会发生的坏情况;内容真被改坏的入口是
    下载,而那条路每次都验。
    """
    total, _estimated = measured_total(entry)
    started = time.monotonic()
    rate = DownloadRate()
    rate.update(_measure(entry), at=started)
    last = [0.0]

    def tick() -> None:
        if not model_id:
            return
        now = time.monotonic()
        if now - last[0] < _POLL_SECONDS:
            return
        last[0] = now
        _report_download(model_id, entry, rate, total, started, now)

    for sub in entry.sub_models:
        for one in sub.pinned:
            target = pinned_target(one)
            if target.is_file():
                good = _sha256_of(target) == one.sha256 if verify else target.stat().st_size == one.bytes
                if good:
                    continue
                target.unlink()  # 坏了或版本不对:重下
            _fetch_pinned(one, target, on_block=tick)


def sherpa_request(action: str, **extra: Any) -> dict[str, Any]:
    """sherpa-onnx 的请求体 —— **预热和转写共用这一份**。

    和 funasr 那边同一条教训(见 workers/asr._funasr_kwargs):构建逻辑分成两份改过一次,代价是
    "下载"下的东西和"转写"要用的东西对不上。这里把目录、文件名、URL、sha256 放在一处,
    转写那一侧只是换一个 action —— 于是 worker 在转写时也能自己补下缺的那一个文件,
    和 funasr / whisperx "首次转写时库自己去下"的行为一致(进度由 `_mirror_model_download_progress`
    照同一套盘上字节数报出来)。
    """
    return {
        "provider": "sherpa-onnx",
        "action": action,
        "sherpa_dir": str(sherpa_model_dir()),
        "sherpa_files": [
            {"name": one.name, "role": one.role, "url": one.url, "bytes": one.bytes, "sha256": one.sha256}
            for one in _SHERPA_PINNED
        ],
        **extra,
    }


_SHERPA_BUNDLE = ModelEntry(
    id="sherpa-onnx-sensevoice",
    engine="sherpa-onnx",
    label="asrLabel_sherpaOnnx",
    detail="asrDetail_sherpaOnnx",
    sub_models=(
        SubModel(
            cache_dir=SHERPA_MODEL_DIR_NAME,
            # 钉死的那一份**不问源**(见 measured_total),所以这个 repo 只是记下它们从哪来;
            # 真正要取的 URL 逐个写在 pin 里。
            repo=_SHERPA_SENSE_VOICE_REPO,
            source="hf",
            # 由 pin 求和得来,**不另写一个数**:两个数分开写就一定会有一天对不上,
            # 而它们一个是分母、一个是"下几个文件"。
            expected_bytes=sum(one.bytes for one in _SHERPA_PINNED),
            pinned=_SHERPA_PINNED,
        ),
    ),
    request=sherpa_request("warmup"),
)


def _whisperx_entry(size: str, label: str, detail: str, expected: int) -> ModelEntry:
    return ModelEntry(
        id=f"whisperx-{size}",
        engine="whisperx",
        label=label,
        detail=detail,
        sub_models=(SubModel(f"models--Systran--faster-whisper-{size}",
                             f"Systran/faster-whisper-{size}", "hf", expected),),
        request={"provider": "whisperx", "action": "warmup", "whisper_model": size},
    )


CATALOG: tuple[ModelEntry, ...] = (
    _FUNASR_BUNDLE,
    _SHERPA_BUNDLE,
    _whisperx_entry("small", "WhisperX Small", "asrDetail_whisperSmall", 500_000_000),
    _whisperx_entry("medium", "WhisperX Medium", "asrDetail_whisperMedium", 1_530_000_000),
    _whisperx_entry("large-v3", "WhisperX Large v3", "asrDetail_whisperLarge", 3_100_000_000),
)

_BY_ID = {entry.id: entry for entry in CATALOG}


def measured_total(entry: ModelEntry, *, blocking: bool = False) -> tuple[int, bool]:
    """(这个条目要下的总字节, 这个数是不是估算)。

    此前用的是目录里写死的估算,而它同时当着卡片体积、进度分母、和"装好了没有"的判据 ——
    上游改一次文件三样一起失准。按源上的**实际文件**算(见 ai/runtime/remote_size);
    任何一份问不到,整个总量就退回估算并说出来 —— 报一个残缺的总数比报估算更糟:
    它看起来精确,而进度条会提前走满。
    """
    total = 0
    for sub in entry.sub_models:
        if sub.pinned:
            # **钉死的那一份不问源。** URL 指向具体一次提交,源上"当前 revision"的大小恰恰
            # 可能不是我们要下的那一份(上游推了新文件,而我们仍然下旧的那一个)。
            # 字节数写在 pin 里,和 sha256 一起;它就是准确值,不是估算。
            total += sub.expected_bytes
            continue
        files = (remote_size.files_for if blocking else remote_size.cached_files)(sub.source, sub.repo)
        size = remote_size.total_bytes(files)
        if not size:
            return entry.expected_bytes, True
        total += size
    return total, False


# ---------------------------------------------------------------------------
# Cache probing
# ---------------------------------------------------------------------------
def _cache_roots(engine: str) -> list[Path]:
    roots: list[Path] = []
    if engine == "funasr":
        env = os.environ.get("MODELSCOPE_CACHE")
        if env:
            roots.append(Path(env))
        roots.append(Path.home() / ".cache" / "modelscope")
    elif engine == "sherpa-onnx":
        # **这一家没有第三方库的缓存,因为没有任何库替我们下载。** funasr / whisperx 的权重
        # 是它们的库按自己的规矩摊开在 `~/.cache/...` 里的;sherpa-onnx 只是一套 ONNX 运行时,
        # 权重是我们自己按 pin 下的(见 PinnedFile),于是落在应用自己的数据目录里。
        # 这不是"另造一套下载器":进度、状态、百分比仍然走本模块这一套(见 measured_total /
        # _measure),只是"放在哪"由我们说了算。
        return [MANAGED_ASR_ROOT] if MANAGED_ASR_ROOT.is_dir() else []
    else:
        env = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
        if env:
            roots.append(Path(env))
        hf_home = os.environ.get("HF_HOME")
        if hf_home:
            roots.append(Path(hf_home) / "hub")
        roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    return [root for root in roots if root.is_dir()]


def _dir_size(path: Path) -> int:
    """目录占的磁盘,**符号链接不跟**。

    HuggingFace 缓存里 `snapshots/<rev>/model.bin` 是指回 `blobs/<sha>` 的符号链接;`is_file()`
    和 `stat()` 默认都跟着链接走,于是每个 blob 被数两遍 —— 实测正是整两倍(du 说 464MB,这里
    报 972MB)。

    后果不只是数字难看:`_is_installed` 的判据是"实测 ≥ 期望的某个比例",量翻倍意味着**下到
    一半的模型也会被判成已安装**,而它要到运行时才炸。
    """
    total = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_symlink() or not child.is_file():
                    continue
                total += child.stat().st_size
            except OSError:
                continue
    except OSError:
        return total
    return total


def _find_sub_dir(engine: str, cache_dir: str) -> Path | None:
    """Locate a sub-model's directory anywhere under the engine's cache roots
    (cache layouts drift across library versions, so we glob by dir name).

    **命名空间前缀那一种也要认**:同一个模型在不同版本的 modelscope 下可能落成
    `hub/models/iic/<dir>`,也可能落成 `models/iic--<dir>/snapshots/master`。只按裸名找的话,
    后一种会被当成"没下载" —— 实测 SenseVoice 就是这样:901MB 已经在盘上,界面却还写着未下载,
    点下载又拉一遍。这不是某个模型的特例,是布局漂移本身,所以在这里认,而不是给某个 id 开后门。
    """
    for root in _cache_roots(engine):
        direct = root / cache_dir
        if direct.is_dir():
            return direct
        # iic/<dir> 与 hub/**/<dir>
        for match in root.rglob(cache_dir):
            if match.is_dir():
                return match
        # models/<namespace>--<dir>
        for match in root.rglob(f"*--{cache_dir}"):
            if match.is_dir():
                return match
    return None


def _measure(entry: ModelEntry) -> int:
    """Current on-disk bytes across all of an entry's sub-model directories."""
    total = 0
    for sub in entry.sub_models:
        found = _find_sub_dir(entry.engine, sub.cache_dir)
        if found is not None:
            total += _dir_size(found)
    return total


def _pinned_installed(entry: ModelEntry) -> bool:
    """钉死的条目:**每个文件都在,而且字节数和 pin 一致**。

    这里不用那个"实测 ≥ 期望的六成"的通用判据 —— 它对 funasr / whisperx 是对症的(库会把权重
    连同我们数不到的一堆元数据一起摊开,六成是个容差),而对这一家是错的:**我们确切知道要有什么**。
    实测过它的后果:`tokens.txt`(315KB)被删掉之后,`_is_installed` 照旧回 True —— 240MB 早过了
    六成,于是一个缺文件的模型在界面上是「已安装」,一直到真的去转写才炸。

    同一个判据顺带堵上了另一个洞:下载中途被杀时留在盘上的 `.part` 也不再被当成"下好了"
    (它名字和 pin 对不上)。**只比字节数,不算 sha256** —— 每开一次设置页就给 239MB 算哈希
    是拿实打实的耗时换一个极小的概率;内容真被改坏的入口是下载,那条路每次都验(见 `_fetch_pinned`)。
    """
    for sub in entry.sub_models:
        if not sub.pinned:
            continue
        found = _find_sub_dir(entry.engine, sub.cache_dir)
        if found is None:
            return False
        for one in sub.pinned:
            target = found / one.name
            if not target.is_file() or target.stat().st_size != one.bytes:
                return False
    return True


def _is_installed(entry: ModelEntry) -> bool:
    if any(sub.pinned for sub in entry.sub_models):
        return _pinned_installed(entry)
    # 判据用实测总量:上游把文件改大之后,拿旧估算当分母会把"才下了一半"判成"已安装"。
    total, _estimated = measured_total(entry)
    return _measure(entry) >= int(total * _INSTALLED_FRACTION)


#: 「正在下 / 刚下失败」的那一半(静息时盘上的文件才是事实源)。见 runtime/download_state。
_store = DownloadStore()


def resolve_engine_python(engine: str) -> str | None:
    """装了这个引擎的解释器;没有就 None。调用方据此决定是报错还是换一个引擎试。"""
    try:
        return _resolve_python(engine)
    except Exception:  # noqa: BLE001 — "没有"就是答案,原因由调用方另行呈现
        return None


#: 探过没探过(见 runtime/download_state.ProbeCache)。装完环境之后调 refresh_runtime_status。
_probes = ProbeCache()


def probe_in_background(engine: str) -> None:
    _probes.probe_in_background(engine, lambda: runtime_ready(engine))


def refresh_runtime_status(engine: str) -> bool:
    """现在就探一次并记下来(装完之后调,以及测试里要确定答案时)。"""
    return bool(_probes.remember(engine, runtime_ready(engine)))


def runtime_status(engine: str) -> tuple[bool, bool]:
    """(跑得起来吗, 测过了吗)。没测过就在后台起一次,先把已知的给出去。

    **只答 `_probes` 里的那一份答案** —— 那是"这个问题定了没有"的唯一记录,也是 `runtime_ready`
    探到答案时会写进去的那一份(见它开头那段)。
    """
    value, known = _probes.known(engine)
    if known:
        return bool(value), True
    probe_in_background(engine)
    return False, False


def clear_runtime_probes() -> None:
    """装好环境之后把探测缓存清掉 —— 只有一处要清,因为只有一份缓存。"""
    # getattr:测试会把探测换成普通函数(没有 cache_clear)。清缓存是清理动作,不是判据,
    # 不该因为"被替换过"就炸。
    getattr(_resolve_python, "cache_clear", lambda: None)()
    getattr(runtime_ready, "cache_clear", lambda: None)()
    _probes.invalidate()


@lru_cache(maxsize=4)
def runtime_ready(engine: str) -> bool:
    """有没有一个解释器能 `import <engine>` —— 也就是**跑不跑得起来**。

    这和"模型文件在不在盘上"是两件独立的事,而它们完全可以一真一假:模型缓存在
    `~/.cache/modelscope`、`~/.cache/huggingface` 里,别的工具下过就在那儿;而这个应用的解释器
    里可能从来没装过 funasr/whisperx。用户撞到的正是这一种:三行「已安装」,一转写就报
    「未找到可用的转写环境」—— 两句话都没说谎,只是在回答不同的问题。

    缓存住:探测要起一次子进程,而这个函数在列表页每行都会被问一遍。装好环境之后调
    `clear_runtime_probes()`。

    **探出来的答案同时记进 `_probes`**(列状态读的那一份)。此前这里只填自己的 lru,
    两处于是各记各的,而它们会**不同步** —— 界面读到的那个组合
    (`runtime_checked=true` 配 `runtime_ready=false`)恰好是"答案定了,但定在装环境之前":
    轮询据此停下(见前端 lib/pollWhileUnsettled),那一页就永远写着「还没有能运行它的
    Python 环境」,而刷新一次页面又对了(新进程重新探一遍)。装环境那条路更会把这个假答案
    钉死:`ensure_engine_runtime` 开头问的正是这个 lru 缓存的 false,于是"已经有了就直接返回",
    `clear_runtime_probes()` 一次都不走。用户原话就是「明明环境已经装好了」。
    """
    try:
        _resolve_python(engine)
    except Exception:  # noqa: BLE001 — 探测失败就是"跑不起来",原因由调用方另行呈现
        return bool(_probes.remember(engine, False))
    return bool(_probes.remember(engine, True))


def _status_dict(entry: ModelEntry) -> dict[str, Any]:
    live = _store.get(entry.id)
    installed = _is_installed(entry)
    total, estimated = measured_total(entry)
    ready, checked = runtime_status(entry.engine)
    base = {
        "id": entry.id,
        "engine": entry.engine,
        "label": entry.label,
        "detail": entry.detail,
        "expected_bytes": total,
        "total_is_estimate": estimated,
        # **两件事分开报**:文件在不在(status)、跑不跑得起来(runtime_ready)。
        # 把它们合成一个"已安装"是这一页此前说谎的原因。
        # **不等探测**:它要起子进程 import funasr。没测过就先说"还没测",后台去问。
        # 一次问出来两个字段,而不是各问一遍 —— 两个答案必须来自同一次回答(见 runtime_ready)。
        "runtime_ready": ready,
        "runtime_checked": checked,
    }
    if live is not None and live.status == "downloading":
        return {
            **base,
            "status": "downloading",
            "downloaded_bytes": live.downloaded,
            # **不回落到模型大小**:装运行环境那一阶段没有可报的总量(跑的是 pip),
            # 顶一个模型的字节数上去,界面就会画出"0 MB / 500 MB"这种量错了东西的进度条。
            "total_bytes": live.total,
            "speed_bps": live.speed,
            "eta_seconds": live.eta,
            "message": live.message, "message_params": live.params,
        }
    if live is not None and live.status == "failed":
        return {**base, "status": "failed", "downloaded_bytes": _measure(entry),
                "total_bytes": total, "message": live.message, "message_params": live.params}
    if installed:
        ready = base["runtime_ready"]
        return {**base, "status": "installed", "downloaded_bytes": _measure(entry),
                "total_bytes": total,
                "message": "modelMsg_asrReady" if ready else "modelMsg_asrNoRuntime"}
    return {**base, "status": "missing", "downloaded_bytes": _measure(entry),
            "total_bytes": total, "message": "modelMsg_notDownloaded"}


def list_status() -> list[dict[str, Any]]:
    return [_status_dict(entry) for entry in CATALOG]


def get_status(model_id: str) -> dict[str, Any]:
    entry = _BY_ID.get(model_id)
    if entry is None:
        raise KeyError(model_id)
    return _status_dict(entry)


def any_downloading() -> bool:
    return _store.downloading()


# ---------------------------------------------------------------------------
# Download orchestration
# ---------------------------------------------------------------------------
def candidate_pythons(engine: str) -> list[Path]:
    """可能装了 funasr/whisperx 的解释器,按优先级。**这是唯一一份名单。**

    托管 venv 排在最前:那是应用自己建、自己装的那个(见 ai/runtime/asr_models.ensure_engine_runtime),
    最可能是对的。用户显式指定的次之,后端自己的解释器兜底。

    收在一处是因为它被问过两遍:转写走这里,模型页那个「跑不跑得起来」也走这里。此前两边各拼
    一份,而托管 venv 只加进了后者 —— 于是模型页显示「已安装」、一点转写就报"没有运行环境",
    同一个问题两个答案。
    """
    candidates: list[Path] = [managed_venv_python(engine)]
    if settings.asr_python:
        candidates.append(Path(settings.asr_python).expanduser())
    # 见 core/interpreter:打包版里"自己"是应用的 exe,拿它探测会再起一个后端。
    mine = interpreter.self_python()
    if mine:
        candidates.append(Path(mine))
    return candidates


@lru_cache(maxsize=8)
def _resolve_python(engine: str) -> str:
    """装了 `engine` 的那个解释器。**全项目唯一的探测实现**,也是唯一那份缓存。

    此前有两份:这里一份、transcription.resolve_transcription_runtime 一份,各带各的 lru_cache。两份实现意味着
    两个答案 —— 托管 venv 加进了这一份、漏了那一份,于是模型页说「已安装」而转写说"没有环境"。
    合成一份之后,加候选、改判据都只有一个地方。

    探测要起子进程,所以缓存;装完环境后调 `clear_runtime_probes()`。
    """
    for python in candidate_pythons(engine):
        if not python.is_file():
            continue
        probe = run_logged([str(python), "-c", f"import {_import_name(engine)}"], capture_output=True, timeout=120, what="转写引擎探测", level=logging.DEBUG)
        if probe.returncode == 0:
            return str(python)
    raise RuntimeSetupError("runtimeErr_asrPythonMissing", engine=engine)


def ensure_engine_runtime(engine: str, *, progress_key: str | None = None) -> None:
    """确保有一个解释器能 `import <engine>`;没有就建一个托管 venv 并装进去。

    这一步的存在,就是为了让用户**不必**去设置里指定 Python 解释器 —— 和 TTS 那边同一个做法
    (见 ai/runtime/tts_models.ensure_engine_runtime)。此前 ASR 没有这条路:模型下好了、页面写着
    「已安装」,而转写照样报「未找到可用的转写环境」,唯一的出路是自己去装 funasr 再设环境变量。

    已经跑得起来就直接返回 —— **不碰用户自带的环境**。但"跑得起来"这个答案要**留下来**
    (见 `runtime_ready`):这一条路正是用户点「装一次」时走的,而它此前只是 return 出去 ——
    `_probes` 里那个装环境**之前**的 false 原样留着。于是"已经能跑"和"列表说跑不起来"
    两个答案同时成立,而后者带着 `runtime_checked=true`(定了),前端据此停住轮询
    (见 lib/pollWhileUnsettled),那句「还没有能运行它的 Python 环境」就一直挂在那一页上。

    `progress_key` 是这次进度写在**哪一行**上(模型 id)。此前这里按引擎名写,而界面按模型 id 读,
    于是这两句阶段文字一次都没显示过 —— 用户看到的是一条不动的进度条配一句"准备下载…"。

    这一阶段**不报字节**:跑的是 pip(装 torch 等),它一个字节都不会落进模型缓存目录,而进度是按
    那个目录的增长算的。借用模型的 2.2GB 当分母,结果就是永远 0 MB / 2.2 GB。两件事量纲不同,
    就别共用一个进度条 —— 只报"在做哪一步"。
    """
    if runtime_ready(engine):
        #: 这个 true 要落进 `_probes` —— 那是"答案定了没有"的唯一记录。lru 里之所以已经有一个 true,
        #: 是因为上一次清过缓存之后探过(装环境、改解释器都会清,见 clear_runtime_probes),
        #: 所以它就是当下这个答案,记下来不亏;不记的话,列表那边会一直停在装环境之前的 false。
        refresh_runtime_status(engine)
        return
    key = progress_key or engine
    requirements = ENGINE_REQUIREMENTS.get(engine)
    if not requirements:
        raise RuntimeSetupError("runtimeErr_unknownAsrEngine", engine=engine)

    # **装,一律进这个引擎自己的目录。** 共用的那个只在探测里读(见 candidate_pythons)。
    venv_dir = managed_venv_dir(engine)
    venv_python = managed_venv_python(engine)
    if not venv_python.is_file():
        _store.set(key, DownloadProgress(status="downloading", message="dlMsg_creatingRuntime"))
        venv_dir.parent.mkdir(parents=True, exist_ok=True)
        # **不能用 sys.executable**:打包版里它是应用自己,`-m venv` 会把后端再启动一遍,
        # 然后把 uvicorn "端口已占用" 的日志当成"创建失败的原因"端给用户。
        base = interpreter.base_python()
        if not base:
            raise RuntimeSetupError("runtimeErr_noBasePython")
        created = run_logged(
            [base, "-m", "venv", str(venv_dir)],
            capture_output=True, text=True, timeout=600, what="创建转写运行环境")
        if created.returncode != 0 or not venv_python.is_file():
            raise venv_failure(created.stderr or created.stdout)

    _store.set(key, DownloadProgress(status="downloading", message="dlMsg_installingDeps", params={"engine": engine}))
    # **和克隆走同一个安装器**,包括管理页「引擎」里那个 pip 镜像 —— 此前这里没带,于是同一台机器上
    # 「声音克隆走镜像、转写直连 PyPI」,而设置项写的是「装引擎依赖时用的 pip 索引」。
    # 超时给足:torch 在慢网络下很久。
    #
    # 这个设置存在 tts_config 里(历史上克隆先有了它),但它管的是 pip 而不是克隆 ——
    # 两个引擎装依赖用的是同一个索引。在函数里 import:core/audio 不该在模块层依赖 domain。
    from app.ai.runtime import config as tts_config

    try:
        pip_install.install(
            venv_python,
            requirements,
            what="安装转写运行依赖",
            index_url=tts_config.get().pip_index_url,
        )
    except pip_install.PipInstallError as exc:
        raise RuntimeSetupError("runtimeErr_depsFailed", engine=engine, detail=str(exc)) from exc
    clear_runtime_probes()


def start_download(model_id: str) -> dict[str, Any]:
    """Kick off a deliberate download in a background thread. State is tracked in
    the in-memory store (polled via GET /asr/models); disk detection recovers
    the true state after a restart, so no persistent Job is needed."""
    entry = _BY_ID.get(model_id)
    if entry is None:
        raise KeyError(model_id)
    # **"文件都在了"不等于"没事可做"**:还可能缺运行环境,而那正是这个按钮此时要装的东西。
    # 这里一律早返回的话,那个按钮点了没有任何反应 —— 比报错更让人摸不着头脑。
    if _is_installed(entry) and runtime_ready(entry.engine):
        return _status_dict(entry)
    # **并行是允许的**(同 tts_models.start_download):每个引擎有自己的 venv,下载跑在各自的
    # 一次性子进程里,同时装不会互相弄坏。只拒绝"这一个已经在下了"。
    live = _store.get(model_id)
    if live is not None and live.status == "downloading":
        raise RuntimeSetupError("runtimeErr_alreadyDownloading", name=tr(entry.label))
    # 分母先留空:接下来可能是"装运行环境"(pip,量纲完全不同),真正开始拉模型时再填上。
    _store.set(model_id, DownloadProgress(status="downloading", message="dlMsg_preparingShort"))
    threading.Thread(target=_run_download, args=(model_id,), daemon=True).start()
    return _status_dict(entry)


def _fmt_eta(seconds: float | None) -> tuple[str, dict[str, str]]:
    """(key, 参数)—— **不拼句子**:拼进去那句话就只有一种语言了(见 core/i18n.t)。"""
    if not seconds or seconds <= 0:
        return "", {}
    m, s = divmod(int(seconds), 60)
    return ("dlMsg_etaMinutes", {"m": str(m), "s": f"{s:02d}"}) if m else ("dlMsg_etaSeconds", {"s": str(s)})


def _run_download(model_id: str) -> None:
    """Wrapped so the "downloading" flag can never outlive the thread that set it.

    start_download refuses while _store.downloading() is true. Anything escaping the body
    below — a worker that cannot be spawned, a disk error, a bug — used to leave that flag
    set for the life of the process, so EVERY later download was rejected with
    「已有模型正在下载」 and only a restart cleared it.
    """
    try:
        _download_body(model_id)
    except Exception as exc:  # noqa: BLE001 — the flag must be released whatever happened
        logger.exception("model download failed")
        message, params = failure_message(exc)
        _store.set(model_id, DownloadProgress(status="failed", message=message, params=params))


def _download_body(model_id: str) -> None:
    entry = _BY_ID[model_id]
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    output_path = settings.data_dir / f"asr-warmup-{model_id}.json"
    try:
        # **先把环境建好**。此前这里直接探测解释器、没有就报错 —— 于是缺环境的机器上,
        # 这一页显示着「已安装」,而点任何一个按钮都失败。
        ensure_engine_runtime(entry.engine, progress_key=model_id)
        python = _resolve_python(entry.engine)
    except Exception as exc:  # noqa: BLE001
        message, params = failure_message(exc)
        _store.set(model_id, DownloadProgress(status="failed", message=message, params=params))
        return

    started = time.monotonic()
    last_bytes = _measure(entry)
    # 钉死的那一套(见 PinnedFile)由**宿主**取:worker 跑在外来的解释器里,够不到本进程这道
    # 出站闸。别的两家一个 pin 都没有,这一句对它们什么都不做。
    if any(sub.pinned for sub in entry.sub_models):
        ensure_pinned_files(entry, model_id=model_id, verify=True)
    proc = popen_text(
        [python, str(WORKER_PATH), str(output_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(entry.request))
    proc.stdin.close()
    # The child's stdout/stderr must be drained while we poll. Hub downloads write tqdm
    # progress bars continuously (transcription.py notes this for the transcribe path); once one of
    # those pipes fills, the child blocks writing it, poll() never returns, and the UI shows
    # "下载中" with frozen byte counts forever. There is no timeout here on purpose — a
    # multi-gigabyte download over a slow link is legitimately long — so draining is the whole
    # defence.
    child = ChildProcess(proc)
    threading.Thread(target=lambda: [None for _ in child.raw_lines()], daemon=True).start()

    # 速度按**最近一段**算,不是按最近一次采样:下载器成块写盘,单窗口读数会在 0 和几百 MB/s
    # 之间跳,而 ETA 在跳到 0 的那一瞬就消失。和克隆那条下载路共用一份实现(core.transfer_rate)。
    rate = DownloadRate()
    rate.update(last_bytes, at=started)
    # **分母问源要**,不用目录里那个写死的估算。用户已经在等这次下载,所以这里可以阻塞去问
    # (超时 6 秒);问不到就退回估算 —— 那正是此前一直在用的数,不会更糟。
    # 问在**子进程起来之后**是有意的:funasr / whisperx 的下载是子进程在做,这 6 秒不该挡在它前面。
    download_total, _estimated = measured_total(entry, blocking=True)
    while proc.poll() is None:
        time.sleep(_POLL_SECONDS)
        _report_download(model_id, entry, rate, download_total, started, time.monotonic())

    stderr = child.finish(600)
    if proc.returncode == 0 and _is_installed(entry):
        _store.clear(model_id)  # disk detection now reports "installed"
    else:
        # 此前是 `stderr[:400]` —— 按**位置**裁的又一处(克隆那边裁的是尾巴)。开头 400 字符
        # 通常是进度条和一堆下载提示,真正的异常在后面。挑结论行(core/text.blame_line),
        # 完整输出落盘 —— 否则"进程没了"这种报错除了让用户重跑一遍之外无法诊断。
        path = run_log.save(
            f"模型 {model_id} · 引擎 {entry.engine}\n退出码 {proc.returncode}\n\n{stderr or '(子进程什么都没说)'}\n",
            kind="worker", what=f"asr-{model_id}",
        )
        blamed = blame_line(stderr or "")
        # 「完整日志:…」那半句不拼进原因里(拼进去就只剩一种语言),见 errors.with_log。
        message, params = with_log(blamed[:400], {}, path) if blamed else ("dlMsg_processDied", {})
        logger.warning("下载 %s 失败(完整输出见 %s)", model_id, path)
        _store.set(model_id, DownloadProgress(status="failed", message=message, params=params))
    try:
        output_path.unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Lazy-transcribe integration: report the first-use download in the job
# ---------------------------------------------------------------------------
def entry_for_transcribe(provider: str) -> ModelEntry | None:
    """The catalog entry a transcribe run will (lazily) download, if missing."""
    if provider == "funasr":
        return _FUNASR_BUNDLE
    if provider == "sherpa-onnx":
        return _SHERPA_BUNDLE
    return _BY_ID.get(f"whisperx-{settings.asr_whisper_model}")


def measure_fraction(entry: ModelEntry) -> float:
    total, _estimated = measured_total(entry)
    if not total:
        return 0.0
    return min(_measure(entry) / total, 0.99)


def is_installed(model_id_or_entry: str | ModelEntry) -> bool:
    entry = model_id_or_entry if isinstance(model_id_or_entry, ModelEntry) else _BY_ID.get(model_id_or_entry)
    return bool(entry and _is_installed(entry))


__all__ = [
    "CATALOG",
    "ModelEntry",
    "list_status",
    "get_status",
    "start_download",
    "any_downloading",
    "entry_for_transcribe",
    "measure_fraction",
    "is_installed",
]
