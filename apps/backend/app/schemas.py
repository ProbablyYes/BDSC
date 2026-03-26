from datetime import datetime
from typing import Literal

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
    mode: Literal["coursework", "competition"] = "coursework"


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
    mode: Literal["coursework", "competition"] = "coursework"


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
    mode: Literal["coursework", "competition"] = "coursework"


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
    agent_trace: dict = Field(default_factory=dict)


class AuthRegisterPayload(BaseModel):
    role: Literal["student", "teacher", "admin"] = "student"
    display_name: str = Field(min_length=2, max_length=50)
    email: str = Field(min_length=5, max_length=100)
    password: str = Field(min_length=6, max_length=64)
    student_id: str | None = None
    class_id: str | None = None
    cohort_id: str | None = None
    bio: str | None = ""


class AuthLoginPayload(BaseModel):
    email: str = Field(min_length=5, max_length=100)
    password: str = Field(min_length=6, max_length=64)


class AuthPasswordChangePayload(BaseModel):
    email: str = Field(min_length=5, max_length=100)
    current_password: str = Field(min_length=6, max_length=64)
    new_password: str = Field(min_length=6, max_length=64)


class AuthUserResponse(BaseModel):
    status: str = "ok"
    user: dict = Field(default_factory=dict)


class SmsSendPayload(BaseModel):
    phone: str = Field(min_length=8, max_length=20)


class SmsSendResponse(BaseModel):
    status: str = "ok"
    expires_in: int = 300
    code_hint: str = ""


class SmsLoginPayload(BaseModel):
    phone: str = Field(min_length=8, max_length=20)
    code: str = Field(min_length=4, max_length=8)


class TeamCreatePayload(BaseModel):
    teacher_id: str
    teacher_name: str = ""
    team_name: str = Field(min_length=1, max_length=100)


class TeamJoinPayload(BaseModel):
    user_id: str
    invite_code: str = Field(min_length=4, max_length=10)


class TeamResponse(BaseModel):
    status: str = "ok"
    team: dict = Field(default_factory=dict)
