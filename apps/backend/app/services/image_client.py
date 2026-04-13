from __future__ import annotations

import base64
import logging
import random
import time
from pathlib import Path

from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class ImageClient:
    """Thin wrapper around OpenAI-compatible image generation API.

    Currently wired to the same SiliconFlow-compatible endpoint as LlmClient.
    """

    def __init__(self) -> None:
        self.enabled = bool(settings.llm_api_key and settings.llm_base_url and settings.llm_image_model)
        self._client: OpenAI | None = None
        if self.enabled:
            self._client = OpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                timeout=240.0,
                max_retries=1,
            )

    def generate_poster_image(
        self,
        *,
        prompt: str,
        project_id: str,
        size: str | None = None,
        out_root: Path | None = None,
    ) -> str:
        """Generate a single illustration image and persist it under upload_root.

        Returns a URL path that can be served via FastAPI StaticFiles (e.g. "/uploads/...").
        """

        if not self.enabled or self._client is None:
            raise RuntimeError("ImageClient is not enabled or configured")

        prompt = (prompt or "").strip()
        if not prompt:
            raise ValueError("prompt must not be empty")

        img_size = (size or "1024x576").strip() or "1024x576"

        try:
            # Prefer base64 格式，便于落盘；如果服务端仅返回 url，也能兜底处理
            resp = self._client.images.generate(
                model=settings.llm_image_model,
                prompt=prompt,
                size=img_size,
                n=1,
                response_format="b64_json",
            )
        except Exception as exc:  # pragma: no cover - network / policy errors are logged and surfaced
            # 部分模型（如图像模型）在命中内容安全策略时会返回 451 / code=20021 等错误；
            # 这里统一转换为 RuntimeError，供上层 API 以友好文案返回给前端。
            msg = str(exc)
            if "20021" in msg or "prohibited or sensitive content" in msg or "status code: 451" in msg:
                logger.warning(
                    "Image generation content-moderation blocked (model=%s): %s",
                    settings.llm_image_model,
                    exc,
                )
                raise RuntimeError("图像生成被模型的内容安全策略拦截，请稍微调整提示词后重试。")

            logger.warning("Image generation failed (model=%s): %s", settings.llm_image_model, exc)
            raise

        data_item = resp.data[0]

        # OpenAI SDK v1: data_item 是 pydantic 模型，属性访问 b64_json / url
        b64 = getattr(data_item, "b64_json", None)
        if not b64:
            # 部分兼容实现可能只返回 url；此时直接把远端 url 透传给前端
            url = getattr(data_item, "url", None)
            if isinstance(url, str) and url:
                return url
            logger.warning("Image generation response missing both b64_json and url")
            raise RuntimeError("图像生成接口返回格式不符合预期，缺少 b64_json/url 字段")

        try:
            binary = base64.b64decode(b64)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to decode image base64: %s", exc)
            raise

        base_dir = out_root or (settings.upload_root / "poster_images")
        project_dir = base_dir / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        filename = f"poster_{int(time.time())}_{random.randint(1000, 9999)}.png"
        out_path = project_dir / filename
        out_path.write_bytes(binary)

        # Build URL under existing /uploads mount
        rel_path = out_path.relative_to(settings.upload_root).as_posix()
        return f"/uploads/{rel_path}"
