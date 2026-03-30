from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable
import re

from app.services.document_parser import ParsedDocument

SUPPORTED_DOC_SUFFIXES = {".pdf", ".pptx", ".ppt", ".docx", ".txt", ".md"}
# support ppt
APPENDIX_KEYWORDS = [
    "附录",
    "附件",
    "证明材料",
    "佐证材料",
    "补充材料",
    "支撑材料",
    "截图",
    "evidence",
    "appendix",
    "supplementary",
]


# 比赛抬头/图号等前缀清洗用的正则
FIGURE_PREFIX_RE = re.compile(r"^图\s*\d+[-－—–\.．]\d+\s*")
CHALLENGE_CUP_RE = re.compile(r"挑战杯.*?竞赛")


def now_iso() -> str:
    # Use timezone-aware UTC timestamp to avoid deprecation warnings.
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_rel_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def detect_category(rel_path: Path) -> str:
    # Root-level files are treated as uncategorized records.
    return rel_path.parts[0] if len(rel_path.parts) > 1 else "未分类"


def bool_from_csv(value: str, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def detect_appendix_start(parsed: ParsedDocument) -> int | None:
    for segment in parsed.segments:
        low = segment.text.lower()
        if any(k.lower() in low for k in APPENDIX_KEYWORDS):
            return segment.index
    return None


def parse_quality(parsed: ParsedDocument) -> tuple[str, str]:
    chars = parsed.text_chars
    seg_count = parsed.segment_count
    if chars == 0 or seg_count == 0:
        return "C", "文档几乎未提取到有效文本，疑似扫描件或受保护文件。"

    short_segments = [s for s in parsed.segments if len(s.text.strip()) < 30]
    short_ratio = len(short_segments) / max(seg_count, 1)

    if parsed.doc_type == "pdf" and short_ratio > 0.7 and seg_count >= 8:
        return "C", "PDF 页面大多为低文本密度，疑似截图附录占比过高。"
    if chars < 300 or seg_count < 3:
        return "C", "文本量不足，难以支撑结构化抽取。"
    if chars < 1800 or short_ratio > 0.5:
        return "B", "可提取文本有限，建议人工复核关键字段。"
    return "A", "文本质量良好，可用于自动结构化抽取。"


def _cleanup_spaces(text: str) -> str:
    """清理句子内部“莫名其妙的空格”。

    - 折叠连续空格/Tab 为单个空格；
    - 去掉两个汉字之间多余的空格；
    - 去掉标点前面的空格。
    """

    if not text:
        return ""
    s = str(text)
    # 折叠普通空白（但不包含换行）
    s = re.sub(r"[ \t]+", " ", s)
    # 汉字之间的空格通常是 PDF 断字噪声
    s = re.sub(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])", r"\1\2", s)
    # 标点前不保留空格
    s = re.sub(r"\s+([，。！？；,.!?])", r"\1", s)
    return s.strip()


def _strip_competition_prefix(text: str) -> str:
    """去掉图号和“挑战杯…竞赛”这类比赛抬头前缀，只保留后面的实质内容。
    这类前缀在结构化抽取时反而是噪声，且不具有通用意义。"""

    if not text:
        return ""
    s = str(text).strip()

    # 1) 去掉开头的图号，例如“图1-1 ”、“图 2.3 ”
    s = FIGURE_PREFIX_RE.sub("", s)

    # 2) 若包含“挑战杯 … 竞赛”，只保留竞赛后面的正文
    if "挑战杯" in s and "竞赛" in s:
        m = CHALLENGE_CUP_RE.search(s)
        if m:
            idx = m.end()
            # 跳过紧跟其后的空格、标点及数字等
            while idx < len(s) and s[idx] in " 　\t：:，,。.!?？；;、0123456789-—–()（）\"“”‘’":
                idx += 1
            if idx < len(s):
                s = s[idx:].lstrip()

    return s


def split_lines(text: str) -> list[str]:
    """按语义做句子级切分，处理跨行句子，并清理异常空格。

    约定：
    - 不再简单按换行切分，而是综合句末标点 + 换行做 NLP 式句子分割；
    - 对于被硬换行拆断的单句，自动将换行视为空格合并；
    - 仅在句内合并换行，不会修改原始文档保存的换行（只影响返回的句子片段）。
    """

    if not text:
        return []

    # 统一换行符，但不直接丢弃换行，用于后续判断“跨行句子”
    raw = str(text).replace("\r\n", "\n").replace("\r", "\n")
    # 逐行先做一次空格清理，避免“创 新 创 业”这类噪声
    lines = raw.split("\n")
    cleaned_lines = [_cleanup_spaces(line) for line in lines]
    merged = "\n".join(cleaned_lines)

    # 将“句内换行”视为空格，将“段落换行”保留为分段标记
    chars: list[str] = []
    end_punct = "。！？!?；;"
    i = 0
    n = len(merged)
    while i < n:
        ch = merged[i]
        if ch == "\n":
            # 找到换行前一个非换行字符
            j = len(chars) - 1
            prev = ""
            while j >= 0:
                if chars[j] != "\n" and not chars[j].isspace():
                    prev = chars[j]
                    break
                j -= 1

            # 找到换行后第一个非空白字符
            k = i + 1
            while k < n and merged[k] in {" ", "\t", "\n"}:
                k += 1
            frag = merged[k : k + 8] if k < n else ""

            # 粗略判断：下一行是否像新的条目/标题（避免错误合并列表项）
            is_heading_like = bool(re.match(r"^\s*([0-9]{1,2}|[一二三四五六七八九十])[、.．)]", frag))

            if prev and prev not in end_punct and not is_heading_like:
                # 视为句内换行：合并为一个空格
                if chars and chars[-1] not in {" ", "\n"}:
                    chars.append(" ")
            else:
                # 段落/列表换行：保留为换行标记
                if not chars or chars[-1] != "\n":
                    chars.append("\n")
            i += 1
            continue

        chars.append(ch)
        i += 1

    resolved = "".join(chars).strip()
    if not resolved:
        return []

    # 使用正则按句末标点或段落换行切分，保留标点本身
    sentence_pattern = re.compile(r"[^。！？!?；;\n]*[。！？!?；;\n]")
    sentences: list[str] = []
    last_end = 0
    for match in sentence_pattern.finditer(resolved):
        seg = match.group(0).strip()
        if not seg:
            last_end = match.end()
            continue
        # 最终句子内部不保留换行
        seg = _cleanup_spaces(seg.replace("\n", " "))
        seg = _strip_competition_prefix(seg)
        if seg:
            sentences.append(seg)
        last_end = match.end()

    # 处理结尾没有句号/换行收尾的残留文本
    if last_end < len(resolved):
        tail = _cleanup_spaces(resolved[last_end:].replace("\n", " "))
        if tail:
            sentences.append(tail)

    return sentences


def unique_keep_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = item.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out
