"use client";

import { CSSProperties, FormEvent, useEffect, useMemo, useState, useRef } from "react";
import Link from "next/link";
import { useAuth, logout } from "../hooks/useAuth";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8037").trim().replace(/\/+$/, "");
type Tab = "overview" | "assistant" | "conversation-analytics" | "submissions" | "compare" | "evidence" | "report" | "feedback" | "capability" | "rule-coverage" | "interventions" | "class" | "project" | "rubric" | "competition";
type TeamView = "comparison" | "team-detail" | "student-detail" | "project-detail";

// 风险规则名称映射
const RISK_RULE_NAMES: Record<string, string> = {
  "weak_user_evidence": "弱用户证据",
  "compliance_not_covered": "合规性覆盖不足",
  "market_size_fallacy": "市场规模谬误",
  "no_competitor_claim": "缺少竞争对手声明",
};

function getRuleDisplayName(ruleName: string): string {
  return RISK_RULE_NAMES[ruleName] || ruleName;
}

function parseServerTime(value?: string) {
  if (!value) return null;
  const normalized = /Z$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`;
  const d = new Date(normalized);
  return Number.isNaN(d.getTime()) ? null : d;
}

function formatBJTime(value?: string, withDate = true) {
  const d = parseServerTime(value);
  if (!d) return "";
  return new Intl.DateTimeFormat("zh-CN", withDate
    ? { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }
    : { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit" }).format(d);
}

const INTENT_ORDER = ["学习理解", "商业诊断", "方案设计", "材料润色", "路演表达", "综合咨询"];
const INTENT_COLORS: Record<string, string> = {
  "学习理解": "#73ccff",
  "商业诊断": "#6b8aff",
  "方案设计": "#5cbd8a",
  "材料润色": "#e0a84c",
  "路演表达": "#bd93f9",
  "综合咨询": "#9aa4bf",
};

function intentEntries(input: any): Array<{ label: string; value: number; color: string }> {
  const source = input && typeof input === "object" ? input : {};
  return INTENT_ORDER
    .map((label) => ({ label, value: Number(source[label] || 0), color: INTENT_COLORS[label] || "var(--accent)" }))
    .filter((item) => item.value > 0);
}

function dominantIntent(input: any) {
  const entries = intentEntries(input);
  return entries.sort((a, b) => b.value - a.value)[0]?.label || "综合咨询";
}

function sparklinePoints(values: number[], width = 180, height = 56) {
  if (!values.length) return "";
  const max = Math.max(1, ...values);
  return values.map((value, idx) => {
    const x = values.length === 1 ? width / 2 : (idx / (values.length - 1)) * width;
    const y = height - (value / max) * (height - 8) - 4;
    return `${x},${y}`;
  }).join(" ");
}

// 骨架屏加载器组件
function SkeletonLoader({ rows = 3, type = "bar" }: { rows?: number; type?: "bar" | "card" | "table" }) {
  return (
    <div style={{ opacity: 0.7 }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          style={{
            height: type === "bar" ? 40 : type === "card" ? 100 : 44,
            background: "var(--bg-card)",
            borderRadius: 10,
            marginBottom: 10,
            animation: "skeleton-loading 1.5s ease-in-out infinite",
            border: "1px solid var(--border)",
          }}
        />
      ))}
    </div>
  );
}

// 成功提示组件
function SuccessToast({ message, onClose }: { message: string; onClose: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onClose, 4000);
    return () => clearTimeout(timer);
  }, [onClose]);

  return (
    <div
      style={{
        position: "fixed",
        top: 72,
        right: 20,
        padding: "12px 20px",
        background: "var(--tch-success-soft, rgba(92,189,138,0.15))",
        color: "var(--tch-success, #5cbd8a)",
        border: "1px solid rgba(92,189,138,0.3)",
        borderRadius: 10,
        backdropFilter: "blur(12px)",
        animation: "toast-slide-in 0.3s ease-out",
        zIndex: 1000,
        fontWeight: 600,
        fontSize: 13,
      }}
    >
      ✓ {message}
    </div>
  );
}

function ErrorToast({ message, onClose }: { message: string; onClose: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onClose, 4000);
    return () => clearTimeout(timer);
  }, [onClose]);

  return (
    <div
      style={{
        position: "fixed",
        top: 72,
        right: 20,
        padding: "12px 20px",
        background: "var(--tch-danger-soft, rgba(224,112,112,0.15))",
        color: "var(--tch-danger, #e07070)",
        border: "1px solid rgba(224,112,112,0.3)",
        borderRadius: 10,
        backdropFilter: "blur(12px)",
        animation: "toast-slide-in 0.3s ease-out",
        zIndex: 1001,
        fontWeight: 600,
        fontSize: 13,
      }}
    >
      ⚠ {message}
    </div>
  );
}

// 动画计数器组件
function AnimatedNumber({ value, duration = 800, decimals = 0 }: { value: number; duration?: number; decimals?: number }) {
  const [display, setDisplay] = useState(0);
  const prevRef = useRef(0);

  useEffect(() => {
    const start = prevRef.current;
    const startTime = performance.now();
    let frameId: number;
    function tick(now: number) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(start + (value - start) * eased);
      if (progress < 1) frameId = requestAnimationFrame(tick);
      else prevRef.current = value;
    }
    frameId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frameId);
  }, [value, duration]);

  return <>{display.toFixed(decimals)}</>;
}

// ── 雷达图组件 ──
function RadarChart({ data, size = 230 }: { data: Array<{ label: string; value: number; max: number }>; size?: number }) {
  const n = data.length;
  if (n < 3) return null;
  const cx = size / 2, cy = size / 2, r = size * 0.34;
  const step = (2 * Math.PI) / n;
  const pt = (i: number, ratio: number) => ({
    x: cx + r * ratio * Math.cos(step * i - Math.PI / 2),
    y: cy + r * ratio * Math.sin(step * i - Math.PI / 2),
  });
  const gridLevels = [0.25, 0.5, 0.75, 1];
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ display: "block", margin: "0 auto" }}>
      {gridLevels.map(lv => (
        <polygon key={lv} points={data.map((_, i) => { const p = pt(i, lv); return `${p.x},${p.y}`; }).join(" ")} fill="none" stroke="var(--border)" strokeWidth="1" opacity={0.45} />
      ))}
      {data.map((_, i) => { const p = pt(i, 1); return <line key={i} x1={cx} y1={cy} x2={p.x} y2={p.y} stroke="var(--border)" strokeWidth="1" opacity={0.3} />; })}
      <polygon
        points={data.map((d, i) => { const p = pt(i, d.max > 0 ? Math.min(d.value / d.max, 1) : 0); return `${p.x},${p.y}`; }).join(" ")}
        fill="rgba(107,138,255,0.18)" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round"
      />
      {data.map((d, i) => { const p = pt(i, d.max > 0 ? Math.min(d.value / d.max, 1) : 0); return <circle key={`d${i}`} cx={p.x} cy={p.y} r="3.5" fill="var(--accent)" stroke="var(--bg-primary)" strokeWidth="1.5" />; })}
      {data.map((d, i) => {
        const p = pt(i, 1.22);
        return <text key={`l${i}`} x={p.x} y={p.y} textAnchor="middle" dominantBaseline="central" fill="var(--text-secondary)" fontSize="10" fontWeight="500">{d.label}</text>;
      })}
    </svg>
  );
}

// ── 环形图组件 ──
function DonutChart({ data, size = 170 }: { data: Array<{ label: string; value: number; color: string }>; size?: number }) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const total = data.reduce((s, d) => s + d.value, 0);
  if (total === 0) return null;
  const cx = size / 2, cy = size / 2, outerR = size * 0.42, innerR = outerR - 28;
  let cum = -Math.PI / 2;
  const arcs = data.map((d, idx) => {
    const angle = (d.value / total) * 2 * Math.PI;
    const s = cum; const e = cum + angle; cum = e;
    const lg = angle > Math.PI ? 1 : 0;
    const oR = hoverIdx === idx ? outerR + 4 : outerR;
    const path = `M ${cx + oR * Math.cos(s)} ${cy + oR * Math.sin(s)} A ${oR} ${oR} 0 ${lg} 1 ${cx + oR * Math.cos(e)} ${cy + oR * Math.sin(e)} L ${cx + innerR * Math.cos(e)} ${cy + innerR * Math.sin(e)} A ${innerR} ${innerR} 0 ${lg} 0 ${cx + innerR * Math.cos(s)} ${cy + innerR * Math.sin(s)} Z`;
    return <path key={idx} d={path} fill={d.color} opacity={hoverIdx === idx ? 1 : 0.82} style={{ transition: "all 0.2s", cursor: "pointer" }} onMouseEnter={() => setHoverIdx(idx)} onMouseLeave={() => setHoverIdx(null)} />;
  });
  return (
    <div style={{ position: "relative", width: size, margin: "0 auto" }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ display: "block" }}>
        {arcs}
        <text x={cx} y={cy - 6} textAnchor="middle" fill="var(--text-primary)" fontSize="22" fontWeight="700">{total}</text>
        <text x={cx} y={cy + 12} textAnchor="middle" fill="var(--text-muted)" fontSize="11">{hoverIdx !== null ? data[hoverIdx].label : "总计"}</text>
      </svg>
    </div>
  );
}

// ── 面积图组件 ──
function AreaChart({ data, width = 340, height = 110, color = "var(--accent)" }: { data: Array<{ label: string; value: number }>; width?: number; height?: number; color?: string }) {
  if (data.length < 2) return <p style={{ color: "var(--text-muted)", fontSize: 12, textAlign: "center" }}>数据不足</p>;
  const maxV = Math.max(1, ...data.map(d => d.value));
  const pad = { t: 8, b: 22, l: 2, r: 2 };
  const cW = width - pad.l - pad.r, cH = height - pad.t - pad.b;
  const pts = data.map((d, i) => ({ x: pad.l + (i / (data.length - 1)) * cW, y: pad.t + cH - (d.value / maxV) * cH }));
  const line = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");
  const area = `${line} L ${pts[pts.length - 1].x} ${pad.t + cH} L ${pts[0].x} ${pad.t + cH} Z`;
  const uid = `ag${Math.random().toString(36).slice(2, 8)}`;
  return (
    <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ display: "block" }}>
      <defs><linearGradient id={uid} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity="0.35" /><stop offset="100%" stopColor={color} stopOpacity="0.03" /></linearGradient></defs>
      <path d={area} fill={`url(#${uid})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      {pts.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r="3" fill={color} stroke="var(--bg-primary)" strokeWidth="1.5" opacity={i === 0 || i === pts.length - 1 ? 1 : 0.5} />)}
      {data.map((d, i) => { const show = data.length <= 7 || i % Math.ceil(data.length / 6) === 0 || i === data.length - 1; return show ? <text key={i} x={pts[i].x} y={height - 3} textAnchor="middle" fill="var(--text-muted)" fontSize="9">{d.label.slice(5)}</text> : null; })}
    </svg>
  );
}

// ── 散点图组件 ──
function ScatterPlot({ data, width = 300, height = 200, xLabel = "提交次数", yLabel = "均分" }: { data: Array<{ id: string; x: number; y: number }>; width?: number; height?: number; xLabel?: string; yLabel?: string }) {
  const [hover, setHover] = useState<string | null>(null);
  if (data.length === 0) return null;
  const pad = { t: 14, b: 30, l: 38, r: 14 };
  const cW = width - pad.l - pad.r, cH = height - pad.t - pad.b;
  const maxX = Math.max(1, ...data.map(d => d.x)), maxY = Math.max(1, ...data.map(d => d.y));
  return (
    <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: "block" }}>
      {[0, 0.5, 1].map(r => <line key={r} x1={pad.l} y1={pad.t + cH * (1 - r)} x2={pad.l + cW} y2={pad.t + cH * (1 - r)} stroke="var(--border)" strokeWidth="1" opacity="0.35" />)}
      {[0, 0.5, 1].map(r => <text key={`y${r}`} x={pad.l - 6} y={pad.t + cH * (1 - r) + 3} textAnchor="end" fill="var(--text-muted)" fontSize="9">{(maxY * r).toFixed(1)}</text>)}
      {[0, 0.5, 1].map(r => <text key={`x${r}`} x={pad.l + cW * r} y={height - 8} textAnchor="middle" fill="var(--text-muted)" fontSize="9">{Math.round(maxX * r)}</text>)}
      <text x={pad.l + cW / 2} y={height} textAnchor="middle" fill="var(--text-muted)" fontSize="9">{xLabel}</text>
      <text x={8} y={pad.t + cH / 2} textAnchor="middle" fill="var(--text-muted)" fontSize="9" transform={`rotate(-90,8,${pad.t + cH / 2})`}>{yLabel}</text>
      {data.map(d => {
        const px = pad.l + (d.x / maxX) * cW, py = pad.t + cH - (d.y / maxY) * cH;
        const c = d.y >= 7 ? "rgba(92,189,138,0.85)" : d.y >= 5 ? "rgba(232,168,76,0.85)" : "rgba(224,112,112,0.85)";
        const isH = hover === d.id;
        return (
          <g key={d.id} onMouseEnter={() => setHover(d.id)} onMouseLeave={() => setHover(null)} style={{ cursor: "pointer" }}>
            <circle cx={px} cy={py} r={isH ? 8 : 5.5} fill={c} stroke="var(--bg-primary)" strokeWidth="2" style={{ transition: "r 0.2s" }} />
            {isH && <text x={px} y={py - 12} textAnchor="middle" fill="var(--text-primary)" fontSize="10" fontWeight="600">{d.id.slice(0, 12)} ({d.y.toFixed(1)})</text>}
          </g>
        );
      })}
    </svg>
  );
}

// ── 箱型图组件 ──
function BoxPlotChart({ data, width = 300, height = 70 }: { data: { min: number; q1: number; median: number; q3: number; max: number; avg: number }; width?: number; height?: number }) {
  const maxV = 10;
  const pad = { l: 30, r: 16, t: 14, b: 20 };
  const cW = width - pad.l - pad.r, midY = pad.t + (height - pad.t - pad.b) / 2;
  const sc = (v: number) => pad.l + (v / maxV) * cW;
  return (
    <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: "block" }}>
      <line x1={pad.l} y1={height - pad.b} x2={pad.l + cW} y2={height - pad.b} stroke="var(--border)" strokeWidth="1" />
      {[0, 2, 4, 6, 8, 10].map(v => (
        <g key={v}><line x1={sc(v)} y1={height - pad.b} x2={sc(v)} y2={height - pad.b + 4} stroke="var(--border)" strokeWidth="1" /><text x={sc(v)} y={height - 3} textAnchor="middle" fill="var(--text-muted)" fontSize="9">{v}</text></g>
      ))}
      <line x1={sc(data.min)} y1={midY} x2={sc(data.max)} y2={midY} stroke="var(--text-muted)" strokeWidth="1.5" strokeDasharray="3 2" />
      <line x1={sc(data.min)} y1={midY - 10} x2={sc(data.min)} y2={midY + 10} stroke="var(--text-muted)" strokeWidth="1.5" />
      <line x1={sc(data.max)} y1={midY - 10} x2={sc(data.max)} y2={midY + 10} stroke="var(--text-muted)" strokeWidth="1.5" />
      <rect x={sc(data.q1)} y={midY - 16} width={Math.max(sc(data.q3) - sc(data.q1), 2)} height={32} rx="4" fill="rgba(107,138,255,0.18)" stroke="var(--accent)" strokeWidth="1.5" />
      <line x1={sc(data.median)} y1={midY - 16} x2={sc(data.median)} y2={midY + 16} stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx={sc(data.avg)} cy={midY} r="4.5" fill="var(--tch-warning)" stroke="var(--bg-primary)" strokeWidth="2" />
      <text x={sc(data.avg)} y={midY - 22} textAnchor="middle" fill="var(--tch-warning)" fontSize="9" fontWeight="600">均值 {data.avg.toFixed(1)}</text>
    </svg>
  );
}

export default function TeacherPage() {
  const currentUser = useAuth("teacher");
  const [tab, setTab] = useState<Tab>("overview");
  const [assistantView, setAssistantView] = useState<"queue" | "assessment" | "intervention" | "conversation" | "impact">("queue");
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [projectId, setProjectId] = useState("");
  const [teacherId, setTeacherId] = useState("teacher-001");
  const [classId, setClassId] = useState("");
  const [cohortId, setCohortId] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState("正在加载");
  const [successMessage, setSuccessMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  const [dashboard, setDashboard] = useState<any>(null);
  const [submissions, setSubmissions] = useState<any[]>([]);
  const [compareData, setCompareData] = useState<any>(null);
  const [evidence, setEvidence] = useState<any>(null);
  const [report, setReport] = useState("");
  const [reportSnapshot, setReportSnapshot] = useState<any>(null);

  const [feedbackText, setFeedbackText] = useState("");
  const [feedbackTags, setFeedbackTags] = useState("evidence,feasibility");
  const [selectedProject, setSelectedProject] = useState("");
  const [selectedLogicalProjectId, setSelectedLogicalProjectId] = useState("");
  const [expandedSubmission, setExpandedSubmission] = useState<number | null>(null);

  // 班级页面状态
  const [classTabInput, setClassTabInput] = useState("");
  const [classIdConfirmed, setClassIdConfirmed] = useState(false);
  const [classView, setClassView] = useState<"overview" | "student" | "student-project">("overview");
  const [classSubmissions, setClassSubmissions] = useState<any[]>([]);
  const [selectedClassStudent, setSelectedClassStudent] = useState("");
  const [selectedClassStudentProject, setSelectedClassStudentProject] = useState("");

  const [teamData, setTeamData] = useState<{ my_teams: any[]; other_teams: any[] } | null>(null);
  const [selectedTeamId, setSelectedTeamId] = useState<string>("");
  const [teamView, setTeamView] = useState<TeamView>("comparison");
  const [selectedTeamStudentId, setSelectedTeamStudentId] = useState("");
  const [selectedTeamProjectId, setSelectedTeamProjectId] = useState("");
  const [showCreateTeam, setShowCreateTeam] = useState(false);
  const [newTeamName, setNewTeamName] = useState("");
  const [createdInviteCode, setCreatedInviteCode] = useState("");

  // 项目页面状态
  const [projectTabInput, setProjectTabInput] = useState("");
  const [projectIdConfirmed, setProjectIdConfirmed] = useState(false);
  const [projectWorkspaceView, setProjectWorkspaceView] = useState<"insight" | "library" | "compare" | "detail">("insight");
  const [projectBoardCategory, setProjectBoardCategory] = useState("全部项目");
  const [projectBoardSort, setProjectBoardSort] = useState<"risk" | "score" | "improvement" | "submissions">("risk");
  const [projectCompareSelection, setProjectCompareSelection] = useState<string[]>([]);

  // 饼状图悬浮状态
  const [hoveredCategory, setHoveredCategory] = useState<string | null>(null);
  const [hoveredRisk, setHoveredRisk] = useState<string | null>(null);
  const [overviewSubmissions, setOverviewSubmissions] = useState<any[]>([]);
  const [hoveredKpi, setHoveredKpi] = useState<string | null>(null);

  // New state for enhanced features
  const [capabilityMap, setCapabilityMap] = useState<any>(null);
  const [ruleCoverage, setRuleCoverage] = useState<any>(null);
  const [projectDiagnosis, setProjectDiagnosis] = useState<any>(null);
  const [rubricAssessment, setRubricAssessment] = useState<any>(null);
  const [competitionScore, setCompetitionScore] = useState<any>(null);
  const [projectRuleDashboard, setProjectRuleDashboard] = useState<any>(null);
  const [projectEvidenceTrace, setProjectEvidenceTrace] = useState<any>(null);
  const [projectWorkbenchSummary, setProjectWorkbenchSummary] = useState<any>(null);
  const [projectCaseBenchmark, setProjectCaseBenchmark] = useState<any>(null);
  const [projectStructuredReport, setProjectStructuredReport] = useState<any>(null);
  const [hyperLibrary, setHyperLibrary] = useState<any>(null);
  const [conversationAnalytics, setConversationAnalytics] = useState<any>(null);
  const [projectStructuredReportLoading, setProjectStructuredReportLoading] = useState(false);
  const [teachingInterventions, setTeachingInterventions] = useState<any>(null);
  const [assistantDashboard, setAssistantDashboard] = useState<any>(null);
  const [assistantAssessment, setAssistantAssessment] = useState<any>(null);
  const [assistantInterventionData, setAssistantInterventionData] = useState<any>(null);
  const [assistantConversationEval, setAssistantConversationEval] = useState<any>(null);
  const [assistantImpact, setAssistantImpact] = useState<any>(null);
  const [assistantLastUpdated, setAssistantLastUpdated] = useState("");
  const [assistantSelectedTeamId, setAssistantSelectedTeamId] = useState("");
  const [assistantDraftIntervention, setAssistantDraftIntervention] = useState<any>({
    scope_type: "team",
    scope_id: "",
    source_type: "class_plan",
    target_student_id: "",
    project_id: "",
    logical_project_id: "",
    title: "",
    reason_summary: "",
    action_items: [],
    acceptance_criteria: [],
    priority: "medium",
  });
  const [assistantSmartSelectResult, setAssistantSmartSelectResult] = useState<any>(null);
  const [, setAssistantReviewDraft] = useState<any>({
    title: "",
    summary: "",
    strengths: [],
    weaknesses: [],
    action_items: [],
    focus_tags: [],
    score_band: "",
  });

  // 文件级反馈状态
  const [studentFiles, setStudentFiles] = useState<any[]>([]);
  const [projectSubmissionHistory, setProjectSubmissionHistory] = useState<any[]>([]);
  const [feedbackSortMode, setFeedbackSortMode] = useState<"urgent" | "activity" | "score">("urgent");
  const [feedbackCategoryFilter, setFeedbackCategoryFilter] = useState("全部类别");
  const [feedbackWorkspaceView, setFeedbackWorkspaceView] = useState<"queue" | "timeline" | "reader" | "history">("queue");
  const [feedbackTimelinePage, setFeedbackTimelinePage] = useState(1);
  const [feedbackActionView, setFeedbackActionView] = useState<"write" | "annotate" | "upload">("write");
  const [selectedHistorySubmissionId, setSelectedHistorySubmissionId] = useState("");
  const [selectedFile, setSelectedFile] = useState<any>(null);
  const [fileContent, setFileContent] = useState("");
  const [editedContent, setEditedContent] = useState("");
  const [isEditMode, setIsEditMode] = useState(false);
  const [documentEdits, setDocumentEdits] = useState<any[]>([]);
  const [editSummary, setEditSummary] = useState("");
  const [feedbackAnnotations, setFeedbackAnnotations] = useState<any[]>([]);
  const [annotationText, setAnnotationText] = useState("");
  const [annotationType, setAnnotationType] = useState("issue");
  const [annotationAnchorText, setAnnotationAnchorText] = useState("");
  const [annotationAnchorPosition, setAnnotationAnchorPosition] = useState(0);
  const [feedbackAiSuggestions, setFeedbackAiSuggestions] = useState<any[]>([]);
  const [feedbackAiLoading, setFeedbackAiLoading] = useState(false);
  const [feedbackFileToUpload, setFeedbackFileToUpload] = useState<File | null>(null);
  const [feedbackFiles, setFeedbackFiles] = useState<any[]>([]);
  const [projectFeedbackHistory, setProjectFeedbackHistory] = useState<any[]>([]);
  const [onlinePreviewData, setOnlinePreviewData] = useState<any>(null);  // 在线预览数据（PDF base64、HTML等）
  const [onlinePreviewLoading, setOnlinePreviewLoading] = useState(false);  // 在线预览加载状态
  const [pdfAnalysisData, setPdfAnalysisData] = useState<any>(null);  // PDF LLM分析数据（摘要、要点等）
  const [pdfAnalysisLoading, setPdfAnalysisLoading] = useState(false);  // PDF分析加载状态
  const feedbackFileInputRef = useRef<HTMLInputElement>(null);

  async function api(path: string, opts?: RequestInit) {
    const r = await fetch(`${API}${path}`, opts);
    if (!r.ok) {
      let msg = `请求失败 (${r.status})`;
      try { const j = await r.json(); msg = j.detail || j.message || msg; } catch {}
      throw new Error(msg);
    }
    return r.json();
  }

  // 响应验证函数
  function validateResponse(response: any, errorMessage: string = "API调用失败"): any {
    if (!response) {
      throw new Error(errorMessage);
    }
    if (response.error) {
      throw new Error(response.error);
    }
    if (response.status === "error") {
      throw new Error(response.message || errorMessage);
    }
    return response;
  }

  function asLines(value: any): string[] {
    if (Array.isArray(value)) return value.map((x) => String(x || "").trim()).filter(Boolean);
    return String(value || "").split("\n").map((x) => x.trim()).filter(Boolean);
  }

  // 提取有效内容函数 - 去除过多空白行、清理格式
  function extractValidContent(text: string): string {
    if (!text || typeof text !== "string") return "";
    
    // 去除HTML标签
    let cleaned = text.replace(/<[^>]*>/g, "");
    
    // 分割成行
    let lines = cleaned.split("\n");
    
    // 清理每一行、去除纯空白行、去除过多连续空行
    let cleanedLines: string[] = [];
    let emptyLineCount = 0;
    
    for (let line of lines) {
      const trimmed = line.trim();
      if (trimmed === "") {
        emptyLineCount++;
        // 最多保留2个连续空行
        if (emptyLineCount <= 2) {
          cleanedLines.push("");
        }
      } else {
        emptyLineCount = 0;
        cleanedLines.push(trimmed);
      }
    }
    
    // 拼接并去除两端空白
    let result = cleanedLines.join("\n").trim();
    
    // 如果文本过长，截断到合理长度
    const maxLen = 3000;
    if (result.length > maxLen) {
      result = result.substring(0, maxLen) + "\n\n[内容过长，已截断...]";
    }
    
    return result;
  }

  // 获取文件类型显示名称和图标
  function getFileTypeInfo(fileName: string): { type: string; icon: string; displayName: string; canPreview: boolean } {
    const ext = (fileName.split(".").pop() || "").toLowerCase();
    const typeMap: Record<string, { icon: string; displayName: string; canPreview: boolean }> = {
      pdf: { icon: "📄", displayName: "PDF 文档", canPreview: false },
      ppt: { icon: "🎜", displayName: "PowerPoint 97-2003", canPreview: false },
      pptx: { icon: "🎜", displayName: "PowerPoint 演示文稿", canPreview: false },
      docx: { icon: "📋", displayName: "Word 文档", canPreview: false },
      doc: { icon: "📋", displayName: "Word 97-2003", canPreview: false },
      txt: { icon: "📝", displayName: "纯文本文件", canPreview: true },
      md: { icon: "🔤", displayName: "Markdown 文档", canPreview: true },
      xlsx: { icon: "📊", displayName: "Excel 表格", canPreview: false },
      xls: { icon: "📊", displayName: "Excel 97-2003", canPreview: false },
      csv: { icon: "📊", displayName: "CSV 数据文件", canPreview: true },
    };
    
    const info = typeMap[ext] || { icon: "📎", displayName: `${ext.toUpperCase()} 文件`, canPreview: false };
    return { type: ext, ...info };
  }

  function serialLabel(prefix: string, value?: number | string): string {
    const num = Number(value || 0);
    if (!Number.isFinite(num) || num <= 0) return prefix;
    return `${prefix} ${String(num).padStart(2, "0")}`;
  }

  function compactId(value: string, keep = 6): string {
    const raw = String(value || "").trim();
    if (!raw) return "未命名";
    if (raw.length <= keep * 2 + 3) return raw;
    return `${raw.slice(0, keep)}...${raw.slice(-keep)}`;
  }

  function buildCaseBenchmarkExportText(benchmark: any): string {
    if (!benchmark) return "";
    const sp = benchmark.student_project || {};
    const cases = (benchmark.top_cases || []).slice(0, 3);
    const studentRisks: string[] = benchmark.student_risks || [];

    const headerLines = [
      `项目：${sp.project_name || sp.logical_project_id || sp.project_id || "未命名项目"}`,
      `当前得分：${Number(sp.overall_score || 0).toFixed(1)}，风险水平：${sp.risk_level || "-"}`,
      studentRisks.length ? `当前主要风险：${studentRisks.join("、")}` : "当前主要风险：暂无明显集中风险",
      "",
      "[案例对标推荐]",
    ];

    const caseLines: string[] = [];
    cases.forEach((c: any, idx: number) => {
      const rubric = (c.rubric_coverage || []).filter((r: any) => r && r.covered).map((r: any) => r.rubric_item || r.item).filter(Boolean);
      const riskFlags: string[] = c.risk_flags || [];
      const avoided = riskFlags.filter((r) => !studentRisks.includes(r));
      caseLines.push(
        `${idx + 1}. ${c.project_name || c.case_id || "案例"}（${c.category || "未分类"}，相似度 ${Number(c.avg_similarity || c.max_similarity || 0).toFixed(2)}）`,
      );
      if (rubric.length) {
        caseLines.push(`   · Rubric 强项：${rubric.join("、")}`);
      }
      if (avoided.length) {
        caseLines.push(`   · 已成功规避的风险：${avoided.join("、")}`);
      } else if (riskFlags.length) {
        caseLines.push(`   · 案例风险标签：${riskFlags.join("、")}`);
      }
    });

    if (!caseLines.length) {
      caseLines.push("暂无可用案例对标记录。先让学生与助教对话几轮，再刷新本区块。");
    }

    return [...headerLines, ...caseLines].join("\n");
  }

  async function copyCaseBenchmarkToClipboard() {
    if (!projectCaseBenchmark) {
      setErrorMessage("请先生成当前项目的案例对标");
      return;
    }
    try {
      const text = buildCaseBenchmarkExportText(projectCaseBenchmark);
      if (!text) {
        setErrorMessage("当前没有可导出的案例对标内容");
        return;
      }
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        setSuccessMessage("已复制案例对标摘要，可直接粘贴到PPT或文档中");
      } else {
        setErrorMessage("当前环境不支持一键复制，请手动选择文本");
      }
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "复制案例对标内容失败");
    }
  }

  function feedbackUrgencyScore(item: any): number {
    const riskCount = Array.isArray(item?.top_risks) ? item.top_risks.length : Array.isArray(item?.triggered_rules) ? item.triggered_rules.length : 0;
    const lowScoreBoost = Math.max(0, 10 - Number(item?.latest_score || item?.overall_score || 0));
    const backlogBoost = Number(item?.submission_count || 0) * 0.2;
    return riskCount * 10 + lowScoreBoost + backlogBoost;
  }

  function inferProjectCategory(item: any): string {
    const text = [
      item?.project_name,
      item?.summary,
      item?.team_name,
      item?.project_phase,
      item?.dominant_intent,
    ].join(" ").toLowerCase();
    if (/(竞赛|比赛|大赛|challenge|contest|赛道|路演|答辩)/.test(text)) return "参赛项目";
    if (/(课程|课堂|作业|课设|教学|辅导|实验|结课|论文)/.test(text)) return "课程辅导";
    if (/(创新|科技|研发|发明|智能|算法|ai|模型|技术)/.test(text)) return "科技创新";
    if (/(交通|出行|物流|车路|运输|轨道|公交|停车)/.test(text)) return "交通运输";
    if (/(商业|市场|运营|用户|品牌|创业|产品|商业模式)/.test(text)) return "商业策划";
    return "综合探索";
  }

  function categoryAccent(category: string): string {
    const map: Record<string, string> = {
      "参赛项目": "var(--accent)",
      "课程辅导": "var(--tch-success)",
      "科技创新": "#8b5cf6",
      "交通运输": "#06b6d4",
      "商业策划": "#f59e0b",
      "综合探索": "var(--text-muted)",
    };
    return map[category] || "var(--accent)";
  }

  function buildProjectCompareKey(item: any): string {
    return `${item?.root_project_id || ""}::${item?.logical_project_id || ""}`;
  }

  function captureAnnotationAnchor() {
    const selectedText = typeof window !== "undefined" ? window.getSelection?.()?.toString().trim() || "" : "";
    if (!selectedText) {
      setErrorMessage("请先在正文中选中一段文字，再生成划线批注");
      return;
    }
    const source = extractValidContent(editedContent || fileContent || "");
    const index = source.indexOf(selectedText);
    setAnnotationAnchorText(selectedText);
    setAnnotationAnchorPosition(index >= 0 ? index : 0);
    setSuccessMessage("已捕获当前选中文本，可作为划线批注锚点");
  }

  function renderHighlightPreview(text: string, anchorText: string) {
    const source = extractValidContent(text || "");
    if (!anchorText) {
      return <div className="feedback-highlight-empty">先从 AI 引文中点选，或在正文里手动选中一句话。</div>;
    }
    const index = source.indexOf(anchorText);
    if (index < 0) {
      return (
        <div className="feedback-highlight-preview">
          <mark>{anchorText}</mark>
        </div>
      );
    }
    const start = Math.max(0, index - 70);
    const end = Math.min(source.length, index + anchorText.length + 70);
    const prefix = start > 0 ? `...${source.slice(start, index)}` : source.slice(start, index);
    const suffix = end < source.length ? `${source.slice(index + anchorText.length, end)}...` : source.slice(index + anchorText.length, end);
    return (
      <div className="feedback-highlight-preview">
        <span>{prefix}</span>
        <mark>{anchorText}</mark>
        <span>{suffix}</span>
      </div>
    );
  }

  function flattenAnnotationItems(records: any[]): any[] {
    return (records || []).flatMap((record: any) =>
      (record?.annotations || []).map((item: any, idx: number) => ({
        annotation_id: record?.annotation_id || `${record?.created_at || "annotation"}-${idx}`,
        created_at: record?.created_at || "",
        teacher_id: record?.teacher_id || "",
        overall_feedback: record?.overall_feedback || "",
        content: item?.content || "",
        annotation_type: item?.annotation_type || "issue",
        type: item?.type || "comment",
        position: Number(item?.position || 0),
        length: Number(item?.length || 0),
        quote: item?.quote || "",
      }))
    ).sort((a: any, b: any) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
  }

  function annotationTone(type: string) {
    const tones: Record<string, { label: string; bg: string; border: string; text: string }> = {
      praise: { label: "亮点", bg: "rgba(92,189,138,0.12)", border: "rgba(92,189,138,0.28)", text: "var(--tch-success)" },
      issue: { label: "问题", bg: "rgba(255,95,95,0.12)", border: "rgba(255,95,95,0.28)", text: "var(--tch-danger)" },
      suggest: { label: "建议", bg: "rgba(107,138,255,0.12)", border: "rgba(107,138,255,0.28)", text: "var(--accent)" },
      question: { label: "追问", bg: "rgba(232,168,76,0.12)", border: "rgba(232,168,76,0.28)", text: "var(--tch-warning)" },
    };
    return tones[type] || tones.issue;
  }

  function buildReviewSectionsFromText(text: string) {
    const source = extractValidContent(text || "").trim();
    if (!source) return [];
    const rawBlocks = source
      .split(/\n{2,}/)
      .map((item) => item.trim())
      .filter(Boolean);
    const blocks = rawBlocks.length > 0 ? rawBlocks : source.split(/\n/).map((item) => item.trim()).filter(Boolean);
    const sections: Array<{ id: number; text: string; position: number }> = [];
    let cursor = 0;
    let buffer = "";
    blocks.forEach((block) => {
      const next = buffer ? `${buffer}\n\n${block}` : block;
      if (next.length < 260) {
        buffer = next;
        return;
      }
      const position = source.indexOf(next, cursor >= 0 ? cursor : 0);
      sections.push({
        id: sections.length,
        text: next.slice(0, 900),
        position: position >= 0 ? position : cursor,
      });
      cursor = (position >= 0 ? position : cursor) + next.length;
      buffer = "";
    });
    if (buffer) {
      const position = source.indexOf(buffer, cursor >= 0 ? cursor : 0);
      sections.push({
        id: sections.length,
        text: buffer.slice(0, 900),
        position: position >= 0 ? position : cursor,
      });
    }
    return sections.slice(0, 20);
  }

  function normalizeAiAnnotationType(type: string) {
    if (type === "suggestion") return "suggest";
    if (type === "praise" || type === "issue" || type === "question" || type === "suggest") return type;
    return "issue";
  }

  function renderAnnotatedDocument(text: string, annotationRecords: any[], aiSuggestions: any[] = []) {
    const source = extractValidContent(text || "");
    const teacherAnnotations = flattenAnnotationItems(annotationRecords)
      .filter((item: any) => item.quote || item.length > 0)
      .map((item: any) => ({ ...item, source: "teacher" }));
    const machineAnnotations = (aiSuggestions || [])
      .filter((item: any) => item.quote || item.length > 0)
      .map((item: any) => ({ ...item, source: "ai" }));
    const annotations = [...teacherAnnotations, ...machineAnnotations]
      .sort((a: any, b: any) => {
        const delta = Number(a.position || 0) - Number(b.position || 0);
        if (delta !== 0) return delta;
        return a.source === "teacher" ? -1 : 1;
      });
    if (!source) return <div className="feedback-reader-empty">当前提交暂无可显示的正文内容。</div>;
    if (!annotations.length) return <div className="feedback-annotated-text">{source}</div>;
    const nodes: JSX.Element[] = [];
    let cursor = 0;
    annotations.forEach((item: any, idx: number) => {
      const quote = item.quote || "";
      const start = Math.max(cursor, Number(item.position || 0));
      const inferredEnd = quote ? start + quote.length : start + Math.max(0, Number(item.length || 0));
      if (start > cursor) {
        nodes.push(<span key={`plain-${idx}`}>{source.slice(cursor, start)}</span>);
      }
      const slice = source.slice(start, inferredEnd) || quote;
      const tone = annotationTone(item.annotation_type);
      nodes.push(
        <mark
          key={`annot-${idx}`}
          className={`feedback-inline-mark ${item.annotation_type || "issue"} ${item.source === "ai" ? "ai" : "teacher"}`}
          title={`${item.source === "ai" ? "AI候选" : "教师批注"} ${tone.label}：${item.content || item.overall_feedback || "已批注"}`}
        >
          {slice}
        </mark>
      );
      cursor = Math.max(cursor, inferredEnd);
    });
    if (cursor < source.length) nodes.push(<span key="plain-tail">{source.slice(cursor)}</span>);
    return <div className="feedback-annotated-text">{nodes}</div>;
  }

  function markAssistantUpdated() {
    setAssistantLastUpdated(new Date().toISOString());
  }

  function toggleProjectCompareSelection(projectKey: string) {
    setProjectCompareSelection((prev) => {
      if (prev.includes(projectKey)) return prev.filter((item) => item !== projectKey);
      if (prev.length >= 2) return [prev[1], projectKey];
      return [...prev, projectKey];
    });
  }

  function randomizeProjectCompareSelection() {
    const pool = [...filteredProjectCatalog];
    if (pool.length < 2) return;
    for (let idx = pool.length - 1; idx > 0; idx -= 1) {
      const swap = Math.floor(Math.random() * (idx + 1));
      [pool[idx], pool[swap]] = [pool[swap], pool[idx]];
    }
    setProjectCompareSelection(pool.slice(0, 2).map((item: any) => item.project_key));
  }

  // 生成文件预览区域的内容
  function renderFilePreview(selectedFile: any, editedContent: string, isEditMode: boolean) {
    if (!selectedFile) return null;
    
    const fileInfo = getFileTypeInfo(selectedFile.filename || "");
    
    if (isEditMode) {
      // 编辑模式：显示可编辑的纯文本框（无图片）
      return (
        <div>
          <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginBottom: "8px", padding: "0 4px" }}>
            ✏️ 编辑模式 - 纯文本（仅显示文字内容，不包含图片或格式）
          </div>
          <textarea
            value={editedContent}
            onChange={(e) => setEditedContent(e.target.value)}
            style={{
              width: "100%",
              maxHeight: "400px",
              padding: "12px",
              borderRadius: "8px",
              border: "2px solid var(--accent)",
              fontSize: "13px",
              lineHeight: "1.6",
              fontFamily: "monospace",
              boxSizing: "border-box",
              background: "var(--bg-card)",
            }}
          />
        </div>
      );
    }
    
    // 查看模式：首先尝试使用在线预览数据
    
    // PDF在线预览（base64编码） + LLM分析结果
    if (onlinePreviewData?.type === "pdf" && onlinePreviewData?.pdf_base64) {
      const pdfDataUrl = `data:application/pdf;base64,${onlinePreviewData.pdf_base64}`;
      const analysis = pdfAnalysisData?.analysis;
      const pdfStats = pdfAnalysisData?.pdf_stats;
      
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          {/* 工具栏 */}
          <div style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "10px 12px",
            backgroundColor: "var(--bg-card)",
            borderRadius: "8px",
            border: "1px solid var(--border)",
          }}>
            <div style={{ fontSize: "12px", color: "var(--text-secondary)", fontWeight: "500" }}>
              📄 PDF 文档 - 共 {onlinePreviewData.page_count || "?"} 页 ({Math.round((onlinePreviewData.file_size || 0) / 1024)} KB)
            </div>
            <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
              {pdfAnalysisLoading && (
                <span style={{ fontSize: "12px", color: "var(--tch-warning)" }}>⚙️ 正在分析...</span>
              )}
              <a
                href={pdfDataUrl}
                download={selectedFile.filename}
                style={{
                  padding: "6px 12px",
                  fontSize: "12px",
                  backgroundColor: "var(--accent)",
                  color: "var(--bg-secondary)",
                  textDecoration: "none",
                  border: "none",
                  borderRadius: "8px",
                  cursor: "pointer",
                  transition: "background-color 0.2s",
                }}
              >
                ⬇️ 下载原文件
              </a>
            </div>
          </div>

          {/* 主容器：PDF + 分析结果并排 */}
          <div style={{ display: "flex", gap: "12px", height: "700px" }}>
            {/* 左侧：PDF预览 */}
            <div style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              backgroundColor: "var(--bg-secondary)",
              borderRadius: "8px",
              border: "1px solid var(--border)",
              overflow: "hidden",
            }}>
              <div style={{
                fontSize: "12px",
                fontWeight: "500",
                padding: "8px 12px",
                backgroundColor: "var(--bg-card)",
                borderBottom: "1px solid var(--border)",
                color: "var(--text-secondary)",
              }}>
                原文件预览
              </div>
              <iframe
                src={pdfDataUrl}
                style={{
                  flex: 1,
                  border: "none",
                  borderRadius: "0 0 8px 0",
                }}
                title="PDF Preview"
              />
            </div>

            {/* 右侧：LLM分析结果 */}
            <div style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              backgroundColor: "var(--bg-card)",
              borderRadius: "8px",
              border: "1px solid var(--border)",
              overflow: "hidden",
            }}>
              <div style={{
                fontSize: "12px",
                fontWeight: "500",
                padding: "8px 12px",
                background: "var(--tch-success-soft, rgba(92,189,138,0.12))",
                borderBottom: "1px solid var(--border)",
                color: "var(--tch-success)",
              }}>
                🤖 AI智能分析摘要
              </div>
              
              <div style={{
                flex: 1,
                overflowY: "auto",
                padding: "12px",
                fontSize: "13px",
                lineHeight: "1.6",
              }}>
                {pdfAnalysisLoading ? (
                  <div style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    justifyContent: "center",
                    height: "100%",
                    gap: "12px",
                    color: "var(--text-muted)",
                  }}>
                    <div style={{
                      width: "30px",
                      height: "30px",
                      border: "3px solid var(--border)",
                      borderTopColor: "var(--accent)",
                      borderRadius: "50%",
                      animation: "spin 0.8s linear infinite",
                    }} />
                    <span>正在使用AI分析文档内容...</span>
                  </div>
                ) : analysis?.status === "success" ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                    {/* 总结 */}
                    <div>
                      <div style={{ fontWeight: "600", color: "var(--accent)", marginBottom: "6px" }}>
                        📝 内容总结
                      </div>
                      <div style={{
                        backgroundColor: "var(--bg-secondary)",
                        padding: "10px",
                        borderRadius: "8px",
                        border: "1px solid var(--border)",
                        color: "var(--text-primary)",
                      }}>
                        {analysis?.summary || "暂无总结"}
                      </div>
                    </div>

                    {/* 关键要点 */}
                    {analysis?.key_points && analysis.key_points.length > 0 && (
                      <div>
                        <div style={{ fontWeight: "600", color: "var(--tch-danger)", marginBottom: "6px" }}>
                          ⭐ 关键要点
                        </div>
                        <ul style={{
                          margin: 0,
                          paddingLeft: "20px",
                          backgroundColor: "var(--bg-secondary)",
                          padding: "10px",
                          borderRadius: "8px",
                          border: "1px solid var(--border)",
                        }}>
                          {analysis.key_points.map((point: string, idx: number) => (
                            <li key={idx} style={{ marginBottom: idx < analysis.key_points.length - 1 ? "6px" : 0, color: "var(--text-primary)" }}>
                              {point}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* 重点关注领域 */}
                    {analysis?.focus_areas && analysis.focus_areas.length > 0 && (
                      <div>
                        <div style={{ fontWeight: "600", color: "var(--tch-warning)", marginBottom: "6px" }}>
                          🎯 重点领域
                        </div>
                        <div style={{
                          display: "flex",
                          flexWrap: "wrap",
                          gap: "6px",
                          backgroundColor: "var(--bg-secondary)",
                          padding: "10px",
                          borderRadius: "8px",
                          border: "1px solid var(--border)",
                        }}>
                          {analysis.focus_areas.map((area: string, idx: number) => (
                            <div key={idx} style={{
                              background: "var(--tch-warning-soft)",
                              padding: "4px 10px",
                              borderRadius: "8px",
                              fontSize: "12px",
                              color: "var(--tch-warning)",
                              border: "1px solid var(--border)",
                            }}>
                              {area}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* 深度见解 */}
                    {analysis?.insights && (
                      <div>
                        <div style={{ fontWeight: "600", color: "var(--accent-text)", marginBottom: "6px" }}>
                          💡 深度见解
                        </div>
                        <div style={{
                          backgroundColor: "var(--bg-secondary)",
                          padding: "10px",
                          borderRadius: "8px",
                          border: "1px solid var(--border)",
                          color: "var(--text-primary)",
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                        }}>
                          {analysis.insights}
                        </div>
                      </div>
                    )}

                    {/* 统计信息 */}
                    {pdfStats && (
                      <div style={{
                        fontSize: "11px",
                        color: "var(--text-muted)",
                        paddingTop: "8px",
                        borderTop: "1px solid var(--border)",
                      }}>
                        文档统计: 共 {pdfStats.total_pages} 页 | 已分析 {pdfStats.extracted_pages} 页 | 共 {pdfStats.total_chars} 字符
                      </div>
                    )}
                  </div>
                ) : (
                  <div style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    height: "100%",
                    color: "var(--text-muted)",
                    textAlign: "center",
                  }}>
                    <div>
                      <div style={{ fontSize: "24px", marginBottom: "8px" }}>💭</div>
                      <div>AI分析结果不可用</div>
                      <div style={{ fontSize: "12px", marginTop: "4px" }}>您仍可查看左侧的原始PDF文件</div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      );
    }
    
    // DOCX/PPT在线预览（HTML格式）
    if (onlinePreviewData?.status === "success" && onlinePreviewData?.html_content) {
      const docType = onlinePreviewData.type;
      const displayName = docType === "docx" ? "📋 Word 文档" :
                         docType === "pptx" || docType === "ppt" ? "🎜 PowerPoint演示文稿" :
                         "📄 文档";
      
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          <div style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "8px 12px",
            backgroundColor: "var(--bg-card)",
            borderRadius: "8px",
            borderBottom: "1px solid var(--border)",
          }}>
            <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
              {displayName} 
              {onlinePreviewData.slide_count ? ` - 共 ${onlinePreviewData.slide_count} 页` : ""}
              ({onlinePreviewData.file_size || 0} 字节)
            </div>
          </div>
          <div style={{
            maxHeight: "500px",
            overflowY: "auto",
            backgroundColor: "var(--bg-secondary)",
            borderRadius: "8px",
            border: "1px solid var(--border)",
            padding: "12px",
            fontSize: "14px",
            lineHeight: "1.8",
            color: "var(--text-primary)",
          }}>
            <div 
              dangerouslySetInnerHTML={{ __html: onlinePreviewData.html_content }}
              style={{
                "& h1, & h2, & h3": { marginTop: "16px", marginBottom: "8px" },
                "& p": { marginBottom: "8px" },
                "& table": { width: "100%", borderCollapse: "collapse" },
                "& td, & th": { border: "1px solid var(--border)", padding: "8px" }
              } as any}
            />
          </div>
        </div>
      );
    }
    
    // 加载中的在线预览
    if (onlinePreviewLoading) {
      return (
        <div style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          minHeight: "300px",
          backgroundColor: "var(--bg-card)",
          borderRadius: "8px",
          border: "1px solid var(--border)",
          textAlign: "center",
        }}>
          <div style={{ fontSize: "24px", marginBottom: "12px", animation: "spin 1s linear infinite" }}>
            ⚙️
          </div>
          <div style={{ fontSize: "14px", color: "var(--text-secondary)" }}>正在加载文件预览...</div>
        </div>
      );
    }
    
    // 在线预览失败，回退到文本预览
    if (onlinePreviewData?.status === "text_fallback" || onlinePreviewData?.status === "error") {
      if (onlinePreviewData?.raw_text && onlinePreviewData.raw_text.trim()) {
        return (
          <div>
            <div style={{ fontSize: "12px", color: "var(--tch-warning)", marginBottom: "8px", padding: "8px", background: "var(--bg-card)", borderRadius: "8px" }}>
              💡 原始文件不可用，显示的是提取的文本内容预览
            </div>
            <div style={{
              maxHeight: "450px",
              overflowY: "auto",
              backgroundColor: "var(--bg-secondary)",
              padding: "12px",
              borderRadius: "8px",
              border: "1px solid var(--border)",
              fontSize: "13px",
              lineHeight: "1.6",
              color: "var(--text-primary)",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}>
              {extractValidContent(onlinePreviewData.raw_text)}
            </div>
          </div>
        );
      }
    }
    
    // 其他格式或没有预览数据时的显示
    if (fileInfo.canPreview && editedContent && editedContent.trim()) {
      // 支持预览的文本格式
      return (
        <div style={{
          maxHeight: "400px",
          overflowY: "auto",
          backgroundColor: "var(--bg-secondary)",
          padding: "12px",
          borderRadius: "8px",
          border: "1px solid var(--border)",
          fontSize: "13px",
          lineHeight: "1.6",
          color: "var(--text-primary)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}>
          {extractValidContent(editedContent)}
        </div>
      );
    }
    
    // 无法预览的文件格式
    return (
      <div style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "300px",
        backgroundColor: "var(--bg-card)",
        borderRadius: "8px",
        border: "2px dashed var(--border)",
        padding: "20px",
        textAlign: "center",
      }}>
        <div style={{ fontSize: "48px", marginBottom: "12px" }}>{fileInfo.icon}</div>
        <div style={{ fontSize: "16px", fontWeight: "600", color: "var(--text-primary)", marginBottom: "8px" }}>
          {fileInfo.displayName}
        </div>
        <div style={{ fontSize: "13px", color: "var(--text-secondary)", marginBottom: "12px" }}>
          {selectedFile.filename}
        </div>
        <div style={{ fontSize: "12px", color: "var(--text-muted)", maxWidth: "300px", lineHeight: "1.6" }}>
          文件预览功能正在加载或暂时不可用，但已自动提取文本内容。您可以在编辑模式中查看和修改提取的文本。
        </div>
        {editedContent && (
          <div style={{
            fontSize: "12px",
            color: "var(--accent)",
            marginTop: "12px",
            padding: "8px 12px",
            background: "var(--tch-accent-soft, rgba(107,138,255,0.12))",
            borderRadius: "8px",
          }}>
            ✓ 已提取 {editedContent.length} 个字符的文本内容
          </div>
        )}
      </div>
    );
  }

  async function loadDashboard() {
    try {
      setLoadingMessage("正在加载总览数据");
      setLoading(true);
      setErrorMessage("");
      const q = categoryFilter ? `?category=${encodeURIComponent(categoryFilter)}` : "";
      const [dashData, subsData] = await Promise.all([
        api(`/api/teacher/dashboard${q}`).catch(() => null),
        api("/api/teacher/submissions?limit=50").catch(() => ({ submissions: [] })),
      ]);
      if (dashData && !dashData.error) {
        setDashboard(dashData.data);
      }
      setOverviewSubmissions(subsData?.submissions ?? []);
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "加载总览数据失败"}`);
      setDashboard(null);
    } finally {
      setLoading(false);
    }
  }

  async function loadClassData(cid: string) {
    setLoadingMessage("正在加载团队全量数据");
    setLoading(true);
    setErrorMessage("");
    try {
      const [subsData, capData, ruleData, intervData, compData] = await Promise.all([
        api(`/api/teacher/submissions?class_id=${encodeURIComponent(cid)}&limit=300`).catch(() => ({ submissions: [] })),
        api(`/api/teacher/capability-map/${encodeURIComponent(cid)}`).catch(() => null),
        api(`/api/teacher/rule-coverage/${encodeURIComponent(cid)}`).catch(() => null),
        api(`/api/teacher/teaching-interventions/${encodeURIComponent(cid)}`).catch(() => null),
        api(`/api/teacher/compare?class_id=${encodeURIComponent(cid)}`).catch(() => null),
      ]);
      setClassSubmissions(subsData?.submissions ?? []);
      if (capData) setCapabilityMap(capData);
      if (ruleData) setRuleCoverage(ruleData);
      if (intervData) setTeachingInterventions(intervData);
      if (compData) setCompareData(compData);
      setClassView("overview");
      setSelectedClassStudent("");
      setSelectedClassStudentProject("");
    } catch {
      setErrorMessage("加载团队数据失败");
    } finally {
      setLoading(false);
    }
  }

  async function loadTeams() {
    setLoadingMessage("正在加载团队数据");
    setLoading(true);
    setErrorMessage("");
    try {
      const tid = currentUser?.user_id || "";
      const data = await api(`/api/teacher/teams?teacher_id=${encodeURIComponent(tid)}`);
      if (!data || !Array.isArray(data.my_teams) || !Array.isArray(data.other_teams)) {
        throw new Error("团队数据格式异常");
      }
      setTeamData(data);
      setTeamView("comparison");
      setSelectedTeamId("");
      setSelectedTeamStudentId("");
      setSelectedTeamProjectId("");
    } catch (err: any) {
      setErrorMessage(err?.message ?? "加载团队数据失败");
      setTeamData(null);
    } finally {
      setLoading(false);
    }
  }

  async function handleCreateTeam() {
    if (!newTeamName.trim()) return;
    try {
      const res = await api("/api/teams", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          teacher_id: currentUser?.user_id || "",
          teacher_name: currentUser?.display_name || "",
          team_name: newTeamName.trim(),
        }),
      });
      setCreatedInviteCode(res.team?.invite_code || "");
      setNewTeamName("");
      loadTeams();
    } catch (err: any) {
      setErrorMessage(err?.message ?? "创建团队失败");
    }
  }

  async function handleDeleteTeam(teamId: string) {
    try {
      await api(`/api/teams/${teamId}?teacher_id=${encodeURIComponent(currentUser?.user_id || "")}`, { method: "DELETE" });
      loadTeams();
    } catch (err: any) {
      setErrorMessage(err?.message ?? "删除团队失败");
    }
  }

  async function handleRemoveMember(teamId: string, userId: string) {
    try {
      await api(`/api/teams/${teamId}/members/${userId}?teacher_id=${encodeURIComponent(currentUser?.user_id || "")}`, { method: "DELETE" });
      loadTeams();
    } catch (err: any) {
      setErrorMessage(err?.message ?? "移除成员失败");
    }
  }

  async function loadSubmissions() {
    setLoadingMessage("正在加载学生提交记录");
    setLoading(true);
    const params = new URLSearchParams();
    if (classId.trim()) params.set("class_id", classId.trim());
    if (cohortId.trim()) params.set("cohort_id", cohortId.trim());
    const q = params.toString();
    const data = await api(`/api/teacher/submissions${q ? `?${q}` : ""}`);
    setSubmissions(data.submissions ?? []);
    setLoading(false);
  }

  async function loadCompare() {
    setLoadingMessage("正在对比基线数据");
    setLoading(true);
    const params = new URLSearchParams();
    if (classId.trim()) params.set("class_id", classId.trim());
    if (cohortId.trim()) params.set("cohort_id", cohortId.trim());
    const q = params.toString();
    const data = await api(`/api/teacher/compare${q ? `?${q}` : ""}`);
    setCompareData(data);
    setLoading(false);
  }

  async function loadEvidence(pid: string) {
    setLoadingMessage("正在加载证据链数据");
    setLoading(true);
    setSelectedProject(pid);
    const data = await api(`/api/teacher/project/${encodeURIComponent(pid)}/evidence`);
    setEvidence(data.data);
    setTab("evidence");
    setLoading(false);
  }

  async function generateReport() {
    setLoadingMessage("正在生成AI班级报告");
    setLoading(true);
    const params = new URLSearchParams();
    if (classId.trim()) params.set("class_id", classId.trim());
    if (cohortId.trim()) params.set("cohort_id", cohortId.trim());
    const q = params.toString();
    const data = await api(`/api/teacher/generate-report${q ? `?${q}` : ""}`, { method: "POST" });
    setReport(data.report ?? "");
    setReportSnapshot(data.snapshot ?? null);
    setTab("report");
    setLoading(false);
  }

  async function loadCapabilityMap() {
    setLoadingMessage("正在加载能力映射");
    setLoading(true);
    const data = await api(`/api/teacher/capability-map/${encodeURIComponent(classId.trim() || "default")}`);
    setCapabilityMap(data);
    setTab("capability");
    setLoading(false);
  }

  async function loadRuleCoverage() {
    setLoadingMessage("正在分析规则覆盖率");
    setLoading(true);
    const data = await api(`/api/teacher/rule-coverage/${encodeURIComponent(classId.trim() || "default")}`);
    setRuleCoverage(data);
    setTab("rule-coverage");
    setLoading(false);
  }

  async function loadConversationAnalytics() {
    setLoadingMessage("正在分析对话质量");
    setLoading(true);
    setErrorMessage("");
    try {
      const params = new URLSearchParams();
      if (classId.trim()) params.set("class_id", classId.trim());
      if (cohortId.trim()) params.set("cohort_id", cohortId.trim());
      const q = params.toString();
      const data = await api(`/api/teacher/conversation-analytics${q ? `?${q}` : ""}`);
      setConversationAnalytics(data);
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "加载对话质量分析失败"}`);
      setConversationAnalytics(null);
    } finally {
      setLoading(false);
    }
  }

  async function loadProjectDiagnosis() {
    setLoadingMessage("正在进行项目诊断");
    setLoading(true);
    if (!selectedProject) {
      setLoading(false);
      return;
    }
    const data = await api(`/api/teacher/project/${encodeURIComponent(selectedProject)}/deep-diagnosis`);
    setProjectDiagnosis(data);
    setTab("rubric");
    setLoading(false);
  }

  async function loadRubricAssessment() {
    setLoadingMessage("正在计算Rubric评分");
    setLoading(true);
    if (!selectedProject) {
      setLoading(false);
      return;
    }
    const data = await api(`/api/teacher/project/${encodeURIComponent(selectedProject)}/rubric-assessment`);
    setRubricAssessment(data);
    setTab("rubric");
    setLoading(false);
  }

  async function loadCompetitionScore() {
    setLoadingMessage("正在预测竞赛评分");
    setLoading(true);
    if (!selectedProject) {
      setLoading(false);
      return;
    }
    const data = await api(`/api/teacher/project/${encodeURIComponent(selectedProject)}/competition-score`);
    setCompetitionScore(data);
    setTab("competition");
    setLoading(false);
  }

  async function loadProjectWorkbench(targetProjectId?: string, logicalProjectId = "") {
    const pid = (targetProjectId || projectTabInput || selectedProject || projectId).trim();
    if (!pid) {
      setErrorMessage("请先输入项目 ID");
      return;
    }
    try {
      setLoadingMessage("正在加载项目工作台");
      setLoading(true);
      setErrorMessage("");
      setSelectedProject(pid);
      setProjectTabInput(pid);
      setProjectCaseBenchmark(null);
      const summaryData = await api(`/api/teacher/project/${encodeURIComponent(pid)}/workbench-summary`).catch(() => ({ logical_projects: [] }));
      setProjectWorkbenchSummary(summaryData);
      const resolvedLogicalProjectId = (
        logicalProjectId
        || summaryData?.logical_projects?.[0]?.logical_project_id
        || ""
      ).trim();
      setSelectedLogicalProjectId(resolvedLogicalProjectId);
      const q = resolvedLogicalProjectId ? `?logical_project_id=${encodeURIComponent(resolvedLogicalProjectId)}` : "";
      const [assessmentData, diagnosisData, competitionData, evidenceData, evidenceTraceData, ruleDashboardData, feedbackData] = await Promise.all([
        api(`/api/teacher/assistant/project/${encodeURIComponent(pid)}/assessment${q}`).catch(() => null),
        api(`/api/teacher/project/${encodeURIComponent(pid)}/deep-diagnosis`).catch(() => null),
        api(`/api/teacher/project/${encodeURIComponent(pid)}/competition-score`).catch(() => null),
        api(`/api/teacher/project/${encodeURIComponent(pid)}/evidence`).catch(() => null),
        api(`/api/teacher/project/${encodeURIComponent(pid)}/evidence-trace${q}`).catch(() => null),
        api(`/api/teacher/project/${encodeURIComponent(pid)}/rule-dashboard${q}`).catch(() => null),
        api(`/api/project/${encodeURIComponent(pid)}/feedback`).catch(() => ({ feedback: [] })),
      ]);
      setAssistantAssessment(assessmentData);
      if (assessmentData && !assessmentData?.error) {
        setAssistantReviewDraft({
          title: assessmentData?.existing_review?.title || `${assessmentData?.project_name || "项目"} 批改意见`,
          summary: assessmentData?.existing_review?.summary || assessmentData?.summary || "",
          strengths: assessmentData?.existing_review?.strengths || assessmentData?.diagnosis?.strengths || [],
          weaknesses: assessmentData?.existing_review?.weaknesses || assessmentData?.diagnosis?.weaknesses || [],
          action_items: assessmentData?.existing_review?.action_items || assessmentData?.revision_suggestions || assessmentData?.next_task?.acceptance_criteria || [],
          focus_tags: assessmentData?.existing_review?.focus_tags || (assessmentData?.evidence_chain || []).slice(0, 3).map((x: any) => x.risk_id || x.risk_name).filter(Boolean),
          score_band: assessmentData?.existing_review?.score_band || assessmentData?.score_band || "",
        });
      }
      setProjectDiagnosis(diagnosisData);
      setCompetitionScore(competitionData);
      setProjectEvidenceTrace(evidenceTraceData);
      setProjectRuleDashboard(ruleDashboardData);
      setEvidence(evidenceData?.data || evidenceData || null);
      setProjectFeedbackHistory(
        (feedbackData?.feedback || []).filter((item: any) => {
          if (!resolvedLogicalProjectId) return true;
          if (!item?.logical_project_id) return true;
          return item.logical_project_id === resolvedLogicalProjectId;
        })
      );
      setProjectIdConfirmed(true);
      setProjectWorkspaceView("detail");
      setTab("project");
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "加载项目工作台失败"}`);
    } finally {
      setLoading(false);
    }
  }

  async function loadProjectCaseBenchmark(targetProjectId?: string, logicalProjectId = "") {
    const pid = (targetProjectId || selectedProject || projectId).trim();
    if (!pid) {
      setErrorMessage("请先输入或选择项目 ID");
      return;
    }
    try {
      setLoadingMessage("正在汇总案例对标");
      setLoading(true);
      setErrorMessage("");
      const resolvedLogicalId = (logicalProjectId || selectedLogicalProjectId || "").trim();
      const q = resolvedLogicalId ? `?logical_project_id=${encodeURIComponent(resolvedLogicalId)}` : "";
      const data = await api(`/api/teacher/project/${encodeURIComponent(pid)}/case-benchmark${q}`);
      setProjectCaseBenchmark(data);
      setProjectWorkspaceView("detail");
      setTab("project");
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "加载案例对标失败"}`);
      setProjectCaseBenchmark(null);
    } finally {
      setLoading(false);
    }
  }

  async function generateProjectStructuredReport(scopeRows: any[], category: string) {
    if (!scopeRows.length) {
      setProjectStructuredReport(null);
      return;
    }
    try {
      setProjectStructuredReportLoading(true);
      const payload = {
        category,
        rows: scopeRows.slice(0, 24).map((item: any) => ({
          project_name: item.project_name || item.logical_project_id || "未命名项目",
          category: item.category || inferProjectCategory(item),
          latest_score: Number(item.latest_score || 0),
          improvement: Number(item.improvement || 0),
          submission_count: Number(item.submission_count || 0),
          project_phase: item.project_phase || "",
          student_name: item.student_name || item.student_id || "",
          team_name: item.team_name || "",
          top_risks: item.top_risks || [],
          summary: item.summary || "",
          dominant_intent: item.dominant_intent || "综合咨询",
        })),
      };
      const data = await api("/api/teacher/project-insight-report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setProjectStructuredReport(data);
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "生成项目结构化报告失败"}`);
      setProjectStructuredReport(null);
    } finally {
      setProjectStructuredReportLoading(false);
    }
  }

  async function loadTeachingInterventions() {
    setLoadingMessage("正在分析教学干预方案");
    setLoading(true);
    const data = await api(`/api/teacher/teaching-interventions/${encodeURIComponent(classId.trim() || "default")}`);
    setTeachingInterventions(data);
    setTab("interventions");
    setLoading(false);
  }

  async function loadAssistantDashboard() {
    try {
      setLoadingMessage("正在加载教学助理工作台");
      setLoading(true);
      setErrorMessage("");
      const tid = currentUser?.user_id || teacherId;
      const data = await api(`/api/teacher/assistant/dashboard?teacher_id=${encodeURIComponent(tid)}`);
      setAssistantDashboard(data);
      markAssistantUpdated();
      setAssistantView("queue");
      setTab("assistant");
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "加载教学助理失败"}`);
      setAssistantDashboard(null);
    } finally {
      setLoading(false);
    }
  }

  async function loadAssistantAssessment(targetProjectId: string, logicalProjectId = "") {
    try {
      setLoadingMessage("正在加载批改与溯源");
      setLoading(true);
      setErrorMessage("");
      const q = logicalProjectId ? `?logical_project_id=${encodeURIComponent(logicalProjectId)}` : "";
      const [data, summaryData] = await Promise.all([
        api(`/api/teacher/assistant/project/${encodeURIComponent(targetProjectId)}/assessment${q}`),
        api(`/api/teacher/project/${encodeURIComponent(targetProjectId)}/workbench-summary`).catch(() => null),
      ]);
      setAssistantAssessment(data);
      if (summaryData) setProjectWorkbenchSummary(summaryData);
      setAssistantReviewDraft({
        title: data?.existing_review?.title || `${data?.project_name || "项目"} 批改意见`,
        summary: data?.existing_review?.summary || data?.summary || "",
        strengths: data?.existing_review?.strengths || data?.diagnosis?.strengths || [],
        weaknesses: data?.existing_review?.weaknesses || data?.diagnosis?.weaknesses || [],
        action_items: data?.existing_review?.action_items || data?.next_task?.acceptance_criteria || [],
        focus_tags: data?.existing_review?.focus_tags || (data?.evidence_chain || []).slice(0, 3).map((x: any) => x.risk_id || x.risk_name).filter(Boolean),
        score_band: data?.existing_review?.score_band || data?.score_band || "",
      });
      setAssistantView("assessment");
      setTab("assistant");
      setSelectedProject(targetProjectId);
      setSelectedLogicalProjectId(logicalProjectId);
      markAssistantUpdated();
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "加载评估报告失败"}`);
      setAssistantAssessment(null);
    } finally {
      setLoading(false);
    }
  }

  async function loadAssistantInterventions(targetTeamId?: string) {
    try {
      setLoadingMessage("正在加载教学干预中心");
      setLoading(true);
      setErrorMessage("");
      const tid = currentUser?.user_id || teacherId;
      let resolvedTeamId = targetTeamId || assistantSelectedTeamId;
      if (!resolvedTeamId) {
        const teamResp = teamData || await api(`/api/teacher/teams?teacher_id=${encodeURIComponent(tid)}`);
        const firstMine = (teamResp?.my_teams || [])[0];
        resolvedTeamId = firstMine?.team_id || "";
      }
      if (!resolvedTeamId) {
        throw new Error("请先创建团队或让学生加入团队后再使用教学干预中心");
      }
      const data = await api(`/api/teacher/assistant/class/${encodeURIComponent(resolvedTeamId)}/interventions?teacher_id=${encodeURIComponent(tid)}`);
      setAssistantSelectedTeamId(resolvedTeamId);
      setAssistantInterventionData(data);
      const firstPlan = (data?.suggested_plans || [])[0] || {};
      setAssistantDraftIntervention({
        scope_type: "team",
        scope_id: resolvedTeamId,
        source_type: "class_plan",
        target_student_id: "",
        project_id: "",
        logical_project_id: "",
        title: firstPlan.title || "下周教学干预任务",
        reason_summary: firstPlan.reason_summary || "",
        action_items: firstPlan.action_items || [],
        acceptance_criteria: firstPlan.acceptance_criteria || [],
        priority: "high",
      });
      markAssistantUpdated();
      setAssistantView("intervention");
      setTab("assistant");
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "加载教学干预中心失败"}`);
      setAssistantInterventionData(null);
    } finally {
      setLoading(false);
    }
  }

  async function loadAssistantConversationEval(targetProjectId?: string, logicalProjectId = "") {
    const pid = (targetProjectId || assistantAssessment?.project_id || selectedProject || "").trim();
    if (!pid) {
      setErrorMessage("请先选择一个项目后再生成对话过程评估");
      return;
    }
    try {
      setLoadingMessage("正在生成对话过程评估");
      setLoading(true);
      setErrorMessage("");
      const q = logicalProjectId ? `?logical_project_id=${encodeURIComponent(logicalProjectId)}` : "";
      const [data, summaryData] = await Promise.all([
        api(`/api/teacher/assistant/project/${encodeURIComponent(pid)}/conversation-eval${q}`),
        api(`/api/teacher/project/${encodeURIComponent(pid)}/workbench-summary`).catch(() => null),
      ]);
      setAssistantConversationEval(data);
      if (summaryData) setProjectWorkbenchSummary(summaryData);
      markAssistantUpdated();
      setAssistantView("conversation");
      setTab("assistant");
      setSelectedLogicalProjectId(logicalProjectId);
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "加载对话过程评估失败"}`);
      setAssistantConversationEval(null);
    } finally {
      setLoading(false);
    }
  }

  async function loadAssistantImpact() {
    try {
      setLoadingMessage("正在汇总干预效果");
      setLoading(true);
      setErrorMessage("");
      const tid = currentUser?.user_id || teacherId;
      const data = await api(`/api/teacher/assistant/intervention-impact?teacher_id=${encodeURIComponent(tid)}`);
      setAssistantImpact(data);
      markAssistantUpdated();
      setAssistantView("impact");
      setTab("assistant");
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "加载干预效果看板失败"}`);
      setAssistantImpact(null);
    } finally {
      setLoading(false);
    }
  }

  async function handleQuickPlanToIntervention(plan: any, horizon: "24h" | "72h") {
    if (!assistantAssessment) return;
    if (!assistantInterventionData) {
      await loadAssistantInterventions();
    }
    const horizonLabel = horizon === "24h" ? "24 小时紧急修正" : "72 小时深度优化";
    setAssistantDraftIntervention((prev: any) => ({
      ...prev,
      source_type: horizon === "24h" ? "quick_plan_24h" : "quick_plan_72h",
      target_student_id: assistantAssessment.student_id || prev.target_student_id || "",
      project_id: assistantAssessment.project_id || prev.project_id || "",
      logical_project_id: assistantAssessment.logical_project_id || prev.logical_project_id || "",
      title: plan.title || `${horizonLabel}：${plan.rubric_item || assistantAssessment.project_name || ""}`,
      reason_summary: plan.description || prev.reason_summary || `基于当前 Rubric 与竞赛预测的${horizon === "24h" ? "紧急修正" : "深度优化"}建议。`,
      action_items: plan.description ? asLines(plan.description) : prev.action_items,
      acceptance_criteria: prev.acceptance_criteria && prev.acceptance_criteria.length > 0
        ? prev.acceptance_criteria
        : ["学生根据该计划完成一轮修改，并在提交后由老师复查。"],
      priority: horizon === "24h" ? "high" : (prev.priority || "medium"),
    }));
    setAssistantView("intervention");
    setTab("assistant");
  }

  async function saveAssistantIntervention(sendImmediately = false) {
    try {
      setLoading(true);
      setLoadingMessage(sendImmediately ? "正在下发教师干预任务" : "正在保存干预草稿");
      setErrorMessage("");
      const payload = {
        teacher_id: currentUser?.user_id || teacherId,
        scope_type: assistantDraftIntervention.scope_type,
        scope_id: assistantDraftIntervention.scope_id,
        source_type: assistantDraftIntervention.source_type,
        target_student_id: assistantDraftIntervention.target_student_id || "",
        project_id: assistantDraftIntervention.project_id || "",
        logical_project_id: assistantDraftIntervention.logical_project_id || "",
        title: assistantDraftIntervention.title,
        reason_summary: assistantDraftIntervention.reason_summary,
        action_items: asLines(assistantDraftIntervention.action_items),
        acceptance_criteria: asLines(assistantDraftIntervention.acceptance_criteria),
        priority: assistantDraftIntervention.priority || "medium",
        status: sendImmediately ? "approved" : "draft",
      };
      const created = await api("/api/teacher/assistant/interventions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (sendImmediately && created?.intervention_id) {
        await api(`/api/teacher/assistant/interventions/${encodeURIComponent(created.intervention_id)}/send`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ teacher_id: currentUser?.user_id || teacherId }),
        });
      }
      setSuccessMessage(sendImmediately ? "干预任务已发送到学生端" : "干预草稿已保存");
      await loadAssistantInterventions(assistantDraftIntervention.scope_id || assistantSelectedTeamId);
      const refreshed = await api(`/api/teacher/assistant/dashboard?teacher_id=${encodeURIComponent(currentUser?.user_id || teacherId)}`);
      setAssistantDashboard(refreshed);
      setAssistantView("intervention");
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "保存干预任务失败"}`);
    } finally {
      setLoading(false);
    }
  }

  async function runAssistantSmartSelect() {
    try {
      setLoading(true);
      setLoadingMessage("正在根据条件筛选适合干预的项目");
      setErrorMessage("");
      const body: any = {
        class_id: classId.trim() || undefined,
        cohort_id: cohortId.trim() || undefined,
      };
      // 简化版：根据当前草稿里的优先级和 scope 推导一个默认筛选条件
      if ((assistantDraftIntervention.priority || "medium") === "high") {
        body.min_risk_count = 2;
        body.max_overall_score = 7;
      }
      const res = await api("/api/teacher/assistant/smart-select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setAssistantSmartSelectResult(res);
      const items: any[] = res.items || [];
      if (items.length > 0) {
        const scopeIds = Array.from(new Set(items.map((it) => it.project_id)));
        // 将筛选结果映射到按项目的批量干预草稿（scope_type=project）
        setAssistantDraftIntervention((prev: any) => ({
          ...prev,
          scope_type: "project",
          scope_id: scopeIds[0] || prev.scope_id,
          project_id: scopeIds[0] || prev.project_id,
          target_student_id: "",
        }));
      }
      setAssistantView("intervention");
      setTab("assistant");
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "智能筛选失败"}`);
      setAssistantSmartSelectResult(null);
    } finally {
      setLoading(false);
    }
  }

  async function submitFeedback(e: FormEvent) {
    e.preventDefault();
    if (!feedbackText.trim() || feedbackText.trim().length < 5) {
      setErrorMessage("反馈内容至少需要5个字符");
      return;
    }
    
    try {
      setErrorMessage("");
      const targetPid = (selectedProject || projectId || "").trim();
      if (!targetPid) {
        setErrorMessage("请先选择一个项目后再提交反馈");
        return;
      }
      const data = await api("/api/teacher-feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: targetPid,
          teacher_id: teacherId,
          comment: feedbackText.trim(),
          focus_tags: feedbackTags.split(",").map((t) => t.trim()).filter(Boolean),
        }),
      });
      setSuccessMessage(`反馈已保存 (ID: ${data.feedback_id ?? "?"})`);
      setFeedbackText("");
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "提交反馈失败"}`);
    }
  }

  // 文件级反馈函数
  async function loadStudentFiles(targetProjectId?: string, preferredLogicalProjectId = "") {
    try {
      setLoadingMessage("正在加载学生提交文件");
      setLoading(true);
      setErrorMessage("");
      const targetPid = (targetProjectId || selectedProject || projectId).trim();
      if (!targetPid.trim()) {
        setErrorMessage("请先输入项目ID");
        setStudentFiles([]);
        return [];
      }
      const data = validateResponse(await api(`/api/teacher/student-files/${encodeURIComponent(targetPid)}`), "加载文件列表失败");
      const files = data.files || [];
      setStudentFiles(files);
      if (!files.length) {
        if (!preferredLogicalProjectId) setSelectedLogicalProjectId("");
        setSelectedFile(null);
        setFileContent("");
        setEditedContent("");
        return [];
      }
      const existingSelectedSubmissionId = selectedFile?.submission_id;
      const existingLogicalProjectId = preferredLogicalProjectId || selectedLogicalProjectId;
      const resolvedLogicalProjectId = existingLogicalProjectId && files.some((file: any) => file.logical_project_id === existingLogicalProjectId)
        ? existingLogicalProjectId
        : (files[0]?.logical_project_id || "");
      setSelectedLogicalProjectId(resolvedLogicalProjectId);
      const hasSelectedFile = existingSelectedSubmissionId && files.some((file: any) => file.submission_id === existingSelectedSubmissionId);
      if (!hasSelectedFile) {
        setSelectedFile(null);
        setFileContent("");
        setEditedContent("");
      }
      return files;
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "加载文件列表失败"}`);
      setStudentFiles([]);
      return [];
    } finally {
      setLoading(false);
    }
  }

  async function loadFeedbackWorkspace(targetProjectId?: string, preferredLogicalProjectId = "", preferredSubmissionId = "") {
    try {
      setLoadingMessage("正在加载材料反馈工作台");
      setLoading(true);
      setErrorMessage("");
      const targetPid = (targetProjectId || selectedProject || projectId).trim();
      if (!targetPid) {
        setErrorMessage("请先选择一个项目");
        setStudentFiles([]);
        setProjectSubmissionHistory([]);
        return;
      }
      setSelectedProject(targetPid);
      const [fileResp, submissionResp] = await Promise.all([
        api(`/api/teacher/student-files/${encodeURIComponent(targetPid)}`).catch(() => ({ files: [] })),
        api(`/api/project/${encodeURIComponent(targetPid)}/submissions`).catch(() => ({ submissions: [] })),
      ]);
      const files = validateResponse(fileResp, "加载文件列表失败").files || [];
      const history = validateResponse(submissionResp, "加载项目提交历史失败").submissions || [];
      setStudentFiles(files);
      setProjectSubmissionHistory(history);
      const resolvedLogicalProjectId = (
        preferredLogicalProjectId
        || selectedLogicalProjectId
        || files[0]?.logical_project_id
        || history[0]?.logical_project_id
        || ""
      ).trim();
      const scopedHistory = history.filter((item: any) => !resolvedLogicalProjectId || item.logical_project_id === resolvedLogicalProjectId);
      const resolvedHistorySubmissionId = (
        preferredSubmissionId && scopedHistory.some((item: any) => item.submission_id === preferredSubmissionId)
          ? preferredSubmissionId
          : scopedHistory[0]?.submission_id
      ) || "";
      setSelectedLogicalProjectId(resolvedLogicalProjectId);
      setSelectedHistorySubmissionId(resolvedHistorySubmissionId);
      setFeedbackTimelinePage(1);
      setTab("feedback");
      const nextFile =
        (preferredSubmissionId && files.find((item: any) => item.submission_id === preferredSubmissionId))
        || files.find((item: any) => !resolvedLogicalProjectId || item.logical_project_id === resolvedLogicalProjectId)
        || null;
      if (nextFile) {
        await loadFileContent(nextFile.submission_id, targetPid);
      } else {
        setSelectedFile(null);
        setFileContent("");
        setEditedContent("");
        setFeedbackAnnotations([]);
        setFeedbackFiles([]);
        setDocumentEdits([]);
        setAnnotationAnchorText("");
        setAnnotationAnchorPosition(0);
        setFeedbackAiSuggestions([]);
      }
      setFeedbackActionView("write");
      if (preferredSubmissionId) setFeedbackWorkspaceView("reader");
      else if (preferredLogicalProjectId || targetProjectId) setFeedbackWorkspaceView("timeline");
      else setFeedbackWorkspaceView("queue");
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "加载材料反馈工作台失败"}`);
      setStudentFiles([]);
      setProjectSubmissionHistory([]);
    } finally {
      setLoading(false);
    }
  }

  async function loadFeedbackAiSuggestions(rawText: string, context = "") {
    const sections = buildReviewSectionsFromText(rawText);
    if (!sections.length) {
      setFeedbackAiSuggestions([]);
      return;
    }
    try {
      setFeedbackAiLoading(true);
      setFeedbackAiSuggestions([]);
      const data = await api("/api/document-review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sections: sections.map((item) => ({ id: item.id, text: item.text })),
          mode: "coursework",
          context,
        }),
      });
      const suggestions = ((data?.annotations || []) as any[])
        .map((item: any, idx: number) => {
          const section = sections.find((sectionItem) => sectionItem.id === Number(item?.section_id));
          if (!section) return null;
          const anchorQuote = String(item?.anchor_quote || "").trim();
          const quote = anchorQuote && section.text.includes(anchorQuote)
            ? anchorQuote
            : section.text.slice(0, Math.min(section.text.length, 160));
          const position = anchorQuote
            ? section.position + Math.max(0, section.text.indexOf(anchorQuote))
            : section.position;
          return {
            annotation_id: `ai-${section.id}-${idx}`,
            annotation_type: normalizeAiAnnotationType(String(item?.type || "")),
            content: item?.comment || "",
            quote,
            position,
            length: quote.length,
            source: "ai",
          };
        })
        .filter(Boolean);
      setFeedbackAiSuggestions(suggestions);
    } catch {
      setFeedbackAiSuggestions([]);
    } finally {
      setFeedbackAiLoading(false);
    }
  }

  async function openFeedbackSubmission(submission: any, targetProjectId?: string) {
    if (!submission?.submission_id) return;
    setFeedbackWorkspaceView("reader");
    const targetPid = (targetProjectId || selectedProject || projectId).trim();
    const fileCandidate = (studentFiles || []).find((item: any) => item.submission_id === submission.submission_id);
    if (fileCandidate) {
      await loadFileContent(submission.submission_id, targetPid);
      return;
    }
    try {
      setErrorMessage("");
      const [annotationsData, feedbackFilesData, editsData] = await Promise.all([
        api(`/api/teacher/feedback-annotations/${encodeURIComponent(targetPid)}/${encodeURIComponent(submission.submission_id)}`),
        api(`/api/teacher/feedback-files/${encodeURIComponent(targetPid)}/${encodeURIComponent(submission.submission_id)}`),
        api(`/api/teacher/document-edits/${encodeURIComponent(targetPid)}/${encodeURIComponent(submission.submission_id)}`),
      ]);
      const virtualFile = {
        submission_id: submission.submission_id,
        logical_project_id: submission.logical_project_id || selectedLogicalProjectId || "",
        project_display_name: submission.project_display_name || "当前项目",
        project_order: submission.project_order || 0,
        material_order: submission.submission_order || 0,
        material_display_name: serialLabel("提交", submission.submission_order || 0),
        filename: submission.filename || `${submission.source_type || "text"} 提交`,
        student_id: selectedFile?.student_id || "",
        created_at: submission.created_at || "",
        project_phase: submission.project_phase || "",
        raw_text: submission.full_text || submission.text_preview || "",
        diagnosis: { bottleneck: submission.bottleneck || "" },
        next_task: { title: submission.next_task || "" },
        evidence_quotes: [],
        download_url: "",
      };
      setSelectedHistorySubmissionId(submission.submission_id);
      setSelectedFile(virtualFile);
      setFileContent(virtualFile.raw_text || "");
      setEditedContent(virtualFile.raw_text || "");
      setOnlinePreviewData(null);
      setPdfAnalysisData(null);
      setIsEditMode(false);
      setFeedbackAnnotations(annotationsData.annotations || []);
      setFeedbackFiles(feedbackFilesData.feedback_files || []);
      setDocumentEdits(editsData.edits || []);
      setAnnotationAnchorText("");
      setAnnotationAnchorPosition(0);
      await loadFeedbackAiSuggestions(
        virtualFile.raw_text || "",
        [virtualFile?.diagnosis?.bottleneck || "", virtualFile?.next_task?.title || ""].filter(Boolean).join("\n")
      );
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "打开提交失败"}`);
    }
  }

  async function loadFileContent(submissionId: string, targetProjectId?: string) {
    try {
      const targetPid = (targetProjectId || selectedProject || projectId).trim();
      setErrorMessage("");
      const [fileData, annotationsData, feedbackFilesData, editsData] = await Promise.all([
        api(`/api/teacher/student-file/${encodeURIComponent(targetPid)}/${encodeURIComponent(submissionId)}`),
        api(`/api/teacher/feedback-annotations/${encodeURIComponent(targetPid)}/${encodeURIComponent(submissionId)}`),
        api(`/api/teacher/feedback-files/${encodeURIComponent(targetPid)}/${encodeURIComponent(submissionId)}`),
        api(`/api/teacher/document-edits/${encodeURIComponent(targetPid)}/${encodeURIComponent(submissionId)}`),
      ]);
      setSelectedHistorySubmissionId(submissionId);
      setSelectedFile(fileData);
      setFileContent(fileData.raw_text || "");
      setEditedContent(fileData.raw_text || "");
      setOnlinePreviewData(null);
      setPdfAnalysisData(null);
      setIsEditMode(false);
      setFeedbackAnnotations(annotationsData.annotations || []);
      setFeedbackFiles(feedbackFilesData.feedback_files || []);
      setDocumentEdits(editsData.edits || []);
      setAnnotationAnchorText("");
      setAnnotationAnchorPosition(0);
      await loadFeedbackAiSuggestions(
        fileData.raw_text || "",
        [fileData?.diagnosis?.bottleneck || "", fileData?.next_task?.title || ""].filter(Boolean).join("\n")
      );
    } catch (error) {
      setErrorMessage("加载文件内容失败");
      setSelectedFile(null);
      setFileContent("");
      setOnlinePreviewData(null);
      setPdfAnalysisData(null);
      setFeedbackAiSuggestions([]);
    }
  }

  async function saveAnnotation() {
    if (!annotationText.trim() || !selectedFile) {
      setErrorMessage("请输入批注内容并选择文件");
      return;
    }
    
    try {
        const targetPid = (selectedProject || projectId || "").trim();
        if (!targetPid) {
          setErrorMessage("请先选择项目后再保存批注");
          return;
        }
        setErrorMessage("");
      const payload = {
        project_id: targetPid,
        submission_id: selectedFile.submission_id,
        teacher_id: teacherId,
        annotations: [{
          type: annotationAnchorText ? "highlight" : "comment",
          position: annotationAnchorText ? annotationAnchorPosition : 0,
          length: annotationAnchorText ? annotationAnchorText.length : 0,
          quote: annotationAnchorText,
          content: annotationText.trim(),
          annotation_type: annotationType,
        }],
        overall_feedback: "",
        focus_areas: [],
      };
      
      await validateResponse(await api("/api/teacher/feedback-annotations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }), "保存批注失败");
      
      setSuccessMessage("批注已保存");
      setAnnotationText("");
      setAnnotationAnchorText("");
      setAnnotationAnchorPosition(0);
      
      // 重新加载批注列表
      if (selectedFile) {
        const annotationsData = await api(`/api/teacher/feedback-annotations/${encodeURIComponent(targetPid)}/${encodeURIComponent(selectedFile.submission_id)}`);
        setFeedbackAnnotations(annotationsData.annotations || []);
      }
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "保存批注失败"}`);
    }
  }

  async function uploadFeedbackFile() {
    if (!feedbackFileToUpload || !selectedFile) {
      setErrorMessage("请选择文件并选中学生文件");
      return;
    }
    
    try {
        setErrorMessage("");
        const targetPid = (selectedProject || projectId || "").trim();
        if (!targetPid) {
          setErrorMessage("请先选择项目后再上传反馈文件");
          return;
        }
      const formData = new FormData();
      formData.append("project_id", targetPid);
      formData.append("submission_id", selectedFile.submission_id);
      formData.append("teacher_id", teacherId);
      formData.append("feedback_comment", feedbackText || "");
      formData.append("file", feedbackFileToUpload);
      
      await api("/api/teacher/upload-feedback-file", {
        method: "POST",
        body: formData,
      });
      
      setSuccessMessage("反馈文件已上传");
      setFeedbackFileToUpload(null);
      if (feedbackFileInputRef.current) feedbackFileInputRef.current.value = "";
      
      // 重新加载反馈文件列表
      const feedbackFilesData = await api(`/api/teacher/feedback-files/${encodeURIComponent(targetPid)}/${encodeURIComponent(selectedFile.submission_id)}`);
      setFeedbackFiles(feedbackFilesData.feedback_files || []);
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "上传反馈文件失败"}`);
    }
  }

  async function loadDocumentEdits() {
    if (!selectedFile) return;
      const targetPid = (selectedProject || projectId || "").trim();
      if (!targetPid) {
        setErrorMessage("请先选择项目后再查看编辑历史");
        return;
      }
    const editsData = await api(`/api/teacher/document-edits/${encodeURIComponent(targetPid)}/${encodeURIComponent(selectedFile.submission_id)}`);
    setDocumentEdits(editsData.edits || []);
  }

  async function saveEditedDocument() {
    if (!editedContent.trim() || !selectedFile) {
      setErrorMessage("请输入编辑内容并选择文件");
      return;
    }
    
    try {
        setErrorMessage("");
        const targetPid = (selectedProject || projectId || "").trim();
        if (!targetPid) {
          setErrorMessage("请先选择项目后再保存编辑内容");
          return;
        }
      const payload = {
        project_id: targetPid,
        submission_id: selectedFile.submission_id,
        teacher_id: teacherId,
        edited_content: editedContent,
        edit_summary: editSummary || "文档编辑",
      };
      
      await api("/api/teacher/edit-document", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      
      setSuccessMessage("文档编辑已保存");
      setEditSummary("");
      setIsEditMode(false);
      
      // 重新加载编辑历史
      await loadDocumentEdits();
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "保存编辑失败"}`);
    }
  }

  async function exportDocument(format: 'txt' | 'pdf') {
    if (!editedContent.trim() || !selectedFile) {
      setErrorMessage("请先编辑文档内容");
      return;
    }
    
    try {
        setErrorMessage("");
        const targetPid = (selectedProject || projectId || "").trim();
        if (!targetPid) {
          setErrorMessage("请先选择项目后再导出文档");
          return;
        }
      const filename = `反馈_${selectedFile.student_id || 'student'}_export`;
      
      const payload = {
        project_id: targetPid,
        submission_id: selectedFile.submission_id,
        edited_content: editedContent,
        format: format,
        filename: filename,
      };
      
      const data = await api("/api/teacher/export-document", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      
      if (data.download_url) {
        const link = document.createElement('a');
        link.href = `${API}${data.download_url}`;
        link.download = `${filename}.${format}`;
        link.click();
        setSuccessMessage(`文档已导出为 ${format.toUpperCase()} 格式`);
      } else {
        setErrorMessage("导出失败：无法获取下载链接");
      }
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "导出文档失败"}`);
    }
  }

  useEffect(() => {
    const saved = localStorage.getItem("tch-theme") as "dark" | "light" | null;
    if (saved) setTheme(saved);
  }, []);

  useEffect(() => {
    localStorage.setItem("tch-theme", theme);
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    if (currentUser?.user_id) setTeacherId(currentUser.user_id);
  }, [currentUser?.user_id]);

  useEffect(() => { loadDashboard(); }, []);

  useEffect(() => {
    if (teamView !== "project-detail") return;
    let cancelled = false;
    fetch(`${API}/api/hypergraph/library?limit=16`)
      .then((r) => r.json())
      .then((data) => { if (!cancelled) setHyperLibrary(data?.data ?? null); })
      .catch(() => { if (!cancelled) setHyperLibrary(null); });
    return () => { cancelled = true; };
  }, [teamView, selectedTeamProjectId]);

  const maxCat = useMemo(() => Math.max(1, ...(dashboard?.category_distribution ?? []).map((r: any) => Number(r.projects || 0))), [dashboard]);
  const maxRule = useMemo(() => Math.max(1, ...(dashboard?.top_risk_rules ?? []).map((r: any) => Number(r.projects || 0))), [dashboard]);

  const overviewStats = useMemo(() => {
    const subs = overviewSubmissions;
    if (!subs || subs.length === 0) return null;
    const uniqueStudents = new Set(subs.map((s: any) => s.student_id).filter(Boolean)).size;
    const scores = subs.map((s: any) => Number(s.overall_score || 0)).filter((s: number) => s > 0);
    const avgScore = scores.length > 0 ? scores.reduce((a: number, b: number) => a + b, 0) / scores.length : 0;
    const scoreBuckets = [0, 0, 0, 0, 0];
    scores.forEach((s: number) => {
      if (s <= 2) scoreBuckets[0]++;
      else if (s <= 4) scoreBuckets[1]++;
      else if (s <= 6) scoreBuckets[2]++;
      else if (s <= 8) scoreBuckets[3]++;
      else scoreBuckets[4]++;
    });
    const withRules = subs.filter((s: any) => (s.triggered_rules?.length || 0) > 0).length;
    const riskRate = subs.length > 0 ? (withRules / subs.length * 100) : 0;
    const sourceTypes: Record<string, number> = {};
    subs.forEach((s: any) => { const t = s.source_type || "unknown"; sourceTypes[t] = (sourceTypes[t] || 0) + 1; });
    const recent = subs.slice(0, 8);
    const studentMap: Record<string, { count: number; totalScore: number; lastActive: string }> = {};
    subs.forEach((s: any) => {
      const sid = s.student_id || "unknown";
      if (!studentMap[sid]) studentMap[sid] = { count: 0, totalScore: 0, lastActive: "" };
      studentMap[sid].count++;
      studentMap[sid].totalScore += Number(s.overall_score || 0);
      if ((s.created_at || "") > studentMap[sid].lastActive) studentMap[sid].lastActive = s.created_at || "";
    });
    const studentSummary = Object.entries(studentMap).map(([id, data]) => ({
      id, count: data.count, avgScore: data.count > 0 ? data.totalScore / data.count : 0, lastActive: data.lastActive,
    })).sort((a, b) => b.count - a.count);

    // 活动时间线（按日期分组）
    const dateMap: Record<string, number> = {};
    subs.forEach((s: any) => { const d = (s.created_at || "").slice(0, 10); if (d) dateMap[d] = (dateMap[d] || 0) + 1; });
    const activityByDate = Object.entries(dateMap).sort(([a],[b]) => a.localeCompare(b)).map(([date, count]) => ({ label: date, value: count }));

    // 规则雷达数据
    const ruleFreq: Record<string, number> = {};
    subs.forEach((s: any) => { (s.triggered_rules || []).forEach((r: string) => { ruleFreq[r] = (ruleFreq[r] || 0) + 1; }); });
    const ruleRadar = Object.entries(ruleFreq).sort(([,a],[,b]) => (b as number) - (a as number)).slice(0, 6).map(([rule, count]) => ({ label: getRuleDisplayName(rule), value: count as number, max: Math.max(1, ...Object.values(ruleFreq) as number[]) }));

    // 分位数（箱型图）
    const sorted = [...scores].sort((a, b) => a - b);
    const pct = (arr: number[], p: number) => { if (!arr.length) return 0; const idx = (p / 100) * (arr.length - 1); const lo = Math.floor(idx); return lo === Math.ceil(idx) ? arr[lo] : arr[lo] + (arr[Math.ceil(idx)] - arr[lo]) * (idx - lo); };
    const scorePercentiles = { min: sorted[0] || 0, q1: pct(sorted, 25), median: pct(sorted, 50), q3: pct(sorted, 75), max: sorted[sorted.length - 1] || 0, avg: avgScore };

    // 学生散点数据
    const studentScatter = studentSummary.map(s => ({ id: s.id, x: s.count, y: s.avgScore }));

    return { uniqueStudents, totalSubmissions: subs.length, avgScore, scoreBuckets, riskRate, withRules, sourceTypes, recent, studentSummary, activityByDate, ruleRadar, scorePercentiles, studentScatter };
  }, [overviewSubmissions]);

  // ── 班级(团队)分析 ──
  const classAnalytics = useMemo(() => {
    const subs = classSubmissions;
    if (!subs || subs.length === 0) return null;
    const uniqueStudents = [...new Set(subs.map((s: any) => s.student_id).filter(Boolean))];
    const uniqueProjects = [...new Set(subs.map((s: any) => s.project_id).filter(Boolean))];
    const scores = subs.map((s: any) => Number(s.overall_score || 0)).filter((s: number) => s > 0);
    const avgScore = scores.length > 0 ? scores.reduce((a: number, b: number) => a + b, 0) / scores.length : 0;
    const withRules = subs.filter((s: any) => (s.triggered_rules?.length || 0) > 0).length;
    const riskRate = subs.length > 0 ? (withRules / subs.length * 100) : 0;

    const studentMap: Record<string, any[]> = {};
    subs.forEach((s: any) => { const sid = s.student_id || "unknown"; if (!studentMap[sid]) studentMap[sid] = []; studentMap[sid].push(s); });
    const students = Object.entries(studentMap).map(([id, items]) => {
      const sc = items.map((s: any) => Number(s.overall_score || 0)).filter((s: number) => s > 0);
      const sorted = [...items].sort((a: any, b: any) => (a.created_at || "").localeCompare(b.created_at || ""));
      const avg = sc.length > 0 ? sc.reduce((a: number, b: number) => a + b, 0) / sc.length : 0;
      const projects = [...new Set(items.map((s: any) => s.project_id).filter(Boolean))];
      const riskC = items.filter((s: any) => (s.triggered_rules?.length || 0) > 0).length;
      const trend = sc.length >= 4 ? (() => { const mid = Math.floor(sc.length / 2); const h1 = sc.slice(0, mid).reduce((a: number, b: number) => a + b, 0) / mid; const h2 = sc.slice(mid).reduce((a: number, b: number) => a + b, 0) / (sc.length - mid); return h2 - h1; })() : 0;
      const latest = sorted.length > 0 ? Number(sorted[sorted.length - 1].overall_score || 0) : 0;
      const fileCount = items.filter((s: any) => s.source_type === "file" || s.source_type === "file_in_chat").length;
      return { id, count: items.length, avgScore: avg, latestScore: latest, projects, projectCount: projects.length, riskCount: riskC, trend, lastActive: sorted[sorted.length - 1]?.created_at || "", fileCount, submissions: sorted };
    }).sort((a, b) => b.avgScore - a.avgScore);

    const dateMap: Record<string, number> = {};
    subs.forEach((s: any) => { const d = (s.created_at || "").slice(0, 10); if (d) dateMap[d] = (dateMap[d] || 0) + 1; });
    const activityByDate = Object.entries(dateMap).sort(([a], [b]) => a.localeCompare(b)).map(([date, count]) => ({ label: date, value: count }));

    const scoreBuckets = [0, 0, 0, 0, 0];
    scores.forEach((s: number) => { if (s <= 2) scoreBuckets[0]++; else if (s <= 4) scoreBuckets[1]++; else if (s <= 6) scoreBuckets[2]++; else if (s <= 8) scoreBuckets[3]++; else scoreBuckets[4]++; });
    const sorted = [...scores].sort((a, b) => a - b);
    const pctFn = (arr: number[], p: number) => { if (!arr.length) return 0; const idx = (p / 100) * (arr.length - 1); const lo = Math.floor(idx); return lo === Math.ceil(idx) ? arr[lo] : arr[lo] + (arr[Math.ceil(idx)] - arr[lo]) * (idx - lo); };
    const scorePercentiles = { min: sorted[0] || 0, q1: pctFn(sorted, 25), median: pctFn(sorted, 50), q3: pctFn(sorted, 75), max: sorted[sorted.length - 1] || 0, avg: avgScore };

    const ruleFreq: Record<string, number> = {};
    subs.forEach((s: any) => { (s.triggered_rules || []).forEach((r: string) => { ruleFreq[r] = (ruleFreq[r] || 0) + 1; }); });
    const ruleRadar = Object.entries(ruleFreq).sort(([, a], [, b]) => (b as number) - (a as number)).slice(0, 6).map(([rule, count]) => ({ label: getRuleDisplayName(rule), value: count as number, max: Math.max(1, ...Object.values(ruleFreq) as number[]) }));

    return { totalSubmissions: subs.length, studentCount: uniqueStudents.length, projectCount: uniqueProjects.length, avgScore, riskRate, withRules, students, activityByDate, scoreBuckets, scorePercentiles, ruleRadar, studentScatter: students.map(s => ({ id: s.id, x: s.count, y: s.avgScore })) };
  }, [classSubmissions]);

  // ── 单个学生的项目分析 ──
  const studentProjectAnalytics = useMemo(() => {
    if (!selectedClassStudent || !classSubmissions.length) return null;
    const subs = classSubmissions.filter((s: any) => s.student_id === selectedClassStudent);
    if (subs.length === 0) return null;
    const projectMap: Record<string, any[]> = {};
    subs.forEach((s: any) => { const pid = s.project_id || "unknown"; if (!projectMap[pid]) projectMap[pid] = []; projectMap[pid].push(s); });
    const projects = Object.entries(projectMap).map(([pid, items]) => {
      const sorted = [...items].sort((a: any, b: any) => (a.created_at || "").localeCompare(b.created_at || ""));
      const sc = sorted.map((s: any) => Number(s.overall_score || 0)).filter((v: number) => v > 0);
      return {
        id: pid, submissions: sorted, submissionCount: sorted.length,
        scoreTimeline: sorted.map((s: any) => ({ label: formatBJTime(s.created_at), value: Number(s.overall_score || 0) })),
        avgScore: sc.length > 0 ? sc.reduce((a: number, b: number) => a + b, 0) / sc.length : 0,
        latestScore: sc.length > 0 ? sc[sc.length - 1] : 0,
        firstScore: sc.length > 0 ? sc[0] : 0,
        improvement: sc.length >= 2 ? sc[sc.length - 1] - sc[0] : 0,
        fileSubmissions: sorted.filter((s: any) => s.filename),
        lastActive: sorted[sorted.length - 1]?.created_at || "",
      };
    }).sort((a, b) => b.submissionCount - a.submissionCount);
    const allScores = subs.map((s: any) => Number(s.overall_score || 0)).filter((v: number) => v > 0);
    return { studentId: selectedClassStudent, totalSubmissions: subs.length, projectCount: projects.length, projects, avgScore: allScores.length > 0 ? allScores.reduce((a: number, b: number) => a + b, 0) / allScores.length : 0 };
  }, [selectedClassStudent, classSubmissions]);

  const TABS: { id: Tab; label: string }[] = [
    { id: "overview", label: "总览" },
    { id: "assistant", label: "教学助理" },
    { id: "conversation-analytics", label: "对话质量" },
    { id: "class", label: "团队" },
    { id: "project", label: "项目" },
    { id: "submissions", label: "学生提交" },
    { id: "feedback", label: "材料反馈" },
  ];

  const teacherProjectCatalog = useMemo(() => {
    const teams = [
      ...((teamData?.my_teams || []) as any[]),
      ...((teamData?.other_teams || []) as any[]),
    ];
    const rows: any[] = [];
    teams.forEach((team: any) => {
      (team.students || []).forEach((stu: any) => {
        (stu.projects || []).forEach((proj: any) => {
          rows.push({
            root_project_id: `project-${stu.student_id}`,
            logical_project_id: proj.project_id,
            project_name: proj.project_name,
            student_id: stu.student_id,
            student_name: stu.display_name || stu.student_id,
            team_id: team.team_id,
            team_name: team.team_name,
            is_mine: !!team.is_mine,
            latest_score: Number(proj.latest_score || 0),
            avg_score: Number(proj.avg_score || 0),
            improvement: Number(proj.improvement || 0),
            submission_count: Number(proj.submission_count || 0),
            project_phase: proj.project_phase || "持续迭代",
            top_risks: proj.top_risks || [],
            summary: proj.current_summary || "暂无项目摘要",
            dominant_intent: dominantIntent(proj.intent_distribution),
          });
        });
      });
    });
    rows.sort((a, b) => {
      if (a.is_mine !== b.is_mine) return a.is_mine ? -1 : 1;
      if ((b.submission_count || 0) !== (a.submission_count || 0)) return (b.submission_count || 0) - (a.submission_count || 0);
      return (b.latest_score || 0) - (a.latest_score || 0);
    });
    return rows.map((item, idx) => {
      const category = inferProjectCategory(item);
      return {
        ...item,
        catalog_order: idx + 1,
        project_key: buildProjectCompareKey(item),
        category,
        risk_priority: feedbackUrgencyScore(item),
      };
    });
  }, [teamData]);

  useEffect(() => {
    if (projectId && projectId.trim()) return;

    const subs = overviewSubmissions || [];
    const preferred = subs.find((s: any) => String(s.project_id || "").startsWith("project-"));
    const fallback = subs[0];
    const nextPid = String((preferred?.project_id || fallback?.project_id || "")).trim();

    if (nextPid) {
      setProjectId(nextPid);
      return;
    }

    if (teacherProjectCatalog.length > 0) {
      const firstRoot = String(teacherProjectCatalog[0]?.root_project_id || "").trim();
      if (firstRoot) setProjectId(firstRoot);
    }
  }, [projectId, overviewSubmissions, teacherProjectCatalog]);

  const projectBoardCategories = useMemo(() => {
    const groups = new Map<string, any>();
    teacherProjectCatalog.forEach((item: any) => {
      const prev = groups.get(item.category) || {
        category: item.category,
        count: 0,
        avgScore: 0,
        riskCount: 0,
        improvement: 0,
        submissionCount: 0,
        items: [],
      };
      prev.count += 1;
      prev.avgScore += Number(item.latest_score || 0);
      prev.riskCount += (item.top_risks || []).length;
      prev.improvement += Number(item.improvement || 0);
      prev.submissionCount += Number(item.submission_count || 0);
      prev.items.push(item);
      groups.set(item.category, prev);
    });
    const summary = Array.from(groups.values()).map((entry: any) => ({
      ...entry,
      avgScore: entry.count ? entry.avgScore / entry.count : 0,
      avgImprovement: entry.count ? entry.improvement / entry.count : 0,
      avgRiskCount: entry.count ? entry.riskCount / entry.count : 0,
      avgSubmissionCount: entry.count ? entry.submissionCount / entry.count : 0,
      accent: categoryAccent(entry.category),
    })).sort((a: any, b: any) => b.count - a.count);
    return [{ category: "全部项目", count: teacherProjectCatalog.length, accent: "var(--accent)", items: teacherProjectCatalog }, ...summary];
  }, [teacherProjectCatalog]);

  const filteredProjectCatalog = useMemo(() => {
    const rows = teacherProjectCatalog.filter((item: any) => projectBoardCategory === "全部项目" || item.category === projectBoardCategory);
    rows.sort((a: any, b: any) => {
      if (projectBoardSort === "score") return Number(b.latest_score || 0) - Number(a.latest_score || 0);
      if (projectBoardSort === "improvement") return Number(b.improvement || 0) - Number(a.improvement || 0);
      if (projectBoardSort === "submissions") return Number(b.submission_count || 0) - Number(a.submission_count || 0);
      return feedbackUrgencyScore(b) - feedbackUrgencyScore(a);
    });
    return rows;
  }, [teacherProjectCatalog, projectBoardCategory, projectBoardSort]);

  const projectBoardInsight = useMemo(() => {
    const scope = filteredProjectCatalog;
    if (!scope.length) return null;
    const totalScore = scope.reduce((sum: number, item: any) => sum + Number(item.latest_score || 0), 0);
    const avgScore = totalScore / scope.length;
    const highest = [...scope].sort((a: any, b: any) => Number(b.latest_score || 0) - Number(a.latest_score || 0))[0];
    const lowest = [...scope].sort((a: any, b: any) => Number(a.latest_score || 0) - Number(b.latest_score || 0))[0];
    const fastest = [...scope].sort((a: any, b: any) => Number(b.improvement || 0) - Number(a.improvement || 0))[0];
    const riskFreq: Record<string, number> = {};
    const intentFreq: Record<string, number> = {};
    scope.forEach((item: any) => {
      (item.top_risks || []).forEach((risk: string) => { riskFreq[risk] = (riskFreq[risk] || 0) + 1; });
      const intent = item.dominant_intent || "综合咨询";
      intentFreq[intent] = (intentFreq[intent] || 0) + 1;
    });
    const topRisks = Object.entries(riskFreq).sort((a, b) => Number(b[1]) - Number(a[1])).slice(0, 3);
    const topIntent = Object.entries(intentFreq).sort((a, b) => Number(b[1]) - Number(a[1]))[0]?.[0] || "综合咨询";
    return {
      total: scope.length,
      avgScore,
      highest,
      lowest,
      fastest,
      topIntent,
      topRisks,
      summaryLines: [
        `${projectBoardCategory}里共有 ${scope.length} 个项目，平均最新分 ${avgScore.toFixed(1)}。`,
        topRisks.length > 0 ? `最常出现的问题是 ${topRisks.map(([risk]) => getRuleDisplayName(risk)).join("、")}。` : "当前这一组项目的主要问题还不集中，适合老师做抽样精读。",
        fastest ? `最近进步最快的是 ${fastest.project_name}，提升 ${Number(fastest.improvement || 0).toFixed(1)} 分。` : "",
      ].filter(Boolean),
    };
  }, [filteredProjectCatalog, projectBoardCategory]);

  useEffect(() => {
    if (projectWorkspaceView !== "insight") return;
    if (!filteredProjectCatalog.length) {
      setProjectStructuredReport(null);
      return;
    }
    void generateProjectStructuredReport(filteredProjectCatalog, projectBoardCategory);
  }, [projectWorkspaceView, projectBoardCategory, filteredProjectCatalog]);

  const comparedProjectCards = useMemo(() => {
    const selected = projectCompareSelection
      .map((key) => teacherProjectCatalog.find((item: any) => item.project_key === key))
      .filter(Boolean);
    return selected.slice(0, 2);
  }, [projectCompareSelection, teacherProjectCatalog]);

  const projectCompareInsight = useMemo(() => {
    if (comparedProjectCards.length < 2) return null;
    const [left, right] = comparedProjectCards as any[];
    const scoreGap = Number(left.latest_score || 0) - Number(right.latest_score || 0);
    const iterationGap = Number(left.submission_count || 0) - Number(right.submission_count || 0);
    const stronger = scoreGap >= 0 ? left : right;
    const weaker = scoreGap >= 0 ? right : left;
    const progressLeader = Number(left.improvement || 0) >= Number(right.improvement || 0) ? left : right;
    const riskUnion = Array.from(new Set([...(left.top_risks || []), ...(right.top_risks || [])]));
    const sharedRisks = (left.top_risks || []).filter((risk: string) => (right.top_risks || []).includes(risk));
    return {
      stronger,
      weaker,
      progressLeader,
      scoreGap: Math.abs(scoreGap),
      iterationGap: Math.abs(iterationGap),
      sharedRisks,
      riskUnion,
      lines: [
        `${stronger.project_name} 当前整体状态更稳，最新分比另一项高 ${Math.abs(scoreGap).toFixed(1)} 分。`,
        `${progressLeader.project_name} 最近提升更明显，说明这一项的迭代质量更高。`,
        sharedRisks.length > 0
          ? `两项项目共同卡在 ${sharedRisks.map((risk: string) => getRuleDisplayName(risk)).join("、")}，适合提炼成一次共性教学。`
          : `两项项目的问题类型差异较大，建议分别处理：${riskUnion.slice(0, 3).map((risk: string) => getRuleDisplayName(risk)).join("、") || "当前暂无明显规则风险"}。`,
      ],
    };
  }, [comparedProjectCards]);

  useEffect(() => {
    const availableKeys = filteredProjectCatalog.map((item: any) => item.project_key);
    const kept = projectCompareSelection.filter((key) => availableKeys.includes(key)).slice(0, 2);
    if (kept.length >= 2) {
      if (kept.join("::") !== projectCompareSelection.slice(0, 2).join("::")) {
        setProjectCompareSelection(kept);
      }
      return;
    }
    const fallback = availableKeys.slice(0, 2);
    if (fallback.length === 2 && fallback.join("::") !== kept.join("::")) {
      setProjectCompareSelection(fallback);
    }
  }, [filteredProjectCatalog, projectCompareSelection]);

  const feedbackProjectCatalog = useMemo(() => {
    const rows = [...teacherProjectCatalog];
    rows.sort((a: any, b: any) => {
      if (feedbackSortMode === "activity") {
        return Number(b.submission_count || 0) - Number(a.submission_count || 0);
      }
      if (feedbackSortMode === "score") {
        return Number(a.latest_score || 0) - Number(b.latest_score || 0);
      }
      const urgencyDelta = feedbackUrgencyScore(b) - feedbackUrgencyScore(a);
      if (urgencyDelta !== 0) return urgencyDelta;
      return Number(b.submission_count || 0) - Number(a.submission_count || 0);
    });
    return rows.map((item: any, idx: number) => ({ ...item, feedback_order: idx + 1 }));
  }, [teacherProjectCatalog, feedbackSortMode]);

  const assistantPendingProjectCards = useMemo(() => {
    const pending = (assistantDashboard?.pending_assessments || []) as any[];
    const grouped = new Map<string, any>();
    pending.forEach((item: any) => {
      const key = `${item.project_id || ""}::${item.logical_project_id || ""}`;
      if (!grouped.has(key)) grouped.set(key, item);
    });
    if (assistantAssessment?.project_id) {
      const key = `${assistantAssessment.project_id || ""}::${assistantAssessment.logical_project_id || ""}`;
      if (!grouped.has(key)) {
        grouped.set(key, {
          project_id: assistantAssessment.project_id,
          logical_project_id: assistantAssessment.logical_project_id,
          project_name: assistantAssessment.project_name,
          student_id: assistantAssessment.student_id,
          student_name: assistantAssessment.student_id,
          team_name: "当前项目",
          project_phase: assistantAssessment.project_phase,
          latest_score: assistantAssessment.overall_score,
          submission_count: assistantAssessment.submission_count,
          top_risks: (assistantAssessment.evidence_chain || []).map((item: any) => item.risk_id || item.risk_name).filter(Boolean).slice(0, 3),
          current_summary: assistantAssessment.summary,
        });
      }
    }
    return Array.from(grouped.values()).sort((a: any, b: any) => {
      const riskDelta = (b.top_risks?.length || 0) - (a.top_risks?.length || 0);
      if (riskDelta !== 0) return riskDelta;
      return Number(a.latest_score || 0) - Number(b.latest_score || 0);
    }).map((item: any, idx: number) => ({ ...item, queue_order: idx + 1 }));
  }, [assistantDashboard, assistantAssessment]);

  const CLASS_SUB_TABS = [
    { id: "compare", label: "基线对比" },
    { id: "capability", label: "能力映射" },
    { id: "rule-coverage", label: "规则检查" },
    { id: "interventions", label: "教学建议" },
    { id: "report", label: "智能报告" },
  ];

  const PROJECT_SUB_TABS = [
    { id: "rubric", label: "评分与诊断" },
    { id: "competition", label: "竞赛预测" },
    { id: "evidence", label: "证据链" },
  ];

  if (!currentUser) return <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", color: "var(--text-muted)" }}>加载中...</div>;

  return (
    <div className="tch-app" suppressHydrationWarning>
      <header className="chat-topbar">
        <div className="topbar-left">
          <Link href="/" className="topbar-brand">VentureCheck</Link>
          <span className="topbar-sep" />
          <span className="topbar-label">教师控制台</span>
        </div>
        <div className="topbar-center">
          <div className="tch-topbar-status">
            <span className="tch-topbar-status-dot" />
            <span>{tab === "class" ? "团队视图基于学生真实项目记录自动汇总" : tab === "assistant" ? "教学助理支持审核批改与干预下发" : "教师端分析视图"}</span>
          </div>
        </div>
        <div className="topbar-right">
          <button 
            type="button"
            className="topbar-icon-btn" 
            onClick={() => setTheme((t) => t === "dark" ? "light" : "dark")}
            title={theme === "dark" ? "切换日间模式" : "切换夜间模式"}
            suppressHydrationWarning
          >
            {theme === "dark" ? (
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
            ) : (
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>
            )}
          </button>
          <button type="button" className="topbar-btn" onClick={logout}>退出</button>
        </div>
      </header>

      <div className="tch-body">
        <nav className="tch-sidebar">
          {TABS.map((t) => (
            <button 
              key={t.id} 
              className={`tch-nav-btn ${tab === t.id ? "active" : ""} ${loading ? "disabled" : ""}`}
              disabled={loading}
              style={{
                transition: "all 0.3s ease",
                opacity: loading && tab !== t.id ? 0.6 : 1,
              }}
              onClick={() => {
                setTab(t.id);
                if (t.id === "overview") loadDashboard();
                if (t.id === "submissions") loadSubmissions();
                if (t.id === "compare") loadCompare();
                if (t.id === "capability") loadCapabilityMap();
                if (t.id === "rule-coverage") loadRuleCoverage();
                if (t.id === "conversation-analytics") loadConversationAnalytics();
                if (t.id === "rubric") loadRubricAssessment();
                if (t.id === "competition") loadCompetitionScore();
                if (t.id === "interventions") loadTeachingInterventions();
                if (t.id === "assistant") loadAssistantDashboard();
                if (t.id === "class") {
                  if (!teamData) loadTeams();
                }
                if (t.id === "project") {
                  if (!teamData) loadTeams();
                }
                if (t.id === "feedback") {
                  if (!teamData) loadTeams();
                }
              }}>
              {t.label}
              {loading && tab === t.id && <span style={{ marginLeft: 8 }}>⏳</span>}
            </button>
          ))}
        </nav>

        <main className="tch-main">
          {/* 加载进度条 */}
          {loading && (
            <div
              style={{
                position: "fixed",
                top: 0,
                left: 0,
                right: 0,
                height: "3px",
                zIndex: 999,
              }}
              className="tch-progress-bar"
            />
          )}

          {/* 加载状态提示 */}
          {loading && (
            <div
              className="tch-loading"
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                gap: 12,
                animation: "fade-in 0.3s ease-out",
              }}
            >
              <div
                style={{
                  width: 40,
                  height: 40,
                  border: "3px solid var(--border)",
                  borderTop: "3px solid var(--accent)",
                  borderRadius: "50%",
                  animation: "spin 0.8s linear infinite",
                }}
              />
              <p>{loadingMessage}...</p>
              <p style={{ fontSize: 12, color: "var(--text-muted)" }}>请稍候</p>
            </div>
          )}

          {/* 消息提示 */}
          {successMessage && <SuccessToast message={successMessage} onClose={() => setSuccessMessage("")} />}
          {errorMessage && <ErrorToast message={errorMessage} onClose={() => setErrorMessage("")} />}

          {/* ── 总览 ── */}
          {tab === "overview" && !loading && (
            <div className="tch-panel fade-up">
              <h2>教学数据总览</h2>
              <p className="tch-desc">基于学生提交数据和图数据库实时计算，鼠标悬浮数字可查看计算方式</p>
              {dashboard?.error && <p className="right-hint">图数据读取失败：{dashboard.error}</p>}

              {!dashboard && !overviewStats ? (
                <SkeletonLoader rows={4} type="card" />
              ) : (
                <>
                  {/* ── KPI 统计卡片 ── */}
                  <div className="ov-kpi-grid">
                    {[
                      { key: "projects", icon: "📁", iconBg: "rgba(107,138,255,0.15)", iconColor: "var(--accent)", value: dashboard?.overview?.total_projects ?? 0, label: "项目总数", decimals: 0, tip: "Neo4j 图数据库中 Project 节点总数", formula: `COUNT(Project) = ${dashboard?.overview?.total_projects ?? 0}` },
                      { key: "students", icon: "👥", iconBg: "rgba(115,204,255,0.15)", iconColor: "#73ccff", value: overviewStats?.uniqueStudents ?? 0, label: "活跃学生", decimals: 0, tip: "提交记录中去重后的 student_id 数量", formula: `DISTINCT(student_id) = ${overviewStats?.uniqueStudents ?? 0}` },
                      { key: "submissions", icon: "📝", iconBg: "rgba(92,189,138,0.15)", iconColor: "var(--tch-success)", value: overviewStats?.totalSubmissions ?? 0, label: "总提交数", decimals: 0, tip: "所有项目的提交记录总数（含对话和文件）", formula: overviewStats?.sourceTypes ? Object.entries(overviewStats.sourceTypes).map(([k,v]) => `${k}: ${v}`).join(" + ") : "" },
                      { key: "score", icon: "⭐", iconBg: "rgba(232,168,76,0.15)", iconColor: "var(--tch-warning)", value: overviewStats?.avgScore ?? 0, label: "平均评分", decimals: 1, tip: "所有提交的 overall_score 平均值（满分10）", formula: `SUM(score) / COUNT = ${(overviewStats?.avgScore ?? 0).toFixed(1)}`, valueColor: (overviewStats?.avgScore ?? 0) >= 7 ? "var(--tch-success)" : (overviewStats?.avgScore ?? 0) >= 5 ? "var(--tch-warning)" : "var(--tch-danger)" },
                      { key: "evidence", icon: "🔗", iconBg: "rgba(189,147,249,0.15)", iconColor: "#bd93f9", value: dashboard?.overview?.total_evidence ?? 0, label: "证据链", decimals: 0, tip: "Neo4j 中 Evidence 节点总数", formula: `COUNT(Evidence) = ${dashboard?.overview?.total_evidence ?? 0}` },
                      { key: "risk", icon: "⚠️", iconBg: "rgba(224,112,112,0.15)", iconColor: "var(--tch-danger)", value: overviewStats?.riskRate ?? 0, label: "风险触发率", decimals: 1, suffix: "%", tip: "触发至少一条风险规则的提交占总提交比", formula: `${overviewStats?.withRules ?? 0} / ${overviewStats?.totalSubmissions ?? 0} = ${(overviewStats?.riskRate ?? 0).toFixed(1)}%`, valueColor: (overviewStats?.riskRate ?? 0) > 50 ? "var(--tch-danger)" : (overviewStats?.riskRate ?? 0) > 30 ? "var(--tch-warning)" : "var(--tch-success)" },
                    ].map((kpi: any) => (
                      <div key={kpi.key} className="ov-kpi-card" onMouseEnter={() => setHoveredKpi(kpi.key)} onMouseLeave={() => setHoveredKpi(null)}>
                        <div className="ov-kpi-icon" style={{ background: kpi.iconBg, color: kpi.iconColor }}>{kpi.icon}</div>
                        <div className="ov-kpi-value" style={kpi.valueColor ? { color: kpi.valueColor } : undefined}>
                          <AnimatedNumber value={kpi.value} decimals={kpi.decimals} />
                          {kpi.suffix && <span style={{ fontSize: 16, fontWeight: 500 }}>{kpi.suffix}</span>}
                        </div>
                        <div className="ov-kpi-label">{kpi.label}</div>
                        {hoveredKpi === kpi.key && (
                          <div className="ov-kpi-tip">
                            <strong>计算方式</strong>
                            <p>{kpi.tip}</p>
                            {kpi.formula && <div className="ov-kpi-formula">{kpi.formula}</div>}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>

                  {/* ── ROW 2: 类别分布 + 风险雷达 ── */}
                  <div className="ov-chart-grid">
                    <div className="ov-chart-card">
                      <h3>类别分布</h3>
                      <p className="tch-desc">学生项目的领域分类，点击可筛选</p>
                      {(dashboard?.category_distribution ?? []).length === 0 ? (
                        <p style={{ color: "var(--text-muted)", fontSize: 13, textAlign: "center", padding: 20 }}>暂无类别数据</p>
                      ) : (
                        <div className="ov-bar-list">
                          {(dashboard?.category_distribution ?? []).map((row: any, idx: number) => {
                            const pct = maxCat > 0 ? (Number(row.projects || 0) / maxCat) * 100 : 0;
                            const colors = ["rgba(107,138,255,0.65)","rgba(115,204,255,0.65)","rgba(92,189,138,0.65)","rgba(232,168,76,0.65)","rgba(189,147,249,0.65)","rgba(129,199,212,0.65)","rgba(255,183,197,0.65)","rgba(255,209,102,0.65)"];
                            return (
                              <div key={row.category} className="ov-bar-item" onClick={() => setCategoryFilter(row.category)} style={{ animationDelay: `${idx * 0.06}s` }}>
                                <div className="ov-bar-label"><span className="ov-bar-dot" style={{ background: colors[idx % colors.length] }} /><span>{row.category}</span></div>
                                <div className="ov-bar-track"><div className="ov-bar-fill" style={{ width: `${pct}%`, background: colors[idx % colors.length] }} /></div>
                                <span className="ov-bar-val">{row.projects}</span>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>

                    <div className="ov-chart-card">
                      <h3>风险规则雷达</h3>
                      <p className="tch-desc">各规则触发频率的多维可视化</p>
                      {overviewStats && overviewStats.ruleRadar.length >= 3 ? (
                        <RadarChart data={overviewStats.ruleRadar} />
                      ) : (dashboard?.top_risk_rules ?? []).length > 0 ? (
                        <div className="ov-bar-list">
                          {(dashboard?.top_risk_rules ?? []).slice(0, 6).map((row: any, idx: number) => {
                            const pct = maxRule > 0 ? (Number(row.projects || 0) / maxRule) * 100 : 0;
                            const colors = ["rgba(224,112,112,0.55)","rgba(224,168,76,0.55)","rgba(255,150,130,0.55)","rgba(189,147,249,0.55)","rgba(224,112,112,0.4)","rgba(224,168,76,0.4)"];
                            return (
                              <div key={row.rule} className="ov-bar-item" style={{ animationDelay: `${idx * 0.06}s` }}>
                                <div className="ov-bar-label"><span className="ov-bar-dot" style={{ background: colors[idx % colors.length] }} /><span>{getRuleDisplayName(row.rule)}</span></div>
                                <div className="ov-bar-track"><div className="ov-bar-fill" style={{ width: `${pct}%`, background: colors[idx % colors.length] }} /></div>
                                <span className="ov-bar-val">{row.projects}</span>
                              </div>
                            );
                          })}
                        </div>
                      ) : (
                        <p style={{ color: "var(--text-muted)", fontSize: 13, textAlign: "center", padding: 20 }}>暂无风险规则数据</p>
                      )}
                    </div>
                  </div>

                  {/* ── ROW 3: 成绩箱型图 + 直方图 | 提交趋势面积图 ── */}
                  {overviewStats && (
                    <div className="ov-chart-grid">
                      <div className="ov-chart-card">
                        <h3>成绩分布总览</h3>
                        <p className="tch-desc">箱型图：最小值 / Q1 / 中位数 / Q3 / 最大值，黄点为均值</p>
                        {overviewStats.scorePercentiles.max > 0 ? (
                          <BoxPlotChart data={overviewStats.scorePercentiles} />
                        ) : (
                          <p style={{ color: "var(--text-muted)", fontSize: 12, textAlign: "center" }}>暂无成绩数据</p>
                        )}
                        <div style={{ marginTop: 12, fontSize: 11, color: "var(--text-muted)", display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
                          <span>最低 <strong style={{ color: "var(--tch-danger)" }}>{overviewStats.scorePercentiles.min.toFixed(1)}</strong></span>
                          <span>Q1 <strong>{overviewStats.scorePercentiles.q1.toFixed(1)}</strong></span>
                          <span>中位数 <strong style={{ color: "var(--accent)" }}>{overviewStats.scorePercentiles.median.toFixed(1)}</strong></span>
                          <span>Q3 <strong>{overviewStats.scorePercentiles.q3.toFixed(1)}</strong></span>
                          <span>最高 <strong style={{ color: "var(--tch-success)" }}>{overviewStats.scorePercentiles.max.toFixed(1)}</strong></span>
                        </div>
                        <div style={{ marginTop: 16 }}>
                          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)", marginBottom: 8 }}>分段直方图</div>
                          <div className="ov-histogram">
                            {["0-2", "2-4", "4-6", "6-8", "8-10"].map((label, idx) => {
                              const count = overviewStats.scoreBuckets[idx] || 0;
                              const maxB = Math.max(1, ...overviewStats.scoreBuckets);
                              const h = (count / maxB) * 100;
                              const barColors = ["var(--tch-danger)","rgba(224,168,76,0.8)","rgba(232,168,76,0.65)","rgba(92,189,138,0.65)","var(--tch-success)"];
                              return (
                                <div key={label} className="ov-hist-col">
                                  <div className="ov-hist-count">{count}</div>
                                  <div className="ov-hist-bar" style={{ height: `${Math.max(h, 6)}%`, background: barColors[idx] }} />
                                  <div className="ov-hist-label">{label}</div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      </div>

                      <div className="ov-chart-card">
                        <h3>提交趋势</h3>
                        <p className="tch-desc">按日期统计的提交量变化趋势</p>
                        {overviewStats.activityByDate.length >= 2 ? (
                          <AreaChart data={overviewStats.activityByDate} color="rgba(107,138,255,0.9)" />
                        ) : (
                          <p style={{ color: "var(--text-muted)", fontSize: 12, textAlign: "center", padding: 20 }}>数据点不足，需至少 2 天提交记录</p>
                        )}
                        <div style={{ marginTop: 16, padding: "12px 14px", background: "var(--bg-secondary)", borderRadius: 10, border: "1px solid var(--border)" }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                            <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>规则命中总次数</span>
                            <strong style={{ fontSize: 20, color: "var(--tch-danger)" }}>{dashboard?.overview?.total_rule_hits ?? 0}</strong>
                          </div>
                          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>Project → HITS_RULE → RiskRule 关系总数</div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* ── ROW 4: 提交来源环形图 + 学生分布散点图 ── */}
                  {overviewStats && (
                    <div className="ov-chart-grid">
                      <div className="ov-chart-card">
                        <h3>提交来源构成</h3>
                        <p className="tch-desc">各提交方式的占比分布</p>
                        {Object.keys(overviewStats.sourceTypes).length === 0 ? (
                          <p style={{ color: "var(--text-muted)", fontSize: 13, textAlign: "center", padding: 20 }}>暂无数据</p>
                        ) : (
                          <>
                            <DonutChart data={Object.entries(overviewStats.sourceTypes).map(([type, count], idx) => {
                              const labels: Record<string,string> = { dialogue: "对话", file: "文件上传", file_in_chat: "聊天上传", text: "文本输入" };
                              const colors = ["rgba(107,138,255,0.7)","rgba(92,189,138,0.7)","rgba(232,168,76,0.7)","rgba(189,147,249,0.7)","rgba(129,199,212,0.7)"];
                              return { label: labels[type] || type, value: count as number, color: colors[idx % colors.length] };
                            })} />
                            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center", marginTop: 12 }}>
                              {Object.entries(overviewStats.sourceTypes).map(([type, count], idx) => {
                                const labels: Record<string,string> = { dialogue: "💬 对话", file: "📄 文件", file_in_chat: "📎 聊天上传", text: "📝 文本" };
                                const colors = ["rgba(107,138,255,0.7)","rgba(92,189,138,0.7)","rgba(232,168,76,0.7)","rgba(189,147,249,0.7)","rgba(129,199,212,0.7)"];
                                return (
                                  <span key={type} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "var(--text-secondary)" }}>
                                    <span style={{ width: 8, height: 8, borderRadius: "50%", background: colors[idx % colors.length] }} />
                                    {labels[type] || type} <strong style={{ marginLeft: 2 }}>{count as number}</strong>
                                  </span>
                                );
                              })}
                            </div>
                          </>
                        )}
                      </div>

                      <div className="ov-chart-card">
                        <h3>学生表现分布</h3>
                        <p className="tch-desc">横轴=提交次数 纵轴=平均分，颜色=状态（绿/黄/红），悬浮查看详情</p>
                        {overviewStats.studentScatter.length > 0 ? (
                          <ScatterPlot data={overviewStats.studentScatter} />
                        ) : (
                          <p style={{ color: "var(--text-muted)", fontSize: 12, textAlign: "center", padding: 20 }}>暂无学生数据</p>
                        )}
                      </div>
                    </div>
                  )}

                  {/* ── 近期提交活动 ── */}
                  {overviewStats && overviewStats.recent.length > 0 && (
                    <div className="ov-section">
                      <h3>近期提交活动</h3>
                      <p className="tch-desc">最近的学生提交，点击可跳转查看证据链</p>
                      <div className="ov-activity-list">
                        {overviewStats.recent.map((s: any, i: number) => (
                          <div key={i} className="ov-activity-item" style={{ animationDelay: `${i * 0.04}s` }} onClick={() => { setSelectedProject(s.project_id); loadEvidence(s.project_id); }}>
                            <div className="ov-activity-avatar">{(s.student_id || "?")[0].toUpperCase()}</div>
                            <div className="ov-activity-info">
                              <div className="ov-activity-name">
                                <span>{s.student_id || "未知学生"}</span>
                                <span className="ov-activity-type">{s.source_type === "dialogue" ? "💬 对话" : s.source_type === "file" ? "📄 文件" : s.source_type || "提交"}</span>
                              </div>
                              <div className="ov-activity-detail">{s.project_id}{s.filename ? ` · ${s.filename}` : ""}{s.bottleneck ? ` · ${(s.bottleneck as string).slice(0, 50)}` : ""}</div>
                            </div>
                            <div className="ov-activity-score" style={{ color: Number(s.overall_score) >= 7 ? "var(--tch-success)" : Number(s.overall_score) >= 5 ? "var(--tch-warning)" : "var(--tch-danger)" }}>
                              {Number(s.overall_score).toFixed(1)}
                            </div>
                            <div className="ov-activity-time">{formatBJTime(s.created_at)}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* ── 学生概况 ── */}
                  {overviewStats && overviewStats.studentSummary.length > 0 && (
                    <div className="ov-section">
                      <h3>学生概况</h3>
                      <p className="tch-desc">按学生维度汇总，快速识别需要关注的学生</p>
                      <div className="ov-stu-table">
                        <div className="ov-stu-header"><span>学生</span><span>提交次数</span><span>平均分</span><span>状态</span></div>
                        {overviewStats.studentSummary.map((stu: any, idx: number) => {
                          const st = stu.avgScore >= 7 ? { l: "良好", c: "var(--tch-success)", bg: "var(--tch-success-soft)" } : stu.avgScore >= 5 ? { l: "一般", c: "var(--tch-warning)", bg: "var(--tch-warning-soft)" } : { l: "需关注", c: "var(--tch-danger)", bg: "var(--tch-danger-soft)" };
                          return (
                            <div key={stu.id} className="ov-stu-row" style={{ animationDelay: `${idx * 0.03}s` }}>
                              <span className="ov-stu-name"><span className="ov-stu-av">{(stu.id as string)[0]?.toUpperCase()}</span>{stu.id}</span>
                              <span><strong>{stu.count}</strong><span style={{ fontSize: 11, color: "var(--text-muted)", marginLeft: 4 }}>次</span></span>
                              <span style={{ fontWeight: 600, color: st.c }}>{stu.avgScore.toFixed(1)}</span>
                              <span><span className="ov-status-badge" style={{ color: st.c, background: st.bg }}>{st.l}</span></span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* ── 高风险项目 ── */}
                  <div className="ov-section">
                    <h3>高风险项目</h3>
                    <p className="tch-desc">触发风险规则最多的项目，建议优先关注</p>
                    {(dashboard?.high_risk_projects ?? []).length === 0 ? (
                      <p style={{ color: "var(--text-muted)", fontSize: 13, padding: 20, textAlign: "center" }}>暂无高风险项目</p>
                    ) : (
                      <div className="ov-risk-grid">
                        {(dashboard?.high_risk_projects ?? []).slice(0, 8).map((row: any, idx: number) => (
                          <button key={row.project_id} className="ov-risk-card" onClick={() => loadEvidence(row.project_id)} style={{ animationDelay: `${idx * 0.05}s` }}>
                            <div className="ov-risk-hd"><span className="ov-risk-name">{row.project_name || row.project_id}</span><span className="risk-badge high">风险 {row.risk_count}</span></div>
                            <div className="ov-risk-meta"><span>{row.category}</span>{row.confidence !== undefined && <span>置信度 {row.confidence}</span>}</div>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          )}

          {/* ── 对话质量 ── */}
          {tab === "conversation-analytics" && !loading && (
            <div className="tch-panel fade-up">
              <h2>🧠 对话质量分析</h2>
              <p className="tch-desc">基于多轮对话的提问密度、高阶对话占比、证据意识趋势，以及班级共性谬误与提问热点。</p>
              {!conversationAnalytics ? (
                <SkeletonLoader rows={3} type="card" />
              ) : (() => {
                const ca = conversationAnalytics as any;
                const summary = ca.summary || {};
                const scatter = (ca.scatter || []) as any[];
                const box = ca.high_order_ratio_box || { min: 0, q1: 0, median: 0, q3: 0, max: 0, avg: 0 };
                const topics = (ca.topics || []) as any[];
                const fallacies = (ca.fallacies || []) as any[];
                const scatterQuestion = scatter.map((row: any) => ({
                  id: row.student_id || "?",
                  x: Number(row.turn_count || 0),
                  y: Math.max(0, Math.min(10, Number(row.question_density || 0) * 10)),
                }));
                const scatterEvidence = scatter.map((row: any) => {
                  const raw = Number(row.evidence_awareness_trend || 0);
                  const score = Math.max(0, Math.min(10, 5 + raw));
                  return {
                    id: row.student_id || "?",
                    x: Number(row.turn_count || 0),
                    y: score,
                  };
                });
                const students = (ca.students || []) as any[];
                return (
                  <>
                    <div className="kpi-grid" style={{ marginBottom: 16 }}>
                      <div className="kpi">
                        <span>活跃学生</span>
                        <strong>{summary.student_count ?? 0}</strong>
                        <em className="kpi-hint">有对话记录的学生人数</em>
                      </div>
                      <div className="kpi">
                        <span>总对话轮数</span>
                        <strong>{summary.conversation_count ?? 0}</strong>
                        <em className="kpi-hint">按 conversation_id 聚合的轮数总和</em>
                      </div>
                      <div className="kpi">
                        <span>人均轮数</span>
                        <strong>{Number(summary.avg_turn_count || 0).toFixed(1)}</strong>
                        <em className="kpi-hint">平均每名学生的对话轮数</em>
                      </div>
                      <div className="kpi">
                        <span>平均提问密度</span>
                        <strong>{Number(summary.avg_question_density || 0).toFixed(2)}</strong>
                        <em className="kpi-hint">每轮对话中 AI 关键追问条数</em>
                      </div>
                    </div>

                    <div className="ov-chart-grid">
                      <div className="ov-chart-card">
                        <h3>提问密度 vs 对话轮数</h3>
                        <p className="tch-desc">横轴=对话轮数 纵轴=提问密度(0-10)，颜色代表得分高低。</p>
                        {scatterQuestion.length > 0 ? (
                          <ScatterPlot data={scatterQuestion} xLabel="对话轮数" yLabel="提问密度(0-10)" />
                        ) : (
                          <p style={{ color: "var(--text-muted)", fontSize: 12, textAlign: "center", padding: 20 }}>暂无对话记录</p>
                        )}
                      </div>
                      <div className="ov-chart-card">
                        <h3>证据意识进步度</h3>
                        <p className="tch-desc">横轴=对话轮数 纵轴=证据意识分数(0-10)，高于5表示缺失证据在减少。</p>
                        {scatterEvidence.length > 0 ? (
                          <ScatterPlot data={scatterEvidence} xLabel="对话轮数" yLabel="证据意识(0-10)" />
                        ) : (
                          <p style={{ color: "var(--text-muted)", fontSize: 12, textAlign: "center", padding: 20 }}>暂无对话记录</p>
                        )}
                      </div>
                    </div>

                    <div className="ov-chart-grid">
                      <div className="ov-chart-card">
                        <h3>高阶对话占比（班级分布）</h3>
                        <p className="tch-desc">统计每名学生高阶意图对话（学习/诊断/方案/路演）的占比，0-10 代表 0%-100%。</p>
                        <BoxPlotChart data={box} />
                      </div>
                      <div className="ov-chart-card">
                        <h3>学生对话画像</h3>
                        <p className="tch-desc">快速识别“话很多但进步小”的学生，点击可跳转到对话复盘。</p>
                        {students.length === 0 ? (
                          <p style={{ color: "var(--text-muted)", fontSize: 12, textAlign: "center", padding: 20 }}>暂无对话记录</p>
                        ) : (
                          <div className="ov-stu-table">
                            <div className="ov-stu-header">
                              <span>学生</span>
                              <span>对话轮数</span>
                              <span>提问密度</span>
                              <span>高阶对话占比</span>
                              <span>画像</span>
                              <span>操作</span>
                            </div>
                            {students.map((stu: any, idx: number) => {
                              const highOrderPct = Math.round(Number(stu.high_order_ratio || 0) * 100);
                              const qd = Number(stu.question_density || 0);
                              const persona = String(stu.persona || "直觉表达型");
                              const personaStyle = persona === "证据敏感型"
                                ? { color: "var(--tch-success)", background: "var(--tch-success-soft)" }
                                : persona === "被动应答型"
                                  ? { color: "var(--tch-danger)", background: "var(--tch-danger-soft)" }
                                  : { color: "var(--accent)", background: "rgba(107,138,255,0.15)" };
                              return (
                                <div key={stu.student_id} className="ov-stu-row" style={{ animationDelay: `${idx * 0.03}s` }}>
                                  <span className="ov-stu-name">
                                    <span className="ov-stu-av">{(stu.student_id as string)[0]?.toUpperCase()}</span>
                                    {stu.student_id}
                                  </span>
                                  <span>{stu.turn_count}</span>
                                  <span>{qd.toFixed(2)}</span>
                                  <span>{highOrderPct}%</span>
                                  <span>
                                    <span className="ov-status-badge" style={personaStyle}>{persona}</span>
                                  </span>
                                  <span>
                                    <button
                                      type="button"
                                      className="tch-sm-btn"
                                      onClick={() => loadAssistantConversationEval(`project-${stu.student_id}`)}
                                    >
                                      对话复盘
                                    </button>
                                  </span>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="ov-chart-grid" style={{ marginTop: 12 }}>
                      <div className="ov-chart-card">
                        <h3>提问热点 Top 主题</h3>
                        <p className="tch-desc">横向比较学生最常追问/求助的主题，以及对应的高频红线规则。</p>
                        {topics.length === 0 ? (
                          <p style={{ color: "var(--text-muted)", fontSize: 12, textAlign: "center", padding: 20 }}>暂无可统计的对话主题。</p>
                        ) : (
                          <div className="ov-stu-table">
                            <div className="ov-stu-header">
                              <span>主题</span>
                              <span>覆盖学生占比</span>
                              <span>轮次占比</span>
                              <span>相关规则</span>
                            </div>
                            {topics.map((t: any, idx: number) => (
                              <div key={t.topic || idx} className="ov-stu-row" style={{ animationDelay: `${idx * 0.03}s` }}>
                                <span>{t.topic || "未标注"}</span>
                                <span>{Math.round(Number(t.students_ratio || 0) * 100)}%</span>
                                <span>{Math.round(Number(t.turn_ratio || 0) * 100)}%</span>
                                <span>
                                  {(t.related_rules || []).slice(0, 4).map((r: any) => (
                                    <span key={r.rule_id} className="tm-smart-chip">{getRuleDisplayName(r.rule_id)}</span>
                                  ))}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                      <div className="ov-chart-card">
                        <h3>班级共性谬误（对话视角）</h3>
                        <p className="tch-desc">聚焦在多轮对话中频繁被触发的 H 规则，辅助老师设计集中讲解。</p>
                        {fallacies.length === 0 ? (
                          <p style={{ color: "var(--text-muted)", fontSize: 12, textAlign: "center", padding: 20 }}>暂无明显的共性谬误。</p>
                        ) : (
                          <div className="ov-stu-table">
                            <div className="ov-stu-header">
                              <span>规则</span>
                              <span>触发次数</span>
                              <span>覆盖学生占比</span>
                              <span>谬误/超图族</span>
                            </div>
                            {fallacies.map((f: any, idx: number) => (
                              <div key={f.rule_id || idx} className="ov-stu-row" style={{ animationDelay: `${idx * 0.03}s` }}>
                                <span>{getRuleDisplayName(f.rule_id)}</span>
                                <span>{f.hit_count ?? 0}</span>
                                <span>{Math.round(Number(f.students_ratio || 0) * 100)}%</span>
                                <span>
                                  <span className="tm-smart-chip">{f.fallacy || "-"}</span>
                                  {(f.edge_families || []).slice(0, 3).map((fam: string) => (
                                    <span key={fam} className="tm-smart-chip">{fam}</span>
                                  ))}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </>
                );
              })()}
            </div>
          )}

          {/* ── 学生提交列表 ── */}
          {tab === "submissions" && !loading && (
            <div className="tch-panel fade-up">
              {(() => {
                const recent = submissions.slice(0, 12);
                const sourceMix = recent.reduce((acc: Record<string, number>, row: any) => {
                  const key = row.source_type || "text";
                  acc[key] = (acc[key] || 0) + 1;
                  return acc;
                }, {});
                const risky = recent.filter((row: any) => (row.triggered_rules || []).length > 0).length;
                const avgScore = recent.length ? recent.reduce((sum: number, row: any) => sum + Number(row.overall_score || 0), 0) / recent.length : 0;
                const highlighted = recent[expandedSubmission ?? 0] || recent[0];
                return (
                  <>
                    <div className="assistant-hero assistant-hero-large" style={{ marginBottom: 20 }}>
                      <div>
                        <div className="tm-project-cover-label">Submission Flow</div>
                        <h2 style={{ marginTop: 6, marginBottom: 6 }}>学生提交</h2>
                        <p className="tch-desc" style={{ margin: 0 }}>这里不再只是原始记录表，而是“学生材料流转入口”。老师可以快速判断哪些提交该进 `项目工作台`、哪些该进 `材料反馈`、哪些该触发 `教学助理`。</p>
                      </div>
                      <div className="assistant-summary-stack" style={{ minWidth: 280 }}>
                        <div className="assistant-summary-card">
                          <span>最近提交</span>
                          <strong>{recent.length}</strong>
                        </div>
                        <div className="assistant-summary-card">
                          <span>高风险占比</span>
                          <strong>{recent.length ? Math.round((risky / recent.length) * 100) : 0}%</strong>
                        </div>
                        <div className="assistant-summary-card">
                          <span>均分</span>
                          <strong>{avgScore.toFixed(1)}</strong>
                        </div>
                        <div className="assistant-summary-card">
                          <span>主要来源</span>
                          <strong>{Object.keys(sourceMix)[0] || "text"}</strong>
                        </div>
                      </div>
                    </div>

                    {recent.length === 0 ? (
                      <p style={{ color: "var(--text-muted)", fontSize: 12, padding: 20, textAlign: "center" }}>📭 暂无提交记录。学生对话或上传材料后，这里会自动形成材料流。</p>
                    ) : (
                      <div className="assistant-shell">
                        <div className="assistant-main-panel">
                          <div className="assistant-panel-head">
                            <div>
                              <h3>提交流时间廊道</h3>
                              <p className="tch-desc" style={{ marginBottom: 0 }}>每一条都是一个可进入后续工作台的入口：诊断、材料反馈、证据链、过程评估。</p>
                            </div>
                          </div>
                          <div className="submission-corridor">
                            {recent.map((s: any, i: number) => {
                              const score = Number(s.overall_score || 0);
                              const scoreColor = score >= 7 ? "var(--tch-success)" : score >= 5 ? "var(--tch-warning)" : "var(--tch-danger)";
                              const isActive = (expandedSubmission ?? 0) === i;
                              return (
                                <button
                                  key={`${s.project_id}-${s.created_at}-${i}`}
                                  className={`submission-card ${isActive ? "active" : ""}`}
                                  onClick={() => setExpandedSubmission(i)}
                                >
                                  <div className="submission-card-top">
                                    <div>
                                      <div className="submission-card-meta">{formatBJTime(s.created_at)}</div>
                                      <strong>{s.filename || s.project_id}</strong>
                                    </div>
                                    <div className="submission-score-pill" style={{ color: scoreColor, borderColor: `${scoreColor}55` }}>{score.toFixed(1)}</div>
                                  </div>
                                  <div className="tm-case-meta">
                                    <span>{s.student_id}</span>
                                    {s.logical_project_id && <span>{s.logical_project_id}</span>}
                                    {s.project_phase && <span>{s.project_phase}</span>}
                                    <span>{s.source_type}{s.filename ? ` · ${s.filename}` : ""}</span>
                                  </div>
                                  <div className="tm-case-inline-summary" style={{ marginTop: 8 }}>{s.bottleneck || s.text_preview || "暂无摘要"}</div>
                                  <div className="tm-corridor-tags" style={{ marginTop: 10 }}>
                                    {(s.triggered_rules || []).slice(0, 3).map((risk: string) => <span key={risk} className="tm-smart-chip">{getRuleDisplayName(risk)}</span>)}
                                    {(s.agent_trace_meta?.agents_called || []).slice(0, 2).map((agent: string) => <span key={agent} className="tm-smart-chip">{agent}</span>)}
                                  </div>
                                </button>
                              );
                            })}
                          </div>
                        </div>

                        <div className="assistant-side-panel">
                          <div className="assistant-side-card sticky">
                            <div className="assistant-section-title">当前选中提交</div>
                            {highlighted ? (
                              <>
                                <div className="tm-case-summary" style={{ marginTop: 0 }}>
                                  <div className="tm-case-summary-title">{highlighted.student_id}</div>
                                  <div className="tm-case-summary-body">{highlighted.full_text || highlighted.text_preview || "暂无原文预览"}</div>
                                </div>
                                <div className="assistant-note-list" style={{ marginTop: 12 }}>
                                  <div className="tm-note-row good">逻辑项目：{highlighted.logical_project_id || "当前项目"}</div>
                                  <div className="tm-note-row good">阶段：{highlighted.project_phase || "持续迭代"}</div>
                                  <div className="tm-note-row good">运行策略：{highlighted.agent_trace_meta?.strategy || "submission_flow"}</div>
                                  <div className="tm-note-row good">意图形态：{highlighted.agent_trace_meta?.intent_shape || "single"}</div>
                                  {(highlighted.agent_trace_meta?.agents_called || []).length > 0 && (
                                    <div className="tm-note-row warn">参与 Agent：{highlighted.agent_trace_meta.agents_called.join(" / ")}</div>
                                  )}
                                  {highlighted.agent_trace_meta?.agent_reasoning && (
                                    <div className="tm-note-row good">编排理由：{highlighted.agent_trace_meta.agent_reasoning}</div>
                                  )}
                                  {highlighted.agent_trace_meta?.intent_reason && (
                                    <div className="tm-note-row good">识别理由：{highlighted.agent_trace_meta.intent_reason}</div>
                                  )}
                                  {(highlighted.matched_teacher_interventions || []).length > 0 && (
                                    <div className="tm-note-row warn">命中教师干预：{highlighted.matched_teacher_interventions.map((item: any) => item.title).join(" / ")}</div>
                                  )}
                                </div>
                                {highlighted.bottleneck && <div className="tm-note-row warn" style={{ marginTop: 12 }}>{highlighted.bottleneck}</div>}
                                {highlighted.next_task && <div className="tm-note-row good" style={{ marginTop: 8 }}>{highlighted.next_task}</div>}
                                {highlighted.kg_analysis?.insight && <div className="tm-note-row good" style={{ marginTop: 8 }}>{highlighted.kg_analysis.insight}</div>}
                                <div className="assistant-toolbar">
                                  <button className="tch-sm-btn" onClick={() => loadProjectWorkbench(highlighted.project_id, highlighted.logical_project_id || "")}>进入项目工作台</button>
                                  <button className="tch-sm-btn" onClick={() => loadFeedbackWorkspace(highlighted.project_id, highlighted.logical_project_id || "", highlighted.submission_id || "")}>进入材料反馈</button>
                                  <button className="tch-sm-btn" onClick={() => loadAssistantAssessment(highlighted.project_id, highlighted.logical_project_id || "")}>批改与溯源</button>
                                  <button className="tch-sm-btn" onClick={() => loadAssistantConversationEval(highlighted.project_id, highlighted.logical_project_id || "")}>过程评估</button>
                                </div>
                              </>
                            ) : <p className="right-hint">请选择一条提交。</p>}
                          </div>
                        </div>
                      </div>
                    )}
                  </>
                );
              })()}
            </div>
          )}

          {/* ── 基线对比 ── */}
          {tab === "compare" && !loading && (
            <div className="tch-panel fade-up">
              <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
                <button onClick={() => setTab("class")} className="tch-back-btn">← 返回班级</button>
              </div>
              <h2>📊 历史基线 vs 本班现状</h2>
              <p className="tch-desc">将本班数据与历史所有班级的平均水平对比。"风险强度"=平均每个项目触发的风险规则数，数值越低越好。差值为正表示本班风险高于历史平均。</p>
              <div className="kpi-grid" style={{ animation: "fade-in 0.4s ease-out" }}>
                <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                  <span>📈 基线风险强度</span>
                  <strong style={{ fontSize: 28 }}>{compareData?.baseline?.avg_rule_hits_per_project ?? "-"}</strong>
                  <em className="kpi-hint">历史全部项目的平均值</em>
                </div>
                <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                  <span>🎯 本班风险强度</span>
                  <strong style={{ fontSize: 28 }}>{compareData?.current_class?.avg_rule_hits_per_submission ?? "-"}</strong>
                  <em className="kpi-hint">本班学生提交的平均值</em>
                </div>
                <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                  <span>📊 差值</span>
                  <strong style={{ 
                    fontSize: 28, 
                    color: Number(compareData?.comparison?.risk_intensity_delta) > 0 ? "var(--tch-danger)" : "var(--tch-success)"
                  }}>
                    {compareData?.comparison?.risk_intensity_delta ?? "-"}
                  </strong>
                  <em className="kpi-hint">正数=高于基线，负数=优于基线</em>
                </div>
              </div>
              <div className="kpi-grid" style={{ animation: "fade-in 0.5s ease-out" }}>
                <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                  <span>⚠️ 基线高风险占比</span>
                  <strong style={{ fontSize: 28 }}>{compareData?.baseline?.high_risk_ratio ?? "-"}</strong>
                  <em className="kpi-hint">历史高危项目的比例</em>
                </div>
                <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                  <span>🔍 本班高风险占比</span>
                  <strong style={{ fontSize: 28 }}>{compareData?.current_class?.high_risk_ratio ?? "-"}</strong>
                  <em className="kpi-hint">本班高危项目的比例</em>
                </div>
                <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                  <span>⭐ Rubric 均分</span>
                  <strong style={{ fontSize: 28, color: "var(--tch-warning)" }}>{compareData?.current_class?.avg_rubric_score ?? "-"}</strong>
                  <em className="kpi-hint">9维度评分的平均值(满分10)</em>
                </div>
              </div>
              <h3 style={{ marginTop: 24 }}>💡 自动干预建议</h3>
              <p className="tch-desc">系统根据对比差异自动生成的教学建议。建议在课堂上针对性讲解。</p>
              <div className="tch-recs" style={{ animation: "fade-in 0.6s ease-out" }}>
                {(compareData?.recommendations ?? []).length === 0 ? (
                  <p style={{ color: "var(--text-muted)", fontSize: 12 }}>暂无建议</p>
                ) : (
                  (compareData?.recommendations ?? []).map((item: string, i: number) => (
                    <div 
                      key={i} 
                      className="right-tag"
                      style={{
                        animation: `fade-in 0.3s ease-out ${i * 0.1}s both`,
                        transition: "all 0.2s ease",
                      }}
                    >
                      ✓ {item}
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {/* ── 证据链 ── */}
          {tab === "evidence" && !loading && (
            <div className="tch-panel fade-up">
              <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
                <button onClick={() => setTab("project")} className="tch-back-btn">← 返回项目</button>
              </div>
              <h2>🔗 项目证据链 — {selectedProject || projectId}</h2>
              <p className="tch-desc">证据链包括从Neo4j图数据库中提取的关键证据，以及学生提交的项目文件。证据越完整，项目越成熟。</p>
              <div className="tch-evidence-actions" style={{ display: "flex", gap: 8 }}>
                <input 
                  value={selectedProject || projectId} 
                  onChange={(e) => setSelectedProject(e.target.value)} 
                  placeholder="项目ID"
                  style={{ flex: 1 }}
                />
                <button className="topbar-btn" onClick={() => loadEvidence(selectedProject || projectId)}>加载</button>
                <button className="topbar-btn" onClick={() => loadFeedbackWorkspace(selectedProject || projectId, selectedLogicalProjectId || "")}>✍️ 去材料反馈</button>
              </div>
              {!evidence ? (
                <SkeletonLoader rows={3} type="card" />
              ) : evidence && evidence.project ? (
                <>
                  <p className="right-hint" style={{ animation: "fade-in 0.3s ease-out" }}>
                    📌 {evidence.project.project_name} | {evidence.project.category} | 置信度 {evidence.project.confidence ?? 0}
                  </p>
                  
                  {/* Neo4j Evidence Section */}
                  {evidence.evidence && evidence.evidence.length > 0 ? (
                    <div style={{ animation: "fade-in 0.4s ease-out" }}>
                      <h3 style={{ marginTop: 20, marginBottom: 10 }}>🗂️ 图数据库证据 ({evidence.evidence.length})</h3>
                      <div className="table-like">
                        {evidence.evidence.map((e: any, idx: number) => (
                          <div 
                            key={e.evidence_id} 
                            className="evidence-item"
                            style={{
                              animation: `fade-in 0.3s ease-out ${idx * 0.05}s both`,
                              transition: "all 0.2s ease",
                            }}
                          >
                            <strong style={{ color: "var(--accent-text)" }}>📝 {e.type}</strong>
                            <p style={{ margin: "8px 0" }}>{e.quote}</p>
                            <em style={{ color: "var(--text-muted)" }}>来源: {e.source_unit}</em>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div style={{ marginTop: 20, padding: 16, background: "var(--bg-card)", borderRadius: 8 }}>
                      <p style={{ fontSize: 12, color: "var(--text-muted)" }}>📭 Neo4j中暂无结构化证据数据</p>
                    </div>
                  )}
                  
                  {/* Student File Submissions Section */}
                  {evidence.file_submissions && evidence.file_submissions.length > 0 ? (
                    <div style={{ animation: "fade-in 0.5s ease-out" }}>
                      <h3 style={{ marginTop: 20, marginBottom: 10 }}>📤 学生提交文件 ({evidence.file_submissions.length})</h3>
                      <div className="table-like">
                        {evidence.file_submissions.map((s: any, idx: number) => (
                          <div 
                            key={s.submission_id} 
                            className="evidence-item" 
                            style={{ 
                              borderLeft: "3px solid var(--tch-success)",
                              animation: `fade-in 0.3s ease-out ${idx * 0.05}s both`,
                              transition: "all 0.2s ease",
                            }}
                          >
                            <strong>📄 {s.filename}</strong>
                            <p style={{ marginTop: 8, marginBottom: 10, fontSize: 12, color: "var(--text-secondary)" }}>
                              <em suppressHydrationWarning>学生: {s.student_id} | 提交时间: {s.created_at ? '已提交' : '未知'}</em>
                            </p>
                            
                            {/* Summary Section */}
                            {s.summary ? (
                              <p style={{ fontSize: 13, color: "var(--text-primary)", fontWeight: 500, marginBottom: 10, padding: "8px 10px", background: "var(--bg-card)", borderRadius: 4 }}>
                                {s.summary}
                              </p>
                            ) : null}
                            
                            {/* Diagnosis Details */}
                            {s.diagnosis && Object.keys(s.diagnosis).length > 0 ? (
                              <details style={{ fontSize: 12, marginTop: 8 }}>
                                <summary style={{ cursor: "pointer", color: "var(--accent-text)", fontWeight: 500 }}>📊 查看详细诊断信息</summary>
                                <div style={{ fontSize: 12, background: "var(--bg-card)", padding: 10, borderRadius: 4, marginTop: 8 }}>
                                  {s.diagnosis.overall_score !== undefined && (
                                    <p><strong>诊断评分:</strong> {s.diagnosis.overall_score.toFixed(2)}/5.0</p>
                                  )}
                                  {s.diagnosis.bottleneck && (
                                    <p><strong>核心瓶颈:</strong> {s.diagnosis.bottleneck}</p>
                                  )}
                                  {s.diagnosis.triggered_rules && s.diagnosis.triggered_rules.length > 0 ? (
                                    <p>
                                      <strong>触发规则:</strong> {s.diagnosis.triggered_rules.map((r: any) => (
                                        <span key={r.id} style={{ display: "inline-block", marginRight: 8, padding: "2px 6px", background: "var(--tch-danger-soft)", borderRadius: 3, fontSize: 11 }}>
                                          {r.id}: {r.name}
                                        </span>
                                      ))}
                                    </p>
                                  ) : null}
                                </div>
                              </details>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div style={{ marginTop: 20, padding: 16, background: "var(--bg-card)", borderRadius: 8 }}>
                      <p style={{ fontSize: 12, color: "var(--text-muted)" }}>📭 该项目暂无学生提交的文件</p>
                    </div>
                  )}
                  
                  {(!evidence.evidence || evidence.evidence.length === 0) && (!evidence.file_submissions || evidence.file_submissions.length === 0) && (
                    <p className="right-hint" style={{ marginTop: 20, padding: 20, textAlign: "center" }}>暂无任何证据数据</p>
                  )}
                </>
              ) : (
                <p className="right-hint" style={{ padding: 20, textAlign: "center" }}>
                  {!evidence ? "📌 请输入项目ID后点击'加载'按钮" : "❌ 项目信息加载失败，请检查项目ID是否正确或稍后重试"}
                </p>
              )}
            </div>
          )}

          {/* ── 智能报告 ── */}
          {tab === "report" && !loading && (
            <div className="tch-panel fade-up">
              <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
                <button onClick={() => setTab("class")} className="tch-back-btn">← 返回班级</button>
              </div>
              <h2>🤖 AI 班级报告</h2>
              <p className="tch-desc">由AI基于全班提交数据自动生成的评估报告，包含风险分布、共性问题和教学建议。可反复生成获取最新分析。</p>
              <button className="topbar-btn" onClick={generateReport} disabled={loading} style={{ marginBottom: 16, transition: "all 0.2s ease" }}>
                {loading ? "生成中…" : "🔄 重新生成"}
              </button>
              {!report ? (
                <SkeletonLoader rows={3} type="card" />
              ) : (
                <>
                  <div className="tch-report-content" style={{ animation: "fade-in 0.4s ease-out" }}>
                    {report}
                  </div>
                  {reportSnapshot && (
                    <details className="debug-json" style={{ marginTop: 16, animation: "fade-in 0.5s ease-out" }}>
                      <summary style={{ cursor: "pointer", color: "var(--accent-text)", fontWeight: "600" }}>📊 查看报告依据的原始数据</summary>
                      <pre style={{ marginTop: 12, padding: 12, background: "var(--bg-card)", borderRadius: 6, overflow: "auto", maxHeight: 400 }}>
                        {JSON.stringify(reportSnapshot, null, 2)}
                      </pre>
                    </details>
                  )}
                </>
              )}
              {!report && !loading && (
                <p className="right-hint" style={{ padding: 20, textAlign: "center" }}>
                  📌 点击上方按钮，系统将汇总所有学生的提交数据、风险分布和评分情况，生成一份班级分析报告。
                </p>
              )}
            </div>
          )}

          {/* ── 写回反馈 ── */}
          {tab === "feedback" && !loading && (
            <div className="tch-panel fade-up" style={{ maxWidth: "none" }}>
              {(() => {
                const fallbackCatalog = Array.from(
                  new Map(
                    (projectSubmissionHistory || []).map((item: any) => [
                      `${selectedProject || projectId}::${item.logical_project_id || ""}`,
                      {
                        root_project_id: selectedProject || projectId,
                        logical_project_id: item.logical_project_id || "",
                        project_name: item.project_display_name || item.logical_project_id || "未命名项目",
                        student_id: selectedFile?.student_id || "",
                        student_name: selectedFile?.student_id || "",
                        team_name: "当前项目",
                        latest_score: Number(item.overall_score || 0),
                        submission_count: (projectSubmissionHistory || []).filter((row: any) => row.logical_project_id === item.logical_project_id).length,
                        project_phase: item.project_phase || "持续迭代",
                        top_risks: (item.triggered_rules || []).slice(0, 3),
                        summary: item.ai_summary || item.bottleneck || "暂无摘要",
                        feedback_order: item.project_order || 1,
                      },
                    ])
                  ).values()
                );

                const baseCatalog = feedbackProjectCatalog.length > 0 ? feedbackProjectCatalog : fallbackCatalog;
                const feedbackCategoryOptions = ["全部类别", ...Array.from(new Set(baseCatalog.map((item: any) => inferProjectCategory(item))))];
                const catalog = baseCatalog.filter((item: any) => feedbackCategoryFilter === "全部类别" || inferProjectCategory(item) === feedbackCategoryFilter);
                const activeCatalogProject =
                  catalog.find((item: any) => item.root_project_id === selectedProject && item.logical_project_id === selectedLogicalProjectId)
                  || catalog.find((item: any) => item.root_project_id === selectedProject)
                  || baseCatalog.find((item: any) => item.root_project_id === selectedProject)
                  || catalog[0]
                  || baseCatalog[0]
                  || null;
                const activeLogicalProjectId = selectedLogicalProjectId || activeCatalogProject?.logical_project_id || "";
                const activeSubmissionHistory = (projectSubmissionHistory || [])
                  .filter((item: any) => !activeLogicalProjectId || item.logical_project_id === activeLogicalProjectId)
                  .sort((a: any, b: any) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
                const timelinePageSize = 5;
                const timelineTotalPages = Math.max(1, Math.ceil(activeSubmissionHistory.length / timelinePageSize));
                const timelinePage = Math.min(feedbackTimelinePage, timelineTotalPages);
                const pagedSubmissionHistory = activeSubmissionHistory.slice((timelinePage - 1) * timelinePageSize, timelinePage * timelinePageSize);
                const activeHistorySubmission =
                  activeSubmissionHistory.find((item: any) => item.submission_id === selectedHistorySubmissionId)
                  || activeSubmissionHistory[0]
                  || null;
                const visibleFiles = (studentFiles || []).filter((file: any) => !activeLogicalProjectId || file.logical_project_id === activeLogicalProjectId);
                const scopedSelectedFile = selectedFile && (!activeLogicalProjectId || selectedFile.logical_project_id === activeLogicalProjectId)
                  ? selectedFile
                  : visibleFiles[0] || null;
                const aiQuoteCandidates = [
                  ...((scopedSelectedFile?.evidence_quotes || []).map((item: any) => item?.quote || "").filter(Boolean)),
                  ...((assistantAssessment?.logical_project_id === activeLogicalProjectId ? assistantAssessment?.evidence_chain || [] : [])
                    .map((item: any) => item?.quote || "")
                    .filter(Boolean)),
                ].slice(0, 4);
                const annotationItems = flattenAnnotationItems(feedbackAnnotations);
                const selectedSubmissionIndex = activeHistorySubmission
                  ? activeSubmissionHistory.findIndex((item: any) => item.submission_id === activeHistorySubmission.submission_id)
                  : -1;
                const followupSubmissions = selectedSubmissionIndex >= 0 ? activeSubmissionHistory.slice(0, selectedSubmissionIndex) : [];
                const breadcrumbParts = [
                  "材料反馈",
                  activeCatalogProject ? serialLabel("项目", activeCatalogProject.feedback_order || activeCatalogProject.catalog_order || activeCatalogProject.project_order || 1) : "",
                  activeHistorySubmission ? serialLabel("提交", activeHistorySubmission.submission_order || 1) : "",
                  scopedSelectedFile ? (scopedSelectedFile.material_display_name || serialLabel("材料", scopedSelectedFile.material_order)) : "",
                ].filter(Boolean);

                return (
                  <>
                    <div className="feedback-stage-hero" style={{ marginBottom: 20 }}>
                      <div className="feedback-stage-glow" />
                      <div className="feedback-stage-copy">
                        <div className="tm-project-cover-label">Feedback Studio</div>
                        <h2 style={{ marginTop: 6, marginBottom: 6 }}>材料反馈</h2>
                        <p className="tch-desc" style={{ margin: 0 }}>先从最近需要处理的项目流里选对象，再进入大尺寸正文精读区。这里不再做 PDF 在线预览，而是专注于时间线、批注层和跟进记录。</p>
                        <div className="feedback-breadcrumb-strip">
                          {breadcrumbParts.length > 0 ? breadcrumbParts.map((part, idx) => (
                            <span key={`${part}-${idx}`}>{part}</span>
                          )) : <span>先从上方项目流里选择一个项目</span>}
                        </div>
                      </div>
                      <div className="feedback-stage-kpis">
                        <div className="feedback-stage-kpi">
                          <span>项目目录</span>
                          <strong>{catalog.length}</strong>
                        </div>
                        <div className="feedback-stage-kpi">
                          <span>当前项目提交</span>
                          <strong>{activeSubmissionHistory.length}</strong>
                        </div>
                        <div className="feedback-stage-kpi">
                          <span>当前项目</span>
                          <strong>{activeCatalogProject ? serialLabel("项目", activeCatalogProject.feedback_order || activeCatalogProject.catalog_order || activeCatalogProject.project_order || 1) : "未选择"}</strong>
                        </div>
                        <div className="feedback-stage-kpi">
                          <span>历史批注</span>
                          <strong>{annotationItems.length}</strong>
                        </div>
                      </div>
                    </div>

                    <div className="assistant-toolbar" style={{ marginBottom: 12 }}>
                      <input
                        className="tm-input"
                        value={selectedProject || projectId}
                        onChange={(e) => setSelectedProject(e.target.value)}
                        placeholder="输入根项目 ID，例如 project-student-001"
                        style={{ minWidth: 280, flex: "0 1 340px" }}
                      />
                      <button className="topbar-btn" onClick={() => loadFeedbackWorkspace()}>加载材料反馈</button>
                      <button className="tch-sm-btn" onClick={() => selectedProject && loadProjectWorkbench(selectedProject, selectedLogicalProjectId)}>进入项目工作台</button>
                      <button className="tch-sm-btn" onClick={() => selectedProject && loadAssistantAssessment(selectedProject, selectedLogicalProjectId)}>进入批改与溯源</button>
                      <button className="tch-sm-btn" onClick={() => selectedProject && loadAssistantConversationEval(selectedProject, selectedLogicalProjectId)}>查看过程评估</button>
                    </div>

                    <div className="assistant-toolbar" style={{ marginBottom: 8 }}>
                      <span className="assistant-label" style={{ minWidth: 72 }}>排序方式</span>
                      <button className={`tm-chip ${feedbackSortMode === "urgent" ? "tm-chip-active" : ""}`} onClick={() => setFeedbackSortMode("urgent")}>风险优先</button>
                      <button className={`tm-chip ${feedbackSortMode === "activity" ? "tm-chip-active" : ""}`} onClick={() => setFeedbackSortMode("activity")}>提交量优先</button>
                      <button className={`tm-chip ${feedbackSortMode === "score" ? "tm-chip-active" : ""}`} onClick={() => setFeedbackSortMode("score")}>低分优先</button>
                    </div>

                    <div className="assistant-toolbar" style={{ marginBottom: 18 }}>
                      <span className="assistant-label" style={{ minWidth: 72 }}>项目类别</span>
                      {feedbackCategoryOptions.map((item: string) => (
                        <button
                          key={item}
                          className={`tm-chip ${feedbackCategoryFilter === item ? "tm-chip-active" : ""}`}
                          onClick={() => setFeedbackCategoryFilter(item)}
                        >
                          {item}
                        </button>
                      ))}
                    </div>

                    <div className="feedback-flow-strip">
                      <button className={`feedback-flow-step ${feedbackWorkspaceView === "queue" ? "active" : ""}`} onClick={() => setFeedbackWorkspaceView("queue")}>
                        <span>1</span>
                        <div>
                          <strong>选项目</strong>
                          <em>先确定今天要批改哪个学生项目</em>
                        </div>
                      </button>
                      <button className={`feedback-flow-step ${feedbackWorkspaceView === "timeline" ? "active" : ""}`} onClick={() => activeCatalogProject && setFeedbackWorkspaceView("timeline")}>
                        <span>2</span>
                        <div>
                          <strong>提交时间线</strong>
                          <em>分页查看当前项目历次提交</em>
                        </div>
                      </button>
                      <button className={`feedback-flow-step ${feedbackWorkspaceView === "reader" ? "active" : ""}`} onClick={() => scopedSelectedFile && setFeedbackWorkspaceView("reader")}>
                        <span>3</span>
                        <div>
                          <strong>精读批注</strong>
                          <em>在学生原文上看 AI 划线并继续批注</em>
                        </div>
                      </button>
                      <button className={`feedback-flow-step ${feedbackWorkspaceView === "history" ? "active" : ""}`} onClick={() => setFeedbackWorkspaceView("history")}>
                        <span>4</span>
                        <div>
                          <strong>历史跟进</strong>
                          <em>回看批注、反馈文件和后续修改</em>
                        </div>
                      </button>
                    </div>

                    {catalog.length === 0 && !selectedProject ? (
                      <div className="feedback-empty-state">
                        <strong>还没有可进入批改的项目</strong>
                        <p>先在“团队”完成项目观察，或直接输入根项目 ID 加载。这里会按项目维度汇总全部提交，再进入材料精读。</p>
                      </div>
                    ) : (
                      <div className="feedback-shell">
                        {(feedbackWorkspaceView === "queue" || feedbackWorkspaceView === "timeline" || feedbackWorkspaceView === "reader") && (
                        <div className="feedback-main">
                          {feedbackWorkspaceView === "queue" && (
                          <div className="assistant-section">
                            <div className="assistant-section-title">时间排序项目流</div>
                            <div className="feedback-intake-river">
                              {catalog.map((group: any) => {
                                const isActive = activeCatalogProject?.root_project_id === group.root_project_id && activeLogicalProjectId === group.logical_project_id;
                                const category = inferProjectCategory(group);
                                return (
                                  <button
                                    key={`${group.root_project_id}-${group.logical_project_id}`}
                                    className={`feedback-project-card ${isActive ? "active" : ""}`}
                                    onClick={() => loadFeedbackWorkspace(group.root_project_id, group.logical_project_id)}
                                  >
                                    <div className="feedback-project-top">
                                      <span className="feedback-project-index">{serialLabel("项目", group.feedback_order || group.catalog_order || group.project_order || 1)}</span>
                                      <span className="tm-case-badge">{group.submission_count || 0} 次提交</span>
                                    </div>
                                    <strong>{group.project_name || group.project_display_name}</strong>
                                    <div className="tm-case-meta">
                                      <span>{group.student_name || group.student_id}</span>
                                      <span>{group.team_name || "当前项目"}</span>
                                      <span>{group.project_phase || "持续迭代"}</span>
                                      <span>最新分 {Number(group.latest_score || 0).toFixed(1)}</span>
                                    </div>
                                    <div className="tm-case-inline-summary" style={{ marginTop: 8 }}>{group.summary || "暂无摘要"}</div>
                                    <div className="tm-corridor-tags" style={{ marginTop: 10 }}>
                                      <span className="tm-smart-chip">{category}</span>
                                      {(group.top_risks || []).slice(0, 3).map((risk: string) => (
                                        <span key={risk} className="tm-smart-chip">{getRuleDisplayName(risk)}</span>
                                      ))}
                                    </div>
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                          )}

                          {feedbackWorkspaceView === "timeline" && (
                          <div className="assistant-section feedback-wide-stage">
                            <div className="assistant-section-title">该项目全部提交</div>
                            {activeCatalogProject ? (
                              <>
                                <div className="feedback-timeline-head">
                                  <div className="tch-desc" style={{ margin: 0 }}>当前项目共 {activeSubmissionHistory.length} 次提交，本页显示第 {timelinePage} / {timelineTotalPages} 页。</div>
                                  {timelineTotalPages > 1 && (
                                    <div className="feedback-pagination">
                                      <button className="tch-sm-btn" onClick={() => setFeedbackTimelinePage((value) => Math.max(1, value - 1))} disabled={timelinePage <= 1}>上一页</button>
                                      <span>第 {timelinePage} 页</span>
                                      <button className="tch-sm-btn" onClick={() => setFeedbackTimelinePage((value) => Math.min(timelineTotalPages, value + 1))} disabled={timelinePage >= timelineTotalPages}>下一页</button>
                                    </div>
                                  )}
                                </div>
                                <div className="feedback-history-strip">
                                  {pagedSubmissionHistory.map((submission: any) => {
                                    const score = Number(submission.overall_score || 0);
                                    const scoreColor = score >= 7 ? "var(--tch-success)" : score >= 5 ? "var(--tch-warning)" : "var(--tch-danger)";
                                    return (
                                      <button
                                        key={submission.submission_id}
                                        className={`feedback-history-card ${activeHistorySubmission?.submission_id === submission.submission_id ? "active" : ""}`}
                                        onClick={() => setSelectedHistorySubmissionId(submission.submission_id)}
                                      >
                                        <div className="feedback-file-top">
                                          <span className="feedback-file-index">{serialLabel("提交", submission.submission_order || 1)}</span>
                                          <span className="submission-score-pill" style={{ color: scoreColor, borderColor: `${scoreColor}55` }}>{score.toFixed(1)}</span>
                                        </div>
                                        <strong>{submission.filename || `${submission.source_type || "text"} 提交`}</strong>
                                        <div className="tm-case-meta">
                                          <span>{submission.project_phase || "持续迭代"}</span>
                                          <span>{formatBJTime(submission.created_at)}</span>
                                          <span>{submission.source_type || "text"}</span>
                                        </div>
                                        <div className="tm-case-inline-summary" style={{ marginTop: 10 }}>
                                          {submission.ai_summary || submission.bottleneck || submission.text_preview || "查看本次提交的摘要和证据。"}
                                        </div>
                                        <div className="tm-corridor-tags" style={{ marginTop: 10 }}>
                                          {(submission.triggered_rules || []).slice(0, 3).map((risk: string) => <span key={risk} className="tm-smart-chip">{getRuleDisplayName(risk)}</span>)}
                                        </div>
                                      </button>
                                    );
                                  })}
                                </div>
                                {activeHistorySubmission && (
                                  <div className="feedback-history-focus">
                                    <div className="feedback-history-focus-head">
                                      <div>
                                        <div className="tm-project-cover-label">Submission Focus</div>
                                        <h3 style={{ marginTop: 6, marginBottom: 6 }}>{activeHistorySubmission.filename || `${activeHistorySubmission.source_type || "text"} 提交`}</h3>
                                        <div className="tm-case-meta">
                                          <span>{activeHistorySubmission.project_display_name || activeCatalogProject.project_name}</span>
                                          <span>{formatBJTime(activeHistorySubmission.created_at)}</span>
                                          <span>{activeHistorySubmission.project_phase || "持续迭代"}</span>
                                        </div>
                                      </div>
                                      <div className="assistant-toolbar" style={{ justifyContent: "flex-end" }}>
                                        <button
                                          className="topbar-btn"
                                          onClick={() => {
                                            setFeedbackActionView("annotate");
                                            setFeedbackWorkspaceView("reader");
                                            openFeedbackSubmission(activeHistorySubmission, selectedProject || activeCatalogProject.root_project_id);
                                          }}
                                        >
                                          进入精读批注
                                        </button>
                                      </div>
                                    </div>
                                    <div className="feedback-history-focus-grid">
                                      <div className="feedback-history-focus-card">
                                        <div className="assistant-section-title">AI 摘要</div>
                                        <p>{activeHistorySubmission.ai_summary || activeHistorySubmission.bottleneck || "暂无 AI 摘要"}</p>
                                      </div>
                                      <div className="feedback-history-focus-card">
                                        <div className="assistant-section-title">风险与 Agent</div>
                                        <div className="tm-corridor-tags" style={{ marginTop: 8 }}>
                                          {(activeHistorySubmission.triggered_rules || []).slice(0, 3).map((risk: string) => <span key={risk} className="tm-smart-chip">{getRuleDisplayName(risk)}</span>)}
                                          {(activeHistorySubmission.agent_trace_meta?.agents_called || []).slice(0, 2).map((agent: string) => <span key={agent} className="tm-smart-chip">{agent}</span>)}
                                        </div>
                                      </div>
                                      <div className="feedback-history-focus-card full">
                                        <div className="assistant-section-title">提交内容摘录</div>
                                        <p style={{ whiteSpace: "pre-wrap" }}>{activeHistorySubmission.full_text || activeHistorySubmission.text_preview || "该次提交暂无文本内容。"}</p>
                                      </div>
                                    </div>
                                  </div>
                                )}
                              </>
                            ) : (
                              <div className="feedback-reader-empty">先从上方项目目录中选择一个项目。</div>
                            )}
                          </div>
                          )}

                          {feedbackWorkspaceView === "reader" && (
                          <div className="assistant-section">
                            <div className="assistant-section-title">全屏精读批注区</div>
                            {!scopedSelectedFile ? (
                              <div className="feedback-reader-empty">
                                先从上方“材料走廊”中选择一份材料，再进入精读、批注和反馈。
                              </div>
                            ) : (
                              <div className="feedback-reader-card">
                                <div className="feedback-reader-head">
                                  <div>
                                    <div className="tm-project-cover-label">{scopedSelectedFile.project_display_name || serialLabel("项目", scopedSelectedFile.project_order)}</div>
                                    <h3 style={{ marginTop: 6, marginBottom: 6 }}>{scopedSelectedFile.material_display_name || serialLabel("材料", scopedSelectedFile.material_order)} · {scopedSelectedFile.filename}</h3>
                                    <div className="tm-case-meta">
                                      <span>{compactId(scopedSelectedFile.logical_project_id || "")}</span>
                                      <span>{scopedSelectedFile.student_id}</span>
                                      <span>{scopedSelectedFile.project_phase || "持续迭代"}</span>
                                      <span>{formatBJTime(scopedSelectedFile.created_at)}</span>
                                    </div>
                                  </div>
                                  <div className="assistant-toolbar" style={{ justifyContent: "flex-end" }}>
                                    <button className="tch-sm-btn" onClick={() => setIsEditMode(!isEditMode)}>{isEditMode ? "退出编辑" : "进入编辑"}</button>
                                    {isEditMode && editedContent !== fileContent && <button className="tch-sm-btn" onClick={() => setEditedContent(fileContent)}>撤销修改</button>}
                                    {isEditMode && editedContent !== fileContent && <button className="topbar-btn" onClick={saveEditedDocument}>保存改稿</button>}
                                    {!isEditMode && scopedSelectedFile.download_url && (
                                      <a className="tch-sm-btn" href={`${API}${scopedSelectedFile.download_url}`} target="_blank" rel="noreferrer">下载原文件</a>
                                    )}
                                    {!isEditMode && editedContent && editedContent !== fileContent && <button className="tch-sm-btn" onClick={() => exportDocument("txt")}>导出文本</button>}
                                  </div>
                                </div>

                                {isEditMode && (
                                  <input
                                    className="tm-input"
                                    value={editSummary}
                                    onChange={(e) => setEditSummary(e.target.value)}
                                    placeholder="填写本次改稿摘要，例如：补充市场证据、修正逻辑表达"
                                    style={{ marginBottom: 12 }}
                                  />
                                )}

                                {!isEditMode && (
                                  <div className="assistant-note-list feedback-summary-ribbon" style={{ marginBottom: 12 }}>
                                    <div className="tm-note-row good">AI 总结：{selectedFile?.kg_analysis?.insight || selectedFile?.diagnosis?.bottleneck || "暂无总结"}</div>
                                    {selectedFile?.next_task?.title && <div className="tm-note-row warn">下一步任务：{selectedFile.next_task.title}</div>}
                                  </div>
                                )}

                                <div className="feedback-reader-layout">
                                  <div className="feedback-reader-main-column">
                                    {isEditMode ? (
                                      <textarea
                                        value={editedContent}
                                        onChange={(e) => setEditedContent(e.target.value)}
                                        className="feedback-editor-textarea"
                                      />
                                    ) : (
                                      <div className="feedback-reading-stage">
                                        <div className="feedback-reading-canvas">
                                          {renderAnnotatedDocument(fileContent, feedbackAnnotations, feedbackAiSuggestions)}
                                        </div>
                                      </div>
                                    )}

                                    {documentEdits.length > 0 && !isEditMode && (
                                      <div className="assistant-note-list" style={{ marginTop: 14 }}>
                                        {documentEdits.slice(0, 5).map((edit, idx) => (
                                          <div key={idx} className="tm-note-row good">
                                            {edit.edit_summary || "文档编辑"} · {edit.edited_length || 0} 字符 · {formatBJTime(edit.created_at)}
                                          </div>
                                        ))}
                                      </div>
                                    )}
                                  </div>

                                  <aside className="feedback-reader-side-column">
                                    <div className="feedback-workbench-card">
                                      <div className="feedback-workbench-head">
                                        <div className="assistant-section-title" style={{ marginBottom: 0 }}>批注与反馈工作台</div>
                                        <div className="tch-desc" style={{ margin: 0 }}>左侧看原文与 AI 划线，右侧继续写反馈、保存批注或上传老师反馈文件。</div>
                                      </div>
                                      <div className="feedback-action-tabs">
                                        <button className={`feedback-action-tab ${feedbackActionView === "write" ? "active" : ""}`} onClick={() => setFeedbackActionView("write")}>写反馈</button>
                                        <button className={`feedback-action-tab ${feedbackActionView === "annotate" ? "active" : ""}`} onClick={() => setFeedbackActionView("annotate")}>划线批注</button>
                                        <button className={`feedback-action-tab ${feedbackActionView === "upload" ? "active" : ""}`} onClick={() => setFeedbackActionView("upload")}>上传文件</button>
                                      </div>
                                      {feedbackActionView === "write" && (
                                        <div className="feedback-action-panel">
                                          <label className="assistant-label">快速反馈模板</label>
                                          <div className="feedback-template-row">
                                            {["先补充关键证据链。", "把方案和用户场景一一对应。", "把结论改成可验证的数据表达。"] .map((item) => (
                                              <button key={item} className="tm-chip" onClick={() => setFeedbackText((value) => `${value}${value ? "\n" : ""}${item}`)}>{item}</button>
                                            ))}
                                          </div>
                                          <label className="assistant-label">总体反馈</label>
                                          <textarea
                                            className="tm-input assistant-textarea"
                                            value={feedbackText}
                                            onChange={(e) => setFeedbackText(e.target.value)}
                                            placeholder="这里写老师真正要发给学生的总体反馈，例如：先肯定亮点，再指出关键问题，最后给出下一轮修改要求。"
                                          />
                                          <label className="assistant-label">关注标签</label>
                                          <input
                                            className="tm-input"
                                            value={feedbackTags}
                                            onChange={(e) => setFeedbackTags(e.target.value)}
                                            placeholder="evidence,business_model,expression"
                                          />
                                          <div className="feedback-preview-card">
                                            <div className="assistant-section-title">发送预览</div>
                                            <p>{feedbackText.trim() || "你写的总体反馈会显示在这里，方便确认语气和结构。"}</p>
                                          </div>
                                          <button className="tch-primary-btn tch-success-btn" onClick={submitFeedback}>提交文本反馈</button>
                                        </div>
                                      )}

                                      {feedbackActionView === "annotate" && (
                                        <div className="feedback-action-panel">
                                          <label className="assistant-label">AI 精读候选批注</label>
                                          <div className="assistant-note-list" style={{ marginTop: 8 }}>
                                            {feedbackAiLoading ? (
                                              <div className="tm-note-row good">AI 正在精读正文并生成批注候选...</div>
                                            ) : feedbackAiSuggestions.length > 0 ? feedbackAiSuggestions.map((item: any, idx: number) => (
                                              <button
                                                key={item.annotation_id || `${item.quote}-${idx}`}
                                                className="tm-note-row good"
                                                style={{ textAlign: "left", width: "100%" }}
                                                onClick={() => {
                                                  setAnnotationType(item.annotation_type || "issue");
                                                  setAnnotationText(item.content || "");
                                                  setAnnotationAnchorText(item.quote || "");
                                                  const source = extractValidContent(editedContent || fileContent || "");
                                                  const index = item.quote ? source.indexOf(item.quote) : Number(item.position || 0);
                                                  setAnnotationAnchorPosition(index >= 0 ? index : Number(item.position || 0));
                                                }}
                                              >
                                                <strong>{annotationTone(item.annotation_type || "issue").label}</strong>
                                                <div style={{ marginTop: 6, color: "var(--text-primary)" }}>{item.content || "AI 认为这里值得老师重点查看。"}</div>
                                                <div style={{ marginTop: 8, opacity: 0.82 }}>“{item.quote}”</div>
                                              </button>
                                            )) : aiQuoteCandidates.length > 0 ? aiQuoteCandidates.map((quote: string, idx: number) => (
                                              <button
                                                key={`${quote}-${idx}`}
                                                className="tm-note-row good"
                                                style={{ textAlign: "left", width: "100%" }}
                                                onClick={() => {
                                                  setAnnotationAnchorText(quote);
                                                  const source = extractValidContent(editedContent || fileContent || "");
                                                  const index = source.indexOf(quote);
                                                  setAnnotationAnchorPosition(index >= 0 ? index : 0);
                                                }}
                                              >
                                                “{quote}”
                                              </button>
                                            )) : <div className="tm-note-row good">暂无 AI 批注候选，可在左侧正文中选中一句话后再回来。</div>}
                                          </div>
                                          <div className="assistant-toolbar" style={{ marginTop: 10 }}>
                                            <button className="tch-sm-btn" onClick={captureAnnotationAnchor}>使用当前选中文本</button>
                                            {annotationAnchorText && <button className="tch-sm-btn" onClick={() => { setAnnotationAnchorText(""); setAnnotationAnchorPosition(0); }}>清除锚点</button>}
                                          </div>
                                          <div className="feedback-preview-card">
                                            <div className="assistant-section-title">划线预览</div>
                                            {renderHighlightPreview(editedContent || fileContent, annotationAnchorText)}
                                          </div>
                                          <div className="feedback-tag-picker">
                                            {[
                                              { id: "praise", label: "亮点" },
                                              { id: "issue", label: "问题" },
                                              { id: "suggest", label: "建议" },
                                              { id: "question", label: "追问" },
                                            ].map((item) => (
                                              <button
                                                key={item.id}
                                                className={`feedback-tag-pill ${annotationType === item.id ? "active" : ""}`}
                                                onClick={() => setAnnotationType(item.id)}
                                              >
                                                {item.label}
                                              </button>
                                            ))}
                                          </div>
                                          <select className="tm-input" value={annotationType} onChange={(e) => setAnnotationType(e.target.value)} style={{ marginBottom: 8 }}>
                                            <option value="praise">亮点</option>
                                            <option value="issue">问题</option>
                                            <option value="suggest">建议</option>
                                            <option value="question">追问</option>
                                          </select>
                                          <textarea
                                            className="tm-input assistant-textarea small"
                                            value={annotationText}
                                            onChange={(e) => setAnnotationText(e.target.value)}
                                            placeholder="解释这段为什么要改、改什么、下一轮应补什么。"
                                          />
                                          <button className="tch-primary-btn" onClick={saveAnnotation}>保存批注</button>
                                        </div>
                                      )}

                                      {feedbackActionView === "upload" && (
                                        <div className="feedback-action-panel">
                                          <label className="assistant-label">上传反馈文件</label>
                                          <input
                                            ref={feedbackFileInputRef}
                                            type="file"
                                            accept=".pdf,.docx,.pptx,.txt"
                                            onChange={(e) => setFeedbackFileToUpload(e.target.files?.[0] || null)}
                                            style={{ width: "100%", marginBottom: 8 }}
                                          />
                                          {feedbackFileToUpload && <div className="tm-note-row good" style={{ marginBottom: 10 }}>已选择：{feedbackFileToUpload.name}</div>}
                                          <div className="feedback-preview-card">
                                            <div className="assistant-section-title">上传说明</div>
                                            <p>适合上传老师改好的版本、批注稿或要求学生下载回看的反馈附件。</p>
                                          </div>
                                          <button className="tch-primary-btn" onClick={uploadFeedbackFile} disabled={!feedbackFileToUpload}>上传反馈文件</button>
                                        </div>
                                      )}
                                    </div>
                                  </aside>
                                </div>
                              </div>
                            )}
                          </div>
                          )}
                        </div>
                        )}

                        {feedbackWorkspaceView === "history" && (
                          <div className="feedback-main">
                            {feedbackFiles.length > 0 && (
                              <div className="assistant-section">
                                <div className="assistant-section-title">已上传反馈文件</div>
                                <div className="assistant-note-list">
                                  {feedbackFiles.map((file, idx) => (
                                    <div key={idx} className="tm-note-row good">
                                      {file.original_filename} · <a href={`${API}${file.file_url}`} target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>下载</a>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                            {feedbackAnnotations.length > 0 && (
                              <div className="assistant-section">
                                <div className="assistant-section-title">历史批注</div>
                                <div className="assistant-note-list">
                                  {annotationItems.map((ann, idx) => {
                                    const tone = annotationTone(ann.annotation_type);
                                    return (
                                      <div key={`${ann.annotation_id}-${idx}`} className="feedback-history-note" style={{ borderColor: tone.border, background: tone.bg }}>
                                        <strong style={{ color: tone.text }}>{tone.label}</strong>
                                        <p>{ann.quote ? `“${ann.quote}”` : "段落批注"}</p>
                                        <span>{ann.content || ann.overall_feedback || "已保存批注"} · {formatBJTime(ann.created_at)}</span>
                                      </div>
                                    );
                                  })}
                                </div>
                              </div>
                            )}
                            {followupSubmissions.length > 0 && (
                              <div className="assistant-section">
                                <div className="assistant-section-title">学生后续修改</div>
                                <div className="assistant-note-list">
                                  {followupSubmissions.slice(0, 4).map((item: any) => (
                                    <button
                                      key={item.submission_id}
                                      className="feedback-followup-card"
                                      onClick={() => openFeedbackSubmission(item, selectedProject || activeCatalogProject?.root_project_id)}
                                    >
                                      <strong>{serialLabel("提交", item.submission_order || 1)} · {formatBJTime(item.created_at)}</strong>
                                      <span>{item.project_phase || "持续迭代"}</span>
                                      <p>{item.ai_summary || item.bottleneck || item.text_preview || "查看该次后续提交"}</p>
                                    </button>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </>
                );
              })()}
              
              {successMessage && <SuccessToast message={successMessage} onClose={() => setSuccessMessage("")} />}
              {errorMessage && <ErrorToast message={errorMessage} onClose={() => setErrorMessage("")} />}
            </div>
          )}

          {/* ── 能力映射雷达图 ── */}
          {tab === "capability" && !loading && (
            <div className="tch-panel fade-up">
              <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
                <button onClick={() => setTab("class")} className="tch-back-btn">← 返回班级</button>
              </div>
              <h2>🎯 班级能力映射</h2>
              <p className="tch-desc">基于5个维度（痛点发现、方案策划、商业建模、资源杠杆、路演表达）评估班级整体能力水平。雷达图越接近外圆表示能力越强。</p>
              {!capabilityMap?.dimensions ? (
                <SkeletonLoader rows={3} type="bar" />
              ) : (
                <>
                  <div className="viz-grid" style={{ animation: "fade-in 0.4s ease-out" }}>
                    <div className="viz-card">
                      <h3>📊 班级能力分布（满分10）</h3>
                      <p className="tch-desc">班级平均成绩</p>
                      {(capabilityMap.dimensions ?? []).length === 0 ? (
                        <p style={{ color: "var(--text-muted)", fontSize: 12 }}>暂无维度数据</p>
                      ) : (
                        (capabilityMap.dimensions ?? []).map((dim: any, idx: number) => (
                          <div 
                            key={dim.name} 
                            className="bar-row"
                            style={{
                              animation: `fade-in 0.3s ease-out ${idx * 0.08}s both`,
                              transition: "all 0.2s ease",
                            }}
                          >
                            <span>{dim.name}</span>
                            <div className="bar-track">
                              <div 
                                className="bar-fill" 
                                style={{ width: `${(dim.score / dim.max) * 100}%`, transition: "width 0.4s ease" }} 
                              />
                            </div>
                            <em style={{ fontWeight: "600", color: dim.score >= 7 ? "var(--tch-success)" : dim.score >= 5 ? "var(--tch-warning)" : "var(--tch-danger)" }}>
                              {dim.score.toFixed(1)}
                            </em>
                          </div>
                        ))
                      )}
                    </div>
                    <div className="viz-card" style={{ animation: "fade-in 0.5s ease-out" }}>
                      <h3>🔍 维度强弱对比</h3>
                      <p className="tch-desc">找出班级的短板（得分最低的维度）并重点补强</p>
                      {(() => {
                        const sorted = [...(capabilityMap.dimensions ?? [])].sort((a, b) => a.score - b.score);
                        return sorted.length === 0 ? (
                          <p style={{ color: "var(--text-muted)", fontSize: 12 }}>暂无数据</p>
                        ) : (
                          <div>
                            {sorted.slice(0, 3).map((dim: any, i: number) => (
                              <div 
                                key={dim.name} 
                                className="bar-row"
                                style={{
                                  animation: `fade-in 0.3s ease-out ${i * 0.1}s both`,
                                  padding: "8px 12px",
                                  background: i === 0 ? "var(--tch-danger-soft)" : i === 1 ? "var(--tch-warning-soft)" : "var(--tch-success-soft)",
                                  borderRadius: 4,
                                  marginBottom: 8
                                }}
                              >
                                <span>{i === 0 ? "🔴 最弱" : i === 1 ? "🟡 较弱" : "🟢 需强化"}</span>
                                <span style={{ fontWeight: "600", flex: 1 }}>{dim.name}</span>
                                <strong style={{ color: i === 0 ? "var(--tch-danger)" : i === 1 ? "var(--tch-warning)" : "var(--tch-success)" }}>
                                  {dim.score.toFixed(1)}
                                </strong>
                              </div>
                            ))}
                          </div>
                        );
                      })()}
                    </div>
                  </div>
                </>
              )}
              {!capabilityMap && <p className="right-hint" style={{ padding: 20, textAlign: "center" }}>加载中或暂无数据...请确保班级已有学生提交。</p>}
            </div>
          )}

          {/* ── 规则检查热力图 ── */}
          {tab === "rule-coverage" && !loading && (
            <div className="tch-panel fade-up">
              <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
                <button onClick={() => setTab("class")} className="tch-back-btn">← 返回班级</button>
              </div>
              <h2>🔥 规则检查覆盖率</h2>
              <p className="tch-desc">15条关键业务规则（H1-H15）的触发统计。热力图显示哪些规则在班级中最常被触发，即班级共性风险点。</p>
              {!ruleCoverage?.rule_coverage ? (
                <SkeletonLoader rows={5} type="table" />
              ) : (
                <>
                  <div style={{ marginBottom: 16, padding: 12, background: "var(--bg-card)", borderRadius: 8, animation: "fade-in 0.3s ease-out" }}>
                    <strong>⚠️ 高危规则：</strong>
                    <span style={{ fontSize: 18, fontWeight: "bold", color: "var(--tch-danger)", marginLeft: 8 }}>
                      {ruleCoverage.high_risk_count}
                    </span>
                    <span style={{ marginLeft: 16 }}> | </span>
                    <strong style={{ marginLeft: 16 }}>📊 总提交数：</strong>
                    <span style={{ fontSize: 18, fontWeight: "bold", color: "var(--accent)", marginLeft: 8 }}>
                      {ruleCoverage.total_submissions}
                    </span>
                  </div>
                  <div className="tch-table" style={{ animation: "fade-in 0.4s ease-out" }}>
                    <div className="tch-table-header">
                      <span>规则ID</span><span>规则名称</span><span>触发次数</span><span>覆盖率</span><span>风险等级</span>
                    </div>
                    {ruleCoverage.rule_coverage.length === 0 ? (
                      <p style={{ color: "var(--text-muted)", fontSize: 12, padding: 20 }}>暂无规则覆盖率数据</p>
                    ) : (
                      ruleCoverage.rule_coverage.map((rule: any, idx: number) => (
                        <div 
                          key={rule.rule_id} 
                          className="tch-table-row"
                          style={{
                            animation: `fade-in 0.3s ease-out ${idx * 0.05}s both`,
                            backgroundColor: rule.severity === "high" ? "var(--tch-danger-soft)" : rule.severity === "medium" ? "var(--tch-warning-soft)" : "var(--bg-card)",
                            transition: "all 0.2s ease",
                          }}
                        >
                          <span className="tch-cell-time" style={{ fontWeight: "bold" }}>{rule.rule_id}</span>
                          <span>{rule.rule_name}</span>
                          <span style={{ fontWeight: "600" }}>{rule.hit_count}</span>
                          <span>
                            <div className="bar-track" style={{ width: 100, height: 20, display: "inline-block", marginRight: 8 }}>
                              <div 
                                className="bar-fill" 
                                style={{ 
                                  width: `${(rule.coverage_ratio * 100)}%`, 
                                  height: "100%",
                                  backgroundColor: rule.severity === "high" ? "var(--tch-danger)" : rule.severity === "medium" ? "var(--tch-warning)" : "var(--tch-success)"
                                }} 
                              />
                            </div>
                            {(rule.coverage_ratio * 100).toFixed(1)}%
                          </span>
                          <span className={rule.severity === "high" ? "risk-badge high" : rule.severity === "medium" ? "risk-badge" : "risk-badge low"}>
                            {rule.severity === "high" ? "🔴 高" : rule.severity === "medium" ? "🟡 中" : "🟢 低"}
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                </>
              )}
              {!ruleCoverage && <p className="right-hint" style={{ padding: 20, textAlign: "center" }}>加载中或暂无数据...</p>}
            </div>
          )}

          {/* ── Rubric 评分与项目诊断 ── */}
          {tab === "rubric" && !loading && (
            <div className="tch-panel fade-up">
              <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
                <button onClick={() => setTab("project")} className="tch-back-btn">← 返回项目</button>
              </div>
              <h2>📋 Rubric评分与项目诊断</h2>
              <p className="tch-desc">针对单个项目的深度评估，包括9个维度（R1-R9）的Rubric评分，触发的规则及修复建议。</p>
              <div style={{ marginBottom: 16, display: "flex", gap: 8 }}>
                <input 
                  value={selectedProject || projectId} 
                  onChange={(e) => setSelectedProject(e.target.value)} 
                  placeholder="项目ID"
                  style={{ marginRight: 0, flex: 1 }}
                />
                <button className="topbar-btn" onClick={loadRubricAssessment}>加载评分</button>
              </div>

              {!rubricAssessment?.rubric_items ? (
                <SkeletonLoader rows={3} type="table" />
              ) : (
                <div style={{ animation: "fade-in 0.4s ease-out" }}>
                  <div className="kpi-grid">
                    <div className="kpi">
                      <span>⭐ 加权总分</span>
                      <strong style={{ fontSize: 32, color: "var(--tch-warning)" }}>
                        {rubricAssessment.overall_weighted_score}
                      </strong>
                      <em>满分5分</em>
                    </div>
                  </div>

                  <h3 style={{ marginTop: 24, marginBottom: 12 }}>各维度评分详情</h3>
                  <div className="tch-table" style={{ animation: "fade-in 0.5s ease-out" }}>
                    <div className="tch-table-header">
                      <span>维度</span><span>得分</span><span>权重</span><span>修改建议</span>
                    </div>
                    {rubricAssessment.rubric_items.length === 0 ? (
                      <p style={{ color: "var(--text-muted)", fontSize: 12, padding: 20 }}>暂无评分数据</p>
                    ) : (
                      rubricAssessment.rubric_items.map((item: any, idx: number) => (
                        <div 
                          key={item.item_id} 
                          className="tch-table-row"
                          style={{
                            animation: `fade-in 0.3s ease-out ${idx * 0.05}s both`,
                            backgroundColor: Number(item.score) >= item.max_score * 0.7 ? "var(--tch-success-soft)" : 
                                           Number(item.score) >= item.max_score * 0.5 ? "var(--tch-warning-soft)" : "var(--tch-danger-soft)",
                            transition: "all 0.2s ease",
                          }}
                        >
                          <span><strong>{item.item_id}</strong> {item.item_name}</span>
                          <span style={{ fontWeight: "600", color: Number(item.score) >= item.max_score * 0.7 ? "var(--tch-success)" : "var(--tch-warning)" }}>
                            {item.score}/{item.max_score}
                          </span>
                          <span>{(item.weight * 100).toFixed(0)}%</span>
                          <span style={{ fontSize: "0.9em", color: "var(--text-secondary)" }}>{item.revision_suggestion}</span>
                        </div>
                      ))
                    )}
                  </div>

                  {projectDiagnosis?.fix_strategies && projectDiagnosis.fix_strategies.length > 0 && (
                    <>
                      <h3 style={{ marginTop: 24, marginBottom: 12 }}>🔧 关键风险修复方案</h3>
                      {projectDiagnosis.fix_strategies.map((fix: any, idx: number) => (
                        <div 
                          key={fix.rule_id} 
                          className="right-tag" 
                          style={{ 
                            marginBottom: 8,
                            animation: `fade-in 0.3s ease-out ${idx * 0.08}s both`,
                            transition: "all 0.2s ease"
                          }}
                        >
                          <strong>{fix.rule_id}</strong> {fix.rule_name} → {fix.fix_strategy}
                        </div>
                      ))}
                    </>
                  )}
                </div>
              )}
              {!rubricAssessment && <p className="right-hint" style={{ padding: 20, textAlign: "center" }}>📌 选择项目后点击"加载评分"获取详细评估...</p>}
            </div>
          )}

          {/* ── 竞赛评分预测 ── */}
          {tab === "competition" && !loading && (
            <div className="tch-panel fade-up">
              <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
                <button onClick={() => setTab("project")} className="tch-back-btn">← 返回项目</button>
              </div>
              <h2>🏆 竞赛评分预测</h2>
              <p className="tch-desc">基于项目当前状态预测在竞赛中的得分（0-100分），并给出24小时和72小时的快速修复清单。</p>
              <div style={{ marginBottom: 16, display: "flex", gap: 8 }}>
                <input 
                  value={selectedProject || projectId} 
                  onChange={(e) => setSelectedProject(e.target.value)} 
                  placeholder="项目ID"
                  style={{ marginRight: 0, flex: 1 }}
                />
                <button className="topbar-btn" onClick={loadCompetitionScore}>预测评分</button>
              </div>

              {!competitionScore ? (
                <SkeletonLoader rows={2} type="card" />
              ) : competitionScore?.predicted_competition_score !== undefined ? (
                <div style={{ animation: "fade-in 0.4s ease-out" }}>
                  <div className="kpi-grid">
                    <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                      <span>🎯 预测竞赛评分</span>
                      <strong 
                        style={{ 
                          fontSize: 40, 
                          color: competitionScore.predicted_competition_score >= 75 ? "var(--tch-success)" : 
                                 competitionScore.predicted_competition_score >= 60 ? "var(--tch-warning)" : "var(--tch-danger)",
                          animation: "number-scale 0.6s ease-out"
                        }}
                      >
                        {competitionScore.predicted_competition_score}
                      </strong>
                      <em>
                        预测范围：
                        {typeof competitionScore.score_range === 'string' 
                          ? competitionScore.score_range 
                          : `${competitionScore.score_range_min || competitionScore.score_range?.[0]}-${competitionScore.score_range_max || competitionScore.score_range?.[1]}`}
                        分
                      </em>
                      <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 8 }}>
                        <strong>📌 评分说明：</strong>基于项目诊断评分、触发规则数量等因素综合计算。
                      </p>
                    </div>
                  </div>

                  <h3 style={{ marginTop: 24, marginBottom: 12, fontSize: 18 }}>⚡ 24小时快速修复（最关键的3项）</h3>
                  <ul style={{ paddingLeft: 20, lineHeight: 2, background: "var(--tch-accent-soft)", padding: 16, borderRadius: 8, borderLeft: "3px solid var(--accent)" }}>
                    {(competitionScore.quick_fixes_24h ?? []).map((fix: string, i: number) => (
                      <li key={i} style={{ animation: `fade-in 0.3s ease-out ${i * 0.1}s both` }}>✓ {fix}</li>
                    ))}
                  </ul>

                  <h3 style={{ marginTop: 24, marginBottom: 12, fontSize: 18 }}>📋 72小时完整改进方案</h3>
                  <ul style={{ paddingLeft: 20, lineHeight: 2, background: "var(--bg-card)", padding: 16, borderRadius: 8, borderLeft: "3px solid var(--text-muted)" }}>
                    {(competitionScore.quick_fixes_72h ?? []).map((fix: string, i: number) => (
                      <li key={i} style={{ animation: `fade-in 0.3s ease-out ${i * 0.1}s both` }}>→ {fix}</li>
                    ))}
                  </ul>

                  {competitionScore.high_risk_rules_for_competition?.length > 0 && (
                    <>
                      <h3 style={{ marginTop: 24, marginBottom: 12, fontSize: 18 }}>🔴 竞赛评审关注的高风险规则</h3>
                      <div style={{ 
                        display: "grid", 
                        gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                        gap: 12,
                        padding: "12px",
                        background: "var(--tch-danger-soft)",
                        borderRadius: "10px",
                        borderLeft: "3px solid var(--tch-danger)",
                        animation: "fade-in 0.5s ease-out"
                      }}>
                        {competitionScore.high_risk_rules_for_competition.map((rule: any, idx: number) => (
                          <div 
                            key={rule.rule} 
                            style={{ 
                              padding: "10px 12px", 
                              background: "var(--bg-card)",
                              border: "1px solid var(--border)",
                              borderRadius: "8px",
                              boxShadow: "var(--shadow-sm, 0 1px 3px rgba(0,0,0,0.08))",
                              display: "flex",
                              alignItems: "center",
                              gap: "8px",
                              animation: `fade-in 0.3s ease-out ${idx * 0.05}s both`,
                              transition: "all 0.2s ease",
                            }}
                          >
                            <span style={{ 
                              display: "inline-block",
                              background: "var(--tch-danger)",
                              color: "#fff",
                              padding: "4px 8px",
                              borderRadius: "8px",
                              fontSize: "12px",
                              fontWeight: "bold",
                              minWidth: "32px",
                              textAlign: "center"
                            }}>
                              {rule.rule}
                            </span>
                            <span style={{ fontSize: "12px", color: "var(--text-secondary)", flex: 1 }}>
                              {rule.name}
                            </span>
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              ) : (
                <p className="right-hint" style={{ padding: 20, textAlign: "center" }}>📌 选择项目后点击"预测评分"获取优化建议...</p>
              )}
            </div>
          )}

          {/* ── 教学干预建议 ── */}
          {tab === "interventions" && !loading && (
            <div className="tch-panel fade-up">
              <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
                <button onClick={() => setTab("class")} className="tch-back-btn">← 返回班级</button>
              </div>
              <h2>💡 教学干预建议</h2>
              <p className="tch-desc">基于全班共性问题智能生成的教学干预优先级清单。系统识别出现在40%以上学生提交中的问题，并给出针对性教学方案。</p>
              <button className="topbar-btn" onClick={loadTeachingInterventions} disabled={loading} style={{ marginBottom: 16, transition: "all 0.2s ease" }}>
                {loading ? "分析中…" : "🔄 刷新分析"}
              </button>

              {!teachingInterventions?.shared_problems ? (
                <SkeletonLoader rows={3} type="card" />
              ) : (
                <div style={{ animation: "fade-in 0.4s ease-out" }}>
                  <div className="kpi-grid">
                    <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                      <span>👥 班级规模</span>
                      <strong style={{ fontSize: 28 }}>{teachingInterventions.student_count ?? 0}</strong>
                      <em>学生数</em>
                    </div>
                    <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                      <span>🚨 共性问题</span>
                      <strong style={{ fontSize: 28, color: "var(--tch-danger)" }}>
                        {teachingInterventions.total_shared_problems ?? 0}
                      </strong>
                      <em>需干预</em>
                    </div>
                  </div>

                  <h3 style={{ marginTop: 24, marginBottom: 12 }}>⚡ 优先级教学方案</h3>
                  {teachingInterventions.shared_problems.length === 0 ? (
                    <p style={{ color: "var(--text-muted)", fontSize: 12, padding: 20, textAlign: "center" }}>暂无共性问题识别</p>
                  ) : (
                    teachingInterventions.shared_problems.map((problem: any, idx: number) => (
                      <div 
                        key={problem.rule_id} 
                        className="viz-card"
                        style={{
                          animation: `fade-in 0.3s ease-out ${idx * 0.08}s both`,
                          borderLeft: `3px solid ${problem.priority === "高" ? "var(--tch-danger)" : problem.priority === "中" ? "var(--tch-warning)" : "var(--tch-success)"}`,
                          transition: "all 0.2s ease",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                          <strong style={{ fontSize: 16 }}>
                            {problem.rule_id}: {problem.problem_description}
                          </strong>
                          <span className={problem.priority === "高" ? "risk-badge high" : problem.priority === "中" ? "risk-badge" : "risk-badge low"}>
                            {problem.priority}优先级
                          </span>
                        </div>
                        <p style={{ marginBottom: 8 }}>
                          <strong>📚 教学建议：</strong>{problem.teaching_suggestion}
                        </p>
                        <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
                          <em>⏱️ 预计课时：{problem.estimated_teaching_time}</em>
                        </p>
                      </div>
                    ))
                  )}

                  <h3 style={{ marginTop: 24, marginBottom: 12 }}>📅 下周课程设计建议</h3>
                  <p 
                    className="right-tag"
                    style={{
                      animation: "fade-in 0.5s ease-out",
                      background: "var(--tch-accent-soft)",
                      color: "var(--text-primary)",
                      padding: 16,
                      borderRadius: 10,
                      borderLeft: "3px solid var(--accent)",
                    }}
                  >
                    ✨ {teachingInterventions.recommended_next_class_focus}
                  </p>
                </div>
              )}
              {!teachingInterventions && <p className="right-hint" style={{ padding: 20, textAlign: "center" }}>加载中或暂无数据...</p>}
            </div>
          )}

          {/* ── 班级管理 ── */}
          {tab === "project" && (
            <div className="tch-panel fade-up" style={{ maxWidth: "none" }}>
              <h2>项目工作台</h2>
              <p className="tch-desc">这里不再只是项目跳转页，而是老师从大批项目中提炼重点、比较差异、再进入单项目深钻的分析台。</p>

              {teacherProjectCatalog.length === 0 ? (
                <div className="project-launchpad">
                  <div className="project-launch-card">
                    <div className="tm-project-cover-label">Project Intelligence Deck</div>
                    <h3 style={{ marginTop: 8, marginBottom: 8 }}>当前还没有可用项目目录</h3>
                    <p className="tch-desc" style={{ marginBottom: 0 }}>请先让老师名下团队产生学生项目记录；系统会自动把这些项目收束成目录，不再要求手输 ID。</p>
                  </div>
                </div>
              ) : (
                (() => {
                  const activeBoardCategory =
                    projectBoardCategories.find((item: any) => item.category === projectBoardCategory)
                    || projectBoardCategories[0];
                  const logicalProjects = projectWorkbenchSummary?.logical_projects || [];
                  const activeProjectCard =
                    logicalProjects.find((item: any) => item.logical_project_id === selectedLogicalProjectId)
                    || logicalProjects[0]
                    || null;
                  const rankedProjects = [...logicalProjects].sort((a: any, b: any) => Number(b.latest_score || 0) - Number(a.latest_score || 0));
                  const maxScore = Math.max(1, ...rankedProjects.map((item: any) => Number(item.latest_score || 0)));
                  const reportScope = filteredProjectCatalog.slice(0, 12);
                  const scoreBands = [
                    { label: "8.0+", count: reportScope.filter((item: any) => Number(item.latest_score || 0) >= 8).length },
                    { label: "6.0-7.9", count: reportScope.filter((item: any) => Number(item.latest_score || 0) >= 6 && Number(item.latest_score || 0) < 8).length },
                    { label: "0-5.9", count: reportScope.filter((item: any) => Number(item.latest_score || 0) < 6).length },
                  ];
                  const maxBandCount = Math.max(1, ...scoreBands.map((item) => item.count));
                  const reportSparkData = reportScope.map((item: any) => Number(item.latest_score || 0));
                  const reportEvidenceCitations = (
                    projectStructuredReport?.evidence_citations?.length
                      ? projectStructuredReport.evidence_citations
                      : reportScope.slice(0, 3).map((item: any) => ({
                          claim: `${item.project_name} 能代表当前分类的一个观察切面。`,
                          project_name: item.project_name,
                          evidence: item.summary || "暂无材料摘要。",
                        }))
                  ).filter(Boolean);
                  return (
                    <>
                      <div className="project-intel-hero">
                        <div className="project-intel-copy">
                          <div className="tm-project-cover-label">Project Intelligence Deck</div>
                          <h2 style={{ marginTop: 6, marginBottom: 8 }}>先看项目群像，再决定先处理谁</h2>
                          <p className="tch-desc" style={{ margin: 0 }}>
                            系统会自动按主题把项目收成类别，并从同类项目里提炼共性问题、进步样本和风险方向。老师可以直接抽两项做横向对比，不用在大量项目里来回翻找。
                          </p>
                          <div className="project-intel-summary-band">
                            <div className="project-intel-summary-chip">
                              <span>项目总数</span>
                              <strong>{teacherProjectCatalog.length}</strong>
                            </div>
                            <div className="project-intel-summary-chip">
                              <span>当前分类</span>
                              <strong>{projectBoardCategory}</strong>
                            </div>
                            <div className="project-intel-summary-chip">
                              <span>平均最新分</span>
                              <strong>{projectBoardInsight?.avgScore?.toFixed(1) || "0.0"}</strong>
                            </div>
                            <div className="project-intel-summary-chip">
                              <span>高风险项目</span>
                              <strong>{teacherProjectCatalog.filter((item: any) => feedbackUrgencyScore(item) >= 28).length}</strong>
                            </div>
                          </div>
                          <div className="project-category-mosaic">
                            {projectBoardCategories.slice(0, 6).map((item: any) => (
                              <button
                                key={item.category}
                                className={`project-category-mosaic-item ${projectBoardCategory === item.category ? "active" : ""}`}
                                onClick={() => setProjectBoardCategory(item.category)}
                                style={{ "--project-accent": item.accent } as CSSProperties}
                              >
                                <strong>{item.category}</strong>
                                <span>{item.count} 项</span>
                                <b>{Number(item.avgScore || 0).toFixed(1)}</b>
                              </button>
                            ))}
                          </div>
                        </div>
                      </div>

                      <div className="workspace-head-nav" style={{ marginBottom: 18 }}>
                        <button className={`workspace-head-pill ${projectWorkspaceView === "insight" ? "active" : ""}`} onClick={() => setProjectWorkspaceView("insight")}>
                          <strong>分类洞察</strong>
                          <span>每次只看一类项目的共性信息</span>
                        </button>
                        <button className={`workspace-head-pill ${projectWorkspaceView === "library" ? "active" : ""}`} onClick={() => setProjectWorkspaceView("library")}>
                          <strong>项目库</strong>
                          <span>只做筛选和进入单项目画像</span>
                        </button>
                        <button className={`workspace-head-pill ${projectWorkspaceView === "compare" ? "active" : ""}`} onClick={() => setProjectWorkspaceView("compare")}>
                          <strong>智能对比</strong>
                          <span>专门做两项目横向分析</span>
                        </button>
                        <button className={`workspace-head-pill ${projectWorkspaceView === "detail" ? "active" : ""}`} onClick={() => projectIdConfirmed && setProjectWorkspaceView("detail")}>
                          <strong>项目画像</strong>
                          <span>进入单项目深钻工作区</span>
                        </button>
                      </div>

                      {projectWorkspaceView !== "detail" && (
                      <div className="project-intel-shell">
                        <div className="project-intel-main">
                          {projectWorkspaceView === "insight" && (
                          <div className="assistant-section">
                            <div className="assistant-section-title">同类项目关键洞察</div>
                            <div className="project-insight-panel">
                              <div className="project-insight-head">
                                <div>
                                  <strong>{activeBoardCategory?.category || "全部项目"}</strong>
                                  <p className="tch-desc" style={{ margin: "6px 0 0 0" }}>
                                    {activeBoardCategory?.category === "全部项目"
                                      ? "先看全量项目的大盘，再切入某一类项目的共性问题。"
                                      : `这一组项目共有 ${activeBoardCategory?.count || 0} 项，适合老师做同题型教学判断。`}
                                  </p>
                                </div>
                                <div className="project-insight-glance">
                                  <span>平均分 {projectBoardInsight?.avgScore?.toFixed(1) || "0.0"}</span>
                                  <span>主导意图 {projectBoardInsight?.topIntent || "综合咨询"}</span>
                                </div>
                              </div>
                              <div className="assistant-toolbar" style={{ marginTop: 18, justifyContent: "space-between", alignItems: "center" }}>
                                <div className="tch-desc" style={{ margin: 0 }}>结构化 AI 报告会把这一类项目压缩成老师可直接使用的洞察、样本和教学动作。</div>
                                <button
                                  className="topbar-btn"
                                  onClick={() => generateProjectStructuredReport(filteredProjectCatalog, projectBoardCategory)}
                                  disabled={projectStructuredReportLoading}
                                >
                                  {projectStructuredReportLoading ? "生成中..." : "刷新结构化 AI 报告"}
                                </button>
                              </div>
                              <div className="project-report-board">
                                <div className="project-report-hero">
                                  <div>
                                    <span className="project-report-label">AI 分类报告</span>
                                    <h3>{projectStructuredReport?.headline || `${activeBoardCategory?.category || "全部项目"} 的总体判断`}</h3>
                                    <div className="project-report-tag-row">
                                      <span>{activeBoardCategory?.category || "全部项目"}</span>
                                      <span>{activeBoardCategory?.count || filteredProjectCatalog.length || 0} 个项目</span>
                                      <span>主导意图 {projectBoardInsight?.topIntent || "综合咨询"}</span>
                                    </div>
                                  </div>
                                  <div className="project-report-kpis">
                                    <div><span>代表性优势</span><strong>{projectBoardInsight?.highest?.project_name || "暂无"}</strong></div>
                                    <div><span>最需介入</span><strong>{projectBoardInsight?.lowest?.project_name || "暂无"}</strong></div>
                                    <div><span>高频问题</span><strong>{projectBoardInsight?.topRisks?.length ? getRuleDisplayName(projectBoardInsight.topRisks[0][0]) : "暂无"}</strong></div>
                                  </div>
                                </div>
                                <div className="project-report-overview">
                                  <p>{projectStructuredReport?.overview || projectBoardInsight?.summaryLines?.join(" ") || "系统正在汇总这一类项目的主要洞察。"}</p>
                                </div>
                                <div className="project-report-dashboard">
                                  <div className="project-report-chart-card">
                                    <div className="project-report-chart-head">
                                      <strong>分数分布</strong>
                                      <span>看这一类项目当前的成熟度分层</span>
                                    </div>
                                    <div className="table-like">
                                      {scoreBands.map((band) => (
                                        <div key={band.label} className="bar-row">
                                          <span>{band.label}</span>
                                          <div className={`bar-track ${band.label === "0-5.9" ? "danger" : ""}`}>
                                            <div
                                              className={`bar-fill ${band.label === "0-5.9" ? "danger" : ""}`}
                                              style={{ width: `${(band.count / maxBandCount) * 100}%` }}
                                            />
                                          </div>
                                          <strong>{band.count}</strong>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                  <div className="project-report-chart-card accent">
                                    <div className="project-report-chart-head">
                                      <strong>分类走势</strong>
                                      <span>抽样看当前分类前几项项目分数起伏</span>
                                    </div>
                                    <div className="project-report-spark-shell">
                                      <svg width="100%" height="86" viewBox="0 0 220 86" preserveAspectRatio="none">
                                        <polyline
                                          points={sparklinePoints(reportSparkData, 220, 86)}
                                          fill="none"
                                          stroke="url(#projectReportSpark)"
                                          strokeWidth="3"
                                          strokeLinejoin="round"
                                          strokeLinecap="round"
                                        />
                                        <defs>
                                          <linearGradient id="projectReportSpark" x1="0" y1="0" x2="1" y2="0">
                                            <stop offset="0%" stopColor="#73ccff" />
                                            <stop offset="100%" stopColor="#8f7bff" />
                                          </linearGradient>
                                        </defs>
                                      </svg>
                                    </div>
                                    <div className="tm-corridor-tags" style={{ marginTop: 8 }}>
                                      {(projectBoardInsight?.topRisks || []).slice(0, 3).map(([risk, count]: any) => (
                                        <span key={risk} className="tm-smart-chip">{getRuleDisplayName(risk)} {count}</span>
                                      ))}
                                    </div>
                                  </div>
                                </div>
                                <div className="project-report-signal-strip">
                                  {(projectStructuredReport?.category_diagnosis?.length
                                    ? projectStructuredReport.category_diagnosis.map((item: any) => `${item.theme}：${item.detail}`)
                                    : (projectBoardInsight?.summaryLines || [])
                                  ).slice(0, 3).map((line: string) => (
                                    <div key={line} className="project-report-signal-item">{line}</div>
                                  ))}
                                </div>
                                <div className="project-report-article">
                                  <section className="project-report-block">
                                    <div className="project-report-block-title">Agent 总判断</div>
                                    <p>{projectStructuredReport?.executive_brief || "先看这一类项目是否已经出现可被统一讲评的共性问题，再决定是批量干预还是逐个精读。"}</p>
                                  </section>
                                  <section className="project-report-block">
                                    <div className="project-report-block-title">分类诊断</div>
                                    <div className="project-report-stack">
                                      {(projectStructuredReport?.category_diagnosis?.length
                                        ? projectStructuredReport.category_diagnosis
                                        : [
                                          { theme: "整体完成度", detail: projectBoardInsight?.summaryLines?.[0] || "暂无整体判断。" },
                                          { theme: "主要风险", detail: projectBoardInsight?.summaryLines?.[1] || "暂无集中风险。" },
                                        ]).map((item: any) => (
                                          <div key={`${item.theme}-${item.detail}`} className="project-report-stack-item">
                                            <strong>{item.theme}</strong>
                                            <p>{item.detail}</p>
                                          </div>
                                        ))}
                                    </div>
                                  </section>
                                  <section className="project-report-block">
                                    <div className="project-report-block-title">样本对照</div>
                                    <div className="project-report-sample-board">
                                      {(projectStructuredReport?.sample_comparison?.length
                                        ? projectStructuredReport.sample_comparison
                                        : [
                                          {
                                            role: "高分样本",
                                            project_name: projectBoardInsight?.highest?.project_name || "暂无",
                                            takeaway: "适合作为这一类项目的正样本。",
                                          },
                                          {
                                            role: "高风险样本",
                                            project_name: projectBoardInsight?.lowest?.project_name || "暂无",
                                            takeaway: "适合作为需要老师优先介入的反例样本。",
                                          },
                                        ]).map((item: any) => (
                                          <div key={`${item.role}-${item.project_name}`} className="project-report-sample-item">
                                            <span>{item.role}</span>
                                            <strong>{item.project_name}</strong>
                                            <p>{item.takeaway}</p>
                                          </div>
                                        ))}
                                    </div>
                                  </section>
                                  <section className="project-report-block">
                                    <div className="project-report-block-title">结论依据</div>
                                    <div className="project-report-evidence-list">
                                      {reportEvidenceCitations.map((item: any) => (
                                        <div key={`${item.claim}-${item.project_name}`} className="project-report-evidence-item">
                                          <div className="project-report-evidence-top">
                                            <span>引用项目</span>
                                            <strong>{item.project_name || "未命名项目"}</strong>
                                          </div>
                                          <div className="project-report-evidence-claim">{item.claim}</div>
                                          <p>{item.evidence || "暂无可展示论据。"}</p>
                                        </div>
                                      ))}
                                    </div>
                                  </section>
                                  <section className="project-report-block">
                                    <div className="project-report-block-title">共性优势与问题</div>
                                    <div className="project-report-dual-list">
                                      <div>
                                        <h4>共性优势</h4>
                                        <ul className="project-report-list">
                                          {(projectStructuredReport?.strengths?.length ? projectStructuredReport.strengths : [
                                            projectBoardInsight?.highest ? `${projectBoardInsight.highest.project_name} 当前分 ${Number(projectBoardInsight.highest.latest_score || 0).toFixed(1)}，适合作为这一类项目的正样本。` : "",
                                            projectBoardInsight?.fastest ? `${projectBoardInsight.fastest.project_name} 最近提升 ${Number(projectBoardInsight.fastest.improvement || 0).toFixed(1)} 分，说明这一类项目存在可复制的迭代路径。` : "",
                                          ].filter(Boolean)).map((item: string) => (
                                            <li key={item}>{item}</li>
                                          ))}
                                        </ul>
                                      </div>
                                      <div>
                                        <h4>共性问题</h4>
                                        <ul className="project-report-list">
                                          {(projectStructuredReport?.issues?.length
                                            ? projectStructuredReport.issues.map((item: any) => `${item.title}：${item.detail}`)
                                            : (projectBoardInsight?.topRisks || []).map(([risk, count]: any) => `${getRuleDisplayName(risk)}：当前分类中出现 ${count} 次，建议集中讲评。`)
                                          ).map((item: string) => (
                                            <li key={item}>{item}</li>
                                          ))}
                                        </ul>
                                      </div>
                                    </div>
                                  </section>
                                  <section className="project-report-block">
                                    <div className="project-report-block-title">建议老师先做什么</div>
                                    <div className="project-report-priority-list">
                                      {(projectStructuredReport?.priority_projects?.length ? projectStructuredReport.priority_projects : [
                                        {
                                          project_name: projectBoardInsight?.lowest?.project_name || "暂无",
                                          reason: projectBoardInsight?.lowest ? `当前分 ${Number(projectBoardInsight.lowest.latest_score || 0).toFixed(1)}，建议优先检查证据链和材料结构。` : "当前没有明显的优先项目。",
                                        },
                                      ]).map((item: any) => (
                                        <div key={`${item.project_name}-${item.reason}`} className="project-report-priority-item">
                                          <strong>{item.project_name}</strong>
                                          <p>{item.reason}</p>
                                        </div>
                                      ))}
                                    </div>
                                  </section>
                                  <section className="project-report-block">
                                    <div className="project-report-block-title">教学动作与比较维度</div>
                                    <ul className="project-report-list">
                                      {(projectStructuredReport?.comparison_axes?.length
                                        ? projectStructuredReport.comparison_axes.map((item: any) => `${item.dimension}：${item.insight}`)
                                        : [`主导意图 ${projectBoardInsight?.topIntent || "综合咨询"}，横向比较时可重点看论证闭环和迭代质量。`]
                                      ).map((item: string) => (
                                        <li key={item}>{item}</li>
                                      ))}
                                    </ul>
                                    <div className="project-report-action">
                                      <span>建议教学动作</span>
                                      <strong>{projectStructuredReport?.teaching_focus || "统一提醒高频问题"}</strong>
                                      <p>{projectStructuredReport?.teaching_action || "先抽一份高分样本和一份高风险样本做对照讲评，再布置下一轮修改要求。"}</p>
                                    </div>
                                    <div className="project-report-teaching-list">
                                      {(projectStructuredReport?.teaching_modules || []).map((item: string) => (
                                        <div key={item} className="project-report-teaching-item">{item}</div>
                                      ))}
                                    </div>
                                  </section>
                                </div>
                              </div>
                            </div>
                          </div>
                          )}

                          {projectWorkspaceView === "library" && (
                          <div className="assistant-section">
                            <div className="assistant-section-title">项目库</div>
                            <div className="project-board-toolbar">
                              <div className="project-board-sort">
                                <button className={`tch-sm-btn ${projectBoardSort === "risk" ? "active" : ""}`} onClick={() => setProjectBoardSort("risk")}>按风险优先</button>
                                <button className={`tch-sm-btn ${projectBoardSort === "score" ? "active" : ""}`} onClick={() => setProjectBoardSort("score")}>按当前分</button>
                                <button className={`tch-sm-btn ${projectBoardSort === "improvement" ? "active" : ""}`} onClick={() => setProjectBoardSort("improvement")}>按提升幅度</button>
                                <button className={`tch-sm-btn ${projectBoardSort === "submissions" ? "active" : ""}`} onClick={() => setProjectBoardSort("submissions")}>按迭代次数</button>
                              </div>
                              <div className="project-board-sort">
                                <button className="tch-sm-btn" onClick={randomizeProjectCompareSelection}>随机抽两项对比</button>
                              </div>
                            </div>
                            <div className="project-board-grid">
                              {filteredProjectCatalog.map((item: any) => {
                                const isFocused = item.root_project_id === selectedProject && item.logical_project_id === selectedLogicalProjectId;
                                const selectedForCompare = projectCompareSelection.includes(item.project_key);
                                const improvementColor = Number(item.improvement || 0) >= 0 ? "var(--tch-success)" : "var(--tch-danger)";
                                return (
                                  <div
                                    key={item.project_key}
                                    className={`project-board-card ${isFocused ? "active" : ""}`}
                                    style={{ "--project-accent": categoryAccent(item.category) } as CSSProperties}
                                  >
                                    <div className="project-board-card-top">
                                      <span className="project-compare-index">{serialLabel("项目", item.catalog_order)}</span>
                                      <span className="project-board-category">{item.category}</span>
                                    </div>
                                    <strong>{item.project_name}</strong>
                                    <div className="tm-case-meta">
                                      <span>{item.student_name}</span>
                                      <span>{item.team_name}</span>
                                      <span>{item.project_phase}</span>
                                    </div>
                                    <p className="project-board-summary">{item.summary}</p>
                                    <div className="project-board-stats">
                                      <div><strong>{Number(item.latest_score || 0).toFixed(1)}</strong><span>当前分</span></div>
                                      <div><strong>{item.submission_count}</strong><span>迭代</span></div>
                                      <div><strong style={{ color: improvementColor }}>{Number(item.improvement || 0) > 0 ? "+" : ""}{Number(item.improvement || 0).toFixed(1)}</strong><span>变化</span></div>
                                    </div>
                                    <div className="tm-corridor-tags" style={{ marginTop: 10 }}>
                                      <span className="tm-smart-chip">{item.dominant_intent || "综合咨询"}</span>
                                      {(item.top_risks || []).slice(0, 2).map((risk: string) => <span key={risk} className="tm-smart-chip">{getRuleDisplayName(risk)}</span>)}
                                    </div>
                                    <div className="project-board-actions">
                                      <button className={`tch-sm-btn ${selectedForCompare ? "active" : ""}`} onClick={() => toggleProjectCompareSelection(item.project_key)}>
                                        {selectedForCompare ? "已加入对比" : "加入对比"}
                                      </button>
                                      <button className="tch-sm-btn" onClick={() => loadProjectWorkbench(item.root_project_id, item.logical_project_id)}>进入画像</button>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                          )}

                          {projectWorkspaceView === "compare" && (
                            <>
                              <div className="assistant-section">
                                <div className="assistant-section-title">AI 智能对比</div>
                                {comparedProjectCards.length === 2 ? (
                                  <div className="project-compare-lab">
                                    <div className="project-compare-duo">
                                      {comparedProjectCards.map((item: any) => (
                                        <button key={item.project_key} className="project-compare-mini" onClick={() => loadProjectWorkbench(item.root_project_id, item.logical_project_id)}>
                                          <span>{item.category}</span>
                                          <strong>{item.project_name}</strong>
                                          <p>{item.student_name} · {Number(item.latest_score || 0).toFixed(1)} 分</p>
                                        </button>
                                      ))}
                                    </div>
                                    <div className="project-compare-opinion">
                                      {(projectCompareInsight?.lines || []).map((line: string) => (
                                        <div key={line} className="project-insight-line">{line}</div>
                                      ))}
                                    </div>
                                    <div className="project-compare-signals">
                                      <span>分差 {projectCompareInsight?.scoreGap?.toFixed(1) || "0.0"}</span>
                                      <span>迭代差 {projectCompareInsight?.iterationGap || 0}</span>
                                      <span>共同问题 {(projectCompareInsight?.sharedRisks || []).length}</span>
                                    </div>
                                  </div>
                                ) : <p className="right-hint">先在下方候选区选中两项项目，再看系统给出的横向差异判断。</p>}
                              </div>
                              <div className="assistant-section">
                                <div className="assistant-section-title">对比候选项目</div>
                                <div className="project-board-grid">
                                  {filteredProjectCatalog.map((item: any) => {
                                    const selectedForCompare = projectCompareSelection.includes(item.project_key);
                                    return (
                                      <div key={item.project_key} className="project-board-card" style={{ "--project-accent": categoryAccent(item.category) } as CSSProperties}>
                                        <div className="project-board-card-top">
                                          <span className="project-compare-index">{serialLabel("项目", item.catalog_order)}</span>
                                          <span className="project-board-category">{item.category}</span>
                                        </div>
                                        <strong>{item.project_name}</strong>
                                        <div className="tm-case-meta">
                                          <span>{item.student_name}</span>
                                          <span>{item.team_name}</span>
                                          <span>{item.project_phase}</span>
                                        </div>
                                        <p className="project-board-summary">{item.summary}</p>
                                        <div className="project-board-actions">
                                          <button className={`tch-sm-btn ${selectedForCompare ? "active" : ""}`} onClick={() => toggleProjectCompareSelection(item.project_key)}>
                                            {selectedForCompare ? "已加入对比" : "加入对比"}
                                          </button>
                                          <button className="tch-sm-btn" onClick={() => loadProjectWorkbench(item.root_project_id, item.logical_project_id)}>查看画像</button>
                                        </div>
                                      </div>
                                    );
                                  })}
                                </div>
                              </div>
                            </>
                          )}
                        </div>

                      </div>
                      )}

                      {projectWorkspaceView === "detail" && !projectIdConfirmed ? (
                        <p className="right-hint">从上方项目库里点开某个项目后，下面会展开这个项目的综合画像与深钻工作区。</p>
                      ) : projectWorkspaceView === "detail" ? (
                        <>
                          <div className="tm-project-cover">
                            <div>
                              <div className="tm-project-cover-label">Focused Project Portrait</div>
                              <h2 style={{ marginTop: 6, marginBottom: 6 }}>{activeProjectCard?.project_name || assistantAssessment?.project_name || selectedProject}</h2>
                              <div className="tm-case-meta">
                                <span>根项目 {selectedProject}</span>
                                {activeProjectCard?.project_order ? <span>{serialLabel("项目", activeProjectCard.project_order)}</span> : null}
                                {activeProjectCard?.project_phase && <span>{activeProjectCard.project_phase}</span>}
                                {activeProjectCard?.submission_count ? <span>{activeProjectCard.submission_count} 次提交</span> : null}
                                {activeProjectCard?.material_count !== undefined ? <span>{activeProjectCard.material_count} 份材料</span> : null}
                              </div>
                              <div className="tm-case-summary" style={{ marginTop: 14 }}>
                                <div className="tm-case-summary-title">当前项目画像</div>
                                <div className="tm-case-summary-body">{activeProjectCard?.summary || assistantAssessment?.summary || projectDiagnosis?.bottleneck || "先从上方项目库中选择一个项目，系统会自动展开它的综合画像。"}</div>
                              </div>
                            </div>
                            <div className="tm-project-cover-score">
                              <div>{activeProjectCard?.latest_score || assistantAssessment?.overall_score || competitionScore?.predicted_competition_score || 0}</div>
                              <span>{activeProjectCard?.dominant_intent || assistantAssessment?.score_band || "当前项目视图"}</span>
                            </div>
                          </div>

                          <div className="assistant-toolbar" style={{ marginBottom: 18 }}>
                            <button className="tch-sm-btn" onClick={() => loadProjectWorkbench(selectedProject, selectedLogicalProjectId)}>刷新画像</button>
                            <button className="tch-sm-btn" onClick={() => loadAssistantAssessment(selectedProject, selectedLogicalProjectId)}>去批改与溯源</button>
                            <button className="tch-sm-btn" onClick={() => loadAssistantConversationEval(selectedProject, selectedLogicalProjectId)}>看过程评估</button>
                            <button className="tch-sm-btn" onClick={() => loadFeedbackWorkspace(selectedProject || projectId, selectedLogicalProjectId || "")}>打开材料反馈</button>
                            <button className="tch-sm-btn" onClick={() => loadProjectCaseBenchmark(selectedProject, selectedLogicalProjectId)}>刷新案例对标</button>
                            <button onClick={() => { setProjectIdConfirmed(false); setSelectedProject(""); setSelectedLogicalProjectId(""); setProjectWorkbenchSummary(null); setProjectWorkspaceView("library"); }} className="tch-back-btn">返回项目库</button>
                          </div>

                          <div className="assistant-shell">
                            <div className="assistant-main-panel">
                              <div className="assistant-section">
                                <div className="assistant-section-title">根项目下的多项目比较</div>
                                {logicalProjects.length > 0 ? (
                                  <div className="project-compare-grid">
                                    {logicalProjects.map((item: any) => {
                                      const active = item.logical_project_id === selectedLogicalProjectId;
                                      const improvementColor = Number(item.improvement || 0) >= 0 ? "var(--tch-success)" : "var(--tch-danger)";
                                      return (
                                        <button
                                          key={item.logical_project_id}
                                          className={`project-compare-card ${active ? "active" : ""}`}
                                          onClick={() => loadProjectWorkbench(selectedProject, item.logical_project_id)}
                                        >
                                          <div className="project-compare-top">
                                            <span className="project-compare-index">{serialLabel("项目", item.project_order)}</span>
                                            <span className="tm-case-badge">{item.project_phase || "持续迭代"}</span>
                                          </div>
                                          <strong>{item.project_name}</strong>
                                          <div className="tm-case-meta">
                                            <span>{compactId(item.logical_project_id || "")}</span>
                                            <span>{item.submission_count} 次提交</span>
                                            <span>{item.material_count} 份材料</span>
                                          </div>
                                          <div className="tm-case-inline-summary" style={{ marginTop: 8 }}>{item.summary}</div>
                                          <div className="project-compare-stats">
                                            <div><strong>{Number(item.latest_score || 0).toFixed(1)}</strong><span>当前分</span></div>
                                            <div><strong>{Number(item.avg_score || 0).toFixed(1)}</strong><span>均分</span></div>
                                            <div><strong style={{ color: improvementColor }}>{Number(item.improvement || 0) > 0 ? "+" : ""}{Number(item.improvement || 0).toFixed(1)}</strong><span>变化</span></div>
                                          </div>
                                        </button>
                                      );
                                    })}
                                  </div>
                                ) : <p className="right-hint">当前根项目下还没有可用于对比的逻辑项目。</p>}
                              </div>

                              <div className="assistant-section">
                                <div className="assistant-section-title">画像诊断快照</div>
                                {assistantAssessment && !assistantAssessment.error ? (
                                  <>
                                    <div className="assistant-rubric-table">
                                      {(assistantAssessment.rubric_items || []).slice(0, 4).map((item: any) => (
                                        <div key={item.item_id} className="assistant-rubric-row rich">
                                          <div>
                                            <strong>{item.item_name}</strong>
                                            <div className="assistant-inline-note">{item.reason}</div>
                                          </div>
                                          <div>{item.score}/{item.max_score}</div>
                                          <div>{Math.round((item.weight || 0) * 100)}%</div>
                                        </div>
                                      ))}
                                    </div>
                                    <div className="assistant-note-list" style={{ marginTop: 12 }}>
                                      {(assistantAssessment.revision_suggestions || []).slice(0, 3).map((item: string, idx: number) => <div key={idx} className="tm-note-row warn">{item}</div>)}
                                    </div>
                                  </>
                                ) : <p className="right-hint">暂无批改快照。</p>}
                              </div>

                              <div className="assistant-section">
                                <div className="assistant-section-title">证据与问题链</div>
                                <div className="tm-evidence-grid">
                                  {(assistantAssessment?.evidence_chain || []).slice(0, 4).map((item: any, idx: number) => (
                                    <div key={idx} className="tm-evidence-card">
                                      <div className="tm-evidence-top">
                                        <span>{getRuleDisplayName(item.risk_name || item.risk_id || "未归类")}</span>
                                        <span>{formatBJTime(item.created_at)}</span>
                                      </div>
                                      <div className="tm-evidence-quote">“{item.quote}”</div>
                                    </div>
                                  ))}
                                </div>
                                {projectDiagnosis?.fix_strategies?.length > 0 && (
                                  <div className="assistant-note-list" style={{ marginTop: 12 }}>
                                    {projectDiagnosis.fix_strategies.slice(0, 3).map((fix: any) => <div key={fix.rule_id} className="tm-note-row good">{fix.rule_name}：{fix.fix_strategy}</div>)}
                                  </div>
                                )}
                              </div>

                              {projectRuleDashboard && !projectRuleDashboard.error && (
                                <div className="assistant-section">
                                  <div className="assistant-section-title">规则触发雷达 & 红线看板</div>
                                  <div className="assistant-insight-grid">
                                    <div className="assistant-summary-card" style={{ minWidth: 0 }}>
                                      <div className="assistant-section-title" style={{ marginBottom: 8 }}>本项目规则雷达</div>
                                      {Array.isArray(projectRuleDashboard.radar) && projectRuleDashboard.radar.length >= 3 ? (
                                        <RadarChart
                                          data={projectRuleDashboard.radar.map((row: any) => ({
                                            label: getRuleDisplayName(row.label || row.rule || row.rule_id || "规则"),
                                            value: Number(row.value ?? row.raw_hits ?? 0),
                                            max: 10,
                                          }))}
                                          size={230}
                                        />
                                      ) : (
                                        <p className="right-hint">当前项目的规则触发样本还不多。</p>
                                      )}
                                    </div>
                                    <div className="assistant-summary-card" style={{ minWidth: 0 }}>
                                      <div className="assistant-section-title" style={{ marginBottom: 8 }}>高频红线规则</div>
                                      <div className="assistant-note-list">
                                        {(projectRuleDashboard.rules || []).slice(0, 5).map((rule: any) => (
                                          <div
                                            key={rule.rule_id}
                                            className={`tm-note-row ${rule.severity && rule.severity !== "low" ? "warn" : "good"}`}
                                          >
                                            <strong>{rule.rule_id}</strong> · {rule.rule_name || getRuleDisplayName(rule.rule_id)}
                                            <div className="assistant-inline-note">
                                              命中 {rule.hit_count} 次 · {rule.fallacy || "未归类"}
                                              {Array.isArray(rule.edge_families) && rule.edge_families.length > 0 && (
                                                <span> · {(rule.edge_families || []).slice(0, 2).join(" / ")}</span>
                                              )}
                                            </div>
                                          </div>
                                        ))}
                                        {(!projectRuleDashboard.rules || projectRuleDashboard.rules.length === 0) && (
                                          <p className="right-hint">当前项目还没有明显的规则触发集中区。</p>
                                        )}
                                      </div>
                                    </div>
                                  </div>
                                </div>
                              )}

                              {projectEvidenceTrace && !projectEvidenceTrace.error && (
                                <div className="assistant-section">
                                  <div className="assistant-section-title">Rubric × 证据链追溯</div>
                                  <div className="assistant-note-list">
                                    {(projectEvidenceTrace.rubric_summary || []).slice(0, 4).map((row: any) => (
                                      <div key={row.rubric_item} className="tm-note-row warn">
                                        {row.rubric_item} · {row.evidence_count} 条证据 · 关联规则
                                        {" "}
                                        {(row.rule_ids || []).slice(0, 3).map((rid: string) => getRuleDisplayName(rid)).join(" / ") || "未标注"}
                                      </div>
                                    ))}
                                    {(projectEvidenceTrace.rubric_summary || []).length === 0 && (
                                      <p className="right-hint">暂未在当前项目下找到可追溯的 Rubric 证据链。</p>
                                    )}
                                  </div>
                                </div>
                              )}

                              <div className="assistant-section">
                                <div className="assistant-section-title">案例对标推荐板</div>
                                {projectCaseBenchmark && !projectCaseBenchmark.error ? (
                                  <div className="project-benchmark-grid" style={{ display: "grid", gridTemplateColumns: "minmax(0,1.2fr) minmax(0,1.5fr)", gap: 16 }}>
                                    {(() => {
                                      const bench = projectCaseBenchmark;
                                      const sp = bench.student_project || {};
                                      const studentRisks: string[] = bench.student_risks || [];
                                      const topCases: any[] = (bench.top_cases || []).slice(0, 3);
                                      return (
                                        <>
                                          <div className="project-benchmark-card" style={{ borderRadius: 10, padding: 14, border: "1px solid var(--border)", background: "var(--bg-card)" }}>
                                            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 6 }}>当前项目画像 · 案例对标视角</div>
                                            <h3 style={{ margin: "2px 0 6px 0", fontSize: 16 }}>{sp.project_name || activeProjectCard?.project_name || selectedProject}</h3>
                                            <div className="tm-case-meta">
                                              {sp.student_id && <span>{sp.student_id}</span>}
                                              {sp.class_id && <span>{sp.class_id}</span>}
                                              {sp.cohort_id && <span>{sp.cohort_id}</span>}
                                            </div>
                                            <div style={{ display: "flex", gap: 16, marginTop: 10 }}>
                                              <div>
                                                <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>最新得分</div>
                                                <div style={{ fontSize: 24, fontWeight: 700 }}>
                                                  <AnimatedNumber value={Number(sp.overall_score || activeProjectCard?.latest_score || 0)} duration={800} decimals={1} />
                                                </div>
                                              </div>
                                              <div>
                                                <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>风险标签数</div>
                                                <div style={{ fontSize: 22, fontWeight: 700 }}>{studentRisks.length}</div>
                                              </div>
                                              <div>
                                                <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>rag 命中轮次</div>
                                                <div style={{ fontSize: 22, fontWeight: 700 }}>{bench.similarity?.rag_turn_count ?? 0}</div>
                                              </div>
                                            </div>
                                            <div className="tm-corridor-tags" style={{ marginTop: 10 }}>
                                              {studentRisks.slice(0, 4).map((risk) => (
                                                <span key={risk} className="tm-smart-chip">{getRuleDisplayName(risk)}</span>
                                              ))}
                                              {studentRisks.length === 0 && <span className="right-hint">当前项目尚未触发集中风险规则。</span>}
                                            </div>
                                            <button
                                              className="tch-sm-btn"
                                              style={{ marginTop: 12 }}
                                              onClick={copyCaseBenchmarkToClipboard}
                                            >
                                              复制为教学对比表
                                            </button>
                                          </div>

                                          <div className="project-benchmark-card" style={{ borderRadius: 10, padding: 14, border: "1px solid var(--border)", background: "var(--bg-card)" }}>
                                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                                              <div>
                                                <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>最相近的参考案例</div>
                                                <strong>按相似度与出现频次排序的 1-3 个案例</strong>
                                              </div>
                                              <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                                                平均相似度 {Number(bench.similarity?.avg_top_similarity || 0).toFixed(2)}
                                              </div>
                                            </div>
                                            {topCases.length > 0 ? (
                                              <div className="project-benchmark-case-list" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                                                {topCases.map((c: any, idx: number) => {
                                                  const rubric = (c.rubric_coverage || []).filter((r: any) => r && r.covered).map((r: any) => r.rubric_item || r.item).filter(Boolean);
                                                  const riskFlags: string[] = c.risk_flags || [];
                                                  const avoided = riskFlags.filter((r) => !studentRisks.includes(r));
                                                  return (
                                                    <div key={c.case_id || c.project_name || idx} className="project-benchmark-case" style={{ padding: 10, borderRadius: 8, border: "1px solid var(--border)", background: "var(--bg-secondary)" }}>
                                                      <div className="tm-case-meta" style={{ marginBottom: 4 }}>
                                                        <span>{serialLabel("案例", idx + 1)}</span>
                                                        {c.category && <span>{c.category}</span>}
                                                        <span>相似度 {Number(c.avg_similarity || c.max_similarity || 0).toFixed(2)}</span>
                                                      </div>
                                                      <strong>{c.project_name || c.case_id || "推荐案例"}</strong>
                                                      {c.summary && (
                                                        <p className="project-board-summary" style={{ marginTop: 4 }}>{c.summary}</p>
                                                      )}
                                                      <div className="tm-corridor-tags" style={{ marginTop: 6 }}>
                                                        {rubric.slice(0, 4).map((r: string) => (
                                                          <span key={r} className="tm-smart-chip">Rubric：{r}</span>
                                                        ))}
                                                      </div>
                                                      <div className="tm-corridor-tags" style={{ marginTop: 4 }}>
                                                        {avoided.slice(0, 4).map((r) => (
                                                          <span key={r} className="tm-smart-chip">已规避：{getRuleDisplayName(r)}</span>
                                                        ))}
                                                        {avoided.length === 0 && riskFlags.slice(0, 3).map((r) => (
                                                          <span key={r} className="tm-smart-chip">案例风险：{getRuleDisplayName(r)}</span>
                                                        ))}
                                                      </div>
                                                    </div>
                                                  );
                                                })}
                                              </div>
                                            ) : (
                                              <p className="right-hint">当前项目的对话记录中还没有触发带有案例检索的轮次。先引导学生与助教围绕具体竞赛案例进行几轮对话，再刷新本区块。</p>
                                            )}
                                          </div>
                                        </>
                                      );
                                    })()}
                                  </div>
                                ) : (
                                  <p className="right-hint">点击上方“刷新案例对标”后，这里会展示“你的项目目前更像哪些典型案例 / 差在哪些 Rubric 或风险上”。</p>
                                )}
                              </div>
                            </div>

                            <div className="assistant-side-panel">
                              <div className="assistant-side-card">
                                <div className="assistant-section-title">根项目总览</div>
                                <div className="assistant-summary-stack" style={{ gridTemplateColumns: "1fr 1fr" }}>
                                  <div className="assistant-summary-card">
                                    <span>逻辑项目</span>
                                    <strong>{projectWorkbenchSummary?.logical_project_count || 0}</strong>
                                  </div>
                                  <div className="assistant-summary-card">
                                    <span>总提交</span>
                                    <strong>{projectWorkbenchSummary?.submission_count || 0}</strong>
                                  </div>
                                  <div className="assistant-summary-card">
                                    <span>总材料</span>
                                    <strong>{projectWorkbenchSummary?.material_count || 0}</strong>
                                  </div>
                                  <div className="assistant-summary-card">
                                    <span>整体均分</span>
                                    <strong>{Number(projectWorkbenchSummary?.avg_score || 0).toFixed(1)}</strong>
                                  </div>
                                </div>
                              </div>

                              <div className="assistant-side-card">
                                <div className="assistant-section-title">单项目排序</div>
                                {rankedProjects.length > 0 ? (
                                  <div className="project-rank-list">
                                    {rankedProjects.map((item: any, idx: number) => (
                                      <button
                                        key={`${item.logical_project_id}-rank`}
                                        className={`project-rank-row ${item.logical_project_id === selectedLogicalProjectId ? "active" : ""}`}
                                        onClick={() => loadProjectWorkbench(selectedProject, item.logical_project_id)}
                                      >
                                        <span className="project-rank-order">#{idx + 1}</span>
                                        <span className="project-rank-name">{serialLabel("项目", item.project_order)} · {item.project_name}</span>
                                        <div className="project-rank-track"><i style={{ width: `${(Number(item.latest_score || 0) / maxScore) * 100}%` }} /></div>
                                        <b>{Number(item.latest_score || 0).toFixed(1)}</b>
                                      </button>
                                    ))}
                                  </div>
                                ) : <p className="right-hint">暂无排序数据。</p>}
                              </div>

                              <div className="assistant-side-card">
                                <div className="assistant-section-title">竞赛预测与教师记录</div>
                                {competitionScore?.predicted_competition_score !== undefined ? (
                                  <>
                                    <div className="assistant-summary-card" style={{ marginBottom: 10 }}>
                                      <span>预测得分</span>
                                      <strong>{competitionScore.predicted_competition_score}</strong>
                                    </div>
                                    <div className="assistant-note-list" style={{ marginBottom: 12 }}>
                                      {(competitionScore.quick_fixes_24h || []).slice(0, 3).map((item: string, idx: number) => <div key={idx} className="tm-note-row good">{item}</div>)}
                                    </div>
                                  </>
                                ) : <p className="right-hint">暂无竞赛预测。</p>}
                                <div className="assistant-note-list">
                                  {projectFeedbackHistory.length > 0 ? projectFeedbackHistory.slice(0, 4).map((item: any) => (
                                    <div key={item.feedback_id} className="tm-note-row warn">{item.comment}</div>
                                  )) : <p className="right-hint">当前逻辑项目还没有教师写回记录。</p>}
                                </div>
                              </div>
                            </div>
                          </div>
                        </>
                      ) : null}
                    </>
                  );
                })()
              )}
            </div>
          )}

          {tab === "assistant" && (
            <div className="tch-panel fade-up">
              {loading && !assistantDashboard && <SkeletonLoader rows={4} type="card" />}
              {!loading && (
                <>
                  <div className="assistant-stage-hero">
                    <div className="assistant-stage-copy">
                      <div className="tm-project-cover-label">Teacher Operating Console</div>
                      <h2 style={{ marginTop: 6, marginBottom: 8 }}>教学助理</h2>
                      <p className="tch-desc" style={{ margin: 0 }}>这里专门负责“先看清，再决定去哪做”。老师先在这里浏览今天最值得处理的风险、干预和复查动态，再进入正式的项目或材料工作台。</p>
                      <div className="assistant-stage-highlights">
                        <div className="assistant-stage-highlight">
                          <strong>{(assistantDashboard?.pending_assessments || []).length}</strong>
                          <span>待判断项目</span>
                        </div>
                        <div className="assistant-stage-highlight">
                          <strong>{(assistantDashboard?.pending_interventions || []).length}</strong>
                          <span>待审核干预</span>
                        </div>
                        <div className="assistant-stage-highlight">
                          <strong>{(assistantDashboard?.followups || []).length}</strong>
                          <span>待复查对象</span>
                        </div>
                      </div>
                    </div>
                    <div className="assistant-stage-tools">
                      <div className="assistant-stage-status">
                        <span className="assistant-stage-status-dot" />
                        <span>今日待判断 {assistantPendingProjectCards.length}</span>
                        <span>最近更新 {assistantLastUpdated ? formatBJTime(assistantLastUpdated, false) : "刚刚"}</span>
                      </div>
                      <div className="assistant-stage-actions">
                        <button className="assistant-refresh-btn ghost" onClick={() => setAssistantView("queue")}>返回总览</button>
                        <button className="assistant-refresh-btn" onClick={loadAssistantDashboard}>刷新工作台</button>
                      </div>
                    </div>
                  </div>

                  <div className="assistant-nav-strip">
                    <button className={`assistant-nav-pill ${assistantView === "queue" ? "active" : ""}`} onClick={() => { if (!assistantDashboard) loadAssistantDashboard(); else setAssistantView("queue"); }}>
                      <strong>今日待处理</strong>
                      <span>看全局和今日入口</span>
                    </button>
                    <button className={`assistant-nav-pill ${assistantView === "assessment" ? "active" : ""}`} onClick={() => {
                      const first = assistantPendingProjectCards[0];
                      if (assistantAssessment) setAssistantView("assessment");
                      else if (first) loadAssistantAssessment(first.project_id, first.logical_project_id || "");
                      else loadAssistantDashboard();
                    }}>
                      <strong>批改与溯源</strong>
                      <span>只看风险和证据</span>
                    </button>
                    <button className={`assistant-nav-pill ${assistantView === "intervention" ? "active" : ""}`} onClick={() => assistantInterventionData ? setAssistantView("intervention") : loadAssistantInterventions()}>
                      <strong>教学干预中心</strong>
                      <span>审核班级动作</span>
                    </button>
                    <button className={`assistant-nav-pill ${assistantView === "impact" ? "active" : ""}`} onClick={() => {
                      if (assistantImpact) setAssistantView("impact");
                      else loadAssistantImpact();
                    }}>
                      <strong>干预效果看板</strong>
                      <span>看干预前后变化</span>
                    </button>
                    <button className={`assistant-nav-pill ${assistantView === "conversation" ? "active" : ""}`} onClick={() => {
                      const first = assistantPendingProjectCards[0];
                      if (assistantConversationEval) setAssistantView("conversation");
                      else if (first) loadAssistantConversationEval(first.project_id, first.logical_project_id || "");
                      else loadAssistantDashboard();
                    }}>
                      <strong>对话过程评估</strong>
                      <span>看能力变化轨迹</span>
                    </button>
                  </div>

                  {assistantView === "queue" && (
                    <div className="assistant-overview-board">
                      <div className="assistant-command-shell">
                        <div className="assistant-command-card">
                          <div className="assistant-command-head">
                            <div>
                              <div className="assistant-section-title">今日工作起点</div>
                              <h3 style={{ marginTop: 6, marginBottom: 6 }}>先从一个入口开始，而不是到处点</h3>
                              <p className="tch-desc" style={{ margin: 0 }}>这块只保留今天最重要的起点和三个正式入口。先看优先对象，再选择进入风险预览、教学干预或过程评估。</p>
                            </div>
                          </div>

                          <div className="assistant-command-kpis">
                            <div><span>团队</span><strong><AnimatedNumber value={assistantDashboard?.team_count || 0} /></strong></div>
                            <div><span>待判断</span><strong><AnimatedNumber value={(assistantDashboard?.pending_assessments || []).length} /></strong></div>
                            <div><span>待发送</span><strong><AnimatedNumber value={(assistantDashboard?.pending_interventions || []).length} /></strong></div>
                            <div><span>待复查</span><strong><AnimatedNumber value={(assistantDashboard?.followups || []).length} /></strong></div>
                          </div>

                          <div className="assistant-priority-card">
                            <div className="assistant-priority-top">
                              <span>当前最优先</span>
                              <strong>{assistantPendingProjectCards[0]?.project_name || "先看风险较高项目"}</strong>
                            </div>
                            <p>{assistantPendingProjectCards[0]?.current_summary || "系统会把最值得先判断的对象放在最前面，老师先看证据和风险，再进入正式工作台。"}</p>
                            {assistantPendingProjectCards[0] && (
                              <div className="tm-case-meta">
                                <span>{assistantPendingProjectCards[0].student_name || assistantPendingProjectCards[0].student_id}</span>
                                <span>{assistantPendingProjectCards[0].project_phase || "持续迭代"}</span>
                                <span>得分 {Number(assistantPendingProjectCards[0].latest_score || 0).toFixed(1)}</span>
                              </div>
                            )}
                          </div>

                          <div className="assistant-command-actions">
                            <button className="assistant-route-card hero" onClick={() => {
                              const first = assistantPendingProjectCards[0];
                              if (first) loadAssistantAssessment(first.project_id, first.logical_project_id || "");
                            }}>
                              <div className="assistant-route-top">
                                <span>01</span>
                                <strong>先去风险预览</strong>
                              </div>
                              <p>适合先看高风险项目的 Rubric 风险、证据链和轨迹，再决定是否进入正式批改。</p>
                              <em>进入 `批改与溯源`</em>
                            </button>
                            <button className="assistant-route-card" onClick={() => loadAssistantInterventions()}>
                              <div className="assistant-route-top">
                                <span>02</span>
                                <strong>去教学干预</strong>
                              </div>
                              <p>适合查看班级共性问题、学生画像和建议动作，统一审核并下发。</p>
                              <em>进入 `教学干预中心`</em>
                            </button>
                            <button className="assistant-route-card" onClick={() => {
                              const first = assistantPendingProjectCards[0];
                              if (first) loadAssistantConversationEval(first.project_id, first.logical_project_id || "");
                            }}>
                              <div className="assistant-route-top">
                                <span>03</span>
                                <strong>去过程评估</strong>
                              </div>
                              <p>适合回看多轮对话中的能力变化、介入命中和轮次诊断。</p>
                              <em>进入 `对话过程评估`</em>
                            </button>
                          </div>
                        </div>

                        <div className="assistant-stream-card">
                          <div className="assistant-stream-section">
                            <div className="assistant-section-title">今日优先项目</div>
                            <div className="assistant-signal-list">
                              {(assistantDashboard?.pending_assessments || []).slice(0, 3).map((item: any) => (
                                <button key={`${item.project_id}-${item.logical_project_id}`} className="assistant-signal-item" onClick={() => loadAssistantAssessment(item.project_id, item.logical_project_id || "")}>
                                  <strong>{item.project_name || "未命名项目"}</strong>
                                  <span>{item.student_name} · {item.project_phase || "持续迭代"}</span>
                                  <em>{(item.top_risks || []).slice(0, 2).map((risk: string) => getRuleDisplayName(risk)).join(" / ") || "待看证据"}</em>
                                </button>
                              ))}
                              {(assistantDashboard?.pending_assessments || []).length === 0 && <p className="right-hint">当前没有需要先判断的项目。</p>}
                            </div>
                          </div>

                          <div className="assistant-stream-section">
                            <div className="assistant-section-title">班级共性信号</div>
                            <div className="assistant-signal-list">
                              {(assistantDashboard?.shared_focus || []).slice(0, 3).map((item: any, idx: number) => (
                                <button key={`${item.team_id}-${item.rule_id}-${idx}`} className="assistant-signal-item" onClick={() => loadAssistantInterventions(item.team_id)}>
                                  <strong>{item.team_name}</strong>
                                  <span>{getRuleDisplayName(item.rule_id)}</span>
                                  <em>命中 {item.hit_count} 次</em>
                                </button>
                              ))}
                              {(assistantDashboard?.shared_focus || []).length === 0 && <p className="right-hint">当前没有突出的班级共性问题。</p>}
                            </div>
                          </div>

                          <div className="assistant-stream-section">
                            <div className="assistant-section-title">待复查动态</div>
                            <div className="assistant-signal-list">
                              {(assistantDashboard?.followups || []).slice(0, 3).map((item: any, idx: number) => (
                                <button key={`${item.intervention_id}-${idx}`} className="assistant-signal-item" onClick={() => item.project_id && loadAssistantConversationEval(item.project_id, item.logical_project_id || "")}>
                                  <strong>{item.student_name || item.target_student_id || "学生"}</strong>
                                  <span>{item.title}</span>
                                  <em>{item.status === "viewed" ? "学生已查看" : "等待复查"}</em>
                                </button>
                              ))}
                              {(assistantDashboard?.followups || []).length === 0 && <p className="right-hint">当前没有待复查对象。</p>}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {assistantView === "assessment" && (
                    <div className="assistant-workspace">
                      {(() => {
                        const activeQueueCard = assistantPendingProjectCards.find((item: any) => item.project_id === selectedProject && (item.logical_project_id || "") === (selectedLogicalProjectId || "")) || assistantPendingProjectCards[0] || null;

                        if (!assistantAssessment && !activeQueueCard) {
                          return <div className="ov-chart-card"><p className="right-hint">从“今日待处理”里选择一个项目，系统会在这里展开批改预览台。</p></div>;
                        }
                        if (assistantAssessment?.error) {
                          return <div className="ov-chart-card"><p className="right-hint">{assistantAssessment.error}</p></div>;
                        }

                        return (
                          <>
                            <div className="assistant-preview-board">
                              <div className="assistant-preview-header">
                                <div className="tm-project-cover assistant-cover-warm">
                                  <div>
                                    <div className="tm-project-cover-label">Risk Preview</div>
                                    <h2 style={{ marginTop: 6, marginBottom: 6 }}>{assistantAssessment?.project_name || activeQueueCard?.project_name || "待选择项目"}</h2>
                                    <div className="tm-case-meta">
                                      <span>{assistantAssessment?.student_id || activeQueueCard?.student_name || activeQueueCard?.student_id}</span>
                                      {selectedLogicalProjectId && <span>{compactId(selectedLogicalProjectId)}</span>}
                                      <span>{assistantAssessment?.project_phase || activeQueueCard?.project_phase || "持续迭代"}</span>
                                    </div>
                                    <div className="tm-case-summary" style={{ marginTop: 14 }}>
                                      <div className="tm-case-summary-title">当前判断</div>
                                      <div className="tm-case-summary-body">{assistantAssessment?.summary || activeQueueCard?.current_summary || "先看风险证据，再决定是否进入正式工作台。"}</div>
                                    </div>
                                  </div>
                                  <div className="tm-project-cover-score">
                                    <div>{assistantAssessment?.overall_score || activeQueueCard?.latest_score || 0}</div>
                                    <span>{assistantAssessment?.score_band || "待判断"}</span>
                                  </div>
                                </div>
                              </div>

                              <div className="assistant-preview-grid">
                                <div className="assistant-preview-card">
                                  <div className="assistant-section-title">Rubric 风险摘要</div>
                                  <div className="assistant-note-list">
                                    {(assistantAssessment?.rubric_items || []).slice(0, 4).map((item: any) => (
                                      <div key={item.item_id} className="tm-note-row warn">
                                        {item.item_name} · {item.score}/{item.max_score}
                                      </div>
                                    ))}
                                    {(assistantAssessment?.rubric_items || []).length === 0 && <p className="right-hint">暂无 Rubric 结果。</p>}
                                  </div>
                                </div>
                                <div className="assistant-preview-card">
                                  <div className="assistant-section-title">证据预览</div>
                                  <div className="assistant-note-list">
                                    {(assistantAssessment?.evidence_chain || []).slice(0, 3).map((item: any, idx: number) => (
                                      <div key={idx} className="tm-note-row good">“{item.quote}”</div>
                                    ))}
                                    {(assistantAssessment?.evidence_chain || []).length === 0 && <p className="right-hint">暂无证据链。</p>}
                                  </div>
                                </div>
                                <div className="assistant-preview-card">
                                  <div className="assistant-section-title">Agent 轨迹</div>
                                  <div className="assistant-note-list">
                                    <div className="tm-note-row good">策略：{assistantAssessment?.workflow_trace?.strategy || "assessment_pipeline"}</div>
                                    <div className="tm-note-row good">意图：{assistantAssessment?.workflow_trace?.intent || "综合咨询"}</div>
                                    <div className="tm-note-row good">意图形态：{assistantAssessment?.workflow_trace?.intent_shape || "single"}</div>
                                    <div className="tm-note-row warn">Agent：{(assistantAssessment?.workflow_trace?.agents_called || []).join(" / ") || "Assessment Agent"}</div>
                                    {assistantAssessment?.workflow_trace?.intent_reason && <div className="tm-note-row good">识别理由：{assistantAssessment.workflow_trace.intent_reason}</div>}
                                    {assistantAssessment?.workflow_trace?.agent_reasoning && <div className="tm-note-row good">编排理由：{assistantAssessment.workflow_trace.agent_reasoning}</div>}
                                  </div>
                                </div>
                              </div>

                              {(assistantAssessment?.quick_plan_24h?.length || assistantAssessment?.quick_plan_72h?.length) ? (
                                <div className="assistant-preview-grid">
                                  <div className="assistant-preview-card">
                                    <div className="assistant-section-title">24 小时紧急修正</div>
                                    <div className="assistant-note-list">
                                      {(assistantAssessment.quick_plan_24h || []).slice(0, 4).map((plan: any, idx: number) => (
                                        <div key={idx} className="tm-note-row warn">
                                          <strong>{plan.title || `紧急修正 ${idx + 1}`}</strong>
                                          {plan.rubric_item && <span style={{ marginLeft: 6 }}>· {plan.rubric_item}</span>}
                                          {plan.description && <div className="assistant-inline-note">{plan.description}</div>}
                                          <button
                                            className="tch-sm-btn"
                                            style={{ marginTop: 6 }}
                                            onClick={() => { void handleQuickPlanToIntervention(plan, "24h"); }}
                                          >
                                            转为干预任务
                                          </button>
                                        </div>
                                      ))}
                                      {(assistantAssessment.quick_plan_24h || []).length === 0 && <p className="right-hint">暂无 24 小时修正建议。</p>}
                                    </div>
                                  </div>
                                  <div className="assistant-preview-card">
                                    <div className="assistant-section-title">72 小时深度优化</div>
                                    <div className="assistant-note-list">
                                      {(assistantAssessment.quick_plan_72h || []).slice(0, 4).map((plan: any, idx: number) => (
                                        <div key={idx} className="tm-note-row good">
                                          <strong>{plan.title || `深度优化 ${idx + 1}`}</strong>
                                          {plan.rubric_item && <span style={{ marginLeft: 6 }}>· {plan.rubric_item}</span>}
                                          {plan.description && <div className="assistant-inline-note">{plan.description}</div>}
                                          <button
                                            className="tch-sm-btn"
                                            style={{ marginTop: 6 }}
                                            onClick={() => { void handleQuickPlanToIntervention(plan, "72h"); }}
                                          >
                                            转为干预任务
                                          </button>
                                        </div>
                                      ))}
                                      {(assistantAssessment.quick_plan_72h || []).length === 0 && <p className="right-hint">暂无 72 小时优化建议。</p>}
                                    </div>
                                  </div>
                                </div>
                              ) : null}

                              <div className="assistant-routing-grid">
                                <button className="assistant-route-card" onClick={() => loadFeedbackWorkspace(assistantAssessment.project_id, assistantAssessment.logical_project_id || "")}>
                                  <div className="assistant-route-top">
                                    <span>A</span>
                                    <strong>去材料反馈</strong>
                                  </div>
                                  <p>查看完整原文、写反馈、做划线批注、上传反馈文件。</p>
                                  <em>正式批改入口</em>
                                </button>
                                <button className="assistant-route-card" onClick={() => loadProjectWorkbench(assistantAssessment.project_id, assistantAssessment.logical_project_id || "")}>
                                  <div className="assistant-route-top">
                                    <span>B</span>
                                    <strong>去项目工作台</strong>
                                  </div>
                                  <p>查看证据链、阶段状态、竞赛预测和项目级评审记录。</p>
                                  <em>项目级分析入口</em>
                                </button>
                                <button className="assistant-route-card" onClick={() => loadAssistantConversationEval(assistantAssessment.project_id, assistantAssessment.logical_project_id || "")}>
                                  <div className="assistant-route-top">
                                    <span>C</span>
                                    <strong>去过程评估</strong>
                                  </div>
                                  <p>查看多轮对话中的能力变化、轮次诊断和教师干预命中情况。</p>
                                  <em>过程型评估入口</em>
                                </button>
                              </div>
                            </div>
                          </>
                        );
                      })()}
                    </div>
                  )}

                  {assistantView === "intervention" && (
                    <div className="assistant-workspace">
                      {!assistantInterventionData ? (
                        <div className="ov-chart-card"><p className="right-hint">请选择一个团队进入教学干预中心。</p></div>
                      ) : assistantInterventionData?.error ? (
                        <div className="ov-chart-card"><p className="right-hint">{assistantInterventionData.error}</p></div>
                      ) : (
                        <>
                          <div className="assistant-hero">
                            <div>
                              <div className="tm-project-cover-label">Instructor Assistant</div>
                              <h2 style={{ marginTop: 6, marginBottom: 6 }}>教学干预中心</h2>
                              <p className="tch-desc" style={{ margin: 0 }}>{assistantInterventionData.team_name} · 共性问题、班级洞察、学生画像和干预草稿都在同一个操作区里。</p>
                            </div>
                            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                              {((teamData?.my_teams || []) as any[]).map((team: any) => (
                                <button key={team.team_id} className={`tm-chip ${assistantSelectedTeamId === team.team_id ? "tm-chip-active" : ""}`} onClick={() => loadAssistantInterventions(team.team_id)}>{team.team_name}</button>
                              ))}
                            </div>
                          </div>

                          <div className="assistant-shell">
                            <div className="assistant-main-panel">
                              <div className="assistant-section">
                                <div className="assistant-section-title">班级共性问题</div>
                                <div className="assistant-list">
                                  {(assistantInterventionData.shared_problems || []).map((item: any) => (
                                    <div key={item.rule_id} className="assistant-focus-card">
                                      <div>
                                        <strong>{getRuleDisplayName(item.rule_id)}</strong>
                                        <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 6 }}>团队内命中 {item.hit_count} 次 · {item.priority}优先级</div>
                                      </div>
                                      <button className="tch-sm-btn" onClick={() => {
                                        const matched = (assistantInterventionData.suggested_plans || []).find((p: any) => String(p.title || "").includes(getRuleDisplayName(item.rule_id)));
                                        setAssistantDraftIntervention((v: any) => ({
                                          ...v,
                                          scope_type: "team",
                                          scope_id: assistantInterventionData.team_id,
                                          source_type: "class_plan",
                                          target_student_id: "",
                                          project_id: "",
                                          logical_project_id: "",
                                          title: matched?.title || `围绕${getRuleDisplayName(item.rule_id)}开展专项讲解`,
                                          reason_summary: matched?.reason_summary || `${getRuleDisplayName(item.rule_id)}是当前团队最集中出现的问题之一。`,
                                          action_items: matched?.action_items || ["讲解问题本质", "布置修正作业", "下一轮复查"],
                                          acceptance_criteria: matched?.acceptance_criteria || ["学生能解释问题成因", "项目材料补齐对应证据"],
                                          priority: item.priority === "高" ? "high" : "medium",
                                        }));
                                      }}>生成班级干预</button>
                                    </div>
                                  ))}
                                </div>
                              </div>
                              {assistantInterventionData.team_insight && !assistantInterventionData.team_insight.error && (
                                <div className="assistant-section">
                                  <div className="assistant-section-title">班级洞察快照</div>
                                  <div className="assistant-insight-grid">
                                    {(assistantInterventionData.team_insight.coverage_summary || []).map((item: any) => (
                                      <div key={item.topic} className="assistant-summary-card">
                                        <span>{item.topic}</span>
                                        <strong>{item.ratio}%</strong>
                                      </div>
                                    ))}
                                  </div>
                                  <div className="assistant-note-list" style={{ marginTop: 12 }}>
                                    {(assistantInterventionData.team_insight.suggested_teaching_interventions || []).slice(0, 2).map((item: any, idx: number) => (
                                      <div key={idx} className="tm-note-row good">{item.plan}</div>
                                    ))}
                                  </div>
                                </div>
                              )}
                              <div className="assistant-section">
                                <div className="assistant-section-title">学生能力画像</div>
                                <div className="assistant-student-grid">
                                  {(assistantInterventionData.students || []).map((stu: any) => (
                                    <div key={stu.student_id} className="assistant-student-card">
                                      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                                        <strong>{stu.display_name}</strong>
                                        <span className="tm-case-badge">{stu.latest_phase || "持续迭代"}</span>
                                      </div>
                                      <div className="tm-case-meta">
                                        <span>均分 {stu.avg_score}</span>
                                        <span>{stu.dominant_intent || dominantIntent(stu.intent_distribution)}</span>
                                        <span>{stu.risk_count} 个风险</span>
                                      </div>
                                      <div className="tm-case-inline-summary" style={{ marginTop: 8 }}>{stu.student_case_summary || "暂无学生摘要"}</div>
                                      <div className="tm-case-inline-summary" style={{ marginTop: 8 }}>{stu.teacher_intervention || "老师可进行一对一辅导。"}</div>
                                      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                                        <button className="tch-sm-btn" onClick={() => setAssistantDraftIntervention({
                                          scope_type: "student",
                                          scope_id: stu.student_id,
                                          source_type: "student_profile",
                                          target_student_id: stu.student_id,
                                          project_id: "",
                                          logical_project_id: "",
                                          title: `给${stu.display_name}的个性化干预任务`,
                                          reason_summary: stu.teacher_intervention || "该学生需要针对性跟进。",
                                          action_items: ["老师做一次针对性点评", "学生补齐关键证据", "一周后复查"],
                                          acceptance_criteria: ["学生完成补充材料", "下一轮得分提升或风险下降"],
                                          priority: stu.risk_count >= 3 ? "high" : "medium",
                                        })}>按学生起草</button>
                                        {(stu.projects || [])[0] && (
                                          <button className="tch-sm-btn" onClick={() => setAssistantDraftIntervention({
                                            scope_type: "project",
                                            scope_id: `project-${stu.student_id}`,
                                            source_type: "project_case",
                                            target_student_id: stu.student_id,
                                            project_id: `project-${stu.student_id}`,
                                            logical_project_id: stu.projects[0].project_id,
                                            title: `${stu.projects[0].project_name} 项目干预任务`,
                                            reason_summary: stu.projects[0].teacher_intervention || stu.teacher_intervention || "该项目需要专项介入。",
                                            action_items: stu.projects[0].latest_task?.acceptance_criteria || ["补齐项目关键证据", "完成下一步任务"],
                                            acceptance_criteria: stu.projects[0].latest_task?.acceptance_criteria || ["学生完成指定项目修改"],
                                            priority: (stu.projects[0].top_risks || []).length >= 2 ? "high" : "medium",
                                          })}>按项目起草</button>
                                        )}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              </div>
                              <div className="assistant-section">
                                <div className="assistant-section-title">条件筛选 & 智能批量干预</div>
                                <p className="tch-desc">可先输入班级/届别，再点击“智能筛选”自动挑选落后且高风险的项目，作为本次干预范围。</p>
                                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
                                  <input
                                    className="tm-input"
                                    style={{ maxWidth: 180 }}
                                    placeholder="班级 ID（可选）"
                                    value={classId}
                                    onChange={(e) => setClassId(e.target.value)}
                                  />
                                  <input
                                    className="tm-input"
                                    style={{ maxWidth: 180 }}
                                    placeholder="届别/期数（可选）"
                                    value={cohortId}
                                    onChange={(e) => setCohortId(e.target.value)}
                                  />
                                  <select
                                    className="tm-input"
                                    style={{ maxWidth: 160 }}
                                    value={assistantDraftIntervention.priority || "medium"}
                                    onChange={(e) => setAssistantDraftIntervention((v: any) => ({ ...v, priority: e.target.value }))}
                                  >
                                    <option value="high">优先筛选高风险项目</option>
                                    <option value="medium">一般优先级</option>
                                    <option value="low">较低优先级</option>
                                  </select>
                                  <button className="tch-sm-btn" onClick={runAssistantSmartSelect}>智能筛选候选项目</button>
                                </div>
                                {assistantSmartSelectResult && (
                                  <div className="assistant-list compact">
                                    <div className="tm-note-row good">共找到 {assistantSmartSelectResult.total_candidates ?? 0} 个候选项目，当前选中 {assistantSmartSelectResult.selected_count ?? 0} 个。</div>
                                    {(assistantSmartSelectResult.items || []).slice(0, 8).map((item: any, idx: number) => (
                                      <div key={`${item.project_id}-${idx}`} className="assistant-queue-card compact">
                                        <div>
                                          <strong>{item.project_id}</strong>
                                          <div className="tm-case-meta">
                                            <span>{item.student_id}</span>
                                            <span>分数 {Number(item.overall_score || 0).toFixed(1)}</span>
                                            <span>风险 {item.risk_count}</span>
                                            <span>{item.project_stage}</span>
                                          </div>
                                          {item.latest_bottleneck && <div className="tm-case-inline-summary" style={{ marginTop: 4 }}>{item.latest_bottleneck}</div>}
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            </div>
                            <div className="assistant-side-panel">
                              <div className="assistant-side-card sticky">
                                <div className="assistant-section-title">干预草稿编辑区</div>
                                <p className="tch-desc" style={{ marginTop: 0 }}>老师可以在这里修改 AI 起草的干预任务，再审核后发送到学生端。</p>
                                <div className="assistant-form-grid">
                                  <div>
                                    <label className="assistant-label">标题</label>
                                    <input className="tm-input" value={assistantDraftIntervention.title || ""} onChange={(e) => setAssistantDraftIntervention((v: any) => ({ ...v, title: e.target.value }))} />
                                  </div>
                                  <div>
                                    <label className="assistant-label">优先级</label>
                                    <select className="tm-input" value={assistantDraftIntervention.priority || "medium"} onChange={(e) => setAssistantDraftIntervention((v: any) => ({ ...v, priority: e.target.value }))}>
                                      <option value="high">高</option>
                                      <option value="medium">中</option>
                                      <option value="low">低</option>
                                    </select>
                                  </div>
                                </div>
                                <div style={{ marginTop: 12 }}>
                                  <label className="assistant-label">原因说明</label>
                                  <textarea className="tm-input assistant-textarea" value={assistantDraftIntervention.reason_summary || ""} onChange={(e) => setAssistantDraftIntervention((v: any) => ({ ...v, reason_summary: e.target.value }))} />
                                </div>
                                <div className="assistant-form-grid" style={{ marginTop: 12 }}>
                                  <div>
                                    <label className="assistant-label">行动项（每行一条）</label>
                                    <textarea className="tm-input assistant-textarea small" value={Array.isArray(assistantDraftIntervention.action_items) ? assistantDraftIntervention.action_items.join("\n") : (assistantDraftIntervention.action_items || "")} onChange={(e) => setAssistantDraftIntervention((v: any) => ({ ...v, action_items: e.target.value }))} />
                                  </div>
                                  <div>
                                    <label className="assistant-label">验收标准（每行一条）</label>
                                    <textarea className="tm-input assistant-textarea small" value={Array.isArray(assistantDraftIntervention.acceptance_criteria) ? assistantDraftIntervention.acceptance_criteria.join("\n") : (assistantDraftIntervention.acceptance_criteria || "")} onChange={(e) => setAssistantDraftIntervention((v: any) => ({ ...v, acceptance_criteria: e.target.value }))} />
                                  </div>
                                </div>
                                <div style={{ display: "flex", gap: 10, marginTop: 14, flexWrap: "wrap" }}>
                                  <button className="tch-sm-btn" onClick={() => saveAssistantIntervention(false)}>保存草稿</button>
                                  <button className="topbar-btn" onClick={() => saveAssistantIntervention(true)}>审核后发送到学生端</button>
                                </div>
                              </div>
                              <div className="assistant-side-card">
                                <div className="assistant-section-title">已生成的干预记录</div>
                                <div className="assistant-list compact">
                                  {(assistantInterventionData.existing_interventions || []).length > 0 ? (assistantInterventionData.existing_interventions || []).map((item: any, idx: number) => (
                                    <div key={`${item.intervention_id}-${idx}`} className="assistant-queue-card compact">
                                      <div>
                                        <strong>{item.title}</strong>
                                        <div className="tm-case-meta">
                                          <span>{item.scope_type}</span>
                                          <span>{item.priority}</span>
                                          <span>{item.status}</span>
                                        </div>
                                        <div className="tm-case-inline-summary" style={{ marginTop: 8 }}>{item.reason_summary || "暂无说明"}</div>
                                      </div>
                                      <span className="tm-case-badge">{item.status}</span>
                                    </div>
                                  )) : <p className="right-hint">当前团队还没有已保存的干预记录。</p>}
                                </div>
                              </div>
                            </div>
                          </div>
                        </>
                      )}
                    </div>
                  )}

                  {assistantView === "impact" && (
                    <div className="assistant-workspace">
                      {(() => {
                        if (!assistantImpact) {
                          return <div className="ov-chart-card"><p className="right-hint">先从“教学干预中心”或“今日待处理”下发一些干预任务，系统才有可分析的数据。</p></div>;
                        }
                        if (assistantImpact.error) {
                          return <div className="ov-chart-card"><p className="right-hint">{assistantImpact.error}</p></div>;
                        }

                        const summary = assistantImpact.summary || {};
                        const statusCounts = summary.status_counts || {};
                        const effectSummary = summary.effect_counts || {};
                        const byPriority = (assistantImpact.by_priority || []) as any[];
                        const timeline = (assistantImpact.timeline || []) as any[];
                        const items = (assistantImpact.items || []) as any[];

                        const positiveTotal = (Number(effectSummary.positive || 0) + Number(effectSummary.neutral || 0) + Number(effectSummary.negative || 0));
                        const positiveRate = Math.round((Number(effectSummary.positive || 0) / Math.max(positiveTotal, 1)) * 100);

                        const positiveCases = [...items]
                          .filter((it: any) => it.effect === "positive")
                          .sort((a: any, b: any) => (b.score_delta || 0) - (a.score_delta || 0))
                          .slice(0, 4);
                        const negativeCases = [...items]
                          .filter((it: any) => it.effect === "negative")
                          .sort((a: any, b: any) => (a.score_delta || 0) - (b.score_delta || 0))
                          .slice(0, 3);
                        const timelineSeries = timeline.map((row: any) => ({ label: row.date, value: row.effective || row.total || 0 }));

                        return (
                          <>
                            <div className="assistant-hero">
                              <div>
                                <div className="tm-project-cover-label">Impact Dashboard</div>
                                <h2 style={{ marginTop: 6, marginBottom: 6 }}>教学干预效果看板</h2>
                                <p className="tch-desc" style={{ margin: 0 }}>系统会自动对“发送到学生端”的教师干预任务做事后回看，帮助老师了解哪些动作最有用。</p>
                              </div>
                                <div className="assistant-command-kpis">
                                  <div><span>累计干预</span><strong><AnimatedNumber value={summary.total_interventions || 0} /></strong></div>
                                  <div><span>已形成闭环</span><strong><AnimatedNumber value={summary.effective_interventions || 0} /></strong></div>
                                  <div><span>正向占比</span><strong>{positiveRate}%</strong></div>
                                  <div><span>平均得分提升</span><strong>{Number(summary.avg_score_gain || 0).toFixed(2)}</strong></div>
                                </div>
                            </div>

                            <div className="assistant-shell">
                              <div className="assistant-main-panel">
                                <div className="assistant-section">
                                  <div className="assistant-section-title">干预效果分布</div>
                                  <div className="assistant-insight-grid">
                                    <div className="assistant-summary-card">
                                      <span>正向改善</span>
                                      <strong>{Number(effectSummary.positive || 0)}</strong>
                                    </div>
                                    <div className="assistant-summary-card">
                                      <span>基本持平</span>
                                      <strong>{Number(effectSummary.neutral || 0)}</strong>
                                    </div>
                                    <div className="assistant-summary-card">
                                      <span>需要复盘</span>
                                      <strong>{Number(effectSummary.negative || 0)}</strong>
                                    </div>
                                    <div className="assistant-summary-card">
                                      <span>尚无后续数据</span>
                                      <strong>{Number(effectSummary.no_followup || 0)}</strong>
                                    </div>
                                  </div>
                                </div>

                                <div className="assistant-section">
                                  <div className="assistant-section-title">干预执行时间线</div>
                                  <div className="ov-chart-card">
                                    {timelineSeries.length > 1 ? (
                                      <AreaChart data={timelineSeries} width={360} height={110} color="var(--accent)" />
                                    ) : (
                                      <p className="right-hint">当前干预样本还不多，随着更多班级使用会自动补齐时间线。</p>
                                    )}
                                  </div>
                                </div>

                                <div className="assistant-section">
                                  <div className="assistant-section-title">典型提升案例</div>
                                  <div className="assistant-list">
                                    {positiveCases.length === 0 && <p className="right-hint">暂时还没有显著提升的干预案例。</p>}
                                    {positiveCases.map((item: any, idx: number) => (
                                      <div key={item.intervention_id || idx} className="assistant-queue-card compact">
                                        <div>
                                          <strong>{item.title || "未命名干预任务"}</strong>
                                          <div className="tm-case-meta">
                                            <span>{item.student_id || "学生"}</span>
                                            <span>{item.class_id || "班级未标注"}</span>
                                            <span>优先级 {item.priority}</span>
                                          </div>
                                          <div className="tm-case-inline-summary" style={{ marginTop: 8 }}>
                                            干预后综合得分提升 {item.score_delta?.toFixed ? item.score_delta.toFixed(2) : Number(item.score_delta || 0).toFixed(2)} 分，风险等级从
                                            {item.risk_level_before || "?"} 调整为 {item.risk_level_after || "?"}。
                                          </div>
                                        </div>
                                        <span className="tm-case-badge">正向</span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              </div>

                              <div className="assistant-side-panel">
                                <div className="assistant-side-card">
                                  <div className="assistant-section-title">按优先级回看</div>
                                  <div className="assistant-note-list">
                                    {byPriority.length === 0 && <div className="tm-note-row good">还没有足够数据区分不同优先级的效果。</div>}
                                    {byPriority.map((row: any) => (
                                      <div key={row.priority} className="tm-note-row good">
                                        {row.priority === "high" ? "高优" : row.priority === "medium" ? "中优" : "低优"} · {row.count} 条 · 平均提升 {Number(row.avg_score_gain || 0).toFixed(2)} 分，风险变化 {Number(row.avg_risk_delta || 0).toFixed(3)}
                                      </div>
                                    ))}
                                  </div>
                                </div>

                                <div className="assistant-side-card">
                                  <div className="assistant-section-title">需要复盘的干预</div>
                                  <div className="assistant-note-list">
                                    {negativeCases.length === 0 && <div className="tm-note-row warn">暂时没有明显“效果不佳”的干预，后续可以重点关注这里。</div>}
                                    {negativeCases.map((item: any, idx: number) => (
                                      <div key={item.intervention_id || idx} className="tm-note-row warn">
                                        {item.title || "未命名干预任务"} · 学生 {item.student_id || "学生"} · 分数变化 {item.score_delta?.toFixed ? item.score_delta.toFixed(2) : Number(item.score_delta || 0).toFixed(2)}
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              </div>
                            </div>
                          </>
                        );
                      })()}
                    </div>
                  )}

                  {assistantView === "conversation" && (
                    <div className="assistant-workspace">
                      {(() => {
                        const conversationProjects = (projectWorkbenchSummary?.logical_projects || []).length > 0
                          ? (projectWorkbenchSummary?.logical_projects || []).map((item: any) => ({
                              project_id: selectedProject,
                              logical_project_id: item.logical_project_id,
                              project_name: item.project_name,
                              project_phase: item.project_phase,
                              latest_score: item.latest_score,
                              submission_count: item.submission_count,
                              top_risks: item.top_risks || [],
                              dominant_intent: item.dominant_intent || "综合咨询",
                              summary: item.summary,
                              project_order: item.project_order,
                            }))
                          : assistantPendingProjectCards.map((item: any, idx: number) => ({
                              project_id: item.project_id,
                              logical_project_id: item.logical_project_id,
                              project_name: item.project_name,
                              project_phase: item.project_phase,
                              latest_score: item.latest_score,
                              submission_count: item.submission_count,
                              top_risks: item.top_risks || [],
                              dominant_intent: item.dominant_intent || "综合咨询",
                              summary: item.current_summary || "暂无摘要",
                              project_order: idx + 1,
                            }));

                        if (!assistantConversationEval && conversationProjects.length === 0) {
                          return <div className="ov-chart-card"><p className="right-hint">先选择一个项目，再生成对话过程评估。</p></div>;
                        }
                        if (assistantConversationEval?.error) {
                          return <div className="ov-chart-card"><p className="right-hint">{assistantConversationEval.error}</p></div>;
                        }

                        return (
                          <>
                            <div className="assistant-section" style={{ marginBottom: 18 }}>
                              <div className="assistant-section-title">多项目入口</div>
                              <div className="project-compare-grid">
                                {conversationProjects.map((item: any) => (
                                  <button
                                    key={`${item.project_id}-${item.logical_project_id}`}
                                    className={`project-compare-card ${item.logical_project_id === selectedLogicalProjectId ? "active" : ""}`}
                                    onClick={() => loadAssistantConversationEval(item.project_id, item.logical_project_id || "")}
                                  >
                                    <div className="project-compare-top">
                                      <span className="project-compare-index">{serialLabel("项目", item.project_order)}</span>
                                      <span className="tm-case-badge">{item.project_phase || "持续迭代"}</span>
                                    </div>
                                    <strong>{item.project_name}</strong>
                                    <div className="tm-case-meta">
                                      <span>{compactId(item.logical_project_id || "")}</span>
                                      <span>{item.submission_count} 次提交</span>
                                      <span>{Number(item.latest_score || 0).toFixed(1)}</span>
                                    </div>
                                    <div className="tm-case-inline-summary" style={{ marginTop: 8 }}>{item.summary}</div>
                                    <div className="tm-corridor-tags" style={{ marginTop: 10 }}>
                                      <span className="tm-smart-chip">{item.dominant_intent || "综合咨询"}</span>
                                      {(item.top_risks || []).slice(0, 2).map((risk: string) => <span key={risk} className="tm-smart-chip">{getRuleDisplayName(risk)}</span>)}
                                    </div>
                                  </button>
                                ))}
                              </div>
                            </div>

                            {!assistantConversationEval ? (
                              <div className="ov-chart-card"><p className="right-hint">请选择一张项目卡片，查看该项目的对话过程评估。</p></div>
                            ) : (
                              <>
                                <div className="tm-project-cover assistant-cover-warm">
                                  <div>
                                    <div className="tm-project-cover-label">Conversation Traceability</div>
                                    <h2 style={{ marginTop: 6, marginBottom: 6 }}>多轮对话能力评估</h2>
                                    <div className="tm-case-meta">
                                      <span>{assistantConversationEval.turn_count} 轮有效对话</span>
                                      <span>{compactId(assistantConversationEval.logical_project_id || "当前项目")}</span>
                                      {(assistantConversationEval.trace_summary?.agents_called || []).length > 0 && <span>{assistantConversationEval.trace_summary.agents_called.slice(0, 2).join(" / ")}</span>}
                                    </div>
                                    <div className="tm-case-summary" style={{ marginTop: 14 }}>
                                      <div className="tm-case-summary-title">过程评估总述</div>
                                      <div className="tm-case-summary-body">{assistantConversationEval.overall_summary}</div>
                                    </div>
                                  </div>
                                  <div className="tm-project-cover-score">
                                    <div>{assistantConversationEval.turn_count || 0}</div>
                                    <span>对话轮次</span>
                                  </div>
                                </div>
                                <div className="assistant-shell">
                                  <div className="assistant-main-panel">
                                    <div className="assistant-section">
                                      <div className="assistant-section-title">Capability Map</div>
                                      <div className="assistant-capability-grid">
                                        <RadarChart data={(assistantConversationEval.capability_scores || []).map((item: any) => ({ label: item.label, value: item.score, max: 5 }))} size={240} />
                                        <div className="assistant-note-list">
                                          {(assistantConversationEval.capability_scores || []).map((item: any) => (
                                            <div key={item.dimension} className="tm-note-row good">{item.label}：{item.score}/5</div>
                                          ))}
                                        </div>
                                      </div>
                                    </div>
                                    <div className="assistant-section">
                                      <div className="assistant-section-title">三轮对话行为诊断</div>
                                      <div className="assistant-list">
                                        {(assistantConversationEval.round_reports || []).map((item: any) => (
                                          <div key={item.round_index} className="assistant-round-card">
                                            <strong>{item.title}</strong>
                                            <div className="tm-case-meta">
                                              <span>{item.phase}</span>
                                              <span>{item.dominant_intent}</span>
                                              <span>{item.score}/10</span>
                                            </div>
                                            <div className="tm-case-inline-summary" style={{ marginTop: 8 }}>{item.summary}</div>
                                            {item.quote && <div className="assistant-quote-inline" style={{ marginTop: 8 }}>“{item.quote}”</div>}
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  </div>
                                  <div className="assistant-side-panel">
                                    <div className="assistant-side-card">
                                      <div className="assistant-section-title">Trace Agent 来源</div>
                                      <div className="assistant-note-list">
                                        <div className="tm-note-row good">工作流策略：{assistantConversationEval.trace_summary?.workflow_strategy || "trace_eval"}</div>
                                        <div className="tm-note-row good">参与 Agent：{(assistantConversationEval.trace_summary?.agents_called || []).length > 0 ? assistantConversationEval.trace_summary.agents_called.join(" / ") : "Trace Agent"}</div>
                                        {(assistantConversationEval.trace_summary?.matched_teacher_interventions || []).length > 0 ? (
                                          assistantConversationEval.trace_summary.matched_teacher_interventions.map((item: any, idx: number) => (
                                            <div key={`${item.title}-${idx}`} className="tm-note-row warn">命中教师干预：{item.title}{item.reason_summary ? ` · ${item.reason_summary}` : ""}</div>
                                          ))
                                        ) : (
                                          <div className="tm-note-row good">当前轮次没有命中教师干预，评估主要来自对话历史与诊断结果。</div>
                                        )}
                                      </div>
                                    </div>
                                    <div className="assistant-side-card">
                                      <div className="assistant-section-title">证据引用</div>
                                      <div className="assistant-note-list">
                                        {(assistantConversationEval.evidence_quotes || []).map((item: any, idx: number) => (
                                          <div key={idx} className="tm-note-row warn">[{formatBJTime(item.created_at)}] “{item.quote}”</div>
                                        ))}
                                      </div>
                                    </div>
                                  </div>
                                </div>
                              </>
                            )}
                          </>
                        );
                      })()}
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {tab === "class" && (
            <div className="tch-panel fade-up">
              {loading && <SkeletonLoader rows={4} type="card" />}

              {/* ── Create Team Modal ── */}
              {showCreateTeam && (
                <div className="tm-modal-overlay" onClick={() => { setShowCreateTeam(false); setCreatedInviteCode(""); }}>
                  <div className="tm-modal" onClick={(e) => e.stopPropagation()}>
                    {!createdInviteCode ? (
                      <>
                        <h3 style={{ margin: "0 0 16px" }}>创建新团队</h3>
                        <input className="tm-input" placeholder="输入团队名称" value={newTeamName} onChange={(e) => setNewTeamName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && handleCreateTeam()} autoFocus />
                        <div style={{ display: "flex", gap: 8, marginTop: 16, justifyContent: "flex-end" }}>
                          <button className="tch-sm-btn" onClick={() => { setShowCreateTeam(false); setCreatedInviteCode(""); }}>取消</button>
                          <button className="tch-sm-btn" style={{ background: "var(--accent)", color: "#fff" }} onClick={handleCreateTeam} disabled={!newTeamName.trim()}>创建</button>
                        </div>
                      </>
                    ) : (
                      <>
                        <h3 style={{ margin: "0 0 8px", color: "var(--tch-success)" }}>团队创建成功</h3>
                        <p style={{ color: "var(--text-muted)", fontSize: 13, margin: "0 0 16px" }}>将以下邀请码分享给学生，学生在个人中心输入即可加入团队</p>
                        <div className="tm-invite-display">
                          <span className="tm-invite-code">{createdInviteCode}</span>
                          <button className="tch-sm-btn" onClick={() => { navigator.clipboard?.writeText(createdInviteCode); }}>复制</button>
                        </div>
                        <button className="tch-sm-btn" style={{ marginTop: 16, width: "100%" }} onClick={() => { setShowCreateTeam(false); setCreatedInviteCode(""); }}>完成</button>
                      </>
                    )}
                  </div>
                </div>
              )}

              {/* ── Top: Team selector chips ── */}
              {teamData && !loading && (
                <>
                  <div className="cls-breadcrumb" style={{ marginBottom: 12 }}>
                    <span className={`cls-crumb-item ${teamView === "comparison" ? "active" : ""}`} onClick={() => { setTeamView("comparison"); setSelectedTeamId(""); setSelectedTeamStudentId(""); setSelectedTeamProjectId(""); }}>全部团队</span>
                    {selectedTeamId && (() => { const t = [...(teamData.my_teams ?? []), ...(teamData.other_teams ?? [])].find((x: any) => x.team_id === selectedTeamId); return t ? (<><span className="cls-crumb-sep">›</span><span className={`cls-crumb-item ${teamView === "team-detail" ? "active" : ""}`} onClick={() => { setTeamView("team-detail"); setSelectedTeamStudentId(""); setSelectedTeamProjectId(""); }}>{t.team_name}</span></>) : null; })()}
                    {selectedTeamStudentId && (() => { const t = (teamData.my_teams ?? []).find((x: any) => x.team_id === selectedTeamId); const s = t?.students?.find((x: any) => x.student_id === selectedTeamStudentId); return s ? (<><span className="cls-crumb-sep">›</span><span className={`cls-crumb-item ${teamView === "student-detail" ? "active" : ""}`} onClick={() => { setTeamView("student-detail"); setSelectedTeamProjectId(""); }}>{s.display_name}</span></>) : null; })()}
                    {selectedTeamProjectId && (() => { const t = (teamData.my_teams ?? []).find((x: any) => x.team_id === selectedTeamId); const s = t?.students?.find((x: any) => x.student_id === selectedTeamStudentId); const p = s?.projects?.find((x: any) => x.project_id === selectedTeamProjectId); return p ? (<><span className="cls-crumb-sep">›</span><span className="cls-crumb-item active">{p.project_name}</span></>) : null; })()}
                    <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
                      <button onClick={() => { setShowCreateTeam(true); setCreatedInviteCode(""); setNewTeamName(""); }} className="tch-sm-btn" style={{ background: "var(--accent)", color: "#fff" }}>+ 创建团队</button>
                      <button onClick={loadTeams} className="tch-sm-btn">🔄 刷新</button>
                    </div>
                  </div>

                  <div className="tm-chips">
                    <button className={`tm-chip ${teamView === "comparison" && !selectedTeamId ? "tm-chip-active" : ""}`} onClick={() => { setTeamView("comparison"); setSelectedTeamId(""); }}>📊 全部对比</button>
                    {(teamData.my_teams ?? []).map((t: any) => (
                      <button key={t.team_id} className={`tm-chip tm-chip-mine ${selectedTeamId === t.team_id ? "tm-chip-active" : ""}`} onClick={() => { setSelectedTeamId(t.team_id); setTeamView("team-detail"); setSelectedTeamStudentId(""); setSelectedTeamProjectId(""); }}>
                        <span className="tm-chip-dot tm-dot-mine" />{t.team_name}
                      </button>
                    ))}
                    {(teamData.other_teams ?? []).map((t: any) => (
                      <button key={t.team_id} className={`tm-chip ${selectedTeamId === t.team_id ? "tm-chip-active" : ""}`} onClick={() => { setSelectedTeamId(t.team_id); setTeamView("team-detail"); setSelectedTeamStudentId(""); setSelectedTeamProjectId(""); }}>
                        <span className="tm-chip-dot tm-dot-other" />{t.team_name}
                      </button>
                    ))}
                  </div>
                </>
              )}

              {/* ══════ VIEW: Comparison ══════ */}
              {teamView === "comparison" && !loading && teamData && (() => {
                const all = [...(teamData.my_teams ?? []), ...(teamData.other_teams ?? [])];
                if (!all.length) return (
                  <div style={{ textAlign: "center", padding: "40px 20px" }}>
                    <div style={{ fontSize: 40, marginBottom: 12 }}>🏫</div>
                    <h3 style={{ color: "var(--text-primary)", margin: "0 0 8px" }}>还没有团队</h3>
                    <p style={{ color: "var(--text-muted)", fontSize: 13 }}>点击上方「创建团队」按钮开始</p>
                  </div>
                );
                const sortedAll = [...all].sort((a: any, b: any) => b.avg_score - a.avg_score);
                const myTeams = teamData.my_teams ?? [];
                const maxScore = Math.max(1, ...all.map((t: any) => Number(t.avg_score || 0)));
                const maxSubs = Math.max(1, ...all.map((t: any) => Number(t.total_submissions || 0)));
                const maxDensity = Math.max(1, ...all.map((t: any) => Number(t.submission_density || 0)));
                return (
                  <>
                    <h2 style={{ marginTop: 0 }}>团队横向对比</h2>
                    <p className="tch-desc">把团队对比做成可点击的病例入口。悬停看摘要，点击直接进入团队层级。</p>

                    <div className="ov-kpi-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
                      <div className="ov-kpi-card"><div className="ov-kpi-icon" style={{ background: "rgba(107,138,255,0.15)", color: "var(--accent)" }}>🏫</div><div className="ov-kpi-value"><AnimatedNumber value={all.length} /></div><div className="ov-kpi-label">团队总数</div></div>
                      <div className="ov-kpi-card"><div className="ov-kpi-icon" style={{ background: "rgba(115,204,255,0.15)", color: "#73ccff" }}>👥</div><div className="ov-kpi-value"><AnimatedNumber value={all.reduce((a: number, t: any) => a + t.student_count, 0)} /></div><div className="ov-kpi-label">学生总数</div></div>
                      <div className="ov-kpi-card"><div className="ov-kpi-icon" style={{ background: "rgba(92,189,138,0.15)", color: "var(--tch-success)" }}>📝</div><div className="ov-kpi-value"><AnimatedNumber value={all.reduce((a: number, t: any) => a + t.total_submissions, 0)} /></div><div className="ov-kpi-label">提交总量</div></div>
                      <div className="ov-kpi-card"><div className="ov-kpi-icon" style={{ background: "rgba(232,168,76,0.15)", color: "var(--tch-warning)" }}>⭐</div><div className="ov-kpi-value"><AnimatedNumber value={all.length > 0 ? all.reduce((a: number, t: any) => a + t.avg_score, 0) / all.length : 0} decimals={1} /></div><div className="ov-kpi-label">全局均分</div></div>
                    </div>

                    <div className="ov-chart-card" style={{ marginBottom: 20 }}>
                      <h3>团队病例廊道</h3>
                      <p className="tch-desc">每个团队卡都包含均分、提交密度、风险率、当前高频求助方向。点击即可进入。</p>
                      <div className="tm-corridor">
                        {sortedAll.map((t: any, idx: number) => {
                          const intents = intentEntries(t.intent_distribution);
                          const dominant = dominantIntent(t.intent_distribution);
                          const scorePct = Math.max(8, Math.min(100, (Number(t.avg_score || 0) / maxScore) * 100));
                          const subPct = Math.max(8, Math.min(100, (Number(t.total_submissions || 0) / maxSubs) * 100));
                          const densityPct = Math.max(8, Math.min(100, (Number(t.submission_density || 0) / maxDensity) * 100));
                          return (
                            <button
                              key={t.team_id}
                              className={`tm-corridor-card ${t.is_mine ? "mine" : ""}`}
                              onClick={() => { setSelectedTeamId(t.team_id); setTeamView("team-detail"); setSelectedTeamStudentId(""); setSelectedTeamProjectId(""); }}
                            >
                              <div className="tm-corridor-top">
                                <div>
                                  <div className="tm-corridor-rank">#{idx + 1} {t.is_mine ? "我的团队" : "其他团队"}</div>
                                  <div className="tm-corridor-name">{t.team_name}</div>
                                </div>
                                <div className="tm-corridor-arrow">查看病例 →</div>
                              </div>
                              <div className="tm-corridor-meta">
                                <span>{t.student_count} 人</span>
                                <span>{t.active_students || 0} 人活跃</span>
                                <span>{t.teacher_name || "未绑定教师"}</span>
                              </div>
                              <div className="tm-corridor-bars">
                                <div className="tm-corridor-barline">
                                  <span>均分</span>
                                  <div><i style={{ width: `${scorePct}%` }} /></div>
                                  <b>{Number(t.avg_score || 0).toFixed(1)}</b>
                                </div>
                                <div className="tm-corridor-barline">
                                  <span>提交量</span>
                                  <div><i style={{ width: `${subPct}%`, background: "linear-gradient(90deg, rgba(115,204,255,0.28), #73ccff)" }} /></div>
                                  <b>{t.total_submissions}</b>
                                </div>
                                <div className="tm-corridor-barline">
                                  <span>密度</span>
                                  <div><i style={{ width: `${densityPct}%`, background: "linear-gradient(90deg, rgba(92,189,138,0.28), #5cbd8a)" }} /></div>
                                  <b>{Number(t.submission_density || 0).toFixed(1)}</b>
                                </div>
                              </div>
                              <div className="tm-corridor-tags">
                                <span className="tm-smart-chip" style={{ background: "rgba(224,112,112,0.12)", color: "var(--tch-danger)" }}>风险率 {Number(t.risk_rate || 0).toFixed(0)}%</span>
                                <span className="tm-smart-chip">{dominant}</span>
                                {(t.top_risks || []).slice(0, 2).map((risk: string) => <span key={risk} className="tm-smart-chip">{getRuleDisplayName(risk)}</span>)}
                              </div>
                              <div className="tm-corridor-tooltip">
                                <strong>团队摘要</strong>
                                {(t.care_points || []).slice(0, 3).map((point: string, i: number) => <span key={i}>{point}</span>)}
                                {!t.care_points?.length && <span>点击进入查看团队病例。</span>}
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    <div className="ov-chart-card" style={{ marginBottom: 20 }}>
                      <h3>我的团队脉冲状态卡</h3>
                      <p className="tch-desc">用项目病例趋势线替代静止圆环，卡片边缘会提示可点击。</p>
                      <div className="tm-pulse-grid">
                        {myTeams.map((t: any) => {
                          const trendValues = (t.project_highlights || []).slice(0, 6).map((p: any) => Number(p.latest_score || 0));
                          const points = sparklinePoints(trendValues);
                          return (
                            <button
                              key={t.team_id}
                              className="tm-pulse-card"
                              onClick={() => { setSelectedTeamId(t.team_id); setTeamView("team-detail"); setSelectedTeamStudentId(""); setSelectedTeamProjectId(""); }}
                            >
                              <div className="tm-pulse-card-head">
                                <div>
                                  <div className="tm-pulse-label">团队状态</div>
                                  <div className="tm-pulse-title">{t.team_name}</div>
                                </div>
                                <div className="tm-pulse-link">点击查看团队病例 →</div>
                              </div>
                              <div className="tm-pulse-stats">
                                <div><strong>{Number(t.avg_score || 0).toFixed(1)}</strong><span>均分</span></div>
                                <div><strong>{t.total_submissions}</strong><span>提交</span></div>
                                <div><strong>{Number(t.risk_rate || 0).toFixed(0)}%</strong><span>风险率</span></div>
                              </div>
                              <div className="tm-pulse-spark">
                                {points ? (
                                  <svg viewBox="0 0 180 56" preserveAspectRatio="none">
                                    <polyline points={points} fill="none" stroke="url(#pulse-grad)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                                    <defs>
                                      <linearGradient id="pulse-grad" x1="0" y1="0" x2="1" y2="0">
                                        <stop offset="0%" stopColor="#73ccff" />
                                        <stop offset="100%" stopColor="#6b8aff" />
                                      </linearGradient>
                                    </defs>
                                  </svg>
                                ) : <div className="tm-pulse-empty">等待更多项目迭代数据</div>}
                              </div>
                              <div className="tm-pulse-foot">
                                <span>{dominantIntent(t.intent_distribution)}</span>
                                <span>{(t.top_risks || []).slice(0, 1).map((r: string) => getRuleDisplayName(r)).join(" / ") || "暂无高频风险"}</span>
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  </>
                );
              })()}

              {/* ══════ VIEW: Team Detail ══════ */}
              {teamView === "team-detail" && !loading && teamData && (() => {
                const team = [...(teamData.my_teams ?? []), ...(teamData.other_teams ?? [])].find((t: any) => t.team_id === selectedTeamId);
                if (!team) return <p style={{ color: "var(--text-muted)", padding: 40, textAlign: "center" }}>未找到团队数据</p>;
                const isMine = team.is_mine;
                const stuList: any[] = team.students || team.students_summary || [];
                const sortedStu = [...stuList].sort((a: any, b: any) => b.avg_score - a.avg_score);
                const maxStuSubs = Math.max(1, ...stuList.map((s: any) => s.total_submissions));
                const tiers = [0, 0, 0]; stuList.forEach((s: any) => { if (s.avg_score >= 7) tiers[0]++; else if (s.avg_score >= 5) tiers[1]++; else tiers[2]++; });
                const tierTotal = Math.max(1, tiers[0] + tiers[1] + tiers[2]);
                return (
                  <>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 8 }}>
                      <div>
                        <h2 style={{ marginTop: 0, marginBottom: 4 }}>{team.team_name} <span style={{ fontSize: 13, color: "var(--text-muted)", fontWeight: 400 }}>· {team.teacher_name}</span></h2>
                        <p className="tch-desc" style={{ margin: 0 }}>{isMine ? "点击学生行可查看详细项目演进" : "其他教师的团队，可查看学生概览数据"}</p>
                      </div>
                      {isMine && (
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
                          {team.invite_code && (
                            <div className="tm-invite-badge">
                              <span style={{ fontSize: 11, color: "var(--text-muted)" }}>邀请码</span>
                              <span style={{ fontWeight: 700, fontSize: 16, letterSpacing: 2, color: "var(--accent)" }}>{team.invite_code}</span>
                              <button className="tch-sm-btn" style={{ fontSize: 10, padding: "2px 8px" }} onClick={() => navigator.clipboard?.writeText(team.invite_code)}>复制</button>
                            </div>
                          )}
                          <button className="tch-sm-btn" style={{ color: "var(--tch-danger)", fontSize: 11 }} onClick={() => { if (confirm(`确定删除团队「${team.team_name}」？`)) handleDeleteTeam(team.team_id); }}>删除团队</button>
                        </div>
                      )}
                    </div>

                    {isMine && stuList.length === 0 && (
                      <div style={{ textAlign: "center", padding: "30px 20px", background: "var(--bg-card)", borderRadius: 12, margin: "16px 0" }}>
                        <p style={{ color: "var(--text-muted)", fontSize: 13, margin: 0 }}>暂无学生加入此团队，请将邀请码 <strong style={{ color: "var(--accent)" }}>{team.invite_code}</strong> 分享给学生</p>
                      </div>
                    )}

                    <div className="ov-kpi-grid" style={{ gridTemplateColumns: "repeat(5, 1fr)" }}>
                      {[
                        { icon: "👥", bg: "rgba(115,204,255,0.15)", c: "#73ccff", v: team.student_count, l: "学生", d: 0 },
                        { icon: "📝", bg: "rgba(92,189,138,0.15)", c: "var(--tch-success)", v: team.total_submissions, l: "提交", d: 0 },
                        { icon: "⭐", bg: "rgba(232,168,76,0.15)", c: "var(--tch-warning)", v: team.avg_score, l: "均分", d: 1 },
                        { icon: "⚠️", bg: "rgba(224,112,112,0.15)", c: "var(--tch-danger)", v: team.risk_rate, l: "风险%", d: 1 },
                        { icon: "📈", bg: "rgba(107,138,255,0.15)", c: "var(--accent)", v: team.trend, l: "趋势", d: 1 },
                      ].map((k, i) => (
                        <div key={i} className="ov-kpi-card">
                          <div className="ov-kpi-icon" style={{ background: k.bg, color: k.c }}>{k.icon}</div>
                          <div className="ov-kpi-value" style={{ color: k.c }}>{k.l === "趋势" && k.v > 0 ? "+" : ""}<AnimatedNumber value={k.v} decimals={k.d} />{k.l === "风险%" && <span style={{ fontSize: 14 }}>%</span>}</div>
                          <div className="ov-kpi-label">{k.l}</div>
                        </div>
                      ))}
                    </div>

                    {team.team_insight && !team.team_insight.error && (
                      <div className="ov-chart-card" style={{ marginBottom: 20 }}>
                        <h3>班级洞察</h3>
                        <p className="tch-desc">在保留当前团队页主体的前提下，把 A6-2 的洞察信息收进团队详情，不单独做成另一套大页面。</p>
                        <div className="assistant-insight-grid">
                          {(team.team_insight.coverage_summary || []).map((item: any) => (
                            <div key={item.topic} className="assistant-summary-card">
                              <span>{item.topic}</span>
                              <strong>{item.ratio}%</strong>
                            </div>
                          ))}
                        </div>
                        <div className="ov-chart-grid" style={{ marginTop: 14 }}>
                          <div className="ov-chart-card" style={{ margin: 0 }}>
                            <h3 style={{ marginTop: 0 }}>Top 5 Common Mistakes</h3>
                            <div className="assistant-note-list">
                              {(team.team_insight.top_mistakes || []).slice(0, 5).map((item: any) => (
                                <div key={item.rule_id} className="tm-note-row warn">{item.summary}</div>
                              ))}
                            </div>
                          </div>
                          <div className="ov-chart-card" style={{ margin: 0 }}>
                            <h3 style={{ marginTop: 0 }}>Suggested Teaching Interventions</h3>
                            <div className="assistant-note-list">
                              {(team.team_insight.suggested_teaching_interventions || []).slice(0, 3).map((item: any, idx: number) => (
                                <div key={idx} className="tm-note-row good">{item.plan}</div>
                              ))}
                            </div>
                          </div>
                        </div>
                        <details className="debug-json" style={{ marginTop: 14 }}>
                          <summary style={{ cursor: "pointer", color: "var(--accent-text)", fontWeight: 600 }}>统计 JSON</summary>
                          <pre style={{ marginTop: 12, padding: 12, background: "var(--bg-card)", borderRadius: 10, overflow: "auto", maxHeight: 220 }}>
                            {JSON.stringify(team.team_insight.statistics_json || {}, null, 2)}
                          </pre>
                        </details>
                      </div>
                    )}

                    <div className="ov-chart-grid">
                      {/* ─ Lollipop: student ranking ─ */}
                      <div className="ov-chart-card">
                        <h3>学生均分排名</h3>
                        <p className="tch-desc">棒棒糖图：圆点 = 均分，线长 = 与零轴距离</p>
                        <svg viewBox={`0 0 440 ${sortedStu.length * 30 + 10}`} style={{ width: "100%", overflow: "visible" }}>
                          {sortedStu.map((s: any, i) => {
                            const x = (s.avg_score / 10) * 300 + 130;
                            const y = i * 30 + 14;
                            const col = s.avg_score >= 7 ? "#5cbd8a" : s.avg_score >= 5 ? "#e0a84c" : "#e07070";
                            return (
                              <g key={s.student_id} style={{ cursor: isMine ? "pointer" : "default" }} onClick={() => { if (isMine) { setSelectedTeamStudentId(s.student_id); setTeamView("student-detail"); } }}>
                                <line x1="130" y1={y} x2={x} y2={y} stroke={col} strokeWidth="2" opacity="0.7" strokeLinecap="round" />
                                <circle cx={x} cy={y} r="5" fill={col} />
                                <text x={x + 10} y={y + 4} fill="var(--text-secondary)" fontSize="10" fontWeight="600">{s.avg_score.toFixed(1)}</text>
                                <text x="125" y={y + 4} fill="var(--text-muted)" fontSize="10" textAnchor="end">{(s.display_name || s.student_id).slice(0, 6)}</text>
                              </g>
                            );
                          })}
                        </svg>
                      </div>

                      {/* ─ Tier donut ─ */}
                      <div className="ov-chart-card">
                        <h3>成绩分层</h3>
                        <p className="tch-desc">绿 = 良好(≥7)，黄 = 一般(5-7)，红 = 需关注(&lt;5)</p>
                        <div style={{ display: "flex", justifyContent: "center", padding: "12px 0" }}>
                          <svg width="160" height="160" viewBox="0 0 160 160">
                            {(() => {
                              const R = 65; const C = 2 * Math.PI * R; const cx = 80; const cy = 80;
                              const slices = [{ v: tiers[0], c: "#5cbd8a" }, { v: tiers[1], c: "#e0a84c" }, { v: tiers[2], c: "#e07070" }];
                              let offset = 0;
                              return slices.map((sl, si) => {
                                const len = (sl.v / tierTotal) * C;
                                const el = <circle key={si} cx={cx} cy={cy} r={R} fill="none" stroke={sl.c} strokeWidth="18" strokeDasharray={`${len} ${C - len}`} strokeDashoffset={-offset} transform={`rotate(-90 ${cx} ${cy})`} style={{ transition: "stroke-dasharray 0.8s, stroke-dashoffset 0.8s" }} />;
                                offset += len;
                                return el;
                              });
                            })()}
                            <text x="80" y="76" textAnchor="middle" fill="var(--text-primary)" fontSize="22" fontWeight="700">{stuList.length}</text>
                            <text x="80" y="92" textAnchor="middle" fill="var(--text-muted)" fontSize="10">学生</text>
                          </svg>
                        </div>
                        <div style={{ display: "flex", justifyContent: "center", gap: 16, fontSize: 12 }}>
                          <span style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ width: 8, height: 8, borderRadius: 4, background: "#5cbd8a", display: "inline-block" }} />良好 {tiers[0]}</span>
                          <span style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ width: 8, height: 8, borderRadius: 4, background: "#e0a84c", display: "inline-block" }} />一般 {tiers[1]}</span>
                          <span style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ width: 8, height: 8, borderRadius: 4, background: "#e07070", display: "inline-block" }} />需关注 {tiers[2]}</span>
                        </div>
                      </div>
                    </div>

                    {/* ─ Student activity bars ─ */}
                    <div className="ov-chart-card" style={{ marginBottom: 20 }}>
                      <h3>学生活跃度</h3>
                      <p className="tch-desc">横条长度 = 提交次数，颜色反映成绩状态</p>
                      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
                        {sortedStu.map((s: any) => {
                          const col = s.avg_score >= 7 ? "#5cbd8a" : s.avg_score >= 5 ? "#e0a84c" : "#e07070";
                          return (
                            <div key={s.student_id} style={{ display: "flex", alignItems: "center", gap: 8, cursor: isMine ? "pointer" : "default" }} onClick={() => { if (isMine) { setSelectedTeamStudentId(s.student_id); setTeamView("student-detail"); } }}>
                              <span style={{ minWidth: 60, fontSize: 11, color: "var(--text-muted)", textAlign: "right", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{(s.display_name || "").slice(0, 4)}</span>
                              <div style={{ flex: 1, height: 14, background: "var(--bg-card-hover)", borderRadius: 7, overflow: "hidden" }}>
                                <div style={{ width: `${(s.total_submissions / maxStuSubs) * 100}%`, height: "100%", background: col, borderRadius: 7, transition: "width 0.8s ease" }} />
                              </div>
                              <span style={{ minWidth: 24, fontSize: 11, fontWeight: 600, color: col }}>{s.total_submissions}</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>

                    {/* Student table */}
                    <div className="ov-section">
                      <h3>学生明细 ({stuList.length})</h3>
                      <div className="cls-stu-table">
                        <div className="cls-stu-hdr"><span>#</span><span>学生</span><span>提交</span><span>均分</span><span>趋势</span><span>状态</span></div>
                        {sortedStu.map((stu: any, idx: number) => {
                          const st = stu.avg_score >= 7 ? { l: "良好", c: "var(--tch-success)", bg: "var(--tch-success-soft)" } : stu.avg_score >= 5 ? { l: "一般", c: "var(--tch-warning)", bg: "var(--tch-warning-soft)" } : { l: "需关注", c: "var(--tch-danger)", bg: "var(--tch-danger-soft)" };
                          return (
                            <div key={stu.student_id} className="cls-stu-row" style={{ animationDelay: `${idx * 0.03}s`, cursor: isMine ? "pointer" : "default", opacity: isMine ? 1 : 0.75 }}
                              onClick={() => { if (isMine) { setSelectedTeamStudentId(stu.student_id); setTeamView("student-detail"); } }}>
                              <span style={{ fontWeight: 700, color: idx < 3 ? "var(--accent)" : "var(--text-muted)" }}>{idx + 1}</span>
                              <span className="ov-stu-name"><span className="ov-stu-av">{(stu.display_name || "?")[0]}</span>{stu.display_name || stu.student_id}</span>
                              <span><strong>{stu.total_submissions}</strong></span>
                              <span style={{ fontWeight: 600, color: st.c }}>{stu.avg_score.toFixed(1)}</span>
                              <span style={{ color: stu.trend > 0 ? "var(--tch-success)" : stu.trend < 0 ? "var(--tch-danger)" : "var(--text-muted)", fontWeight: 600 }}>{stu.trend > 0 ? `↑${stu.trend.toFixed(1)}` : stu.trend < 0 ? `↓${Math.abs(stu.trend).toFixed(1)}` : "—"}</span>
                              <span><span className="ov-status-badge" style={{ color: st.c, background: st.bg }}>{st.l}</span></span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </>
                );
              })()}

              {/* ══════ VIEW: Student Detail — Systematic Dashboard ══════ */}
              {teamView === "student-detail" && !loading && teamData && (() => {
                const team = (teamData.my_teams ?? []).find((t: any) => t.team_id === selectedTeamId);
                const stu = team?.students?.find((s: any) => s.student_id === selectedTeamStudentId);
                if (!stu) return <p style={{ color: "var(--text-muted)", padding: 40, textAlign: "center" }}>学生数据未找到</p>;
                const projects: any[] = stu.projects || [];
                const activeProject = projects.find((p: any) => p.project_id === selectedTeamProjectId) || projects[0];
                const allSubs = [...projects.flatMap((p: any) => (p.submissions || []))].sort((a: any, b: any) => (a.created_at || "").localeCompare(b.created_at || ""));
                const projectTimeline = (activeProject?.submissions || []).map((s: any) => ({ label: formatBJTime(s.created_at), value: Number(s.overall_score || 0) }));
                const studentIntentMix = intentEntries(stu.intent_distribution);
                const activeIntentMix = intentEntries(activeProject?.intent_distribution);
                const latestDiag = activeProject?.latest_diagnosis || {};
                const latestTask = activeProject?.latest_task || {};
                const latestKg = activeProject?.latest_kg || {};
                const latestHyper = activeProject?.latest_hypergraph || {};
                const latestHyperStudent = activeProject?.latest_hypergraph_student || {};
                const latestQuotes: any[] = activeProject?.evidence_quotes || [];
                const latestKgEntities: any[] = latestKg.entities || [];
                const latestKgGaps: string[] = latestKg.structural_gaps || [];
                const latestKgStrengths: string[] = latestKg.content_strengths || [];
                const latestHubs: any[] = latestHyperStudent.hub_entities || [];
                const latestCrossLinks: any[] = latestHyperStudent.cross_links || [];
                const latestWarnings: string[] = latestHyperStudent.pattern_warnings || [];
                const localDate = (v: string) => formatBJTime(v) || "—";
                const studentNarrative = stu.student_case_summary || activeProject?.current_summary || "暂无可用的项目理解摘要";
                const statusColor = stu.avg_score >= 7 ? "var(--tch-success)" : stu.avg_score >= 5 ? "var(--tch-warning)" : "var(--tch-danger)";
                const statusLabel = stu.avg_score >= 7 ? "良好" : stu.avg_score >= 5 ? "一般" : "需关注";
                const riskScore = allSubs.length > 0 ? Math.round(allSubs.filter((s: any) => (s.triggered_rules || []).length > 0).length / allSubs.length * 100) : 0;

                return (
                  <>
                    <div className="tm-case-hero">
                      <div className="tm-case-avatar">{(stu.display_name || "?")[0]}</div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                          <h2 style={{ margin: 0, fontSize: 20 }}>{stu.display_name}</h2>
                          <span className="tm-case-badge" style={{ background: statusColor + "1f", color: statusColor }}>{statusLabel}</span>
                          <span className="tm-case-badge">{stu.latest_phase || "持续迭代"}</span>
                          <span className="tm-case-badge">{dominantIntent(stu.intent_distribution)}</span>
                          {activeProject?.project_name && <span className="tm-case-badge">当前聚焦：{activeProject.project_name}</span>}
                        </div>
                        <div className="tm-case-meta">
                          <span>最后活跃 {localDate(stu.last_active || "")}</span>
                          <span>{stu.project_count} 个项目</span>
                          <span>{stu.total_submissions} 次提交</span>
                        </div>
                        <div className="tm-case-summary">
                          <div className="tm-case-summary-title">AI 项目病历摘要</div>
                          <div className="tm-case-summary-body">{studentNarrative}</div>
                        </div>
                        {stu.teacher_intervention && <div className="tm-case-inline-summary" style={{ marginTop: 10 }}>教师建议介入：{stu.teacher_intervention}</div>}
                      </div>
                    </div>

                    <div className="ov-kpi-grid" style={{ gridTemplateColumns: "repeat(5, 1fr)" }}>
                      {[
                        { icon: "📝", bg: "rgba(107,138,255,0.15)", c: "var(--accent)", v: stu.total_submissions, l: "提交", d: 0 },
                        { icon: "📁", bg: "rgba(92,189,138,0.15)", c: "var(--tch-success)", v: stu.project_count, l: "项目", d: 0 },
                        { icon: "⭐", bg: "rgba(232,168,76,0.15)", c: "var(--tch-warning)", v: stu.avg_score, l: "均分", d: 1 },
                        { icon: "📈", bg: "rgba(115,204,255,0.15)", c: "#73ccff", v: stu.trend, l: "趋势", d: 1 },
                        { icon: "⚠️", bg: "rgba(224,112,112,0.15)", c: "var(--tch-danger)", v: riskScore, l: "风险%", d: 0 },
                      ].map((k, i) => (
                        <div key={i} className="ov-kpi-card">
                          <div className="ov-kpi-icon" style={{ background: k.bg, color: k.c }}>{k.icon}</div>
                          <div className="ov-kpi-value" style={{ color: k.c }}>{k.l === "趋势" && k.v > 0 ? "+" : ""}<AnimatedNumber value={k.v} decimals={k.d} />{k.l === "风险%" && <span style={{ fontSize: 14 }}>%</span>}</div>
                          <div className="ov-kpi-label">{k.l}</div>
                        </div>
                      ))}
                    </div>

                    <div className="ov-chart-grid">
                      <div className="ov-chart-card">
                        <h3>项目病例切换</h3>
                        <p className="tch-desc">一个学生多个项目时，下面每张病例卡都代表一个独立项目，不会再共用同一张图谱卡。</p>
                        <div className="tm-project-switch-list">
                          {projects.map((p: any) => {
                            const active = activeProject?.project_id === p.project_id;
                            const impColor = p.improvement > 0 ? "var(--tch-success)" : p.improvement < 0 ? "var(--tch-danger)" : "var(--text-muted)";
                            return (
                              <div
                                key={p.project_id}
                                className={`tm-project-switch-card ${active ? "active" : ""}`}
                                onClick={() => setSelectedTeamProjectId(p.project_id)}
                              >
                                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                                  <strong style={{ color: "var(--text-primary)" }}>{p.project_name}</strong>
                                  <span style={{ color: impColor, fontWeight: 700 }}>{p.improvement > 0 ? `+${p.improvement}` : p.improvement || "0"}</span>
                                </div>
                                <div className="tm-case-meta" style={{ marginTop: 6 }}>
                                  <span>{p.project_phase || "持续迭代"}</span>
                                  <span>{p.submission_count} 次迭代</span>
                                  <span>{p.latest_score}/10</span>
                                </div>
                                <div className="tm-case-inline-summary" style={{ marginTop: 8 }}>{p.current_summary || "暂无项目摘要"}</div>
                                <div className="tm-corridor-tags" style={{ marginTop: 10 }}>
                                  {(p.top_risks || []).slice(0, 2).map((risk: string) => <span key={risk} className="tm-smart-chip">{getRuleDisplayName(risk)}</span>)}
                                  <span className="tm-smart-chip">{dominantIntent(p.intent_distribution)}</span>
                                </div>
                                <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}>
                                  <button
                                    className="tch-sm-btn"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setSelectedTeamProjectId(p.project_id);
                                      setTeamView("project-detail");
                                    }}
                                  >
                                    查看证据链
                                  </button>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                      <div className="ov-chart-card">
                        <h3>求助意图分布</h3>
                        <p className="tch-desc">老师可以判断学生更需要补基础、做商业诊断，还是打磨表达材料。</p>
                        <div className="tm-intent-panel">
                          {(studentIntentMix.length ? studentIntentMix : [{ label: "综合咨询", value: 1, color: "var(--accent)" }]).map((item) => {
                            const total = Math.max(1, studentIntentMix.reduce((sum, cur) => sum + cur.value, 0));
                            return (
                              <div key={item.label} className="tm-intent-row">
                                <span>{item.label}</span>
                                <div><i style={{ width: `${(item.value / total) * 100}%`, background: `linear-gradient(90deg, ${item.color}33, ${item.color})` }} /></div>
                                <b>{item.value}</b>
                              </div>
                            );
                          })}
                        </div>
                        <div className="tm-case-summary" style={{ marginTop: 14 }}>
                          <div className="tm-case-summary-title">教学介入提示</div>
                          <div className="tm-case-summary-body">{stu.teacher_intervention || "建议结合下方项目病例判断该学生当前最需要哪类帮助。"}</div>
                        </div>
                      </div>
                    </div>

                    <div className="ov-chart-grid">
                      <div className="ov-chart-card">
                        <h3>当前聚焦项目病程</h3>
                        <p className="tch-desc">{activeProject ? `${activeProject.project_name} 的阶段与得分如何变化` : "暂无项目"}</p>
                        {projectTimeline.length >= 2 ? <AreaChart data={projectTimeline} color="rgba(107,138,255,0.9)" height={130} /> : <p style={{ color: "var(--text-muted)", fontSize: 12, textAlign: "center", padding: 20 }}>提交次数不足，暂无曲线</p>}
                        {activeIntentMix.length > 0 && (
                          <div className="tm-corridor-tags" style={{ marginTop: 12 }}>
                            {activeIntentMix.map((item) => <span key={item.label} className="tm-smart-chip" style={{ background: `${item.color}22`, color: item.color }}>{item.label} {item.value}</span>)}
                          </div>
                        )}
                      </div>
                      <div className="ov-chart-card">
                        <h3>当前病情快照</h3>
                        <p className="tch-desc">只针对当前选中项目展示，不再把多个项目混到一起。</p>
                        {activeProject ? (
                          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 8 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                              <div style={{ width: 56, height: 56, borderRadius: 14, background: statusColor + "18", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, fontWeight: 800, color: statusColor }}>{latestDiag.overall_score || activeProject.latest_score || 0}</div>
                              <div style={{ flex: 1 }}>
                                <div style={{ fontSize: 12, color: "var(--text-primary)", fontWeight: 700 }}>{activeProject.project_phase || "持续迭代"}</div>
                                {latestDiag.bottleneck && <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 4 }}>🎯 {latestDiag.bottleneck}</div>}
                                {latestTask.title && <div style={{ fontSize: 11, color: "var(--accent)", marginTop: 3 }}>➡️ {latestTask.title}</div>}
                              </div>
                            </div>
                            <div className="tm-case-inline-summary">{activeProject.current_summary || "暂无项目摘要"}</div>
                            {latestDiag.weaknesses?.length > 0 && <div style={{ fontSize: 11 }}><strong style={{ color: "var(--tch-danger)" }}>当前差什么：</strong><span style={{ color: "var(--text-secondary)" }}>{latestDiag.weaknesses.slice(0, 3).join("；")}</span></div>}
                            {latestDiag.strengths?.length > 0 && <div style={{ fontSize: 11 }}><strong style={{ color: "var(--tch-success)" }}>已有优势：</strong><span style={{ color: "var(--text-secondary)" }}>{latestDiag.strengths.slice(0, 3).join("；")}</span></div>}
                          </div>
                        ) : <p style={{ color: "var(--text-muted)", fontSize: 12, textAlign: "center", padding: 20 }}>暂无诊断数据</p>}
                      </div>
                    </div>

                    <div className="ov-chart-grid">
                      <div className="ov-chart-card">
                        <h3>知识图谱病灶</h3>
                        <p className="tch-desc">帮助老师理解学生项目“缺哪块、强哪块”</p>
                        <div className="tm-signal-grid">
                          <div className="tm-signal-box">
                            <div className="tm-signal-value">{latestKgEntities.length}</div>
                            <div className="tm-signal-label">识别实体</div>
                          </div>
                          <div className="tm-signal-box">
                            <div className="tm-signal-value">{(latestKg.relationships || []).length}</div>
                            <div className="tm-signal-label">关键关系</div>
                          </div>
                          <div className="tm-signal-box">
                            <div className="tm-signal-value">{latestKg.completeness_score || 0}</div>
                            <div className="tm-signal-label">完整度</div>
                          </div>
                        </div>
                        {activeProject && <div className="tm-case-inline-summary" style={{ marginTop: 10 }}>{latestKg.insight || "暂无图谱洞察"}</div>}
                        {latestKgEntities.length > 0 && (
                          <div className="tm-chip-cloud">
                            {latestKgEntities.slice(0, 10).map((e: any, i: number) => <span key={i} className="tm-smart-chip">{e.label || e.id}</span>)}
                          </div>
                        )}
                        {latestKgGaps.length > 0 && (
                          <div style={{ marginTop: 10 }}>
                            <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 6 }}>结构缺口</div>
                            {latestKgGaps.slice(0, 4).map((g: string, i: number) => <div key={i} className="tm-note-row bad">{g}</div>)}
                          </div>
                        )}
                        {latestKgStrengths.length > 0 && (
                          <div style={{ marginTop: 10 }}>
                            <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 6 }}>已有亮点</div>
                            {latestKgStrengths.slice(0, 4).map((g: string, i: number) => <div key={i} className="tm-note-row good">{g}</div>)}
                          </div>
                        )}
                      </div>
                      <div className="ov-chart-card">
                        <h3>超图联动诊断</h3>
                        <p className="tch-desc">看项目是否形成跨维度联动，而不是单点堆砌</p>
                        <div className="tm-signal-grid">
                          <div className="tm-signal-box">
                            <div className="tm-signal-value">{latestHyperStudent.coverage_score || 0}</div>
                            <div className="tm-signal-label">覆盖分</div>
                          </div>
                          <div className="tm-signal-box">
                            <div className="tm-signal-value">{latestHubs.length}</div>
                            <div className="tm-signal-label">核心支撑点</div>
                          </div>
                          <div className="tm-signal-box">
                            <div className="tm-signal-value">{latestCrossLinks.length}</div>
                            <div className="tm-signal-label">跨维链接</div>
                          </div>
                        </div>
                        {latestHyper.summary && <div className="tm-case-inline-summary">{latestHyper.summary}</div>}
                        {latestHubs.length > 0 && (
                          <div style={{ marginTop: 10 }}>
                            {latestHubs.slice(0, 4).map((h: any, i: number) => (
                              <div key={i} className="tm-linked-row">
                                <span className="tm-linked-main">{h.entity}</span>
                                <span className="tm-linked-side">{h.connections} 维连接</span>
                              </div>
                            ))}
                          </div>
                        )}
                        {latestWarnings.length > 0 && (
                          <div style={{ marginTop: 10 }}>
                            {latestWarnings.slice(0, 3).map((w: string, i: number) => <div key={i} className="tm-note-row warn">{w}</div>)}
                          </div>
                        )}
                      </div>
                    </div>

                    {activeProject?.teacher_intervention && (
                      <div className="ov-chart-card" style={{ marginBottom: 20, borderLeft: "3px solid var(--accent)" }}>
                        <h3 style={{ display: "flex", alignItems: "center", gap: 6 }}>🎯 当前项目建议介入</h3>
                        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)", marginTop: 4 }}>{activeProject.teacher_intervention}</div>
                        {latestTask.description && <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 6, lineHeight: 1.6 }}>{latestTask.description}</div>}
                        {latestTask.acceptance_criteria?.length > 0 && (
                          <div style={{ marginTop: 8 }}>
                            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", marginBottom: 4 }}>验收标准</div>
                            {latestTask.acceptance_criteria.map((c: string, ci: number) => (
                              <div key={ci} style={{ display: "flex", alignItems: "flex-start", gap: 6, fontSize: 12, color: "var(--text-secondary)", marginBottom: 3 }}>
                                <span style={{ color: "var(--accent)", flexShrink: 0 }}>✓</span>{c}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    <div className="ov-chart-card" style={{ marginBottom: 20 }}>
                      <h3>风险证据预览</h3>
                      <p className="tch-desc">这里直接展示 AI 做判断时引用到的学生原话/文档片段，老师无需只看结论。</p>
                      {latestQuotes.length > 0 ? (
                        <div className="tm-evidence-grid">
                          {latestQuotes.map((quote: any, idx: number) => (
                            <div key={idx} className="tm-evidence-card">
                              <div className="tm-evidence-top">
                                <span>{getRuleDisplayName(quote.risk_name || quote.risk_id || "未归类风险")}</span>
                                <span>{quote.filename || (quote.source === "document" ? "文档证据" : "对话证据")}</span>
                              </div>
                              <div className="tm-evidence-quote">“{quote.quote}”</div>
                            </div>
                          ))}
                        </div>
                      ) : <p style={{ color: "var(--text-muted)", fontSize: 12, textAlign: "center", padding: 20 }}>当前项目还没有可展示的证据片段</p>}
                    </div>
                  </>
                );
              })()}

              {/* ══════ VIEW: Project Detail ══════ */}
              {teamView === "project-detail" && !loading && teamData && (() => {
                const team = (teamData.my_teams ?? []).find((t: any) => t.team_id === selectedTeamId);
                const stu = team?.students?.find((s: any) => s.student_id === selectedTeamStudentId);
                const proj = stu?.projects?.find((p: any) => p.project_id === selectedTeamProjectId);
                if (!proj) return <p style={{ color: "var(--text-muted)", padding: 40, textAlign: "center" }}>项目数据未找到</p>;
                const subs: any[] = proj.submissions || [];
                const scoreTimeline = subs.map((s: any) => ({ label: formatBJTime(s.created_at), value: s.overall_score }));
                const latestDiag = proj.latest_diagnosis || {};
                const latestKg = proj.latest_kg || {};
                const latestHyper = proj.latest_hypergraph || {};
                const latestHyperStudent = proj.latest_hypergraph_student || {};
                const latestTask = proj.latest_task || {};
                const intentMix = intentEntries(proj.intent_distribution);
                const evidenceGroups = Object.entries((proj.risk_evidence || []).reduce((acc: Record<string, any[]>, item: any) => {
                  const key = item.risk_name || item.risk_id || "未归类风险";
                  acc[key] = acc[key] || [];
                  acc[key].push(item);
                  return acc;
                }, {}));
                return (
                  <>
                    <div className="tm-project-cover">
                      <div>
                        <div className="tm-project-cover-label">项目诊断封面</div>
                        <h2 style={{ marginTop: 6, marginBottom: 6 }}>{proj.project_name}</h2>
                        <div className="tm-case-meta">
                          <span>{stu.display_name}</span>
                          <span>{proj.project_phase || "持续迭代"}</span>
                          <span>{proj.submission_count} 次迭代</span>
                        </div>
                        <div className="tm-case-summary" style={{ marginTop: 14 }}>
                          <div className="tm-case-summary-title">一句话理解项目</div>
                          <div className="tm-case-summary-body">{proj.current_summary || latestKg.insight || latestHyper.summary || "暂无摘要"}</div>
                        </div>
                      </div>
                      <div className="tm-project-cover-score">
                        <div>{proj.latest_score || 0}</div>
                        <span>当前分数</span>
                      </div>
                    </div>

                    <div className="ov-kpi-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
                      <div className="ov-kpi-card"><div className="ov-kpi-icon" style={{ background: "rgba(107,138,255,0.15)", color: "var(--accent)" }}>📊</div><div className="ov-kpi-value"><AnimatedNumber value={proj.avg_score} decimals={1} /></div><div className="ov-kpi-label">均分</div></div>
                      <div className="ov-kpi-card"><div className="ov-kpi-icon" style={{ background: "rgba(92,189,138,0.15)", color: "var(--tch-success)" }}>📈</div><div className="ov-kpi-value" style={{ color: proj.improvement >= 0 ? "var(--tch-success)" : "var(--tch-danger)" }}>{proj.improvement >= 0 ? "+" : ""}<AnimatedNumber value={proj.improvement} decimals={1} /></div><div className="ov-kpi-label">进步</div></div>
                      <div className="ov-kpi-card"><div className="ov-kpi-icon" style={{ background: "rgba(232,168,76,0.15)", color: "var(--tch-warning)" }}>🔄</div><div className="ov-kpi-value"><AnimatedNumber value={proj.submission_count} /></div><div className="ov-kpi-label">迭代</div></div>
                      <div className="ov-kpi-card"><div className="ov-kpi-icon" style={{ background: "rgba(189,147,249,0.15)", color: "#bd93f9" }}>📄</div><div className="ov-kpi-value"><AnimatedNumber value={subs.filter((s: any) => s.filename).length} /></div><div className="ov-kpi-label">文件</div></div>
                    </div>

                    <div className="ov-chart-grid">
                      <div className="ov-chart-card">
                        <h3>老师最关心的第一个问题</h3>
                        <p className="tch-desc">这个项目现在差什么</p>
                        <div className="tm-threeq-card">
                          <strong>当前瓶颈</strong>
                          <div>{latestDiag.bottleneck || "暂无明确瓶颈"}</div>
                        </div>
                        {latestDiag.weaknesses?.length > 0 && (
                          <div className="tm-chip-cloud" style={{ marginTop: 12 }}>
                            {latestDiag.weaknesses.slice(0, 4).map((item: string, idx: number) => <span key={idx} className="tm-smart-chip">{item}</span>)}
                          </div>
                        )}
                      </div>
                      <div className="ov-chart-card">
                        <h3>老师最关心的第二个问题</h3>
                        <p className="tch-desc">学生最近主要向 AI 寻求什么帮助</p>
                        <div className="tm-intent-panel">
                          {(intentMix.length ? intentMix : [{ label: "综合咨询", value: 1, color: "var(--accent)" }]).map((item) => {
                            const total = Math.max(1, intentMix.reduce((sum, cur) => sum + cur.value, 0));
                            return (
                              <div key={item.label} className="tm-intent-row">
                                <span>{item.label}</span>
                                <div><i style={{ width: `${(item.value / total) * 100}%`, background: `linear-gradient(90deg, ${item.color}33, ${item.color})` }} /></div>
                                <b>{item.value}</b>
                              </div>
                            );
                          })}
                        </div>
                        <div className="tm-case-inline-summary" style={{ marginTop: 12 }}>当前主导求助方向：{dominantIntent(proj.intent_distribution)}</div>
                      </div>
                      <div className="ov-chart-card">
                        <h3>老师最关心的第三个问题</h3>
                        <p className="tch-desc">老师该介入什么</p>
                        <div className="tm-threeq-card accent">
                          <strong>教学建议</strong>
                          <div>{proj.teacher_intervention || "建议先检查风险证据链，再决定是补基础还是做专项诊断。"}</div>
                        </div>
                        {latestTask.title && <div className="tm-case-inline-summary" style={{ marginTop: 12 }}>下一步任务：{latestTask.title}</div>}
                      </div>
                    </div>

                    <div className="ov-chart-grid">
                      <div className="ov-chart-card">
                        <h3>项目结构状态</h3>
                        <p className="tch-desc">当前项目在图谱和超图上的结构信号</p>
                        <div className="tm-signal-grid">
                          <div className="tm-signal-box"><div className="tm-signal-value">{latestKg.completeness_score || 0}</div><div className="tm-signal-label">图谱完整度</div></div>
                          <div className="tm-signal-box"><div className="tm-signal-value">{(latestKg.entities || []).length}</div><div className="tm-signal-label">关键实体</div></div>
                          <div className="tm-signal-box"><div className="tm-signal-value">{latestHyperStudent.coverage_score || 0}</div><div className="tm-signal-label">超图覆盖</div></div>
                        </div>
                        {latestHyper.summary && (
                          <div className="tm-case-inline-summary" style={{ marginTop: 12 }}>
                            超图摘要：{latestHyper.summary}
                          </div>
                        )}
                        {(latestHyper.top_signals || []).length > 0 && (
                          <div className="tm-chip-cloud" style={{ marginTop: 10 }}>
                            {(latestHyper.top_signals || []).slice(0, 4).map((item: string, idx: number) => (
                              <span key={idx} className="tm-smart-chip">{item}</span>
                            ))}
                          </div>
                        )}
                        {(latestKg.entities || []).length > 0 && (
                          <div className="tm-chip-cloud">
                            {(latestKg.entities || []).slice(0, 8).map((e: any, idx: number) => <span key={idx} className="tm-smart-chip">{e.label || e.id}</span>)}
                          </div>
                        )}
                        {hyperLibrary?.overview && (
                          <div className="tm-case-inline-summary" style={{ marginTop: 12 }}>
                            超图库规模：{hyperLibrary.overview.edge_count || 0} 条超边 / {hyperLibrary.overview.node_count || 0} 个超节点 / 平均 {hyperLibrary.overview.avg_member_count || 0} 个成员
                          </div>
                        )}
                        {(hyperLibrary?.families || []).length > 0 && (
                          <div className="tm-chip-cloud" style={{ marginTop: 10 }}>
                            {(hyperLibrary.families || []).slice(0, 6).map((item: any, idx: number) => (
                              <span key={idx} className="tm-smart-chip">{item.label || item.family} {item.count}</span>
                            ))}
                          </div>
                        )}
                      </div>
                      <div className="ov-chart-card">
                        <h3>意图时间轴</h3>
                        <p className="tch-desc">除了得分变化，也看学生提问方向如何变化。</p>
                        <div className="tm-intent-timeline">
                          {subs.map((sub: any, idx: number) => (
                            <div key={sub.submission_id || idx} className="tm-intent-timeline-item">
                              <div className="tm-intent-timeline-dot" />
                              <div>
                                <div className="tm-case-meta">
                                  <span>{formatBJTime(sub.created_at)}</span>
                                  <span>{sub.project_phase || "持续迭代"}</span>
                                  <span>{sub.intent || "综合咨询"}</span>
                                  <span>{sub.agent_trace_meta?.intent_shape || "single"}</span>
                                  <span>{Number(sub.overall_score || 0).toFixed(1)}</span>
                                </div>
                                <div className="tm-case-inline-summary" style={{ marginTop: 6 }}>{sub.bottleneck || sub.next_task || sub.text_preview || "暂无记录"}</div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>

                    {scoreTimeline.length >= 2 && (
                      <div className="ov-chart-card" style={{ marginBottom: 20 }}>
                        <h3>评分演进</h3>
                        <AreaChart data={scoreTimeline} color="rgba(107,138,255,0.9)" height={140} />
                      </div>
                    )}

                    <div className="ov-section">
                      <h3>风险证据链</h3>
                      <div className="tm-risk-chain">
                        {evidenceGroups.length > 0 ? evidenceGroups.map(([riskName, items]: any) => (
                          <div key={riskName} className="tm-risk-chain-card">
                            <div className="tm-risk-chain-head">
                              <strong>{getRuleDisplayName(riskName)}</strong>
                              <span>{items.length} 条证据</span>
                            </div>
                            <div className="tm-case-inline-summary" style={{ marginTop: 8 }}>
                              {latestDiag.bottleneck || "AI 认为该风险需要老师优先介入。"}
                            </div>
                            <div className="tm-risk-chain-list">
                              {items.slice(0, 4).map((item: any, idx: number) => (
                                <div key={idx} className="tm-evidence-card">
                                  <div className="tm-evidence-top">
                                    <span>{item.filename || (item.source === "document" ? "文档片段" : "学生原话")}</span>
                                    <span>{formatBJTime(item.created_at)}</span>
                                  </div>
                                  <div className="tm-evidence-quote">“{item.quote}”</div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )) : (
                          <p style={{ color: "var(--text-muted)", padding: 20, textAlign: "center" }}>当前项目还没有可用的风险证据链。</p>
                        )}
                      </div>
                    </div>
                  </>
                );
              })()}

              {!loading && !teamData && (
                <div style={{ textAlign: "center", padding: "60px 20px" }}>
                  <div style={{ fontSize: 48, marginBottom: 16 }}>📋</div>
                  <h3 style={{ color: "var(--text-primary)", margin: "0 0 8px" }}>暂无团队数据</h3>
                  <p style={{ color: "var(--text-muted)", fontSize: 13, margin: "0 0 20px" }}>创建您的第一个团队，然后将邀请码分享给学生</p>
                  <button className="tch-sm-btn" style={{ background: "var(--accent)", color: "#fff", padding: "10px 24px", fontSize: 14 }} onClick={() => { setShowCreateTeam(true); setCreatedInviteCode(""); setNewTeamName(""); }}>+ 创建团队</button>
                </div>
              )}
            </div>
          )}
        </main>
      </div>

      <style>{`
        .tch-app {
          background: var(--bg-primary);
          color: var(--text-primary);
          --skeleton-bg: var(--bg-card);
          --tch-accent: var(--accent);
          --tch-accent-soft: var(--accent-soft);
          --tch-accent-text: var(--accent-text);
          --tch-success: #5cbd8a;
          --tch-danger: #e07070;
          --tch-warning: #e0a84c;
          --tch-success-soft: rgba(92,189,138,0.12);
          --tch-danger-soft: rgba(224,112,112,0.12);
          --tch-warning-soft: rgba(224,168,76,0.12);
        }

        .tch-body { display: flex; background: var(--bg-primary); min-height: calc(100vh - 56px); }

        .tch-app h1,.tch-app h2,.tch-app h3,.tch-app h4,.tch-app h5 { color: var(--heading-color); }
        .tch-app p,.tch-app span,.tch-app div { color: var(--text-primary); }

        .tch-sidebar {
          background: var(--bg-secondary);
          border-right: 1px solid var(--border);
          min-width: 220px; overflow-y: auto; max-height: calc(100vh - 56px); padding: 12px 8px;
        }
        .tch-nav-btn {
          background: transparent; color: var(--text-secondary); border: none;
          border-left: 3px solid transparent; padding: 11px 14px; width: 100%;
          text-align: left; cursor: pointer; font-weight: 500; font-size: 13.5px;
          transition: all 0.2s; margin: 2px 0; border-radius: 0 8px 8px 0;
        }
        .tch-nav-btn:hover:not(.disabled) { background: var(--bg-card-hover); color: var(--text-primary); }
        .tch-nav-btn.active { background: var(--tch-accent-soft); color: var(--tch-accent-text); border-left-color: var(--tch-accent); font-weight: 600; }
        .tch-nav-btn.disabled { opacity: 0.5; cursor: not-allowed; }

        .tch-main {
          background: var(--bg-primary); padding: 28px 36px; flex: 1;
          overflow-y: auto; max-height: calc(100vh - 56px);
          display: flex; flex-direction: column; align-items: center;
        }
        .tch-main > * { width: 100%; max-width: 1100px; margin: 0 auto; }

        .tch-panel {
          background: var(--bg-card); border: 1px solid var(--border);
          border-radius: 16px; padding: 28px 32px; margin-bottom: 24px;
          animation: fade-up 0.3s ease-out;
        }
        .tch-panel h2 {
          color: var(--heading-color); font-size: 22px; margin: 0 0 16px;
          padding-bottom: 12px; border-bottom: 1px solid var(--border); font-weight: 700;
        }
        .tch-panel h3 { color: var(--text-primary); font-size: 16px; margin: 24px 0 12px; font-weight: 600; }
        .tch-desc { color: var(--text-secondary); font-size: 13.5px; line-height: 1.7; margin-bottom: 16px; }

        .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .kpi {
          background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px;
          padding: 24px 20px; text-align: center; transition: all 0.25s;
          display: flex; flex-direction: column; justify-content: center;
        }
        .kpi:hover { background: var(--bg-card-hover); border-color: var(--border-strong); transform: translateY(-2px); }
        .kpi span { display: block; color: var(--text-secondary); font-size: 12px; font-weight: 600; letter-spacing: 0.5px; margin-bottom: 8px; }
        .kpi strong { display: block; color: var(--text-primary); font-size: 32px; font-weight: 700; margin-bottom: 8px; line-height: 1.2; }
        .kpi em { display: block; color: var(--text-muted); font-size: 12px; font-style: normal; margin-top: 4px; }
        .kpi-hint { color: var(--text-muted); font-size: 11px; font-style: normal; }

        .viz-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .viz-card {
          background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px; padding: 20px 24px;
        }
        .viz-card h3 { color: var(--heading-color); margin-top: 0; margin-bottom: 12px; font-size: 16px; }
        .viz-card p { color: var(--text-secondary); font-size: 13px; line-height: 1.6; margin-bottom: 12px; }

        .tch-table { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: var(--bg-card); }
        .table-like { display: flex; flex-direction: column; gap: 8px; }
        .tch-table-header {
          display: grid; grid-template-columns: repeat(7, minmax(80px, 1fr));
          background: var(--bg-card-hover); border-bottom: 1px solid var(--border);
          padding: 12px 14px; font-weight: 600; color: var(--text-secondary);
          font-size: 12px; letter-spacing: 0.3px;
        }
        .tch-table-row {
          display: grid; grid-template-columns: repeat(7, minmax(80px, 1fr));
          padding: 12px 14px; border-bottom: 1px solid var(--border);
          align-items: center; color: var(--text-primary);
          transition: background 0.15s; font-size: 13px;
        }
        .tch-table-row:hover { background: var(--bg-card-hover); }
        .tch-cell-time { color: var(--text-muted); font-size: 12px; }
        .tch-cell-score { font-weight: 700; color: var(--accent2); }

        .bar-row { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; padding: 8px 0; }
        .bar-row span:first-child { min-width: 120px; color: var(--text-primary); font-weight: 500; font-size: 13px; }
        .bar-track { flex: 1; height: 22px; background: var(--bg-card-hover); border-radius: 6px; overflow: hidden; }
        .bar-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent2)); transition: width 0.4s; border-radius: 6px; }
        .bar-fill.danger { background: linear-gradient(90deg, #e07070, #c85050); }
        .bar-row em { min-width: 40px; text-align: right; color: var(--text-primary); font-weight: 600; font-style: normal; font-size: 13px; }

        .tch-sm-btn {
          background: var(--tch-accent-soft); color: var(--tch-accent-text);
          border: 1px solid transparent; padding: 6px 12px; border-radius: 8px;
          cursor: pointer; font-size: 12px; font-weight: 500; margin-right: 8px;
          margin-bottom: 6px; transition: all 0.2s;
        }
        .tch-sm-btn:hover { background: var(--bg-card-hover); border-color: var(--border-strong); }

        .project-item {
          margin-top: 0; width: 100%; display: flex; justify-content: space-between;
          align-items: center; gap: 12px; background: var(--bg-card); border: 1px solid var(--border);
          border-radius: 10px; padding: 14px 16px; cursor: pointer; color: var(--text-primary);
          transition: all 0.2s; font-size: 13px;
        }
        .project-item:hover { background: var(--bg-card-hover); border-color: var(--accent); }

        .risk-badge { display: inline-block; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; }
        .risk-badge.high { background: var(--tch-danger-soft); color: var(--tch-danger); border: 1px solid rgba(224,112,112,0.3); }
        .risk-badge.medium { background: var(--tch-warning-soft); color: var(--tch-warning); border: 1px solid rgba(224,168,76,0.3); }
        .risk-badge.low { background: var(--tch-success-soft); color: var(--tch-success); border: 1px solid rgba(92,189,138,0.3); }

        .tch-app input[type="text"],.tch-app input[type="email"],.tch-app textarea,.tch-app select {
          background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border-strong);
          padding: 10px 14px; border-radius: 10px; font-size: 13px; transition: border-color 0.2s;
        }
        .tch-app input::placeholder,.tch-app textarea::placeholder { color: var(--text-muted); }
        .tch-app input:focus,.tch-app textarea:focus { border-color: var(--accent); outline: none; box-shadow: 0 0 0 3px var(--tch-accent-soft); }

        .tch-feedback-form { background: var(--bg-card); padding: 24px; border-radius: 12px; border: 1px solid var(--border); }
        .tch-feedback-form label { color: var(--text-primary); font-weight: 600; font-size: 13px; }
        .tch-feedback-form button { background: linear-gradient(135deg, var(--accent), var(--accent2)); color: #fff; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-weight: 600; transition: all 0.2s; }
        .tch-feedback-form button:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px var(--tch-accent-soft); }
        .tch-feedback-success { background: var(--tch-success-soft); border: 1px solid rgba(92,189,138,0.3); color: var(--tch-success); padding: 12px 16px; border-radius: 8px; margin-top: 12px; }

        .evidence-item { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 16px; margin-bottom: 12px; }
        .evidence-item strong { color: var(--accent-text); font-size: 14px; }
        .evidence-item p { color: var(--text-primary); margin: 8px 0; font-size: 13px; line-height: 1.6; }
        .evidence-item em { color: var(--text-muted); font-size: 12px; }

        .tch-evidence-actions { display: flex; gap: 10px; margin-bottom: 16px; }
        .tch-evidence-actions input { flex: 1; }

        .tch-submission-detail { background: var(--bg-card); border-left: 3px solid var(--accent); padding: 20px; margin-top: 12px; border-radius: 0 10px 10px 0; }
        .tch-detail-section { margin-bottom: 16px; }
        .tch-detail-section:last-child { margin-bottom: 0; }
        .tch-detail-section h4 { color: var(--heading-color); margin: 0 0 8px; font-size: 14px; }
        .tch-detail-section p { color: var(--text-primary); margin: 6px 0; font-size: 13px; line-height: 1.6; }

        .tch-raw-text { background: var(--bg-card); border: 1px solid var(--border); padding: 12px; border-radius: 8px; color: var(--text-primary); font-size: 12px; line-height: 1.6; max-height: 300px; overflow-y: auto; }

        .right-hint { background: var(--tch-accent-soft); border-left: 3px solid var(--accent); color: var(--accent-text); padding: 12px 16px; border-radius: 0 8px 8px 0; margin: 12px 0; font-size: 13px; }
        .right-tag { display: block; background: var(--tch-success-soft); border-left: 3px solid var(--tch-success); color: var(--tch-success); padding: 12px 16px; border-radius: 0 8px 8px 0; margin: 8px 0; font-size: 13px; }

        .tch-loading { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; min-height: 200px; animation: fade-in 0.3s; }
        .tch-loading p { color: var(--text-secondary); font-weight: 500; }

        .tch-report-content { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; color: var(--text-primary); line-height: 1.8; white-space: pre-wrap; word-wrap: break-word; }

        .debug-json summary { cursor: pointer; color: var(--accent-text); font-weight: 600; margin-bottom: 8px; }
        .debug-json pre { background: var(--bg-card); border: 1px solid var(--border); color: var(--text-primary); padding: 12px; border-radius: 8px; overflow-x: auto; font-size: 11px; line-height: 1.5; }

        .tch-back-btn {
          padding: 7px 14px; font-size: 13px; background: var(--bg-card-hover);
          color: var(--text-primary); border: 1px solid var(--border); border-radius: 8px;
          cursor: pointer; transition: all 0.2s; font-weight: 500;
        }
        .tch-back-btn:hover { background: var(--tch-accent-soft); color: var(--tch-accent-text); border-color: var(--accent); }

        .tch-sub-tab-btn {
          padding: 10px 16px; font-size: 13px; font-weight: 600; background: var(--bg-card);
          color: var(--text-secondary); border: 1px solid var(--border); border-radius: 10px;
          cursor: pointer; transition: all 0.2s;
        }
        .tch-sub-tab-btn:hover { background: var(--tch-accent-soft); color: var(--tch-accent-text); border-color: var(--accent); }

        .tch-info-banner { padding: 14px 18px; background: var(--warm-soft); border: 1px solid rgba(232,168,76,0.2); border-radius: 10px; margin-bottom: 20px; color: var(--text-primary); }
        .tch-info-banner strong { color: var(--warm-text); }

        .tch-card-surface { background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; padding: 14px; }
        .tch-file-item { padding: 12px; margin-bottom: 6px; border-radius: 8px; border: 1px solid var(--border); background: var(--bg-card); cursor: pointer; transition: all 0.15s; }
        .tch-file-item:hover { background: var(--bg-card-hover); }
        .tch-file-item.selected { background: var(--tch-accent-soft); border-color: var(--accent); }

        .tch-primary-btn { width: 100%; padding: 9px 16px; background: linear-gradient(135deg, var(--accent), var(--accent2)); color: #fff; border: none; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600; transition: all 0.2s; }
        .tch-primary-btn:hover { transform: translateY(-1px); box-shadow: 0 4px 12px var(--tch-accent-soft); }
        .tch-primary-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
        .tch-success-btn { background: linear-gradient(135deg, var(--tch-success), #4aad7a); }
        .tch-warning-btn { background: linear-gradient(135deg, var(--tch-warning), #c89040); }
        .tch-neutral-btn { background: var(--bg-card-hover); color: var(--text-primary); border: 1px solid var(--border); }

        .tch-progress-bar {
          position: fixed; top: 0; left: 0; right: 0; height: 3px;
          background: linear-gradient(90deg, var(--accent), var(--tch-success));
          animation: progress-line 1.5s ease-in-out infinite; z-index: 999;
        }
        .tch-spinner { width: 36px; height: 36px; border: 3px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; }

        .tch-fix-list { padding-left: 20px; line-height: 2; background: var(--tch-accent-soft); padding: 16px; border-radius: 10px; border-left: 3px solid var(--accent); }
        .tch-fix-list.neutral { background: var(--bg-card); border-left-color: var(--text-muted); }
        .tch-risk-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; padding: 12px; background: var(--tch-danger-soft); border-radius: 10px; border-left: 3px solid var(--tch-danger); }
        .tch-risk-chip { padding: 8px 12px; background: var(--bg-card); border: 1px solid rgba(224,112,112,0.25); border-radius: 8px; display: flex; align-items: center; gap: 8px; font-size: 12px; }
        .tch-risk-chip-badge { display: inline-block; background: var(--tch-danger); color: #fff; padding: 3px 7px; border-radius: 4px; font-size: 11px; font-weight: 700; }

        .tch-stat-summary { margin-bottom: 16px; padding: 12px 16px; background: var(--bg-card); border-radius: 10px; border: 1px solid var(--border); display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
        .tch-stat-summary strong { color: var(--text-primary); }
        .tch-stat-value { font-size: 18px; font-weight: 700; margin-left: 6px; }
        .tch-stat-value.danger { color: var(--tch-danger); }
        .tch-stat-value.accent { color: var(--accent); }

        .tch-weak-rank { padding: 8px 12px; border-radius: 8px; margin-bottom: 6px; display: flex; align-items: center; gap: 8px; }
        .tch-weak-rank.rank-0 { background: var(--tch-danger-soft); }
        .tch-weak-rank.rank-1 { background: var(--tch-warning-soft); }
        .tch-weak-rank.rank-2 { background: var(--tch-success-soft); }

        /* ── 总览页新样式 ── */
        .ov-kpi-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 24px; }
        .ov-kpi-card {
          position: relative; background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 14px;
          padding: 18px 14px; text-align: center; transition: all 0.25s; cursor: default;
        }
        .ov-kpi-card:hover { border-color: var(--border-strong); transform: translateY(-2px); box-shadow: 0 4px 16px rgba(0,0,0,0.1); }
        .ov-kpi-icon { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; margin: 0 auto 10px; font-size: 18px; }
        .ov-kpi-value { font-size: 28px; font-weight: 700; color: var(--text-primary); line-height: 1.2; margin-bottom: 4px; }
        .ov-kpi-label { font-size: 12px; color: var(--text-muted); font-weight: 500; }
        .ov-kpi-tip {
          position: absolute; top: calc(100% + 8px); left: 50%; transform: translateX(-50%);
          background: var(--bg-card); border: 1px solid var(--border-strong); border-radius: 10px;
          padding: 12px 14px; font-size: 12px; line-height: 1.5; z-index: 50; width: 220px;
          text-align: left; box-shadow: 0 8px 24px rgba(0,0,0,0.18); animation: fade-in 0.15s ease-out;
          backdrop-filter: blur(12px);
        }
        .ov-kpi-tip strong { display: block; margin-bottom: 4px; color: var(--accent-text); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
        .ov-kpi-tip p { margin: 0 0 6px; color: var(--text-secondary); font-size: 12px; }
        .ov-kpi-formula { background: var(--bg-secondary); padding: 6px 8px; border-radius: 6px; font-family: monospace; font-size: 11px; color: var(--accent); margin-top: 6px; word-break: break-all; }

        .ov-chart-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; margin-bottom: 24px; }
        .ov-chart-card { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 14px; padding: 20px; }
        .ov-chart-card h3 { margin: 0 0 4px; font-size: 15px; color: var(--heading-color); font-weight: 600; }

        .ov-bar-list { display: flex; flex-direction: column; gap: 10px; }
        .ov-bar-item { display: flex; align-items: center; gap: 10px; padding: 6px 0; cursor: pointer; transition: all 0.2s; animation: fade-in 0.3s ease-out both; }
        .ov-bar-item:hover { padding-left: 4px; }
        .ov-bar-label { min-width: 110px; display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-primary); font-weight: 500; }
        .ov-bar-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
        .ov-bar-track { flex: 1; height: 20px; background: var(--bg-card-hover); border-radius: 6px; overflow: hidden; }
        .ov-bar-fill { height: 100%; border-radius: 6px; transition: width 0.6s ease-out; }
        .ov-bar-val { min-width: 32px; text-align: right; font-weight: 600; font-size: 13px; color: var(--text-primary); }

        .ov-histogram { display: flex; align-items: flex-end; gap: 8px; height: 140px; padding: 12px 0; }
        .ov-hist-col { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; justify-content: flex-end; }
        .ov-hist-count { font-size: 12px; font-weight: 600; color: var(--text-primary); margin-bottom: 4px; }
        .ov-hist-bar { width: 100%; border-radius: 6px 6px 2px 2px; transition: height 0.6s ease-out; min-height: 4px; }
        .ov-hist-label { font-size: 11px; color: var(--text-muted); margin-top: 6px; }

        .ov-section { margin-bottom: 24px; }
        .ov-section h3 { margin: 0 0 4px; font-size: 16px; color: var(--heading-color); font-weight: 600; }

        .ov-activity-list { display: flex; flex-direction: column; background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
        .ov-activity-item { display: flex; align-items: center; gap: 12px; padding: 12px 16px; cursor: pointer; transition: all 0.15s; animation: fade-in 0.3s ease-out both; }
        .ov-activity-item:hover { background: var(--bg-card-hover); }
        .ov-activity-item:not(:last-child) { border-bottom: 1px solid var(--border); }
        .ov-activity-avatar { width: 32px; height: 32px; border-radius: 8px; background: var(--accent-soft); color: var(--accent); display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 14px; flex-shrink: 0; }
        .ov-activity-info { flex: 1; min-width: 0; }
        .ov-activity-name { font-size: 13px; font-weight: 600; color: var(--text-primary); display: flex; align-items: center; gap: 8px; }
        .ov-activity-type { font-size: 11px; font-weight: 500; color: var(--text-muted); background: var(--bg-card-hover); padding: 2px 6px; border-radius: 4px; }
        .ov-activity-detail { font-size: 12px; color: var(--text-secondary); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .ov-activity-score { font-size: 16px; font-weight: 700; flex-shrink: 0; }
        .ov-activity-time { font-size: 11px; color: var(--text-muted); flex-shrink: 0; min-width: 80px; text-align: right; }

        .ov-stu-table { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
        .ov-stu-header { display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; padding: 10px 16px; background: var(--bg-card-hover); font-size: 12px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.3px; }
        .ov-stu-row { display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; padding: 10px 16px; align-items: center; font-size: 13px; border-top: 1px solid var(--border); transition: background 0.15s; animation: fade-in 0.3s ease-out both; }
        .ov-stu-row:hover { background: var(--bg-card-hover); }
        .ov-stu-name { display: flex; align-items: center; gap: 8px; font-weight: 500; color: var(--text-primary); }
        .ov-stu-av { width: 24px; height: 24px; border-radius: 6px; background: var(--accent-soft); color: var(--accent); display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 11px; flex-shrink: 0; }
        .ov-status-badge { padding: 3px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; }

        .ov-risk-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }
        .ov-risk-card { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; cursor: pointer; transition: all 0.2s; text-align: left; width: 100%; color: var(--text-primary); animation: fade-in 0.3s ease-out both; }
        .ov-risk-card:hover { background: var(--bg-card-hover); border-color: var(--tch-danger); transform: translateY(-1px); }
        .ov-risk-hd { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
        .ov-risk-name { font-weight: 600; font-size: 13px; }
        .ov-risk-meta { display: flex; gap: 12px; font-size: 12px; color: var(--text-muted); }

        /* ── 团队管理页：顶部标签 ── */
        .tm-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 20px; }
        .tm-chip { display: inline-flex; align-items: center; gap: 5px; padding: 7px 14px; border-radius: 99px; border: 1px solid var(--border); background: var(--bg-secondary); color: var(--text-secondary); font-size: 12px; cursor: pointer; transition: all 0.2s; font-weight: 500; }
        .tm-chip:hover { border-color: var(--accent); color: var(--text-primary); }
        .tm-chip-active { background: var(--tch-accent-soft); border-color: rgba(107,138,255,0.4); color: var(--accent); font-weight: 700; }
        .tm-chip-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
        .tm-dot-mine { background: var(--accent); box-shadow: 0 0 4px rgba(107,138,255,0.5); }
        .tm-dot-other { background: rgba(255,255,255,0.2); }

        .tm-modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; backdrop-filter: blur(4px); }
        .tm-modal { background: var(--bg-card); border: 1px solid var(--border); border-radius: 16px; padding: 28px; min-width: 360px; max-width: 440px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); }
        .tm-input { width: 100%; padding: 10px 14px; border-radius: 10px; border: 1px solid var(--border); background: var(--bg-secondary); color: var(--text-primary); font-size: 14px; outline: none; transition: border-color 0.2s; }
        .tm-input:focus { border-color: var(--accent); }
        .tm-invite-display { display: flex; align-items: center; gap: 12px; padding: 16px; background: var(--bg-secondary); border-radius: 12px; justify-content: center; }
        .tm-invite-code { font-size: 28px; font-weight: 800; letter-spacing: 4px; color: var(--accent); font-family: monospace; }
        .tm-invite-badge { display: flex; align-items: center; gap: 8px; padding: 6px 12px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; }
        .tm-proj-row { cursor: pointer; padding: 8px 12px; border-radius: 10px; transition: background 0.2s; }
        .tm-proj-row:hover { background: var(--bg-card-hover); }
        .tm-case-hero { display: flex; align-items: flex-start; gap: 16px; padding: 18px 20px; margin-bottom: 20px; border-radius: 18px; border: 1px solid var(--border); background:
          radial-gradient(circle at top right, rgba(107,138,255,0.18), transparent 34%),
          linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01)),
          var(--bg-secondary); }
        .tm-case-avatar { width: 56px; height: 56px; border-radius: 18px; background: var(--tch-accent-soft); display: flex; align-items: center; justify-content: center; font-size: 24px; font-weight: 800; color: var(--accent); flex-shrink: 0; }
        .tm-case-meta { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 6px; font-size: 12px; color: var(--text-muted); }
        .tm-case-badge { display: inline-flex; align-items: center; padding: 4px 10px; border-radius: 999px; background: var(--bg-card); border: 1px solid var(--border); font-size: 11px; color: var(--text-secondary); }
        .tm-case-summary { margin-top: 12px; padding: 12px 14px; border-radius: 14px; background: rgba(107,138,255,0.08); border: 1px solid rgba(107,138,255,0.15); }
        .tm-case-summary-title { font-size: 11px; font-weight: 700; color: var(--accent); letter-spacing: 0.3px; margin-bottom: 6px; }
        .tm-case-summary-body { font-size: 13px; color: var(--text-primary); line-height: 1.7; }
        .tm-signal-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 8px; }
        .tm-signal-box { padding: 10px 8px; border-radius: 12px; background: var(--bg-card-hover); text-align: center; }
        .tm-signal-value { font-size: 18px; font-weight: 800; color: var(--text-primary); }
        .tm-signal-label { font-size: 10px; color: var(--text-muted); margin-top: 2px; }
        .tm-chip-cloud { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
        .tm-smart-chip { display: inline-flex; align-items: center; padding: 5px 10px; border-radius: 999px; background: var(--bg-card-hover); color: var(--text-secondary); font-size: 11px; border: 1px solid var(--border); }
        .tm-note-row { padding: 8px 10px; border-radius: 10px; font-size: 12px; line-height: 1.5; margin-bottom: 6px; }
        .tm-note-row.good { background: rgba(92,189,138,0.10); color: var(--text-secondary); }
        .tm-note-row.bad { background: rgba(224,112,112,0.10); color: var(--text-secondary); }
        .tm-note-row.warn { background: rgba(232,168,76,0.12); color: var(--text-secondary); }
        .tm-linked-row { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 10px; background: var(--bg-card-hover); margin-bottom: 6px; }
        .tm-linked-main { font-size: 12px; color: var(--text-primary); font-weight: 600; }
        .tm-linked-side { font-size: 11px; color: var(--text-muted); }
        .tm-case-inline-summary { padding: 8px 10px; border-radius: 10px; background: rgba(107,138,255,0.08); color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
        .tm-mini-meta { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border); font-size: 10px; color: var(--text-muted); }
        .tm-corridor { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; margin-top: 12px; }
        .tm-corridor-card { position: relative; text-align: left; padding: 16px; border-radius: 18px; border: 1px solid var(--border); background:
          radial-gradient(circle at top right, rgba(107,138,255,0.12), transparent 32%),
          linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01)),
          var(--bg-secondary); cursor: pointer; transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s; }
        .tm-corridor-card:hover { transform: translateY(-2px); border-color: rgba(107,138,255,0.42); box-shadow: 0 14px 30px rgba(8, 19, 49, 0.22); }
        .tm-corridor-card.mine { border-color: rgba(107,138,255,0.34); }
        .tm-corridor-top { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
        .tm-corridor-rank { font-size: 11px; color: var(--accent); font-weight: 700; }
        .tm-corridor-name { margin-top: 4px; font-size: 16px; font-weight: 700; color: var(--text-primary); }
        .tm-corridor-arrow { font-size: 11px; color: var(--text-muted); white-space: nowrap; }
        .tm-corridor-meta { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 8px; font-size: 11px; color: var(--text-muted); }
        .tm-corridor-bars { display: flex; flex-direction: column; gap: 8px; margin-top: 14px; }
        .tm-corridor-barline { display: grid; grid-template-columns: 40px 1fr 42px; gap: 8px; align-items: center; font-size: 11px; color: var(--text-secondary); }
        .tm-corridor-barline div { height: 8px; border-radius: 999px; background: var(--bg-card-hover); overflow: hidden; }
        .tm-corridor-barline i { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, rgba(107,138,255,0.25), #6b8aff); }
        .tm-corridor-barline b { text-align: right; color: var(--text-primary); font-size: 11px; }
        .tm-corridor-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
        .tm-corridor-tooltip { position: absolute; inset: auto 14px 14px 14px; display: flex; flex-direction: column; gap: 5px; padding: 10px 12px; border-radius: 12px; background: rgba(8, 16, 38, 0.92); border: 1px solid rgba(115,204,255,0.18); color: #dfe7ff; font-size: 11px; line-height: 1.55; opacity: 0; transform: translateY(6px); pointer-events: none; transition: opacity 0.2s, transform 0.2s; }
        .tm-corridor-card:hover .tm-corridor-tooltip { opacity: 1; transform: translateY(0); }
        .tm-pulse-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; margin-top: 12px; }
        .tm-pulse-card { text-align: left; padding: 16px; border-radius: 18px; border: 1px solid rgba(107,138,255,0.18); background:
          radial-gradient(circle at left top, rgba(115,204,255,0.10), transparent 30%),
          linear-gradient(180deg, rgba(107,138,255,0.08), rgba(107,138,255,0.02)),
          var(--bg-secondary); cursor: pointer; transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s; }
        .tm-pulse-card:hover { transform: translateY(-2px); border-color: rgba(107,138,255,0.42); box-shadow: 0 12px 26px rgba(13, 21, 43, 0.18); }
        .tm-pulse-card-head { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
        .tm-pulse-label { font-size: 11px; color: var(--accent); font-weight: 700; letter-spacing: 0.2px; }
        .tm-pulse-title { margin-top: 4px; font-size: 16px; font-weight: 700; color: var(--text-primary); }
        .tm-pulse-link { font-size: 11px; color: var(--text-muted); }
        .tm-pulse-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 14px; }
        .tm-pulse-stats div { padding: 10px; border-radius: 12px; background: rgba(255,255,255,0.02); border: 1px solid var(--border); }
        .tm-pulse-stats strong { display: block; font-size: 18px; color: var(--text-primary); }
        .tm-pulse-stats span { display: block; margin-top: 4px; font-size: 10px; color: var(--text-muted); }
        .tm-pulse-spark { height: 66px; margin-top: 12px; padding: 8px; border-radius: 14px; background: rgba(107,138,255,0.06); border: 1px solid rgba(107,138,255,0.1); }
        .tm-pulse-spark svg { width: 100%; height: 100%; }
        .tm-pulse-empty { display: flex; align-items: center; justify-content: center; height: 100%; font-size: 11px; color: var(--text-muted); }
        .tm-pulse-foot { display: flex; justify-content: space-between; gap: 8px; margin-top: 10px; font-size: 11px; color: var(--text-muted); }
        .tm-project-switch-list { display: flex; flex-direction: column; gap: 12px; margin-top: 10px; max-height: 500px; overflow-y: auto; padding-right: 4px; }
        .tm-project-switch-card { padding: 14px; border-radius: 14px; border: 1px solid var(--border); background: var(--bg-secondary); transition: transform 0.15s, border-color 0.15s, background 0.15s; cursor: pointer; }
        .tm-project-switch-card:hover { transform: translateX(2px); border-color: rgba(107,138,255,0.3); background: rgba(107,138,255,0.04); }
        .tm-project-switch-card.active { border-color: var(--accent); background: rgba(107,138,255,0.08); box-shadow: inset 0 0 0 1px rgba(107,138,255,0.12); }
        .tm-intent-panel { display: flex; flex-direction: column; gap: 10px; margin-top: 10px; }
        .tm-intent-row { display: grid; grid-template-columns: 72px 1fr 24px; gap: 8px; align-items: center; font-size: 12px; color: var(--text-secondary); }
        .tm-intent-row div { height: 10px; background: var(--bg-card-hover); border-radius: 999px; overflow: hidden; }
        .tm-intent-row i { display: block; height: 100%; border-radius: 999px; }
        .tm-intent-row b { text-align: right; color: var(--text-primary); font-size: 11px; }
        .tm-evidence-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 10px; }
        .tm-evidence-card { padding: 12px; border-radius: 12px; border: 1px solid var(--border); background: var(--bg-secondary); }
        .tm-evidence-top { display: flex; justify-content: space-between; gap: 8px; font-size: 11px; color: var(--text-muted); }
        .tm-evidence-quote { margin-top: 8px; font-size: 12px; line-height: 1.7; color: var(--text-primary); }
        .tm-project-cover { display: flex; justify-content: space-between; gap: 16px; padding: 18px 20px; margin-bottom: 20px; border-radius: 18px; border: 1px solid rgba(107,138,255,0.2); background:
          radial-gradient(circle at top right, rgba(107,138,255,0.18), transparent 34%),
          linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01)),
          var(--bg-secondary); }
        .tm-project-cover-label { font-size: 11px; color: var(--accent); font-weight: 700; letter-spacing: 0.2px; }
        .tm-project-cover-score { width: 118px; min-width: 118px; border-radius: 18px; background: rgba(107,138,255,0.08); border: 1px solid rgba(107,138,255,0.12); display: flex; flex-direction: column; align-items: center; justify-content: center; }
        .tm-project-cover-score div { font-size: 34px; font-weight: 800; color: var(--text-primary); }
        .tm-project-cover-score span { margin-top: 4px; font-size: 11px; color: var(--text-muted); }
        .tm-threeq-card { padding: 12px 14px; border-radius: 14px; background: var(--bg-secondary); border: 1px solid var(--border); font-size: 13px; line-height: 1.7; color: var(--text-secondary); }
        .tm-threeq-card strong { display: block; margin-bottom: 6px; color: var(--text-primary); }
        .tm-threeq-card.accent { border-color: rgba(107,138,255,0.24); background: rgba(107,138,255,0.06); }
        .tm-intent-timeline { display: flex; flex-direction: column; gap: 12px; margin-top: 10px; }
        .tm-intent-timeline-item { display: grid; grid-template-columns: 14px 1fr; gap: 10px; align-items: flex-start; }
        .tm-intent-timeline-dot { width: 10px; height: 10px; margin-top: 6px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 0 4px rgba(107,138,255,0.1); }
        .tm-risk-chain { display: flex; flex-direction: column; gap: 14px; }
        .tm-risk-chain-card { padding: 16px; border-radius: 16px; border: 1px solid var(--border); background: var(--bg-secondary); }
        .tm-risk-chain-head { display: flex; justify-content: space-between; gap: 8px; align-items: center; color: var(--text-primary); }
        .tm-risk-chain-head span { font-size: 11px; color: var(--text-muted); }
        .tm-risk-chain-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; margin-top: 12px; }
        .assistant-hero { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 18px; flex-wrap: wrap; }
        .assistant-hero-large { padding: 18px 20px; border-radius: 18px; border: 1px solid rgba(107,138,255,0.16); background:
          radial-gradient(circle at top right, rgba(107,138,255,0.16), transparent 30%),
          linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01)),
          var(--bg-secondary); }
        .assistant-workspace { display: flex; flex-direction: column; gap: 18px; }
        .assistant-shell { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.85fr); gap: 18px; }
        .assistant-main-panel, .assistant-side-card { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 16px; }
        .assistant-main-panel { padding: 18px; }
        .assistant-side-panel { display: flex; flex-direction: column; gap: 16px; }
        .assistant-side-card { padding: 16px; }
        .assistant-side-card.sticky { position: sticky; top: 16px; }
        .assistant-panel-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 8px; }
        .assistant-section { margin-top: 14px; }
        .assistant-section:first-child { margin-top: 0; }
        .assistant-section-title { font-size: 12px; font-weight: 700; color: var(--accent); letter-spacing: 0.3px; margin-bottom: 8px; }
        .assistant-list { display: flex; flex-direction: column; gap: 10px; margin-top: 10px; }
        .assistant-list.compact { margin-top: 0; }
        .assistant-queue-card { display: flex; justify-content: space-between; gap: 14px; padding: 14px; border-radius: 14px; border: 1px solid var(--border); background: var(--bg-secondary); transition: border-color 0.2s, transform 0.2s; }
        .assistant-queue-card:hover { border-color: rgba(107,138,255,0.28); transform: translateY(-1px); }
        .assistant-queue-card.compact { align-items: center; }
        .assistant-card-actions { display: flex; flex-direction: column; align-items: flex-end; gap: 10px; min-width: 120px; }
        .assistant-focus-card { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 12px 14px; border-radius: 14px; background: var(--bg-secondary); border: 1px solid var(--border); }
        .assistant-rubric-table { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
        .assistant-rubric-row { display: grid; grid-template-columns: 1.5fr 60px 50px; gap: 10px; align-items: center; padding: 10px 12px; border-radius: 12px; background: var(--bg-card-hover); font-size: 12px; color: var(--text-secondary); }
        .assistant-rubric-row.rich { grid-template-columns: minmax(0, 1.5fr) 72px 54px; }
        .assistant-form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
        .assistant-label { display: block; margin-bottom: 6px; font-size: 12px; color: var(--text-muted); font-weight: 600; }
        .assistant-textarea { min-height: 108px; resize: vertical; }
        .assistant-textarea.small { min-height: 96px; }
        .assistant-student-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 12px; margin-top: 10px; }
        .assistant-student-card { padding: 14px; border-radius: 14px; border: 1px solid var(--border); background: var(--bg-secondary); }
        .assistant-summary-stack, .assistant-insight-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
        .assistant-summary-card { padding: 14px; border-radius: 14px; border: 1px solid var(--border); background: linear-gradient(180deg, rgba(107,138,255,0.08), transparent 45%), var(--bg-secondary); display: flex; flex-direction: column; gap: 6px; }
        .assistant-summary-card span { font-size: 12px; color: var(--text-muted); }
        .assistant-summary-card strong { font-size: 24px; color: var(--text-primary); }
        .assistant-inline-note { font-size: 11px; color: var(--text-muted); margin-top: 6px; line-height: 1.5; }
        .assistant-quote-inline { margin-top: 8px; padding: 8px 10px; border-radius: 10px; background: rgba(107,138,255,0.08); color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
        .assistant-note-list { display: flex; flex-direction: column; gap: 8px; }
        .assistant-toolbar { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
        .assistant-capability-grid { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 16px; align-items: center; }
        .assistant-round-card { padding: 14px; border-radius: 14px; border: 1px solid var(--border); background: var(--bg-card-hover); }
        .assistant-stage-hero { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(280px, 0.8fr); gap: 18px; align-items: stretch; padding: 24px 26px; margin-bottom: 0; border-radius: 28px; border: 1px solid rgba(115,204,255,0.12); background:
          radial-gradient(circle at top left, rgba(115,204,255,0.14), transparent 32%),
          radial-gradient(circle at bottom right, rgba(107,138,255,0.18), transparent 36%),
          linear-gradient(145deg, rgba(13,18,35,0.96), rgba(11,13,26,0.9)); box-shadow: 0 24px 60px rgba(3, 8, 24, 0.32); }
        .assistant-stage-copy { max-width: none; display: grid; gap: 14px; }
        .assistant-stage-copy h2 { font-size: 34px; letter-spacing: -0.03em; color: var(--heading-color); }
        .assistant-stage-tools { display: grid; align-content: space-between; gap: 14px; min-width: 0; }
        .assistant-stage-status { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-start; gap: 8px 12px; padding: 14px 16px; border-radius: 18px; border: 1px solid var(--border); background: rgba(255,255,255,0.05); color: var(--text-secondary); font-size: 12px; }
        .assistant-stage-status-dot { width: 8px; height: 8px; border-radius: 999px; background: #73ccff; box-shadow: 0 0 0 6px rgba(115,204,255,0.12); }
        .assistant-stage-highlights { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
        .assistant-stage-highlight { padding: 14px 16px; border-radius: 18px; border: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.04); display: grid; gap: 4px; }
        .assistant-stage-highlight strong { font-size: 24px; color: var(--text-primary); }
        .assistant-stage-highlight span { font-size: 12px; color: var(--text-secondary); }
        .assistant-stage-actions { display: flex; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
        .assistant-refresh-btn { padding: 11px 16px; border-radius: 14px; border: 1px solid rgba(107,138,255,0.2); background: linear-gradient(135deg, var(--accent), #439eff); color: #fff; cursor: pointer; font-size: 12px; font-weight: 600; transition: transform 0.18s, border-color 0.18s, box-shadow 0.18s; box-shadow: 0 12px 28px rgba(67,158,255,0.18); }
        .assistant-refresh-btn.ghost { background: rgba(255,255,255,0.05); color: var(--text-primary); box-shadow: none; }
        .assistant-refresh-btn:hover { transform: translateY(-1px); border-color: rgba(107,138,255,0.42); }
        .assistant-nav-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px; }
        .assistant-nav-pill { text-align: left; padding: 16px 18px; border-radius: 20px; border: 1px solid var(--border); background: rgba(255,255,255,0.035); color: var(--text-primary); cursor: pointer; transition: transform 0.18s, border-color 0.18s, box-shadow 0.18s; min-height: 94px; display: grid; gap: 6px; }
        .assistant-nav-pill:hover { transform: translateY(-1px); border-color: rgba(107,138,255,0.32); box-shadow: 0 10px 24px rgba(0,0,0,0.06); }
        .assistant-nav-pill.active { border-color: rgba(107,138,255,0.28); background: linear-gradient(135deg, rgba(107,138,255,0.92), rgba(67,158,255,0.88)); box-shadow: 0 16px 36px rgba(67,158,255,0.22); }
        .assistant-nav-pill strong { display: block; font-size: 16px; color: var(--text-primary); margin-bottom: 0; }
        .assistant-nav-pill span { font-size: 12px; color: var(--text-secondary); }
        .assistant-nav-pill.active span { color: rgba(255,255,255,0.86); }
        .assistant-review-shell { display: grid; grid-template-columns: minmax(260px, 300px) minmax(0, 1fr); gap: 18px; }
        .assistant-review-main { min-width: 0; }
        .assistant-project-stack { display: flex; flex-direction: column; gap: 10px; margin-top: 12px; }
        .assistant-project-pill { text-align: left; width: 100%; padding: 14px; border-radius: 16px; border: 1px solid var(--border); background: var(--bg-secondary); color: var(--text-primary); cursor: pointer; transition: transform 0.16s, border-color 0.16s, background 0.16s; }
        .assistant-project-pill:hover { transform: translateX(2px); border-color: rgba(107,138,255,0.3); background: rgba(107,138,255,0.04); }
        .assistant-project-pill.active { border-color: rgba(107,138,255,0.48); background: rgba(107,138,255,0.08); box-shadow: inset 0 0 0 1px rgba(107,138,255,0.12); }
        .assistant-project-pill-top { display: flex; justify-content: space-between; gap: 8px; align-items: center; margin-bottom: 8px; font-size: 11px; color: var(--accent); font-weight: 700; }
        .assistant-cover-warm { background:
          radial-gradient(circle at top right, rgba(107,138,255,0.16), transparent 34%),
          radial-gradient(circle at left bottom, rgba(232,168,76,0.12), transparent 26%),
          linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01)),
          var(--bg-secondary); }
        .assistant-review-grid { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr); gap: 18px; }
        .assistant-rubric-spotlight-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
        .assistant-rubric-spotlight { padding: 16px; border-radius: 18px; border: 1px solid rgba(107,138,255,0.14); background:
          radial-gradient(circle at top right, rgba(107,138,255,0.12), transparent 34%),
          linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0)),
          var(--bg-secondary); }
        .assistant-rubric-spotlight-head { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; margin-bottom: 8px; }
        .assistant-rubric-code { display: inline-block; margin-bottom: 4px; padding: 3px 8px; border-radius: 999px; background: rgba(107,138,255,0.12); color: var(--accent); font-size: 10px; font-weight: 800; letter-spacing: 0.3px; }
        .assistant-rubric-score { min-width: 66px; padding: 8px 10px; border-radius: 14px; background: rgba(255,255,255,0.03); border: 1px solid var(--border); text-align: center; font-size: 15px; font-weight: 800; color: var(--text-primary); }
        .assistant-rubric-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
        .assistant-mini-tag { padding: 6px 10px; border-radius: 999px; border: 1px solid transparent; background: rgba(255,255,255,0.03); font-size: 11px; cursor: pointer; transition: transform 0.16s, border-color 0.16s; }
        .assistant-mini-tag:hover { transform: translateY(-1px); }
        .assistant-mini-tag.good { background: rgba(92,189,138,0.12); color: var(--tch-success); border-color: rgba(92,189,138,0.18); }
        .assistant-mini-tag.warn { background: rgba(224,112,112,0.12); color: var(--tch-danger); border-color: rgba(224,112,112,0.18); }
        .assistant-mini-tag.accent { background: rgba(107,138,255,0.12); color: var(--accent); border-color: rgba(107,138,255,0.18); }
        .assistant-mini-tag.neutral { background: rgba(232,168,76,0.12); color: var(--tch-warning); border-color: rgba(232,168,76,0.18); }
        .assistant-material-grid { display: grid; grid-template-columns: minmax(220px, 280px) minmax(0, 1fr); gap: 14px; }
        .assistant-material-list { display: flex; flex-direction: column; gap: 10px; max-height: 780px; overflow-y: auto; padding-right: 4px; }
        .assistant-material-pill { text-align: left; width: 100%; padding: 12px; border-radius: 14px; border: 1px solid var(--border); background: var(--bg-card-hover); color: var(--text-primary); cursor: pointer; transition: transform 0.16s, border-color 0.16s, background 0.16s; }
        .assistant-material-pill:hover { transform: translateX(2px); border-color: rgba(107,138,255,0.3); }
        .assistant-material-pill.active { border-color: rgba(107,138,255,0.48); background: rgba(107,138,255,0.08); }
        .assistant-material-pill-top { display: flex; justify-content: space-between; gap: 8px; align-items: center; margin-bottom: 6px; font-size: 11px; color: var(--accent); font-weight: 700; }
        .assistant-material-preview { min-width: 0; }
        .submission-corridor { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
        .submission-card { text-align: left; width: 100%; padding: 16px; border-radius: 16px; border: 1px solid var(--border); background:
          radial-gradient(circle at top right, rgba(107,138,255,0.12), transparent 34%),
          linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0)),
          var(--bg-secondary); color: var(--text-primary); cursor: pointer; transition: transform 0.18s, border-color 0.18s, box-shadow 0.18s; }
        .submission-card:hover { transform: translateY(-2px); border-color: rgba(107,138,255,0.32); box-shadow: 0 10px 24px rgba(0,0,0,0.08); }
        .submission-card.active { border-color: rgba(107,138,255,0.42); box-shadow: inset 0 0 0 1px rgba(107,138,255,0.16); }
        .submission-card-top { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
        .submission-card-meta { font-size: 11px; color: var(--text-muted); margin-bottom: 4px; }
        .submission-score-pill { min-width: 54px; text-align: center; padding: 6px 10px; border-radius: 999px; border: 1px solid var(--border); background: rgba(255,255,255,0.02); font-size: 13px; font-weight: 800; }
        .tch-topbar-status { display: inline-flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 999px; background: var(--bg-secondary); border: 1px solid var(--border); color: var(--text-secondary); font-size: 12px; }
        .tch-topbar-status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 8px rgba(107,138,255,0.45); }
        .project-launchpad { padding: 20px 0 6px; }
        .project-launch-card { max-width: 560px; margin: 0 auto; padding: 24px; border-radius: 18px; border: 1px solid var(--border); background:
          radial-gradient(circle at top right, rgba(107,138,255,0.16), transparent 34%),
          linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0)),
          var(--bg-secondary); }
        .project-compare-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 14px; margin-top: 10px; }
        .project-compare-card { text-align: left; width: 100%; padding: 16px; border-radius: 18px; border: 1px solid var(--border); background:
          radial-gradient(circle at top right, rgba(107,138,255,0.14), transparent 34%),
          linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0)),
          var(--bg-secondary); color: var(--text-primary); cursor: pointer; transition: transform 0.18s, border-color 0.18s, box-shadow 0.18s; }
        .project-compare-card:hover { transform: translateY(-2px); border-color: rgba(107,138,255,0.34); box-shadow: 0 10px 24px rgba(0,0,0,0.08); }
        .project-compare-card.active { border-color: rgba(107,138,255,0.5); box-shadow: inset 0 0 0 1px rgba(107,138,255,0.18); }
        .project-compare-top { display: flex; justify-content: space-between; gap: 10px; align-items: center; margin-bottom: 8px; }
        .project-compare-index { font-size: 11px; color: var(--accent); font-weight: 700; }
        .project-compare-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }
        .project-compare-stats div { padding: 10px; border-radius: 12px; border: 1px solid var(--border); background: rgba(255,255,255,0.02); }
        .project-compare-stats strong { display: block; font-size: 18px; color: var(--text-primary); }
        .project-compare-stats span { display: block; margin-top: 4px; font-size: 10px; color: var(--text-muted); }
        .project-rank-list { display: flex; flex-direction: column; gap: 10px; margin-top: 10px; }
        .project-rank-row { width: 100%; display: grid; grid-template-columns: 34px minmax(0, 1.3fr) minmax(100px, 1fr) 42px; gap: 10px; align-items: center; padding: 12px 14px; border-radius: 14px; border: 1px solid var(--border); background: var(--bg-secondary); color: var(--text-primary); cursor: pointer; text-align: left; transition: transform 0.16s, border-color 0.16s; }
        .project-rank-row:hover { transform: translateX(2px); border-color: rgba(107,138,255,0.3); }
        .project-rank-row.active { border-color: rgba(107,138,255,0.48); background: rgba(107,138,255,0.06); }
        .project-rank-order { font-size: 12px; font-weight: 800; color: var(--accent); }
        .project-rank-name { font-size: 13px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .project-rank-track { height: 8px; border-radius: 999px; background: var(--bg-card-hover); overflow: hidden; }
        .project-rank-track i { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, rgba(107,138,255,0.28), #6b8aff); }
        .feedback-shell { display: grid; grid-template-columns: minmax(0, 1fr); gap: 18px; align-items: start; width: 100%; }
        .feedback-main { display: flex; flex-direction: column; gap: 18px; min-width: 0; width: 100%; }
        .feedback-side { display: flex; flex-direction: column; gap: 18px; min-width: 0; }
        .feedback-project-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 10px; }
        .feedback-project-card { text-align: left; width: 100%; padding: 16px; border-radius: 16px; border: 1px solid var(--border); background:
          radial-gradient(circle at top right, rgba(107,138,255,0.14), transparent 32%),
          linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0)),
          var(--bg-secondary); color: var(--text-primary); cursor: pointer; transition: transform 0.18s, border-color 0.18s, box-shadow 0.18s; }
        .feedback-project-card:hover { transform: translateY(-2px); border-color: rgba(107,138,255,0.32); box-shadow: 0 10px 24px rgba(0,0,0,0.08); }
        .feedback-project-card.active { border-color: rgba(107,138,255,0.48); box-shadow: inset 0 0 0 1px rgba(107,138,255,0.16); }
        .feedback-project-top { display: flex; justify-content: space-between; gap: 10px; align-items: center; margin-bottom: 8px; }
        .feedback-project-index { font-size: 11px; font-weight: 700; color: var(--accent); letter-spacing: 0.2px; }
        .feedback-file-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 10px; }
        .feedback-file-card { text-align: left; width: 100%; padding: 14px; border-radius: 16px; border: 1px solid var(--border); background: var(--bg-secondary); color: var(--text-primary); cursor: pointer; transition: transform 0.18s, border-color 0.18s, box-shadow 0.18s; }
        .feedback-file-card:hover { transform: translateY(-1px); border-color: rgba(107,138,255,0.3); box-shadow: 0 8px 18px rgba(0,0,0,0.06); }
        .feedback-file-card.active { border-color: rgba(107,138,255,0.48); background: rgba(107,138,255,0.06); }
        .feedback-file-top { display: flex; justify-content: space-between; gap: 10px; align-items: center; margin-bottom: 8px; }
        .feedback-file-index { font-size: 11px; font-weight: 700; color: var(--accent); }
        .feedback-reader-card { padding: 18px; border-radius: 18px; border: 1px solid var(--border); background:
          linear-gradient(180deg, rgba(107,138,255,0.06), transparent 18%),
          var(--bg-secondary); }
        .feedback-reader-head { display: flex; justify-content: space-between; gap: 14px; align-items: flex-start; margin-bottom: 14px; }
        .feedback-reader-empty, .feedback-empty-state { padding: 28px 22px; border-radius: 16px; border: 1px dashed var(--border-strong); background: linear-gradient(180deg, rgba(107,138,255,0.05), transparent 45%), var(--bg-secondary); color: var(--text-secondary); text-align: center; }
        .feedback-empty-state strong { display: block; color: var(--text-primary); font-size: 16px; margin-bottom: 8px; }
        .feedback-empty-state p { margin: 0; line-height: 1.7; }

        .cls-stu-table .cls-stu-hdr { grid-template-columns: 40px 2fr repeat(4, 1fr); }
        .cls-stu-table .cls-stu-row { grid-template-columns: 40px 2fr repeat(4, 1fr); }

        /* ── 班级(团队)页样式 ── */
        .cls-breadcrumb { display: flex; align-items: center; gap: 6px; padding: 10px 14px; margin-bottom: 20px; background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 10px; font-size: 13px; flex-wrap: wrap; }
        .cls-crumb-item { color: var(--text-secondary); cursor: pointer; transition: color 0.15s; font-weight: 500; }
        .cls-crumb-item:hover { color: var(--accent); }
        .cls-crumb-item.active { color: var(--text-primary); font-weight: 600; cursor: default; }
        .cls-crumb-sep { color: var(--text-muted); font-size: 12px; }

        .cls-stu-table { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
        .cls-stu-hdr { display: grid; grid-template-columns: 40px 2fr repeat(7, 1fr); padding: 10px 16px; background: var(--bg-card-hover); font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.3px; }
        .cls-stu-row { display: grid; grid-template-columns: 40px 2fr repeat(7, 1fr); padding: 11px 16px; align-items: center; font-size: 13px; border-top: 1px solid var(--border); cursor: pointer; transition: all 0.15s; animation: fade-in 0.3s ease-out both; }
        .cls-stu-row:hover { background: var(--tch-accent-soft); }

        .cls-proj-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
        .cls-proj-card { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 12px; padding: 16px; cursor: pointer; transition: all 0.2s; animation: fade-in 0.3s ease-out both; }
        .cls-proj-card:hover { border-color: var(--accent); transform: translateY(-2px); box-shadow: 0 4px 16px rgba(0,0,0,0.1); }

        .cls-timeline { position: relative; padding-left: 24px; }
        .cls-timeline::before { content: ""; position: absolute; left: 7px; top: 0; bottom: 0; width: 2px; background: var(--border); }
        .cls-tl-item { position: relative; margin-bottom: 16px; animation: fade-in 0.3s ease-out both; }
        .cls-tl-dot { position: absolute; left: -20px; top: 6px; width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--bg-primary); z-index: 1; }
        .cls-tl-content { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; transition: border-color 0.15s; }
        .cls-tl-content:hover { border-color: var(--border-strong); }
        .cls-tl-header { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
        .cls-tl-time { font-size: 12px; color: var(--text-muted); font-weight: 500; }
        .cls-tl-type { font-size: 11px; color: var(--text-secondary); background: var(--bg-card-hover); padding: 2px 8px; border-radius: 4px; }
        .cls-tl-score { font-size: 18px; font-weight: 700; margin-left: auto; }
        .cls-tl-bottleneck { font-size: 12px; color: var(--text-secondary); line-height: 1.6; margin-bottom: 4px; padding: 6px 8px; background: var(--tch-warning-soft); border-radius: 6px; }
        .cls-tl-next { font-size: 12px; color: var(--text-secondary); line-height: 1.6; margin-bottom: 4px; padding: 6px 8px; background: var(--tch-success-soft); border-radius: 6px; }
        .cls-tl-rules { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
        .cls-tl-rule-tag { font-size: 11px; padding: 2px 8px; background: var(--tch-danger-soft); color: var(--tch-danger); border-radius: 4px; font-weight: 500; }

        @media (max-width: 768px) {
          .cls-stu-hdr { display: none; }
          .cls-stu-row { grid-template-columns: 1fr; gap: 4px; padding: 12px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; }
          .cls-proj-grid { grid-template-columns: 1fr; }
          .tm-project-cover { flex-direction: column; }
          .tm-project-cover-score { width: 100%; min-width: 0; padding: 18px 0; }
          .tm-pulse-stats { grid-template-columns: 1fr; }
          .tm-intent-row { grid-template-columns: 66px 1fr 24px; }
          .assistant-form-grid { grid-template-columns: 1fr; }
          .assistant-stage-hero, .assistant-stage-highlights, .assistant-nav-strip { grid-template-columns: 1fr; }
          .assistant-stage-tools { align-items: stretch; min-width: 0; }
          .assistant-queue-card, .assistant-focus-card { flex-direction: column; align-items: flex-start; }
          .assistant-shell, .assistant-capability-grid, .assistant-summary-stack, .assistant-insight-grid, .assistant-nav-strip, .assistant-review-shell, .assistant-review-grid, .assistant-material-grid { grid-template-columns: 1fr; }
          .project-compare-grid, .project-compare-stats { grid-template-columns: 1fr; }
          .project-rank-row { grid-template-columns: 34px 1fr; }
          .project-rank-track, .project-rank-row b { grid-column: 2; }
          .feedback-shell { grid-template-columns: 1fr; }
          .feedback-reader-head { flex-direction: column; }
          .assistant-card-actions { align-items: flex-start; }
          .assistant-side-card.sticky { position: static; }
        }

        @media (max-width: 1024px) { .ov-kpi-grid { grid-template-columns: repeat(3, 1fr); } }
        @media (max-width: 768px) {
          .ov-kpi-grid { grid-template-columns: repeat(2, 1fr); }
          .ov-chart-grid { grid-template-columns: 1fr; }
          .ov-stu-header { display: none; }
          .ov-stu-row { grid-template-columns: 1fr; padding: 12px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; }
          .ov-activity-item { flex-wrap: wrap; }
        }

        @keyframes fade-in { from { opacity: 0; } to { opacity: 1; } }
        @keyframes fade-up { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes slide-down { from { opacity: 0; max-height: 0; } to { opacity: 1; max-height: 2000px; } }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes progress-line { 0% { width: 0%; } 50% { width: 80%; } 100% { width: 100%; } }
        @keyframes toast-slide-in { from { opacity: 0; transform: translateX(20px); } to { opacity: 1; transform: translateX(0); } }
        @keyframes number-scale { from { opacity: 0; transform: scale(0.8); } to { opacity: 1; transform: scale(1); } }
        @keyframes skeleton-loading { 0% { background: var(--bg-card); } 50% { background: var(--bg-card-hover); } 100% { background: var(--bg-card); } }

        button:focus-visible, input:focus-visible, textarea:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
        button:disabled { opacity: 0.5; cursor: not-allowed; }

        .tch-main::-webkit-scrollbar, .tch-sidebar::-webkit-scrollbar { width: 6px; }
        .tch-main::-webkit-scrollbar-track, .tch-sidebar::-webkit-scrollbar-track { background: transparent; }
        .tch-main::-webkit-scrollbar-thumb, .tch-sidebar::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 3px; }
        .tch-main::-webkit-scrollbar-thumb:hover, .tch-sidebar::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

        ::selection { background: var(--tch-accent-soft); color: var(--text-primary); }

        @media (max-width: 768px) {
          .tch-main { padding: 16px; }
          .tch-body { flex-direction: column; }
          .tch-sidebar { min-width: 100%; max-height: auto; border-right: none; border-bottom: 1px solid var(--border); display: flex; overflow-x: auto; overflow-y: hidden; padding: 4px; }
          .tch-nav-btn { border-left: none; border-bottom: 2px solid transparent; padding: 10px 14px; white-space: nowrap; border-radius: 8px; }
          .tch-nav-btn.active { border-left: none; border-bottom-color: var(--accent); }
          .tch-panel { padding: 20px 16px; }
          .tch-panel h2 { font-size: 18px; }
          .kpi-grid { grid-template-columns: 1fr; }
          .viz-grid { grid-template-columns: 1fr; }
          .tch-table-header { display: none; }
          .tch-table-row { grid-template-columns: 1fr; padding: 14px 12px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; }
          .topbar-center { display: none; }
        }
        @media (min-width: 769px) and (max-width: 1024px) {
          .tch-main { padding: 24px; }
          .kpi-grid { grid-template-columns: repeat(2, 1fr); }
          .viz-grid { grid-template-columns: 1fr; }
        }
        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
        }
        @media print {
          .tch-sidebar, .chat-topbar { display: none; }
          .tch-body { min-height: auto; }
          .tch-main { padding: 0; max-height: none; overflow: visible; }
          .tch-panel { page-break-inside: avoid; box-shadow: none; }
        }
      `}
      </style>
    </div>
  );
}
