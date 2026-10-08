"""用哪个 ffmpeg 能在「管理 → 引擎 → FFmpeg」里填,存在库里(ADR 0048 第一步)。

发布版的 Mac 用户多半装的是 Homebrew 的 ffmpeg —— 精简版,没有 libass,带字幕 / 花字 / AI 标识的导出在建任务之前就被拒。
此前那句话让他「设环境变量 MOSAEL_FFMPEG」,可从 Finder 起的后端读不到 shell 里设的环境变量:给了修法,却做不到。
而探出来的结论只写进日志,界面上看不见。

这里钉住:
- 填的路径存进库,存完立刻对本进程生效(起 ffmpeg 的地方都读 settings.ffmpeg),旁边的 ffprobe 跟着用;启动时从库里装回来;
- 填的不是一个能跑的 ffmpeg 就不存,说清是哪儿不对;
- 管理页拿得到探测结果:找没找到、版本、有没有 libass、带字的导出走哪条路;换了程序点「重新检测」就认得出;
- 导出被拒时那句话说原因(这个 ffmpeg 没有 libass,Homebrew 默认的就是这种)和怎么办(装完整版、到这一格填路径);
- 环境变量 MOSAEL_FFMPEG 给了的话以它为准,这一格不生效,界面和报错都照实说;
- 只有部署管理员看得到、改得了 —— 填的是这台机器上要执行的程序。

ffmpeg 用一个小脚本冒充:只回答 `-version` 和 `-filters` 两问,足够把「存 → 生效 → 探」这条路走通,不依赖本机装了哪种 ffmpeg。
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.domain import media_tools
from app.media import render_executor
from app.media.render_executor import RenderExecutionError, ensure_text_can_burn
from app.media.render_plan import build_render_plan
from tests.util import fresh_client, second_client

LIBASS_LINE = " ..C subtitles         V->V       Render text subtitles onto input video using the libass library."


def _fake_ffmpeg(folder: Path, *, libass: bool, version: str = "7.1-test", with_ffprobe: bool = True) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    filters = LIBASS_LINE if libass else " ..C scale             V->V       Scale the input video size."
    script = folder / "ffmpeg"
    script.write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do\n'
        '  case "$a" in\n'
        f'    -version) echo "ffmpeg version {version} Copyright (c) 2000-2026 the FFmpeg developers"; exit 0;;\n'
        f'    -filters) echo "{filters}"; exit 0;;\n'
        "  esac\n"
        "done\n"
        "exit 1\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    if with_ffprobe:
        probe = folder / "ffprobe"
        probe.write_text("#!/bin/sh\nexit 0\n")
        probe.chmod(probe.stat().st_mode | stat.S_IEXEC)
    return script


@pytest.fixture
def not_pinned(monkeypatch):
    """本机或 CI 可能设了 MOSAEL_FFMPEG;这几条要的是「没设」的那个世界。"""
    monkeypatch.setattr(media_tools, "FFMPEG_FIELDS_FROM_ENVIRONMENT", frozenset())
    monkeypatch.setattr(render_executor, "FFMPEG_FIELDS_FROM_ENVIRONMENT", frozenset())


def _plan_with_subtitle():
    return build_render_plan(
        sequence_id="s", revision=1, width=160, height=90, fps=10,
        clips=[{"id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 1}],
        assets={"a": {"file_key": "src.mp4"}},
        subtitle_clips=[{"id": "t1", "asset_id": None, "timeline_start": 0, "src_in": 0, "src_out": 1, "text_override": "你好"}],
    )


def test_填的路径存进库_立刻生效_旁边的_ffprobe_跟着用(tmp_path, not_pinned) -> None:
    client = fresh_client()
    ffmpeg = _fake_ffmpeg(tmp_path / "full" / "bin", libass=True)

    saved = client.put("/api/settings/ffmpeg", json={"path": str(ffmpeg)})

    assert saved.status_code == 200, saved.text
    assert settings.ffmpeg == str(ffmpeg)
    assert settings.ffprobe == str(ffmpeg.with_name("ffprobe"))
    body = client.get("/api/settings/ffmpeg").json()
    assert body["path"] == str(ffmpeg) and body["in_use"] == str(ffmpeg)
    assert body["found"] is True and body["version"] == "7.1-test" and body["libass"] is True
    assert body["pinned_by_environment"] is False


def test_旁边没有_ffprobe_就还用_PATH_上的(tmp_path, not_pinned) -> None:
    client = fresh_client()
    ffmpeg = _fake_ffmpeg(tmp_path / "bare", libass=True, with_ffprobe=False)

    assert client.put("/api/settings/ffmpeg", json={"path": str(ffmpeg)}).status_code == 200

    assert settings.ffmpeg == str(ffmpeg)
    assert settings.ffprobe == media_tools.DEFAULT_FFPROBE


def test_清空_回到_PATH_上的_ffmpeg(tmp_path, not_pinned) -> None:
    client = fresh_client()
    ffmpeg = _fake_ffmpeg(tmp_path / "full", libass=True)
    client.put("/api/settings/ffmpeg", json={"path": str(ffmpeg)})

    cleared = client.put("/api/settings/ffmpeg", json={"path": "  "})

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["path"] == ""
    assert (settings.ffmpeg, settings.ffprobe) == (media_tools.DEFAULT_FFMPEG, media_tools.DEFAULT_FFPROBE)


def test_启动时把库里那份装回进程(tmp_path, not_pinned, monkeypatch) -> None:
    fresh_client()
    #: 先记下进来时的值(测试完还原到它):存的那一下提交之后就会改写这两项。
    monkeypatch.setattr(settings, "ffmpeg", settings.ffmpeg)
    monkeypatch.setattr(settings, "ffprobe", settings.ffprobe)
    ffmpeg = _fake_ffmpeg(tmp_path / "full", libass=True)
    with SessionLocal() as db:
        media_tools.save_path(db, str(ffmpeg))
        db.commit()
    settings.ffmpeg, settings.ffprobe = "ffmpeg", "ffprobe"

    with SessionLocal() as db:
        media_tools.apply_to_process(db)

    assert settings.ffmpeg == str(ffmpeg)
    assert settings.ffprobe == str(ffmpeg.with_name("ffprobe"))


@pytest.mark.parametrize("case", ["relative", "missing", "not-executable", "not-ffmpeg"])
def test_填的不是能跑的_ffmpeg_就不存(case, tmp_path, not_pinned) -> None:
    client = fresh_client()
    before = settings.ffmpeg
    if case == "relative":
        path = "bin/ffmpeg"
    elif case == "missing":
        path = str(tmp_path / "nowhere" / "ffmpeg")
    elif case == "not-executable":
        plain = tmp_path / "ffmpeg"
        plain.write_text("not a program")
        path = str(plain)
    else:
        impostor = tmp_path / "impostor"
        impostor.write_text("#!/bin/sh\necho hello\n")
        impostor.chmod(impostor.stat().st_mode | stat.S_IEXEC)
        path = str(impostor)

    refused = client.put("/api/settings/ffmpeg", json={"path": path})

    assert refused.status_code == 422, refused.text
    assert path.split("/")[-1] in refused.json()["detail"]
    assert settings.ffmpeg == before
    assert client.get("/api/settings/ffmpeg").json()["path"] == ""


def test_管理页拿得到探测结果_换了程序点重新检测就认得出(tmp_path, not_pinned, monkeypatch) -> None:
    client = fresh_client()
    monkeypatch.setattr(settings, "text_rasterize", False)
    ffmpeg = _fake_ffmpeg(tmp_path / "brew", libass=False, version="9.0.2")
    client.put("/api/settings/ffmpeg", json={"path": str(ffmpeg)})

    slim = client.get("/api/settings/ffmpeg").json()
    assert (slim["found"], slim["version"], slim["libass"], slim["text_burn_in"]) == (True, "9.0.2", False, None)

    # 同一个路径上换成带 libass 的那一版(比如重装了):不重启,点一下「重新检测」。
    _fake_ffmpeg(tmp_path / "brew", libass=True, version="9.0.2")
    rechecked = client.post("/api/settings/ffmpeg/recheck")

    assert rechecked.status_code == 200, rechecked.text
    assert (rechecked.json()["libass"], rechecked.json()["text_burn_in"]) == (True, "libass")


def test_浏览器那条路通的话_没有_libass_也导得出(tmp_path, not_pinned, monkeypatch) -> None:
    client = fresh_client()
    monkeypatch.setattr(render_executor, "_text_rasterizer_available", lambda: True)
    ffmpeg = _fake_ffmpeg(tmp_path / "brew", libass=False)
    client.put("/api/settings/ffmpeg", json={"path": str(ffmpeg)})

    body = client.get("/api/settings/ffmpeg").json()

    assert (body["libass"], body["text_burn_in"]) == (False, "browser")


def test_找不到_ffmpeg_界面上看得见(tmp_path, not_pinned, monkeypatch) -> None:
    """上次探的是另一个 ffmpeg 也不能拿它的结论顶上:生效的那个换了(卸掉了、换了路径),就照新的现探。"""
    client = fresh_client()
    monkeypatch.setattr(settings, "ffmpeg", str(_fake_ffmpeg(tmp_path / "was-there", libass=True)))
    assert client.get("/api/settings/ffmpeg").json()["found"] is True
    monkeypatch.setattr(settings, "ffmpeg", str(tmp_path / "gone" / "ffmpeg"))

    body = client.get("/api/settings/ffmpeg").json()

    assert (body["found"], body["version"], body["libass"]) == (False, "", False)


def test_导出被拒时_说原因和怎么办(tmp_path, not_pinned, monkeypatch) -> None:
    fresh_client()
    monkeypatch.setattr(settings, "text_rasterize", False)
    monkeypatch.setattr(settings, "ffmpeg", str(_fake_ffmpeg(tmp_path / "brew", libass=False)))

    with pytest.raises(RenderExecutionError) as caught:
        ensure_text_can_burn(_plan_with_subtitle())

    said = str(caught.value)
    assert caught.value.key == "renderErr_noLibass"
    assert "libass" in said and "Homebrew" in said, "原因:这个 ffmpeg 没有 libass,Homebrew 默认的就是这种"
    assert "brew install ffmpeg-full" in said and "管理 → 引擎 → FFmpeg" in said, "怎么办:装完整版、到这一格填路径"
    assert "MOSAEL_FFMPEG" not in said, "发布版做不到的那条修法不再给"


def test_用的是_PATH_上的程序名时_说出实际是哪个文件(tmp_path, not_pinned, monkeypatch) -> None:
    """「ffmpeg(ffmpeg)没有 libass」认不出是哪个;说出 /opt/homebrew/bin/ffmpeg,用户才认得出是 Homebrew 装的那个。"""
    client = fresh_client()
    brew = _fake_ffmpeg(tmp_path / "homebrew" / "bin", libass=False)
    monkeypatch.setenv("PATH", str(brew.parent))
    monkeypatch.setattr(settings, "ffmpeg", "ffmpeg")
    monkeypatch.setattr(settings, "text_rasterize", False)

    assert client.get("/api/settings/ffmpeg").json()["in_use"] == str(brew)
    with pytest.raises(RenderExecutionError) as caught:
        ensure_text_can_burn(_plan_with_subtitle())
    assert str(brew) in str(caught.value)


def test_环境变量给了_这一格不生效_界面和报错都照实说(tmp_path, monkeypatch) -> None:
    client = fresh_client()
    pinned = frozenset({"ffmpeg"})
    monkeypatch.setattr(media_tools, "FFMPEG_FIELDS_FROM_ENVIRONMENT", pinned)
    monkeypatch.setattr(render_executor, "FFMPEG_FIELDS_FROM_ENVIRONMENT", pinned)
    from_environment = _fake_ffmpeg(tmp_path / "env", libass=False)
    monkeypatch.setattr(settings, "ffmpeg", str(from_environment))
    filled = _fake_ffmpeg(tmp_path / "filled", libass=True)

    saved = client.put("/api/settings/ffmpeg", json={"path": str(filled)})

    assert saved.status_code == 200, saved.text
    assert settings.ffmpeg == str(from_environment), "环境变量给的那个照用"
    body = saved.json()
    assert body["path"] == str(filled) and body["in_use"] == str(from_environment)
    assert body["pinned_by_environment"] is True
    monkeypatch.setattr(settings, "text_rasterize", False)
    with pytest.raises(RenderExecutionError) as caught:
        ensure_text_can_burn(_plan_with_subtitle())
    assert caught.value.key == "renderErr_noLibassPinnedByEnvironment"
    assert "MOSAEL_FFMPEG" in str(caught.value)


def test_只有部署管理员看得到也改得了(tmp_path, not_pinned) -> None:
    fresh_client()
    member = second_client("member")
    ffmpeg = _fake_ffmpeg(tmp_path / "full", libass=True)
    before = settings.ffmpeg

    assert member.get("/api/settings/ffmpeg").status_code == 403
    assert member.put("/api/settings/ffmpeg", json={"path": str(ffmpeg)}).status_code == 403
    assert member.post("/api/settings/ffmpeg/recheck").status_code == 403
    assert settings.ffmpeg == before
