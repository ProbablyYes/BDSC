# evidence_refill.py
"""
对当前目录下所有 evidence 为空的 case_*.json 文件，重新提取 evidence 字段并补充到原文件。
- 仅补充 evidence 字段，不改动其他内容。
- 依赖 extract_case_struct.py 的 build_case_record 逻辑。
- 需有 LLM 支持。
"""
import json
from pathlib import Path
from .extract_case_struct import build_case_record
from app.config import settings
from app.services.llm_client import LlmClient


def refill_evidence_for_cases():
    # 处理 data/graph_seed/case_structured/ 下的 case_*.json 文件
    root = Path(__file__).parent.parent.parent.parent.resolve()
    data_dir = root / "data" / "graph_seed" / "case_structured"
    json_files = list(data_dir.glob("case_*.json"))
    llm = LlmClient()
    updated = 0
    for jf in json_files:
        try:
            with jf.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[skip] {jf.name}: load error {e}")
            continue
        if not isinstance(data, dict) or "evidence" not in data:
            continue  # 跳过无 evidence 字段
        if isinstance(data["evidence"], list) and len(data["evidence"]) > 0:
            continue  # 跳过 evidence 非空的
        # 需要补充 evidence
        row = data.get("source", {})
        if not row.get("file_path"):
            print(f"[skip] {jf.name}: missing file_path")
            continue
        try:
            case = build_case_record(
                row,
                use_llm=True,
                llm=llm,
                llm_model="",
                llm_verify=False,
            )
        except Exception as e:
            print(f"[fail] {jf.name}: build_case_record error {e}")
            continue
        if not case.get("evidence"):
            print(f"[warn] {jf.name}: still no evidence after refill")
            continue
        # 只补充 evidence 字段
        data["evidence"] = case["evidence"]
        with jf.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[ok] {jf.name}: evidence filled, {len(case['evidence'])} items")
        updated += 1
    print(f"done. updated {updated} files.")

if __name__ == "__main__":
    refill_evidence_for_cases()
