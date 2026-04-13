from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.diagnosis_engine import _get_rubrics, _llm_rubric_score, _score_band
from app.services.llm_client import LlmClient
from app.services.speech_to_text_client import SpeechToTextClient

logger = logging.getLogger(__name__)


class VideoPitchAnalyzer:
    """Analyze a short pitch video and return rubric-style scores.

    Design goals:
    - Keep completely separate from多智能体对话工作流，不写入 agent_trace
    - 只依赖语音内容（逐字稿），使用现有 RUBRICS + 打分区间
    - 适配现有前端评分面板的数据结构，便于共用 UI 组件
    """

    def __init__(self) -> None:
        self._stt = SpeechToTextClient()
        self._llm = LlmClient()

    @staticmethod
    def _validate_file(path: Path) -> None:
        ext = path.suffix.lower()
        allowed = [e.lower() for e in (settings.video_allowed_ext or [])]
        if allowed and ext not in allowed:
            raise ValueError("不支持的文件格式，请上传 mp4/mov/webm 等常见视频格式。")

        try:
            size_mb = path.stat().st_size / (1024 * 1024)
        except OSError as exc:  # noqa: BLE001
            logger.warning("Failed to stat video file %s: %s", path, exc)
            return
        if size_mb > settings.video_max_mb:
            raise ValueError(
                f"视频文件过大（约 {size_mb:.1f}MB），请控制在 {settings.video_max_mb:.0f}MB 以内。"
            )

    def analyze(
        self,
        *,
        video_path: Path,
        mode: str = "competition",
        competition_type: str = "",
        filename: str = "",
        context_text: str = "",
    ) -> dict[str, Any]:
        """Run end-to-end analysis for one pitch video.

        Returns a dict that matches VideoAnalysisResult in schemas.py.
        """

        self._validate_file(video_path)

        # 大模型必须可用；语音转写可选（静音视频仍然可以只基于文本上下文进行分析）
        if not self._llm.enabled:
            raise RuntimeError("系统暂未启用大模型，无法完成视频分析。")

        transcript = ""
        if self._stt.enabled:
            try:
                transcript = self._stt.transcribe(video_path)
            except RuntimeError as exc:
                # 对于“无音轨/无法解码音频”的情况，不中断分析，改为仅基于文本上下文给出建议
                root = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
                msg = f"{exc!s} {root!s}" if root is not None else str(exc)
                lower_msg = msg.lower()
                if "no supported audio tracks found" in lower_msg or "failed to decode audio" in lower_msg:
                    logger.info("Video %s has no decodable audio track; falling back to context-only analysis.", video_path)
                    transcript = ""
                else:
                    # 其他类型的 STT 错误仍然认为是系统配置问题，按原有逻辑抛出
                    raise

        clean_transcript = " ".join(str(transcript or "").split())

        # 复用诊断引擎中的 LLM Rubric 打分逻辑，确保维度与区间完全一致。
        # 此处在语音逐字稿前拼接一段“当前对话与项目诊断”的精简摘要，
        # 让评分既考虑路演口头表达，也兼顾学生在对话中已提供的项目信息。
        # 若没有可用逐字稿，则仅使用项目/对话摘要或通用提示语作为评分依据
        combined_for_scoring = clean_transcript
        ctx = (context_text or "").strip()
        if ctx:
            combined_for_scoring = (ctx[:1500] + "\n\n[Pitch Transcript]\n" + clean_transcript)[:4000]
        elif not clean_transcript:
            combined_for_scoring = (
                "学生上传了一个几乎没有可识别语音内容的路演视频。\n"
                "请仅基于一般的创业比赛路演规范，给出各评分维度的大致水平判断和改进建议。"
            )

        llm_scores = _llm_rubric_score(combined_for_scoring, mode) or []
        active_rubrics = _get_rubrics(competition_type)
        llm_map = {str(s.get("item")): s for s in llm_scores if isinstance(s, dict) and s.get("item")}

        rubric: list[dict[str, Any]] = []
        weighted_total = 0.0
        total_weight = 0.0

        for row in active_rubrics:
            item = str(row["item"])
            weight = float(row.get("weight", 0.0) or 0.0)
            src = llm_map.get(item)
            if src:
                dim_score = max(0.0, min(10.0, float(src.get("score", 5.0))))
                reason = str(src.get("reason") or "")
            else:
                dim_score = 5.0
                reason = ""
            status = "risk" if dim_score < 5.0 else "ok"
            rubric.append(
                {
                    "item": item,
                    "score": round(dim_score, 2),
                    "weight": weight,
                    "status": status,
                    "reason": reason,
                }
            )
            weighted_total += dim_score * weight
            total_weight += weight

        overall_score = round(weighted_total / total_weight, 2) if total_weight else 0.0
        score_band = _score_band(overall_score)

        # 生成一段针对“表达与路演表现”的中文点评（较长、分段、贴合既有诊断指标）
        feedback = ""
        try:
            prompt_parts: list[str] = []
            if ctx:
                prompt_parts.append("【项目与对话摘要】" + ctx[:800])
            if clean_transcript:
                prompt_parts.append("【路演逐字稿】" + clean_transcript[:3600])
            else:
                prompt_parts.append(
                    "【路演逐字稿】(当前视频未检测到可用语音内容，本次点评将主要依据项目文字信息和通用路演规范给出建议。)"
                )
            feedback = self._llm.chat_text(
                system_prompt=(
                    "你是一位创业比赛的中文评委，擅长用自然、口语化的中文点评学生的路演表现。\n"
                    "上文的\"项目与对话摘要\"中，包含了 AI 之前给出的诊断结论、评分维度和改进建议；"
                    "请把这些内容视为本次路演的'评分标准'，但不要去评论这些文字本身，也不要复述对话细节，只需要在心里把它们当成评判标准。\n"
                    "你的点评要专注于这次路演视频本身的表现：根据路演逐字稿，判断学生在表达结构、逻辑连贯性、语气与自信度、数据和证据的使用等方面，"
                    "是否达到了这些标准，哪些维度已经比较接近，哪些仍然有明显差距。\n"
                    "注意：你只能看到文字逐字稿，无法真正看到视频画面，但可以基于一般优秀路演的标准，给出关于镜头感、眼神交流、站姿和手势的通用建议，"
                    "不要假装自己真的看到了具体画面细节，也不要直接引用学生在文字对话中的原话或 AI 的原始建议。\n"
                    "输出要求：\\n"
                    "1. 用第二人称和学生说话，像人类老师一样自然交流，不要刻意罗列'优点'、'缺点'等小标题，也不要提到'在前面的对话中'、'根据之前 AI 的建议'之类的表述。\\n"
                    "2. 尽量写成 8-10 段连续的中文自然段，总字数大约 800-1200 字（尽量接近 1000 字），每段 2-4 句，方便阅读。\\n"
                    "3. 不要使用编号（如 1. 2. 3.）或项目符号，也不要使用任何 Markdown 语法（包括 **加粗**、# 标题、- 列表等），只用普通中文标点。\\n"
                    "4. 语气具体、诚恳，既指出可以改进的地方，也明确告诉学生已经做得不错的地方，并在最后自然地给出下一次路演可以优先改进的 1-2 个方向。"
                ),
                user_prompt="\n\n".join(prompt_parts),
                temperature=0.35,
            ).strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Video presentation feedback generation failed: %s", exc)

        if clean_transcript:
            summary = (
                "已基于路演视频的语音内容和当前项目上下文完成一次 Rubric 评分；"
                "分数仅反映当前讲述内容与结构，不代表最终比赛成绩。"
            )
        else:
            summary = (
                "当前视频未检测到清晰的语音内容，本次评分主要参考你的项目文字描述与对话上下文，"
                "结果仅作演练和改进方向参考。"
            )

        return {
            "overall_score": overall_score,
            "score_band": score_band,
            "rubric": rubric,
            "transcript": clean_transcript[:12000],
            "summary": summary,
            "presentation_feedback": feedback,
            "mode": mode,
            "competition_type": competition_type,
            "source_filename": filename,
        }
