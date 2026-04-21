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
    video_analyses: list[dict] = Field(default_factory=list)
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


class VideoRubricItem(BaseModel):
    item: str
    score: float
    weight: float
    status: Literal["ok", "risk"] = "ok"
    reason: str = ""


class VideoAnalysisResult(BaseModel):
    overall_score: float | None = None
    score_band: str = ""
    rubric: list[VideoRubricItem] = Field(default_factory=list)
    transcript: str = ""
    summary: str = ""
    presentation_feedback: str = ""
    mode: Literal["coursework", "competition", "learning"] = "competition"
    competition_type: Literal["", "internet_plus", "challenge_cup", "dachuang"] = ""


class VideoAnalysisResponse(BaseModel):
    project_id: str
    student_id: str
    filename: str
    created_at: datetime
    analysis: VideoAnalysisResult


class PosterSection(BaseModel):
    id: str
    title: str
    bullets: list[str] = Field(default_factory=list)
    highlight: bool = False


class PosterLayout(BaseModel):
    orientation: Literal["portrait", "landscape"] = "portrait"
    grid: str | None = None
    accent_area: str | None = None


class PosterDesign(BaseModel):
    """Structured poster design plan for a student's project.

    This is intentionally compact so that it can be generated by LLMs
    and rendered flexibly on the frontend.
    """

    title: str
    subtitle: str = ""
    sections: list[PosterSection] = Field(default_factory=list)
    layout: PosterLayout = Field(default_factory=PosterLayout)
    # 如: "tech_blue", "youthful_gradient", "minimal_black"
    theme: str = "tech_blue"
    image_prompts: list[str] = Field(default_factory=list)
    # 如: "A3 纵向", "1080x1920 竖屏海报"
    export_hint: str = ""


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


class SetStudentIdPayload(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    student_id: str = Field(min_length=4, max_length=32, pattern=r"^[A-Za-z0-9_-]{4,32}$")


class AuthUserResponse(BaseModel):
    status: str = "ok"
    user: dict = Field(default_factory=dict)


class PosterGeneratePayload(BaseModel):
        """Request payload for /api/poster/generate.

        - If use_latest_context is true, backend will try to read the latest
            diagnosis + knowledge graph context from JsonStorage / ConversationStorage.
        - If source_text is provided, it will be treated as the primary project
            description and the latest context will be used as supplementary hints.
        """

        project_id: str
        student_id: str
        # 当前对话 ID，用于严格限定海报生成只基于这一条对话记录
        conversation_id: str = ""
        mode: Literal["coursework", "competition", "learning"] = "coursework"
        competition_type: Literal["", "internet_plus", "challenge_cup", "dachuang"] = ""
        source_text: str | None = None
        use_latest_context: bool = True


class PosterImageGeneratePayload(BaseModel):
    """Request payload for /api/poster/generate-image.

    - prompt: 由前端基于 PosterDesign.image_prompts 或标题生成的插画提示词
    - orientation/size: 可选，后端可用来选择更合适的画布比例
    """

    project_id: str
    student_id: str
    prompt: str
    orientation: Literal["portrait", "landscape"] | None = None
    size: str | None = None


class AdminUserCreatePayload(BaseModel):
    role: Literal["student", "teacher", "admin"] = "student"
    display_name: str = Field(min_length=1, max_length=50)
    email: str = Field(min_length=1, max_length=100)
    password: Optional[str] = Field(default=None, max_length=64)
    student_id: Optional[str] = None
    class_id: Optional[str] = None
    cohort_id: Optional[str] = None
    bio: Optional[str] = ""


class PosterGenerateResponse(BaseModel):
    poster: PosterDesign


class PosterImageGenerateResponse(BaseModel):
    image_url: str


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


class AdminBatchCreateUsersPayload(BaseModel):
    """Payload for admin-side batch user creation.

    Supports creating multiple student/teacher accounts with a shared
    account prefix and predictable default passwords.

    Password rule (backend side):
    - if password_suffix is provided: password = account + password_suffix
    - otherwise: password = account + "123"
    """

    role: Literal["student", "teacher"] = "student"
    prefix: str = Field(min_length=1, max_length=32)
    start_index: int = Field(default=1, ge=1, le=100000)
    count: int = Field(default=1, ge=1, le=500)
    password_suffix: str = Field(default="123", max_length=64)

    # 学生批量加入团队的邀请码（对应已有 team.invite_code）
    invite_code: Optional[str] = None

    # 教师批量创建团队时的基础信息（可选）
    # 若提供，则会为每个教师创建一个团队：
    # - team_name: 多个教师时自动追加序号后缀
    # - team_invite_code: 单教师时可直接使用，自定义邀请码；
    #                      多个教师时若提供则仅对第一个教师生效
    team_name: Optional[str] = None
    team_invite_code: Optional[str] = None


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
    # 可选邀请码：若提供则需满足 4-10 位，并保持唯一
    invite_code: Optional[str] = None


class TeamJoinPayload(BaseModel):
    user_id: str
    invite_code: str = Field(min_length=4, max_length=10)


class TeamUpdatePayload(BaseModel):
    teacher_id: str
    team_name: str = Field(min_length=1, max_length=100)


class TeamResponse(BaseModel):
    status: str = "ok"
    team: dict = Field(default_factory=dict)


# ── Chat ──────────────────────────────────────────────────────────────

class ChatRoomCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    room_type: str = "group"
    members: list[str] = Field(default_factory=list)
    admin_ids: list[str] = Field(default_factory=list)
    team_id: Optional[str] = None
    project_id: Optional[str] = None


class ChatRoomAddMemberPayload(BaseModel):
    user_id: str


class ChatMessageSendPayload(BaseModel):
    sender_id: str
    sender_name: str = ""
    msg_type: str = "text"
    content: str = ""
    mentions: list[str] = Field(default_factory=list)
    reply_to: Optional[str] = None


class ChatReactionPayload(BaseModel):
    user_id: str
    emoji: str


# ── Budget ────────────────────────────────────────────────────────────

class BudgetCreatePayload(BaseModel):
    name: str = "未命名方案"
    purpose: str = "business"


class BudgetSavePayload(BaseModel):
    project_costs: Optional[dict] = None
    business_finance: Optional[dict] = None
    competition_budget: Optional[dict] = None
    funding_plan: Optional[dict] = None
    name: Optional[str] = None
    visible_tabs: Optional[list[str]] = None
    ai_result: Optional[dict] = None
    ai_chat_history: Optional[list[dict]] = None


class BudgetAISuggestPayload(BaseModel):
    project_description: str = ""
    project_type: str = ""


class BudgetAIChatPayload(BaseModel):
    question: str = ""


# ── Business Plan ─────────────────────────────────────────────────────

class BusinessPlanGeneratePayload(BaseModel):
    project_id: str
    student_id: str = ""
    conversation_id: str = ""
    allow_low_confidence: bool = False
    # 生成模式：coursework（课程辅导）、competition（竞赛冲刺）、learning（项目教练）
    mode: Literal["coursework", "competition", "learning"] = "learning"


class BusinessPlanSectionUpdatePayload(BaseModel):
    content: str = ""
    field_map: dict = Field(default_factory=dict)
    display_title: str | None = None


class BusinessPlanExportPayload(BaseModel):
    export_mode: Literal["clean_final", "revision_marked"] = "clean_final"
    export_format: Literal["docx", "pdf"] = "docx"
    cover_info: dict = Field(default_factory=dict)


class BusinessPlanUpgradePayload(BaseModel):
    mode: Literal["basic", "full"] = "full"


class BusinessPlanExpandAnswer(BaseModel):
    question_id: str = ""
    question_text: str = ""
    text: str = ""


class BusinessPlanExpandPayload(BaseModel):
    answers: list[BusinessPlanExpandAnswer] = Field(default_factory=list)
    merge_strategy: Literal["append", "rewrite"] = "append"


class BusinessPlanResponse(BaseModel):
    status: str = "ok"
    plan: dict | None = None
    readiness: dict = Field(default_factory=dict)


class BusinessPlanQuestionsResponse(BaseModel):
    status: str = "ok"
    questions: list[dict] = Field(default_factory=list)


class BusinessPlanSuggestionsResponse(BaseModel):
    status: str = "ok"
    suggestions: list[dict] = Field(default_factory=list)


# ── 竞赛分支 / 教师评分 / 计划书对比 ────────────────────────────
class BusinessPlanForkCompetitionPayload(BaseModel):
    # 可选 override 的竞赛类型（用于定向优化，例如 "互联网+"、"挑战杯"）
    competition_type: str = ""
    # 是否强制重新抽取 KB 参考模板
    refresh_kb_reference: bool = True


class BusinessPlanRubricScore(BaseModel):
    section_id: str
    score: float = Field(ge=0, le=10)
    weight: float = Field(ge=0, le=5, default=1.0)
    comment: str = ""


class BusinessPlanGradingPayload(BaseModel):
    teacher_id: str = ""
    teacher_name: str = ""
    overall_score: float = Field(ge=0, le=100)
    grade: Literal["A", "B", "C", "D", "E"] = "B"
    passed: bool = True
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    rubric: list[BusinessPlanRubricScore] = Field(default_factory=list)


class BusinessPlanGradingResponse(BaseModel):
    status: str = "ok"
    grading: dict | None = None


class BusinessPlanComparePayload(BaseModel):
    plan_ids: list[str] = Field(min_length=2, max_length=5)
    focus_sections: list[str] = Field(default_factory=list)
    # 是否调用 LLM 产出差异建议（若关闭仅给出结构化 diff）
    use_llm: bool = True


class BusinessPlanCompareResponse(BaseModel):
    status: str = "ok"
    comparison: dict | None = None


# ── 竞赛教练模式 / 议题板 ────────────────────────────────────────
class BusinessPlanCoachingModePayload(BaseModel):
    mode: Literal["project", "competition"] = "project"


class BusinessPlanAgendaApplyPayload(BaseModel):
    agenda_ids: list[str] = Field(default_factory=list)
    target_section_map: dict[str, str] = Field(default_factory=dict)


class BusinessPlanAgendaPatchPayload(BaseModel):
    status: Literal["pending", "applied", "dismissed"] | None = None
    section_id_hint: str | None = None


# ── Finance Report ────────────────────────────────────────────────────

class FinanceReportGeneratePayload(BaseModel):
    user_id: str = Field(min_length=1)
    plan_id: str | None = None
    project_id: str | None = None
    conversation_id: str | None = None
    industry_hint: str = ""
    context_text: str = ""
    use_llm_explain: bool = True


class FinanceReportResponse(BaseModel):
    status: str = "ok"
    report: dict | None = None
    detail: str = ""


class FinanceReportStatusResponse(BaseModel):
    status: str = "idle"
    detail: str = ""
    updated_at: str = ""
