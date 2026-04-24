"""
竞赛 / 答辩评委角色卡库（Judge Persona Bank）。

设计目标：
- advisor / competition pipeline 在 system prompt 里只放一份"角色目录"（
  避免把所有 persona 全文塞进 prompt，体积失控），运行时按学生指令或
  competition_type 自动挑一位评委，把完整 persona 拼进当轮 system prompt。
- 学生可在消息里写"请扮演 X"或"切到 X 视角"主动指定评委；也可以由
  pick_judge 按 competition_type 给一个默认。
- 选中的 judge.id 会写到 agent_trace.competition.active_judge，前端可视化、
  脚本可断言。

数据来源：apps/backend/config/competition_judges.json
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import settings


@dataclass
class JudgePersona:
    id: str
    name: str
    archetype: str = ""
    focus: list[str] = field(default_factory=list)
    tone: str = ""
    trigger_keywords: list[str] = field(default_factory=list)
    signature_questions: list[str] = field(default_factory=list)
    killer_metrics: list[str] = field(default_factory=list)
    typical_pitfalls: list[str] = field(default_factory=list)


@dataclass
class JudgeBank:
    judges: list[JudgePersona]
    default_by_competition: dict[str, str]

    def by_id(self, judge_id: str) -> JudgePersona | None:
        for j in self.judges:
            if j.id == judge_id:
                return j
        return None


def _judges_config_path() -> Path:
    """
    优先 apps/backend/config/competition_judges.json，
    其次 BDSC/config/competition_judges.json（兼容潜在的全局覆盖）。
    """
    backend_path = settings.workspace_root / "apps" / "backend" / "config" / "competition_judges.json"
    if backend_path.exists():
        return backend_path
    return settings.workspace_root / "config" / "competition_judges.json"


@lru_cache(maxsize=1)
def load_judges() -> JudgeBank:
    """读取并缓存评委角色卡库。读取失败时返回空库，不阻断主流程。"""
    path = _judges_config_path()
    try:
        if not path.exists():
            return JudgeBank(judges=[], default_by_competition={})
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return JudgeBank(judges=[], default_by_competition={})

    raw_judges = data.get("judges") or []
    judges: list[JudgePersona] = []
    for item in raw_judges:
        if not isinstance(item, dict):
            continue
        try:
            judges.append(JudgePersona(
                id=str(item.get("id") or "").strip(),
                name=str(item.get("name") or "").strip(),
                archetype=str(item.get("archetype") or "").strip(),
                focus=list(item.get("focus") or []),
                tone=str(item.get("tone") or "").strip(),
                trigger_keywords=list(item.get("trigger_keywords") or []),
                signature_questions=list(item.get("signature_questions") or []),
                killer_metrics=list(item.get("killer_metrics") or []),
                typical_pitfalls=list(item.get("typical_pitfalls") or []),
            ))
        except Exception:  # noqa: BLE001
            continue
    judges = [j for j in judges if j.id]

    defaults = data.get("default_by_competition") or {}
    if not isinstance(defaults, dict):
        defaults = {}
    return JudgeBank(judges=judges, default_by_competition={str(k): str(v) for k, v in defaults.items()})


# ── 显式选择指令识别 ────────────────────────────────────────────────

# 学生主动指定评委的常见说法
_EXPLICIT_PATTERNS = [
    re.compile(r"请?(?:扮演|当|做)\s*(?:一个|一位|一名)?\s*([^\s,，。.；;]+?)(?:评委|视角|角色|口吻)?[，,。.！!？\?]"),
    re.compile(r"切到\s*([^\s,，。.；;]+?)\s*(?:评委|视角|角色|口吻)"),
    re.compile(r"用\s*([^\s,，。.；;]+?)\s*(?:的)?\s*(?:视角|口吻|角度)"),
    re.compile(r"模拟\s*([^\s,，。.；;]+?)\s*(?:评委|视角|角色)"),
    re.compile(r"以\s*([^\s,，。.；;]+?)\s*的(?:身份|角度|视角)"),
]


def _match_judge_by_keywords(message: str, bank: JudgeBank) -> JudgePersona | None:
    if not message:
        return None
    msg_lower = message.lower()
    best: tuple[int, JudgePersona] | None = None
    for j in bank.judges:
        score = 0
        for kw in j.trigger_keywords:
            if not kw:
                continue
            if kw.lower() in msg_lower:
                score += len(kw)
        if score > 0 and (best is None or score > best[0]):
            best = (score, j)
    return best[1] if best else None


def parse_explicit_judge(message: str, bank: JudgeBank | None = None) -> JudgePersona | None:
    """
    检测学生消息里是否显式指定了一个评委角色。
    - "请扮演激进型 VC" / "切到银行家视角" / "用合规官的角度" 等
    - 命中后用候选名片的 trigger_keywords 二次匹配，避免误识别普通名词。
    """
    if not message:
        return None
    if bank is None:
        bank = load_judges()
    if not bank.judges:
        return None

    # 1) 用模式抽出"角色名候选"
    candidates: list[str] = []
    for pat in _EXPLICIT_PATTERNS:
        for m in pat.finditer(message):
            text = (m.group(1) or "").strip()
            if 1 <= len(text) <= 12:
                candidates.append(text)

    # 2) 候选名 → 反查 judge（按 trigger_keywords / name 包含）
    for cand in candidates:
        cand_low = cand.lower()
        for j in bank.judges:
            if cand_low in j.name.lower():
                return j
            for kw in j.trigger_keywords:
                if kw and kw.lower() in cand_low:
                    return j

    return None


def pick_judge(
    message: str,
    *,
    mode: str = "",
    competition_type: str = "",
    sticky_judge_id: str = "",
    bank: JudgeBank | None = None,
) -> JudgePersona | None:
    """
    挑选当轮要注入到 advisor system prompt 的评委。
    优先级：
      1) 学生本轮显式指定（"请扮演 X"）
      2) 学生本轮关键词强信号（如直接说"VC""银行家"）
      3) sticky_judge_id（上一轮命中且未被覆盖）
      4) competition_type 默认值
      5) None（advisor 走通用 advisor system prompt，不注入 persona）

    仅在 mode == "competition" 时启用 4)；其余场景需要 1)/2)/3) 才返回。
    """
    if bank is None:
        bank = load_judges()
    if not bank.judges:
        return None

    explicit = parse_explicit_judge(message, bank)
    if explicit is not None:
        return explicit

    keyword_hit = _match_judge_by_keywords(message, bank)
    if keyword_hit is not None:
        return keyword_hit

    if sticky_judge_id:
        sticky = bank.by_id(sticky_judge_id)
        if sticky is not None:
            return sticky

    if mode == "competition" and competition_type:
        default_id = bank.default_by_competition.get(competition_type, "")
        if default_id:
            default_j = bank.by_id(default_id)
            if default_j is not None:
                return default_j

    return None


# ── Prompt 拼接 ─────────────────────────────────────────────────────

def format_judge_for_advisor(judge: JudgePersona, max_chars: int = 700) -> str:
    """
    把一位评委 persona 拼成可注入到 advisor system prompt 的角色卡块。
    控制总长度避免吃掉 advisor 主 prompt 的预算。
    """
    if judge is None:
        return ""

    sigs = "\n".join(f"  - {q}" for q in judge.signature_questions[:4])
    metrics = "、".join(judge.killer_metrics[:5])
    pitfalls = "、".join(judge.typical_pitfalls[:3])
    focus = "、".join(judge.focus[:5])

    block = (
        f"【本轮答辩评委角色 · {judge.name}】\n"
        f"画像：{judge.archetype}\n"
        f"语气：{judge.tone}\n"
        f"重点关注：{focus}\n"
        f"杀手级问题（按这位评委的口径自然提问，不要照搬原话）：\n{sigs}\n"
        f"必看指标：{metrics}\n"
        f"学生常见陷阱：{pitfalls}\n"
        "扮演要求：你这一轮整段回答都用这位评委的口吻和关注点追问，"
        "可以引用学生原话、可以打断、但要保留教练性——每个尖锐问题之后给一句"
        "「如果我是你，我会怎么答」的安全话术，让答辩从『被问住』变成『学会答』。"
    )
    if len(block) > max_chars:
        block = block[:max_chars - 1] + "…"
    return block


def format_judge_directory(bank: JudgeBank | None = None, max_chars: int = 600) -> str:
    """
    生成轻量"角色目录"段，用于 advisor system prompt 常驻 —— 让 LLM 知道
    可被切换到的评委有哪些（只列 id + 一行风格摘要，不展开），学生
    可以用"请扮演 X 评委"等指令触发。
    """
    if bank is None:
        bank = load_judges()
    if not bank.judges:
        return ""
    lines = [f"- {j.id} · {j.name}：{j.archetype[:50]}" for j in bank.judges]
    block = (
        "【可切换的答辩评委角色目录】（学生说『请扮演 X』『切到 X 视角』即可主动切换）\n"
        + "\n".join(lines)
    )
    if len(block) > max_chars:
        block = block[:max_chars - 1] + "…"
    return block


def all_judge_ids(bank: JudgeBank | None = None) -> list[str]:
    if bank is None:
        bank = load_judges()
    return [j.id for j in bank.judges]
