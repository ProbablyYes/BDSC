from app.services.agents import (
    competition_advisor_agent,
    instructor_assistant_agent,
    project_coach_agent,
    student_learning_agent,
)


def run_agents(
    agent_type: str,
    input_text: str,
    mode: str,
    project_state: dict,
) -> dict:
    if agent_type == "student_learning":
        return student_learning_agent(prompt=input_text, mode=mode)
    if agent_type == "project_coach":
        return project_coach_agent(input_text=input_text, mode=mode)
    if agent_type == "competition_advisor":
        return competition_advisor_agent(input_text=input_text, mode=mode)
    if agent_type == "instructor_assistant":
        return instructor_assistant_agent(project_state=project_state)
    if agent_type == "all":
        return {
            "student_learning": student_learning_agent(prompt=input_text, mode=mode),
            "project_coach": project_coach_agent(input_text=input_text, mode=mode),
            "competition_advisor": competition_advisor_agent(input_text=input_text, mode=mode),
            "instructor_assistant": instructor_assistant_agent(project_state=project_state),
        }
    raise ValueError(f"Unsupported agent_type: {agent_type}")
