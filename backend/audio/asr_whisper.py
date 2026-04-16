"""Placeholder for Whisper-based ASR integration.

This module will provide speech-to-text transcription using OpenAI Whisper
or a local Whisper model. Currently a stub for future implementation.
"""

from __future__ import annotations


class ASRWhisperService:
    """Automatic Speech Recognition service using Whisper."""

    def __init__(self, model_name: str = "base") -> None:
        self.model_name = model_name
        self._model = None

    def transcribe(self, audio_path: str) -> str:
        raise NotImplementedError("Whisper ASR is not yet implemented.")
