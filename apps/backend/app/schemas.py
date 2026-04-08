from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    timestamp: datetime


class UploadAnalysisResponse(BaseModel):
    project_id: str
    student_id: str
    filename: str
    extracted_length: int
    diagnosis: dict
    next_task: dict
    hypergraph_insight: dict = Field(default_factory=dict)


class TeacherFeedbackRequest(BaseModel):
    project_id: str
    teacher_id: str
    comment: str = Field(min_length=5)
    focus_tags: list[str] = Field(default_factory=list)


class TeacherFeedbackResponse(BaseModel):
    project_id: str
    status: str
    feedback_id: str


class TeacherAssistantAssessmentReviewPayload(BaseModel):
    teacher_id: str
    logical_project_id: str | None = None
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=5)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    focus_tags: list[str] = Field(default_factory=list)
    score_band: str = ""
    send_to_student: bool = False


class TeacherAssistantInterventionPayload(BaseModel):
    teacher_id: str
    scope_type: Literal["team", "student", "project"] = "student"
    scope_id: str = Field(min_length=1)
    source_type: Literal["class_plan", "student_profile", "project_case"] = "student_profile"
    target_student_id: str | None = None
    project_id: str | None = None
    logical_project_id: str | None = None
    title: str = Field(min_length=1, max_length=120)
    reason_summary: str = Field(min_length=5)
    action_items: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    priority: Literal["high", "medium", "low"] = "medium"
    status: Literal["draft", "approved", "sent", "viewed", "completed", "archived"] = "approved"


class TeacherAssistantInterventionSendPayload(BaseModel):
    teacher_id: str


class TeacherAssistantSmartSelectFilter(BaseModel):
    """教师端“智能筛选”条件，用于批量选择干预目标项目/学生。

    设计为尽量宽松的可选字段集，前端只需填充用到的条件即可。
    """

    class_id: str | None = None
    cohort_id: str | None = None
    min_overall_score: float | None = None
    max_overall_score: float | None = None
    min_risk_count: int | None = None
    max_risk_count: int | None = None
    min_progress_rank: int | None = None
    max_progress_rank: int | None = None
    require_high_risk_rules: list[str] = Field(default_factory=list)
    exclude_rules: list[str] = Field(default_factory=list)
    project_phase_in: list[str] = Field(default_factory=list)
    limit: int = 30


class StudentInterventionViewPayload(BaseModel):
    project_id: str
    student_id: str | None = None

    class TeacherAssistantSmartSelectFilter(BaseModel):
        """教师端“智能筛选”条件，用于批量选择干预目标项目/学生。

        设计为尽量宽松的可选字段集，前端只需填充用到的条件即可。
        """

        class_id: str | None = None
        cohort_id: str | None = None
        min_overall_score: float | None = None
        max_overall_score: float | None = None
        min_risk_count: int | None = None
        max_risk_count: int | None = None
        min_progress_rank: int | None = None
        max_progress_rank: int | None = None
        require_high_risk_rules: list[str] = Field(default_factory=list)
        exclude_rules: list[str] = Field(default_factory=list)
        project_phase_in: list[str] = Field(default_factory=list)
        limit: int = 30

class ProjectSnapshotResponse(BaseModel):
    project_id: str
    latest_student_submission: dict | None = None
    teacher_feedback: list[dict] = Field(default_factory=list)
    graph_signals: dict = Field(default_factory=dict)


class AnalyzePayload(BaseModel):
    project_id: str
    student_id: str
    class_id: str | None = None
    cohort_id: str | None = None
    input_text: str = Field(min_length=20)
    mode: Literal["coursework", "competition", "learning"] = "coursework"


class AgentRunPayload(BaseModel):
    project_id: str
    agent_type: Literal[
        "student_learning",
        "project_coach",
        "competition_advisor",
        "instructor_assistant",
        "all",
    ] = "all"
    student_id: str | None = None
    prompt: str | None = None
    mode: Literal["coursework", "competition", "learning"] = "coursework"


class AgentRunResponse(BaseModel):
    project_id: str
    agent_type: str
    result: dict


class DialogueTurnPayload(BaseModel):
    project_id: str
    student_id: str
    message: str = Field(min_length=1)
    conversation_id: str | None = None
    class_id: str | None = None
    cohort_id: str | None = None
    mode: Literal["coursework", "competition", "learning"] = "coursework"
    competition_type: Literal["", "internet_plus", "challenge_cup", "dachuang"] = ""


class DialogueTurnResponse(BaseModel):
    project_id: str
    student_id: str
    conversation_id: str = ""
    assistant_message: str
    diagnosis: dict
    next_task: dict
    kg_analysis: dict = Field(default_factory=dict)
    hypergraph_insight: dict = Field(default_factory=dict)
    hypergraph_student: dict = Field(default_factory=dict)
    rag_cases: list = Field(default_factory=list)
    pressure_test_trace: dict = Field(default_factory=dict)
    agent_trace: dict = Field(default_factory=dict)
    insight_sources: dict = Field(default_factory=dict)


class AuthRegisterPayload(BaseModel):
    role: Literal["student", "teacher", "admin"] = "student"
    display_name: str = Field(min_length=2, max_length=50)
    email: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=6, max_length=64)
    student_id: str | None = None
    class_id: str | None = None
    cohort_id: str | None = None
    bio: str | None = ""


class AuthLoginPayload(BaseModel):
    email: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=6, max_length=64)


class AuthPasswordChangePayload(BaseModel):
    email: str = Field(min_length=1, max_length=100)
    current_password: str = Field(min_length=6, max_length=64)
    new_password: str = Field(min_length=6, max_length=64)


class AuthUserResponse(BaseModel):
    status: str = "ok"
    user: dict = Field(default_factory=dict)


class AdminUserCreatePayload(BaseModel):
    role: Literal["student", "teacher", "admin"] = "student"
    display_name: str = Field(min_length=1, max_length=50)
    email: str = Field(min_length=1, max_length=100)
    password: Optional[str] = Field(default=None, max_length=64)
    student_id: Optional[str] = None
    class_id: Optional[str] = None
    cohort_id: Optional[str] = None
    bio: Optional[str] = ""


class AdminUserUpdatePayload(BaseModel):
    role: Optional[Literal["student", "teacher", "admin"]] = None
    display_name: Optional[str] = None
    email: Optional[str] = None
    student_id: Optional[str] = None
    class_id: Optional[str] = None
    cohort_id: Optional[str] = None
    bio: Optional[str] = None
    status: Optional[Literal["active", "disabled"]] = None


class AdminChangePasswordPayload(BaseModel):
    new_password: str = Field(min_length=6, max_length=64)


class SmsSendPayload(BaseModel):
    phone: str = Field(min_length=1, max_length=100)


class SmsSendResponse(BaseModel):
    status: str = "ok"
    expires_in: int = 300
    code_hint: str = ""


class SmsLoginPayload(BaseModel):
    phone: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=4, max_length=8)


class TeamCreatePayload(BaseModel):
    teacher_id: str
    teacher_name: str = ""
    team_name: str = Field(min_length=1, max_length=100)


class TeamJoinPayload(BaseModel):
    user_id: str
    invite_code: str = Field(min_length=4, max_length=10)


class TeamUpdatePayload(BaseModel):
    teacher_id: str
    team_name: str = Field(min_length=1, max_length=100)


class TeamResponse(BaseModel):
    status: str = "ok"
    team: dict = Field(default_factory=dict)
