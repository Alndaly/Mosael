"""sherpa-onnx 这一家:钉死的权重、按引擎探测、以及 worker 那一段的形状。

这一家与前两家(通过 funasr / whisperx 库下载)有一处根本不同:**权重是我们自己下的**。
于是"下哪一份"第一次成了我们要回答的问题,而这份文件钉的就是那个答案 —— URL 带提交哈希、
字节数当分母、sha256 在落盘前校验。所以下面大头在验那三个数字彼此自洽、以及不问源。
"""
from __future__ import annotations

import hashlib
import json
import re
import types
import wave
from pathlib import Path

import pytest

from app.ai.runtime import asr_models, remote_size
from app.ai.runtime.workers import asr


# ---------------------------------------------------------------------------
# 钉死的资产
# ---------------------------------------------------------------------------
def test_每个pin都是钉死的_URL带提交哈希() -> None:
    """**不能是分支名。** `/resolve/main/...` 指向的是"此刻的 main",而上游推一次文件
    我们下的就是另一份了 —— 那时 sha256 会不匹配(下载当场失败),或者更糟:我们在没有 pin 的
    情况下拿到了一份没验过的权重。"""
    for one in asr_models._SHERPA_PINNED:
        assert re.search(r"/resolve/[0-9a-f]{40}/", one.url), one.url
        assert len(one.sha256) == 64 and re.fullmatch(r"[0-9a-f]{64}", one.sha256), one.sha256
        assert one.bytes > 0


def test_三个pin各自有唯一的角色() -> None:
    """worker 按 role 取文件,不按文件名猜(见 asr_models.PinnedFile.role)。"""
    roles = [one.role for one in asr_models._SHERPA_PINNED]
    assert sorted(roles) == ["model", "tokens", "vad"], roles


def test_分母等于要下的那几个文件() -> None:
    """`expected_bytes`(分母)和 `pinned`(要下什么)**必须对得上**。

    它们分开写就一定会有一天不一致,而症状是进度条永远走不满(分母算进了我们不下的东西)
    或者提前走满(分母算漏了) —— 见 remote_size 开头那段。
    """
    entry = asr_models._BY_ID["sherpa-onnx-sensevoice"]
    for sub in entry.sub_models:
        assert sub.pinned, "这一家应当是按 pin 下的"
        assert sub.expected_bytes == sum(one.bytes for one in sub.pinned)
    assert entry.expected_bytes == sum(one.bytes for one in asr_models._SHERPA_PINNED)


def test_落盘目录和找文件的目录是同一个() -> None:
    """取权重按 `sherpa_model_dir() + 文件名` 落,而"装好了没有/在不在"按 `cache_dir` 找 ——
    两个名字必须指同一个目录,不然会出现"下好了但界面说没有"(或反过来)。"""
    sub = asr_models._SHERPA_BUNDLE.sub_models[0]
    assert sub.cache_dir == asr_models.SHERPA_MODEL_DIR_NAME
    assert asr_models.pinned_target(asr_models._SHERPA_PINNED[0]) == (
        asr_models.sherpa_model_dir() / asr_models._SHERPA_PINNED[0].name)
    assert asr_models._find_sub_dir("sherpa-onnx", sub.cache_dir) == asr_models.sherpa_model_dir() \
        or not asr_models.sherpa_model_dir().is_dir()


def test_钉死的地址跟着模型源走(monkeypatch: pytest.MonkeyPatch) -> None:
    """**默认的模型源是 hf-mirror**,而那个人群里 huggingface.co 常常不可达 —— 下权重的地址
    必须跟着这个设置走,不然"选了 hf-mirror 照样连 huggingface"就是一次白等。

    路径一个字都不改:hf-mirror 是同一套路径的镜像,这也正是 pin 的 sha256 仍然成立的原因。
    """
    from app.ai.runtime import config as tts_config

    one = asr_models._SHERPA_PINNED[0]
    original = one.url
    assert original.startswith("https://huggingface.co/")

    def use(source: str):
        monkeypatch.setattr(tts_config, "get", lambda: tts_config.TtsRuntimeConfig(
            engine="", python_path="", source=source, fish_repo_dir="", fish_model_dir=""))

    use("hf-mirror")
    assert asr_models.pinned_url(one) == original.replace("https://huggingface.co", "https://hf-mirror.com")

    use("hf")
    assert asr_models.pinned_url(one) == original

    # ModelScope 不是 HF 兼容端点,这几个文件那边也没有 —— 选了它照样走 HF,而不是拼一个不存在的地址。
    use("modelscope")
    assert asr_models.pinned_url(one) == original


def test_钉死的体积不问源(monkeypatch: pytest.MonkeyPatch) -> None:
    """**不问源**:URL 指向具体一次提交,而源上"当前 revision"的大小恰恰可能不是我们要下的
    那一份。这里让问源直接炸,证明它一次都没被问。"""

    def explode(*_args, **_kwargs):
        raise AssertionError("钉死的资产不该去问源")

    monkeypatch.setattr(remote_size, "cached_files", explode)
    monkeypatch.setattr(remote_size, "files_for", explode)

    total, estimated = asr_models.measured_total(asr_models._BY_ID["sherpa-onnx-sensevoice"])

    assert estimated is False, "钉死的字节数是准确值,不是估算"
    assert total == 239_233_841 + 315_894 + 1_807_522


# ---------------------------------------------------------------------------
# 引擎登记与探测
# ---------------------------------------------------------------------------
def test_引擎登记在三处而三处是同一件事() -> None:
    """依赖、目录条目、本机引擎名单 —— 少一处,症状分别是"装不上"、"看不到"、"挑不中"。"""
    from app.domain.voices import transcription

    assert "sherpa-onnx" in asr_models.ENGINE_REQUIREMENTS
    assert [one.id for one in asr_models.CATALOG if one.engine == "sherpa-onnx"] == ["sherpa-onnx-sensevoice"]
    assert "sherpa-onnx" in transcription.LOCAL_ENGINES
    assert asr_models.entry_for_transcribe("sherpa-onnx").id == "sherpa-onnx-sensevoice"


def test_依赖里没有torch() -> None:
    """**快和轻的全部来源就是这一条。** 同一个权重跑在 onnxruntime 上而不是 PyTorch 上;
    哪天有人"顺手"把 torch 加回来,这一家就只剩一个好听的名字了。"""
    requirements = " ".join(asr_models.ENGINE_REQUIREMENTS["sherpa-onnx"]).lower()
    assert "torch" not in requirements, requirements
    assert requirements == "sherpa-onnx"


def test_探测用的是能import的那个名字(monkeypatch: pytest.MonkeyPatch) -> None:
    """引擎名同时是 pip 名(连字符合法)和 `import` 的目标(只能下划线)。

    写错的表现是"环境永远装不上":pip 装成功,探测还是 ModuleNotFoundError。
    """
    seen: list[list[str]] = []

    class Done:
        returncode = 0
        stdout = ""
        stderr = ""

    def capture(command, **_kwargs):
        seen.append([str(one) for one in command])
        return Done()

    monkeypatch.setattr(asr_models, "run_logged", capture)
    monkeypatch.setattr(asr_models, "candidate_pythons",
                        lambda engine: [Path("/fake/python")])
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    asr_models._resolve_python.cache_clear()
    try:
        assert asr_models._resolve_python("sherpa-onnx") == "/fake/python"
    finally:
        asr_models._resolve_python.cache_clear()

    assert any(cmd[-1] == "import sherpa_onnx" for cmd in seen), seen


def test_不在名单里的引擎照样是原来的写法() -> None:
    """`_import_name` 不能把 funasr / whisperx 改出别的名字来。"""
    assert asr_models._import_name("funasr") == "funasr"
    assert asr_models._import_name("whisperx") == "whisperx"
    assert asr_models._import_name("sherpa-onnx") == "sherpa_onnx"


# ---------------------------------------------------------------------------
# worker:分发
# ---------------------------------------------------------------------------
def test_分发认得第三个引擎() -> None:
    assert asr._RUNNERS["sherpa-onnx"] is asr.run_sherpa_onnx
    assert asr._WARMUPS["sherpa-onnx"] is asr.warmup_sherpa_onnx


def test_认不出的引擎当场说_不悄悄跑成别的() -> None:
    """此前是"funasr 否则 whisperx",于是一个写错的引擎名会**悄悄按 whisperx 跑起来** ——
    那种错误的表现是"转出来的是别的引擎的结果",比报错难查得多。"""
    with pytest.raises(ValueError):
        asr.execute_request({"provider": "not-an-engine", "action": "transcribe"})


def test_预热和转写要的是同一批文件() -> None:
    """funasr 那边的教训:两份构建逻辑各改各的,预热下的东西转写根本不用。
    这里只有一份(见 asr_models.sherpa_request),预热与转写只差一个 action。"""
    warm, run = asr_models.sherpa_request("warmup"), asr_models.sherpa_request("transcribe")
    assert warm["sherpa_files"] == run["sherpa_files"]
    assert warm["sherpa_dir"] == run["sherpa_dir"]
    assert (warm["action"], run["action"]) == ("warmup", "transcribe")


# ---------------------------------------------------------------------------
# 取权重(按 pin,验 sha256)—— **在宿主进程里取**
# ---------------------------------------------------------------------------
def _fake_stream(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> None:
    """把 RetryingClient 换成"回一段字节"的假客户端。

    这里换的是宿主那个客户端(app.core.http_retry.RetryingClient)—— 出站检查就装在这一层,
    所以这一换同时也说明:**取权重走的是那道闸**,不是 worker 里的 urllib。
    """

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self, _size: int = -1):
            yield payload

    class _Stream:
        def __enter__(self) -> _Response:
            return _Response()

        def __exit__(self, *_exc: object) -> None:
            return None

    class _Client:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def stream(self, _method: str, _url: str) -> _Stream:
            return _Stream()

    import app.core.http_retry as http_retry

    monkeypatch.setattr(http_retry, "RetryingClient", _Client)


def _pin(name: str, payload: bytes, *, role: str = "model") -> asr_models.PinnedFile:
    return asr_models.PinnedFile(name=name, role=role, url="https://example.invalid/x",
                                 bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())


def test_校验不过就不留文件(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """**先校验、再改成正式名。** 顺序反过来的话,一次断线就在盘上留下一个"名字对、内容截断"
    的模型,而下一轮"文件在,跳过"会直接放行它。"""
    _fake_stream(monkeypatch, b"not what we pinned")
    target = tmp_path / "model.onnx"
    one = asr_models.PinnedFile(name="model.onnx", role="model", url="https://example.invalid/x",
                                bytes=18, sha256="0" * 64)

    with pytest.raises(asr_models.RuntimeSetupError) as raised:
        asr_models._fetch_pinned(one, target)

    assert raised.value.key == "asrErr_weightChecksum"
    assert not target.exists(), "校验不过的东西不许留在正式名下"
    assert not target.with_name("model.onnx.part").exists(), "半截的也不留"


def test_校验过了才改成正式名(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"the real weights"
    _fake_stream(monkeypatch, payload)
    target = tmp_path / "model.onnx"

    asr_models._fetch_pinned(_pin("model.onnx", payload), target)

    assert target.read_bytes() == payload
    assert not target.with_name("model.onnx.part").exists()


def _small_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payloads: dict[str, bytes]):
    """一个按**小文件**钉死的条目 + 它落盘的目录。

    真的那几个 pin 是 239MB(测试里不写这么大的文件),而"齐了没有"这件事和文件多大无关 ——
    所以这里换成几百字节的 pin,验的是同一段逻辑。`pinned_target` 也指到这个临时目录,
    免得碰到跑测试的人机器上真的那份权重。
    """
    pins = tuple(asr_models.PinnedFile(
        name=name, role=role, url="https://example.invalid/x",
        bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        for name, (role, payload) in payloads.items())
    directory = tmp_path / "sherpa-onnx"
    directory.mkdir(exist_ok=True)
    entry = asr_models.ModelEntry(
        id="probe", engine="sherpa-onnx", label="l", detail="d",
        sub_models=(asr_models.SubModel(cache_dir="sherpa-onnx", repo="r", source="hf",
                                        expected_bytes=sum(one.bytes for one in pins), pinned=pins),),
        request={})
    monkeypatch.setattr(asr_models, "pinned_target", lambda one: directory / one.name)
    return entry, directory, pins


def test_齐了就不发请求(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """**已经对了就一个请求都不发。** 这是"每次转写都先走一遍"的那条路 —— 它每说一句话都要给
    239MB 发一次请求或者算一次哈希,而那份代价会落在每一次听写上。"""
    entry, directory, pins = _small_entry(tmp_path, monkeypatch, {
        "model.int8.onnx": ("model", b"m" * 300), "tokens.txt": ("tokens", b"t" * 40),
        "silero_vad.onnx": ("vad", b"v" * 90)})
    for one in pins:
        (directory / one.name).write_bytes(b"x" * one.bytes)

    def explode(*_args: object, **_kwargs: object):
        raise AssertionError("文件都在、字节数也对,不该去问网络")

    monkeypatch.setattr(asr_models, "_fetch_pinned", explode)
    monkeypatch.setattr(asr_models, "_sha256_of", explode)

    asr_models.ensure_pinned_files(entry)  # verify=False:只比字节数


def test_字节数不对就重下(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """半截的文件和 pin 的字节数对不上 —— 那正是"下到一半被杀"留在盘上的东西。"""
    entry, directory, pins = _small_entry(tmp_path, monkeypatch, {
        "model.int8.onnx": ("model", b"m" * 300), "tokens.txt": ("tokens", b"t" * 40),
        "silero_vad.onnx": ("vad", b"v" * 90)})
    # 两个是齐的,第三个短了一截。
    (directory / "tokens.txt").write_bytes(b"t" * 40)
    (directory / "silero_vad.onnx").write_bytes(b"v" * 90)
    (directory / "model.int8.onnx").write_bytes(b"m" * 12)

    fetched: list[str] = []

    def fake_fetch(one: asr_models.PinnedFile, target: Path, **_kwargs: object) -> None:
        fetched.append(one.name)
        target.write_bytes(b"x" * one.bytes)

    monkeypatch.setattr(asr_models, "_fetch_pinned", fake_fetch)

    asr_models.ensure_pinned_files(entry)

    assert fetched == ["model.int8.onnx"], "只该重下对不上的那一个 —— 别的两个别再下一遍"


def test_点下载时会重算哈希(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`verify=True`(管理页那个「下载」按钮)对**已经在盘上的**文件也验一遍 sha256:
    用户点它的意思是"把这一套装对",而不是"文件在就当我没来过"。

    注意字节数是对的、内容不是 —— 只看大小的话这里会当成"齐了"。
    """
    entry, directory, pins = _small_entry(tmp_path, monkeypatch, {
        "model.int8.onnx": ("model", b"m" * 300), "tokens.txt": ("tokens", b"t" * 40),
        "silero_vad.onnx": ("vad", b"v" * 90)})
    for one in pins:
        # 大小一模一样,内容全是 x —— 正好是"被换掉的文件"那个形状。
        (directory / one.name).write_bytes(b"x" * one.bytes)

    asr_models.ensure_pinned_files(entry)  # verify=False:大小对得上,于是什么都不做
    assert all((directory / one.name).read_bytes() == b"x" * one.bytes for one in pins)

    fetched: list[str] = []

    def fake_fetch(one: asr_models.PinnedFile, target: Path, **_kwargs: object) -> None:
        fetched.append(one.name)
        target.write_bytes(b"real")

    monkeypatch.setattr(asr_models, "_fetch_pinned", fake_fetch)
    asr_models.ensure_pinned_files(entry, verify=True)

    assert sorted(fetched) == sorted(one.name for one in pins), "内容不对的三个都该重下"


def test_worker_不下载_缺了就说清楚() -> None:
    """出站检查装在宿主那一层,worker 跑在外来的解释器里够不到它 —— 所以取文件不是它的事。
    它要说的是"缺了、谁去补",而不是自己偷偷发一个请求。"""
    with pytest.raises(RuntimeError, match="sherpa_dir"):
        asr._sherpa_files({"sherpa_files": []})


def test_worker_见到缺文件时报出是哪一个(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="model.int8.onnx is not on disk"):
        asr._sherpa_files({"sherpa_dir": str(tmp_path), "sherpa_files": [
            {"name": "model.int8.onnx", "role": "model", "bytes": 10}]})


def test_worker_见到字节数不对时报出两个数(tmp_path: Path) -> None:
    (tmp_path / "model.int8.onnx").write_bytes(b"x" * 7)
    with pytest.raises(RuntimeError, match="expected 10"):
        asr._sherpa_files({"sherpa_dir": str(tmp_path), "sherpa_files": [
            {"name": "model.int8.onnx", "role": "model", "bytes": 10}]})


# ---------------------------------------------------------------------------
# worker:读音频(只用标准库)
# ---------------------------------------------------------------------------
def _write_wav(path: Path, samples: list[int], *, rate: int = 16000, channels: int = 1) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"".join(int(one).to_bytes(2, "little", signed=True) for one in samples))


def test_读wav_单声道_原样(tmp_path: Path) -> None:
    target = tmp_path / "a.wav"
    _write_wav(target, [0, 16384, -16384, 32767])
    samples = asr._read_16k_mono(target)
    assert len(samples) == 4
    assert samples[0] == 0.0 and abs(samples[1] - 0.5) < 1e-6 and abs(samples[3] - 1.0) < 1e-3


def test_读wav_立体声_混成单声道(tmp_path: Path) -> None:
    """VAD 只吃单声道;混音这一步漏掉的话,喂进去的样本数会翻倍,而时间轴跟着错一倍。"""
    target = tmp_path / "s.wav"
    _write_wav(target, [32767, 0, 32767, 0], channels=2)
    samples = asr._read_16k_mono(target)
    assert len(samples) == 2
    assert all(abs(one - 0.5) < 1e-3 for one in samples)


def test_读wav_别的采样率_重采样到16k(tmp_path: Path) -> None:
    target = tmp_path / "r.wav"
    _write_wav(target, [0] * 8000, rate=8000)
    assert len(asr._read_16k_mono(target)) == 16000


def test_不支持的位宽说得出是哪一种() -> None:
    with pytest.raises(RuntimeError, match="24 bits"):
        asr._to_floats(b"\x00\x00\x00", 3)


# ---------------------------------------------------------------------------
# worker:输出形状(与既有引擎同形:带时间的 segments + words + 语种)
# ---------------------------------------------------------------------------
class _Result:
    def __init__(self, text: str, tokens: list[str], timestamps: list[float], lang: str) -> None:
        self.text, self.tokens, self.timestamps, self.lang = text, tokens, timestamps, lang


class _Stream:
    def __init__(self, result: _Result) -> None:
        self._result = result
        self.result = result

    def accept_waveform(self, *_args: object) -> None:
        return None


class _Recognizer:
    def __init__(self, result: _Result) -> None:
        self._result = result

    def create_stream(self) -> _Stream:
        return _Stream(self._result)

    def decode_stream(self, _stream: _Stream) -> None:
        return None


class _FakeVad:
    """把预先排好的几段按"喂够样本才吐"的规矩给出去,形状照 sherpa 那个:`front` 是一个
    带 `start`(样本号)与 `samples` 的视图,`pop()` 取走队首。"""

    def __init__(self, *, segments: list[tuple[int, int]], total: int) -> None:
        self._pending = list(segments)
        self._queue: list[tuple[int, list[float]]] = []
        self._fed = 0
        self._total = total

    def accept_waveform(self, samples: list[float]) -> None:
        self._fed += len(samples)
        while self._pending and self._fed >= self._pending[0][0] + self._pending[0][1]:
            at, length = self._pending.pop(0)
            self._queue.append((min(at, max(self._total - length, 0)), [0.0] * length))

    def flush(self) -> None:
        return None

    def empty(self) -> bool:
        return not self._queue

    @property
    def front(self):
        at, samples = self._queue[0]
        # SimpleNamespace 而不是内嵌 class:类体不闭包外层函数的局部变量(经典坑),
        # 在那里写 `samples = samples` 拿到的是 NameError。
        return types.SimpleNamespace(start=at, samples=samples)

    def pop(self) -> None:
        self._queue.pop(0)


def test_段的时间是绝对时间_不是相对这一段() -> None:
    """VAD 的 `start` 是**喂进去的第几个样本**。把它当"相对本段"加两次、或者干脆不加,
    产出的时间轴就整体错位 —— 而错的字幕比没有字幕更难发现。"""
    result = _Result("<|zh|>你好。", ["你", "好", "。"], [0.0, 0.06, 0.12], "<|zh|>")
    vad = _FakeVad(segments=[(8000, 3200)], total=16000)

    segments, detected = asr._sherpa_transcribe(_Recognizer(result), vad, [0.0] * 16000)

    assert len(segments) == 1
    segment = segments[0]
    # VAD 说 8000(0.5s),往回带 4800(0.3s)前奏 → 这一段实际识别的是 0.2s…0.7s 那段音频。
    assert (segment["start"], segment["end"]) == (0.2, 0.7)
    assert segment["text"] == "你好。", "语种标记必须剥掉(复用 strip_funasr_tags 的口径)"
    assert detected == "zh"
    assert segment["speaker"] is None, "这条路上没有说话人分离 —— 报 None,不许编一个"
    assert [one["word"] for one in segment["words"]] == ["你", "好"]
    assert segment["words"][0] == {"word": "你", "start": 0.2, "end": 0.26}


def test_前奏不许把上一段的尾巴再念一遍() -> None:
    """往回带前奏的下界是**上一段的结束**。

    不设这个下界的话,后一段会把前一段的尾巴再识别一次 —— 症状是"某几个字在逐字稿里出现了
    两遍",而它出现在一段的**开头**,看起来像模型听错了,不像拼接出的错。
    """
    result = _Result("第二句", ["第", "二", "句"], [0.0, 0.1, 0.2], "<|zh|>")
    # 第一段 0.0…1.0s(16000),第二段从 1.1s(17600)开始 —— 只差 1600 个样本,远小于 4800 的前奏。
    vad = _FakeVad(segments=[(0, 16000), (17600, 3200)], total=32000)

    segments, _detected = asr._sherpa_transcribe(_Recognizer(result), vad, [0.0] * 32000)

    assert len(segments) == 2
    assert segments[0]["start"] == 0.0
    assert segments[1]["start"] == 1.0, "第二段的起点被上一段的结束顶住了,不许往前越过它"


def test_前奏把句首那个字捞回来() -> None:
    """**这条是实测出来的。** VAD 报的起点是"确认这是语音"的那一刻,而那时第一个字已经念过去了:
    英文的 "The"、中文的"大"被整段切掉。往回带 0.3s 之后,这一段实际识别的音频从 VAD 的起点
    之前开始 —— 而识别器是照着喂给它的那段音频出字的。"""
    result = _Result("大家好", ["大", "家", "好"], [0.0, 0.1, 0.2], "<|zh|>")
    total = 32000
    # VAD 说这一段从第 16000 个样本(1.0s)开始、长 8000(0.5s)。
    vad = _FakeVad(segments=[(16000, 8000)], total=total)

    segments, _detected = asr._sherpa_transcribe(_Recognizer(result), vad, [0.0] * total)

    assert segments[0]["start"] == 0.7, "1.0s 起的一段往前带 0.3s → 实际从 0.7s 开始识别"
    assert segments[0]["end"] == 1.5


def test_语种标记在正文里也算数() -> None:
    """funasr 的 SenseVoice 把标记塞在正文开头,sherpa 放在 `lang` 字段里 —— 两处都要认。"""
    assert asr._sherpa_language_of(_Result("<|ja|>こんにちは", [], [], "")) == "ja"
    assert asr._sherpa_language_of(_Result("hello", [], [], "<|en|>")) == "en"
    assert asr._sherpa_language_of(_Result("hello", [], [], "<|EMO_UNKNOWN|>")) == ""


def test_请求的语种不认识就交给模型自己判() -> None:
    """语言来自工作流节点、听写、素材设置;不认识一个语种时让多语种模型自己判,
    比让整条转写失败有用。"""
    assert asr._sherpa_language("zh") == "zh"
    assert asr._sherpa_language("YUE") == "yue"
    assert asr._sherpa_language("fr") == "auto"
    assert asr._sherpa_language("") == "auto"


def test_整段没切出语音时退化成整段识别() -> None:
    """听写本来就是"说一句话",短到 0.25 秒是常态;VAD 那道门槛把它滤掉时,
    空手而归的代价是一条转写直接失败。"""

    class _Deaf(_FakeVad):
        def accept_waveform(self, samples: list[float]) -> None:
            return None

        def flush(self) -> None:
            return None

    result = _Result("你好", ["你", "好"], [0.0, 0.5], "<|zh|>")
    segments, detected = asr._sherpa_transcribe(_Recognizer(result), _Deaf(segments=[], total=16000),
                                                [0.0] * 16000)

    assert len(segments) == 1
    assert segments[0]["text"] == "你好"
    assert (segments[0]["start"], segments[0]["end"]) == (0.0, 1.0)
    assert detected == "zh"


def test_空结果不产出空段() -> None:
    """静音的正确结果是零段(下游会说"转写结果为空"),不是一段空文本。"""
    quiet = _Result("", [], [], "")
    segments, detected = asr._sherpa_transcribe(_Recognizer(quiet), _FakeVad(segments=[(0, 3200)], total=16000),
                                                [0.0] * 16000)
    assert segments == [] and detected == ""


def test_输出形状和转写域接得上() -> None:
    """worker 交出来的东西必须能被 domain 的 parse_transcript_segments 吃下 ——
    "形状对不上"正是插件那条路要专门挡一次的失败。"""
    from app.domain.voices.transcription import parse_transcript_segments

    result = _Result("<|zh|>你好。", ["你", "好", "。"], [0.0, 0.06, 0.12], "<|zh|>")
    segments, _detected = asr._sherpa_transcribe(_Recognizer(result),
                                                 _FakeVad(segments=[(8000, 3200)], total=16000),
                                                 [0.0] * 16000)

    parsed = parse_transcript_segments(json.loads(json.dumps(segments)))
    assert len(parsed) == 1
    assert parsed[0].text == "你好。"
    assert [one.text for one in parsed[0].tokens] == ["你", "好"]
