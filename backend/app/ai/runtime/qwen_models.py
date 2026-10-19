"""Qwen3-TTS 的**模型**目录 —— 版本、文件、许可证、音色与语言,都钉在这一个地方。

为什么单成一个模块,而不是把几个常量塞进 `tts_models.CATALOG`:`TtsEngine` 回答的是「这个引擎
怎么装、怎么跑」,而这里回答的是「装的是**哪一版**权重、里面有哪几个文件、每个文件的 sha256 是
多少」。后者要能被测试逐项断言(不写会漂的 “latest”),也要能被下载那一路拿去当 revision ——
两件事放一张表里,改版本时总有一半会被忘掉。

**版本不是猜的**(2026-10 查证,链接在下面),全部钉死:

  ・release:Qwen3-TTS 于 2026-01-22 开源(0.6B/1.7B,12Hz tokenizer);
  ・HF 仓库:`Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`,commit `0c0e3051…`;
  ・ModelScope 同一个仓库的 revision 是另一套哈希(`ae999bce…`)—— 两个源各钉各的;
  ・权重 Apache-2.0;中文是官方首批 10 种语言之一;
  ・两个真正的大文件(model.safetensors / speech_tokenizer/model.safetensors)带 sha256,
    小 JSON/文本文件只有体积:它们由 commit 钉住,而给每个几 KB 的文件再抄一份哈希的收益
    抵不上抄错的风险。

体积按 HF 仓库的文件清单逐个加出来的(见 `files`),不是拍的。`expected_bytes` 只当问不到源时
的兜底 —— 卡片上的数字仍然优先问下载源(见 ai/runtime/remote_size)。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

#: 运行时目录里这个引擎的名字(worker / daemon / 下载都认它)。能力表里的 `builtin:qwentts`
#: 由 domain 层映射到这里(见 domain/voices/speech.LOCAL_SPEECH_ENGINES),两边不各写一份。
ENGINE_ID = "qwen-tts"

#: 权重落在哪(App 托管的用户数据目录)。**在这里定义、由 config 引用** —— 反过来的话
#: `config → tts_models → qwen_models → config` 就成环了(分层测试抓过)。
MANAGED_QWEN_MODEL = settings.data_dir / "tts" / "qwen3-tts-12hz-1.7b-customvoice"

#: 装进**这个引擎自己的**托管 venv 的依赖。qwen-tts 0.1.1 是 2026-02-06 的版本;它自己钉了
#: transformers==4.57.3 / accelerate==1.12.0。**不进后端 pyproject**:它带 torch/torchaudio 与
#: gradio,几 GB —— 和 F5/Fish 一样按需装进用户数据目录,而不是把安装包撑大。
PIP_REQUIREMENTS = ("qwen-tts==0.1.1", "modelscope")


@dataclass(frozen=True)
class QwenFile:
    """仓库里的一个文件。sha256 为空 = 只按存在性检查(小配置文件)。"""

    path: str
    size: int
    sha256: str = ""


@dataclass(frozen=True)
class QwenSpeaker:
    """模型自带的预置音色。`id` 是上游 `spk_id` 的小写形式,`label` 只给人看。"""

    id: str
    label: str
    #: 官方建议每种音色用它自己的母语,质量最好(当然它可以念全部 10 种语言)。
    native_language: str = ""


@dataclass(frozen=True)
class QwenTtsModel:
    id: str
    repo: str
    modelscope_repo: str
    #: 两个源各自的 revision(HF commit / ModelScope revision)。**不写 “latest”**。
    hf_revision: str
    modelscope_revision: str
    release_date: str
    release_url: str
    license: str
    languages: tuple[str, ...]
    files: dict[str, QwenFile]
    speakers: tuple[QwenSpeaker, ...]

    @property
    def total_bytes(self) -> int:
        return sum(item.size for item in self.files.values())

    @property
    def required_files(self) -> tuple[str, ...]:
        """少了任何一样都加载不起来:主模型、声码器、config。"""
        return ("model.safetensors", "speech_tokenizer/model.safetensors", "config.json")

    @property
    def release(self) -> str:
        """报告和卡片上说「哪一版」时用的那一句。"""
        return f"Qwen3-TTS-12Hz 1.7B CustomVoice ({self.release_date}, {self.hf_revision[:8]})"


#: 官方 10 种语言(中文在前 —— 这是这次接入必须支持的那一门)。
LANGUAGES = ("zh", "en", "ja", "ko", "de", "fr", "ru", "pt", "es", "it")

#: 9 个预置音色,顺序照官方模型卡的表格。
SPEAKERS: tuple[QwenSpeaker, ...] = (
    QwenSpeaker("vivian", "Vivian(女·明亮)", "zh"),
    QwenSpeaker("serena", "Serena(女·温柔)", "zh"),
    QwenSpeaker("uncle_fu", "傅叔叔(男·低沉)", "zh"),
    QwenSpeaker("dylan", "Dylan(男·京腔)", "zh"),
    QwenSpeaker("eric", "Eric(男·川渝)", "zh"),
    QwenSpeaker("ryan", "Ryan(男·英文)", "en"),
    QwenSpeaker("aiden", "Aiden(男·美音)", "en"),
    QwenSpeaker("ono_anna", "音乃安娜(女·日语)", "ja"),
    QwenSpeaker("sohee", "Sohee(女·韩语)", "ko"),
)

#: 没选音色时用第一个(和界面下拉显示的第一个一致)。
DEFAULT_SPEAKER = SPEAKERS[0].id

_BY_ID = {speaker.id: speaker for speaker in SPEAKERS}

#: 公开依据(报告里给的就是这几条):
#:  ・发布公告 https://qwen.ai/blog?id=qwen3tts-0115
#:  ・模型卡   https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
#:  ・技术报告 https://arxiv.org/abs/2601.15621
MODEL = QwenTtsModel(
    id="qwen3-tts-12hz-1.7b-customvoice",
    repo="Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    modelscope_repo="Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    hf_revision="0c0e3051f131929182e2c023b9537f8b1c68adfe",
    modelscope_revision="ae999bce1d1356e93686274865bc72744daab1a5",
    release_date="2026-01-22",
    release_url="https://qwen.ai/blog?id=qwen3tts-0115",
    license="Apache-2.0",
    languages=LANGUAGES,
    files={
        # 两个大文件是 LFS,pointer 里带着 sha256(和 ModelScope 的 Sha256 一致)。
        "model.safetensors": QwenFile(
            "model.safetensors", 3_833_402_552,
            "38b1d5971bdbd982b561cccec982669a53b0537c3cf5e9bd4778ed07bb2f5137",
        ),
        "speech_tokenizer/model.safetensors": QwenFile(
            "speech_tokenizer/model.safetensors", 682_293_092,
            "836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258",
        ),
        # 下面是加载要读的小文件。体积逐个照 HF 文件清单;内容由上面的 commit 钉住。
        "config.json": QwenFile("config.json", 4_908),
        "generation_config.json": QwenFile("generation_config.json", 245),
        "preprocessor_config.json": QwenFile("preprocessor_config.json", 127),
        "tokenizer_config.json": QwenFile("tokenizer_config.json", 7_344),
        "vocab.json": QwenFile("vocab.json", 2_776_833),
        "merges.txt": QwenFile("merges.txt", 1_671_839),
        "speech_tokenizer/config.json": QwenFile("speech_tokenizer/config.json", 2_336),
        "speech_tokenizer/configuration.json": QwenFile("speech_tokenizer/configuration.json", 76),
        "speech_tokenizer/preprocessor_config.json": QwenFile("speech_tokenizer/preprocessor_config.json", 234),
        "README.md": QwenFile("README.md", 57_846),
        ".gitattributes": QwenFile(".gitattributes", 1_519),
    },
    speakers=SPEAKERS,
)


def root() -> Path:
    """权重落在哪(App 托管的用户数据目录)。和模型目录分开:权重是几 GB,不是代码。"""
    return MANAGED_QWEN_MODEL


def installed() -> bool:
    """该有的文件都在盘上吗。**只看那几个必需的** —— README 之类缺了不影响加载,
    把它们算进来只会让一次网络抖动看起来像"整个模型没下"。"""
    base = root()
    return all((base / name).is_file() for name in MODEL.required_files)


def revision_for(source: str) -> str:
    """这个下载源上要取哪一版。两个源的 revision 不是同一个哈希,分开钉。"""
    return MODEL.modelscope_revision if source == "modelscope" else MODEL.hf_revision


def speaker(name: str) -> QwenSpeaker | None:
    """按名字认音色。大小写、空格、连字符都容得下(`Uncle_Fu` / `uncle fu` → `uncle_fu`)。"""
    key = (name or "").strip().lower().replace(" ", "_").replace("-", "_")
    return _BY_ID.get(key)


def speaker_id(name: str) -> str:
    """名字 → 上游认的 id;认不出就是空串(调用方决定是报错还是用默认)。"""
    found = speaker(name)
    return found.id if found is not None else ""


def voice_labels() -> dict[str, str]:
    """音色 id → 界面上的名字。音色下拉和素材名共用这一份。"""
    return {item.id: item.label for item in SPEAKERS}


#: `tts_language.detect_script` 报出来的硬证据 → 上游 `generate_custom_voice` 认的语言名。
#: 中文/英文以及法语、德语、西语等拉丁字母语言没有硬证据,交给 `Auto`(模型自己判)。
_LANGUAGE_NAMES = {"ja": "Japanese", "ko": "Korean", "ru": "Russian"}


def language_for(script: str) -> str:
    """这次合成该把 `language` 报成什么。**只报能确证的** —— 猜错了不如让模型自己判。"""
    return _LANGUAGE_NAMES.get(script, "Auto")
