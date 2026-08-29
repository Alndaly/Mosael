"""TTS engine model manager + external-interpreter resolution.

Mirrors app/audio/asr_models.py: a catalog of downloadable TTS engine weights,
install detection by probing the HuggingFace cache, deliberate download via the
worker's warmup action (runs in the external TTS interpreter), byte-poll
progress with speed + ETA. The heavy engines (f5-tts / fish-speech) live in a
separate Python resolved from OPEN_STUDIO_TTS_PYTHON.
"""
from __future__ import annotations

import logging

import json
import os
import sys
import subprocess
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.ai.runtime import workers
from typing import Any

from app.core import interpreter, pip_install, run_log
from app.core.child_process import ChildProcess, popen_text, run_logged
from app.core.rate import DownloadRate
from app.core.config import settings
from app.core.text import blame_line, strip_ansi
from app.ai.runtime import remote_size

logger = logging.getLogger(__name__)

WORKER_PATH = workers.tts_script()
_POLL_SECONDS = 1.5
_INSTALLED_FRACTION = 0.6


@dataclass(frozen=True)
class TtsEngine:
    id: str  # engine id used by the worker: "f5-tts" | "fish-speech"
    label: str
    detail: str
    cache_dirs: tuple[str, ...]  # HF cache dir names to sum for install/progress
    expected_bytes: int
    module: str  # importable python module that proves the engine is installed
    #: 装进托管 venv 的 pip 依赖。fish-speech 的 fish_speech 包不在 PyPI(靠 git 检出),
    #: 所以这里只列它运行所需的第三方依赖。
    pip_requirements: tuple[str, ...] = ()
    #: 这个引擎的权重在 ModelScope 上的仓库 id。空 = ModelScope 上没有(或只有一部分),
    #: 那就不该把它列进这个引擎的下载源里 —— 只供一半的源不是源。
    modelscope_repo: str = ""
    #: 合成**真正**会 import 的模块。探测跑的就是这几行 —— 写顶层包名等于没探
    #: (`import fish_speech` 命中一个空的 __init__,永远成功,而合成 import 的是它的子模块)。
    imports: tuple[str, ...] = ()
    #: 需不需要参考文本。F5 不需要(它自己会转写参考音频);Fish Speech 需要 —— 我们用
    #: `mode="tts"` 构造它,不带 ASR,空文本就是空文本,合成出来听不懂。
    needs_reference_text: bool = False
    #: 吃不吃语速。实测:`F5TTS.infer(..., speed=...)` 吃;fish 的 `ServeTTSRequest` 字段里
    #: 根本没有这一项 —— 给它一个语速等于假装能调。此前我用一句「本地克隆的 worker 不吃这个
    #: 参数」把两个引擎一起判了,而那句话只对 fish 成立。
    supports_speed: bool = False


CATALOG: tuple[TtsEngine, ...] = (
    TtsEngine(
        id="f5-tts",
        label="F5-TTS",
        detail="ttsDetail_f5",
        cache_dirs=("models--SWivid--F5-TTS", "models--charactr--vocos-mel-24khz"),
        expected_bytes=1_500_000_000,
        module="f5_tts",
        # modelscope:走 ModelScope 拉那 1.35 GB 检查点要用它。**列了源就得带上客户端** ——
        # 真机上正是漏了它,拉权重时 ModuleNotFoundError。
        # torchcodec 显式列出来:它是 torchaudio 的**间接**依赖,不写在这儿的话
        # `pip install --upgrade f5-tts` 不会带着它升。而它恰恰是最容易过期的一环 ——
        # 每个版本只支持到当时的 FFmpeg,系统 ffmpeg 一升级就集体加载失败(0.15 支持到
        # FFmpeg 8,而这台机器上是 9)。不钉版本:要的就是当下最新的那个。
        pip_requirements=("f5-tts", "modelscope", "torchcodec"),
        # 检查点(1.35 GB)和 vocab 在 ModelScope 上;声码器 vocos(约 55 MB)只在 HF
        # (AI-ModelScope / charactr / iic 三个命名空间都查过,都是 404)。
        # 所以这条路是"大的走快路,小的还走 HF" —— 在 46 KB/s 的网络上,那 1.35 GB
        # 是八小时和三分钟的区别,而 55 MB 就算慢也只有二十分钟。
        modelscope_repo="AI-ModelScope/F5-TTS",
        imports=("f5_tts.api",),
        needs_reference_text=False,
        supports_speed=True,
    ),
    TtsEngine(
        id="fish-speech",
        label="Fish Speech S2 Pro",
        detail="ttsDetail_fishSpeech",
        cache_dirs=("models--fishaudio--s2-pro",),
        # 11.01 GB —— 照 Hub 上 fishaudio/s2-pro 的文件清单实测(两个 4~5 GB 的 safetensors
        # + 1.87 GB 的 codec.pth),`snapshot_download` 是整仓拉。此前写的 4.0 GB 是拍出来的:
        # 卡片上那句「4.0 GB」是用户据以决定要不要下的数字,而 `_is_installed` 的 0.6 倍判据
        # 意味着只下了两成就会被判成"已安装",然后合成在运行时炸。
        expected_bytes=11_000_000_000,
        module="fish_speech",
        # 这张表是**实测**补出来的,不是照上游 pyproject 抄的:在一台干净机器上依次撞出
        # natsort → pytorch_lightning → lightning → audiotools → dac 五轮,而其中
        # descript-audiotools / descript-audio-codec **连 fish 自己的 pyproject 都没声明**。
        # 所以"照它的清单装"同样不够,判据只能是 ENGINE_IMPORTS 那几行导得动。
        #
        # 一律不写版本钉子:上游 pin 了 torch==2.8.0,而这个 venv 是两个引擎共用的,
        # 照 pin 装会把 f5(torch 2.13)一起弄坏。实测不钉版本时两边都能跑。
        pip_requirements=("torch", "torchaudio", "transformers", "huggingface_hub", "hydra-core", "loguru",
                          "natsort", "pyrootutils", "loralib", "resampy", "einops", "librosa",
                          "pytorch-lightning", "lightning", "tensorboard", "grpcio", "kui",
                          "descript-audiotools", "descript-audio-codec",
                          # 走 ModelScope 下权重要用它。用户机器上实测 ~9 MB/s,
                          # 而 HuggingFace 与 hf-mirror 都是 46 KB/s —— 两百倍。
                          "modelscope"),
        modelscope_repo="fishaudio/s2-pro",
        imports=("fish_speech.utils.schema", "tools.server.inference", "tools.server.model_manager"),
        needs_reference_text=True,
        supports_speed=False,
    ),
)

_BY_ID = {engine.id: engine for engine in CATALOG}

#: 谁都能走的那几条(HuggingFace 官方 + 它的镜像)。ModelScope 按引擎有没有对应仓库来加。
_UNIVERSAL_SOURCES = ("hf", "hf-mirror")


def sources_for(engine_id: str) -> tuple[str, ...]:
    """这个引擎**真的**能用的下载源。

    界面据此渲染下拉,而不是自己猜。让界面猜的下场就是这个选项最早的样子:列在那里、选得中、
    却什么都不改变。
    """
    engine = _BY_ID.get(engine_id)
    if engine is None or not engine.modelscope_repo:
        return _UNIVERSAL_SOURCES
    return (*_UNIVERSAL_SOURCES, "modelscope")


def effective_source(engine_id: str, source: str) -> str:
    """把"用户选的源"落到"这个引擎能走的源"上。

    库里存着 modelscope、而当前引擎是 F5 时,不能就这么去 ModelScope 上找一个不存在的仓库。
    """
    return source if source in sources_for(engine_id) else "hf"


def _hf_roots() -> list[Path]:
    roots: list[Path] = []
    env = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    if env:
        roots.append(Path(env))
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        roots.append(Path(hf_home) / "hub")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    return [root for root in roots if root.is_dir()]


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += child.stat().st_size
            except OSError:
                continue
    except OSError as exc:
        # 目录读不动时返回的是**残缺的**总量,而这个数会被 `_is_installed` 当判据用 ——
        # 一个权限问题会表现成"模型没装好"。量不全就说一声。
        logger.debug("量 %s 的大小时读不动:%s", path, exc)
        return total
    return total


def _fish_model_dir() -> Path | None:
    """Fish Speech 的权重目录(配置的 / App 托管的),没有解析出来就是 None。"""
    from app.ai.runtime import config as tts_config

    model = tts_config.get().resolved_fish_model
    return Path(model) if model and Path(model).is_dir() else None


def _f5_model_dir() -> Path | None:
    """F5 走 ModelScope 时权重落的地方(没有就是 None,那说明走的是 HF 缓存那条路)。"""
    from app.ai.runtime import config as tts_config

    path = tts_config.MANAGED_F5_MODEL
    return path if path.is_dir() else None


def _measure(engine: TtsEngine) -> int:
    # Fish Speech reuses a local weights dir (configured / app-managed), not the
    # HF hub cache — measure that so a reused setup reads as installed, not "missing".
    if engine.id == "fish-speech":
        model = _fish_model_dir()
        if model is not None:
            return _dir_size(model)
    if engine.id == "f5-tts":
        managed = _f5_model_dir()
        if managed is not None and _dir_size(managed) > 0:
            return _dir_size(managed)
    total = 0
    for name in engine.cache_dirs:
        for root in _hf_roots():
            found = root / name
            if found.is_dir():
                total += _dir_size(found)
                break
    return total


#: safetensors 分片清单的文件名。模型自己带着"我需要哪些文件、合起来多大"的答案。
_SHARD_INDEX = "model.safetensors.index.json"


def _fish_manifest_complete(model: Path) -> bool | None:
    """按 `model.safetensors.index.json` 核 Fish Speech 的权重齐不齐。

    返回 None = 这个目录没有清单(别的工具下的老目录),交给调用方回退到体积判据 ——
    读不到清单不等于"没装好",不能把一个已经能用的环境说成坏的。
    """
    index = model / _SHARD_INDEX
    if not index.is_file():
        return None
    try:
        manifest = json.loads(index.read_text(encoding="utf-8"))
        shards = set((manifest.get("weight_map") or {}).values())
        expected = int((manifest.get("metadata") or {}).get("total_size") or 0)
    except (OSError, ValueError, TypeError) as exc:
        # 读不出清单就退回体积判据(见下),但**要说一声**:一个坏掉的清单和"老目录没有清单"
        # 走的是同一条路,而前者说明这份权重可能是坏的。
        logger.warning("权重清单读不出来,退回按体积判断:%s(%s)", index, exc)
        return None
    if not shards:
        return None
    if not (model / "codec.pth").is_file():  # 合成要加载的另一半
        return False
    actual = 0
    for name in shards:
        shard = model / name
        if not shard.is_file():
            return False
        actual += shard.stat().st_size
    # 少一个字节都不算:一个写了一半的 safetensors 加载时才会炸,而那时错误指向"文件损坏",
    # 没人会想到是"还没下完"。
    return actual >= expected if expected else True


def _has_partial_downloads(engine: TtsEngine) -> bool:
    """HuggingFace 缓存里下载中的 blob 叫 `*.incomplete` —— 它在就说明还没下完。"""
    for name in engine.cache_dirs:
        for root in _hf_roots():
            found = root / name
            if found.is_dir() and any(found.rglob("*.incomplete")):
                return True
    return False


def _install_verdict(engine: TtsEngine) -> str:
    """把「装没装好」这个判断的**依据**摊开成几行字,给失败日志用。

    判成"没装好"而子进程又什么都没说错时,用户和我手上都只剩一句结论、没有任何过程。
    这几行就是那个过程:量到多少、要求多少、该有的文件在不在。
    """
    lines = [f"判定:{'已装好' if _is_installed(engine) else '未装好'}"]
    try:
        total, estimated = measured_total(engine, _download_source(engine.id))
        measured = _measure(engine)
        lines.append(f"  量到 {measured:,} 字节 / 需要 {int(total * _INSTALLED_FRACTION):,}"
                     f"(总量 {total:,},{'估算' if estimated else '实测'})")
        if engine.id == "f5-tts" and (managed := _f5_model_dir()) is not None:
            ckpt = [str(x.relative_to(managed)) for x in managed.rglob("*.safetensors")]
            ckpt += [str(x.relative_to(managed)) for x in managed.rglob("*.pt")]
            vocab = [str(x.relative_to(managed)) for x in managed.rglob("vocab*.txt")]
            lines.append(f"  权重目录 {managed}")
            lines.append(f"  检查点 {ckpt or '(没有)'}")
            lines.append(f"  vocab {vocab or '(没有)'}")
        if _has_partial_downloads(engine):
            lines.append("  **有没下完的分片(*.incomplete)**")
    except Exception as exc:  # noqa: BLE001 — 诊断信息取不到不该盖住真正的失败
        logger.debug("取 %s 的安装判定依据时出错", engine.id, exc_info=True)
        lines.append(f"  (取判定依据时出错:{exc})")
    return "\n".join(lines)


def _is_installed(engine: TtsEngine) -> bool:
    """装没装,**看该有的文件在不在**,不是看体积够不够。

    此前的判据是"实测 ≥ 期望 × 0.6"。比例回答不了"能不能用":用户机器上抓到过分片 2 才下
    三分之一、总量已经过线的情形,于是设置页写着「已安装,声音克隆可用」,而合成会在加载权重
    时炸。转写那边踩过同一个根的另一种形态(符号链接把体积翻倍)。

    体积判据留作**兜底**:老目录、别的工具下的缓存没有清单可核,那时它仍然是唯一能问的东西。
    """
    if engine.id == "fish-speech":
        model = _fish_model_dir()
        if model is not None:
            complete = _fish_manifest_complete(model)
            if complete is not None:
                return complete
    elif engine.id == "f5-tts" and (managed := _f5_model_dir()) is not None:
        # 走 ModelScope 落在我们自己目录里的那份:检查点 + vocab 都在才算。
        # 只看体积会把"只下到 vocab"也算成装好了。
        #
        # **rglob 不是 glob**:ModelScope 是按仓库内路径落盘的,文件在
        # `F5TTS_v1_Base/model_1250000.safetensors`,而顶层 glob 一个也匹配不到 ——
        # 这两个判据于是从来没成立过,一直悄悄落到底下的体积兜底上。
        # (基础模型 shared_root=True 才落在根下,别的语言各有自己的子目录。)
        has_ckpt = any(managed.rglob("*.safetensors")) or any(managed.rglob("*.pt"))
        has_vocab = any(managed.rglob("vocab.txt")) or any(managed.rglob("vocab_*.txt"))
        if has_ckpt and has_vocab:
            return True
        if has_ckpt or has_vocab:
            return False
    if _has_partial_downloads(engine):
        return False
    # 判据也用实测总量:上游把文件改大之后,拿旧估算当分母会把"才下了一半"判成"已安装",
    # 然后合成在运行时炸(fish-speech 那条 4.0 GB 的旧估算就是这么坑过一次)。
    total, _estimated = measured_total(engine, _download_source(engine.id))
    return _measure(engine) >= int(total * _INSTALLED_FRACTION)


# ---------------------------------------------------------------------------
# Interpreter resolution (mirrors ASR)
# ---------------------------------------------------------------------------
#: torchcodec(torchaudio 2.9+ 唯一的解码后端)带的是**按 FFmpeg 大版本编译**的一组动态库:
#: libtorchcodec_core4…core9,每个硬依赖一个 libavutil 主版本。而 0.16 起这些 dylib **不带
#: LC_RPATH** —— dlopen 解析 `@rpath/libavutil.NN.dylib` 时无路可查,只能靠外部给库搜索路径。
#: 于是 ffmpeg 装得好好的、版本也对得上,合成照样报「语音合成失败」。
#:
#: coreN 与 libavutil 主版本差一个常数(core9→61、core8→60…core4→56)。**从盘上实际有哪几个
#: coreN 推**,而不是写死一张表:torchcodec 每升一版就多支持一个 FFmpeg,写死的表会在下一次
#: 升级后开始说谎。
_CORE_TO_AVUTIL_OFFSET = 52


def _torchcodec_avutil_majors(engine_python: str) -> tuple[int, ...]:
    """这套 torchcodec 认得的 libavutil 主版本,从高到低。装的时候带了什么就是什么。"""
    interpreter = Path(engine_python)
    majors: set[int] = set()
    for site in interpreter.parent.parent.glob("lib/python*/site-packages/torchcodec"):
        for lib in site.glob("libtorchcodec_core*.dylib"):
            digits = "".join(ch for ch in lib.stem.rsplit("core", 1)[-1] if ch.isdigit())
            if digits:
                majors.add(int(digits) + _CORE_TO_AVUTIL_OFFSET)
    return tuple(sorted(majors, reverse=True))


def _ffmpeg_lib_roots() -> list[Path]:
    """Homebrew 的安装前缀(Apple Silicon / Intel)。单独一个函数是为了测试能换掉它。"""
    return [Path("/opt/homebrew/opt"), Path("/usr/local/opt")]


def _ffmpeg_runtime_dir(engine_python: str) -> str:
    """一个这套 torchcodec 认得的 FFmpeg 库目录,没有就返回空串。

    **系统那份排在最前**:它通常是最新的,而新版 torchcodec 恰好也支持到最新的 FFmpeg ——
    先看系统的,才不会为了一个能解决的问题去回退到老版本库。系统那份太新时(torchcodec 还没
    跟上)才退到 Homebrew 的版本化 formula,它们与主 ffmpeg 并存,不影响渲染用的那一份。
    """
    if sys.platform != "darwin":
        return ""
    majors = _torchcodec_avutil_majors(engine_python)
    if not majors:
        return ""
    roots: list[Path] = []
    for base in _ffmpeg_lib_roots():
        roots.append(base / "ffmpeg" / "lib")
        # formula 名字不等于里面装的版本(这台机器上 `ffmpeg@8` 装的是 libavutil.61),
        # 所以只拿它们当候选目录,版本一律看盘上的 libavutil。
        roots.extend(sorted((entry / "lib" for entry in base.glob("ffmpeg@*")), reverse=True))
    for major in majors:
        for lib in roots:
            if (lib / f"libavutil.{major}.dylib").exists():
                return str(lib)
    return ""


def weights_for(engine_id: str, text: str, model_id: str = "") -> dict[str, str]:
    """这次合成该用**哪一份权重**。

    只有 F5 有多份(按语言分,见 ai/runtime/f5_models);别的引擎一份权重走天下,返回空字典。
    判断放在这个文件里,是因为"哪个引擎有多份权重"本身就是关于引擎的知识 —— 它属于目录,
    不属于调用方(棘轮 test_engine_capabilities_live_in_one_table 盯的正是这个)。

    `model_id` 是**用户明说的**那一份,优先于按文字自动挑。这不是可选的锦上添花:法语、德语、
    西班牙语、意大利语、芬兰语都写拉丁字母,没有任何字符能证明"这是法语而不是英语"——
    自动挑永远挑不中它们,只能由人来说。
    """
    if engine_id != "f5-tts":
        return {}
    from app.ai.runtime import f5_models
    from app.ai.runtime.tts_language import detect_script

    explicit = f5_models.get(model_id) if model_id else None
    chosen = explicit if explicit is not None and f5_models.installed(explicit) else f5_models.for_language(detect_script(text))
    # 给 worker 的是**本地**相对路径(每个模型在自己的子目录里),不是仓库内路径。
    return {"checkpoint": chosen.local_checkpoint, "vocab": chosen.local_vocab} if chosen is not None else {}


def _worker_env(engine_python: str = "") -> dict[str, str]:
    """Env for the TTS worker subprocess: point HuggingFace at the configured
    mirror so first-use model downloads work (e.g. hf-mirror in CN), and pass the
    resolved Fish Speech source-checkout + weights dirs the worker runs from."""
    from app.ai.runtime import config as tts_config

    cfg = tts_config.get()
    env = dict(os.environ)
    env["HF_ENDPOINT"] = cfg.hf_endpoint
    # 下载跑在 worker 子进程里,它得知道这一次走哪条路 —— ModelScope 不是 HF 兼容端点,
    # HF_ENDPOINT 那一套对它无效,得换一个客户端。
    env["OPEN_STUDIO_MODEL_SOURCE"] = effective_source(cfg.engine, cfg.source)
    if cfg.resolved_fish_repo:
        env["OPEN_STUDIO_FISH_REPO_DIR"] = cfg.resolved_fish_repo
    if cfg.resolved_fish_model:
        env["OPEN_STUDIO_FISH_MODEL_DIR"] = cfg.resolved_fish_model
    # F5 走 ModelScope 时权重落在这里,worker 据此显式指给 F5TTS。
    env["OPEN_STUDIO_F5_MODEL_DIR"] = str(tts_config.MANAGED_F5_MODEL)
    # 让 torchcodec 找得到一份它认得的 FFmpeg。排在最前:dlopen 按这个顺序找,而系统里那份
    # 太新的正是加载不上的那个。找不到就什么都不做 —— 那种机器上错误信息会说清楚要装什么。
    ffmpeg_lib = _ffmpeg_runtime_dir(engine_python) if engine_python else ""
    if ffmpeg_lib:
        for key in ("DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"):
            existing = env.get(key, "")
            env[key] = f"{ffmpeg_lib}:{existing}" if existing else ffmpeg_lib
    return env


def candidate_pythons(engine_id: str) -> list[Path]:
    """探测顺序:用户显式覆盖 → **这个引擎自己的** venv → 本进程解释器。

    托管 venv 排在自动位:用户点过「下载」之后就该直接可用,不必再去设置里填路径——
    那个输入框只是留给"我自己装好了、想用我的环境"的高级用法。

    分开之前那个共用 venv **不在这里** —— 它由 `tts_config.migrate_shared_venv()` 一次性
    搬到它实际服务的引擎名下。留着当候选就是两条路并存,而两条路正是这次的病根。
    """
    from app.ai.runtime import config as tts_config

    candidates: list[Path] = []
    configured = tts_config.get().python_path
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(tts_config.managed_venv_python(engine_id))
    # 探测要**执行**候选解释器。打包版里"自己"是应用的 exe —— 拿它探等于再起一个后端
    # (Windows 上真的会撞在 8800 上),所以冻结时这里什么都不加。
    mine = interpreter.self_python()
    if mine:
        candidates.append(Path(mine))
    return candidates


def _probe_code(engine_id: str) -> str | None:
    """一行 Python:把**合成真正 import 的那几个模块**导一遍。资源不齐时返回 None。

    此前 fish 探的是 `import fish_speech`(一个空的 __init__,永远成功),f5 探的是
    `import f5_tts`(同理)。于是设置页说「已就绪」,而一点合成就 ModuleNotFoundError。
    """
    engine = _BY_ID.get(engine_id)
    imports = engine.imports if engine else ()
    if not imports:
        return None
    body = "; ".join(f"import {module}" for module in imports)
    if engine_id != "fish-speech":
        return body
    from app.ai.runtime import config as tts_config

    cfg = tts_config.get()
    repo, model = cfg.resolved_fish_repo, cfg.resolved_fish_model
    if not repo or not model:
        return None
    # fish_speech 和 tools 都在源码检出里,不是 pip 包 —— 先把它挂上 sys.path。
    return f"import sys; sys.path.insert(0, {repo!r}); {body}"


@lru_cache(maxsize=8)
def _resolve_engine_python(engine_id: str) -> str | None:
    """探测本身。**只有这一处**会去起子进程试 import。

    带缓存是因为它不便宜:每个候选解释器一次子进程,最长各等两分钟。而配音面板、设置页、
    引擎列表都要问这个问题 —— 不缓存的话,光是打开一次面板就能起好几个 python。
    装完引擎之后由 `clear_runtime_probes()` 作废,答案不会停在"装之前"。
    """
    code = _probe_code(engine_id)
    if code is None:  # 依赖的资源(fish 检出/权重)不齐,谈不上就绪
        return None
    for python in candidate_pythons(engine_id):
        if not python.is_file():
            continue
        try:
            probe = run_logged([str(python), "-c", code], capture_output=True, timeout=120, what="克隆引擎探测", level=logging.DEBUG)
        except (subprocess.SubprocessError, OSError):
            continue
        if probe.returncode == 0:
            return str(python)
    return None


#: 探测过的结果。**列状态只读这里,永远不等** —— 探测要起子进程 import torch,而列状态是
#: 一次纯读的请求。这个仓库修过同一个形状:列供应商曾经在返回前替过期令牌去联网刷新
#: (见 test_listing_connections_does_not_block),判据是"这个接口要回答的问题,不需要出网
#: 就能回答";这里是同一句话的另一半 —— 不需要起子进程就能回答。
_PROBED: dict[str, str | None] = {}
_PROBING: set[str] = set()
_PROBE_LOCK = threading.Lock()
#: 探测的**代次**。`clear_runtime_probes()` 让它 +1,于是所有在飞的探测都成了上一代。
#:
#: 少了它有两个后果,都真实发生过:
#:   · `_PROBING` 不清 —— 上一代那条还挂着"正在探测",新一代的探测**永远起不来**,
#:     状态卡在「还没测过」;
#:   · 就算清了,上一代那条跑完还是会把**过期答案写回缓存**,覆盖掉新探出来的那个。
#: 所以判据不是"清空",是"只有当代的才算数"。
_PROBE_GENERATION = 0


def probe_in_background(engine_id: str) -> None:
    """确保这个引擎被探过一次。已经在探的不重复起线程。"""
    with _PROBE_LOCK:
        if engine_id in _PROBED or engine_id in _PROBING:
            return
        _PROBING.add(engine_id)
        generation = _PROBE_GENERATION

    def run() -> None:
        python = None
        try:
            python = _resolve_engine_python(engine_id)
        finally:
            with _PROBE_LOCK:
                # 上一代的结果一律丢掉 —— 它探的是改配置之前那套环境。
                if generation == _PROBE_GENERATION:
                    _PROBING.discard(engine_id)
                    _PROBED[engine_id] = python

    threading.Thread(target=run, daemon=True).start()


def runtime_status(engine_id: str) -> tuple[bool, bool]:
    """(跑得起来吗, 测过了吗)。**不等** —— 没测过就顺手在后台起一次,先把已知的给出去。

    "还没测过"和"测过了、跑不起来"是两回事。把前者说成后者,就是拿一个未知冒充一个结论:
    界面会写着「未就绪」,而其实只是还没问。
    """
    with _PROBE_LOCK:
        if engine_id in _PROBED:
            return bool(_PROBED[engine_id]), True
    probe_in_background(engine_id)
    return False, False


def refresh_runtime_status(engine_id: str) -> bool:
    """**现在就探一次**并记下来。装完引擎之后调它 —— 否则下一次列状态还得等后台那一轮,
    用户刚点完「下载」看到的仍是"正在检查"。测试里也用它拿一个确定的答案。
    """
    # 走**公开的**那个:它是这件事唯一的入口,打桩/替换也都替它(私有的那个只是缓存层)。
    python = resolve_engine_python(engine_id)
    with _PROBE_LOCK:
        _PROBED[engine_id] = python
    return bool(python)


def resolve_engine_python(engine_id: str) -> str | None:
    """能真的跑这个引擎的解释器,**没有就是没有**。

    这里曾经在找不到时回退到后端自己的解释器,注释写着"worker 的占位音在那儿也能生成一个
    合法 wav"—— 而那正是用户说的「根本克隆不了」:合成照跑、任务报成功、素材库里多一段正弦音。
    一个跑不了的引擎的正确答案是 None,不是"随便找个解释器凑合"。

    这也是**唯一**一处回答"哪个解释器能跑这个引擎"。此前 `probe_interpreter` 自己又实现了
    一遍:设置页问的是它,合成问的是另一个带兜底的 —— 同一个问题两处实现,于是两个答案。
    """
    return _resolve_engine_python(engine_id)


def clear_runtime_probes() -> None:
    """装完引擎、改完解释器路径之后叫一声,否则答案会停在"装之前"。"""
    # getattr:测试会把探测换成一个普通函数(没有 cache_clear)。作废缓存是清理动作,
    # 不该因为"被替换过"就炸。
    global _PROBE_GENERATION
    getattr(_resolve_engine_python, "cache_clear", lambda: None)()
    with _PROBE_LOCK:
        _PROBED.clear()
        # 在飞的那些连同它们的结果一起作废,位置也让出来 —— 否则新的探测起不来。
        _PROBING.clear()
        _PROBE_GENERATION += 1


def probe_interpreter(engine_id: str) -> dict[str, Any]:
    """设置页要的形状。答案来自上面那一处,不另算一遍。

    **不等探测。** 它要起一个子进程 import f5_tts(连带 torch),实测 7 秒 —— 而这是
    「打开设置页」和「点保存」都必经的一次请求:打开时表单要等它回来才填得上值(下拉于是
    一直显示默认值),保存更糟,PUT 里刚 clear_runtime_probes() 过,于是**每次**都重探一遍,
    按钮转四秒。真机反馈就是「下载源加载很久」「保存点了 loading 很久」。

    「还没测过」和「测过了、跑不起来」是两回事(同 runtime_status)——所以多给一个
    `worker_checked`,而不是把未知说成"没就绪"。
    """
    with _PROBE_LOCK:
        if engine_id in _PROBED:
            python = _PROBED[engine_id]
            return {"worker_ready": bool(python), "worker_python": python or "", "worker_checked": True}
    probe_in_background(engine_id)
    return {"worker_ready": False, "worker_python": "", "worker_checked": False}


# ---------------------------------------------------------------------------
# Live download state
# ---------------------------------------------------------------------------
@dataclass
class _Live:
    status: str = "idle"
    downloaded: int = 0
    total: int = 0
    speed: float = 0.0
    eta: float | None = None
    message: str = ""
    #: message 是 key 时的模板参数(见 core/i18n.t)。翻译在出口做,这里只负责把值带出来。
    params: dict[str, str] = field(default_factory=dict)


class _Store:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._live: dict[str, _Live] = {}

    def get(self, key: str) -> _Live | None:
        with self._lock:
            live = self._live.get(key)
            return None if live is None else _Live(**live.__dict__)

    def set(self, key: str, live: _Live) -> None:
        with self._lock:
            self._live[key] = live

    def clear(self, key: str) -> None:
        with self._lock:
            self._live.pop(key, None)

    def downloading(self) -> bool:
        with self._lock:
            return any(live.status == "downloading" for live in self._live.values())


_store = _Store()


def _source_fields(engine: TtsEngine) -> dict[str, Any]:
    """Fish Speech needs a source checkout separate from its weights — report that piece on
    its own so the card can show it. f5-tts needs no source (pip package)."""
    if engine.id != "fish-speech":
        return {"needs_source": False, "source_ready": False, "source_dir": ""}
    from app.ai.runtime import config as tts_config

    repo = tts_config.get().resolved_fish_repo
    return {"needs_source": True, "source_ready": bool(repo), "source_dir": repo}


def _download_source(engine_id: str) -> str:
    """这个引擎此刻**实际**会走的下载源(把库里存的值落到它支持的那几个上)。"""
    from app.ai.runtime import config as tts_config

    return effective_source(engine_id, tts_config.get().source)


#: 这次下载**真正要取的东西**:(源, 仓库, 文件通配)。通配为空表示整仓。
#:
#: 体积必须按这个算,而不是按仓库总量:AI-ModelScope/F5-TTS 整仓有四份 1.35 GB 的检查点
#: (不同版本),而我们只要其中一份 —— 拿整仓当分母,进度条会永远走不到头。
def download_parts(engine_id: str, source: str) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """这一次下载会从哪些源、哪些仓库、取哪些文件。

    和 `tts_worker.fetch_f5_weights` / `fetch_fish_weights` 是同一件事的两面 —— 那边负责取,
    这边负责说清楚"要取多少"。两边一起改,否则分母又和实际下的东西对不上。
    """
    if engine_id == "f5-tts":
        # 声码器 vocos 只在 HuggingFace 上(ModelScope 三个命名空间都是 404),
        # 所以无论主源选谁,它这一份都走 HF。
        vocoder = ("hf" if source == "modelscope" else source, "charactr/vocos-mel-24khz", ())
        if source == "modelscope":
            return (
                ("modelscope", "AI-ModelScope/F5-TTS",
                 ("F5TTS_v1_Base/model_1250000.safetensors", "F5TTS_v1_Base/vocab.txt")),
                vocoder,
            )
        return ((source, "SWivid/F5-TTS", ("F5TTS_v1_Base/*",)), vocoder)
    if engine_id == "fish-speech":
        return ((source if source == "modelscope" else source, "fishaudio/s2-pro", ()),)
    return ()


def measured_total(engine: TtsEngine, source: str, *, blocking: bool = False) -> tuple[int, bool]:
    """(要下的总字节, 这个数是不是估算)。

    目录里那个 `expected_bytes` 是**当初抄下来的快照**,而它同时当着三样东西用:卡片上给用户
    看的体积、进度条的分母、以及"装好了没有"的判据。上游改一次文件它就失准 —— F5 走
    ModelScope 实际是 1.40 GB,而写死的是 1.5 GB,于是进度走到 93% 就完成了。

    所以先问源。问不到(离线、源变了、接口改了)就退回估算,并**说出它是估算** ——
    一个猜出来的数字装成实测值,比承认不知道更糟。

    `blocking=False` 时只读缓存、缺了在后台补:列卡片是每开一次设置页都跑的路径,不能让它
    等网络(同一个教训在 ai/model_catalog 上吃过一次)。下载正要开始时用 blocking=True,
    那时用户本来就在等。
    """
    parts = download_parts(engine.id, source)
    if not parts:
        return engine.expected_bytes, True
    total = 0
    for part_source, repo, patterns in parts:
        files = (remote_size.files_for if blocking else remote_size.cached_files)(part_source, repo)
        size = remote_size.total_bytes(files, patterns)
        # 任何一部分问不到,整个总量就不是实测的 —— 报一个残缺的总数比报估算更糟:
        # 它看起来精确,而进度条会提前走满。
        if size is None:
            return engine.expected_bytes, True
        total += size
    return total, False


def _status_dict(engine: TtsEngine) -> dict[str, Any]:
    from app.ai.runtime import config as tts_config

    live = _store.get(engine.id)
    source = effective_source(engine.id, tts_config.get().source)
    total, estimated = measured_total(engine, source)
    base = {"id": engine.id, "label": engine.label, "detail": engine.detail,
            "expected_bytes": total, "total_is_estimate": estimated,
            "sources": list(sources_for(engine.id)),
            "supports_speed": engine.supports_speed,
            **_source_fields(engine)}
    if live is not None and live.status == "downloading":
        # **实测越过估计值 = 这个估计已经被证伪**,那一刻起就不该再拿它当分母:界面会画出一根
        # 满的条(用户截图里是 `5.2 GB / 4.0 GB`、100%,而它还在下),而"满"说的是"下完了"。
        # 和装运行环境那一阶段同一条规矩:没有诚实的分母就不报分母,只报下了多少、在做什么。
        total = 0 if live.total and live.downloaded > live.total else live.total
        return {**base, "status": "downloading", "downloaded_bytes": live.downloaded,
                # **不回落到权重大小**:装运行环境那一阶段没有可报的总量(跑的是 pip),
                # 顶一个权重的字节数上去,界面就会画出"0 MB / 1.5 GB"这种量错了东西的进度条。
                # 光在 _Live 里置 0 不够 —— 这个 `or` 会把它填回来,转写那边就是这么被填回来的。
                "total_bytes": total, "speed_bps": live.speed,
                "eta_seconds": live.eta, "message": live.message, "message_params": live.params}
    if live is not None and live.status == "failed":
        return {**base, "status": "failed", "downloaded_bytes": _measure(engine),
                "total_bytes": total, "message": live.message, "message_params": live.params}
    if _is_installed(engine):
        # 权重齐了不等于跑得起来:pip 包可能压根没装(权重是别的工具下的,或者托管 venv 被删了)。
        # 此前这里一律说「已安装,声音克隆可用」,而合成那边探测解释器失败 —— 页面说可用,
        # 一点就说不可用。两句话得出自同一次判断。
        ready, checked = runtime_status(engine.id)
        return {**base, "status": "installed", "runtime_ready": ready, "runtime_checked": checked,
                "downloaded_bytes": _measure(engine), "total_bytes": total,
                "message": "modelMsg_checkingRuntime" if not checked else "modelMsg_cloneReady" if ready
                else "modelMsg_weightsNoRuntime"}
    # runtime_ready 说的是"跑不跑得起来",和"权重下没下"是两件事 —— 别因为在"未下载"这条
    # 分支上就无条件写 False。装好了运行环境、只差权重,是一个该说清楚的状态。
    ready, checked = runtime_status(engine.id)
    return {**base, "status": "missing", "runtime_ready": ready, "runtime_checked": checked, "downloaded_bytes": _measure(engine),
            "total_bytes": total,
            "message": ("modelMsg_checkingRuntime" if not checked else
                        "modelMsg_runtimeNoWeights" if ready else "modelMsg_notDownloaded")}


def list_status() -> list[dict[str, Any]]:
    return [_status_dict(engine) for engine in CATALOG]


def get_status(engine_id: str) -> dict[str, Any]:
    engine = _BY_ID.get(engine_id)
    if engine is None:
        raise KeyError(engine_id)
    return _status_dict(engine)


def is_installed(engine_id: str) -> bool:
    engine = _BY_ID.get(engine_id)
    return bool(engine and _is_installed(engine))


#: HuggingFace 连不上时抛的那几个名字。命中就多说一句 —— 这台机器上镜像下不动、
#: 而直连官方是通的,而用户没有任何线索能想到去动「模型下载源」。
_HUB_UNREACHABLE = ("LocalEntryNotFoundError", "ConnectionError", "ReadTimeout", "ProxyError",
                    "check your connection", "Max retries exceeded")


def _explain_failure(stderr: str) -> str:
    """把子进程的最后一句话变成卡片上那句话。

    此前这里是 `stderr or "下载未完成,可能引擎未安装"` —— 而 worker 把异常吞了、退出码 0、
    stderr 空,于是永远走后半句。那是一句**猜测**,还猜错了方向:用户会去重装引擎,
    而真正坏掉的是下载源。
    """
    # 先去掉终端颜色码:子进程以为自己在终端里,而这句话的去处是浏览器。
    text = strip_ansi(stderr or "").strip()
    unknown = "下载没有完成,而子进程没有留下原因 —— 请重试一次;若仍然如此请反馈。"
    if not text:
        return unknown
    # **不取最后一行。** huggingface_hub 的 tqdm 进度条写在 stderr 上,下完就停在那儿,
    # 于是最后一行是 `Downloading: 100%|██████| 1/1 [00:00<00:00, 1.39file/s]` ——
    # 用户看到的报错是一根进度条。判据在 core/text.blame_line 一处(那里记着这三次发作)。
    # **fallback 不能是原文**:输出全是进度条时,那等于把进度条又端了一遍(就是这次的 bug)。
    # 说不出原因就说不出来。
    last = blame_line(text)
    if not last:
        return unknown
    if any(marker in text for marker in _HUB_UNREACHABLE):
        from app.ai.runtime import config as tts_config

        endpoint = tts_config.get().hf_endpoint
        # 截断只截**错误本身**,不截后面那半句 —— 那是整条消息里唯一能行动的部分。
        return (
            f"连不上模型下载源({endpoint}):{_clip(last, 220)}"
            " —— 在上面的「模型下载源」换一个(镜像下不动时,官方直连往往反而是通的)再重试。"
        )
    return _clip(last, 400)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}…"


def forget_failures() -> None:
    """丢掉所有"失败"状态,不动正在下的那些。

    改了下载源 / 解释器之后叫一声:上一次失败说的是**改之前**那套配置,而它长得像当前状态 ——
    用户照着它去排查一个已经不存在的设置(实测:源已经换成 ModelScope,卡片还在说 hf-mirror)。
    """
    for engine in CATALOG:
        live = _store.get(engine.id)
        if live is not None and live.status == "failed":
            _store.clear(engine.id)


def _fmt_eta(seconds: float | None) -> tuple[str, dict[str, str]]:
    """(key, 参数)—— **不拼句子**:拼进去那句话就只有一种语言了(见 core/i18n.t)。"""
    if not seconds or seconds <= 0:
        return "", {}
    m, s = divmod(int(seconds), 60)
    return ("dlMsg_etaMinutes", {"m": str(m), "s": f"{s:02d}"}) if m else ("dlMsg_etaSeconds", {"s": str(s)})


def start_download(engine_id: str) -> dict[str, Any]:
    engine = _BY_ID.get(engine_id)
    if engine is None:
        raise KeyError(engine_id)
    if _is_installed(engine):
        return _status_dict(engine)
    # **并行是允许的。** 每个引擎有自己的 venv、自己的权重目录,下载跑在各自的一次性子进程里
    # (不共用常驻进程),所以两个引擎同时装不会互相弄坏 —— 只是抢带宽和磁盘。
    # 此前这里拒绝一切并发,理由是两个引擎共用一个 venv(装一边弄坏另一边);venv 后来按引擎
    # 拆开了,那个理由就没了,而限制留了下来。
    live = _store.get(engine.id)
    if live is not None and live.status == "downloading":
        raise RuntimeError(f"{engine.label} 已经在下载中")
    _store.set(engine.id, _Live(status="downloading", message="dlMsg_preparing"))
    threading.Thread(target=_run_download, args=(engine.id,), daemon=True).start()
    return _status_dict(engine)


_FISH_SOURCE_URL = "https://github.com/fishaudio/fish-speech"


def ensure_engine_runtime(engine_id: str) -> None:
    """确保托管 venv 存在、且装好了该引擎的依赖。已就绪则直接返回。

    这一步的存在,就是为了让用户**不必**去设置里指定 Python 解释器:点「下载」时由后端把环境
    建好。重的依赖(torch 等 2.5–3.5GB)落在用户数据目录而不是安装包里——预装会让安装包涨到
    约 4GB,而多数用户根本不用声音克隆。

    失败一律抛 RuntimeError 并带上可读原因;调用方把它落到下载状态上显示给用户。
    """
    from app.ai.runtime import config as tts_config

    engine = _BY_ID[engine_id]
    if not engine.pip_requirements:
        return
    # 已经有解释器能 import 它了(托管 venv 装过,或用户自带环境)→ 什么都不用做。
    if probe_interpreter(engine_id)["worker_ready"]:
        return

    # **装,一律进这个引擎自己的目录。** 共用的那个只在探测里读,不再往里装新东西 ——
    # 只要还有一条路会往里装,"装一边弄坏另一边"就没消除。
    venv_dir = tts_config.managed_venv_dir(engine_id)
    venv_python = tts_config.managed_venv_python(engine_id)
    if not venv_python.is_file():
        base = interpreter.base_python()
        if not base:
            raise RuntimeError(
                "找不到可用于创建运行环境的 Python。请重装应用,或在设置里手动指定一个 TTS 解释器。"
            )
        _store.set(engine_id, _Live(status="downloading", message="dlMsg_creatingRuntime"))
        venv_dir.parent.mkdir(parents=True, exist_ok=True)
        result = run_logged(
            [base, "-m", "venv", str(venv_dir)],
            capture_output=True, text=True, timeout=600, what="创建克隆运行环境")
        if result.returncode != 0 or not venv_python.is_file():
            raise RuntimeError(f"创建运行环境失败:{blame_line(result.stderr or result.stdout, fallback='没有留下原因')}")

    _store.set(
        engine_id,
        # 这一阶段**不报字节**:跑的是 pip(装 torch 等),它一个字节都不会落进权重缓存,
        # 而进度是按那个目录的增长算的。借用权重的 1.5GB 当分母,结果就是永远 0 MB / 1.5 GB。
        # 两件事量纲不同,就别共用一个进度条 —— 只报"在做哪一步"。
        _Live(status="downloading", message="dlMsg_installingDeps", params={"engine": engine.label}),
    )
    # 装到托管 venv 里。超时给足 —— torch 在慢网络下很久。
    # pip 镜像来自设置页(与「模型下载源」分开:那个管 HF 权重,这个管 Python 包)。
    # 直连 PyPI 拉 2.5–3.5GB 在国内常常慢到不可用,所以这一项值得单独可切。
    try:
        pip_install.install(
            venv_python,
            engine.pip_requirements,
            what="安装克隆运行依赖",
            index_url=tts_config.get().pip_index_url,
            env=_worker_env(),
        )
    except pip_install.PipInstallError as exc:
        raise RuntimeError(f"安装 {engine.label} 运行依赖失败:{exc}") from exc


def _ensure_fish_source() -> None:
    """Clone the official Fish Speech source into the managed dir (its ``fish_speech`` package
    and ``tools.server.*`` modules aren't on PyPI, so real synthesis needs the checkout).
    No-op if already present; raises with a readable hint on failure."""
    from app.ai.runtime import config as tts_config

    repo = tts_config.MANAGED_FISH_REPO
    if (repo / tts_config.FISH_REPO_MARKER).is_file():
        return
    # 同上:拉的是 git 源码,不是权重 —— 没有分母就别摆一个。
    _store.set("fish-speech", _Live(status="downloading", message="dlMsg_fetchingFishSource"))
    repo.parent.mkdir(parents=True, exist_ok=True)
    if repo.is_dir() and any(repo.iterdir()):
        # A prior half-clone — wipe so `git clone` into it succeeds.
        import shutil

        shutil.rmtree(repo, ignore_errors=True)
    try:
        result = run_logged(
            ["git", "clone", "--depth", "1", _FISH_SOURCE_URL, str(repo)],
            capture_output=True, text=True, timeout=600, what="拉取 Fish Speech 源码")
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 git,无法拉取 Fish Speech 源码") from exc
    except subprocess.SubprocessError as exc:
        raise RuntimeError(f"拉取 Fish Speech 源码失败:{exc}") from exc
    if result.returncode != 0 or not (repo / tts_config.FISH_REPO_MARKER).is_file():
        raise RuntimeError(f"拉取 Fish Speech 源码失败:{blame_line(result.stderr, fallback='git 没有说明原因')}")


def _download_python(engine_id: str) -> str:
    """First existing candidate interpreter — the TTS env that has huggingface_hub, used to
    run the weights snapshot. 一个都没有就退回"能建 venv 的那个"(打包版里是随包带的解释器);
    再没有就是真的没有,让调用方拿到一个说得清的失败,而不是拿应用自己去跑下载。"""
    for python in candidate_pythons(engine_id):
        if python.is_file():
            return str(python)
    return interpreter.base_python()


def _run_download(engine_id: str) -> None:
    """Wrapped so the "downloading" flag can never outlive the thread that set it.

    start_download refuses while _store.downloading() is true. Anything escaping the body
    below — a worker that cannot be spawned, a disk error, a bug — used to leave that flag
    set for the life of the process, so EVERY later download was rejected with
    「已有模型正在下载」 and only a restart cleared it.
    """
    try:
        _download_body(engine_id)
    except Exception as exc:  # noqa: BLE001 — the flag must be released whatever happened
        logger.exception("model download failed")
        _store.set(engine_id, _Live(status="failed", message=str(exc)[:400]))


def _download_body(engine_id: str) -> None:
    engine = _BY_ID[engine_id]
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    # 先备好运行环境(建 venv + 装引擎依赖),再拉权重。顺序不能反:权重是用那个环境里的
    # huggingface_hub 拉的,环境不在就只能退回本后端解释器,拉下来也跑不了合成。
    ensure_engine_runtime(engine_id)
    output_path = settings.data_dir / f"tts-warmup-{engine_id}.wav"

    env = _worker_env(resolve_engine_python(engine_id) or "")
    progress_dir: Path | None = None
    if engine_id == "fish-speech":
        from app.ai.runtime import config as tts_config

        try:
            _ensure_fish_source()
        except RuntimeError as exc:
            logger.warning("拉取 %s 源码失败:%s", engine.id, exc)
            _store.set(engine.id, _Live(status="failed", message=str(exc)[:400]))
            return
        # Snapshot weights into the managed model dir (flat: codec.pth at root) and measure it
        # for live progress — resolved_fish_model won't resolve until codec.pth lands.
        progress_dir = tts_config.MANAGED_FISH_MODEL
        progress_dir.mkdir(parents=True, exist_ok=True)
        env["OPEN_STUDIO_FISH_MODEL_DIR"] = str(progress_dir)
        python = _download_python(engine_id)
    else:
        # 预热是**去下权重**:优先能跑引擎的那个解释器,没有就退到第一个存在的候选
        # (装了 f5-tts 但还没下权重时,它就是那一个)。跑不起来由预热自己的状态去报。
        python = resolve_engine_python(engine.id) or _download_python(engine.id)

    def measure() -> int:
        return _dir_size(progress_dir) if progress_dir is not None else _measure(engine)

    started = time.monotonic()
    last_bytes = measure()
    proc = popen_text(
        [python, str(WORKER_PATH), str(output_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )
    assert proc.stdin is not None
    proc.stdin.write(json.dumps({"action": "warmup", "engine": engine.id}))
    proc.stdin.close()
    # Drain both pipes while polling — an undrained one fills, the child blocks writing it,
    # poll() never returns, and the download appears frozen forever. See ChildProcess.
    child = ChildProcess(proc)
    threading.Thread(target=lambda: [None for _ in child.raw_lines()], daemon=True).start()

    # 速度按**最近一段**算,不是按最近 1.5 秒:下载器成块写盘,单窗口读数会在 0 和几百 MB/s
    # 之间跳,而 ETA 在跳到 0 的那一瞬就消失 —— 用户看到的那一眼恰好是 0 的那一眼。
    rate = DownloadRate()
    rate.update(last_bytes, at=started)
    # **分母问源要,不用目录里那个写死的估算。** 用户已经在等这次下载了,所以这里可以阻塞去问
    # (超时 6 秒);问不到就退回估算 —— 那正是此前一直在用的数,不会更糟。
    total_bytes, _estimated = measured_total(engine, _download_source(engine.id), blocking=True)
    while proc.poll() is None:
        time.sleep(_POLL_SECONDS)
        now = time.monotonic()
        current = measure()
        speed = rate.update(current, at=now)
        eta = rate.eta(remaining=max(0, total_bytes - current))
        elapsed = int(now - started)
        key, params = _fmt_eta(eta)
        if not key:
            key, params = "dlMsg_elapsed", {"m": str(elapsed // 60), "s": f"{elapsed % 60:02d}"}
        _store.set(engine.id, _Live(status="downloading", downloaded=current, total=total_bytes,
                                    speed=speed, eta=eta, message=key, params=params))

    stderr = child.finish(600)
    if engine_id == "fish-speech":
        # Managed dirs just changed on disk — drop the cached resolution so probe/synthesis
        # pick them up without a restart.
        from app.ai.runtime import config as tts_config

        tts_config.refresh()
    clear_runtime_probes()  # 刚装完,探测结果必须重算
    refresh_runtime_status(engine_id)  # 并且**现在**就算,别让用户对着"正在检查"再等一轮
    if _is_installed(engine):
        _store.clear(engine.id)
    else:
        # **完整输出落盘。** 界面上只放一句话,而排查要全文 —— 此前全文哪儿都没有(日志里也只
        # 留 1200 字符),于是"下载没有完成,而子进程没有留下原因"这种报错除了让用户重跑一遍
        # 并录屏之外无法诊断。装依赖那条路已经这么做了,这里是同一件事的第二处。
        # 判据本身也写进去。**子进程一切正常、而我们判它"没装好"时,原因全在判据里** ——
        # 真机上就是这一幕:两个文件都下完了、没有任何异常,而界面说"下载没有完成"。
        # 只留子进程的输出,等于把唯一有用的那部分排除在外。
        path = run_log.save(
            f"引擎 {engine.id} · 源 {_download_source(engine.id)}\n"
            f"{_install_verdict(engine)}\n\n{stderr or '(子进程什么都没说)'}\n",
            kind="worker", what=f"download-{engine.id}",
        )
        reason = _explain_failure(stderr)
        if path is not None:
            reason = f"{reason}\n完整日志:{path}"
        logger.warning("下载 %s 失败(完整输出见 %s):%s", engine.id, path, (stderr or "(空)")[-800:])
        _store.set(engine.id, _Live(status="failed", message=reason))
    for path in (output_path, Path(str(output_path) + ".json")):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = ["CATALOG", "list_status", "get_status", "start_download", "is_installed",
           "resolve_engine_python", "clear_runtime_probes", "sources_for", "effective_source"]
