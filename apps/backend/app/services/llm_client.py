from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from app.config import settings


def _extract_json_obj(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    snippet = text[start : end + 1]
    try:
        parsed = json.loads(snippet)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


class LlmClient:
    """OpenAI-compatible client for SiliconFlow/Qwen/DeepSeek providers."""

    def __init__(self) -> None:
        self.enabled = bool(settings.llm_api_key and settings.llm_base_url)
        self._client: OpenAI | None = None
        if self.enabled:
            self._client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        if not self.enabled or self._client is None:
            return {}

        model_name = model or settings.llm_fast_model or settings.llm_model
        resp = self._client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            stream=False,
        )
        content = ""
        if resp.choices and resp.choices[0].message:
            content = resp.choices[0].message.content or ""
        return _extract_json_obj(content)

