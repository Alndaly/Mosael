"""属性型操作的逆向/正向重放:片段的调色/速度/增益/变换/文本,序列的画幅与字幕样式。

这一组的形状都一样 —— payload 里存着改之前和改之后的值,两个方向就是各写一边。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Sequence
from app.domain.sequences.undo import undoable
from app.domain.sequences.undo.rows import require_clip_row


@undoable("set_clip_effect")
class SetClipEffect:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        require_clip_row(db, payload["clip_id"]).effects = payload["previous"]

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        require_clip_row(db, payload["clip_id"]).effects = payload["effects"]


@undoable("set_clip_speed")
class SetClipSpeed:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        require_clip_row(db, payload["clip_id"]).speed = payload["previous"]

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        require_clip_row(db, payload["clip_id"]).speed = payload["speed"]


@undoable("set_clip_gain")
class SetClipGain:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        clip = require_clip_row(db, payload["clip_id"])
        clip.gain = payload["previous"]["gain"]
        clip.muted = payload["previous"]["muted"]

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        clip = require_clip_row(db, payload["clip_id"])
        clip.gain = payload["gain"]
        clip.muted = payload["muted"]


@undoable("set_clip_transform")
class SetClipTransform:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        require_clip_row(db, payload["clip_id"]).transform = payload["previous"]

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        require_clip_row(db, payload["clip_id"]).transform = payload["transform"]


@undoable("set_clip_text")
class SetClipText:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        require_clip_row(db, payload["clip_id"]).text_override = payload["previous"]

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        require_clip_row(db, payload["clip_id"]).text_override = payload["text"]


@undoable("set_clip_texts_batch")
class SetClipTextsBatch:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        for entry in payload["entries"]:
            require_clip_row(db, entry["clip_id"]).text_override = entry["previous"]

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        for entry in payload["entries"]:
            require_clip_row(db, entry["clip_id"]).text_override = entry["text"]


@undoable("set_sequence_reframe")
class SetSequenceReframe:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        previous = payload["previous"]
        sequence.width, sequence.height, sequence.reframe = (
            previous["width"],
            previous["height"],
            previous["reframe"],
        )

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        sequence.width, sequence.height, sequence.reframe = (
            payload["width"],
            payload["height"],
            payload["reframe"],
        )


@undoable("set_subtitle_style")
class SetSubtitleStyle:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        sequence.subtitle_style = payload["previous"]

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        sequence.subtitle_style = payload["style"]
