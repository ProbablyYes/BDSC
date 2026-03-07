import json
from pathlib import Path

from app.services.agent_router import run_agents


def main() -> None:
    eval_file = Path(__file__).parent / "cases.sample.json"
    cases = json.loads(eval_file.read_text(encoding="utf-8"))

    print("=== Agent Eval Report ===")
    for idx, case in enumerate(cases, 1):
        result = run_agents(
            agent_type="all",
            input_text=case["input_text"],
            mode=case.get("mode", "coursework"),
            project_state={"submissions": [], "teacher_feedback": []},
        )
        coach = result["project_coach"]
        rules = coach["diagnosis"]["triggered_rules"]
        next_task = coach["next_task"]["title"]
        print(f"\n[{idx}] {case['name']}")
        print(f"- project_id: {case['project_id']}")
        print(f"- triggered_rules: {[r['id'] for r in rules]}")
        print(f"- next_task: {next_task}")


if __name__ == "__main__":
    main()
