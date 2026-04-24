# -*- coding: utf-8 -*-
"""端到端探针：跑一轮 dialogue turn，看 ontology→KG→hypergraph→subgraph→graph_rag 是否真正联动。

跑法：
    cd apps/backend
    .venv\\Scripts\\python.exe scripts/probe_chain.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import uuid
from typing import Any

API = "http://127.0.0.1:8037"


CASES = [
    {
        "label": "case_business_unit_econ",
        "msg": (
            "我们做了一款面向独立咖啡馆的进货 SaaS，目标客户是 50 平米以下的小店主。"
            "现在测试期客单价 199/月，CAC 大概 320，留存 8 个月，毛利 65%。"
            "想问下 LTV 还能怎么撑起来，渠道目前主要靠地推和小红书。"
        ),
    },
    {
        "label": "case_innovation_moat",
        "msg": (
            "我们做了一个用 LLM 做数学辅导的 AI 助教，号称比同类产品都更准。"
            "竞品我看过几个，但还没做对比表。技术上用了 RAG + 自研 prompt，没申请专利。"
            "想知道这种创新算不算真正的护城河，路演时怎么讲。"
        ),
    },
]


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        API + path,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=240) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _short(s: str, n: int = 80) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _probe(label: str, msg: str) -> dict[str, Any]:
    project_id = f"project-probe-{uuid.uuid4().hex[:8]}"
    print(f"\n{'=' * 78}")
    print(f"[{label}] project_id={project_id}")
    print(f"  msg: {msg[:120]}")
    print(f"{'=' * 78}")

    payload = {
        "project_id": project_id,
        "student_id": "probe-stu",
        "message": msg,
        "mode": "learning",
        "competition_type": "",
    }
    t0 = time.time()
    r = _post("/api/dialogue/turn", payload)
    dt = time.time() - t0
    print(f"  request took {dt:.1f}s, intent={r.get('intent')}, conv={r.get('conversation_id')}")
    return r


def _explore(label: str, r: dict[str, Any]) -> dict[str, Any]:
    """Inspect chain pieces and produce a verdict."""
    diag = r.get("diagnosis") or {}
    kg = r.get("kg_analysis") or {}
    hi = r.get("hypergraph_insight") or {}
    hs = r.get("hypergraph_student") or {}
    rag = r.get("rag_cases") or []
    trace = r.get("agent_trace") or {}
    onto = trace.get("ontology_grounding") or r.get("ontology_grounding") or {}
    ability = trace.get("ability_subgraphs") or r.get("ability_subgraphs") or []
    refresh = r.get("analysis_refresh") or {}

    print("\n--- chain ---")

    # 1. Ontology grounding
    print(f"  ONTOLOGY: covered={len(onto.get('covered_concepts') or [])}, "
          f"missing={len(onto.get('missing_concepts') or [])}, "
          f"stage={onto.get('stage')!r}, "
          f"stage_gap={len(onto.get('stage_gap_concepts') or [])}, "
          f"probing={len(onto.get('stage_probing_questions') or [])}, "
          f"coverage={onto.get('coverage_ratio')}")
    cov = [c.get("label") for c in (onto.get("covered_concepts") or [])][:6]
    if cov:
        print(f"     covered_labels: {cov}")
    if onto.get("stage_probing_questions"):
        for q in onto["stage_probing_questions"][:3]:
            print(f"     probing: {_short(q, 90)}")

    # 2. KG analysis
    ents = kg.get("entities") or []
    rels = kg.get("relationships") or []
    print(f"  KG: entities={len(ents)}, relationships={len(rels)}")
    if ents:
        for e in ents[:5]:
            print(f"     entity[{e.get('type')}] {e.get('label') or e.get('name')}")

    # 3. Hypergraph
    he = (hi or {}).get("edges") or []
    print(f"  HYPER_INSIGHT: ok={hi.get('ok')}, edges={len(he)}, "
          f"family_dist={(hi.get('matched_by') or {}).get('family_distribution', {})}")
    for e in he[:3]:
        print(f"     [{e.get('type')}] support={e.get('support')} note={_short(e.get('teaching_note'), 80)}")
    print(f"  HYPER_STUDENT: ok={hs.get('ok')}, has_recs={bool(hs.get('recommendations'))}")

    # 4. Ability subgraph
    print(f"  ABILITY_SUBGRAPHS: count={len(ability)}")
    for sg in ability:
        print(f"     {sg.get('id')} score={sg.get('score')} purpose={_short(sg.get('purpose'), 60)}")

    # 5. RAG (with concept_hits / subgraph_hits)
    print(f"  RAG_CASES: count={len(rag)}")
    for c in rag[:4]:
        print(f"     {c.get('case_id')} sim={c.get('similarity')} "
              f"concept_hits={c.get('concept_hits')} subgraph_hits={c.get('subgraph_hits')} "
              f"retrieval_mode={c.get('retrieval_mode')}")

    # 6. Refresh metadata (carry-forward visibility)
    print(f"  REFRESH: fresh={refresh.get('fresh_components')} carried={refresh.get('carried')}")

    return {
        "ontology_active": (len(onto.get("covered_concepts") or []) > 0
                            or bool(onto.get("stage_probing_questions"))),
        "kg_active": len(ents) > 0,
        "hyper_active": bool(he),
        "ability_active": len(ability) > 0,
        "rag_active": len(rag) > 0,
        "rag_concept_boosted": any((c.get("concept_hits") or []) for c in rag),
        "rag_subgraph_boosted": any((c.get("subgraph_hits") or []) for c in rag),
    }


def main() -> int:
    overall: dict[str, dict] = {}
    for c in CASES:
        try:
            r = _probe(c["label"], c["msg"])
        except Exception as exc:
            print(f"  !! request failed: {exc}")
            overall[c["label"]] = {"error": str(exc)}
            continue
        overall[c["label"]] = _explore(c["label"], r)
        # Save raw for later inspection
        out = f"probe_{c['label']}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)
        print(f"  raw saved -> {out}")

    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    for label, v in overall.items():
        print(f"  {label}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
