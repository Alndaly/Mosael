"""Transcript domain interface."""

from app.domain.transcripts.operations import attach_transcript, get_transcript_for_asset

__all__ = ["attach_transcript", "get_transcript_for_asset"]
