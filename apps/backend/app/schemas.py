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
    message: str = Field(min_length=5)
    class_id: str | None = None
    cohort_id: str | None = None
    mode: Literal["coursework", "competition"] = "coursework"


class DialogueTurnResponse(BaseModel):
    project_id: str
    student_id: str
    assistant_message: str
    diagnosis: dict
    next_task: dict
    hypergraph_insight: dict = Field(default_factory=dict)
    agent_trace: dict = Field(default_factory=dict)
