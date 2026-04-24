# -*- coding: utf-8 -*-
"""把 regression_final01.json 输出成可读 UTF-8 BOM 文件。"""
from __future__ import annotations
import codecs
import json
import sys

PATH = "regression_final01.json"
OUT = "summary_final01.txt"


def main() -> int:
    data = json.load(open(PATH, "r", encoding="utf-8"))
    lines: list[str] = []
    for tag, rows in data.items():
        lines.append("=" * 80)
        lines.append(tag)
        lines.append("=" * 80)
        for r in rows:
            tv = r.get("track_vector") or {}
            iv = float(tv.get("innov_venture") or 0.0)
            bp = float(tv.get("biz_public") or 0.0)
            iv_label = "创业(+)" if iv > 0.2 else ("创新(-)" if iv < -0.2 else "中性")
            bp_label = "公益(+)" if bp > 0.2 else ("商业(-)" if bp < -0.2 else "中性")
            lines.append("")
            lines.append(
                f"--- Turn {r['turn']} pid={r.get('logical_project_id')} "
                f"stage={r.get('project_stage_v2')} score={r.get('overall_score')} ---"
            )
            lines.append(f"象限: innov_venture={iv:+.3f} [{iv_label}], biz_public={bp:+.3f} [{bp_label}]")
            lines.append(f"subgraphs: {r.get('ability_subgraphs')}")
            lines.append(
                f"ontology_cov={r.get('ontology_coverage_ratio')} miss={r.get('ontology_missing_count')}"
            )
            lines.append(f"ontology: {(r.get('ontology_summary') or '')[:240]}")
            lines.append("assistant_excerpt:")
            lines.append("  " + (r.get("assistant_excerpt") or "")[:600])
            ags = r.get("agent_responses_preview") or []
            if ags:
                lines.append("agents:")
                for ag in ags[:3]:
                    lines.append(
                        f"  [{ag.get('name')}] {(ag.get('snippet') or '')[:300]}"
                    )
        lines.append("")
    with codecs.open(OUT, "w", "utf-8-sig") as f:
        f.write("\n".join(lines))
    print(f"OK {len(lines)} lines -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
