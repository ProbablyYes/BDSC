import json
from pathlib import Path

from app.services.agent_router import run_agents


FOLLOW_UPS = [
    "如果用户不花钱也能解决，你的产品意义在哪？",
    "如果巨头下周推出免费功能，你的护城河在哪？",
    "3个月内做出MVP，最缺什么资源？",
]


def main() -> None:
    eval_file = Path(__file__).parent / "cases.sample.json"
    cases = json.loads(eval_file.read_text(encoding="utf-8"))

    print("=== Dialogue Eval (3 Rounds) ===")
    for idx, case in enumerate(cases, 1):
        context = case["input_text"]
        project_state = {"submissions": [], "teacher_feedback": []}
        print(f"\n[{idx}] {case['name']}")
        for ridx, q in enumerate(FOLLOW_UPS, 1):
            merged_input = f"{context}\n\n追问{ridx}:{q}"
            result = run_agents(
                agent_type="all",
                input_text=merged_input,
                mode=case.get("mode", "coursework"),
                project_state=project_state,
            )
            coach = result["project_coach"]
            diagnosis = coach.get("diagnosis", {})
            next_task = coach.get("next_task", {})
            rules = [r.get("id") for r in diagnosis.get("triggered_rules", [])]
            router = result.get("router", {})
            critic = result.get("critic", {})
            grader = result.get("grader", {})
            print(
                f"- round{ridx} rules={rules} task={next_task.get('title', '')} "
                f"router_focus={router.get('focus', [])} "
                f"critic_missing={critic.get('missing_evidence', [])[:2]} "
                f"score={grader.get('overall_score', 'n/a')}"
            )
            context = f"{context}\nAI建议任务：{next_task.get('title', '')}"
            project_state["submissions"].append(
                {
                    "raw_text": merged_input,
                    "diagnosis": diagnosis,
                    "next_task": next_task,
                }
            )


if __name__ == "__main__":
    main()
