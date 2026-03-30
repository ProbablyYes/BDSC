from __future__ import annotations

import json
import logging
import re
import time
import time
from typing import Any

from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)
_THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.DOTALL)


def _strip_think_tags(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*\n?([\s\S]*?)```", re.DOTALL)


def _extract_json_obj(text: str) -> dict[str, Any]:
    text = _strip_think_tags(text or "")
    if not text:
        return {}

    # Try direct parse first
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass

    # Strip markdown code fences (```json ... ```)
    m = _CODE_FENCE_RE.search(text)
    if m:
        try:
            parsed = json.loads(m.group(1).strip())
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass

    # Fallback: extract substring between first { and last }
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
        self._qwen_client: OpenAI | None = None
        if self.enabled:
            self._client = OpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                timeout=180.0,
                max_retries=1,
            )
        if settings.llm_qwen_api_key and settings.llm_qwen_base_url:
            self._qwen_client = OpenAI(
                api_key=settings.llm_qwen_api_key,
                base_url=settings.llm_qwen_base_url,
                timeout=180.0,
                max_retries=1,
            )

    @staticmethod
    def _is_qwen_model(model_name: str) -> bool:
        lowered = (model_name or "").lower()
        return "qwen" in lowered or "tongyi" in lowered

    def _resolve_client_and_model(self, model: str | None = None) -> tuple[OpenAI | None, str]:
        model_name = model or settings.llm_fast_model or settings.llm_model
        if self._qwen_client is not None and self._is_qwen_model(model_name):
            return self._qwen_client, (settings.llm_qwen_model or model_name)
        return self._client, model_name

    def _provider_name(self, client: OpenAI | None) -> str:
        if client is None:
            return "disabled"
        if client is self._qwen_client:
            return "dashscope"
        return "default"

    @staticmethod
    def _error_kind(exc: Exception) -> str:
        text = f"{type(exc).__name__}: {exc}".lower()
        if "connection" in text or "connect" in text or "dns" in text:
            return "connect_error"
        if "timeout" in text or "timed out" in text:
            return "timeout"
        if "rate limit" in text or "429" in text:
            return "rate_limit"
        return "other"

    @staticmethod
    def _should_retry(error_kind: str) -> bool:
        return error_kind in {"connect_error", "timeout", "rate_limit"}

    def _fallback_target(self, client: OpenAI | None, model_name: str) -> tuple[OpenAI | None, str] | None:
        if client is self._qwen_client and self._client is not None:
            candidates = [
                settings.llm_reason_model,
                settings.llm_fast_model,
                settings.llm_model,
            ]
            for candidate in candidates:
                if candidate and not self._is_qwen_model(candidate):
                    return self._client, candidate
        return None

    def chat_text_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        temperature: float = 0.2,
    ):
        """Yield text chunks as a generator (for SSE streaming)."""
        client, model_name = self._resolve_client_and_model(model)
        if client is None:
            yield ""
            return
        safe_temp = max(0.0, min(float(temperature), 1.2))
        provider = self._provider_name(client)

        def _stream_once(stream_client: OpenAI, stream_model: str):
            return stream_client.chat.completions.create(
                model=stream_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=safe_temp,
                stream=True,
            )

        stream = None
        last_exc: Exception | None = None
        max_attempts = 3 if client is self._qwen_client else 2
        for attempt in range(1, max_attempts + 1):
            try:
                stream = _stream_once(client, model_name)
                break
            except Exception as exc:
                last_exc = exc
                error_kind = self._error_kind(exc)
                logger.warning(
                    "LLM stream failed (model=%s provider=%s attempt=%d kind=%s): %s",
                    model_name, provider, attempt, error_kind, exc,
                )
                if attempt >= max_attempts or not self._should_retry(error_kind):
                    break
                time.sleep(min(1.5, 0.4 * attempt))

        if stream is None:
            fallback = self._fallback_target(client, model_name)
            if fallback:
                fb_client, fb_model = fallback
                try:
                    logger.warning("LLM stream fallback: %s/%s -> %s/%s", provider, model_name, self._provider_name(fb_client), fb_model)
                    stream = _stream_once(fb_client, fb_model)
                    client = fb_client
                    model_name = fb_model
                    provider = self._provider_name(fb_client)
                except Exception as exc:
                    last_exc = exc
                    logger.warning("LLM stream fallback failed (model=%s provider=%s): %s", fb_model, provider, exc)
            if stream is None:
                if last_exc:
                    logger.warning("LLM stream exhausted retries (model=%s provider=%s): %s", model_name, provider, last_exc)
                yield ""
                return

        in_think = False
        try:
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    text = delta.content
                    if "<think>" in text:
                        in_think = True
                        continue
                    if "</think>" in text:
                        in_think = False
                        continue
                    if in_think:
                        continue
                    yield text
        except Exception as exc:
            logger.warning("LLM stream interrupted (model=%s provider=%s kind=%s): %s", model_name, provider, self._error_kind(exc), exc)
            yield ""

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
        result = _extract_json_obj(raw)
        if not result and raw:
            logger.warning("chat_json: failed to parse JSON from LLM response (len=%d): %.200s", len(raw), raw)
        return result

    def chat_text(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        client, model_name = self._resolve_client_and_model(model)
        if client is None:
            return ""
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
        except Exception as exc:
            logger.warning("LLM call failed (model=%s): %s", model_name, exc)
            return ""
        return ""
