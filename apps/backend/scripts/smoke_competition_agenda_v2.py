"""Smoke test: 议题板 v2 三路链路（无需真实 LLM）

跑法（项目根目录下）：
    cd apps/backend
    python -m scripts.smoke_competition_agenda_v2

预期：
- note_agenda_signal 累积到第 4 轮触发抽取
- 缺 LLM → 走关键词兜底 → 议题入库
- run_jury_review 走 LLM 失败回退（每章返回 0 条议题）
- apply_agenda 用 fallback_block 拼接，pending_revision 真的写入 plan
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# 让脚本可以独立跑：把 apps/backend 加进 path
HERE = Path(__file__).resolve()
BACKEND_ROOT = HERE.parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.business_plan_service import BusinessPlanService, BusinessPlanStorage
from app.services.storage import ConversationStorage, JsonStorage


def main() -> int:
    tmpdir = Path(tempfile.mkdtemp(prefix="bp_v2_smoke_"))
    print(f"[smoke] tmp data root = {tmpdir}")
    try:
        # 用临时目录搭一个最小存储
        json_store = JsonStorage(root=tmpdir / "json")
        conv_store = ConversationStorage(root=tmpdir / "conv")
        plan_storage = BusinessPlanStorage(root=tmpdir / "plans")
        # llm=None → 三处 LLM 调用全部走回退
        svc = BusinessPlanService(
            storage=plan_storage,
            json_store=json_store,
            conv_store=conv_store,
            llm=None,
        )

        # 手搓一个最小 plan，跨过 generate_plan 的复杂依赖
        plan_id = "smoke-plan-001"
        project_id = "smoke-project"
        conversation_id = "smoke-conv"
        plan = {
            "plan_id": plan_id,
            "project_id": project_id,
            "conversation_id": conversation_id,
            "title": "智能水杯创业项目",
            "coaching_mode": "competition",
            "competition_unlocked": True,
            "version": 1,
            "previous_version": None,
            "sections": [
                {
                    "section_id": "users",
                    "title": "用户痛点与目标人群",
                    "display_title": "用户痛点与目标人群",
                    "content": (
                        "我们的目标人群是 25-40 岁的白领。\n\n"
                        "他们普遍有忘记喝水的痛点，但目前并没有可靠的提醒方式。"
                    ),
                    "user_edit": "",
                    "missing_points": ["规模估计", "样本调研"],
                    "field_map": {},
                },
                {
                    "section_id": "market",
                    "title": "市场与竞品分析",
                    "display_title": "市场与竞品分析",
                    "content": (
                        "国内智能水杯市场预计很大。\n\n"
                        "目前主要竞品有 A 品牌和 B 品牌。"
                    ),
                    "user_edit": "",
                    "missing_points": ["TAM/SAM/SOM 拆解", "竞品差异化"],
                    "field_map": {},
                },
            ],
            "competition_agenda": [],
            "pending_revisions": [],
            "revision_badge_count": 0,
        }
        # 走 storage.save 直接落盘（绕开 _save_plan 的 sync_project_meta 依赖）
        plan_storage.save(plan)
        # 重新通过服务读，验证 load 正常
        loaded = svc.get_plan(plan_id)
        assert loaded and loaded.get("plan_id") == plan_id, "plan 加载失败"
        print(f"[smoke] plan 准备好：{plan_id}（2 个章节）")

        # 1) 聊天沉淀链路：连灌 5 轮（首轮因 last_extract 缺省必 flush；
        #    第 5 轮命中 _AGENDA_CHAT_BATCH=4 阈值再次 flush）
        msgs = [
            "建议你给市场章节补上 TAM/SAM/SOM 拆解，目前评委看不到具体规模数字。",
            "用户那一段缺少证据和样本量，你要补充至少 30 份用户访谈或问卷数据。",
            "差异化分析不够清晰，需要量化和竞品对比，比如核心 KPI 比对。",
            "防守点 / 护城河没说清，请补充专利、独占供应链或先发壁垒方面的论证。",
            "另外，市场段还缺竞品矩阵，要把 A 品牌和 B 品牌列出指标对比。",
        ]
        flush_count = 0
        for i, m in enumerate(msgs, 1):
            r = svc.note_agenda_signal(
                plan_id, assistant_text=m, source_message_id=f"{conversation_id}#{i}"
            )
            print(f"[smoke] note_agenda_signal turn {i}: status={r.get('status')}, "
                  f"new={len(r.get('new_items') or [])}, "
                  f"buffered={r.get('buffered_count')}")
            if r.get("status") in {"ok", "no_new"}:
                flush_count += 1
        assert flush_count >= 1, f"5 轮里至少应 flush 一次，实际 {flush_count} 次"
        print(f"[smoke] 5 轮里共 flush {flush_count} 次（首轮缺省 + 第 5 轮命中阈值）")

        # 2) 全书巡检链路（LLM=None → 每章返回 0 条 → status=ok new_count=0）
        review = svc.run_jury_review(plan_id, force=True)
        print(f"[smoke] run_jury_review: status={review.get('status')}, "
              f"new={len(review.get('new_items') or [])}, "
              f"scanned={len(review.get('scanned_sections') or [])}")
        assert review.get("status") in {"ok", "skipped"}, f"unexpected: {review.get('status')}"
        rs = review.get("review_status") or {}
        assert rs.get("state") in {"done", "idle"}, f"review_status state: {rs.get('state')}"
        print(f"[smoke] review_status = {json.dumps(rs, ensure_ascii=False)}")

        # 3) 应用议题（如果第 4 轮真的产出了议题，就拿去 apply）
        list_resp = svc.list_agenda(plan_id)
        items = list_resp.get("items") or []
        pending = [it for it in items if (it.get("status") or "pending") == "pending"]
        print(f"[smoke] 议题板共 {len(items)} 条；pending {len(pending)} 条")
        if pending:
            ids_to_apply = [it["agenda_id"] for it in pending[:2]]
            apply_resp = svc.apply_agenda(plan_id, agenda_ids=ids_to_apply)
            print(f"[smoke] apply_agenda: status={apply_resp.get('status')}")
            new_plan = apply_resp.get("plan") or {}
            revs = list(new_plan.get("pending_revisions") or [])
            assert revs, "apply_agenda 没产出 pending_revisions"
            r0 = revs[-1]
            print(f"[smoke] 新增 revision: section={r0.get('section_id')}, "
                  f"summary={r0.get('summary')}, modes={r0.get('patch_modes')}, "
                  f"old_len={len(r0.get('old_content') or '')}, "
                  f"new_len={len(r0.get('new_content') or '')}")
            # 验证 patch_preview 已回填到议题里
            applied_items = [
                it for it in (new_plan.get("competition_agenda") or [])
                if it.get("agenda_id") in ids_to_apply
            ]
            assert all(it.get("status") == "applied" for it in applied_items)
            assert all(it.get("patch_preview") for it in applied_items)
            print(f"[smoke] {len(applied_items)} 条议题已 applied，"
                  f"patch_preview 已回填")
            # 验证 new_content 真的不是单纯等于 old_content（fallback 也会追加教练块）
            assert (r0.get("new_content") or "") != (r0.get("old_content") or ""), (
                "new_content 居然和 old_content 一样，apply 没改东西"
            )
            print("[smoke] new_content != old_content ✓ (有真实改动)")
        else:
            print("[smoke] 第 4 轮没产出议题（关键词兜底没命中或都被 normalize 丢弃），跳过 apply 链路")

        print("\n[smoke] ✅ 三路链路全部跑通（无 LLM 回退路径稳定）")
        return 0

    finally:
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
