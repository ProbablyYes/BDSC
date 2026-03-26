"use client";

import { FormEvent, useEffect, useMemo, useState, useRef } from "react";
import Link from "next/link";
import { useAuth, logout } from "../hooks/useAuth";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8787").trim().replace(/\/+$/, "");
type Tab = "overview" | "submissions" | "compare" | "evidence" | "report" | "feedback" | "capability" | "rule-coverage" | "interventions" | "class" | "project" | "rubric" | "competition";
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
function ScatterPlot({ data, width = 300, height = 200 }: { data: Array<{ id: string; x: number; y: number }>; width?: number; height?: number }) {
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
      <text x={pad.l + cW / 2} y={height} textAnchor="middle" fill="var(--text-muted)" fontSize="9">提交次数</text>
      <text x={8} y={pad.t + cH / 2} textAnchor="middle" fill="var(--text-muted)" fontSize="9" transform={`rotate(-90,8,${pad.t + cH / 2})`}>均分</text>
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
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [projectId, setProjectId] = useState("demo-project-001");
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
  const [feedbackResult, setFeedbackResult] = useState("");

  const [selectedProject, setSelectedProject] = useState("");
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
  const [teachingInterventions, setTeachingInterventions] = useState<any>(null);

  // 文件级反馈状态
  const [studentFiles, setStudentFiles] = useState<any[]>([]);
  const [selectedFile, setSelectedFile] = useState<any>(null);
  const [fileContent, setFileContent] = useState("");
  const [editedContent, setEditedContent] = useState("");
  const [isEditMode, setIsEditMode] = useState(false);
  const [documentEdits, setDocumentEdits] = useState<any[]>([]);
  const [editSummary, setEditSummary] = useState("");
  const [feedbackAnnotations, setFeedbackAnnotations] = useState<any[]>([]);
  const [annotationText, setAnnotationText] = useState("");
  const [annotationType, setAnnotationType] = useState("issue");
  const [feedbackFileToUpload, setFeedbackFileToUpload] = useState<File | null>(null);
  const [feedbackFiles, setFeedbackFiles] = useState<any[]>([]);
  const [previewData, setPreviewData] = useState<any>(null);  // 文件预览数据（分页/分段）
  const [currentPreviewPage, setCurrentPreviewPage] = useState(1);  // 当前预览页码
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

  async function loadTeachingInterventions() {
    setLoadingMessage("正在分析教学干预方案");
    setLoading(true);
    const data = await api(`/api/teacher/teaching-interventions/${encodeURIComponent(classId.trim() || "default")}`);
    setTeachingInterventions(data);
    setTab("interventions");
    setLoading(false);
  }

  async function submitFeedback(e: FormEvent) {
    e.preventDefault();
    if (!feedbackText.trim() || feedbackText.trim().length < 5) {
      setErrorMessage("反馈内容至少需要5个字符");
      return;
    }
    
    try {
      setErrorMessage("");
      const targetPid = selectedProject || projectId;
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
      setFeedbackResult("");
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "提交反馈失败"}`);
    }
  }

  // 文件级反馈函数
  async function loadStudentFiles() {
    try {
      setLoadingMessage("正在加载学生提交文件");
      setLoading(true);
      setErrorMessage("");
      const targetPid = selectedProject || projectId;
      if (!targetPid.trim()) {
        setErrorMessage("请先输入项目ID");
        setStudentFiles([]);
        return;
      }
      const data = validateResponse(await api(`/api/teacher/student-files/${encodeURIComponent(targetPid)}`), "加载文件列表失败");
      setStudentFiles(data.files || []);
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "加载文件列表失败"}`);
      setStudentFiles([]);
    } finally {
      setLoading(false);
    }
  }

  async function loadFileContent(submissionId: string) {
    try {
      const targetPid = selectedProject || projectId;
      setErrorMessage("");
      setCurrentPreviewPage(1);  // 重置预览页码
      setOnlinePreviewLoading(true);
      setPdfAnalysisLoading(true);
      
      // 第一阶段：并行加载基本数据
      const [fileData, annotationsData, feedbackFilesData, editsData, previewDataResult] = await Promise.all([
        api(`/api/teacher/student-file/${encodeURIComponent(targetPid)}/${encodeURIComponent(submissionId)}`),
        api(`/api/teacher/feedback-annotations/${encodeURIComponent(targetPid)}/${encodeURIComponent(submissionId)}`),
        api(`/api/teacher/feedback-files/${encodeURIComponent(targetPid)}/${encodeURIComponent(submissionId)}`),
        api(`/api/teacher/document-edits/${encodeURIComponent(targetPid)}/${encodeURIComponent(submissionId)}`),
        api(`/api/teacher/file-preview/${encodeURIComponent(targetPid)}/${encodeURIComponent(submissionId)}`)
      ]);
      
      // 第二阶段：根据文件类型决定是否加载PDF分析
      let pdfAnalysisResult: any = null;
      if (previewDataResult?.type === "pdf" && previewDataResult?.pdf_base64) {
        try {
          pdfAnalysisResult = await api(`/api/teacher/pdf-analysis/${encodeURIComponent(targetPid)}/${encodeURIComponent(submissionId)}`);
        } catch (e) {
          // PDF分析失败不影响其他数据
          pdfAnalysisResult = null;
        }
      }
      
      // 批量更新状态
      setSelectedFile(fileData);
      setFileContent(fileData.raw_text || "");
      setEditedContent(fileData.raw_text || "");
      setPreviewData(fileData.preview_data || null);  // 保存预览数据
      setOnlinePreviewData(previewDataResult || null);  // 保存在线预览数据
      setPdfAnalysisData(pdfAnalysisResult || null);  // 保存PDF分析数据
      setIsEditMode(false);
      setFeedbackAnnotations(annotationsData.annotations || []);
      setFeedbackFiles(feedbackFilesData.feedback_files || []);
      setDocumentEdits(editsData.edits || []);
      setOnlinePreviewLoading(false);
      setPdfAnalysisLoading(false);
    } catch (error) {
      setErrorMessage("加载文件内容失败");
      setSelectedFile(null);
      setFileContent("");
      setPreviewData(null);
      setOnlinePreviewData(null);
      setPdfAnalysisData(null);
      setOnlinePreviewLoading(false);
      setPdfAnalysisLoading(false);
    }
  }

  async function saveAnnotation() {
    if (!annotationText.trim() || !selectedFile) {
      setErrorMessage("请输入批注内容并选择文件");
      return;
    }
    
    try {
      const targetPid = selectedProject || projectId;
      setErrorMessage("");
      const payload = {
        project_id: targetPid,
        submission_id: selectedFile.submission_id,
        teacher_id: teacherId,
        annotations: [{
          type: "comment",
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
      const targetPid = selectedProject || projectId;
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
    
    const targetPid = selectedProject || projectId;
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
      const targetPid = selectedProject || projectId;
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
      const targetPid = selectedProject || projectId;
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

  useEffect(() => { loadDashboard(); }, []);

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
        scoreTimeline: sorted.map((s: any) => ({ label: (s.created_at || "").slice(5, 16), value: Number(s.overall_score || 0) })),
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
    { id: "class", label: "团队" },
    { id: "project", label: "项目" },
    { id: "submissions", label: "学生提交" },
    { id: "feedback", label: "写回反馈" },
  ];

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
          <input className="tch-filter-input" value={classId} onChange={(e) => setClassId(e.target.value)} placeholder="班级ID" />
          <input className="tch-filter-input" value={cohortId} onChange={(e) => setCohortId(e.target.value)} placeholder="学期" />
          <input className="tch-filter-input" value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)} placeholder="类别筛选" />
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
          <button className="topbar-btn" onClick={generateReport} disabled={loading}>生成AI报告</button>
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
                if (t.id === "rubric") loadRubricAssessment();
                if (t.id === "competition") loadCompetitionScore();
                if (t.id === "interventions") loadTeachingInterventions();
                if (t.id === "class") {
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
                            <div className="ov-activity-time">{s.created_at ? (s.created_at as string).slice(5, 16) : ""}</div>
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

          {/* ── 学生提交列表 ── */}
          {tab === "submissions" && !loading && (
            <div className="tch-panel fade-up">
              <h2>学生提交记录 ({submissions.length})</h2>
              <p className="tch-desc">学生每次发消息或上传文件，系统自动记录并分析。评分来自规则引擎（满分10），风险为触发的规则ID。点击"展开"查看学生提交的原始内容。</p>
              <div className="tch-table" style={{ animation: "fade-in 0.4s ease-out" }}>
                <div className="tch-table-header">
                  <span>时间</span><span>项目</span><span>学生</span><span>来源</span><span>评分</span><span>风险</span><span>操作</span>
                </div>
                {submissions.length === 0 ? (
                  <p style={{ color: "var(--text-muted)", fontSize: 12, padding: 20, textAlign: "center" }}>📭 暂无提交记录。学生对话后这里会自动出现。</p>
                ) : (
                  submissions.map((s, i) => (
                    <div 
                      key={i} 
                      className="tch-submission-block"
                      style={{
                        animation: `fade-in 0.3s ease-out ${i * 0.05}s both`,
                        transition: "all 0.2s ease",
                      }}
                    >
                      <div className="tch-table-row">
                        <span className="tch-cell-time">{(s.created_at ?? "").slice(0, 16)}</span>
                        <span>{s.project_id}</span>
                        <span>{s.student_id}</span>
                        <span>{s.source_type}{s.filename ? ` (${s.filename})` : ""}</span>
                        <span className="tch-cell-score" style={{ color: Number(s.overall_score) >= 7 ? "var(--tch-success)" : Number(s.overall_score) >= 5 ? "var(--tch-warning)" : "var(--tch-danger)" }}>
                          {s.overall_score}
                        </span>
                        <span>{(s.triggered_rules ?? []).join(", ") || "-"}</span>
                        <span>
                          <button className="tch-sm-btn" onClick={() => setExpandedSubmission(expandedSubmission === i ? null : i)}>
                            {expandedSubmission === i ? "收起" : "展开"}
                          </button>
                          <button className="tch-sm-btn" onClick={() => loadEvidence(s.project_id)}>证据链</button>
                          <button className="tch-sm-btn" onClick={() => { setSelectedProject(s.project_id); setTab("feedback"); }}>批注</button>
                        </span>
                      </div>
                      {expandedSubmission === i && (
                        <div className="tch-submission-detail" style={{ animation: "slide-down 0.3s ease-out" }}>
                          {s.bottleneck && (
                            <div className="tch-detail-section">
                              <h4>💡 系统诊断瓶颈</h4>
                              <p>{s.bottleneck}</p>
                            </div>
                          )}
                          {s.next_task && (
                            <div className="tch-detail-section">
                              <h4>➡️ 系统建议的下一步</h4>
                              <p>{s.next_task}</p>
                            </div>
                          )}
                          {s.kg_analysis?.insight && (
                            <div className="tch-detail-section">
                              <h4>🔗 知识图谱分析</h4>
                              <p>{s.kg_analysis.insight}</p>
                            </div>
                          )}
                          <div className="tch-detail-section">
                            <h4>⚡ 快速操作</h4>
                            <button className="tch-sm-btn" onClick={() => { setSelectedProject(s.project_id); loadRubricAssessment(); }}>Rubric评分</button>
                            <button className="tch-sm-btn" onClick={() => { setSelectedProject(s.project_id); loadCompetitionScore(); }}>竞赛预测</button>
                            <button className="tch-sm-btn" onClick={() => { setSelectedProject(s.project_id); loadProjectDiagnosis(); }}>深度诊断</button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
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
                <button className="topbar-btn" onClick={() => { setTab("feedback"); }}>✍️ 写反馈</button>
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
            <div className="tch-panel fade-up">
              <h2>📝 教师反馈 → 学生端</h2>
              <p className="tch-desc">支持三种反馈方式：1️⃣ 文本反馈（AI参考方向）2️⃣ 文件级批注（逐段评注） 3️⃣ 反馈文件上传（处理后的文件）</p>
              
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px", marginTop: "20px" }}>
                {/* 左侧：学生文件列表 + 文件查看 */}
                <div style={{ background: "var(--bg-card)", padding: "16px", borderRadius: "8px", border: "1px solid var(--border)" }}>
                  <h3 style={{ marginTop: 0, fontSize: "16px", color: "var(--text-primary)" }}>📤 学生提交文件</h3>
                  
                  <div style={{marginBottom: "16px"}}>
                    <input 
                      value={selectedProject || projectId} 
                      onChange={(e) => setSelectedProject(e.target.value)}
                      placeholder="项目ID"
                      style={{ width: "100%", padding: "8px", marginBottom: "8px", borderRadius: "8px", border: "1px solid var(--border)" }}
                    />
                    <button 
                      onClick={loadStudentFiles}
                      style={{
                        width: "100%",
                        padding: "8px 16px",
                        background: "var(--accent)",
                        color: "#fff",
                        border: "none",
                        borderRadius: "8px",
                        cursor: "pointer",
                        fontSize: "14px",
                      }}
                    >
                      🔄 刷新文件列表
                    </button>
                  </div>
                  
                  {studentFiles.length > 0 ? (
                    <div style={{ maxHeight: "400px", overflowY: "auto", marginBottom: "16px" }}>
                      {studentFiles.map((file, idx) => (
                        <div
                          key={idx}
                          onClick={() => loadFileContent(file.submission_id)}
                          style={{
                            padding: "12px",
                            marginBottom: "8px",
                            background: selectedFile?.submission_id === file.submission_id ? "var(--tch-accent-soft)" : "var(--bg-secondary)",
                            border: selectedFile?.submission_id === file.submission_id ? "2px solid var(--accent)" : "1px solid var(--border)",
                            borderRadius: "8px",
                            cursor: "pointer",
                            transition: "all 0.2s ease",
                          }}
                        >
                          <div style={{ fontSize: "13px", fontWeight: "600", color: "var(--text-primary)" }}>
                            {getFileTypeInfo(file.filename).icon} {file.filename}
                          </div>
                          <div style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "4px" }}>
                            {getFileTypeInfo(file.filename).displayName}
                          </div>
                          <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "4px" }}>
                            学生: {file.student_id} | 评分: <span style={{color: file.overall_score >= 7 ? "var(--tch-success)" : file.overall_score >= 5 ? "var(--tch-warning)" : "var(--tch-danger)"}}>{file.overall_score}</span>
                          </div>
                          <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>
                            <span suppressHydrationWarning>{file.created_at ? '已上传' : '未知'}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p style={{ fontSize: "13px", color: "var(--text-muted)", textAlign: "center", padding: "20px 0" }}>
                      📭 暂无学生文件提交，点击"刷新文件列表"查看
                    </p>
                  )}
                  
                  {/* 文件内容查看器 - 支持编辑 */}
                  {selectedFile && (
                    <div style={{marginTop: "12px"}}>
                      {/* 编辑模式切换 */}
                      <div style={{
                        display: "flex",
                        gap: "8px",
                        marginBottom: "8px",
                        flexWrap: "wrap"
                      }}>
                        <button
                          onClick={() => setIsEditMode(!isEditMode)}
                          style={{
                            padding: "6px 12px",
                            fontSize: "12px",
                            background: isEditMode ? "var(--tch-warning)" : "var(--bg-card-hover)",
                            color: isEditMode ? "#fff" : "var(--text-primary)",
                            border: "none",
                            borderRadius: "8px",
                            cursor: "pointer",
                            transition: "all 0.2s",
                          }}
                        >
                          {isEditMode ? "✏️ 编辑中" : "📖 查看"}
                        </button>
                        
                        {isEditMode && editedContent !== fileContent && (
                          <>
                            <button
                              onClick={() => setEditedContent(fileContent)}
                              style={{
                                padding: "6px 12px",
                                fontSize: "12px",
                                background: "var(--bg-card-hover)",
                                color: "var(--text-primary)",
                                border: "none",
                                borderRadius: "8px",
                                cursor: "pointer",
                              }}
                            >
                              ↩️ 撤销
                            </button>
                            <button
                              onClick={saveEditedDocument}
                              style={{
                                padding: "6px 12px",
                                fontSize: "12px",
                                background: "var(--tch-success)",
                                color: "#fff",
                                border: "none",
                                borderRadius: "8px",
                                cursor: "pointer",
                                fontWeight: "600",
                              }}
                            >
                              💾 保存编辑
                            </button>
                          </>
                        )}
                        
                        {!isEditMode && editedContent && editedContent !== fileContent && (
                          <>
                            <button
                              onClick={() => exportDocument('txt')}
                              style={{
                                padding: "6px 12px",
                                fontSize: "12px",
                                background: "var(--accent)",
                                color: "#fff",
                                border: "none",
                                borderRadius: "8px",
                                cursor: "pointer",
                              }}
                            >
                              📥 导出TXT
                            </button>
                          </>
                        )}
                      </div>
                      
                      {/* 编辑摘要输入 */}
                      {isEditMode && (
                        <input
                          value={editSummary}
                          onChange={(e) => setEditSummary(e.target.value)}
                          placeholder="编辑摘要（如：修正拼写错误）"
                          style={{
                            width: "100%",
                            padding: "6px",
                            marginBottom: "8px",
                            borderRadius: "8px",
                            border: "1px solid var(--border)",
                            fontSize: "12px",
                            boxSizing: "border-box",
                          }}
                        />
                      )}
                      
                      {/* 文件内容显示区域 - 根据文件类型智能显示 */}
                      {renderFilePreview(selectedFile, editedContent, isEditMode)}
                      
                      {/* 编辑历史 */}
                      {documentEdits.length > 0 && !isEditMode && (
                        <div style={{marginTop: "12px", paddingTop: "12px", borderTop: "1px solid var(--border)"}}>
                          <div style={{fontSize: "12px", fontWeight: "600", color: "var(--text-primary)", marginBottom: "6px"}}>📝 编辑历史：</div>
                          <div style={{maxHeight: "150px", overflowY: "auto"}}>
                            {documentEdits.slice(0, 5).map((edit, idx) => (
                              <div key={idx} style={{fontSize: "11px", padding: "6px", marginBottom: "4px", background: "var(--bg-card)", borderRadius: "3px", borderLeft: "3px solid var(--accent)"}}>
                                <div style={{color: "var(--text-primary)"}}>{edit.edit_summary || "文档编辑"}</div>
                                <div style={{color: "var(--text-muted)", marginTop: "2px"}}>
                                  {edit.edited_length || 0} 字符 · <span suppressHydrationWarning>{edit.created_at ? '已编辑' : '未知'}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
                
                {/* 右侧：反馈和批注 */}
                <div style={{ background: "var(--bg-card)", padding: "16px", borderRadius: "8px", border: "1px solid var(--border)" }}>
                  <h3 style={{ marginTop: 0, fontSize: "16px", color: "var(--text-primary)" }}>✏️ 添加批注 & 反馈</h3>
                  
                  {selectedFile ? (
                    <>
                      {/* 文本级反馈 */}
                      <div style={{marginBottom: "16px"}}>
                        <label style={{fontSize: "13px", fontWeight: "600", color: "var(--text-primary)", display: "block", marginBottom: "6px"}}>📝 文本反馈</label>
                        <textarea 
                          value={feedbackText} 
                          onChange={(e) => setFeedbackText(e.target.value)}
                          placeholder="写出对项目的整体反馈..." 
                          rows={3}
                          style={{
                            width: "100%",
                            padding: "8px",
                            borderRadius: "8px",
                            border: "1px solid var(--border)",
                            fontSize: "13px",
                            boxSizing: "border-box",
                          }}
                        />
                        <div style={{fontSize: "12px", color: "var(--text-secondary)", marginTop: "4px"}}>
                          关注标签：
                          <input 
                            value={feedbackTags} 
                            onChange={(e) => setFeedbackTags(e.target.value)}
                            placeholder="evidence,business_model,compliance"
                            style={{
                              width: "100%",
                              padding: "4px",
                              marginTop: "4px",
                              borderRadius: "3px",
                              border: "1px solid var(--border)",
                              fontSize: "12px",
                            }}
                          />
                        </div>
                        <button 
                          onClick={submitFeedback}
                          style={{
                            width: "100%",
                            padding: "8px",
                            marginTop: "8px",
                            background: "var(--tch-success)",
                            color: "#fff",
                            border: "none",
                            borderRadius: "8px",
                            cursor: "pointer",
                            fontSize: "13px",
                            fontWeight: "600",
                          }}
                        >
                          💬 提交文本反馈
                        </button>
                      </div>
                      
                      {/* 批注 */}
                      <div style={{marginBottom: "16px", borderTop: "1px solid var(--border)", paddingTop: "12px"}}>
                        <label style={{fontSize: "13px", fontWeight: "600", color: "var(--text-primary)", display: "block", marginBottom: "6px"}}>🎯 段落批注</label>
                        <select 
                          value={annotationType}
                          onChange={(e) => setAnnotationType(e.target.value)}
                          style={{
                            width: "100%",
                            padding: "6px",
                            marginBottom: "8px",
                            borderRadius: "3px",
                            border: "1px solid var(--border)",
                            fontSize: "12px",
                          }}
                        >
                          <option value="praise">👍 亮点</option>
                          <option value="issue">⚠️ 问题</option>
                          <option value="suggest">💡 建议</option>
                          <option value="question">❓ 追问</option>
                        </select>
                        <textarea 
                          value={annotationText} 
                          onChange={(e) => setAnnotationText(e.target.value)}
                          placeholder="写出对本段内容的批注..."
                          rows={2}
                          style={{
                            width: "100%",
                            padding: "6px",
                            borderRadius: "3px",
                            border: "1px solid var(--border)",
                            fontSize: "12px",
                            boxSizing: "border-box",
                          }}
                        />
                        <button 
                          onClick={saveAnnotation}
                          style={{
                            width: "100%",
                            padding: "6px",
                            marginTop: "6px",
                            background: "var(--tch-warning)",
                            color: "#fff",
                            border: "none",
                            borderRadius: "3px",
                            cursor: "pointer",
                            fontSize: "12px",
                          }}
                        >
                          ✓ 保存批注
                        </button>
                      </div>
                      
                      {/* 上传反馈文件 */}
                      <div style={{borderTop: "1px solid var(--border)", paddingTop: "12px"}}>
                        <label style={{fontSize: "13px", fontWeight: "600", color: "var(--text-primary)", display: "block", marginBottom: "6px"}}>📎 上传反馈文件</label>
                        <input 
                          ref={feedbackFileInputRef}
                          type="file"
                          accept=".pdf,.docx,.pptx,.txt"
                          onChange={(e) => setFeedbackFileToUpload(e.target.files?.[0] || null)}
                          style={{width: "100%", marginBottom: "6px"}}
                        />
                        {feedbackFileToUpload && (
                          <div style={{fontSize: "12px", color: "var(--text-secondary)", marginBottom: "6px"}}>
                            ✓ 已选择: {feedbackFileToUpload.name}
                          </div>
                        )}
                        <button 
                          onClick={uploadFeedbackFile}
                          disabled={!feedbackFileToUpload}
                          style={{
                            width: "100%",
                            padding: "6px",
                            background: feedbackFileToUpload ? "var(--accent)" : "var(--bg-card-hover)",
                            color: "#fff",
                            border: "none",
                            borderRadius: "3px",
                            cursor: feedbackFileToUpload ? "pointer" : "not-allowed",
                            fontSize: "12px",
                          }}
                        >
                          📤 上传反馈文件
                        </button>
                      </div>
                      
                      {/* 已上传的反馈文件列表 */}
                      {feedbackFiles.length > 0 && (
                        <div style={{marginTop: "12px", borderTop: "1px solid var(--border)", paddingTop: "12px"}}>
                          <div style={{fontSize: "12px", fontWeight: "600", color: "var(--text-primary)", marginBottom: "6px"}}>已上传反馈文件：</div>
                          {feedbackFiles.map((file, idx) => (
                            <div key={idx} style={{fontSize: "11px", color: "var(--text-secondary)", padding: "4px", marginBottom: "4px", background: "var(--bg-secondary)", borderRadius: "3px"}}>
                              📄 {file.original_filename} &nbsp; <a href={`${API}${file.file_url}`} target="_blank" style={{color: "var(--accent)"}}>下载</a>
                            </div>
                          ))}
                        </div>
                      )}
                      
                      {/* 批注列表 */}
                      {feedbackAnnotations.length > 0 && (
                        <div style={{marginTop: "12px", borderTop: "1px solid var(--border)", paddingTop: "12px"}}>
                          <div style={{fontSize: "12px", fontWeight: "600", color: "var(--text-primary)", marginBottom: "6px"}}>已保存的批注：</div>
                          <div style={{maxHeight: "200px", overflowY: "auto"}}>
                            {feedbackAnnotations.map((ann, idx) => (
                              <div key={idx} style={{fontSize: "11px", padding: "6px", marginBottom: "6px", background: "var(--bg-secondary)", borderRadius: "3px", borderLeft: "3px solid var(--tch-warning)"}}>
                                <div style={{color: "var(--text-secondary)"}}>{ann.overall_feedback || (ann.annotations?.[0]?.content || "")}</div>
                                <div style={{color: "var(--text-muted)", marginTop: "2px"}} suppressHydrationWarning>{ann.created_at ? '已添加' : '未知'}</div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  ) : (
                    <p style={{ fontSize: "13px", color: "var(--text-muted)", textAlign: "center", padding: "40px 20px" }}>
                      👈 请从左侧选择一个学生文件以开始批注
                    </p>
                  )}
                </div>
              </div>
              
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
            <div className="tch-panel fade-up">
              <h2>🎯 项目管理</h2>
              <p className="tch-desc">输入项目ID以访问项目级别的评分、诊断和竞赛预测。</p>

              {!projectIdConfirmed ? (
                <div style={{ padding: "32px", textAlign: "center", animation: "fade-in 0.3s ease-out" }}>
                  <div style={{ maxWidth: "400px", margin: "0 auto" }}>
                    <input
                      type="text"
                      placeholder="请输入项目 ID"
                      value={projectTabInput}
                      onChange={(e) => setProjectTabInput(e.target.value)}
                      style={{
                        width: "100%",
                        padding: "12px 16px",
                        fontSize: "16px",
                        marginBottom: "16px",
                        boxSizing: "border-box",
                        border: "1px solid var(--border)",
                        borderRadius: "10px",
                      }}
                      onKeyPress={(e) => {
                        if (e.key === "Enter" && projectTabInput.trim()) {
                          setSelectedProject(projectTabInput);
                          setProjectIdConfirmed(true);
                        }
                      }}
                    />
                    <button
                      onClick={() => {
                        if (projectTabInput.trim()) {
                          setSelectedProject(projectTabInput);
                          setProjectIdConfirmed(true);
                        }
                      }}
                      style={{
                        width: "100%",
                        padding: "12px 16px",
                        fontSize: "16px",
                        background: projectTabInput.trim() ? "var(--accent)" : "var(--bg-card-hover)",
                        color: projectTabInput.trim() ? "#fff" : "var(--text-muted)",
                        border: "none",
                        borderRadius: "10px",
                        cursor: projectTabInput.trim() ? "pointer" : "not-allowed",
                        transition: "all 0.2s",
                      }}
                      disabled={!projectTabInput.trim()}
                    >
                      确认项目ID
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="tch-info-banner">
                    <p style={{ margin: "0" }}>
                      <strong>当前项目 ID：</strong> {selectedProject}
                      <button
                        onClick={() => setProjectIdConfirmed(false)}
                        className="tch-back-btn"
                        style={{ marginLeft: 16, fontSize: 12 }}
                      >
                        切换项目
                      </button>
                    </p>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "12px", marginBottom: "32px" }}>
                    {PROJECT_SUB_TABS.map((subTab) => (
                      <button
                        key={subTab.id}
                        className="tch-sub-tab-btn"
                        onClick={() => {
                          setTab(subTab.id as Tab);
                          if (subTab.id === "rubric") loadProjectDiagnosis();
                          if (subTab.id === "competition") loadCompetitionScore();
                          if (subTab.id === "evidence") loadEvidence(selectedProject);
                        }}
                      >
                        {subTab.label}
                      </button>
                    ))}
                  </div>
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
                const metrics = ["均分", "提交量", "风险率", "趋势"];
                const maxV = [10, Math.max(1, ...all.map((t: any) => t.total_submissions)), Math.max(1, ...all.map((t: any) => t.risk_rate)), 6];
                return (
                  <>
                    <h2 style={{ marginTop: 0 }}>团队横向对比</h2>
                    <p className="tch-desc">从多维度审视所有团队表现差异，★ 标记的为我的团队</p>

                    {/* KPI */}
                    <div className="ov-kpi-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
                      <div className="ov-kpi-card"><div className="ov-kpi-icon" style={{ background: "rgba(107,138,255,0.15)", color: "var(--accent)" }}>🏫</div><div className="ov-kpi-value"><AnimatedNumber value={all.length} /></div><div className="ov-kpi-label">团队总数</div></div>
                      <div className="ov-kpi-card"><div className="ov-kpi-icon" style={{ background: "rgba(115,204,255,0.15)", color: "#73ccff" }}>👥</div><div className="ov-kpi-value"><AnimatedNumber value={all.reduce((a: number, t: any) => a + t.student_count, 0)} /></div><div className="ov-kpi-label">学生总数</div></div>
                      <div className="ov-kpi-card"><div className="ov-kpi-icon" style={{ background: "rgba(92,189,138,0.15)", color: "var(--tch-success)" }}>📝</div><div className="ov-kpi-value"><AnimatedNumber value={all.reduce((a: number, t: any) => a + t.total_submissions, 0)} /></div><div className="ov-kpi-label">提交总量</div></div>
                      <div className="ov-kpi-card"><div className="ov-kpi-icon" style={{ background: "rgba(232,168,76,0.15)", color: "var(--tch-warning)" }}>⭐</div><div className="ov-kpi-value"><AnimatedNumber value={all.length > 0 ? all.reduce((a: number, t: any) => a + t.avg_score, 0) / all.length : 0} decimals={1} /></div><div className="ov-kpi-label">全局均分</div></div>
                    </div>

                    {/* ─ Heatmap Matrix: teams × metrics ─ */}
                    <div className="ov-chart-card" style={{ marginBottom: 20 }}>
                      <h3>多维热力矩阵</h3>
                      <p className="tch-desc">颜色越深表现越好（风险率列反色），点击团队名可进入详情</p>
                      <div style={{ overflowX: "auto" }}>
                        <table style={{ width: "100%", borderCollapse: "separate", borderSpacing: 3, fontSize: 12 }}>
                          <thead><tr><th style={{ textAlign: "left", color: "var(--text-muted)", padding: "6px 10px", fontWeight: 500 }}>团队</th>
                            {metrics.map(m => <th key={m} style={{ textAlign: "center", color: "var(--text-muted)", padding: "6px 8px", fontWeight: 500 }}>{m}</th>)}
                            <th style={{ textAlign: "center", color: "var(--text-muted)", padding: "6px 8px", fontWeight: 500 }}>教师</th>
                          </tr></thead>
                          <tbody>{all.map((t: any) => {
                            const vals = [t.avg_score, t.total_submissions, t.risk_rate, t.trend + 3];
                            return (
                              <tr key={t.team_id} style={{ cursor: "pointer" }} onClick={() => { setSelectedTeamId(t.team_id); setTeamView("team-detail"); }}>
                                <td style={{ padding: "8px 10px", fontWeight: t.is_mine ? 700 : 400, color: t.is_mine ? "var(--accent)" : "var(--text-primary)", whiteSpace: "nowrap" }}>{t.is_mine ? "★ " : ""}{t.team_name}</td>
                                {vals.map((v, mi) => {
                                  const norm = Math.min(1, Math.max(0, v / maxV[mi]));
                                  const inv = mi === 2;
                                  const intensity = inv ? 1 - norm : norm;
                                  const bg = intensity > 0.7 ? "rgba(92,189,138,0.35)" : intensity > 0.4 ? "rgba(232,168,76,0.25)" : "rgba(224,112,112,0.25)";
                                  const display = mi === 0 ? v.toFixed(1) : mi === 2 ? `${v.toFixed(0)}%` : mi === 3 ? (t.trend > 0 ? `+${t.trend.toFixed(1)}` : t.trend.toFixed(1)) : v;
                                  return <td key={mi} style={{ textAlign: "center", padding: "8px", borderRadius: 6, background: bg, fontWeight: 600, color: "var(--text-primary)", transition: "background 0.3s" }}>{display}</td>;
                                })}
                                <td style={{ textAlign: "center", padding: "8px", color: "var(--text-muted)", fontSize: 11 }}>{t.teacher_name}</td>
                              </tr>
                            );
                          })}</tbody>
                        </table>
                      </div>
                    </div>

                    {/* ─ Lollipop chart: score ranking ─ */}
                    <div className="ov-chart-card" style={{ marginBottom: 20 }}>
                      <h3>均分排名·棒棒糖图</h3>
                      <p className="tch-desc">圆点位置表示均分，带线连接至零轴，蓝色为我的团队</p>
                      <svg viewBox={`0 0 500 ${all.length * 36 + 20}`} style={{ width: "100%", overflow: "visible" }}>
                        {[...all].sort((a: any, b: any) => b.avg_score - a.avg_score).map((t: any, i) => {
                          const x = (t.avg_score / 10) * 380 + 110;
                          const y = i * 36 + 20;
                          const col = t.is_mine ? "#6b8aff" : "rgba(255,255,255,0.25)";
                          return (
                            <g key={t.team_id} style={{ cursor: "pointer" }} onClick={() => { setSelectedTeamId(t.team_id); setTeamView("team-detail"); }}>
                              <line x1="110" y1={y} x2={x} y2={y} stroke={col} strokeWidth="2" strokeLinecap="round" />
                              <circle cx={x} cy={y} r="7" fill={col} stroke="var(--bg-primary)" strokeWidth="2" />
                              <text x={x + 12} y={y + 4} fill="var(--text-secondary)" fontSize="11" fontWeight="600">{t.avg_score}</text>
                              <text x="105" y={y + 4} fill={t.is_mine ? "#6b8aff" : "var(--text-muted)"} fontSize="11" textAnchor="end" fontWeight={t.is_mine ? 700 : 400}>{t.team_name.slice(0, 10)}</text>
                            </g>
                          );
                        })}
                      </svg>
                    </div>

                    {/* ─ Ring gauges for my teams ─ */}
                    <div className="ov-chart-card">
                      <h3>我的团队·环形指标</h3>
                      <p className="tch-desc">每个环表示一个团队的均分占满分比</p>
                      <div style={{ display: "flex", justifyContent: "center", gap: 32, flexWrap: "wrap", padding: "12px 0" }}>
                        {(teamData.my_teams ?? []).map((t: any) => {
                          const pct = (t.avg_score / 10) * 100;
                          const r = 38; const c = 2 * Math.PI * r;
                          const col = t.avg_score >= 7 ? "#5cbd8a" : t.avg_score >= 5 ? "#e0a84c" : "#e07070";
                          return (
                            <div key={t.team_id} style={{ textAlign: "center", cursor: "pointer" }} onClick={() => { setSelectedTeamId(t.team_id); setTeamView("team-detail"); }}>
                              <svg width="92" height="92" viewBox="0 0 92 92">
                                <circle cx="46" cy="46" r={r} fill="none" stroke="var(--bg-card-hover)" strokeWidth="7" />
                                <circle cx="46" cy="46" r={r} fill="none" stroke={col} strokeWidth="7" strokeLinecap="round" strokeDasharray={`${c * pct / 100} ${c}`} transform="rotate(-90 46 46)" style={{ transition: "stroke-dasharray 1s ease" }} />
                                <text x="46" y="44" textAnchor="middle" fill="var(--text-primary)" fontSize="18" fontWeight="700">{t.avg_score}</text>
                                <text x="46" y="58" textAnchor="middle" fill="var(--text-muted)" fontSize="9">/10</text>
                              </svg>
                              <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 4, fontWeight: 600 }}>{t.team_name.slice(0, 8)}</div>
                              <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{t.student_count}人 · {t.total_submissions}次</div>
                            </div>
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

              {/* ══════ VIEW: Student Detail ══════ */}
              {teamView === "student-detail" && !loading && teamData && (() => {
                const team = (teamData.my_teams ?? []).find((t: any) => t.team_id === selectedTeamId);
                const stu = team?.students?.find((s: any) => s.student_id === selectedTeamStudentId);
                if (!stu) return <p style={{ color: "var(--text-muted)", padding: 40, textAlign: "center" }}>学生数据未找到</p>;
                const projects: any[] = stu.projects || [];
                const allSubs = projects.flatMap((p: any) => (p.submissions || []));
                const timelineData = [...allSubs].sort((a: any, b: any) => (a.created_at || "").localeCompare(b.created_at || "")).map((s: any) => ({ label: (s.created_at || "").slice(5, 16), value: s.overall_score }));
                return (
                  <>
                    <h2 style={{ marginTop: 0 }}>{stu.display_name} · 项目演进</h2>
                    <p className="tch-desc">点击项目卡片可查看详细迭代过程</p>

                    <div className="ov-kpi-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
                      {[
                        { icon: "📝", bg: "rgba(107,138,255,0.15)", c: "var(--accent)", v: stu.total_submissions, l: "总提交", d: 0 },
                        { icon: "📁", bg: "rgba(92,189,138,0.15)", c: "var(--tch-success)", v: stu.project_count, l: "项目数", d: 0 },
                        { icon: "⭐", bg: "rgba(232,168,76,0.15)", c: "var(--tch-warning)", v: stu.avg_score, l: "均分", d: 1 },
                        { icon: "📈", bg: "rgba(115,204,255,0.15)", c: "#73ccff", v: stu.trend, l: "趋势", d: 1 },
                      ].map((k, i) => (
                        <div key={i} className="ov-kpi-card">
                          <div className="ov-kpi-icon" style={{ background: k.bg, color: k.c }}>{k.icon}</div>
                          <div className="ov-kpi-value" style={{ color: k.c }}>{k.l === "趋势" && k.v > 0 ? "+" : ""}<AnimatedNumber value={k.v} decimals={k.d} /></div>
                          <div className="ov-kpi-label">{k.l}</div>
                        </div>
                      ))}
                    </div>

                    {timelineData.length >= 2 && (
                      <div className="ov-chart-card" style={{ marginBottom: 20 }}>
                        <h3>成绩变化曲线</h3>
                        <AreaChart data={timelineData} color="rgba(107,138,255,0.9)" height={130} />
                      </div>
                    )}

                    {/* ─ Project progress bars ─ */}
                    <div className="ov-chart-card" style={{ marginBottom: 20 }}>
                      <h3>各项目得分进度</h3>
                      <p className="tch-desc">每条表示一个项目的最新得分(满10分)和进步幅度</p>
                      <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 8 }}>
                        {projects.map((p: any) => {
                          const col = p.latest_score >= 7 ? "#5cbd8a" : p.latest_score >= 5 ? "#e0a84c" : "#e07070";
                          return (
                            <div key={p.project_id} style={{ cursor: "pointer" }} onClick={() => { setSelectedTeamProjectId(p.project_id); setTeamView("project-detail"); }}>
                              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4, fontSize: 12 }}>
                                <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>{p.project_name}</span>
                                <span style={{ color: col, fontWeight: 700 }}>{p.latest_score} <span style={{ fontSize: 10, fontWeight: 400, color: p.improvement > 0 ? "var(--tch-success)" : p.improvement < 0 ? "var(--tch-danger)" : "var(--text-muted)" }}>{p.improvement > 0 ? `↑${p.improvement}` : p.improvement < 0 ? `↓${Math.abs(p.improvement)}` : ""}</span></span>
                              </div>
                              <div style={{ height: 8, background: "var(--bg-card-hover)", borderRadius: 4, overflow: "hidden" }}>
                                <div style={{ width: `${(p.latest_score / 10) * 100}%`, height: "100%", background: `linear-gradient(90deg, ${col}88, ${col})`, borderRadius: 4, transition: "width 0.8s ease" }} />
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>

                    <div className="ov-section">
                      <h3>项目列表 ({projects.length})</h3>
                      <div className="cls-proj-grid">
                        {projects.map((proj: any, idx: number) => {
                          const impColor = proj.improvement > 0 ? "var(--tch-success)" : proj.improvement < 0 ? "var(--tch-danger)" : "var(--text-muted)";
                          const miniTimeline = (proj.submissions || []).map((s: any) => ({ label: (s.created_at || "").slice(5, 10), value: s.overall_score }));
                          return (
                            <div key={proj.project_id} className="cls-proj-card" style={{ animationDelay: `${idx * 0.05}s` }} onClick={() => { setSelectedTeamProjectId(proj.project_id); setTeamView("project-detail"); }}>
                              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                                <strong style={{ fontSize: 14, color: "var(--text-primary)" }}>{proj.project_name}</strong>
                                <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{proj.submission_count} 次</span>
                              </div>
                              {miniTimeline.length >= 2 && <div style={{ height: 50, marginBottom: 6 }}><AreaChart data={miniTimeline} height={50} color={impColor === "var(--tch-success)" ? "rgba(92,189,138,0.8)" : "rgba(107,138,255,0.7)"} /></div>}
                              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12 }}>
                                <span style={{ color: "var(--text-secondary)" }}>{proj.first_score} → <strong style={{ color: proj.latest_score >= 7 ? "var(--tch-success)" : proj.latest_score >= 5 ? "var(--tch-warning)" : "var(--tch-danger)" }}>{proj.latest_score}</strong></span>
                                <span style={{ fontWeight: 700, color: impColor }}>{proj.improvement > 0 ? `+${proj.improvement}` : proj.improvement < 0 ? `${proj.improvement}` : "—"}</span>
                              </div>
                            </div>
                          );
                        })}
                      </div>
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
                const scoreTimeline = subs.map((s: any) => ({ label: (s.created_at || "").slice(5, 16), value: s.overall_score }));
                return (
                  <>
                    <h2 style={{ marginTop: 0 }}>{proj.project_name}</h2>
                    <p className="tch-desc">学生 {stu.display_name} 的完整迭代记录</p>

                    <div className="ov-kpi-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
                      <div className="ov-kpi-card"><div className="ov-kpi-icon" style={{ background: "rgba(107,138,255,0.15)", color: "var(--accent)" }}>📊</div><div className="ov-kpi-value"><AnimatedNumber value={proj.avg_score} decimals={1} /></div><div className="ov-kpi-label">均分</div></div>
                      <div className="ov-kpi-card"><div className="ov-kpi-icon" style={{ background: "rgba(92,189,138,0.15)", color: "var(--tch-success)" }}>📈</div><div className="ov-kpi-value" style={{ color: proj.improvement >= 0 ? "var(--tch-success)" : "var(--tch-danger)" }}>{proj.improvement >= 0 ? "+" : ""}<AnimatedNumber value={proj.improvement} decimals={1} /></div><div className="ov-kpi-label">进步</div></div>
                      <div className="ov-kpi-card"><div className="ov-kpi-icon" style={{ background: "rgba(232,168,76,0.15)", color: "var(--tch-warning)" }}>🔄</div><div className="ov-kpi-value"><AnimatedNumber value={proj.submission_count} /></div><div className="ov-kpi-label">迭代</div></div>
                      <div className="ov-kpi-card"><div className="ov-kpi-icon" style={{ background: "rgba(189,147,249,0.15)", color: "#bd93f9" }}>📄</div><div className="ov-kpi-value"><AnimatedNumber value={subs.filter((s: any) => s.filename).length} /></div><div className="ov-kpi-label">文件</div></div>
                    </div>

                    {scoreTimeline.length >= 2 && (
                      <div className="ov-chart-card" style={{ marginBottom: 20 }}>
                        <h3>评分演进</h3>
                        <AreaChart data={scoreTimeline} color="rgba(107,138,255,0.9)" height={140} />
                      </div>
                    )}

                    <div className="ov-section">
                      <h3>迭代时间线</h3>
                      <div className="cls-timeline">
                        {subs.map((sub: any, idx: number) => {
                          const sc = Number(sub.overall_score || 0);
                          const scColor = sc >= 7 ? "var(--tch-success)" : sc >= 5 ? "var(--tch-warning)" : "var(--tch-danger)";
                          const prevSc = idx > 0 ? Number(subs[idx - 1].overall_score || 0) : 0;
                          const delta = idx > 0 && sc > 0 && prevSc > 0 ? sc - prevSc : null;
                          return (
                            <div key={idx} className="cls-tl-item" style={{ animationDelay: `${idx * 0.04}s` }}>
                              <div className="cls-tl-dot" style={{ background: scColor }} />
                              <div className="cls-tl-content">
                                <div className="cls-tl-header">
                                  <span className="cls-tl-time">{(sub.created_at || "").slice(0, 16)}</span>
                                  <span className="cls-tl-type">{sub.source_type === "file" ? `📄 ${sub.filename || "文件"}` : "💬 文本"}</span>
                                  <span className="cls-tl-score" style={{ color: scColor }}>{sc.toFixed(1)}</span>
                                  {delta !== null && <span style={{ fontSize: 11, fontWeight: 700, color: delta > 0 ? "var(--tch-success)" : delta < 0 ? "var(--tch-danger)" : "var(--text-muted)", marginLeft: 4 }}>{delta > 0 ? `+${delta.toFixed(1)}` : delta.toFixed(1)}</span>}
                                </div>
                                {sub.bottleneck && <div className="cls-tl-bottleneck"><strong>🎯 瓶颈：</strong>{sub.bottleneck}</div>}
                                {sub.next_task && <div className="cls-tl-next"><strong>➡️ 建议：</strong>{sub.next_task}</div>}
                                {(sub.triggered_rules?.length || 0) > 0 && (
                                  <div className="cls-tl-rules">{sub.triggered_rules.map((r: string) => <span key={r} className="cls-tl-rule-tag">{getRuleDisplayName(r)}</span>)}</div>
                                )}
                              </div>
                            </div>
                          );
                        })}
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
