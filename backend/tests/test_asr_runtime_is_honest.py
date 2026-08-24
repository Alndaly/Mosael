"""「已安装」得是**跑得起来**的意思。

用户撞到的:转写模型那一页三行写着「已安装」,而转写一开始就报「未找到可用的转写环境」。两句话
都没说谎 —— 它们在回答**不同的问题**:

    徽章   = 模型权重的文件在磁盘上吗(`_is_installed` 只量目录大小)
    运行时 = 有没有一个 Python 解释器能 `import funasr` / `import whisperx`

而这两件事完全可以一个成立一个不成立:模型缓存在 `~/.cache/modelscope`、`~/.cache/huggingface`
里,别的工具下过、或者换过解释器,文件就在那儿;而这个应用的解释器里从来没装过那两个包。
实测那台机器:funasr 2.2GB、whisperx large-v3 6.2GB 都在盘上,没有任何解释器 import 得动。

**一个状态显示回答的问题,和用户以为它回答的问题不是同一个** —— 这是这份代码里反复出现的那类
缺陷。修法不是把徽章改得更保守,而是让它把两件事**都**说出来:文件在不在、跑不跑得起来。

顺带:那一页的「下载」按钮也走同一条解释器探测(`_resolve_python`),所以在缺环境的机器上,
点下载同样只会报错 —— 页面上没有任何一个动作是能成的。TTS 那边早就解决了这个问题(托管 venv,
点下载时后端自己把环境建好,见 ai/runtime/tts_models.ensure_engine_runtime),ASR 还停在"请你自己
去设置 OPEN_STUDIO_ASR_PYTHON"。
"""

from __future__ import annotations

from app.ai.runtime import asr_models
from app.domain.voices import service


def test_the_status_says_whether_it_can_actually_run(monkeypatch) -> None:
    """文件在盘上但没有能跑它的解释器时,状态必须说出来。"""
    monkeypatch.setattr(asr_models, "_is_installed", lambda entry: True)
    monkeypatch.setattr(asr_models, "runtime_ready", lambda engine: False)

    rows = {row["id"]: row for row in asr_models.list_status()}

    row = rows["funasr"]
    assert row["status"] == "installed", "文件确实在,这一半不该被改掉"
    assert row["runtime_ready"] is False, "没说「跑不起来」"


def test_a_fully_ready_model_says_so(monkeypatch) -> None:
    monkeypatch.setattr(asr_models, "_is_installed", lambda entry: True)
    monkeypatch.setattr(asr_models, "runtime_ready", lambda engine: True)
    # 探测现在是**后台**跑的(列模型不该卡在 import funasr 上,见
    # test_status_endpoints_do_not_probe_inline)。要确定答案就显式探一次。
    asr_models.clear_runtime_probes()
    asr_models.refresh_runtime_status("funasr")

    row = {r["id"]: r for r in asr_models.list_status()}["funasr"]

    assert row["status"] == "installed" and row["runtime_ready"] is True


def test_runtime_ready_asks_the_interpreter_not_the_disk(monkeypatch) -> None:
    """判据是「import 得动吗」,不是「文件在不在」—— 两者可以一个真一个假。"""
    calls: list[str] = []

    def fake_probe(engine: str) -> str:
        calls.append(engine)
        raise RuntimeError("没有装了它的解释器")

    monkeypatch.setattr(asr_models, "_resolve_python", fake_probe)
    asr_models.runtime_ready.cache_clear()

    assert asr_models.runtime_ready("funasr") is False
    assert calls == ["funasr"]


def test_the_error_says_the_models_are_fine(monkeypatch) -> None:
    """报错要说清缺的是**运行环境**,不是模型 —— 否则用户会去重下已经在盘上的 6GB。"""
    monkeypatch.setattr(asr_models, "candidate_pythons", lambda: [])
    asr_models.clear_runtime_probes()

    try:
        service.resolve_asr_runtime()
    except service.AsrError as exc:
        message = str(exc)
    else:
        raise AssertionError("该报错的没报")

    assert "模型" in message, f"没提模型的处境:{message}"
    assert "下载" in message or "已" in message


# ---------------- 装得上运行环境 ----------------


def test_there_is_a_way_to_install_the_runtime() -> None:
    """必须有一条**从界面走得通**的路把环境装上。

    TTS 早就解决了这件事(托管 venv,点下载时后端自己建环境,见 tts_models.ensure_engine_runtime),
    而 ASR 停在"请你自己去设置 OPEN_STUDIO_ASR_PYTHON"。对一个桌面应用的用户,那句话等于
    "这个功能你用不了" —— 尤其 FunASR 是中文转写的默认引擎,他会第一个撞上。
    """
    assert hasattr(asr_models, "ensure_engine_runtime")


def test_installing_is_skipped_when_it_already_runs(monkeypatch) -> None:
    """已经有解释器能跑它了就什么都不做 —— 别去动用户自带的环境。"""
    calls: list = []
    monkeypatch.setattr(asr_models, "runtime_ready", lambda engine: True)
    monkeypatch.setattr(asr_models.subprocess, "run", lambda *a, **k: calls.append(a))

    asr_models.ensure_engine_runtime("funasr")

    assert calls == [], "已经跑得起来还去建环境"


def test_the_download_installs_the_runtime_first(monkeypatch) -> None:
    """点「下载」要先把环境建好 —— 此前它直接探测解释器,没有就报错,于是这一页上没有任何
    一个动作是能成的:显示「已安装」,点什么都失败。"""
    import inspect

    source = inspect.getsource(asr_models._download_body)

    assert "ensure_engine_runtime" in source


def test_installing_the_runtime_works_on_an_already_downloaded_model(monkeypatch) -> None:
    """模型文件已经在盘上、只差运行环境时,那个按钮必须真的做事。

    `start_download` 对「已安装」的模型直接返回 —— 那是"文件都在了还下什么"的意思,而这里要装的
    是**另一样东西**。不放行的话,那个按钮点了没有任何反应,比报错更让人摸不着头脑。
    """
    started: list[str] = []
    monkeypatch.setattr(asr_models, "_is_installed", lambda entry: True)
    monkeypatch.setattr(asr_models, "runtime_ready", lambda engine: False)
    # 桩要能接住**所有**起线程的调用:后台探测也走 threading.Thread,而它不带 args
    # (见 asr_models.probe_in_background)。一个卡死参数形状的桩,会在别处加线程时炸。
    monkeypatch.setattr(
        asr_models.threading, "Thread",
        lambda target, args=None, daemon=None: type(
            "T", (), {"start": lambda self: started.append(args[0]) if args else None}
        )(),
    )

    asr_models.start_download("funasr")

    assert started == ["funasr"], "文件在盘上时,装运行环境这条路被挡住了"


# ---------------- 装环境 ≠ 下模型 ----------------


def test_installing_the_runtime_reports_on_the_row_being_installed(monkeypatch) -> None:
    """状态要写在**正在装的那一行**上。

    此前它按引擎名写(`funasr`),而界面按模型 id 读(`funasr`)—— 于是"创建运行环境…"
    "安装依赖…"这两句一次都没显示过,用户看到的是一条不动的进度条配一句"准备下载…"。
    """
    monkeypatch.setattr(asr_models, "runtime_ready", lambda engine: False)
    monkeypatch.setattr(asr_models, "managed_venv_python", lambda engine=None: __import__("pathlib").Path("/nope/python"))
    monkeypatch.setattr(asr_models.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 1, "stderr": "x", "stdout": ""})())

    try:
        asr_models.ensure_engine_runtime("funasr", progress_key="funasr")
    except RuntimeError:
        pass

    live = asr_models._store.get("funasr")
    assert live is not None, "状态没写在那一行上"
    # 领域里存 key,出口才翻(见 core/i18n)。断言"说的是哪一句",不断言那句长什么样 ——
    # 换个说法或加一种语言都不该让这条红。
    assert live.message == "dlMsg_creatingRuntime"


def test_the_runtime_phase_does_not_borrow_the_model_size(monkeypatch) -> None:
    """装环境时不该显示模型的字节数。

    2.2GB 是**模型**的大小;这一阶段跑的是 pip(装 torch 等),它一个字节都不会落进模型缓存目录
    —— 于是进度条永远停在 0 MB / 2.2 GB。两件事的量纲不一样,就别共用一个进度条。
    """
    monkeypatch.setattr(asr_models, "runtime_ready", lambda engine: False)
    monkeypatch.setattr(asr_models, "managed_venv_python", lambda engine=None: __import__("pathlib").Path("/nope/python"))
    monkeypatch.setattr(asr_models.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 1, "stderr": "x", "stdout": ""})())

    try:
        asr_models.ensure_engine_runtime("funasr", progress_key="funasr")
    except RuntimeError:
        pass

    live = asr_models._store.get("funasr")
    assert live.total == 0, f"借用了模型的大小:{live.total}"


# ---------------- 量的是磁盘,不是幻觉 ----------------


def test_symlinked_snapshots_are_not_counted_twice(tmp_path) -> None:
    """HuggingFace 缓存里 `snapshots/*` 是指回 `blobs/` 的符号链接。

    跟着链接走的话每个 blob 被数两遍 —— 实测正是整两倍(du 说 464MB,而它报 972MB)。后果不只是
    数字难看:`_is_installed` 的判据是"实测 ≥ 期望的某个比例",量翻倍意味着**下到一半的模型
    也会被判成已安装**,然后转写在运行时炸。
    """
    model = tmp_path / "models--X--y"
    (model / "blobs").mkdir(parents=True)
    (model / "snapshots" / "rev").mkdir(parents=True)
    blob = model / "blobs" / "abc"
    blob.write_bytes(b"x" * 1000)
    (model / "snapshots" / "rev" / "model.bin").symlink_to(blob)

    assert asr_models._dir_size(model) == 1000, "符号链接把同一份数据数了两遍"


def test_a_half_downloaded_model_is_not_reported_installed(tmp_path, monkeypatch) -> None:
    """量翻倍最坏的后果 —— 半个模型被判成已安装。"""
    entry = asr_models.CATALOG[0]
    monkeypatch.setattr(asr_models, "_measure", lambda e: int(e.expected_bytes * 0.5))

    assert asr_models._is_installed(entry) is False


# ---------------- 候选解释器只有一份 ----------------


def test_the_managed_venv_is_visible_to_transcription() -> None:
    """转写和模型页问的是同一个问题 —— 得由同一份名单回答。

    实际撞到的:托管 venv 里 funasr 装好了,模型页显示「已安装」,而一点转写就报"没有运行环境"。
    因为托管 venv 只加进了 asr_models 那个探测点,service 这边还是老的两个候选(用户设的解释器 +
    后端自己的)。**同一个问题问了两遍,两个函数给了不同答案** —— 和「文件在盘上 vs 跑不跑得起来」
    是同一种缺陷,只是这次两边都在回答后者。
    """
    managed = str(asr_models.managed_venv_python("funasr"))
    candidates = [str(p) for p in asr_models.candidate_pythons("funasr")]

    assert managed in candidates, f"转写看不到托管 venv:{candidates}"


def test_the_two_probes_share_one_list() -> None:
    """形状棘轮:候选名单只有一处。两处各拼一份,下一次加候选时又会只加一边。"""
    import inspect

    # 探测只有一份实现:service 不再自己探,它调 asr_models 那一个。
    assert "subprocess" not in inspect.getsource(service.resolve_asr_runtime), "service 又自己探测了一遍"
    assert "candidate_pythons(engine)" in inspect.getsource(asr_models._resolve_python)


def test_the_error_is_plain_text(monkeypatch) -> None:
    """这句话会**原样**显示在界面上 —— markdown 在那儿只会以星号的样子出现。"""
    monkeypatch.setattr(asr_models, "candidate_pythons", lambda: [])
    asr_models.clear_runtime_probes()

    try:
        service.resolve_asr_runtime()
    except service.AsrError as exc:
        assert "**" not in str(exc), f"报错里有没被渲染的 markdown:{exc}"
    else:
        raise AssertionError("该报错的没报")


# ---------------- 全局过一遍时顺手钉的 ----------------


def test_the_page_copy_does_not_promise_an_automatic_runtime() -> None:
    """页面说"首次转写会自动下载" —— 那对**模型**成立,对**运行环境**不成立。

    转写路径只探测解释器,探不到就报错;它不会自己去装几 GB 的 torch(那也不该在用户没点头的
    情况下发生)。文案不改的话,用户会一直等一件不会发生的事。
    """
    import pathlib

    messages = (pathlib.Path(__file__).resolve().parents[2] / "frontend/src/app/messages.ts")
    text = messages.read_text()
    line = next(l for l in text.splitlines() if "asrModelsDesc" in l and "语音模型" in l)
    assert "运行环境" in line, f"文案没说清运行环境要手动装:{line.strip()}"


def test_transcribe_does_not_silently_install_gigabytes() -> None:
    """转写不该在用户没点头时装几 GB 依赖 —— 它只探测,缺了就说清楚去哪装。"""
    import inspect

    assert "ensure_engine_runtime" not in inspect.getsource(service.resolve_asr_runtime)
