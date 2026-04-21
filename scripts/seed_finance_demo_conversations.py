"""为 654321 账号预置 8 条财务守望演示会话。

做法：离线调 finance_guard.scan_message 拿每个场景的真实卡片，然后把
『用户消息 + 预先写好的 AI 回复 + agent_trace.finance_advisory』拼成一份
完整的 conversation JSON，写到 data/conversations/project-<uuid>/ 目录下，
让老师登录 654321/654321 后左侧栏直接看到，点开即有卡片渲染。

为什么不走 API：LLM 漂移会导致每次演示效果不同；直接落盘的 seed
保证可复现；该数据仅用于前端展示，不参与诊断学生真实分数。

幂等：每个 seed JSON 带 "seed_tag": "finance_demo_v1"；重跑前会先把
相同 seed_tag 的旧文件清掉，再按场景顺序重新生成（场景 1 排最上）。

用法（workspace 根）：
    python scripts/seed_finance_demo_conversations.py
    python scripts/seed_finance_demo_conversations.py --purge   # 仅清理不重写
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "apps" / "backend"
sys.path.insert(0, str(BACKEND))

from app.services.finance_guard import scan_message  # noqa: E402

SEED_TAG = "finance_demo_v1"
USER_ID = "0cfb36f4-db33-4cab-b7cb-6258204c454e"  # 654321 的 user_id
PROJECT_ID = f"project-{USER_ID}"
CONV_DIR = ROOT / "data" / "conversations" / PROJECT_ID

BJ = timezone(timedelta(hours=8))


def _iso(delta_sec: int = 0) -> str:
    return (datetime.now(BJ) + timedelta(seconds=delta_sec)).isoformat(timespec="seconds")


# ─────────────────────────────────────────────
#  8 个场景（与 apps/backend/_test_finance_chat.py 严格对齐）
# ─────────────────────────────────────────────

SCENARIOS: list[dict] = [
    {
        "idx": 1,
        "title": "演示·场景1 · 空想（不触发，作对照）",
        "user": "我想做一个帮大学生找自习搭子的 App，让更多人愿意自律。",
        "industry_hint": "",
        "history": None,
        "budget": None,
        "summary": "无数字输入 → guard 静默不打扰",
        "assistant_intro": (
            "这个切入点挺有温度的，不过现在还停留在愿景层。要让它真正能评估，"
            "我们需要先补几个关键数字——"
        ),
        "assistant_outro": (
            "建议先回答：目标用户画像是谁、他们现在怎么解决这个问题、你想怎么收钱？"
            "等你有了初步的定价或获客假设，我会自动给出行业基线对比。"
        ),
    },
    {
        "idx": 2,
        "title": "演示·场景2 · 定价 299/月偏高（pricing 红）",
        "user": "我打算向大学生收月费 299 元，每月新增用户大概 1000 人，转化率 3%。",
        "industry_hint": "教育",
        "history": None,
        "budget": None,
        "summary": "月费 299 显著高于教育 C 端区间，pricing_framework 触发",
        "assistant_intro": (
            "先帮你做一个快速的定价体检——大学生为主的教育 C 端产品，月费 299 元属于"
            "偏高区间，即使 3% 的转化率也会在获客后被价格拦住。"
        ),
        "assistant_outro": (
            "建议先做一个价格敏感度测试：把 99/199/299 三档放给 50 位目标用户选，"
            "看支付意愿曲线再决定是否真的要走高价。"
        ),
    },
    {
        "idx": 3,
        "title": "演示·场景3 · CAC 500 + 留存 40%（单经济红）",
        "user": "我们的获客主要靠抖音投流，CAC 大概是 500 元/付费用户。月留存 40% 左右。",
        "industry_hint": "教育",
        "history": [{"role": "user", "content": "之前说过定价 99 元/月"}],
        "budget": None,
        "summary": "LTV/CAC < 1，典型亏损模型，单位经济红",
        "assistant_intro": (
            "把你之前说的 99 元/月和这次的 CAC 500、留存 40% 串起来算了一下，"
            "LTV 还不够覆盖一个用户的获客成本，这是最典型的\"越卖越亏\"。"
        ),
        "assistant_outro": (
            "两个方向可以平行走：一是压 CAC（把投流换成转介绍或校园 BD），"
            "二是抬留存（内容/社群/作业激励），两项任一能改到行业中位，模型才会转正。"
        ),
    },
    {
        "idx": 4,
        "title": "演示·场景4 · 只说市场不含价格（不触发）",
        "user": "中国在校大学生 4000 万人，TAM 我觉得超过 1000 亿。",
        "industry_hint": "教育",
        "history": None,
        "budget": None,
        "summary": "无定价/成本信号 → guard 仅做市场侧跟进",
        "assistant_intro": (
            "市场盘子确实在这里，但 TAM 是\"理论天花板\"。评委真正想看的是你能"
            "吃到的 SAM 和第一年的 SOM。"
        ),
        "assistant_outro": (
            "接下来麻烦补一下：你打算从哪个细分切入？首年触达几千到几万？"
            "一旦告诉我单价或获客渠道，我会接着帮你做单位经济。"
        ),
    },
    {
        "idx": 5,
        "title": "演示·场景5 · 公益 320 元/人（公益专用卡）",
        "user": "我们是公益项目，每服务一个留守儿童的成本是 320 元，想拿到企业捐赠。",
        "industry_hint": "公益",
        "history": None,
        "budget": None,
        "summary": "触发公益行业基线与受益人成本专用评估",
        "assistant_intro": (
            "公益项目的底层指标和商业项目不同，我按\"每受益人成本\"这条线帮你对照"
            "了行业经验区间。"
        ),
        "assistant_outro": (
            "企业捐赠方最关心两件事：每元带来多少实效（ROI）、能不能持续复用。"
            "建议把 320 元拆成\"固定运营 vs 可变服务\"两部分，再准备 2-3 个亲历故事作"
            "为情感锚点。"
        ),
    },
    {
        "idx": 6,
        "title": "演示·场景6 · 文本只抱怨获客贵（看预算兜底）",
        "user": "我们的获客成本太高了。",
        "industry_hint": "教育",
        "history": None,
        "budget": {
            "monthly_price": 39,
            "cac": 800,
            "gross_margin": 0.35,
            "monthly_retention": 0.5,
        },
        "summary": "对话未给数字 → guard 回读预算面板做合理性评估",
        "assistant_intro": (
            "我把你预算面板里填的数（月费 39、CAC 800、毛利 35%、留存 50%）带入模型跑了一下——"
            "当前结构下，单位经济是不成立的。"
        ),
        "assistant_outro": (
            "CAC 800 对应单用户 LTV 需要做到近 1600 才算健康，按 39 元月费 + 50% 留存，"
            "平均生命周期只有 2 个月多。要么把价格结构抬到订阅+增值，要么压 CAC 到 100 以内。"
        ),
    },
    {
        "idx": 7,
        "title": "演示·场景7 · 文本说 99，预算面板是 299（预算优先）",
        "user": "我们定价 99 元/月",
        "industry_hint": "教育",
        "history": None,
        "budget": {"monthly_price": 299, "cac": 600},
        "summary": "对话 vs 预算冲突 → 以可审计的预算面板为准",
        "assistant_intro": (
            "注意到你口头说的是 99 元/月，但预算面板里登记的是 299。"
            "为了能给到经得起追问的评估，我按 299（可追溯的正式数）来跑。"
        ),
        "assistant_outro": (
            "下一步：要么把正式定价改回 99 并在预算面板同步，要么接受 299 的定位并"
            "准备好对应的价值证据（对标竞品、客单价、高净值用户画像）。两条路我建议选一条，"
            "现在这种\"对外说 99 内部算 299\"的状态最容易被评委抓住。"
        ),
    },
    {
        "idx": 8,
        "title": "演示·场景8 · SaaS 全绿健康（不出卡对照）",
        "user": "我们是 B 端 SaaS，月费 99 元/月，CAC 约 80，月留存 90%，毛利 75%。",
        "industry_hint": "SaaS",
        "history": None,
        "budget": None,
        "summary": "各项指标进入健康区间 → guard 不打扰",
        "assistant_intro": (
            "这组数据放到 SaaS 行业基线里全部进入健康带：CAC < 月费、留存 ≥ 90%、"
            "毛利 ≥ 70%，都是可以直接写进 BP 的。"
        ),
        "assistant_outro": (
            "保持这个结构就不会出红卡。下一步我更建议你把力气放在\"证明\"——"
            "拉 3-5 个付费客户的用量曲线、NRR 数据，把单位经济从模型升级为证据。"
        ),
    },
]


def _build_conversation(scenario: dict, base_time: datetime) -> dict:
    """跑一遍 scan_message，把学生消息 + 助手消息 + finance_advisory 拼成会话 JSON。"""
    t0 = base_time.isoformat(timespec="seconds")
    t1 = (base_time + timedelta(seconds=2)).isoformat(timespec="seconds")
    t2 = (base_time + timedelta(seconds=6)).isoformat(timespec="seconds")

    advisory = scan_message(
        scenario["user"],
        history=scenario.get("history"),
        budget_snapshot=scenario.get("budget"),
        industry_hint=scenario.get("industry_hint", ""),
    )

    user_msg = {"role": "user", "content": scenario["user"], "timestamp": t0}

    assistant_text = scenario["assistant_intro"]
    if advisory and advisory.get("triggered"):
        cards = advisory.get("cards") or []
        if cards:
            assistant_text += "\n\n（详见下方财务守望卡片，红/黄为需要重点处理的信号。）"
    else:
        assistant_text += "\n\n（本轮没有可抽取的数字，财务守望保持静默——这是正常的。）"
    assistant_text += "\n\n" + scenario["assistant_outro"]

    agent_trace: dict = {
        "orchestration": {"mode": "competition", "engine": "seed", "pipeline": ["demo"]},
        "seed_tag": SEED_TAG,
        "demo_note": "本条为 finance_guard 离线演示会话，用于教学展示，不参与真实诊断评分。",
    }
    if advisory and advisory.get("triggered"):
        agent_trace["finance_advisory"] = advisory

    assistant_msg = {
        "role": "assistant",
        "content": assistant_text,
        "timestamp": t2,
        "agent_trace": agent_trace,
    }

    _ = t1

    return {
        "conversation_id": str(uuid4()),
        "project_id": PROJECT_ID,
        "student_id": USER_ID,
        "title": scenario["title"],
        "summary": scenario["summary"],
        "created_at": t0,
        "seed_tag": SEED_TAG,
        "seed_scenario_idx": scenario["idx"],
        "messages": [user_msg, assistant_msg],
    }


def _purge_old() -> int:
    """把旧的 seed_tag 文件清掉。返回删除数量。"""
    if not CONV_DIR.exists():
        return 0
    n = 0
    for p in CONV_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("seed_tag") == SEED_TAG:
            p.unlink()
            n += 1
    return n


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--purge", action="store_true", help="仅清理旧 seed，不重写")
    args = parser.parse_args()

    CONV_DIR.mkdir(parents=True, exist_ok=True)
    removed = _purge_old()
    print(f"[seed] 清理旧 seed 文件 {removed} 个")

    if args.purge:
        print("[seed] --purge 模式，清理完毕退出")
        return

    base = datetime.now(BJ) - timedelta(minutes=len(SCENARIOS) * 2)

    written: list[str] = []
    for s in reversed(SCENARIOS):
        t_base = base + timedelta(minutes=(len(SCENARIOS) - s["idx"]) * 2)
        conv = _build_conversation(s, t_base)
        path = CONV_DIR / f"{conv['conversation_id']}.json"
        path.write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")
        adv = None
        for m in conv["messages"]:
            if m["role"] == "assistant":
                adv = (m.get("agent_trace") or {}).get("finance_advisory")
                break
        status = "触发" if adv and adv.get("triggered") else "静默"
        cards_n = len((adv or {}).get("cards") or []) if adv else 0
        print(f"[seed] 场景{s['idx']}  {status}  cards={cards_n}  → {path.name}")
        written.append(path.name)
        time.sleep(0.05)

    print(f"[seed] 完成，写入 {len(written)} 个会话到 {CONV_DIR}")


if __name__ == "__main__":
    main()
