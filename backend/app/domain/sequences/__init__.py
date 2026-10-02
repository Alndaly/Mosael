"""Sequence domain interface."""

from app.domain.sequences._timeline import CANVAS_SIZE_RANGE, DEFAULT_CANVAS, FPS_RANGE
from app.domain.sequences.creation import SequenceScaffold, copy_sequence, create_sequence_scaffold
from app.domain.sequences.operations import cut_clip_range, delete_clip, insert_clip, move_clip, trim_clip

__all__ = [
    "CANVAS_SIZE_RANGE",
    "DEFAULT_CANVAS",
    "FPS_RANGE",
    "SequenceScaffold",
    "copy_sequence",
    "create_sequence_scaffold",
    "cut_clip_range",
    "delete_clip",
    "insert_clip",
    "move_clip",
    "trim_clip",
]
