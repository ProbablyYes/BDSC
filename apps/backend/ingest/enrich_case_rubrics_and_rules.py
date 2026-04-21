from __future__ import annotations

"""Offline enrichment script for case_structured JSON files.

This script reads teacher_examples metadata and existing structured case JSON
files, then for each case:

- Builds a flattened text view of the project (project_profile + evidence + summary)
  using the same policy as the RAG engine.
- Runs the diagnosis engine's 15-rule (H1-H15) + 9-rubric heuristic on that text
  (without calling any LLM).
- Writes back:
  - ``risk_flags``: list of triggered RiskRule IDs (e.g. ["H1", "H5"]).
  - ``rubric_coverage``: one entry per rubric dimension with a boolean ``covered``.
  - ``tags``: refreshed ``rubric:*`` and ``risk_rule:*`` tags aligned with the
    new diagnostics (other tags are preserved).

Usage (from workspace root):

    python -m ingest.enrich_case_rubrics_and_rules \
        --min-quality B \
        --max-cases 0 \
        --category 教育服务 --category 医疗健康

If no arguments are given, all cases that already have structured JSON files
under ``data/graph_seed/case_structured`` and are marked ``include_in_kg`` in
metadata.csv will be processed.
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from app.config import settings
from app.services.llm_client import LlmClient
from app.services.rag_engine import _build_search_text
from ingest.common import bool_from_csv
from ingest.extract_case_struct import read_metadata, make_case_id


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Enrich structured cases with 9-dimension RubricItem coverage "
            "and 15 RiskRule / HITS_RULE flags, based on metadata + case JSON."
        )
    )
    parser.add_argument(
        "--case-json",
        type=str,
        default=None,
        help="指定单个 case_*.json 文件，仅处理该文件（优先级最高）",
    )
    parser.add_argument(
        "--min-quality",
        choices=["A", "B"],
        default="B",
        help="Minimum parse_quality from metadata to include (A only, or A/B).",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=0,
        help="Optional limit for processed cases (0 means all).",
    )
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        help="Only process selected categories (metadata.category). Can repeat.",
    )
    parser.add_argument(
        "--llm-model",
        default="Qwen/Qwen2.5-72B-Instruct",
        help=(
            "Override model name for Rubric/RiskRule extraction. "
            "Default uses Qwen/Qwen2.5-72B-Instruct."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Resume mode: skip cases that already contain rubric_items_detail "
            "and risk_rule_details to avoid re-running diagnostics."
        ),
    )
    return parser.parse_args(argv)


def _quality_ok(row: Dict[str, Any], min_quality: str) -> bool:
    rank = {"A": 2, "B": 1, "C": 0}.get(str(row.get("parse_quality", "C")), 0)
    min_rank = {"A": 2, "B": 1}.get(min_quality, 1)
    return rank >= min_rank


def _unique_keep_order(items: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for it in items:
        if it in seen:
            continue
        seen.add(it)
        out.append(it)
    return out


def _run_case_diagnosis(
    case: Dict[str, Any],
    llm: LlmClient,
    model_name: str,
) -> tuple[
    List[str],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
]:
    """Use Qwen LLM to extract 9-dim RubricItem coverage and 15 RiskRules.

    Returns:
        risk_flags: list of triggered rule IDs (subset of {"H1".."H15"}).
        rubric_coverage: list of {"rubric_item": name, "covered": bool}.
        rubric_items_full: normalized list of rubric_items with score/reason.
        risk_rules_full: normalized list of risk_rules with evidence/reason.
    """

    text = _build_search_text(case) or ""
    if not text.strip() or not llm.enabled:
        return [], [], [], []

    profile = case.get("project_profile", {}) or {}
    project_name = str(profile.get("project_name") or case.get("case_id") or "").strip()

    schema_hint = {
        "rubric_items": [
            {
                "item": "Problem Definition",
                "covered": True,
                "score": 0,
                "reason": "string",
            }
        ],
        "risk_rules": [
            {
                "id": "H1",
                "triggered": True,
                "severity": "high|medium|low",
                "evidence": "string",
                "reason": "string",
            }
        ],
    }

    # 9 个 RubricItem 维度（名称需与图谱/前端保持一致）
    rubric_desc = (
        "1) Problem Definition (R1 痛点定义)：需求是否真实、具体，有无用户场景支撑。\n"
        "2) User Evidence Strength (R2 用户证据强度)：是否给出访谈/问卷/行为数据等原始证据。\n"
        "3) Solution Feasibility (R3 方案可行性)：技术路线与资源是否匹配，是否存在过度设计。\n"
        "4) Business Model Consistency (R4 商业模式一致性)：客户、价值主张、渠道、营收、成本是否形成闭环。\n"
        "5) Market & Competition (R5 市场与竞争)：TAM/SAM/SOM 口径是否合理，竞品分析是否客观。\n"
        "6) Financial Logic (R6 财务逻辑)：单位经济是否成立，是否存在 LTV < CAC 等问题。\n"
        "7) Innovation & Differentiation (R7 创新与差异化)：是否有可验证的竞争优势或差异化。\n"
        "8) Team & Execution (R8 团队与执行)：团队能力是否匹配目标，里程碑是否清晰可交付。\n"
        "9) Presentation Quality (R9 材料展示质量)：BP/路演结构是否完整、数据是否有说服力。"
    )

    # 15 条 RiskRule (H1-H15) 概要，用于指导判断“是否触发”。
    risk_rule_desc = (
        "H1 客户-价值主张错位：目标用户与价值主张明显不匹配。\n"
        "H2 渠道不可达：主要获客渠道难以有效触达目标用户。\n"
        "H3 定价无支付意愿证据：提到定价/收费但缺少用户支付意愿验证。\n"
        "H4 市场规模口径混乱：TAM/SAM/SOM 口径或计算逻辑混乱。\n"
        "H5 需求证据不足：缺乏用户访谈、问卷或其他需求验证证据。\n"
        "H6 竞品对比不可比：声称“无竞品/无竞争对手”或竞品分析明显失真。\n"
        "H7 创新点不可验证：强调创新/颠覆但缺少可验证的实验或指标。\n"
        "H8 单位经济不成立：根据描述可以判断 LTV <= CAC 或长期亏损。\n"
        "H9 增长逻辑跳跃：出现“只要拿下 1% 市场”等自上而下估算。\n"
        "H10 里程碑不可交付：时间表/里程碑明显不现实或缺少可交付物。\n"
        "H11 合规/伦理缺口：涉及隐私/医疗/金融等高风险领域却缺少合规说明。\n"
        "H12 技术路线与资源不匹配：技术方案对算力/硬件/人才要求远超项目现状。\n"
        "H13 实验设计不合格：提到实验/测试但缺少样本量与评价指标。\n"
        "H14 路演叙事断裂：叙事结构残缺或跳跃，无法形成完整故事线。\n"
        "H15 评分项证据覆盖不足：多个关键 Rubric 维度缺乏支撑证据。"
    )

    system_prompt = (
        "你是“双创智能体知识库”的 Rubric 与 RiskRule 抽取助手。"
        "任务：根据给定的项目文本，判断 9 个 Rubric 维度是否有足够证据被视为“已覆盖”，"
        "并判断 15 条 RiskRule (H1-H15) 中哪些在文本中被触发。"
        "你必须严格只依据提供的文本，不得引入外部常识或编造信息。"
        "RubricItems 与 RiskRules 的含义如下：\n"
        f"RubricItems:\n{rubric_desc}\n"
        f"RiskRules:\n{risk_rule_desc}\n"
        "输出必须是一个 JSON 对象，键名固定为 rubric_items 和 risk_rules，"
        "其结构需与 schema_hint 一致，不要新增或删除顶层键。"
        "rubric_items 中每个元素对应一个 Rubric 维度（item 字段必须是上述 9 个名称之一），"
        "需要给出 covered 布尔值（是否认为该维度已有较充分证据）以及 0-10 的 score 和简短 reason。"
        "risk_rules 中必须包含 H1-H15 每条规则各一个元素，id 为 H1..H15，"
        "triggered 表示该规则是否在文本中被触发，并给出 severity、代表性 evidence 和简短 reason。"
    )

    user_prompt = (
        f"项目名称: {project_name}\n"
        "下面是该项目的聚合文本内容（画像字段 + 代表性原文 quote + 摘要），"
        "请据此完成 Rubric 覆盖与 RiskRule 触发判断：\n"
        f"{text}\n\n"
        "请严格按照下面给出的 JSON 结构返回最终结果（不要额外添加字段）：\n"
        f"schema_hint: {json.dumps(schema_hint, ensure_ascii=False)}"
    )

    effective_model = (
        model_name
        or settings.llm_reason_model
        or settings.llm_fast_model
        or settings.llm_model
        or "Qwen/Qwen2.5-72B-Instruct"
    )

    try:
        result = llm.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=effective_model,
            temperature=0.0,
        )
    except Exception:
        return [], [], [], []

    if not isinstance(result, dict):
        return [], [], [], []

    raw_rubric_items = result.get("rubric_items", []) or []
    raw_risk_rules = result.get("risk_rules", []) or []

    # 先做一次轻量清洗，保证保存到 JSON 里的结构是可预期的。
    rubric_items_full: List[Dict[str, Any]] = []
    for row in raw_rubric_items:
        if not isinstance(row, dict):
            continue
        name = str(row.get("item", "")).strip()
        if not name:
            continue
        rubric_items_full.append(
            {
                "item": name,
                "covered": bool(row.get("covered", False)),
                "score": float(row.get("score", 0.0)) if isinstance(row.get("score"), (int, float)) else 0.0,
                "reason": str(row.get("reason", "")),
            }
        )

    risk_rules_full: List[Dict[str, Any]] = []
    for row in raw_risk_rules:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id", "")).strip()
        if not rid or not (rid.startswith("H") and rid[1:].isdigit()):
            continue
        risk_rules_full.append(
            {
                "id": rid,
                "triggered": bool(row.get("triggered", False)),
                "severity": str(row.get("severity", "")),
                "evidence": str(row.get("evidence", "")),
                "reason": str(row.get("reason", "")),
            }
        )

    # 解析 RiskRule：只保留被判定为触发的 H1-H15 规则 ID。
    risk_ids: List[str] = []
    for item in risk_rules_full:
        if not bool(item.get("triggered", False)):
            continue
        rid = str(item.get("id", "")).strip()
        if not rid:
            continue
        risk_ids.append(rid)
    risk_flags = sorted(_unique_keep_order(risk_ids))

    # 解析 Rubric 覆盖情况。
    rubric_coverage: List[Dict[str, Any]] = []
    for row in rubric_items_full:
        name = str(row.get("item", "")).strip()
        if not name:
            continue
        covered = bool(row.get("covered", False))
        rubric_coverage.append({"rubric_item": name, "covered": covered})

    return risk_flags, rubric_coverage, rubric_items_full, risk_rules_full


def _refresh_tags(
    original_tags: Any,
    rubric_coverage: List[Dict[str, Any]],
    risk_flags: List[str],
) -> List[str]:
    # Normalize existing tags to a flat list of strings.
    tags: List[str]
    if isinstance(original_tags, list):
        tags = [str(t) for t in original_tags]
    elif original_tags is None:
        tags = []
    else:
        tags = [str(original_tags)]

    # Drop legacy rubric:* / risk_rule:* tags; keep everything else.
    kept: List[str] = [
        t for t in tags if not (t.startswith("rubric:") or t.startswith("risk_rule:"))
    ]

    # Add rubric:* tags for covered dimensions.
    for rc in rubric_coverage:
        if not rc.get("covered"):
            continue
        name = str(rc.get("rubric_item", "")).strip()
        if not name:
            continue
        kept.append(f"rubric:{name}")

    # Add risk_rule:* tags for triggered RiskRule IDs.
    for rid in risk_flags:
        kept.append(f"risk_rule:{rid}")

    return _unique_keep_order(kept)


def enrich_cases(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    metadata_path = settings.teacher_examples_root / "metadata.csv"
    case_dir = settings.data_root / "graph_seed" / "case_structured"

    llm = LlmClient()
    if not llm.enabled:
        print("LLM disabled: missing llm_api_key/llm_base_url; aborting enrichment.")
        return

    # 新增：如指定 --case-json，仅处理该文件
    if args.case_json:
        case_path = Path(args.case_json)
        if not case_path.exists():
            print(f"指定的 case_json 文件不存在: {case_path}")
            return
        try:
            case_data = json.loads(case_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"读取 case_json 失败: {exc}")
            return
        risk_flags, rubric_coverage, rubric_items_full, risk_rules_full = _run_case_diagnosis(
            case_data,
            llm=llm,
            model_name=args.llm_model,
        )
        if not risk_flags and not rubric_coverage:
            print("skip (no diagnostic signal)")
            return
        case_data["risk_flags"] = risk_flags
        case_data["rubric_coverage"] = rubric_coverage
        case_data["rubric_items_detail"] = rubric_items_full
        case_data["risk_rule_details"] = risk_rules_full
        case_data["tags"] = _refresh_tags(
            case_data.get("tags", []), rubric_coverage=rubric_coverage, risk_flags=risk_flags
        )
        case_path.write_text(
            json.dumps(case_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"updated {case_path.name} | risks={len(risk_flags)}, rubrics={len(rubric_coverage)}")
        print("rubric/risk enrichment done.")
        return

    # 默认批量模式
    rows = read_metadata(metadata_path)
    included: List[Dict[str, Any]] = []
    for row in rows:
        if not bool_from_csv(row.get("include_in_kg", "true"), default=True):
            continue
        if not _quality_ok(row, args.min_quality):
            continue
        if args.category and row.get("category", "") not in set(args.category):
            continue
        included.append(row)

    if args.max_cases and args.max_cases > 0:
        included = included[: args.max_cases]

    total = len(included)
    processed = 0
    missing = 0
    skipped_text = 0
    resumed_existing = 0

    print(
        f"starting rubric/risk enrichment: {total} metadata rows "
        f"(min_quality={args.min_quality})",
        flush=True,
    )

    for idx, row in enumerate(included, start=1):
        file_path = row.get("file_path", "")
        if not file_path:
            continue
        case_id = make_case_id(file_path)
        case_path = case_dir / f"{case_id}.json"
        if not case_path.exists():
            missing += 1
            print(f"[{idx}/{total}] missing case JSON for {file_path} ({case_id})", flush=True)
            continue

        try:
            case_data = json.loads(case_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"[{idx}/{total}] failed to read {case_path.name}: {exc}", flush=True)
            continue

        # Resume mode: 若该案例已经拥有 rubric_items_detail 和 risk_rule_details，
        # 视为诊断完成，本次跳过，避免重复调用 LLM。
        if getattr(args, "resume", False):
            existing_rubrics = case_data.get("rubric_items_detail")
            existing_rules = case_data.get("risk_rule_details")
            if (
                isinstance(existing_rubrics, list)
                and existing_rubrics
                and isinstance(existing_rules, list)
                and existing_rules
            ):
                resumed_existing += 1
                print(
                    f"[{idx}/{total}] resume-skip existing diagnostics for {file_path} ({case_id})",
                    flush=True,
                )
                continue

        risk_flags, rubric_coverage, rubric_items_full, risk_rules_full = _run_case_diagnosis(
            case_data,
            llm=llm,
            model_name=args.llm_model,
        )
        if not risk_flags and not rubric_coverage:
            skipped_text += 1
            print(
                f"[{idx}/{total}] skip (no diagnostic signal) {file_path}",
                flush=True,
            )
            continue

        case_data["risk_flags"] = risk_flags
        case_data["rubric_coverage"] = rubric_coverage
        # 额外保存 LLM 的完整评分与规则详情，便于前端与后续分析使用。
        case_data["rubric_items_detail"] = rubric_items_full
        case_data["risk_rule_details"] = risk_rules_full
        case_data["tags"] = _refresh_tags(
            case_data.get("tags", []), rubric_coverage=rubric_coverage, risk_flags=risk_flags
        )

        case_path.write_text(
            json.dumps(case_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        processed += 1
        print(
            f"[{idx}/{total}] updated {case_path.name} | "
            f"risks={len(risk_flags)}, rubrics={len(rubric_coverage)}",
            flush=True,
        )

    print("rubric/risk enrichment done.")
    print("metadata rows considered:", total)
    print("cases updated:", processed)
    print("missing case JSON:", missing)
    print("no-text/empty diagnostics:", skipped_text)
    print("resume-skipped existing diagnostics:", resumed_existing)


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - CLI entry
    enrich_cases(argv)


if __name__ == "__main__":  # pragma: no cover
    main()
