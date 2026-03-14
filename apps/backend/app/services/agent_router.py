from app.services.agents import (
    competition_advisor_agent,
    instructor_assistant_agent,
    project_coach_agent,
    student_learning_agent,
)
from app.services.llm_client import LlmClient

llm = LlmClient()
CORE_AGENTS = {"student_learning", "project_coach", "competition_advisor", "instructor_assistant"}


def _short_memory(project_state: dict, max_turns: int = 6) -> list[dict]:
    submissions = project_state.get("submissions", []) or []
    memory: list[dict] = []
    for row in submissions[-max_turns:]:
        memory.append(
            {
                "ts": row.get("created_at"),
                "text": (row.get("raw_text") or "")[:240],
                "rules": [r.get("id") for r in (row.get("diagnosis", {}).get("triggered_rules", []) or [])][:4],
                "next_task": row.get("next_task", {}),
            }
        )
    return memory


def _router_agent(input_text: str, mode: str, memory: list[dict]) -> dict:
    if not llm.enabled:
        return {
            "focus": ["diagnosis", "next_task"],
            "tone": "socratic",
            "risk_level": "medium",
            "should_call": ["student_learning", "project_coach", "competition_advisor", "instructor_assistant"],
            "engine": "rule",
        }
    route = llm.chat_json(
        system_prompt=(
            "你是Router Agent。输出JSON: focus(list), tone, risk_level(low/medium/high), "
            "should_call(list，候选:student_learning,project_coach,competition_advisor,instructor_assistant)。"
        ),
        user_prompt=f"mode={mode}\ninput={input_text}\nmemory={memory}",
        temperature=0.1,
    )
    raw_should = route.get("should_call", [])
    if not isinstance(raw_should, list):
        raw_should = []
    route["should_call"] = [x for x in raw_should if isinstance(x, str) and x in CORE_AGENTS]
    route["engine"] = "llm"
    return route


def _critic_agent(input_text: str, coach_result: dict, memory: list[dict]) -> dict:
    if not llm.enabled:
        return {"challenge_points": [], "missing_evidence": [], "engine": "rule"}
    critic = llm.chat_json(
        system_prompt=(
            "你是Critic Agent。请对coach建议做反驳检查。输出JSON: "
            "challenge_points(list), missing_evidence(list), counterfactual_questions(list)。"
        ),
        user_prompt=f"input={input_text}\ncoach={coach_result}\nmemory={memory}",
        model=None,
        temperature=0.2,
    )
    critic["engine"] = "llm"
    return critic


def _planner_agent(
    input_text: str,
    coach_result: dict,
    critic_result: dict,
    mode: str,
) -> dict:
    next_task = coach_result.get("next_task", {}) if isinstance(coach_result, dict) else {}
    if not llm.enabled:
        return {
            "execution_plan": [
                "先补充关键证据（访谈/问卷/市场数据）",
                "按 next_task 产出模板提交一版",
                "根据 critic 反问做一次压力测试复盘",
            ],
            "next_24h_goal": next_task.get("title", "完成下一步唯一任务"),
            "engine": "rule",
        }
    plan = llm.chat_json(
        system_prompt=(
            "你是Planner Agent。请输出JSON字段："
            "execution_plan(list), next_24h_goal, next_72h_goal, checkpoint(list)。"
        ),
        user_prompt=f"mode={mode}\ninput={input_text}\ncoach={coach_result}\ncritic={critic_result}",
        temperature=0.2,
    )
    if not plan:
        return {
            "execution_plan": ["执行 coach 的 next_task 并补齐证据"],
            "next_24h_goal": next_task.get("title", "完成下一步唯一任务"),
            "engine": "rule-fallback",
        }
    plan["engine"] = "llm"
    return plan


def _grader_agent(coach_result: dict, critic_result: dict) -> dict:
    diagnosis = coach_result.get("diagnosis", {}) if isinstance(coach_result, dict) else {}
    rubric = diagnosis.get("rubric", []) if isinstance(diagnosis, dict) else []
    overall = diagnosis.get("overall_score", 0)
    if not llm.enabled:
        return {
            "overall_score": overall,
            "rubric": rubric,
            "grading_comment": "已完成规则评分，可继续补证据。",
            "engine": "rule",
        }
    grade = llm.chat_json(
        system_prompt=(
            "你是Grader Agent。基于rubric和critic输出评分解释。输出JSON: "
            "overall_score(number), grading_comment, strongest_dim(list), weakest_dim(list)。"
        ),
        user_prompt=f"diagnosis={diagnosis}\ncritic={critic_result}",
        temperature=0.1,
    )
    if "overall_score" not in grade:
        grade["overall_score"] = overall
    if "rubric" not in grade:
        grade["rubric"] = rubric
    grade["engine"] = "llm"
    return grade


def run_agents(
    agent_type: str,
    input_text: str,
    mode: str,
    project_state: dict,
) -> dict:
    memory = _short_memory(project_state=project_state)

    if agent_type == "student_learning":
        return student_learning_agent(prompt=input_text, mode=mode)
    if agent_type == "project_coach":
        return project_coach_agent(input_text=input_text, mode=mode)
    if agent_type == "competition_advisor":
        return competition_advisor_agent(input_text=input_text, mode=mode)
    if agent_type == "instructor_assistant":
        return instructor_assistant_agent(project_state=project_state)
    if agent_type == "all":
        router = _router_agent(input_text=input_text, mode=mode, memory=memory)
        should_call = set(router.get("should_call", [])) if isinstance(router, dict) else set()
        call_all = not should_call

        student_learning = (
            student_learning_agent(prompt=input_text, mode=mode)
            if call_all or "student_learning" in should_call
            else {"agent": "student_learning", "skipped": True}
        )
        # project_coach is mandatory because downstream APIs depend on diagnosis/next_task.
        project_coach = project_coach_agent(input_text=input_text, mode=mode)
        competition_advisor = (
            competition_advisor_agent(input_text=input_text, mode=mode)
            if call_all or "competition_advisor" in should_call
            else {"agent": "competition_advisor", "skipped": True}
        )
        instructor_assistant = (
            instructor_assistant_agent(project_state=project_state)
            if call_all or "instructor_assistant" in should_call
            else {"agent": "instructor_assistant", "skipped": True}
        )
        critic = _critic_agent(input_text=input_text, coach_result=project_coach, memory=memory)
        grader = _grader_agent(coach_result=project_coach, critic_result=critic)
        planner = _planner_agent(
            input_text=input_text,
            coach_result=project_coach,
            critic_result=critic,
            mode=mode,
        )

        return {
            "router": router,
            "memory": memory,
            "student_learning": student_learning,
            "project_coach": project_coach,
            "competition_advisor": competition_advisor,
            "instructor_assistant": instructor_assistant,
            "critic": critic,
            "grader": grader,
            "planner": planner,
            "orchestration": {
                "mode": mode,
                "llm_enabled": llm.enabled,
                "called_agents": sorted(list((CORE_AGENTS if call_all else should_call) | {"project_coach"})),
                "skipped_agents": sorted(list(CORE_AGENTS - ((CORE_AGENTS if call_all else should_call) | {"project_coach"}))),
            },
        }
    raise ValueError(f"Unsupported agent_type: {agent_type}")
