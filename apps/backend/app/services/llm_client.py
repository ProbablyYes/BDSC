from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from app.config import settings

_THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.DOTALL)


def _strip_think_tags(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


def _extract_json_obj(text: str) -> dict[str, Any]:
    text = _strip_think_tags(text or "")
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
        raw = self.chat_text(
            system_prompt=(
                system_prompt
                + "\n请严格返回 JSON 对象，不要输出任何解释文字，不要使用 markdown 代码块。"
            ),
            user_prompt=user_prompt,
            model=model,
            temperature=temperature,
        )
        return _extract_json_obj(raw)

    def chat_text(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        if not self.enabled or self._client is None:
            return ""

        model_name = model or settings.llm_fast_model or settings.llm_model
        safe_temp = max(0.0, min(float(temperature), 1.2))
        try:
            resp = self._client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=safe_temp,
                stream=False,
            )
            if resp.choices and resp.choices[0].message:
                raw = resp.choices[0].message.content or ""
                return _strip_think_tags(raw)
        except Exception:  # noqa: BLE001
            return ""
        return ""
