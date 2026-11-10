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
