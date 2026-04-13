from __future__ import annotations

import logging
from pathlib import Path

from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class SpeechToTextClient:
    """Simple wrapper for OpenAI-compatible speech-to-text API.

    The client reuses the same gateway as LlmClient but calls the
    /audio/transcriptions endpoint to turn short pitch videos into
    Chinese transcripts.
    """

    def __init__(self) -> None:
        self.enabled = bool(settings.llm_api_key and settings.llm_base_url and settings.stt_model)
        self._client: OpenAI | None = None
        if self.enabled:
            self._client = OpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                timeout=240.0,
                max_retries=1,
            )

    def transcribe(self, media_path: Path) -> str:
        """Transcribe a short audio/video file into text.

        The underlying provider is expected to support common formats
        such as mp3/wav/mp4/webm on the /audio/transcriptions API.
        """

        if not self.enabled or self._client is None:
            raise RuntimeError("语音转写尚未配置，请联系教师或管理员开启。")

        path = Path(media_path)
        if not path.exists():
            raise FileNotFoundError(str(path))

        try:
            with path.open("rb") as f:
                resp = self._client.audio.transcriptions.create(
                    model=settings.stt_model,
                    file=f,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("STT transcription failed (model=%s): %s", settings.stt_model, exc)
            raise RuntimeError("语音转写失败，请稍后重试或联系教师排查。") from exc

        # OpenAI SDK v1 returns an object with a .text attribute
        text = getattr(resp, "text", "") if resp is not None else ""
        return str(text or "").strip()