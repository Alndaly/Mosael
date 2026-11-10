"""说话照片的人像交在模型声明的那一格(ADR 0028):云端的收首帧,ComfyUI 上的 H3 数字人把脸接在参考那一路。
此前一律交首帧 —— 只收参考图的工作流拿到一格它不认的素材。"""

from __future__ import annotations

from app.domain.workflows.executors.talking import face_role


def _model(limits: dict[str, int]) -> dict:
    return {"capabilities": {"modes": ["speech-to-video"], "source_limits": limits}}


def test_收首帧的交首帧() -> None:
    assert face_role(_model({"first_frame": 1, "driving_audio": 1})) == "first_frame"


def test_只收参考图的交参考图() -> None:
    assert face_role(_model({"reference_image": 1, "driving_audio": 1})) == "reference_image"


def test_两格都收时按首帧() -> None:
    assert face_role(_model({"first_frame": 1, "reference_image": 3, "driving_audio": 1})) == "first_frame"


def test_不收提示词的模型空着_收的交说话那一句并带上长相() -> None:
    """不给收提示词的模型一句话,它就用工作流里存着的示例提示词:实测画成一张只拍到嘴的真人特写。"""
    from app.domain.workflows.executors.talking import speaking_prompt

    assert speaking_prompt({"capabilities": {"prompt": "none"}}, "17-year-old girl") == ""
    assert speaking_prompt({"capabilities": {}}, "17-year-old girl") == ""
    said = speaking_prompt({"capabilities": {"prompt": "optional"}}, "17-year-old girl, low braid")
    assert said.startswith("17-year-old girl, low braid ")
    assert "draw them once" in said and "art style" in said and "follow the audio" in said


def test_视频比配音长才剪_剪到配音那么长(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.domain.workflows.executors import talking

    assets = {"v": SimpleNamespace(media_info={"duration": 10.125}), "a": SimpleNamespace(media_info={"duration": 4.68}),
              "short": SimpleNamespace(media_info={"duration": 4.8})}
    db = SimpleNamespace(get=lambda _model, key: assets.get(key))
    trims: list[float] = []
    monkeypatch.setattr(talking.run_steps, "ordered", lambda _db, _what, start: start())
    monkeypatch.setattr(talking, "start_trim", lambda _db, *, asset, start, end, created_by: trims.append(end) or SimpleNamespace(id="job"))
    monkeypatch.setattr(talking, "current_actor", lambda _db: None)
    monkeypatch.setattr(talking, "wait_for_job", lambda _job, release: SimpleNamespace(result={"asset_id": "trimmed"}))

    assert talking._fit_to_audio(db, "v", "a") == "trimmed" and trims == [4.68]
    assert talking._fit_to_audio(db, "short", "a") == "short", "只长零点几秒(编码对齐)不剪"
