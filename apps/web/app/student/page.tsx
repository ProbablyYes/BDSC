"use client";

import { Children, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import ReactMarkdown from "react-markdown";
import PosterPreview, { type PosterDesign } from "./PosterPreview";
import FinanceAdvisoryCard from "./FinanceAdvisoryCard";
import FinanceReportView from "./FinanceReportView";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });
import remarkGfm from "remark-gfm";
import { useAuth, logout } from "../hooks/useAuth";
import BudgetPanel from "../budget/BudgetPanel";
import KBGraphPanel from "../knowledge/KBGraphPanel";
import { RationaleCard, type Rationale } from "../components/RationaleCard";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8037").trim().replace(/\/+$/, "");

type ChatMessage = { role: "user" | "assistant"; text: string; ts?: string; id: number; advisory?: unknown };
type RightTab =
  | "agents"
  | "task"
  | "bp"
  | "risk"
  | "score"
  | "finance"
  | "kg"
  | "hyper"
  | "cases"
  | "feedback"
  | "interventions"
  | "debug";
type ConvMeta = { conversation_id: string; title: string; created_at: string; message_count: number; last_message: string };

type BpRevisionChange = { kind: "add" | "remove" | "context"; text: string };
type BpRevision = {
  revision_id: string;
  section_id: string;
  section_title: string;
  summary: string;
  reason: string;
  source_hint?: string;
  old_content: string;
  new_content: string;
  changes?: BpRevisionChange[];
};
type BpSection = {
  section_id: string;
  title: string;
  display_title?: string;
  content: string;
  ai_draft?: string;
  user_edit?: string;
  field_map?: Record<string, any>;
  missing_points?: string[];
  confidence?: number;
  evidence_sources?: string[];
  revision_status?: string;
  missing_level?: "complete" | "mostly_complete" | "partial" | "critical";
  status?: string;
  is_custom?: boolean;
  narrative_opening?: string;
  has_material?: boolean;
  is_ai_stub?: boolean;
  bullets?: string[];
};
type BpMaturity = {
  score?: number;
  tier?: "not_ready" | "basic_ready" | "full_ready";
  breakdown?: {
    skeleton?: number;
    agent_density?: number;
    coherence?: number;
    skeleton_max?: number;
    agent_density_max?: number;
    coherence_max?: number;
  };
  next_gap?: Array<{
    dimension?: string;
    field?: string;
    field_label?: string;
    current_level?: string;
    current_level_label?: string;
    reason?: string;
    suggestion?: string;
  }>;
  field_levels?: Record<string, string>;
};
type BpUpgradeReport = {
  mode?: "basic" | "full";
  requested?: string[];
  success_ids?: string[];
  failed_ids?: string[];
  timestamp?: string;
};
type BusinessPlan = {
  plan_id: string;
  project_id: string;
  conversation_id: string;
  title: string;
  status: string;
  version_tier?: "draft" | "basic" | "full";
  plan_type?: "main" | "competition_fork";
  fork_of?: string | null;
  mode?: "coursework" | "competition" | "learning";
  submission_status?: "draft" | "submitted" | "graded";
  sections: BpSection[];
  pending_revisions?: BpRevision[];
  revision_badge_count?: number;
  cover_info?: Record<string, any>;
  knowledge_base?: Record<string, any>;
  kb_reference?: Record<string, any>;
  maturity?: BpMaturity;
  upgrade_report?: BpUpgradeReport;
  updated_at?: string;
  created_at?: string;
};
type BusinessPlanResponse = {
  status: string;
  plan: BusinessPlan | null;
  readiness?: {
    ready?: boolean;
    filled_core_count?: number;
    missing_core_slots?: string[];
    suggested_questions?: string[];
    maturity_score?: number;
    maturity_tier?: "not_ready" | "basic_ready" | "full_ready";
    maturity_tier_label?: string;
    maturity_breakdown?: BpMaturity["breakdown"];
    maturity_next_gap?: BpMaturity["next_gap"];
    maturity_field_levels?: Record<string, string>;
  };
};
type BpDeepenQuestion = { id: string; text: string; focus_point?: string };
type BpDeepenSuggestion = {
  section_id: string;
  section_title?: string;
  priority?: number;
  question?: string;
  why?: string;
};

type VideoRubricItem = { item: string; score: number; weight: number; status: "ok" | "risk"; reason?: string };
type VideoAnalysisResult = {
  overall_score: number | null;
  score_band: string;
  rubric: VideoRubricItem[];
  transcript: string;
  summary: string;
  presentation_feedback?: string;
};
type VideoAnalysisResponse = {
  project_id: string;
  student_id: string;
  filename: string;
  created_at: string;
  analysis: VideoAnalysisResult;
};
type VideoAnalysisRecord = {
  project_id: string;
  student_id: string;
  class_id?: string | null;
  cohort_id?: string | null;
  mode?: string;
  competition_type?: string;
  filename: string;
  created_at: string;
  analysis: VideoAnalysisResult;
};

let _msgId = 0;

const MODE_WELCOME: Record<string, { title: string; desc: string; hints: Array<{ icon: string; text: string }> }> = {
  coursework: {
    title: "你好，我是你的课程导师",
    desc: "把你卡住的一个具体问题抛给我，我会先讲清你到底卡在哪，再把方法、判断标准和项目应用讲透。",
    hints: [
      { icon: "📚", text: "什么是价值主张？我总分不清它和产品功能有什么区别，能用一个简单的创业例子帮我讲清楚吗？" },
      { icon: "🧭", text: "TAM、SAM、SOM 到底怎么算？我知道概念但一到自己项目里就发虚，能带我用一个真实例子走一遍吗？" },
      { icon: "🧩", text: "老师说我的项目'有用不等于有商业价值'，这两者的区别到底在哪？怎么判断一个功能有没有商业价值？" },
      { icon: "✍️", text: "什么叫MVP？它和'先做一个原型'有什么区别？我想知道怎么用最小成本验证一个想法是否成立。" },
    ],
  },
  competition: {
    title: "你好，我是你的竞赛教练",
    desc: "如果你正准备比赛、答辩或路演，我会按评委视角帮你看证据、逻辑、扣分点和说服力。把你的项目材料发给我，或者先问我竞赛方法论。",
    hints: [
      { icon: "🏆", text: "互联网+比赛中评委打分最看重哪几项？每一项要做到什么程度才算及格？" },
      { icon: "📊", text: "评委说我的项目'缺少需求验证的证据'，在竞赛材料里'证据'到底指什么？什么样的证据最有说服力？" },
      { icon: "🎤", text: "路演开场30秒最该讲什么？有没有一个经过验证的黄金结构可以参考？" },
      { icon: "🛡️", text: "答辩时评委最喜欢从哪些角度挑战？我该怎么提前准备防守策略？" },
    ],
  },
  learning: {
    title: "你好，我是你的项目教练",
    desc: "把项目现状、卡点或材料发给我，我会优先判断你现在真正卡住的那一层，而不是一下子铺开一大堆任务。",
    hints: [
      { icon: "🎯", text: "从想法到MVP验证再到落地，一个创业项目要过哪几关？每一关该怎么判断自己有没有过关？" },
      { icon: "🔎", text: "怎么判断我的项目现在该先做用户验证还是先做产品原型？有没有一个判断框架？" },
      { icon: "🪫", text: "什么叫'需求验证'？我怎么用最低成本做一次有效的需求验证，验证完该看什么信号？" },
      { icon: "🧠", text: "我有一个大方向但还没想清楚细节，怎么做需求验证来快速判断这个方向值不值得做？" },
    ],
  },
};

function escapeHtmlClient(s: any): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function parseServerTime(value?: string) {
  if (!value) return null;
  const normalized = /Z$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`;
  const d = new Date(normalized);
  return Number.isNaN(d.getTime()) ? null : d;
}

function formatBjTime(value?: string | Date, withDate = false) {
  const d = value instanceof Date ? value : parseServerTime(value);
  if (!d) return "";
  return new Intl.DateTimeFormat("zh-CN", withDate
    ? { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }
    : { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit" }).format(d);
}

function annotationStyle(type: string) {
  const map: Record<string, { label: string; cls: string }> = {
    praise: { label: "亮点", cls: "praise" },
    issue: { label: "问题", cls: "issue" },
    suggest: { label: "建议", cls: "suggest" },
    question: { label: "追问", cls: "question" },
  };
  return map[type] || map.issue;
}

function renderAnnotatedStudentText(text: string, annotations: any[]) {
  const source = String(text || "").trim();
  if (!source) return null;
  const sorted = [...(annotations || [])]
    .filter((item: any) => item.quote || item.length > 0)
    .sort((a: any, b: any) => Number(a.position || 0) - Number(b.position || 0));
  if (!sorted.length) return <div className="student-annotated-text">{source}</div>;
  const nodes: JSX.Element[] = [];
  let cursor = 0;
  sorted.forEach((item: any, idx: number) => {
    const start = Math.max(cursor, Number(item.position || 0));
    const end = item.quote ? start + String(item.quote).length : start + Math.max(0, Number(item.length || 0));
    if (start > cursor) nodes.push(<span key={`plain-${idx}`}>{source.slice(cursor, start)}</span>);
    nodes.push(
      <mark key={`mark-${idx}`} className={`student-inline-mark ${annotationStyle(item.annotation_type).cls}`} title={item.content || item.overall_feedback || ""}>
        {source.slice(start, end) || item.quote}
      </mark>
    );
    cursor = Math.max(cursor, end);
  });
  if (cursor < source.length) nodes.push(<span key="tail">{source.slice(cursor)}</span>);
  return <div className="student-annotated-text">{nodes}</div>;
}

let _mermaidReady: Promise<typeof import("mermaid")["default"]> | null = null;
let _mermaidTheme = "";
let _mermaidSeq = 0;

function getMermaid(theme: "dark" | "light") {
  const wantTheme = theme === "dark" ? "dark" : "default";
  if (!_mermaidReady || _mermaidTheme !== wantTheme) {
    _mermaidTheme = wantTheme;
    _mermaidReady = import("mermaid").then((mod) => {
      const m = mod.default;
      m.initialize({
        startOnLoad: false,
        securityLevel: "loose",
        theme: wantTheme,
        fontFamily: "Inter, Segoe UI, sans-serif",
        fontSize: 12,
        flowchart: { nodeSpacing: 16, rankSpacing: 28, curve: "basis", htmlLabels: true },
      } as any);
      return m;
    });
  }
  return _mermaidReady;
}

function _quoteUnquotedBrackets(s: string): string {
  return s.replace(/(\b\w+)\[([^\]"'][^\]]*)\]/g, (_m, id, label) =>
    `${id}["${label.replace(/"/g, "'")}"]`
  );
}

function sanitizeL0(raw: string): string {
  let s = raw.trim();
  s = s.replace(/[\u201c\u201d]/g, '"');
  s = s.replace(/[\u2018\u2019]/g, "'");
  s = s.replace(/\uff1f/g, "?").replace(/\uff01/g, "!").replace(/\uff1b/g, ";");
  s = s.replace(/\uff1a/g, ":").replace(/\uff0c/g, ",").replace(/\u3001/g, ",");
  s = s.replace(/[\u200b\u200c\u200d\ufeff]/g, "");
  s = _quoteUnquotedBrackets(s);
  return s;
}

function sanitizeL1(raw: string): string {
  let s = sanitizeL0(raw);
  s = s.replace(/\s*(?:-->|-.->|==>|~~>|-\.->)\s*$/gm, "");
  const opens = (s.match(/\bsubgraph\b/gi) || []).length;
  const ends = (s.match(/^\s*end\s*$/gm) || []).length;
  for (let i = 0; i < opens - ends; i++) s += "\n    end";
  s = s.replace(/^\s*\n/gm, "");
  return s;
}

function sanitizeL2(raw: string): string {
  let s = sanitizeL1(raw);
  s = s.replace(/<br\s*\/?>/gi, " / ");
  s = s.replace(/(\b\w+)\(([^)"'][^)]*)\)/g, (_m, id, label) =>
    `${id}["${label.replace(/"/g, "'")}"]`
  );
  return s;
}

function cleanupMermaidDom(id: string) {
  document.getElementById(id)?.remove();
  document.getElementById("d" + id)?.remove();
}

function MermaidBlock({ chart, theme }: { chart: string; theme: "dark" | "light" }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [showSource, setShowSource] = useState(false);
  const [copied, setCopied] = useState(false);
  const [scale, setScale] = useState(1);
  const [renderOk, setRenderOk] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const baseId = `mmrd-${++_mermaidSeq}-${Date.now()}`;
    const ids: string[] = [];

    async function doRender() {
      const mermaid = await getMermaid(theme);
      const levels = [sanitizeL0(chart), sanitizeL1(chart), sanitizeL2(chart)];

      for (let lvl = 0; lvl < levels.length; lvl++) {
        const rid = `${baseId}-L${lvl}`;
        ids.push(rid);
        try {
          await mermaid.parse(levels[lvl]);
          const { svg, bindFunctions } = await mermaid.render(rid, levels[lvl]);
          if (cancelled || !hostRef.current) return;
          hostRef.current.innerHTML = svg;
          bindFunctions?.(hostRef.current);
          setRenderOk(true);
          setShowSource(false);
          return;
        } catch {
          cleanupMermaidDom(rid);
        }
      }
      if (!cancelled) {
        setRenderOk(false);
        setShowSource(true);
      }
    }

    doRender();
    return () => {
      cancelled = true;
      ids.forEach(cleanupMermaidDom);
      if (hostRef.current) hostRef.current.innerHTML = "";
    };
  }, [chart, theme]);

  const handleCopy = () => {
    navigator.clipboard.writeText(chart).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  };

  return (
    <div className="mermaid-card">
      <div className="mermaid-head">
        <span>{renderOk ? "流程图" : "流程图 (源码)"}</span>
        <div className="mermaid-toolbar">
          {renderOk && (
            <>
              <button className="mermaid-btn" onClick={() => setScale((v) => Math.min(3, v + 0.25))} title="放大">+</button>
              <button className="mermaid-btn" onClick={() => setScale((v) => Math.max(0.25, v - 0.25))} title="缩小">-</button>
              {scale !== 1 && <button className="mermaid-btn" onClick={() => setScale(1)}>1:1</button>}
              <button className="mermaid-btn" onClick={() => setShowSource((v) => !v)}>{showSource ? "图表" : "</>"}</button>
            </>
          )}
          <button className="mermaid-btn" onClick={handleCopy}>{copied ? "✓ 已复制" : "复制"}</button>
        </div>
      </div>
      {showSource ? (
        <pre className="mermaid-source"><code>{chart}</code></pre>
      ) : (
        <div className="mermaid-stage">
          <div ref={hostRef} style={{ transform: `scale(${scale})`, transformOrigin: "top center", transition: "transform 0.15s" }} />
        </div>
      )}
    </div>
  );
}

function MarkdownContent({ content, theme }: { content: string; theme: "dark" | "light" }) {
  const components = useMemo(() => ({
    pre(props: any) {
      const child = Children.toArray(props.children)[0] as any;
      const className = String(child?.props?.className || "");
      if (className.includes("language-mermaid")) {
        const chart = String(child?.props?.children || "").replace(/\n$/, "");
        return <MermaidBlock chart={chart} theme={theme} />;
      }
      return <pre {...props} />;
    },
    table(props: any) {
      return (
        <div className="md-table-wrap">
          <table {...props} />
        </div>
      );
    },
  }), [theme]);

  return <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>{content}</ReactMarkdown>;
}

export default function StudentPage() {
  const currentUser = useAuth("student");
  const [projectId, setProjectId] = useState("");
  const [studentId, setStudentId] = useState("");
  const [studentNumber, setStudentNumber] = useState("");
  const [classId, setClassId] = useState("");
  const [cohortId, setCohortId] = useState("");
  const [mode, setMode] = useState("coursework");
  const [competitionType, setCompetitionType] = useState<"" | "internet_plus" | "challenge_cup" | "dachuang">("");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [latestResult, setLatestResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [rightTab, setRightTab] = useState<RightTab>("task");
  const [rightOpen, setRightOpen] = useState(false);
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const [topbarMoreOpen, setTopbarMoreOpen] = useState(false);
  const [budgetPanelOpen, setBudgetPanelOpen] = useState(false);
  const [kbPanelOpen, setKbPanelOpen] = useState(false);
  const [dockCompOpen, setDockCompOpen] = useState(false);
  const [teacherFeedback, setTeacherFeedback] = useState<any[]>([]);
  const [teacherAnnotationBoards, setTeacherAnnotationBoards] = useState<any[]>([]);
  const [selectedAnnotationBoardId, setSelectedAnnotationBoardId] = useState("");
  const [teacherInterventions, setTeacherInterventions] = useState<any[]>([]);
  const [convSidebarOpen, setConvSidebarOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(240);
  const sidebarDragRef = useRef(false);
  const [conversations, setConversations] = useState<ConvMeta[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [attachedFile, setAttachedFile] = useState<File | null>(null);

  // Conversation -> logical_project_id 映射（用于在 topbar / 列表显示项目编号）
  const [convToLogicalId, setConvToLogicalId] = useState<Record<string, string>>({});
  const [sidBannerDismissed, setSidBannerDismissed] = useState(false);
  const [pidCopied, setPidCopied] = useState(false);

  // document review (now with PDF viewer)
  const [docReview, setDocReview] = useState<{ filename: string; sections: any[]; annotations: any[]; fileUrl?: string } | null>(null);
  const [docReviewOpen, setDocReviewOpen] = useState(false);
  const [docReviewLoading, setDocReviewLoading] = useState(false);
  const [docSelectedText, setDocSelectedText] = useState("");
  const [docAskPos, setDocAskPos] = useState<{ x: number; y: number } | null>(null);
  const [pdfViewerOpen, setPdfViewerOpen] = useState(false);
  const [pdfViewerUrl, setPdfViewerUrl] = useState<string>("");

  // competition & pitch simulation
  const [pitchTimer, setPitchTimer] = useState<number>(0);
  const [pitchTimerRunning, setPitchTimerRunning] = useState(false);
  const [pitchDuration, setPitchDuration] = useState(300);
  const pitchIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // video pitch analysis
  const [videoAnalysis, setVideoAnalysis] = useState<VideoAnalysisResult | null>(null);
  const [videoLoading, setVideoLoading] = useState(false);
  const [videoError, setVideoError] = useState<string | null>(null);
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [videoHistory, setVideoHistory] = useState<VideoAnalysisRecord[]>([]);
  const [selectedVideoHistoryIdx, setSelectedVideoHistoryIdx] = useState<number>(-1);

  // new features
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [searchQuery, setSearchQuery] = useState("");
  const [rightWidth, setRightWidth] = useState(360);
  const [likedMsgs, setLikedMsgs] = useState<Set<number>>(new Set());
  const [dislikedMsgs, setDislikedMsgs] = useState<Set<number>>(new Set());
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [kgViewport, setKgViewport] = useState({ scale: 1, x: 0, y: 0 });

  const [teamPanelOpen, setTeamPanelOpen] = useState(false);
  const [myTeams, setMyTeams] = useState<any[]>([]);
  const [joinCode, setJoinCode] = useState("");
  const [teamMsg, setTeamMsg] = useState("");
  const [hyperLibrary, setHyperLibrary] = useState<any>(null);
  const [hyperProjectView, setHyperProjectView] = useState<any>(null);
  const [hgCatalog, setHgCatalog] = useState<any>(null);
  const [kbStats, setKbStats] = useState<any>(null);
  const [posterDesign, setPosterDesign] = useState<PosterDesign | null>(null);
  const [posterLoading, setPosterLoading] = useState(false);
  const [posterError, setPosterError] = useState("");
  const [posterPanelOpen, setPosterPanelOpen] = useState(false);
  const [posterEditMode, setPosterEditMode] = useState(false);
  const [videoPanelOpen, setVideoPanelOpen] = useState(false);
  const [businessPlan, setBusinessPlan] = useState<BusinessPlan | null>(null);
  const [bpReadiness, setBpReadiness] = useState<any>(null);
  const [bpLoading, setBpLoading] = useState(false);
  const [bpSaving, setBpSaving] = useState(false);
  const [bpError, setBpError] = useState("");
  const [bpSelectedSectionId, setBpSelectedSectionId] = useState("");
  const [bpEditorContent, setBpEditorContent] = useState("");
  const [bpViewMode, setBpViewMode] = useState<"read" | "edit">("read");
  const [bpDrawerOpen, setBpDrawerOpen] = useState(false);
  const [bpScrollProgress, setBpScrollProgress] = useState(0);
  const [activeBpSectionId, setActiveBpSectionId] = useState("");
  const [bpMaturityOpen, setBpMaturityOpen] = useState(false);
  const [bpSuggestDrawerOpen, setBpSuggestDrawerOpen] = useState(false);
  const [bpSuggestions, setBpSuggestions] = useState<BpDeepenSuggestion[]>([]);
  const [bpSuggestLoading, setBpSuggestLoading] = useState(false);
  const [bpDeepenSectionId, setBpDeepenSectionId] = useState("");
  const [bpDeepenQuestions, setBpDeepenQuestions] = useState<BpDeepenQuestion[]>([]);
  const [bpDeepenAnswers, setBpDeepenAnswers] = useState<Record<string, string>>({});
  const [bpDeepenLoading, setBpDeepenLoading] = useState(false);
  const [bpDeepenSubmitting, setBpDeepenSubmitting] = useState(false);
  const [bpUpgradeBusy, setBpUpgradeBusy] = useState(false);
  const [bpExportBusy, setBpExportBusy] = useState(false);
  const [bpMoreOpen, setBpMoreOpen] = useState(false);
  const [bpAcceptAllBusy, setBpAcceptAllBusy] = useState(false);
  const [bpUpgradeToast, setBpUpgradeToast] = useState("");
  const [bpOutlineOpen, setBpOutlineOpen] = useState(false);
  const [bpOutlinePinned, setBpOutlinePinned] = useState(false);
  const [bpFinalizeBusy, setBpFinalizeBusy] = useState(false);
  const [bpSnapshotBusy, setBpSnapshotBusy] = useState(false);
  const [bpSnapshotOpen, setBpSnapshotOpen] = useState(false);
  const [bpSnapshots, setBpSnapshots] = useState<any[]>([]);
  const [bpSnapshotLoading, setBpSnapshotLoading] = useState(false);
  const [bpTeacherComments, setBpTeacherComments] = useState<any[]>([]);
  const [bpCommentsOpen, setBpCommentsOpen] = useState(false);
  const [bpSiblings, setBpSiblings] = useState<Array<{plan_id:string; title?:string; plan_type?:string; fork_of?:string|null; mode?:string; version_tier?:string; submission_status?:string; updated_at?:string}>>([]);
  // 竞赛教练议题板
  const [bpAgendaItems, setBpAgendaItems] = useState<Array<{
    agenda_id: string;
    plan_id?: string;
    conversation_id?: string;
    source_message_id?: string;
    jury_tag?: string;
    section_id_hint?: string;
    title?: string;
    gist?: string;
    evidence_hint?: string;
    status?: string;
    created_at?: string;
  }>>([]);
  const [bpAgendaBusy, setBpAgendaBusy] = useState(false);
  const [bpAgendaSelected, setBpAgendaSelected] = useState<Set<string>>(new Set());
  const [bpAgendaExpanded, setBpAgendaExpanded] = useState<Set<string>>(new Set());
  const [bpForkBusy, setBpForkBusy] = useState(false);
  const [bpGrading, setBpGrading] = useState<any | null>(null);
  const [bpGradingOpen, setBpGradingOpen] = useState(false);
  const [bpGradingWhyId, setBpGradingWhyId] = useState<string | null>(null);
  const bpMoreRef = useRef<HTMLDivElement>(null);
  const bpOutlineHoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const bpReadRootRef = useRef<HTMLDivElement>(null);
  const bpSectionRefs = useRef<Record<string, HTMLElement | null>>({});
  const modeWelcome = MODE_WELCOME[mode] ?? MODE_WELCOME.coursework;

  const fileInputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const dragRef = useRef<{ active: boolean; startX: number; startW: number }>({ active: false, startX: 0, startW: 360 });
  const abortRef = useRef<AbortController | null>(null);
  const kgPanRef = useRef<{ active: boolean; startX: number; startY: number; x: number; y: number }>({ active: false, startX: 0, startY: 0, x: 0, y: 0 });
  const kgGraphShellRef = useRef<HTMLDivElement>(null);
  const [kgGraphWidth, setKgGraphWidth] = useState(460);
  useEffect(() => {
    const el = kgGraphShellRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = Math.round(entry.contentRect.width);
        if (w > 0) setKgGraphWidth(w);
      }
    });
    ro.observe(el);
    setKgGraphWidth(el.clientWidth || 460);
    return () => ro.disconnect();
  }, []);
  // canvas ref removed — now using SVG

  // pitch timer
  useEffect(() => {
    if (pitchTimerRunning && pitchTimer > 0) {
      pitchIntervalRef.current = setInterval(() => {
        setPitchTimer((t) => {
          if (t <= 1) { setPitchTimerRunning(false); return 0; }
          return t - 1;
        });
      }, 1000);
    }
    return () => { if (pitchIntervalRef.current) clearInterval(pitchIntervalRef.current); };
  }, [pitchTimerRunning]);

  function startPitchTimer() {
    setPitchTimer(pitchDuration);
    setPitchTimerRunning(true);
  }
  function stopPitchTimer() {
    setPitchTimerRunning(false);
    setPitchTimer(0);
  }
  function formatTime(s: number) {
    return `${Math.floor(s / 60).toString().padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`;
  }

  const refreshKbStats = useCallback(() => {
    fetch(`${API_BASE}/api/kb-stats`).then(r => r.json()).then(d => setKbStats(d)).catch(() => {});
  }, []);
  useEffect(() => { refreshKbStats(); }, [refreshKbStats]);
  useEffect(() => { if (rightTab === "kg") refreshKbStats(); }, [rightTab, refreshKbStats]);

  // apply theme
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const loadConversations = useCallback(async () => {
    if (!projectId) return;
    try {
      const r = await fetch(`${API_BASE}/api/conversations?project_id=${encodeURIComponent(projectId)}`);
      const d = await r.json();
      setConversations(d.conversations ?? []);
    } catch { /* ignore */ }
  }, [projectId]);

  useEffect(() => { loadConversations(); }, [loadConversations]);

  // 拉取 submissions 用于构建 conversation → logical_project_id 映射
  const loadLogicalIdMap = useCallback(async () => {
    if (!projectId) return;
    try {
      const r = await fetch(`${API_BASE}/api/project/${encodeURIComponent(projectId)}/submissions`);
      const d = await r.json();
      const map: Record<string, string> = {};
      for (const sub of (d.submissions ?? []) as any[]) {
        const cid = sub?.conversation_id;
        const lid = sub?.logical_project_id;
        if (cid && lid && !map[cid]) map[cid] = String(lid);
      }
      setConvToLogicalId(map);
    } catch { /* ignore */ }
  }, [projectId]);

  useEffect(() => { loadLogicalIdMap(); }, [loadLogicalIdMap]);
  // 每次用户新对话产生 latestResult 时，也可能要刷新 mapping
  useEffect(() => {
    if (latestResult) loadLogicalIdMap();
  }, [latestResult, loadLogicalIdMap]);

  const currentLogicalProjectId = useMemo(() => {
    if (!conversationId) return "";
    return convToLogicalId[conversationId] || "";
  }, [conversationId, convToLogicalId]);

  function copyProjectId() {
    const v = currentLogicalProjectId;
    if (!v) return;
    try {
      navigator.clipboard?.writeText(v);
      setPidCopied(true);
      setTimeout(() => setPidCopied(false), 1500);
    } catch { /* ignore */ }
  }

  const selectedBpSection = useMemo(
    () => (businessPlan?.sections ?? []).find((item) => item.section_id === bpSelectedSectionId) ?? (businessPlan?.sections ?? [])[0] ?? null,
    [businessPlan, bpSelectedSectionId],
  );

  useEffect(() => {
    if (!selectedBpSection) return;
    setBpSelectedSectionId(selectedBpSection.section_id);
    setBpEditorContent(selectedBpSection.user_edit || selectedBpSection.content || "");
  }, [selectedBpSection?.section_id, selectedBpSection?.content, selectedBpSection?.user_edit]);

  useEffect(() => {
    if (bpViewMode !== "read") return;
    const root = bpReadRootRef.current;
    if (!root) return;
    const handle = () => {
      const max = root.scrollHeight - root.clientHeight;
      setBpScrollProgress(max > 0 ? Math.min(1, Math.max(0, root.scrollTop / max)) : 0);
    };
    handle();
    root.addEventListener("scroll", handle, { passive: true });
    return () => root.removeEventListener("scroll", handle);
  }, [bpViewMode, businessPlan?.plan_id, businessPlan?.sections?.length]);

  useEffect(() => {
    if (bpViewMode !== "read") return;
    const root = bpReadRootRef.current;
    const sections = businessPlan?.sections ?? [];
    if (!root || sections.length === 0) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => (a.boundingClientRect.top || 0) - (b.boundingClientRect.top || 0))[0];
        if (visible) {
          const id = (visible.target as HTMLElement).dataset.sectionId || "";
          if (id) setActiveBpSectionId(id);
        }
      },
      { root, rootMargin: "-40% 0px -55% 0px", threshold: 0 },
    );
    sections.forEach((section) => {
      const el = bpSectionRefs.current[section.section_id];
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, [bpViewMode, businessPlan?.plan_id, businessPlan?.sections?.length]);

  // ── 拉教师批注 ────────────────────────────────────────────────
  useEffect(() => {
    const pid = businessPlan?.plan_id;
    if (!pid) { setBpTeacherComments([]); return; }
    (async () => {
      try {
        const resp = await fetch(`${API_BASE}/api/business-plan/${encodeURIComponent(pid)}/comments`);
        const data = await resp.json();
        setBpTeacherComments(Array.isArray(data?.comments) ? data.comments : []);
      } catch {
        setBpTeacherComments([]);
      }
    })();
  }, [businessPlan?.plan_id, businessPlan?.updated_at]);

  // ── 把教师批注注入到阅读视图（DOM 后处理）────────────────────
  useEffect(() => {
    if (bpViewMode !== "read") return;
    const root = bpReadRootRef.current;
    if (!root) return;
    const timer = setTimeout(() => {
      root.querySelectorAll("mark.bp-tch-mark").forEach((el) => {
        const parent = el.parentNode;
        if (!parent) return;
        while (el.firstChild) parent.insertBefore(el.firstChild, el);
        parent.removeChild(el);
        parent.normalize();
      });
      const sections = root.querySelectorAll<HTMLElement>("[data-section-id]");
      const orphans: Record<string, any[]> = {};
      sections.forEach((secEl) => {
        const sid = secEl.dataset.sectionId || "";
        const list = bpTeacherComments.filter((c: any) => c.section_id === sid && (c.status || "open") === "open");
        list.forEach((c: any) => {
          if (!c.quote) { (orphans[sid] = orphans[sid] || []).push(c); return; }
          const walker = document.createTreeWalker(secEl, NodeFilter.SHOW_TEXT, {
            acceptNode: (n: Node) => (n as Text).data.includes(c.quote) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT,
          });
          const tn = walker.nextNode() as Text | null;
          if (!tn) { (orphans[sid] = orphans[sid] || []).push(c); return; }
          const idx = tn.data.indexOf(c.quote);
          if (idx < 0) { (orphans[sid] = orphans[sid] || []).push(c); return; }
          const range = document.createRange();
          range.setStart(tn, idx); range.setEnd(tn, idx + c.quote.length);
          const mark = document.createElement("mark");
          mark.className = `bp-tch-mark bp-tch-${c.annotation_type || "suggestion"}`;
          mark.setAttribute("data-comment-id", c.comment_id);
          const label = c.annotation_type === "issue" ? "问题" : c.annotation_type === "praise" ? "肯定" : "建议";
          mark.setAttribute("title", `教师${label}（${c.teacher_name || "老师"}）：${c.content}`);
          try { range.surroundContents(mark); } catch { (orphans[sid] = orphans[sid] || []).push(c); }
        });
        secEl.querySelectorAll(".bp-tch-orphans").forEach((el) => el.remove());
        const op = orphans[sid] || [];
        if (op.length) {
          const box = document.createElement("div");
          box.className = "bp-tch-orphans";
          box.innerHTML = `<b>教师建议（${op.length}）：</b>` + op.map((c: any) =>
            `<div>· ${c.annotation_type === "issue" ? "[问题]" : c.annotation_type === "praise" ? "[肯定]" : "[建议]"} ${escapeHtmlClient(c.content)}</div>`
          ).join("");
          const h = secEl.querySelector("h2, h3");
          if (h && h.parentElement === secEl) {
            secEl.insertBefore(box, h.nextSibling);
          } else {
            secEl.insertBefore(box, secEl.firstChild);
          }
        }
      });
    }, 80);
    return () => clearTimeout(timer);
  }, [bpTeacherComments, bpViewMode, businessPlan?.plan_id, businessPlan?.sections]);

  useEffect(() => {
    if (!activeBpSectionId) return;
    const outline = typeof document !== "undefined" ? document.querySelector<HTMLElement>(".bp-right-outline .bp-ro-list") : null;
    if (!outline) return;
    const items = outline.querySelectorAll<HTMLElement>(".bp-ro-item");
    const activeBtn = Array.from(items).find((btn) => btn.classList.contains("is-active"));
    if (!activeBtn) return;
    const listRect = outline.getBoundingClientRect();
    const btnRect = activeBtn.getBoundingClientRect();
    if (btnRect.top < listRect.top || btnRect.bottom > listRect.bottom) {
      activeBtn.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [activeBpSectionId]);

  const loadProjectSnapshot = useCallback(async () => {
    if (!projectId) return;
    try {
      const resp = await fetch(`${API_BASE}/api/project/${encodeURIComponent(projectId)}`);
      const data = await resp.json();
      const records = Array.isArray(data?.video_analyses) ? data.video_analyses : [];
      setVideoHistory(records);
      if (records.length > 0) {
        setSelectedVideoHistoryIdx(records.length - 1);
      } else {
        setSelectedVideoHistoryIdx(-1);
      }
    } catch {
      setVideoHistory([]);
      setSelectedVideoHistoryIdx(-1);
    }
  }, [projectId]);

  const loadBusinessPlan = useCallback(async () => {
    if (!projectId || !conversationId) return;
    setBpLoading(true);
    setBpError("");
    try {
      const resp = await fetch(
        `${API_BASE}/api/business-plan/latest?project_id=${encodeURIComponent(projectId)}&conversation_id=${encodeURIComponent(conversationId)}`,
      );
      const data = (await resp.json()) as BusinessPlanResponse;
      setBpReadiness(data.readiness ?? null);
      setBusinessPlan(data.plan ?? null);
      const firstSection = (data.plan?.sections ?? [])[0];
      if (firstSection) {
        setBpSelectedSectionId((prev) => prev || firstSection.section_id);
        setBpEditorContent(firstSection.user_edit || firstSection.content || "");
      } else {
        setBpSelectedSectionId("");
        setBpEditorContent("");
      }
    } catch (err: any) {
      setBpError(err?.message || "加载商业计划书失败");
    } finally {
      setBpLoading(false);
    }
  }, [projectId, conversationId]);

  useEffect(() => {
    if (projectId && conversationId) loadBusinessPlan();
  }, [projectId, conversationId, loadBusinessPlan]);

  async function generateBusinessPlan(allowLowConfidence = false) {
    if (!projectId || !conversationId) return;
    setBpLoading(true);
    setBpError("");
    try {
      const resp = await fetch(`${API_BASE}/api/business-plan/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          student_id: studentId,
          conversation_id: conversationId,
          allow_low_confidence: allowLowConfidence,
          mode: mode === "competition" ? "competition" : (mode === "coursework" ? "coursework" : "learning"),
        }),
      });
      const data = (await resp.json()) as BusinessPlanResponse;
      setBpReadiness(data.readiness ?? null);
      setBusinessPlan(data.plan ?? null);
      if (data.status === "needs_more_info" && !data.plan) {
        setBpError("当前信息还不够完整，建议先补充更多项目核心信息。");
      }
      const firstSection = (data.plan?.sections ?? [])[0];
      if (firstSection) {
        setBpSelectedSectionId(firstSection.section_id);
        setBpEditorContent(firstSection.user_edit || firstSection.content || "");
      }
    } catch (err: any) {
      setBpError(err?.message || "生成商业计划书失败");
    } finally {
      setBpLoading(false);
    }
  }

  async function refreshBusinessPlan() {
    if (!businessPlan?.plan_id) return;
    setBpLoading(true);
    setBpError("");
    try {
      const resp = await fetch(`${API_BASE}/api/business-plan/${encodeURIComponent(businessPlan.plan_id)}/refresh`, {
        method: "POST",
      });
      const data = (await resp.json()) as BusinessPlanResponse;
      setBpReadiness(data.readiness ?? null);
      setBusinessPlan(data.plan ?? null);
    } catch (err: any) {
      setBpError(err?.message || "刷新计划书失败");
    } finally {
      setBpLoading(false);
    }
  }

  async function saveBusinessPlanSection() {
    if (!businessPlan?.plan_id || !bpSelectedSectionId) return;
    setBpSaving(true);
    setBpError("");
    try {
      const section = (businessPlan.sections ?? []).find((item) => item.section_id === bpSelectedSectionId);
      const resp = await fetch(`${API_BASE}/api/business-plan/${encodeURIComponent(businessPlan.plan_id)}/sections/${encodeURIComponent(bpSelectedSectionId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: bpEditorContent,
          field_map: section?.field_map ?? {},
          display_title: section?.display_title ?? section?.title ?? "",
        }),
      });
      const data = (await resp.json()) as BusinessPlanResponse;
      setBpReadiness(data.readiness ?? null);
      setBusinessPlan(data.plan ?? null);
    } catch (err: any) {
      setBpError(err?.message || "保存章节失败");
    } finally {
      setBpSaving(false);
    }
  }

  async function handleBpRevision(planId: string, revisionId: string, action: "accept" | "reject") {
    setBpSaving(true);
    setBpError("");
    try {
      const resp = await fetch(`${API_BASE}/api/business-plan/${encodeURIComponent(planId)}/revisions/${encodeURIComponent(revisionId)}/${action}`, {
        method: "POST",
      });
      const data = (await resp.json()) as BusinessPlanResponse;
      setBpReadiness(data.readiness ?? null);
      setBusinessPlan(data.plan ?? null);
    } catch (err: any) {
      setBpError(err?.message || "处理修订失败");
    } finally {
      setBpSaving(false);
    }
  }

  async function upgradeBusinessPlan(mode: "basic" | "full") {
    if (!businessPlan?.plan_id) return;
    setBpUpgradeBusy(true);
    setBpError("");
    setBpUpgradeToast("");
    setBpMoreOpen(false);
    try {
      const resp = await fetch(`${API_BASE}/api/business-plan/${encodeURIComponent(businessPlan.plan_id)}/upgrade`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      if (!resp.ok) {
        const txt = await resp.text().catch(() => "");
        setBpError(`升级失败（HTTP ${resp.status}）：${txt.slice(0, 200) || "请检查后端日志"}`);
        return;
      }
      const data = (await resp.json()) as BusinessPlanResponse;
      setBpReadiness(data.readiness ?? null);
      setBusinessPlan(data.plan ?? null);
      const rep = data.plan?.upgrade_report;
      if (rep) {
        const succ = rep.success_ids?.length ?? 0;
        const fail = rep.failed_ids?.length ?? 0;
        const total = rep.requested?.length ?? 0;
        setBpUpgradeToast(
          fail > 0
            ? `升级完成：成功 ${succ}/${total} 章，${fail} 章未写完，可在「更多」里重试`
            : `升级完成：全部 ${succ}/${total} 章已生成修订，请审阅`
        );
      }
    } catch (err: any) {
      setBpError(err?.message || "升级失败");
    } finally {
      setBpUpgradeBusy(false);
    }
  }

  // ── 竞赛分支 fork ──────────────────────────────────────────
  const loadBpSiblings = useCallback(async (planId: string) => {
    if (!planId) return;
    try {
      const resp = await fetch(`${API_BASE}/api/business-plan/${encodeURIComponent(planId)}/siblings`);
      const data = await resp.json();
      if (Array.isArray(data?.plans)) setBpSiblings(data.plans);
    } catch {
      setBpSiblings([]);
    }
  }, []);

  const loadBpGrading = useCallback(async (planId: string) => {
    if (!planId) {
      setBpGrading(null);
      return;
    }
    try {
      const resp = await fetch(`${API_BASE}/api/business-plan/${encodeURIComponent(planId)}/grading`);
      const data = await resp.json();
      if (data?.status === "ok") setBpGrading(data.grading);
      else setBpGrading(null);
    } catch {
      setBpGrading(null);
    }
  }, []);

  const loadAgenda = useCallback(async (planId: string) => {
    if (!planId) return;
    try {
      const resp = await fetch(
        `${API_BASE}/api/business-plan/${encodeURIComponent(planId)}/agenda`
      );
      const data = await resp.json();
      if (Array.isArray(data?.items)) setBpAgendaItems(data.items);
      else setBpAgendaItems([]);
    } catch {
      setBpAgendaItems([]);
    }
  }, []);

  async function patchAgendaItem(
    planId: string,
    agendaId: string,
    patch: { status?: string; section_id_hint?: string }
  ) {
    try {
      await fetch(
        `${API_BASE}/api/business-plan/${encodeURIComponent(planId)}/agenda/${encodeURIComponent(agendaId)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(patch),
        }
      );
      await loadAgenda(planId);
    } catch {
      /* silent */
    }
  }

  async function applySelectedAgenda() {
    const plan = businessPlan;
    if (!plan?.plan_id) return;
    const ids = Array.from(bpAgendaSelected);
    if (!ids.length) return;
    setBpAgendaBusy(true);
    try {
      const resp = await fetch(
        `${API_BASE}/api/business-plan/${encodeURIComponent(plan.plan_id)}/agenda/apply`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ agenda_ids: ids, target_section_map: {} }),
        }
      );
      if (resp.ok) {
        const data = (await resp.json()) as BusinessPlanResponse;
        if (data.plan) {
          setBusinessPlan(data.plan);
          setBpReadiness(data.readiness ?? null);
          setBpAgendaSelected(new Set());
          setBpUpgradeToast(`已把 ${ids.length} 条竞赛教练议题合入候选章节，可在右侧逐条审阅。`);
          loadAgenda(plan.plan_id);
        }
      }
    } finally {
      setBpAgendaBusy(false);
    }
  }

  useEffect(() => {
    if (businessPlan?.plan_id) {
      loadBpSiblings(businessPlan.plan_id);
      loadBpGrading(businessPlan.plan_id);
      if (String((businessPlan as any).coaching_mode || "project") === "competition") {
        loadAgenda(businessPlan.plan_id);
      } else {
        setBpAgendaItems([]);
      }
    }
  }, [businessPlan?.plan_id, businessPlan?.updated_at, (businessPlan as any)?.coaching_mode, loadBpSiblings, loadBpGrading, loadAgenda]);

  // 顶栏模式 → 计划书 coaching_mode 自动同步：避免手动切换教练模式
  // competition 模式对应竞赛教练；其它（coursework/learning）统一回到项目教练
  useEffect(() => {
    if (!businessPlan?.plan_id) return;
    const expected: "project" | "competition" = mode === "competition" ? "competition" : "project";
    const current = String((businessPlan as any).coaching_mode || "project");
    if (current === expected) return;
    // 未解锁时不阻断切换，但后端会返回 locked，下面 setCoachingMode 已处理
    setCoachingMode(expected).catch(() => {});
    // 只依赖 mode / plan_id，避免切模式后 businessPlan 更新再次触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, businessPlan?.plan_id]);

  async function openSiblingPlan(siblingId: string) {
    if (!siblingId) return;
    setBpLoading(true);
    setBpError("");
    try {
      const resp = await fetch(`${API_BASE}/api/business-plan/${encodeURIComponent(siblingId)}`);
      const data = (await resp.json()) as BusinessPlanResponse;
      setBpReadiness(data.readiness ?? null);
      setBusinessPlan(data.plan ?? null);
      const firstSection = (data.plan?.sections ?? [])[0];
      if (firstSection) {
        setBpSelectedSectionId(firstSection.section_id);
        setBpEditorContent(firstSection.user_edit || firstSection.content || "");
      }
    } catch (err: any) {
      setBpError(err?.message || "切换分支失败");
    } finally {
      setBpLoading(false);
    }
  }

  async function setCoachingMode(nextMode: "project" | "competition") {
    if (!businessPlan?.plan_id) return;
    setBpForkBusy(true);
    setBpError("");
    setBpUpgradeToast("");
    try {
      const resp = await fetch(
        `${API_BASE}/api/business-plan/${encodeURIComponent(businessPlan.plan_id)}/coaching-mode`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: nextMode }),
        }
      );
      if (!resp.ok) {
        const txt = await resp.text().catch(() => "");
        setBpError(`切换教练模式失败（HTTP ${resp.status}）：${txt.slice(0, 200)}`);
        return;
      }
      const data = (await resp.json()) as BusinessPlanResponse;
      if (data.status === "locked") {
        setBpError("当前成熟度未达基础就绪，尚不能切换到竞赛教练。先补齐骨架与基础字段。");
        return;
      }
      if (data.plan) {
        setBusinessPlan(data.plan);
        setBpReadiness(data.readiness ?? null);
        setBpUpgradeToast(
          nextMode === "competition"
            ? "已切换到竞赛教练模式：对话侧会以评委视角追问，产出议题板供你批量应用。"
            : "已切换回项目教练模式：按章节完整度继续推进。"
        );
        if (nextMode === "competition") {
          // 首次进入竞赛模式，预取一次议题板
          loadAgenda(String(data.plan.plan_id)).catch(() => {});
        }
      }
    } catch (err: any) {
      setBpError(err?.message || "切换教练模式失败");
    } finally {
      setBpForkBusy(false);
    }
  }

  // 兼容入口：旧版 fork（UI 入口已移除，仅供外部脚本/兼容代码调用）
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  async function forkForCompetition() {
    if (!businessPlan?.plan_id) return;
    setBpForkBusy(true);
    setBpError("");
    setBpUpgradeToast("");
    setBpMoreOpen(false);
    try {
      const resp = await fetch(
        `${API_BASE}/api/business-plan/${encodeURIComponent(businessPlan.plan_id)}/fork-competition`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            competition_type: "",
            refresh_kb_reference: true,
          }),
        }
      );
      if (!resp.ok) {
        const txt = await resp.text().catch(() => "");
        setBpError(`竞赛优化失败（HTTP ${resp.status}）：${txt.slice(0, 200)}`);
        return;
      }
      const data = (await resp.json()) as BusinessPlanResponse;
      if (data.status === "invalid") {
        setBpError("当前计划书已是竞赛分支，无法再次 fork。可直接在当前分支继续优化。");
        return;
      }
      if (data.plan) {
        setBusinessPlan(data.plan);
        setBpReadiness(data.readiness ?? null);
        const firstSection = (data.plan.sections ?? [])[0];
        if (firstSection) {
          setBpSelectedSectionId(firstSection.section_id);
          setBpEditorContent(firstSection.user_edit || firstSection.content || "");
        }
        setBpUpgradeToast("已生成竞赛优化分支：基于 KB 预学习做了逐章改写，你可审阅每章修订后接受/忽略。");
      }
    } catch (err: any) {
      setBpError(err?.message || "竞赛优化失败");
    } finally {
      setBpForkBusy(false);
    }
  }

  async function acceptAllRevisions() {
    if (!businessPlan?.plan_id) return;
    setBpAcceptAllBusy(true);
    setBpError("");
    setBpMoreOpen(false);
    try {
      const resp = await fetch(
        `${API_BASE}/api/business-plan/${encodeURIComponent(businessPlan.plan_id)}/revisions/accept-all`,
        { method: "POST" }
      );
      if (!resp.ok) {
        const txt = await resp.text().catch(() => "");
        setBpError(`接受修订失败（HTTP ${resp.status}）：${txt.slice(0, 200)}`);
        return;
      }
      const data = (await resp.json()) as BusinessPlanResponse;
      setBpReadiness(data.readiness ?? null);
      setBusinessPlan(data.plan ?? null);
    } catch (err: any) {
      setBpError(err?.message || "接受修订失败");
    } finally {
      setBpAcceptAllBusy(false);
    }
  }

  async function rejectAllRevisions() {
    if (!businessPlan?.plan_id) return;
    setBpAcceptAllBusy(true);
    setBpError("");
    setBpMoreOpen(false);
    try {
      const resp = await fetch(
        `${API_BASE}/api/business-plan/${encodeURIComponent(businessPlan.plan_id)}/revisions/reject-all`,
        { method: "POST" }
      );
      if (!resp.ok) return;
      const data = (await resp.json()) as BusinessPlanResponse;
      setBpReadiness(data.readiness ?? null);
      setBusinessPlan(data.plan ?? null);
    } catch (err: any) {
      setBpError(err?.message || "忽略修订失败");
    } finally {
      setBpAcceptAllBusy(false);
    }
  }

  async function loadDeepenSuggestions() {
    if (!businessPlan?.plan_id) return;
    setBpSuggestLoading(true);
    try {
      const resp = await fetch(`${API_BASE}/api/business-plan/${encodeURIComponent(businessPlan.plan_id)}/deepen-suggestions`);
      const data = await resp.json();
      setBpSuggestions(data?.suggestions ?? []);
    } catch {
      setBpSuggestions([]);
    } finally {
      setBpSuggestLoading(false);
    }
  }

  async function openDeepenDialog(sectionId: string) {
    if (!businessPlan?.plan_id || !sectionId) return;
    setBpDeepenSectionId(sectionId);
    setBpDeepenQuestions([]);
    setBpDeepenAnswers({});
    setBpDeepenLoading(true);
    try {
      const resp = await fetch(
        `${API_BASE}/api/business-plan/${encodeURIComponent(businessPlan.plan_id)}/chapter/${encodeURIComponent(sectionId)}/deepen-questions`,
        { method: "GET" },
      );
      const data = await resp.json();
      const raw = Array.isArray(data?.questions) ? data.questions : [];
      const normalized: BpDeepenQuestion[] = raw.map((q: any, i: number) => ({
        id: String(q?.id || `q${i + 1}`),
        text: String(q?.question || q?.text || ""),
        focus_point: String(q?.why || q?.focus_point || q?.hint || ""),
      })).filter((q: BpDeepenQuestion) => q.text);
      setBpDeepenQuestions(normalized);
    } catch {
      setBpDeepenQuestions([]);
    } finally {
      setBpDeepenLoading(false);
    }
  }

  function closeDeepenDialog() {
    setBpDeepenSectionId("");
    setBpDeepenQuestions([]);
    setBpDeepenAnswers({});
  }

  useEffect(() => {
    if (!bpMoreOpen) return;
    const onDown = (e: MouseEvent) => {
      const root = bpMoreRef.current;
      if (root && !root.contains(e.target as Node)) setBpMoreOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [bpMoreOpen]);

  useEffect(() => {
    if (rightTab !== "bp") return;
    const onKey = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey;
      if (!mod) return;
      const tag = (e.target as HTMLElement | null)?.tagName || "";
      if (tag === "INPUT" || tag === "TEXTAREA" || (e.target as HTMLElement | null)?.isContentEditable) {
        return;
      }
      if (e.key.toLowerCase() === "e" && !e.shiftKey) {
        e.preventDefault();
        setBpViewMode((m) => (m === "read" ? "edit" : "read"));
      } else if (e.key.toLowerCase() === "u" && !e.shiftKey && businessPlan?.plan_id) {
        e.preventDefault();
        upgradeBusinessPlan((businessPlan.version_tier === "draft" ? "basic" : "full"));
      } else if (e.key.toLowerCase() === "a" && e.shiftKey && businessPlan?.plan_id) {
        e.preventDefault();
        if ((businessPlan.pending_revisions ?? []).length > 0) acceptAllRevisions();
      } else if (e.key === "/" && !e.shiftKey) {
        e.preventDefault();
        setBpOutlineOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rightTab, businessPlan?.plan_id, businessPlan?.version_tier, businessPlan?.pending_revisions]);

  useEffect(() => {
    try {
      const pinned = localStorage.getItem("bp_outline_pinned") === "1";
      setBpOutlinePinned(pinned);
      if (pinned) setBpOutlineOpen(true);
    } catch { /* noop */ }
  }, []);

  useEffect(() => {
    try { localStorage.setItem("bp_outline_pinned", bpOutlinePinned ? "1" : "0"); } catch { /* noop */ }
    if (bpOutlinePinned) setBpOutlineOpen(true);
  }, [bpOutlinePinned]);

  async function submitDeepenAnswers() {
    if (!businessPlan?.plan_id || !bpDeepenSectionId) return;
    const answers = bpDeepenQuestions.map((q) => ({
      question_id: q.id,
      question: q.text,
      answer: (bpDeepenAnswers[q.id] || "").trim(),
    })).filter((a) => a.answer);
    if (!answers.length) return;
    setBpDeepenSubmitting(true);
    try {
      const resp = await fetch(
        `${API_BASE}/api/business-plan/${encodeURIComponent(businessPlan.plan_id)}/chapter/${encodeURIComponent(bpDeepenSectionId)}/deepen`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ answers }),
        },
      );
      const data = (await resp.json()) as BusinessPlanResponse;
      setBpReadiness(data.readiness ?? null);
      setBusinessPlan(data.plan ?? null);
      const sid = bpDeepenSectionId;
      closeDeepenDialog();
      setTimeout(() => {
        const target = bpSectionRefs.current[sid];
        if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 60);
    } catch (err: any) {
      setBpError(err?.message || "深化失败");
    } finally {
      setBpDeepenSubmitting(false);
    }
  }

  async function finalizeBusinessPlan() {
    if (!businessPlan?.plan_id || bpFinalizeBusy) return;
    setBpFinalizeBusy(true);
    setBpUpgradeToast("正在润色为正式稿（生成执行摘要与每章小结）…");
    try {
      const resp = await fetch(
        `${API_BASE}/api/business-plan/${encodeURIComponent(businessPlan.plan_id)}/finalize`,
        { method: "POST" },
      );
      const data = (await resp.json()) as BusinessPlanResponse;
      if (data?.plan) {
        setBusinessPlan(data.plan);
        setBpReadiness(data.readiness ?? null);
        setBpUpgradeToast("已完成润色：开篇执行摘要 + 每章本章小结已到位。");
        setTimeout(() => setBpUpgradeToast(""), 3600);
      } else {
        setBpUpgradeToast("润色失败，请稍后重试。");
        setTimeout(() => setBpUpgradeToast(""), 3600);
      }
    } catch (err: any) {
      setBpError(err?.message || "润色失败");
    } finally {
      setBpFinalizeBusy(false);
    }
  }

  async function createSnapshot() {
    if (!businessPlan?.plan_id || bpSnapshotBusy) return;
    const label = typeof window !== "undefined"
      ? (window.prompt("为当前版本取一个名字（可留空，建议 10 字以内）", "") || "").trim()
      : "";
    setBpSnapshotBusy(true);
    try {
      const resp = await fetch(
        `${API_BASE}/api/business-plan/${encodeURIComponent(businessPlan.plan_id)}/snapshots`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ label }),
        },
      );
      const data = await resp.json();
      if (data?.status === "ok") {
        setBpUpgradeToast(`已保存快照${data?.snapshot?.label ? `：${data.snapshot.label}` : ""}`);
        setTimeout(() => setBpUpgradeToast(""), 3200);
      } else {
        setBpUpgradeToast("保存快照失败");
        setTimeout(() => setBpUpgradeToast(""), 3000);
      }
    } catch (err: any) {
      setBpError(err?.message || "保存快照失败");
    } finally {
      setBpSnapshotBusy(false);
    }
  }

  async function openSnapshotHistory() {
    if (!businessPlan?.plan_id) return;
    setBpSnapshotOpen(true);
    setBpSnapshotLoading(true);
    try {
      const resp = await fetch(
        `${API_BASE}/api/business-plan/${encodeURIComponent(businessPlan.plan_id)}/snapshots`,
      );
      const data = await resp.json();
      setBpSnapshots(Array.isArray(data?.snapshots) ? data.snapshots : []);
    } catch {
      setBpSnapshots([]);
    } finally {
      setBpSnapshotLoading(false);
    }
  }

  async function rollbackToSnapshot(snapId: string) {
    if (!businessPlan?.plan_id) return;
    if (!window.confirm("确认回滚到该版本？系统会先自动保存当前内容的兜底快照。")) return;
    try {
      const resp = await fetch(
        `${API_BASE}/api/business-plan/${encodeURIComponent(businessPlan.plan_id)}/snapshots/${encodeURIComponent(snapId)}/rollback`,
        { method: "POST" },
      );
      const data = (await resp.json()) as BusinessPlanResponse;
      if (data?.plan) {
        setBusinessPlan(data.plan);
        setBpReadiness(data.readiness ?? null);
        setBpSnapshotOpen(false);
        setBpUpgradeToast("已回滚到所选版本。");
        setTimeout(() => setBpUpgradeToast(""), 3000);
      } else {
        setBpUpgradeToast("回滚失败，请稍后重试。");
        setTimeout(() => setBpUpgradeToast(""), 3000);
      }
    } catch (err: any) {
      setBpError(err?.message || "回滚失败");
    }
  }

  async function exportBusinessPlan(format: "docx" | "pdf") {
    if (!businessPlan?.plan_id) return;
    setBpMoreOpen(false);
    // pdf 走「浏览器打印」路线：打开打印预览页 + 自动触发打印，用户选择「另存为 PDF」
    if (format === "pdf") {
      const url = `/business-plan/${encodeURIComponent(businessPlan.plan_id)}/print?autoprint=1`;
      try {
        window.open(url, "_blank");
      } catch (err: any) {
        setBpError(err?.message || "打开打印预览失败");
      }
      return;
    }
    setBpExportBusy(true);
    setBpError("");
    try {
      const resp = await fetch(`${API_BASE}/api/business-plan/${encodeURIComponent(businessPlan.plan_id)}/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          export_mode: "clean_final",
          export_format: format,
          cover_info: businessPlan.cover_info || {},
        }),
      });
      if (!resp.ok) {
        const txt = await resp.text().catch(() => "");
        setBpError(`导出失败（HTTP ${resp.status}）：${txt.slice(0, 240) || "请检查后端日志"}`);
        return;
      }
      const data = await resp.json();
      if (data?.status === "error") {
        setBpError(data.message || "导出失败");
        return;
      }
      if (data?.status === "pdf_unavailable") {
        setBpError(data.message || "pdf 不可用，已回退为 docx");
      }
      if (data?.file_url) {
        window.open(`${API_BASE}${data.file_url}`, "_blank");
      } else if (data?.message) {
        setBpError(data.message);
      }
    } catch (err: any) {
      setBpError(err?.message || "导出失败");
    } finally {
      setBpExportBusy(false);
    }
  }

  useEffect(() => {
    loadProjectSnapshot();
  }, [loadProjectSnapshot]);

  const loadMyTeams = useCallback(async () => {
    if (!currentUser?.user_id) return;
    try {
      const r = await fetch(`${API_BASE}/api/teams?role=student&user_id=${encodeURIComponent(currentUser.user_id)}`);
      if (!r.ok) return;
      const d = await r.json();
      setMyTeams(d.teams ?? []);
    } catch { /* ignore */ }
  }, [currentUser?.user_id]);

  useEffect(() => { loadMyTeams(); }, [loadMyTeams]);

  async function handleJoinTeam() {
    if (!joinCode.trim() || !currentUser?.user_id) return;
    setTeamMsg("");
    try {
      const r = await fetch(`${API_BASE}/api/teams/join`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: currentUser.user_id, invite_code: joinCode.trim() }),
      });
      const d = await r.json();
      if (!r.ok) { setTeamMsg(d.detail || "加入失败"); return; }
      setTeamMsg("加入成功！");
      setJoinCode("");
      loadMyTeams();
    } catch { setTeamMsg("网络错误"); }
  }

  async function handleVideoAnalyze() {
    if (!videoFile) {
      setVideoError("请先选择要分析的路演视频文件。");
      return;
    }
    const maxMb = 1024;
    const sizeMb = videoFile.size / (1024 * 1024);
    if (sizeMb > maxMb + 0.1) {
      setVideoError(`视频文件过大（约 ${sizeMb.toFixed(1)}MB），请控制在 ${maxMb}MB 以内。`);
      return;
    }
    if (!projectId || !studentId) {
      setVideoError("项目信息缺失，请刷新页面后重试。");
      return;
    }

    setVideoLoading(true);
    setVideoError(null);
    try {
      const fd = new FormData();
      fd.append("project_id", projectId);
      fd.append("student_id", studentId || currentUser?.user_id || "");
      fd.append("class_id", classId);
      fd.append("cohort_id", cohortId);
      fd.append("mode", mode);
      fd.append("competition_type", competitionType);
      fd.append("conversation_id", conversationId || "");
      fd.append("file", videoFile);

      const resp = await fetch(`${API_BASE}/api/student/video-analysis`, { method: "POST", body: fd });
      const data: VideoAnalysisResponse | { detail?: any } = await resp.json().catch(() => ({} as any));
      if (!resp.ok) {
        const detail = (data as any)?.detail;
        setVideoError(typeof detail === "string" ? detail : "视频分析失败，请稍后重试。");
        return;
      }
      const analysis = (data as VideoAnalysisResponse).analysis;
      if (analysis) {
        setVideoAnalysis(analysis);
        const record: VideoAnalysisRecord = {
          project_id: (data as VideoAnalysisResponse).project_id,
          student_id: (data as VideoAnalysisResponse).student_id,
          class_id: classId || null,
          cohort_id: cohortId || null,
          mode,
          competition_type: competitionType,
          filename: (data as VideoAnalysisResponse).filename,
          created_at: (data as VideoAnalysisResponse).created_at,
          analysis,
        };
        setVideoHistory((prev) => {
          const next = [...prev, record];
          setSelectedVideoHistoryIdx(next.length - 1);
          return next;
        });
      } else {
        setVideoError("后端返回结果格式不完整，稍后再试。");
      }
    } catch {
      setVideoError("网络错误，视频分析请求未完成。");
    } finally {
      setVideoLoading(false);
    }
  }

  async function regeneratePosterImages() {
    if (!posterDesign || !projectId || !studentId) return;
    setPosterLoading(true);
    setPosterError("");
    try {
      const prompts = (posterDesign.image_prompts || []).filter(Boolean);
      const promptList = prompts.length > 0
        ? prompts.slice(0, 3)
        : [`${posterDesign.title || "项目海报"} | ${posterDesign.subtitle || "中文学生创新项目大赛展演海报插图"}`];
      const basePrompt = promptList[0];
      const suffixes = [" — 主视觉插图", " — 使用场景插图", " — 数据与成果插图"];
      while (promptList.length < 3 && basePrompt) {
        const idx = promptList.length;
        promptList.push(`${basePrompt}${suffixes[idx] || " — 补充插图"}`);
      }
      const orientation = posterDesign.layout?.orientation === "landscape" ? "landscape" : "portrait";
      const size = orientation === "landscape" ? "1280x720" : "1024x576";
      const urls: string[] = [];
      for (let i = 0; i < Math.min(promptList.length, 3); i += 1) {
        const imgResp = await fetch(`${API_BASE}/api/poster/generate-image`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: projectId,
            student_id: studentId,
            prompt: promptList[i],
            orientation,
            size,
          }),
        });
        if (!imgResp.ok) {
          const errJson = await imgResp.json().catch(() => ({}));
          throw new Error(errJson?.detail || "生成插图失败");
        }
        const imgData = await imgResp.json();
        const url: string = imgData.image_url.startsWith("http") ? imgData.image_url : `${API_BASE}${imgData.image_url}`;
        urls.push(url);
      }
      setPosterDesign((prev) => {
        if (!prev) return prev;
        const next: PosterDesign = { ...prev };
        if (urls.length > 0) next.hero_image_url = urls[0];
        next.gallery_image_urls = urls.slice(1);
        return next;
      });
    } catch (err: any) {
      setPosterError(err?.message || "重新生成插图失败");
    } finally {
      setPosterLoading(false);
    }
  }

  function handleKgWheel(e: any) {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.12 : 0.12;
    setKgViewport((v) => ({ ...v, scale: Math.max(0.7, Math.min(2.4, Number((v.scale + delta).toFixed(2)))) }));
  }

  function handleKgMouseDown(e: any) {
    kgPanRef.current = { active: true, startX: e.clientX, startY: e.clientY, x: kgViewport.x, y: kgViewport.y };
  }

  function handleKgMouseMove(e: any) {
    if (!kgPanRef.current.active) return;
    const dx = e.clientX - kgPanRef.current.startX;
    const dy = e.clientY - kgPanRef.current.startY;
    setKgViewport((v) => ({ ...v, x: kgPanRef.current.x + dx, y: kgPanRef.current.y + dy }));
  }

  function handleKgMouseUp() {
    kgPanRef.current.active = false;
  }

  const autoLoaded = useRef(false);
  useEffect(() => {
    if (!autoLoaded.current && conversations.length > 0 && !conversationId) {
      autoLoaded.current = true;
      loadConversation(conversations[0].conversation_id);
    }
  }, [conversations]);

  // right panel drag resize
  useEffect(() => {
    function onMove(e: MouseEvent) {
      if (!dragRef.current.active) return;
      const delta = dragRef.current.startX - e.clientX;
      setRightWidth(Math.max(280, Math.min(700, dragRef.current.startW + delta)));
    }
    function onUp() { dragRef.current.active = false; document.body.style.cursor = ""; document.body.style.userSelect = ""; }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, []);

  function startDrag(e: React.MouseEvent) {
    dragRef.current = { active: true, startX: e.clientX, startW: rightWidth };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }

  // sidebar drag resize
  useEffect(() => {
    function onMove(e: MouseEvent) {
      if (!sidebarDragRef.current) return;
      setSidebarWidth(Math.max(160, Math.min(420, e.clientX)));
    }
    function onUp() { sidebarDragRef.current = false; document.body.style.cursor = ""; document.body.style.userSelect = ""; }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, []);

  function startSidebarDrag(e: React.MouseEvent) {
    sidebarDragRef.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }

  function autoResize() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }

  async function newChat() {
    setMessages([]);
    setLatestResult(null);
    setConversationId(null);
    setAttachedFile(null);
    setResultHistory([]);
    setDocReview(null);
    setDocReviewOpen(false);
    setPdfViewerOpen(false);
  }

  async function deleteConversation(cid: string) {
    try {
      const r = await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(cid)}?project_id=${encodeURIComponent(projectId)}`, {
        method: "DELETE",
      });
      if (!r.ok) return;
      if (conversationId === cid) {
        setConversationId(null);
        setMessages([]);
        setLatestResult(null);
        setResultHistory([]);
        setDocReview(null);
      }
      loadConversations();
    } catch {
      /* ignore */
    }
  }

  async function loadConversation(cid: string) {
    try {
      const r = await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(cid)}?project_id=${encodeURIComponent(projectId)}`);
      const d = await r.json();
      const rawMsgsAll = d.messages ?? [];
      // silent 消息（如计划书深化沉淀 kind=deepen_addon）不在聊天流渲染，
      // 但保留在对话 JSON 中供后续 agent 读取
      const rawMsgs = rawMsgsAll.filter((m: any) => !m?.silent && m?.kind !== "deepen_addon");
      const msgs: ChatMessage[] = rawMsgs.map((m: any) => ({
        role: m.role as "user" | "assistant",
        text: m.content ?? "",
        ts: m.timestamp ? formatBjTime(m.timestamp) : undefined,
        id: ++_msgId,
        advisory: m?.agent_trace?.finance_advisory?.triggered ? m.agent_trace.finance_advisory : undefined,
      }));
      setMessages(msgs);

      // Rebuild FULL resultHistory from ALL assistant messages (persistence!)
      const history: any[] = [];
      let lastDoc: { filename: string; sections: any[]; annotations: any[]; fileUrl?: string } | null = null;

      for (const m of rawMsgs) {
        if (m.role !== "assistant" || !m.agent_trace) continue;
        const t = m.agent_trace;
        history.push({
          diagnosis: t.diagnosis ?? t.orchestration ?? {},
          next_task: t.next_task ?? {},
          kg_analysis: t.kg_analysis ?? {},
          hypergraph_insight: t.hypergraph_insight ?? {},
          hypergraph_student: t.hypergraph_student ?? {},
          rag_cases: t.rag_cases ?? [],
          agent_trace: t,
        });
        // Restore document review from stored conversation
        if (t.doc_sections?.length) {
          const fUrl = t.file_url ? `${API_BASE}${t.file_url}` : "";
          lastDoc = {
            filename: t.filename ?? "document",
            sections: t.doc_sections,
            annotations: t.doc_annotations ?? [],
            fileUrl: fUrl,
          };
        }
      }

      setResultHistory(history);
      if (history.length > 0) {
        setLatestResult(history[history.length - 1]);
      } else {
        setLatestResult(null);
      }
      if (lastDoc) {
        setDocReview(lastDoc);
        // If we have sections but no annotations (old conversation), fetch them async
        if (lastDoc.sections.length > 0 && lastDoc.annotations.length === 0) {
          setDocReviewLoading(true);
          fetch(`${API_BASE}/api/document-review`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sections: lastDoc.sections, mode }),
          })
            .then((r) => r.json())
            .then((d) => {
              const anns = d.annotations ?? [];
              setDocReview((prev) => prev ? { ...prev, annotations: anns } : prev);
            })
            .catch(() => {})
            .finally(() => setDocReviewLoading(false));
        }
      } else {
        setDocReview(null);
      }
      setConversationId(cid);
    } catch { /* ignore */ }
  }

  function abortResponse() {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setLoading(false);
    setMessages((p) => {
      const last = p[p.length - 1];
      if (last && last.role === "assistant" && !last.text) {
        return [...p.slice(0, -1), { ...last, text: "（已中断回答）" }];
      }
      if (last && last.role === "user") {
        return [...p, { role: "assistant" as const, text: "（已中断回答）", ts: formatBjTime(new Date()), id: ++_msgId }];
      }
      return p;
    });
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if ((!text && !attachedFile) || loading) return;
    setLoading(true);

    const controller = new AbortController();
    abortRef.current = controller;

    const displayText = attachedFile ? `${text ? text + " " : ""}📎 ${attachedFile.name}` : text;
    const userMsg: ChatMessage = { role: "user", text: displayText, ts: formatBjTime(new Date()), id: ++_msgId };
    setMessages((p) => [...p, userMsg]);
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";

    try {
      let data: any;

      if (attachedFile) {
        const form = new FormData();
        form.set("project_id", projectId);
        form.set("student_id", studentId);
        form.set("student_number", studentNumber);
        form.set("message", text);
        form.set("conversation_id", conversationId ?? "");
        form.set("mode", mode);
        form.set("competition_type", competitionType || "");
        form.set("file", attachedFile);
        const resp = await fetch(`${API_BASE}/api/dialogue/turn-upload`, { method: "POST", body: form, signal: controller.signal });
        data = await resp.json();
        if (!resp.ok) throw new Error(data?.detail ?? resp.statusText);

        if (data.doc_sections?.length > 0) {
          const fUrl = data.file_url ? `${API_BASE}${data.file_url}` : "";
          const annotations = data.doc_annotations ?? [];
          setDocReview({ filename: attachedFile.name, sections: data.doc_sections, annotations, fileUrl: fUrl });
          const isPdf = attachedFile.name.toLowerCase().endsWith(".pdf");
          if (isPdf && fUrl) { setPdfViewerUrl(fUrl); setPdfViewerOpen(true); } else { setDocReviewOpen(true); }
          // If backend didn't generate annotations, fetch them async
          if (annotations.length === 0) {
            setDocReviewLoading(true);
            fetch(`${API_BASE}/api/document-review`, {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ sections: data.doc_sections, mode, context: text }),
            }).then((r) => r.json())
              .then((d) => setDocReview((prev) => prev ? { ...prev, annotations: d.annotations ?? [] } : prev))
              .catch(() => {}).finally(() => setDocReviewLoading(false));
          }
        }
        setAttachedFile(null);
      } else {
        const resp = await fetch(`${API_BASE}/api/dialogue/turn`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: projectId, student_id: studentId,
            student_number: studentNumber || undefined,
            conversation_id: conversationId || undefined,
            class_id: classId || undefined, cohort_id: cohortId || undefined,
            message: text, mode,
            competition_type: competitionType || "",
          }),
          signal: controller.signal,
        });
        data = await resp.json();
        if (!resp.ok) throw new Error(data?.detail ?? resp.statusText);
      }

      setLatestResult(data);
      setResultHistory((prev) => [...prev, data]);
      if (data.conversation_id && !conversationId) setConversationId(data.conversation_id);
      const reply = (data?.assistant_message ?? "").trim() || "（智能体未返回有效回复）";

      // Typewriter effect: reveal the reply character by character
      const typeMsgId = ++_msgId;
      setMessages((p) => [...p, { role: "assistant", text: "", ts: formatBjTime(new Date()), id: typeMsgId }]);

      const CHUNK = 3;
      for (let i = 0; i < reply.length; i += CHUNK) {
        if (!abortRef.current) break;
        const slice = reply.slice(0, i + CHUNK);
        setMessages((p) => p.map((m) => m.id === typeMsgId ? { ...m, text: slice } : m));
        await new Promise((r) => setTimeout(r, 12));
      }
      const advisory = data?.agent_trace?.finance_advisory?.triggered ? data.agent_trace.finance_advisory : undefined;
      setMessages((p) => p.map((m) => m.id === typeMsgId ? { ...m, text: reply, advisory } : m));

      loadConversations();
    } catch (err: any) {
      if (err?.name === "AbortError") return;
      setMessages((p) => [...p, { role: "assistant", text: `错误：${err?.message ?? "无法连接后端"}`, id: ++_msgId }]);
    }
    abortRef.current = null;
    setLoading(false);
  }

  async function retrySend(msgId: number) {
    const idx = messages.findIndex((m) => m.id === msgId);
    if (idx < 0 || messages[idx].role !== "user") return;
    const text = messages[idx].text;
    setInput(text.replace(/📎\s.*$/, "").trim());
    setMessages((p) => p.slice(0, idx));
    setTimeout(() => textareaRef.current?.focus(), 50);
  }

  function copyText(text: string, msgId: number) {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedId(msgId);
      setTimeout(() => setCopiedId(null), 1500);
    });
  }

  function toggleLike(msgId: number) {
    setLikedMsgs((s) => { const n = new Set(s); if (n.has(msgId)) n.delete(msgId); else n.add(msgId); return n; });
    setDislikedMsgs((s) => { const n = new Set(s); n.delete(msgId); return n; });
  }
  function toggleDislike(msgId: number) {
    setDislikedMsgs((s) => { const n = new Set(s); if (n.has(msgId)) n.delete(msgId); else n.add(msgId); return n; });
    setLikedMsgs((s) => { const n = new Set(s); n.delete(msgId); return n; });
  }

  async function loadFeedback() {
    try {
      const [feedbackResp, annotationResp] = await Promise.all([
        fetch(`${API_BASE}/api/project/${encodeURIComponent(projectId)}/feedback`),
        fetch(`${API_BASE}/api/student/project/${encodeURIComponent(projectId)}/annotation-boards`),
      ]);
      const feedbackData = await feedbackResp.json();
      const annotationData = await annotationResp.json();
      setTeacherFeedback(feedbackData.feedback ?? annotationData.project_feedback ?? []);
      const boards = annotationData.boards ?? [];
      setTeacherAnnotationBoards(boards);
      setSelectedAnnotationBoardId((prev) => prev && boards.some((item: any) => item.submission_id === prev) ? prev : (boards[0]?.submission_id ?? ""));
    } catch { /* ignore */ }
  }

  async function loadInterventions() {
    try {
      const resp = await fetch(`${API_BASE}/api/student/interventions?project_id=${encodeURIComponent(projectId)}`);
      const data = await resp.json();
      setTeacherInterventions(data.interventions ?? []);
    } catch { /* ignore */ }
  }

  async function markInterventionViewed(interventionId: string) {
    try {
      await fetch(`${API_BASE}/api/student/interventions/${encodeURIComponent(interventionId)}/view`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId, student_id: studentId }),
      });
      loadInterventions();
    } catch { /* ignore */ }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(e as any);
    }
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) setAttachedFile(f);
    e.target.value = "";
  }

  const filteredConvs = useMemo(() => {
    if (!searchQuery.trim()) return conversations;
    const q = searchQuery.toLowerCase();
    return conversations.filter((c) => c.title.toLowerCase().includes(q) || c.last_message.toLowerCase().includes(q));
  }, [conversations, searchQuery]);

  const [resultHistory, setResultHistory] = useState<any[]>([]);

  async function generatePosterFromCurrentProject() {
    if (!projectId || !studentId) return;
    if (!latestResult) {
      alert("请先在左侧对话中用一两段话描述你的项目，或上传一份计划书，再生成海报。");
      return;
    }
    setPosterLoading(true);
    setPosterError("");
    try {
      const resp = await fetch(`${API_BASE}/api/poster/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          student_id: studentId,
          conversation_id: conversationId || "",
          mode,
          competition_type: competitionType || "",
          use_latest_context: true,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data?.detail || "生成海报失败，请稍后重试");
      }
      if (!data?.poster) {
        throw new Error("后端未返回有效的 PosterDesign 结构");
      }
      let poster = data.poster as PosterDesign;

      // 一键生成图文海报：在成功拿到文案后，立刻串行调用插图接口
      try {
        const prompts = poster.image_prompts || [];
        const promptList: string[] = [];
        if (prompts[0]) promptList.push(prompts[0]);
        if (prompts[1]) promptList.push(prompts[1]);
        if (prompts[2]) promptList.push(prompts[2]);

        if (promptList.length === 0) {
          const title = (poster.title || "").slice(0, 40);
          const subtitle = (poster.subtitle || "").slice(0, 60);
          promptList.push(`${title} | ${subtitle || "中文学生创新项目大赛展演海报插图"}`);
        }

        // 确保有 3 个 prompt，用于生成上中下三张不同插图
        const basePrompt = promptList[0];
        const suffixes = [" — 主视觉插图", " — 使用场景插图", " — 数据与成果插图"];
        while (promptList.length < 3 && basePrompt) {
          const idx = promptList.length;
          promptList.push(`${basePrompt}${suffixes[idx] || " — 补充插图"}`);
        }

        const orientation = poster.layout?.orientation === "landscape" ? "landscape" : "portrait";
        const size = orientation === "landscape" ? "1280x720" : "1024x576";

        const urls: string[] = [];
        for (let i = 0; i < Math.min(promptList.length, 3); i += 1) {
          const prompt = promptList[i];
          const imgResp = await fetch(`${API_BASE}/api/poster/generate-image`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              project_id: projectId,
              student_id: studentId,
              prompt,
              orientation,
              size,
            }),
          });

          if (!imgResp.ok) {
            let msg = "生成插图失败";
            try {
              const errJson = await imgResp.json();
              msg = errJson?.detail || msg;
            } catch { /* ignore */ }
            throw new Error(msg);
          }

          const imgData = await imgResp.json();
          if (!imgData?.image_url) {
            throw new Error("后端未返回 image_url");
          }
          const url: string = imgData.image_url.startsWith("http") ? imgData.image_url : `${API_BASE}${imgData.image_url}`;
          urls.push(url);
        }

        if (urls.length > 0) {
          const next: any = { ...poster };
          next.hero_image_url = urls[0];
          if (urls.length > 1) next.gallery_image_urls = urls.slice(1);
          poster = next as PosterDesign;
        }
      } catch (imgErr: any) {
        // 插图生成失败不阻塞文案海报，只在错误区提示
        setPosterError((prev) => prev || imgErr?.message || "生成插图失败");
      }

      setPosterDesign(poster);
      setPosterPanelOpen(true);
    } catch (err: any) {
      setPosterError(err?.message || "生成海报失败");
    } finally {
      setPosterLoading(false);
    }
  }

  const rubric = useMemo(() => {
    if (resultHistory.length === 0) return latestResult?.diagnosis?.rubric ?? [];
    // 合并时保留最近一次的完整字段（base_score / signal_bonus / length_bonus / rule_penalty /
    // dim_rules / matched_evidence / missing_evidence / rationale 等），用于"分数怎么算出来的"展示。
    const merged: Record<string, { item: string; scores: number[]; weight: number; reason?: string; source?: string; latestRow?: any }> = {};
    for (const r of resultHistory) {
      for (const row of r?.diagnosis?.rubric ?? []) {
        if (!merged[row.item]) merged[row.item] = { item: row.item, scores: [], weight: row.weight ?? 0 };
        merged[row.item].scores.push(row.score);
        merged[row.item].reason = row.reason ?? merged[row.item].reason;
        merged[row.item].source = row.source ?? merged[row.item].source;
        merged[row.item].weight = row.weight ?? merged[row.item].weight;
        merged[row.item].latestRow = row; // 每次循环覆盖，最终持有"最后一次提交"的整行
      }
    }
    // ── 跨轮累积展示：最近 3 轮 0.5 / 0.3 / 0.2 加权平均 ──
    const SMOOTH_W = [0.5, 0.3, 0.2] as const;
    return Object.values(merged).map((m) => {
      const s = m.scores;
      const latest = s[s.length - 1];
      const best = Math.max(...s);
      const prev = s.length > 1 ? s[s.length - 2] : null;
      const last3 = s.slice(-3);
      const ws = SMOOTH_W.slice(0, last3.length);
      const wsum = ws.reduce((a, b) => a + b, 0) || 1;
      // last3 是旧→新，权重 0.2 / 0.3 / 0.5（新的权重大）
      const smoothed = last3.reduce((acc, v, i) => {
        const w = SMOOTH_W[last3.length - 1 - i] ?? 0;
        return acc + v * (w / wsum);
      }, 0);
      // rawHistory：新→旧（RationaleCard.smoothing 约定）
      const rawHistory = last3.slice().reverse().map((v) => Math.round(v * 100) / 100);
      const latestRow: any = m.latestRow || {};
      return {
        item: m.item,
        score: Math.round(smoothed * 100) / 100,
        rawLatest: Math.round(latest * 100) / 100,
        bestScore: Math.round(best * 100) / 100,
        prevScore: prev !== null ? Math.round(prev * 100) / 100 : null,
        trend: prev !== null ? (latest > prev ? "up" : latest < prev ? "down" : "same") : null,
        smoothedFromTurns: last3.length,
        rawHistory,
        smoothWeights: SMOOTH_W.slice(0, last3.length),
        weight: m.weight,
        reason: m.reason,
        source: m.source,
        // ── 保留推导字段，供评分 tab 的"分数构成 / 命中规则 / 证据关键词 / 详细推导"使用 ──
        base_score: latestRow.base_score,
        signal_bonus: latestRow.signal_bonus,
        length_bonus: latestRow.length_bonus,
        rule_penalty: latestRow.rule_penalty,
        dim_rules: latestRow.dim_rules,
        matched_evidence: latestRow.matched_evidence,
        missing_evidence: latestRow.missing_evidence,
        rationale: latestRow.rationale,
        status: latestRow.status,
      };
    });
  }, [resultHistory, latestResult]);

  const currentVideoRecord = useMemo(
    () => (selectedVideoHistoryIdx >= 0 ? videoHistory[selectedVideoHistoryIdx] ?? null : null),
    [selectedVideoHistoryIdx, videoHistory],
  );

  const currentVideoAnalysis = useMemo(
    () => currentVideoRecord?.analysis ?? videoAnalysis ?? null,
    [currentVideoRecord, videoAnalysis],
  );

  const videoRiskItems = useMemo(
    () => (currentVideoAnalysis?.rubric ?? []).filter((item) => item.status === "risk"),
    [currentVideoAnalysis],
  );

  const videoSummaryCards = useMemo(() => {
    const analysis = currentVideoAnalysis;
    if (!analysis) return [];
    const lastRecord = currentVideoRecord;
    const transcriptLength = analysis.transcript ? analysis.transcript.length : 0;
    return [
      { label: "总分", value: analysis.overall_score != null ? `${analysis.overall_score.toFixed(1)}/10` : "--", hint: analysis.score_band || "本次评分" },
      { label: "风险项", value: `${videoRiskItems.length}`, hint: videoRiskItems.length > 0 ? "优先修正的表达问题" : "当前未识别明显风险" },
      { label: "逐字稿", value: transcriptLength > 0 ? `${Math.min(analysis.transcript.length, 2000)}字+` : "--", hint: "可用于复盘表达逻辑" },
      { label: "分析时间", value: lastRecord?.created_at ? formatBjTime(lastRecord.created_at, true) : "--", hint: lastRecord?.filename || "本次上传文件" },
    ];
  }, [currentVideoAnalysis, currentVideoRecord, videoRiskItems.length]);

  const videoHistoryTrend = useMemo(() => {
    if (videoHistory.length < 2) return null;
    const scores = videoHistory.map((item) => item.analysis?.overall_score).filter((s): s is number => typeof s === "number");
    if (scores.length < 2) return null;
    const prev = scores[scores.length - 2];
    const current = scores[scores.length - 1];
    return {
      prev,
      current,
      delta: Number((current - prev).toFixed(2)),
      improved: current > prev,
    };
  }, [videoHistory]);

  const videoVsTextInsight = useMemo(() => {
    const textScore = latestResult?.diagnosis?.overall_score;
    const videoScore = currentVideoAnalysis?.overall_score;
    const textRules = latestResult?.diagnosis?.triggered_rules ?? [];
    if (videoScore == null && textScore == null) return null;
    const riskHeavy = videoRiskItems.length >= 2;
    if (typeof textScore === "number" && typeof videoScore === "number") {
      if (textScore >= 7 && videoScore < 6) {
        return "项目内容成熟度高，但视频表达与路演呈现偏弱，建议优先训练讲述结构和重点突出。";
      }
      if (textScore < 6 && videoScore >= 7) {
        return "表达状态优于项目文本本身，说明你有讲述优势，但项目证据与逻辑仍需补强。";
      }
      if (riskHeavy && textRules.length > 0) {
        return "文本诊断与视频分析都提示存在薄弱项，建议把书面材料整改和路演表达训练同步推进。";
      }
    }
    return "建议把本次视频表现和当前文本诊断一起看，确认问题是出在内容、证据，还是表达方式。";
  }, [currentVideoAnalysis, latestResult, videoRiskItems.length]);

  const triggeredRules = useMemo(() => {
    const allSeen: Record<string, { rule: any; firstTurn: number; lastTurn: number; turnCount: number }> = {};
    resultHistory.forEach((r, idx) => {
      for (const rule of r?.diagnosis?.triggered_rules ?? []) {
        if (!allSeen[rule.id]) {
          allSeen[rule.id] = { rule: { ...rule }, firstTurn: idx + 1, lastTurn: idx + 1, turnCount: 1 };
        } else {
          allSeen[rule.id].lastTurn = idx + 1;
          allSeen[rule.id].turnCount += 1;
          allSeen[rule.id].rule = { ...rule };
        }
      }
    });
    const latestRules = latestResult?.diagnosis?.triggered_rules ?? [];
    const latestIds = new Set(latestRules.map((r: any) => r.id));
    for (const rule of latestRules) {
      if (!allSeen[rule.id]) {
        allSeen[rule.id] = { rule: { ...rule }, firstTurn: resultHistory.length + 1, lastTurn: resultHistory.length + 1, turnCount: 1 };
      } else {
        allSeen[rule.id].lastTurn = resultHistory.length + 1;
        allSeen[rule.id].turnCount += 1;
        allSeen[rule.id].rule = { ...rule };
      }
    }
    // Only mark resolved when the latest turn actually ran a full diagnosis
    // (has triggered_rules array with content). If the latest turn was chat/simple
    // question with no diagnosis, preserve previous risk status.
    const latestDiagRan = Array.isArray(latestResult?.diagnosis?.triggered_rules)
      && latestResult.diagnosis.triggered_rules.length > 0;
    const entries = Object.entries(allSeen).map(([id, data]) => ({
      ...data.rule,
      id,
      firstTurn: data.firstTurn,
      lastTurn: data.lastTurn,
      turnCount: data.turnCount,
      resolved: latestDiagRan && resultHistory.length > 0 && !latestIds.has(id),
    }));
    if (entries.length === 0) return latestRules;
    return entries.sort((a: any, b: any) => {
      if (a.resolved !== b.resolved) return a.resolved ? 1 : -1;
      const sev = { high: 3, medium: 2, low: 1 } as Record<string, number>;
      return (sev[b.severity] ?? 0) - (sev[a.severity] ?? 0);
    });
  }, [resultHistory, latestResult]);

  // taskHistory removed — task tab now uses planner output directly

  const nextTask = latestResult?.next_task ?? null;
  const hyperInsight = useMemo(() => {
    const pick = (r: any) => r?.hypergraph_insight ?? r?.agent_trace?.hypergraph_insight ?? null;
    const all = [...resultHistory.map(pick), pick(latestResult)].filter((h) => (h?.edges?.length ?? 0) > 0 || h?.summary);
    return all.length > 0 ? all[all.length - 1] : (pick(latestResult) ?? null);
  }, [resultHistory, latestResult]);
  const hyperEdges = useMemo(() => hyperInsight?.edges ?? [], [hyperInsight]);
  const hyperMatchedEdges = useMemo(() => {
    const pvEdges = hyperProjectView?.matched_edges ?? [];
    if (Array.isArray(pvEdges) && pvEdges.length > hyperEdges.length) return pvEdges;
    return hyperEdges;
  }, [hyperProjectView, hyperEdges]);

  // Cumulative KG & HyperStudent: merge across turns so data is never lost
  const kgAnalysis = useMemo(() => {
    const pick = (r: any) => r?.kg_analysis ?? r?.agent_trace?.kg_analysis ?? null;
    const all = [...resultHistory.map(pick), pick(latestResult)].filter(Boolean);
    if (all.length === 0) return null;
    // Deduplicate entities by (type, normalized_label) — LLM generates sequential ids
    // like e1/e2 each turn, so raw id collisions would lose entities across turns
    const entMap = new Map<string, any>();
    const norm = (s: string) => (s || "").trim().toLowerCase().replace(/\s+/g, "");
    let idCounter = 0;
    const relSet = new Set<string>();
    const rels: any[] = [];
    const gapSet = new Set<string>();
    const strengthSet = new Set<string>();
    let insight = "", scores: any = {}, completeness = 0;
    for (const kg of all) {
      for (const e of kg.entities ?? []) {
        const key = `${norm(e.type)}_${norm(e.label)}`;
        if (!entMap.has(key)) {
          idCounter++;
          entMap.set(key, { ...e, _stableId: `s${idCounter}`, _origId: e.id, _turnKey: key });
        }
      }
      for (const g of kg.structural_gaps ?? []) gapSet.add(g);
      for (const s of kg.content_strengths ?? []) strengthSet.add(s);
      if (kg.insight) insight = kg.insight;
      if (kg.section_scores) scores = { ...scores, ...kg.section_scores };
      if (kg.completeness_score != null) completeness = kg.completeness_score;
    }
    // Build stable id lookup: origId per turn → stableId
    const entities = Array.from(entMap.values()).map((e) => ({ ...e, id: e._stableId }));
    const origToStable = new Map<string, Map<string, string>>();
    let turnIdx = 0;
    for (const kg of all) {
      turnIdx++;
      const tMap = new Map<string, string>();
      for (const e of kg.entities ?? []) {
        const key = `${norm(e.type)}_${norm(e.label)}`;
        const stable = entMap.get(key);
        if (stable) tMap.set(e.id, stable._stableId);
      }
      origToStable.set(`t${turnIdx}`, tMap);
      for (const r of kg.relationships ?? []) {
        const src = tMap.get(r.source) ?? r.source;
        const tgt = tMap.get(r.target) ?? r.target;
        const k = `${src}-${r.relation}-${tgt}`;
        if (!relSet.has(k)) { relSet.add(k); rels.push({ ...r, source: src, target: tgt }); }
      }
    }
    const lastKg = all[all.length - 1];
    const kgQuality = lastKg?.kg_quality ?? null;
    return { entities, relationships: rels, structural_gaps: Array.from(gapSet), content_strengths: Array.from(strengthSet), insight, section_scores: scores, completeness_score: completeness, kg_quality: kgQuality as any };
  }, [resultHistory, latestResult]);

  const hyperStudent = useMemo(() => {
    const pick = (r: any) => r?.hypergraph_student ?? r?.agent_trace?.hypergraph_student ?? null;
    const all = [...resultHistory.map(pick), pick(latestResult)].filter((h) => h?.ok);
    return all.length > 0 ? all[all.length - 1] : null;
  }, [resultHistory, latestResult]);

  const hyperConsistencyIssues = useMemo(() => {
    const pick = (r: any) => r?.hyper_consistency_issues ?? r?.agent_trace?.hyper_consistency_issues ?? [];
    const all = [...resultHistory.map(pick), pick(latestResult)].filter((a) => Array.isArray(a) && a.length > 0);
    return all.length > 0 ? all[all.length - 1] : (hyperStudent?.consistency_issues ?? []);
  }, [resultHistory, latestResult, hyperStudent]);

  const hyperTemplateMatches = useMemo(() => hyperStudent?.template_matches ?? [], [hyperStudent]);
  const hyperTemplateComplete = useMemo(() => hyperTemplateMatches.filter((t: any) => t.status === "complete").length, [hyperTemplateMatches]);

  const hyperGraphData = useMemo(() => {
    if (!hyperStudent?.ok) return null;
    const dims = hyperStudent.dimensions ?? {};
    const nodes: any[] = [];
    const links: any[] = [];
    const DIM_COLORS: Record<string, string> = {
      stakeholder: "#4fc3f7", pain_point: "#ef5350", solution: "#66bb6a", innovation: "#ab47bc",
      market: "#ffa726", competitor: "#78909c", business_model: "#ffca28", execution_step: "#26a69a",
      risk_control: "#ec407a", evidence: "#42a5f5", technology: "#7e57c2", resource: "#8d6e63",
      team: "#5c6bc0", risk: "#ec407a", channel: "#9ccc65",
    };
    Object.entries(dims).forEach(([dim, v]: [string, any]) => {
      nodes.push({ id: `dim_${dim}`, label: v.name, type: "dimension", covered: v.covered, count: v.count, dim });
      (v.entities ?? []).slice(0, 4).forEach((ent: string, i: number) => {
        const eid = `ent_${dim}_${i}`;
        nodes.push({ id: eid, label: ent, type: "entity", dim });
        links.push({ source: `dim_${dim}`, target: eid });
      });
    });
    (hyperStudent.cross_links ?? []).forEach((cl: any, ci: number) => {
      const srcDim = Object.entries(dims).find(([, v]: [string, any]) => v.name === cl.from_dim)?.[0];
      const tgtDim = Object.entries(dims).find(([, v]: [string, any]) => v.name === cl.to_dim)?.[0];
      if (srcDim && tgtDim) links.push({ source: `dim_${srcDim}`, target: `dim_${tgtDim}`, cross: true });
    });
    return { nodes, links, DIM_COLORS };
  }, [hyperStudent]);

  const ragCases = useMemo(() => {
    const latest = latestResult?.rag_cases ?? latestResult?.agent_trace?.rag_cases ?? [];
    const seen = new Set<string>();
    return latest
      .filter((c: any) => {
        const k = c?.project_name ?? c?.case_id ?? JSON.stringify(c);
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      })
      .slice(0, 5);
  }, [latestResult]);
  const webSearch = latestResult?.agent_trace?.web_search ?? latestResult?.web_search ?? null;
  const orchestration = latestResult?.agent_trace?.orchestration ?? {};
  const pressureTrace = latestResult?.agent_trace?.pressure_test_trace ?? latestResult?.pressure_test_trace ?? null;
  const agentsCalled = orchestration?.agents_called ?? [];
  const roleAgents = useMemo(() => {
    const merged = new Map<string, any>();
    const all = [...resultHistory, latestResult].filter(Boolean);
    for (const item of all) {
      const roles = item?.agent_trace?.role_agents ?? {};
      for (const [key, rawVal] of Object.entries(roles)) {
        const val: any = rawVal;
        if (!val || typeof val !== "object") continue;
        const prev = merged.get(key) ?? {};
        merged.set(key, {
          ...prev,
          ...val,
          turn_count: Number(prev.turn_count ?? 0) + 1,
          tools_used: Array.from(new Set([...(prev.tools_used ?? []), ...(val.tools_used ?? [])])),
          analysis: val.analysis ?? prev.analysis ?? "",
        });
      }
    }
    return Object.fromEntries(merged.entries());
  }, [resultHistory, latestResult]);

  useEffect(() => {
    if (hyperLibrary && rightTab !== "hyper") return;
    let cancelled = false;
    fetch(`${API_BASE}/api/hypergraph/library?limit=24&t=${Date.now()}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((data) => { if (!cancelled) setHyperLibrary(data?.data ?? null); })
      .catch(() => { if (!cancelled) setHyperLibrary(null); });
    fetch(`${API_BASE}/api/hypergraph/catalog?t=${Date.now()}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((data) => { if (!cancelled && data && !data.error) setHgCatalog(data); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [rightTab, resultHistory.length, latestResult]);

  useEffect(() => {
    if (!hyperInsight && !hyperStudent) return;
    let cancelled = false;
    fetch(`${API_BASE}/api/hypergraph/project-view`, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        hypergraph_insight: hyperInsight ?? {},
        hypergraph_student: hyperStudent ?? {},
        pressure_test_trace: pressureTrace ?? {},
      }),
    })
      .then((r) => r.json())
      .then((data) => { if (!cancelled) setHyperProjectView(data?.data ?? null); })
      .catch(() => { if (!cancelled) setHyperProjectView(null); });
    return () => { cancelled = true; };
  }, [hyperInsight, hyperStudent, pressureTrace, resultHistory.length, latestResult]);

  // Cumulative planner tasks — kept across turns
  const cumulativePlannerTasks = useMemo(() => {
    const pick = (r: any) => r?.agent_trace?.role_agents?.planner?.plan_data?.this_week;
    const all = [...resultHistory.map(pick), pick(latestResult)].filter(Array.isArray);
    return all.length > 0 ? all[all.length - 1] : [];
  }, [resultHistory, latestResult]);

  const plannerTaskHistory = useMemo(() => {
    const history: Array<{task: any; turn: number; isCurrent: boolean}> = [];
    resultHistory.forEach((r, idx) => {
      const tasks = r?.agent_trace?.role_agents?.planner?.plan_data?.this_week;
      if (Array.isArray(tasks)) {
        tasks.forEach((t: any) => history.push({ task: t, turn: idx + 1, isCurrent: false }));
      }
    });
    const currentTasks = latestResult?.agent_trace?.role_agents?.planner?.plan_data?.this_week;
    if (Array.isArray(currentTasks)) {
      currentTasks.forEach((t: any) => history.push({ task: t, turn: resultHistory.length + 1, isCurrent: true }));
    }
    return history;
  }, [resultHistory, latestResult]);

  const plannerNotNow = useMemo(() => {
    const pick = (r: any) => r?.agent_trace?.role_agents?.planner?.plan_data?.not_now;
    const all = [...resultHistory.map(pick), pick(latestResult)].filter(Array.isArray);
    return all.length > 0 ? all[all.length - 1] : [];
  }, [resultHistory, latestResult]);

  const cumulativeMilestone = useMemo(() => {
    const pick = (r: any) => r?.agent_trace?.role_agents?.planner?.plan_data?.milestone;
    const all = [...resultHistory.map(pick), pick(latestResult)].filter(Boolean);
    return all.length > 0 ? all[all.length - 1] : "";
  }, [resultHistory, latestResult]);
  const overallScore = useMemo(() => {
    const scores = resultHistory
      .map((r) => r?.diagnosis?.overall_score)
      .filter((s): s is number => typeof s === "number" && !Number.isNaN(s));
    if (scores.length === 0) {
      const latest = latestResult?.diagnosis?.overall_score;
      return typeof latest === "number" ? latest : null;
    }
    // 跨轮累积平滑：最近 3 轮 0.5 / 0.3 / 0.2 加权平均
    const SMOOTH_W = [0.5, 0.3, 0.2];
    const last3 = scores.slice(-3);
    const ws = SMOOTH_W.slice(0, last3.length);
    const wsum = ws.reduce((a, b) => a + b, 0) || 1;
    const smoothed = last3.reduce((acc, v, i) => {
      const w = SMOOTH_W[last3.length - 1 - i] ?? 0;
      return acc + v * (w / wsum);
    }, 0);
    return Math.round(smoothed * 100) / 100;
  }, [resultHistory, latestResult]);

  // 综合分平滑 meta：给证据对照用（新→旧）
  const overallSmoothing = useMemo(() => {
    const scores = resultHistory
      .map((r) => r?.diagnosis?.overall_score)
      .filter((s): s is number => typeof s === "number" && !Number.isNaN(s));
    if (scores.length < 2 || overallScore === null) return null;
    const last3 = scores.slice(-3);
    const rawHistory = last3.slice().reverse().map((v) => Math.round(v * 100) / 100);
    const W = [0.5, 0.3, 0.2].slice(0, last3.length);
    return {
      displayValue: overallScore,
      turns: last3.length,
      weights: W,
      rawHistory,
    };
  }, [resultHistory, overallScore]);
  const scoreBand = latestResult?.diagnosis?.score_band ?? "";
  const projectStage = latestResult?.diagnosis?.project_stage ?? "";
  const gradingPrinciples: string[] = latestResult?.diagnosis?.grading_principles ?? [];
  const projectStageLabel = ({
    idea: "想法探索期",
    structured: "基本成形期",
    validated: "已验证推进期",
    document: "计划书完善期",
  } as Record<string, string>)[projectStage] ?? projectStage;
  const modeGuide = useMemo(() => ({
    coursework: "学怎么把项目想清楚，适合拆方法、补概念、看案例。",
    competition: "按评委视角提分，适合路演、答辩、证据链和 rubric 优化。",
    learning: "盯当前瓶颈和推进顺序，适合收敛下一步最关键动作。",
  } as Record<string, string>)[mode] ?? "", [mode]);
  const inputPlaceholder = useMemo(() => ({
    coursework: "把你的项目想法、课程作业困惑或一个概念问题发给我，我会结合项目讲方法…",
    competition: "把项目材料、答辩担忧或你想冲高分的部分发给我，我按评委视角帮你拆…",
    learning: "告诉我你项目现在卡在哪，我会优先帮你判断真正瓶颈和下一步…",
  } as Record<string, string>)[mode] ?? "描述你的项目想法、困惑或问题…", [mode]);

  useEffect(() => {
    if (currentUser) {
      setProjectId(`project-${currentUser.user_id}`);
      setStudentId(currentUser.student_id || currentUser.user_id || "");
      setClassId(currentUser.class_id || "");
      setCohortId(currentUser.cohort_id || "");
      try { const saved = sessionStorage.getItem("va_student_number"); if (saved) setStudentNumber(saved); } catch {}
    }
  }, [currentUser]);

  useEffect(() => {
    if (studentNumber) try { sessionStorage.setItem("va_student_number", studentNumber); } catch {}
  }, [studentNumber]);

  if (!currentUser) return <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", color: "var(--text-muted)" }}>加载中...</div>;

  return (
    <div className={`chat-app ${theme}`}>
      {/* ── Top Bar (Redesigned V2) ── */}
      <header className="chat-topbar">
        <div className="topbar-left">
          <button type="button" className="topbar-icon-btn sidebar-toggle" onClick={() => setConvSidebarOpen((v) => !v)} title="会话列表">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 12h18M3 6h18M3 18h18"/></svg>
          </button>
          <Link href="/" className="topbar-brand">
            <span className="brand-dot" />
            VentureCheck
          </Link>
        </div>

        <div className="topbar-center">
          <div className="topbar-mode-toggle">
            <button type="button" className={`topbar-mode-opt${mode === "coursework" ? " active" : ""}`} onClick={() => setMode("coursework")}>课程辅导</button>
            <button type="button" className={`topbar-mode-opt${mode === "competition" ? " active" : ""}`} onClick={() => setMode("competition")}>竞赛冲刺</button>
            <button type="button" className={`topbar-mode-opt${mode === "learning" ? " active" : ""}`} onClick={() => setMode("learning")}>项目教练</button>
          </div>
          {conversationId && (
            (() => {
              const lid = currentLogicalProjectId;
              const isStd = !!lid && /^P-[A-Za-z0-9_-]+-\d{2,}$/.test(lid);
              return (
                <button
                  type="button"
                  className={`topbar-pid-pill${isStd ? " standard" : lid ? " legacy" : " empty"}`}
                  onClick={copyProjectId}
                  disabled={!lid}
                  title={lid ? (isStd ? "规范项目编号 · 点击复制" : "历史会话编号 · 点击复制") : "尚未分配项目编号（填入学号后新会话会自动生成）"}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M10 13a5 5 0 007.07 0l3-3a5 5 0 00-7.07-7.07l-1.7 1.7"/>
                    <path d="M14 11a5 5 0 00-7.07 0l-3 3a5 5 0 007.07 7.07l1.7-1.7"/>
                  </svg>
                  <span className="topbar-pid-label">项目编号</span>
                  <code className="topbar-pid-value">
                    {isStd ? lid : lid ? `#${lid.slice(0, 8)}` : "—"}
                  </code>
                  {pidCopied && <span className="topbar-pid-copied">已复制</span>}
                </button>
              );
            })()
          )}
          {overallScore !== null && <span className="topbar-score">{overallScore}<small>/10</small></span>}
          {pitchTimerRunning && (
            <div className={`pitch-timer-display ${pitchTimer <= 30 ? "urgent" : pitchTimer <= 60 ? "warning" : ""}`}>
              <svg className="pitch-timer-ring" viewBox="0 0 36 36">
                <circle cx="18" cy="18" r="15.5" fill="none" stroke="var(--border)" strokeWidth="2" />
                <circle cx="18" cy="18" r="15.5" fill="none" strokeWidth="2.5" strokeLinecap="round"
                  stroke={pitchTimer <= 30 ? "#e07070" : pitchTimer <= 60 ? "#e0a84c" : "#5cbd8a"}
                  strokeDasharray={`${(pitchTimer / pitchDuration) * 97.4} 97.4`}
                  transform="rotate(-90 18 18)" />
              </svg>
              <span className="pitch-timer-text">{formatTime(pitchTimer)}</span>
              <button type="button" className="pitch-stop-btn-inline" onClick={stopPitchTimer} title="结束路演">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
              </button>
            </div>
          )}
        </div>

        <div className="topbar-right" style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <button type="button" className="topbar-btn" onClick={() => setRightOpen((v) => !v)}>
            {rightOpen ? "收起" : "分析面板"}
          </button>

          <div className="topbar-dock">
            {/* 视频路演分析 */}
            <button type="button" className={`dock-item${videoPanelOpen ? " active" : ""}`} onClick={() => { setVideoPanelOpen(v => !v); setPosterPanelOpen(false); }}>
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="4" width="13" height="14" rx="2" />
                <polygon points="17 8 21 6 21 18 17 16 17 8" />
              </svg>
              <span className="dock-tooltip">路演视频分析</span>
            </button>

            {/* 项目海报 */}
            <button type="button" className={`dock-item${posterPanelOpen ? " active" : ""}`} onClick={() => { setPosterPanelOpen(v => !v); setVideoPanelOpen(false); }} disabled={posterLoading}>
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="4" y="3" width="16" height="14" rx="2" />
                <path d="M8 8h8" />
                <path d="M8 12h5" />
                <path d="M10 21l2-4 2 4" />
              </svg>
              <span className="dock-tooltip">{posterLoading ? "生成海报中…" : "项目海报"}</span>
            </button>

            <div className="dock-sep" />
            {/* Chat */}
            <Link href="/chat" className="dock-item">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
              <span className="dock-tooltip">聊天室 — 与团队和小文实时沟通</span>
            </Link>

            {/* Budget */}
            <button type="button" className={`dock-item${budgetPanelOpen ? " active" : ""}`} onClick={() => setBudgetPanelOpen(v => !v)}>
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 1v22M17 5H9.5a3.5 3.5 0 100 7h5a3.5 3.5 0 110 7H6"/></svg>
              <span className="dock-tooltip">财政预算 — 项目成本与商业计划</span>
            </button>

            {/* Competition type */}
            <div style={{ position: "relative" }}>
              <button type="button" className={`dock-item${dockCompOpen ? " active" : ""}`} onClick={() => setDockCompOpen((v) => !v)}>
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9H4.5a2.5 2.5 0 010-5C7 4 7 7 7 7"/><path d="M18 9h1.5a2.5 2.5 0 000-5C17 4 17 7 17 7"/><path d="M4 22h16"/><path d="M10 22V2h4v20"/><rect x="8" y="9" width="8" height="4" rx="1"/></svg>
                <span className="dock-tooltip">赛事类型{competitionType ? ` — ${({internet_plus:"互联网+",challenge_cup:"挑战杯",dachuang:"大创"} as any)[competitionType] || ""}` : ""}</span>
              </button>
              {dockCompOpen && (
                <div className="dock-popup" onClick={(e) => e.stopPropagation()}>
                  <div className="dock-popup-label">赛事类型</div>
                  <div className="comp-card-group" style={{ padding: "4px 0" }}>
                    {([
                      { value: "", label: "不限" },
                      { value: "internet_plus", label: "互联网+" },
                      { value: "challenge_cup", label: "挑战杯" },
                      { value: "dachuang", label: "大创" },
                    ] as { value: string; label: string }[]).map((opt) => (
                      <button
                        key={opt.value}
                        type="button"
                        className={`comp-card${competitionType === opt.value ? " active" : ""}`}
                        onClick={() => { setCompetitionType(opt.value as any); setDockCompOpen(false); }}
                      >
                        <span className="comp-card-label">{opt.label}</span>
                      </button>
                    ))}
                  </div>
                  {mode === "competition" && !pitchTimerRunning && (
                    <>
                      <div className="dock-popup-label" style={{ marginTop: 8 }}>路演计时</div>
                      <div className="pitch-launcher">
                        <select className="pitch-dur-select" value={pitchDuration} onChange={(e) => setPitchDuration(Number(e.target.value))}>
                          <option value={180}>3 min</option><option value={300}>5 min</option><option value={420}>7 min</option><option value={600}>10 min</option>
                        </select>
                        <button type="button" className="pitch-start-btn" onClick={() => { startPitchTimer(); setDockCompOpen(false); }}>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                          开始
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>

            {/* Knowledge Graph */}
            <button type="button" className={`dock-item${kbPanelOpen ? " active" : ""}`} onClick={() => setKbPanelOpen(v => !v)}>
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="5" r="2.5"/><circle cx="5" cy="19" r="2.5"/><circle cx="19" cy="19" r="2.5"/><path d="M12 7.5v3.5M9 14l-2.5 3M15 14l2.5 3"/><circle cx="12" cy="12" r="1.5"/></svg>
              <span className="dock-tooltip">知识图谱</span>
            </button>

            {/* Team */}
            <button type="button" className="dock-item" onClick={() => { setTeamPanelOpen((v) => !v); if (!teamPanelOpen) loadMyTeams(); }}>
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>
              <span className="dock-tooltip">我的团队{myTeams.length > 0 ? ` (${myTeams.length})` : ""}</span>
            </button>

            <div className="dock-sep" />

            {/* Theme toggle */}
            <button type="button" className="dock-item" onClick={() => setTheme((t) => t === "dark" ? "light" : "dark")}>
              {theme === "dark" ? (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>
              )}
              <span className="dock-tooltip">{theme === "dark" ? "日间模式" : "夜间模式"}</span>
            </button>

            {/* Logout */}
            <button type="button" className="dock-item dock-item-danger" onClick={() => setShowLogoutConfirm(true)}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
              <span className="dock-tooltip">退出登录</span>
            </button>
          </div>

          <Link href="/student/profile" className="topbar-avatar" title="个人中心">
            {(currentUser.display_name ?? "S")[0].toUpperCase()}
          </Link>
        </div>
      </header>

      {/* ── 学号软性提示 banner（未填学号时显示） ── */}
      {currentUser?.role === "student" && !currentUser?.student_id && !sidBannerDismissed && (
        <div className="stu-sid-banner">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
          <span className="stu-sid-banner-text">
            还没填写学号。填入后，新开的会话会自动获得规范项目编号 <code>P-学号-NN</code>，便于老师按编号批改。
          </span>
          <Link href="/student/profile" className="stu-sid-banner-btn">去个人中心填写</Link>
          <button type="button" className="stu-sid-banner-close" onClick={() => setSidBannerDismissed(true)} title="暂不提醒">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>
      )}

      {/* ── Team Panel ── */}
      {teamPanelOpen && (
        <div className="stu-team-panel">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
            <h3 style={{ margin: 0, fontSize: 15 }}>我的团队</h3>
            <button type="button" className="topbar-icon-btn" onClick={() => setTeamPanelOpen(false)} style={{ fontSize: 18 }}>✕</button>
          </div>

          <div className="stu-team-join">
            <input className="stu-team-input" placeholder="输入邀请码加入团队" value={joinCode} onChange={(e) => setJoinCode(e.target.value.toUpperCase())} onKeyDown={(e) => e.key === "Enter" && handleJoinTeam()} maxLength={10} />
            <button className="stu-team-join-btn" onClick={handleJoinTeam} disabled={!joinCode.trim()}>加入</button>
          </div>
          {teamMsg && <p style={{ fontSize: 12, color: teamMsg.includes("成功") ? "#5cbd8a" : "#e07070", margin: "6px 0 0" }}>{teamMsg}</p>}

          {myTeams.length === 0 ? (
            <p style={{ color: "var(--text-muted)", fontSize: 13, textAlign: "center", padding: "20px 0" }}>还未加入任何团队，请向教师索取邀请码</p>
          ) : (
            <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 8 }}>
              {myTeams.map((t: any) => (
                <div key={t.team_id} className="stu-team-card">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <strong style={{ fontSize: 14, color: "var(--text-primary)" }}>{t.team_name}</strong>
                    <span style={{ fontSize: 11, color: "var(--text-muted)", background: "var(--bg-card-hover)", padding: "2px 8px", borderRadius: 99 }}>{t.teacher_name}</span>
                  </div>
                  <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 6 }}>
                    {t.member_count ?? t.members?.length ?? 0} 位成员
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Settings Drawer ── */}
      {/* ── Logout Confirm Modal ── */}
      {showLogoutConfirm && (
        <div className="logout-confirm-overlay" onClick={() => setShowLogoutConfirm(false)}>
          <div className="logout-confirm-box" onClick={(e) => e.stopPropagation()}>
            <div className="logout-confirm-icon">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
            </div>
            <h4 style={{ margin: "0 0 6px", fontSize: 15, color: "var(--text-primary)" }}>确认退出登录？</h4>
            <p style={{ margin: "0 0 18px", fontSize: 13, color: "var(--text-muted)" }}>退出后需要重新输入账号密码登录</p>
            <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
              <button type="button" className="logout-confirm-cancel" onClick={() => setShowLogoutConfirm(false)}>取消</button>
              <button type="button" className="logout-confirm-ok" onClick={() => { setShowLogoutConfirm(false); logout(); }}>确认退出</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Budget Panel (slides in below TopBar) ── */}
      {budgetPanelOpen && currentUser && (
        <div className="budget-panel-overlay">
          <div className="budget-panel-container">
            <BudgetPanel userId={currentUser.user_id} onClose={() => setBudgetPanelOpen(false)} />
          </div>
        </div>
      )}

      {/* ── Video Analysis Panel (slides in below TopBar) ── */}
      {videoPanelOpen && (
        <div className="studio-panel-overlay">
          <div className="studio-panel-shell">
            <div className="studio-panel-header">
              <div className="studio-panel-title-row">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2"><rect x="3" y="4" width="13" height="14" rx="2" /><polygon points="17 8 21 6 21 18 17 16 17 8" /></svg>
                <h3 className="studio-panel-title">路演视频分析</h3>
                <span className="studio-panel-badge">Beta</span>
              </div>
              <p className="studio-panel-desc">上传路演视频（mp4/mov/webm, ≤3min），系统将转写语音并按 Rubric 评分。</p>
              <button type="button" className="studio-panel-close" onClick={() => setVideoPanelOpen(false)}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12" /></svg>
              </button>
            </div>
            <div className="studio-panel-body">
              <div className="studio-upload-zone">
                <div className="studio-upload-icon">
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="1.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12" /></svg>
                </div>
                <input type="file" accept="video/mp4,video/webm,video/quicktime,video/x-m4v,video/x-msvideo" className="studio-file-input"
                  onChange={(e) => { const f = e.target.files?.[0] ?? null; setVideoFile(f); setVideoError(null); if (f) setVideoAnalysis(null); }}
                />
                {videoFile ? <span className="studio-upload-name">{videoFile.name}</span> : <span className="studio-upload-hint">点击或拖拽上传视频文件</span>}
                <span className="studio-upload-sub">建议：环境安静、口齿清晰，先用路演计时练习</span>
              </div>
              <button type="button" className="studio-action-btn" onClick={handleVideoAnalyze} disabled={videoLoading || !videoFile}>
                {videoLoading ? <><span className="studio-spinner" /> 正在分析视频…</> : <><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="5 3 19 12 5 21 5 3" /></svg> 开始分析</>}
              </button>
              {videoError && <div className="studio-error">{videoError}</div>}

              {currentVideoAnalysis ? (() => {
                const total = currentVideoAnalysis.overall_score ?? 0;
                const totalColor = total >= 7 ? "var(--accent-green,#22c55e)" : total >= 4 ? "var(--accent-yellow,#f59e0b)" : "var(--accent-red,#ef4444)";
                const circumf = 2 * Math.PI * 42;
                const offset = circumf * (1 - total / 10);
                const rubric = currentVideoAnalysis.rubric ?? [];
                return (
                  <div className="studio-result">
                    <div className="studio-score-hero">
                      <svg width="96" height="96" viewBox="0 0 104 104">
                        <circle cx="52" cy="52" r="42" fill="none" stroke="var(--border)" strokeWidth="6" />
                        <circle cx="52" cy="52" r="42" fill="none" stroke={totalColor} strokeWidth="6"
                          strokeDasharray={circumf} strokeDashoffset={offset}
                          strokeLinecap="round" transform="rotate(-90 52 52)" style={{ transition: "stroke-dashoffset .6s ease" }} />
                        <text x="52" y="48" textAnchor="middle" fontSize="22" fontWeight="800" fill={totalColor}>{total.toFixed(1)}</text>
                        <text x="52" y="64" textAnchor="middle" fontSize="10" fill="var(--text-muted)">/10</text>
                      </svg>
                      <div className="studio-score-meta">
                        {currentVideoAnalysis.score_band && <span className="studio-chip">{currentVideoAnalysis.score_band}</span>}
                        <span className="studio-chip muted">Rubric 评分</span>
                        {videoHistoryTrend && (
                          <span className={`studio-chip ${videoHistoryTrend.improved ? "good" : "warn"}`}>
                            {videoHistoryTrend.improved ? "较上次提升" : "较上次回落"} {Math.abs(videoHistoryTrend.delta).toFixed(1)}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="studio-summary-grid">
                      {videoSummaryCards.map((card) => (
                        <div key={card.label} className="studio-summary-card">
                          <span>{card.label}</span>
                          <strong>{card.value}</strong>
                          <p>{card.hint}</p>
                        </div>
                      ))}
                    </div>
                    {videoHistory.length > 0 && (
                      <div className="studio-history-strip">
                        <div className="studio-section-caption">历史记录</div>
                        <div className="studio-history-list">
                          {videoHistory.map((record, idx) => (
                            <button
                              key={`${record.created_at}-${idx}`}
                              type="button"
                              className={`studio-history-item${idx === selectedVideoHistoryIdx ? " active" : ""}`}
                              onClick={() => {
                                setSelectedVideoHistoryIdx(idx);
                                setVideoAnalysis(record.analysis);
                              }}
                            >
                              <strong>{record.analysis?.overall_score != null ? record.analysis.overall_score.toFixed(1) : "--"}</strong>
                              <span>{formatBjTime(record.created_at, true)}</span>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    {videoRiskItems.length > 0 && (
                      <div className="studio-risk-board">
                        <div className="studio-section-caption">优先风险项</div>
                        <div className="studio-risk-list">
                          {videoRiskItems.map((item) => (
                            <div key={item.item} className="studio-risk-item">
                              <div className="studio-risk-top">
                                <strong>{item.item}</strong>
                                <span>{item.score.toFixed(1)}</span>
                              </div>
                              <p>{item.reason || "建议优先复盘这一项的路演表达。"}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {videoVsTextInsight && (
                      <div className="studio-link-card">
                        <div className="studio-section-caption">与文本诊断联动</div>
                        <p>{videoVsTextInsight}</p>
                      </div>
                    )}
                    {currentVideoAnalysis.summary && (
                      <div className="studio-link-card">
                        <div className="studio-section-caption">分析摘要</div>
                        <p>{currentVideoAnalysis.summary}</p>
                      </div>
                    )}
                    <div className="studio-dim-grid">
                      {rubric.map((r: any) => {
                        const pct = Math.min(100, (r.score / 10) * 100);
                        const clr = pct >= 70 ? "var(--accent-green,#22c55e)" : pct >= 40 ? "var(--accent-yellow,#f59e0b)" : "var(--accent-red,#ef4444)";
                        return (
                          <details key={r.item} className="studio-dim-card">
                            <summary className="studio-dim-head">
                              <span className="studio-dim-name">{r.item}</span>
                              <div className="studio-dim-bar-wrap">
                                <div className="studio-dim-bar"><div className="studio-dim-fill" style={{ width: `${pct}%`, background: clr }} /></div>
                                <span className="studio-dim-score" style={{ color: clr }}>{r.score.toFixed(1)}</span>
                              </div>
                            </summary>
                            {r.reason && <div className="studio-dim-reason">{r.reason}</div>}
                          </details>
                        );
                      })}
                    </div>
                    {currentVideoAnalysis.presentation_feedback && (() => {
                      const raw = currentVideoAnalysis.presentation_feedback || "";
                      const cleaned = raw.replace(/\*\*/g, "").trim();
                      const blocks = cleaned.split(/\n{2,}/).map((b: string) => b.trim()).filter(Boolean);
                      return (
                        <details className="studio-section" open>
                          <summary className="studio-section-title">路演表现点评</summary>
                          <div className="studio-section-body">
                            {blocks.map((p: string, idx: number) => (
                              <p key={idx} className="studio-feedback-block">{p}</p>
                            ))}
                          </div>
                        </details>
                      );
                    })()}
                    {currentVideoAnalysis.transcript && (
                      <details className="studio-section">
                        <summary className="studio-section-title">语音转写逐字稿</summary>
                        <div className="studio-section-body">
                          <p className="studio-transcript">{currentVideoAnalysis.transcript.slice(0, 2000)}{currentVideoAnalysis.transcript.length > 2000 ? " …" : ""}</p>
                        </div>
                      </details>
                    )}
                  </div>
                );
              })() : !videoLoading && (
                <div className="studio-empty">
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="1.2"><rect x="3" y="4" width="13" height="14" rx="2" /><polygon points="17 8 21 6 21 18 17 16 17 8" /></svg>
                  <span>上传路演视频后，这里会显示分析结果</span>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Poster Panel (slides in below TopBar) ── */}
      {posterPanelOpen && (
        <div className="studio-panel-overlay">
          <div className="studio-panel-shell">
            <div className="studio-panel-header">
              <div className="studio-panel-title-row">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="3" width="16" height="14" rx="2" /><path d="M8 8h8" /><path d="M8 12h5" /><path d="M10 21l2-4 2 4" /></svg>
                <h3 className="studio-panel-title">项目海报工作台</h3>
              </div>
              <p className="studio-panel-desc">先生成一版海报草稿，再挑选风格、调整版式和润色文案，让最终展示更像一张真正能用的作品。</p>
              <button type="button" className="studio-panel-close" onClick={() => setPosterPanelOpen(false)}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12" /></svg>
              </button>
            </div>
            <div className="studio-panel-body">
              <div className="studio-poster-hero">
                <div>
                  <div className="studio-section-caption">推荐流程</div>
                  <p className="studio-poster-hero-text">先生成海报草稿，再选择你想要的风格和版式，最后用编辑模式把标题、卖点和行动信息调顺。</p>
                </div>
                <span className="studio-chip muted">单页海报 · 可持续微调</span>
              </div>

              <div className="studio-poster-controls-card">
                <div className="studio-poster-controls-head">
                  <div>
                    <strong>先生成内容草稿</strong>
                    <p>系统会基于当前项目内容整理出一版适合展示的标题、结构和插图建议。</p>
                  </div>
                </div>
                <div className="studio-inline-actions">
                  <button type="button" className="studio-action-btn" onClick={generatePosterFromCurrentProject} disabled={posterLoading}>
                    {posterLoading ? <><span className="studio-spinner" /> 正在整理海报草稿…</> : <><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="3" width="16" height="14" rx="2" /><path d="M8 8h8" /><path d="M8 12h5" /></svg> 生成一版海报草稿</>}
                  </button>
                  {posterDesign && (
                    <>
                      <button type="button" className="studio-sub-btn" onClick={() => setPosterEditMode((v) => !v)}>
                        {posterEditMode ? "返回预览" : "进入编辑模式"}
                      </button>
                      <button type="button" className="studio-sub-btn" onClick={regeneratePosterImages} disabled={posterLoading}>
                        换一组插图
                      </button>
                    </>
                  )}
                </div>
              </div>
              {latestResult && !posterDesign && !posterLoading && (
                <div className="studio-hint-box">已检测到当前项目的诊断内容，直接生成即可；如果后面觉得气质不对，还可以继续改风格和文案。</div>
              )}
              {posterError && <div className="studio-error">{posterError}</div>}
              {posterDesign ? (
                <div className="studio-poster-preview-wrap">
                  <div className="studio-poster-controls-grid">
                    <div className="studio-poster-controls-card">
                      <div className="studio-poster-controls-head">
                        <div>
                          <strong>配色风格</strong>
                          <p>先决定海报的气质，预览会实时更新。</p>
                        </div>
                      </div>
                      <div className="studio-theme-row">
                        {[
                          ["tech_blue", "科技蓝"],
                          ["youthful_gradient", "青春渐变"],
                          ["minimal_black", "极简黑"],
                          ["warm_orange", "暖橙"],
                          ["green_growth", "成长绿"],
                        ].map(([value, label]) => (
                          <button
                            key={value}
                            type="button"
                            className={`studio-theme-chip${posterDesign.theme === value ? " active" : ""}`}
                            onClick={() => setPosterDesign((prev) => (prev ? { ...prev, theme: value } : prev))}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div className="studio-poster-controls-card">
                      <div className="studio-poster-controls-head">
                        <div>
                          <strong>版式偏好</strong>
                          <p>可以选择更偏展示感，或更偏信息表达。</p>
                        </div>
                      </div>
                      <div className="studio-theme-row">
                        {[
                          ["portrait", "竖版展示"],
                          ["landscape", "横版展示"],
                          ["story_focus", "故事表达"],
                          ["data_focus", "数据表达"],
                        ].map(([value, label]) => (
                          <button
                            key={value}
                            type="button"
                            className={`studio-theme-chip${(value === "portrait" || value === "landscape")
                              ? posterDesign.layout?.orientation === value
                              : posterDesign.layout?.grid === value ? " active" : ""}`}
                            onClick={() => setPosterDesign((prev) => {
                              if (!prev) return prev;
                              if (value === "portrait" || value === "landscape") {
                                return { ...prev, layout: { ...prev.layout, orientation: value as "portrait" | "landscape" } };
                              }
                              return { ...prev, layout: { ...prev.layout, grid: value, accent_area: value === "data_focus" ? "right_column" : "top_left" } };
                            })}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                  <div className="studio-poster-preview-head">
                    <div>
                      <div className="studio-section-caption">海报预览</div>
                      <p>{posterEditMode ? "当前处于编辑模式，可以直接修改标题、小节和要点。" : "当前处于预览模式，适合整体看风格和版式效果。"}</p>
                    </div>
                  </div>
                  <PosterPreview design={posterDesign} onChange={setPosterDesign} mode={posterEditMode ? "edit" : "view"} />
                </div>
              ) : !posterLoading ? (
                <div className="studio-empty">
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="1.2"><rect x="4" y="3" width="16" height="14" rx="2" /><path d="M8 8h8" /><path d="M8 12h5" /><path d="M10 21l2-4 2 4" /></svg>
                  <span>先在左侧补充项目内容，再生成一版海报草稿，后面可以继续改风格和文案。</span>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      )}

      {/* ── KG Explorer Panel (slides in below TopBar) ── */}
      {kbPanelOpen && (
        <div className="kb-panel-overlay">
          <div className="kb-panel-container">
            <KBGraphPanel onClose={() => setKbPanelOpen(false)} />
          </div>
        </div>
      )}

      <div className={`chat-body ${pdfViewerOpen ? "pdf-split-mode" : ""}`}>
        {/* ── Conversation Sidebar ── */}
        {convSidebarOpen && !pdfViewerOpen && (
          <aside className="conv-sidebar" style={{ width: sidebarWidth }}>
            <button className="new-chat-btn" onClick={newChat}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 5v14M5 12h14"/></svg>
              新对话
            </button>
            <div className="conv-search-box">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
              <input className="conv-search" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="搜索对话…" />
            </div>
            <div className="conv-list">
              {filteredConvs.map((c) => (
                <div
                  key={c.conversation_id}
                  className={`conv-item ${c.conversation_id === conversationId ? "active" : ""}`}
                  onClick={() => loadConversation(c.conversation_id)}
                >
                  <div className="conv-item-row">
                    <span className="conv-title">{c.title || "新对话"}</span>
                    <button
                      type="button"
                      className="conv-delete-btn"
                      onClick={(e) => { e.stopPropagation(); deleteConversation(c.conversation_id); }}
                      title="删除对话"
                    >
                      ×
                    </button>
                  </div>
                  <span className="conv-preview">{c.last_message || "等待 AI 归纳..."}</span>
                  <span className="conv-meta">
                    {(() => {
                      const lid = convToLogicalId[c.conversation_id];
                      if (lid && /^P-[A-Za-z0-9_-]+-\d{2,}$/.test(lid)) {
                        return <span className="conv-pid-tag standard" title="规范项目编号">{lid}</span>;
                      }
                      return null;
                    })()}
                    {c.message_count}条 · {formatBjTime(c.created_at, true)}
                  </span>
                </div>
              ))}
              {filteredConvs.length === 0 && <p className="conv-empty">{searchQuery ? "未找到匹配的对话" : "暂无历史对话"}</p>}
            </div>
            <div className="sidebar-drag-handle" onMouseDown={startSidebarDrag} />
          </aside>
        )}

        {/* ── Messages ── */}
        <main className="chat-main">
          <div className="chat-scroll">
            {messages.length === 0 && (
              <div className="chat-welcome">
                <div className="welcome-glow" />
                <h2>{modeWelcome.title}</h2>
                <p>{modeWelcome.desc}</p>
                <div className="chat-hints">
                  {modeWelcome.hints.map((h) => (
                    <button key={h.text} className="hint-chip" onClick={() => { setInput(h.text); textareaRef.current?.focus(); }}>
                      <span className="hint-icon">{h.icon}</span>
                      <span>{h.text}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m, i) => (
              <div key={m.id} data-msg-index={i} className={`msg-row ${m.role}`} style={{ animationDelay: `${Math.min(i * 0.05, 0.3)}s` }}>
                {m.role === "assistant" && <div className="msg-avatar">AI</div>}
                <div className="msg-content">
                  <div className="msg-bubble">
                    {m.role === "assistant" ? (
                      <>
                        {/* Inline web search sources (DeepSeek style) */}
                        {i === messages.length - 1 && webSearch?.searched && (webSearch.results ?? []).length > 0 && (
                          <details className="ws-inline-block">
                            <summary className="ws-inline-summary">
                              <span className="ws-inline-icon">🔍</span>
                              已搜索 {webSearch.results.length} 个网络来源
                            </summary>
                            <div className="ws-inline-list">
                              {webSearch.results.map((r: any, ri: number) => (
                                <a key={ri} href={r.url} target="_blank" rel="noopener noreferrer" className="ws-inline-item">
                                  <span className="ws-inline-idx">{ri + 1}</span>
                                  <span className="ws-inline-info">
                                    <span className="ws-inline-title">{r.title}</span>
                                    <span className="ws-inline-domain">{r.url?.replace(/^https?:\/\//, "").split("/")[0]}</span>
                                  </span>
                                </a>
                              ))}
                            </div>
                          </details>
                        )}
                        <MarkdownContent content={m.text} theme={theme} />
                        {loading && i === messages.length - 1 && <span className="streaming-cursor" />}
                        {m.advisory && typeof m.advisory === "object" ? (
                          <FinanceAdvisoryCard
                            advisory={m.advisory as any}
                            onOpenReport={() => setRightTab("finance")}
                            onJumpBudget={() => {
                              try {
                                const btn = document.querySelector('[data-budget-open-btn]');
                                if (btn && btn instanceof HTMLElement) btn.click();
                              } catch { /* ignore */ }
                            }}
                          />
                        ) : null}
                        {m.text && !loading && <div className="ai-disclaimer">⚠ AI生成，仅供参考</div>}
                      </>
                    ) : (
                      m.text
                    )}
                  </div>
                  <div className="msg-actions-row">
                    {m.ts && <span className="msg-time">{m.ts}</span>}
                    <div className="msg-actions">
                      <button className={`msg-act-btn ${copiedId === m.id ? "active" : ""}`} onClick={() => copyText(m.text, m.id)} title="复制">
                        {copiedId === m.id ? (
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 6L9 17l-5-5"/></svg>
                        ) : (
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                        )}
                      </button>
                      {m.role === "assistant" && (
                        <>
                          <button className={`msg-act-btn ${likedMsgs.has(m.id) ? "liked" : ""}`} onClick={() => toggleLike(m.id)} title="有帮助">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill={likedMsgs.has(m.id) ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2"><path d="M14 9V5a3 3 0 00-3-3l-4 9v11h11.28a2 2 0 002-1.7l1.38-9a2 2 0 00-2-2.3H14zM7 22H4a2 2 0 01-2-2v-7a2 2 0 012-2h3"/></svg>
                          </button>
                          <button className={`msg-act-btn ${dislikedMsgs.has(m.id) ? "disliked" : ""}`} onClick={() => toggleDislike(m.id)} title="需要改进">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill={dislikedMsgs.has(m.id) ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2"><path d="M10 15v4a3 3 0 003 3l4-9V2H5.72a2 2 0 00-2 1.7l-1.38 9a2 2 0 002 2.3H10zM17 2h2.67A2.31 2.31 0 0122 4v7a2.31 2.31 0 01-2.33 2H17"/></svg>
                          </button>
                        </>
                      )}
                      {m.role === "user" && (
                        <button className="msg-act-btn" onClick={() => retrySend(m.id)} title="重新发送">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M1 4v6h6"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/></svg>
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ))}

            {loading && messages.length > 0 && messages[messages.length - 1].role === "user" && (
              <div className="msg-row assistant">
                <div className="msg-avatar">AI</div>
                <div className="msg-content"><div className="msg-bubble typing">
                  <div className="typing-dots"><span /><span /><span /></div>
                  正在分析...
                </div></div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* ── Input Bar ── */}
          <div className="chat-inputbar-wrapper">
            {docReview && !docReviewOpen && !pdfViewerOpen && (
              <div className="attached-file-badge doc-review-reopen" style={{ cursor: "pointer" }}
                onClick={() => {
                  if (docReview.fileUrl && docReview.filename.toLowerCase().endsWith(".pdf")) {
                    setPdfViewerUrl(docReview.fileUrl); setPdfViewerOpen(true);
                  } else { setDocReviewOpen(true); }
                }}>
                <span>📄 打开文档审阅：{docReview.filename}</span>
                {docReview.annotations.length > 0 && <span className="doc-annot-count">{docReview.annotations.length}条批注</span>}
              </div>
            )}
            {attachedFile && (
              <div className="attached-file-badge">
                <span>📎 {attachedFile.name}</span>
                <button type="button" onClick={() => setAttachedFile(null)} className="remove-file">✕</button>
              </div>
            )}
            <form className="chat-inputbar" onSubmit={send}>
              <input ref={fileInputRef} type="file" hidden accept=".pdf,.docx,.pptx,.ppt,.txt,.md" onChange={handleFileSelect} />
              <button type="button" className="attach-btn" onClick={() => fileInputRef.current?.click()} title="上传文件">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
                </svg>
              </button>
              <textarea
                ref={textareaRef}
                className="chat-textarea"
                value={input}
                onChange={(e) => { setInput(e.target.value); autoResize(); }}
                onKeyDown={handleKeyDown}
                placeholder={`${inputPlaceholder}  (Shift+Enter 换行)`}
                rows={1}
              />
              {loading ? (
                <button type="button" className="send-btn stop-btn" onClick={abortResponse} title="停止回答">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>
                </button>
              ) : (
                <button type="submit" className="send-btn" disabled={!input.trim() && !attachedFile}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 2L11 13"/><path d="M22 2L15 22L11 13L2 9L22 2Z"/></svg>
                </button>
              )}
            </form>
          </div>
        </main>

        {/* ── PDF Split Viewer (right side) ── */}
        {pdfViewerOpen && pdfViewerUrl && (
          <div className="pdf-viewer-pane">
            <div className="pdf-viewer-header">
              <span className="pdf-viewer-title">📄 {docReview?.filename ?? "文档预览"}</span>
              <div className="pdf-viewer-actions">
                <button className="pdf-viewer-btn" onClick={() => { setDocReviewOpen(true); setPdfViewerOpen(false); }} title="查看批注">📝 批注</button>
                <button className="pdf-viewer-btn" onClick={() => setPdfViewerOpen(false)} title="关闭">✕</button>
              </div>
            </div>
            {/* AI annotations overlay on top of the PDF section list */}
            {docReview && docReview.annotations.length > 0 ? (
              <div className="pdf-annot-scroll">
                {docReview.sections.map((sec: any) => {
                  const annots = docReview.annotations.filter((a: any) => a.section_id === sec.id);
                  return (
                    <div key={sec.id} className={`pdf-annot-section ${annots.length > 0 ? "has-annot" : ""}`}>
                      <div className="pdf-annot-secnum">§{sec.id + 1}</div>
                      <div className="pdf-annot-text">{sec.text.slice(0, 200)}{sec.text.length > 200 ? "..." : ""}</div>
                      {annots.map((a: any, ai: number) => (
                        <div key={ai} className={`pdf-annot-badge ${a.type}`}>
                          <span className="pdf-annot-type">{{ praise: "✅", issue: "⚠️", suggestion: "💡", question: "❓" }[a.type as string] ?? "📌"} {a.type === "praise" ? "优点" : a.type === "issue" ? "问题" : a.type === "suggestion" ? "建议" : "提问"}</span>
                          <span className="pdf-annot-content">{a.content}</span>
                        </div>
                      ))}
                      {annots.length === 0 && <div className="pdf-annot-ok">✓ 此段无问题</div>}
                    </div>
                  );
                })}
              </div>
            ) : docReviewLoading ? (
              <div className="pdf-annot-loading">
                <div className="typing-dots"><span /><span /><span /></div>
                <p>AI 正在逐段阅读你的文档...</p>
              </div>
            ) : (
              <iframe src={pdfViewerUrl} className="pdf-viewer-iframe" title="PDF Preview" />
            )}
            <div className="pdf-viewer-hint">
              AI 批注会逐段显示。你可以在左侧聊天中针对具体内容提问。
            </div>
          </div>
        )}

        {/* ── Right Panel (resizable) ── */}
        {rightOpen && !pdfViewerOpen && (
          <aside className="chat-right" style={{ width: rightWidth }}>
            <div className="right-drag-handle" onMouseDown={startDrag} />
            <div className="right-tabs-scroll">
              {([
                { id: "agents", label: "智能体" },
                { id: "task",   label: "任务" },
                { id: "bp",     label: "计划书" },
                { id: "risk",   label: "风险" },
                { id: "score",  label: "评分" },
                { id: "finance", label: "财务" },
                { id: "kg",     label: "图谱" },
                { id: "hyper",  label: "超图" },
                { id: "cases",  label: "案例" },
                { id: "feedback", label: "批注" },
                { id: "interventions", label: "教师任务" },
                { id: "debug",  label: "调试" },
              ] as { id: RightTab; label: string }[]).map((t) => (
                <button key={t.id} className={`rtab-pill ${rightTab === t.id ? "active" : ""}`} onClick={() => { setRightTab(t.id); if (t.id === "feedback") loadFeedback(); if (t.id === "interventions") loadInterventions(); }}>
                  {t.label}
                </button>
              ))}
            </div>

            <div className="right-body">
              {rightTab === "agents" && (
                <div className="right-section">
                  <h4>多智能体协作</h4>
                  <div className="panel-desc">你的问题由多位专家Agent协同分析，每位Agent有独立的角色定位和分析工具。</div>
                  {agentsCalled.length > 0 ? (
                    <>
                      {/* Intent detection info */}
                      {latestResult?.agent_trace?.orchestration && (
                        <div className="agent-intent-badge">
                          <span className="intent-label">意图识别</span>
                          <span className="intent-value">{{ project_diagnosis: "项目诊断", evidence_check: "证据检查", business_model: "商业模式", competition_prep: "竞赛准备", pressure_test: "压力测试", learning_concept: "概念学习", idea_brainstorm: "头脑风暴", general_chat: "日常对话" }[latestResult.agent_trace.orchestration.intent as string] ?? latestResult.agent_trace.orchestration.intent}</span>
                          <span className="intent-engine">{latestResult.agent_trace.orchestration.intent_shape === "mixed" ? "混合" : "单一"}</span>
                          <span className="intent-engine">({latestResult.agent_trace.orchestration.engine})</span>
                        </div>
                      )}
                      {latestResult?.agent_trace?.orchestration?.intent_reason && (
                        <div className="panel-desc" style={{ marginBottom: 10 }}>识别理由：{latestResult.agent_trace.orchestration.intent_reason}</div>
                      )}
                      {latestResult?.agent_trace?.orchestration && (
                        <div className="panel-desc" style={{ marginBottom: 10 }}>
                          连续模式：{latestResult.agent_trace.orchestration.conversation_continuation_mode || "new_analysis"}
                          {" · "}
                          评分追问：{latestResult.agent_trace.orchestration.score_request_detected ? "是" : "否"}
                          {" · "}
                          评委追问：{latestResult.agent_trace.orchestration.eval_followup_detected ? "是" : "否"}
                          {" · "}
                          RAG命中：{latestResult.agent_trace.orchestration.rag_hits ?? 0}
                        </div>
                      )}
                      {latestResult?.agent_trace?.orchestration?.conversation_state_summary && (
                        <div className="panel-desc" style={{ marginBottom: 10, whiteSpace: "pre-wrap" }}>
                          连续摘要：{latestResult.agent_trace.orchestration.conversation_state_summary}
                        </div>
                      )}
                      <div className="agent-flow">
                        {agentsCalled.map((a: string, i: number) => (
                          <span key={i} className="agent-flow-node">
                            {a === "router" ? "🔀 路由" : a}
                            {i < agentsCalled.length - 1 && <span className="agent-flow-arrow">→</span>}
                          </span>
                        ))}
                      </div>
                      {/* Web Search Results */}
                      {webSearch?.searched && (webSearch.results ?? []).length > 0 && (
                        <div className="ws-results-card">
                          <h5>🔍 联网搜索 <span className="ws-query">{webSearch.query}</span></h5>
                          {webSearch.results.map((r: any, ri: number) => (
                            <a key={ri} href={r.url} target="_blank" rel="noopener noreferrer" className="ws-result-item">
                              <span className="ws-result-title">{r.title}</span>
                              <span className="ws-result-snippet">{r.snippet}</span>
                              <span className="ws-result-url">{r.url?.replace(/^https?:\/\//, "").split("/")[0]}</span>
                            </a>
                          ))}
                        </div>
                      )}
                      {Object.entries(roleAgents).map(([key, val]: [string, any]) => {
                        if (!val || !val.analysis) return null;
                        const nameMap: Record<string, string> = { coach: "🎯 项目教练", analyst: "⚠️ 风险分析师", advisor: "🏆 竞赛顾问", tutor: "📚 课程导师", grader: "📊 评分官", planner: "📋 行动规划师" };
                        const toolMap: Record<string, string> = { diagnosis: "诊断引擎", rag: "案例知识库", kg_extract: "项目分析", web_search: "联网搜索", hypergraph: "多维分析", hypergraph_student: "维度覆盖", challenge_strategies: "追问策略库", critic_llm: "批判思维", competition_llm: "竞赛评审", learning_llm: "概念教学", kg_baseline: "本地KG检索", rag_reference: "案例引用", rubric_engine: "评分标准", kg_scores: "维度评分", next_task: "任务建议", critic: "批判分析" };

                        const renderPlannerCard = (analysis: string) => {
                          const titleMatch = analysis.match(/\*\*标题\*\*[：:]\s*(.+?)(?:\n|$)/);
                          const whyMatch = analysis.match(/\*\*为什么现在做这个\*\*[：:]\s*(.+?)(?:\n\*\*|$)/s);
                          const stepsMatch = analysis.match(/\*\*具体步骤\*\*[：:]\s*\n((?:\d+\..+\n?)+)/);
                          const criteriaMatch = analysis.match(/\*\*验收标准\*\*[：:]\s*\n((?:[-•].+\n?)+)/);
                          const deferredMatch = analysis.match(/##\s*暂不处理[^\n]*\n((?:[-•].+\n?)+)/);
                          if (!titleMatch) return null;
                          const steps = stepsMatch ? stepsMatch[1].split("\n").filter((l: string) => l.trim()).map((l: string) => l.replace(/^\d+\.\s*/, "").trim()) : [];
                          const criteria = criteriaMatch ? criteriaMatch[1].split("\n").filter((l: string) => l.trim()).map((l: string) => l.replace(/^[-•]\s*/, "").trim()) : [];
                          const deferred = deferredMatch ? deferredMatch[1].split("\n").filter((l: string) => l.trim()).map((l: string) => l.replace(/^[-•]\s*/, "").trim()) : [];
                          return (
                            <div className="planner-structured">
                              <div style={{ fontWeight: 700, fontSize: "1.05em", marginBottom: 6 }}>{titleMatch[1].trim()}</div>
                              {whyMatch && <div style={{ color: "var(--text-secondary)", fontSize: "0.92em", marginBottom: 8 }}>{whyMatch[1].trim()}</div>}
                              {steps.length > 0 && (
                                <div style={{ marginBottom: 8 }}>
                                  <div style={{ fontWeight: 600, fontSize: "0.9em", marginBottom: 4 }}>具体步骤</div>
                                  <ol style={{ margin: 0, paddingLeft: 20 }}>{steps.map((s: string, i: number) => <li key={i} style={{ marginBottom: 3, fontSize: "0.92em" }}>{s}</li>)}</ol>
                                </div>
                              )}
                              {criteria.length > 0 && (
                                <div style={{ marginBottom: 8 }}>
                                  <div style={{ fontWeight: 600, fontSize: "0.9em", marginBottom: 4 }}>验收标准</div>
                                  <ul style={{ margin: 0, paddingLeft: 20, listStyle: "none" }}>{criteria.map((c: string, i: number) => <li key={i} style={{ fontSize: "0.92em" }}>✓ {c}</li>)}</ul>
                                </div>
                              )}
                              {deferred.length > 0 && (
                                <details style={{ marginTop: 6 }}>
                                  <summary style={{ fontSize: "0.88em", color: "var(--text-secondary)", cursor: "pointer" }}>暂不处理（{deferred.length}项）</summary>
                                  <ul style={{ margin: "4px 0 0 0", paddingLeft: 20, fontSize: "0.88em" }}>{deferred.map((d: string, i: number) => <li key={i}>{d}</li>)}</ul>
                                </details>
                              )}
                            </div>
                          );
                        };

                        return (
                          <details key={key} className="agent-card" open>
                            <summary className="agent-card-header">
                              <span className="agent-card-name">{nameMap[key] ?? val.agent ?? key}</span>
                              <span className="agent-card-tools">
                                {(val.tools_used ?? []).map((t: string) => toolMap[t] ?? t).join(" · ")}
                                {val.turn_count ? ` · 累积${val.turn_count}轮` : ""}
                              </span>
                            </summary>
                            <div className="agent-card-body">
                              {key === "planner" ? (renderPlannerCard(val.analysis) ?? <MarkdownContent content={val.analysis} theme={theme} />) : <MarkdownContent content={val.analysis} theme={theme} />}
                            </div>
                          </details>
                        );
                      })}
                    </>
                  ) : <p className="right-hint">发送消息后，这里会展示各专家Agent的协作过程和独立分析结果</p>}
                </div>
              )}

              {rightTab === "task" && (
                <div className="right-section">
                  <div className="panel-desc">基于你的全部对话累积生成的行动建议，不会因追问而丢失。</div>
                  {(() => {
                    const s = (v: any): string => (v == null ? "" : typeof v === "string" ? v : JSON.stringify(v));
                    const priLabel: Record<string, string> = { urgent: "紧急", important: "重要", nice_to_have: "建议" };
                    const priClass: Record<string, string> = { urgent: "pri-urgent", important: "pri-important", nice_to_have: "pri-nice" };
                    const tasks = cumulativePlannerTasks;
                    const milestone = s(cumulativeMilestone);
                    const notNow: string[] = (plannerNotNow || []).map((x: any) => s(x)).filter(Boolean);
                    const pastTasks = plannerTaskHistory.filter((h: any) => !h.isCurrent);
                    const clip = (v: string, max: number) => v.length > max ? v.slice(0, max) + "…" : v;
                    if (tasks.length > 0) {
                      return (
                        <div className="task-rich">
                          {milestone && <div className="task-milestone">{clip(milestone, 60)}</div>}
                          {tasks.slice(0, 3).map((t: any, ti: number) => {
                            const pri = s(t.priority);
                            const howArr: string[] = Array.isArray(t.how) ? t.how.map((h: any) => clip(s(h), 50)) : s(t.how) ? [clip(s(t.how), 120)] : [];
                            return (
                            <details key={ti} className="task-card-v2" open={ti === 0}>
                              <summary className="task-card-head">
                                <span className="task-num">{ti + 1}</span>
                                  {pri && priLabel[pri] && <span className={`task-pri-tag ${priClass[pri] || ""}`}>{priLabel[pri]}</span>}
                                <span className="task-title-v2">{clip(s(t.task), 40)}</span>
                              </summary>
                              <div className="task-card-body">
                                {s(t.why) && <p className="task-why">{clip(s(t.why), 80)}</p>}
                                  {howArr.length > 0 && <ul className="task-how-list">{howArr.slice(0, 3).map((step, si) => <li key={si}>{step}</li>)}</ul>}
                                  {s(t.acceptance) && <div className="task-accept"><span className="task-accept-label">验收</span> {clip(s(t.acceptance), 60)}</div>}
                              </div>
                            </details>
                            );
                          })}
                          {notNow.length > 0 && (
                            <div className="task-not-now">
                              <h5>本周先别做</h5>
                              <div className="not-now-chips">{notNow.map((item, i) => <span key={i} className="not-now-chip">{item}</span>)}</div>
                            </div>
                          )}
                          {pastTasks.length > 0 && (
                            <details className="task-history-section">
                              <summary className="task-history-head">往期建议（{pastTasks.length}条）</summary>
                              <div className="task-history-body">
                                {pastTasks.map((h: any, hi: number) => (
                                  <div key={hi} className="task-history-item">
                                    <span className="task-history-turn">第{h.turn}轮</span>
                                    <span className="task-history-title">{s(h.task?.task || h.task)}</span>
                                  </div>
                                ))}
                              </div>
                            </details>
                          )}
                        </div>
                      );
                    }
                    if (nextTask && nextTask.title && s(nextTask.title) !== "描述你的项目") {
                      const tg = (nextTask.template_guideline || []).slice(0, 3);
                      const ac = (nextTask.acceptance_criteria || []).slice(0, 3);
                      return (
                        <div className="task-rich">
                          <details className="task-card-v2" open>
                            <summary className="task-card-head">
                              <span className="task-num">1</span>
                              <span className="task-title-v2">{clip(s(nextTask.title), 40)}</span>
                            </summary>
                            <div className="task-card-body">
                              <p className="task-why">{clip(s(nextTask.description), 150)}</p>
                              {tg.length > 0 && (
                                <ul className="task-how-list">
                                  {tg.map((step: string, i: number) => <li key={i}>{clip(step, 50)}</li>)}
                                </ul>
                              )}
                              {ac.length > 0 && (
                                <div className="task-accept">
                                  <span className="task-accept-label">验收</span> {ac.map((a: string) => clip(a, 40)).join("；")}
                                </div>
                              )}
                            </div>
                          </details>
                        </div>
                      );
                    }
                    return <p className="right-hint">描述你的项目后，这里会生成针对性的行动建议</p>;
                  })()}
                </div>
              )}

              {rightTab === "bp" && (
                <div className="right-section">
                  <h4>商业计划书</h4>
                  <div className="panel-desc">先快速生成一份草稿（1 次 KB 蒸馏 + 1 次短版写作），再按需升级为基础版或正式版；每章支持「继续深化」。</div>
                  {(() => {
                    const maturityScore = typeof bpReadiness?.maturity_score === "number" ? bpReadiness.maturity_score : (businessPlan?.maturity?.score ?? null);
                    const maturityTier = (bpReadiness?.maturity_tier as string) || businessPlan?.maturity?.tier || "not_ready";
                    const maturityTierLabel = (bpReadiness?.maturity_tier_label as string) || (maturityTier === "full_ready" ? "充分就绪" : maturityTier === "basic_ready" ? "基础就绪" : "未就绪");
                    const maturityBreakdown = (bpReadiness?.maturity_breakdown as any) || businessPlan?.maturity?.breakdown || {};
                    const maturityNextGap = (bpReadiness?.maturity_next_gap as any[]) || businessPlan?.maturity?.next_gap || [];
                    const versionTier = (businessPlan?.version_tier as string) || "draft";
                    const upgradeLabel = maturityTier === "full_ready" ? "升级为正式版" : maturityTier === "basic_ready" ? "升级为基础版" : "升级（未就绪）";
                    const upgradeMode: "basic" | "full" = maturityTier === "full_ready" ? "full" : "basic";
                    const chipClass = `bp-maturity-chip tier-${maturityTier}`;
                    const pendingCount = (businessPlan?.pending_revisions ?? []).length;
                    const suggestCount = bpSuggestions.length;
                    const plan = businessPlan;
                    const sectionsCount = plan?.sections?.length ?? 0;
                    const wordCount = plan ? (plan.sections || []).reduce((sum, s) => sum + ((s.user_edit || s.content || "").length), 0) : 0;
                    const titleText = plan?.title || (plan?.cover_info?.project_name as string) || "商业计划书";
                    const rawOneLiner = (plan?.knowledge_base as any)?.one_liner || (plan?.cover_info?.one_liner as string) || "";
                    const oneLiner = String(rawOneLiner || "").trim();
                    const teamInfo = [(plan?.cover_info?.student_or_team as string), (plan?.cover_info?.course_or_class as string), (plan?.cover_info?.teacher_name as string)].filter(Boolean).join(" · ");
                    const updatedAt = (plan?.updated_at as string) || (plan?.created_at as string) || "";
                    const ring = (() => {
                      const score = Number(maturityScore ?? 0);
                      const pct = Math.max(0, Math.min(100, score));
                      const radius = 28;
                      const circ = 2 * Math.PI * radius;
                      const dash = (pct / 100) * circ;
                      return { pct, radius, circ, dash };
                    })();
                    const failedIds = plan?.upgrade_report?.failed_ids ?? [];
                    return (
                      <>
                        {plan && (
                          <div className="bp-cover-strip bp-cs-v2">
                            {/* 左列：叙事（标题 / 一句话 / 教练模式） */}
                            <div className="bp-cs-left">
                              <div className="bp-cs-title-row">
                                <span className={`bp-version-chip tier-${versionTier} bp-cs-chip`}>
                                  {versionTier === "full" ? "正式版" : versionTier === "basic" ? "基础版" : "草稿"}
                                </span>
                                <div className="bp-cs-title" title={titleText}>{titleText}</div>
                              </div>
                              {oneLiner ? (
                                <div className="bp-cs-oneliner" title={oneLiner}>{oneLiner}</div>
                              ) : (
                                <div className="bp-oneliner-ghost" aria-hidden title="等待项目描述">
                                  <span className="bp-dot" /><span className="bp-dot" /><span className="bp-dot" />
                                  <span className="bp-oneliner-ghost-tag">待项目描述</span>
                                </div>
                              )}
                              {/* 教练模式徽标：只读，模式随顶栏自动同步 */}
                              {plan && (() => {
                                const coachMode = String(((plan as any).coaching_mode) || "project");
                                const isCompetition = coachMode === "competition";
                                const unlocked = (plan as any).competition_unlocked !== false;
                                return (
                                  <span
                                    className={`bp-coach-badge ${isCompetition ? "is-competition" : "is-project"} ${isCompetition && !unlocked ? "is-warn" : ""}`}
                                    title={
                                      isCompetition
                                        ? unlocked
                                          ? "竞赛教练模式：评委视角追问，产出议题板（顶栏切换回其它模式即自动回项目教练）"
                                          : "当前成熟度未达基础就绪，竞赛教练建议仅覆盖关键章节"
                                        : "项目教练模式：按章节完整度节奏引导。顶栏选『竞赛冲刺』即自动进入竞赛教练"
                                    }
                                  >
                                    <span className="bp-coach-badge-dot" aria-hidden />
                                    <span className="bp-coach-badge-txt">
                                      {isCompetition ? "竞赛教练" : "项目教练"}
                                    </span>
                                    {isCompetition && !unlocked && (
                                      <span className="bp-coach-badge-warn">成熟度不足</span>
                                    )}
                                  </span>
                                );
                              })()}
                            </div>

                            {/* 右列：指标群（成熟度环 + 统计三胞胎） */}
                            <div className="bp-cs-right">
                              {maturityScore != null && (
                                <button
                                  type="button"
                                  className={`bp-cs-maturity tier-${maturityTier}`}
                                  onClick={() => setBpMaturityOpen((v) => !v)}
                                  title="点击查看成熟度详情"
                                >
                                  <svg viewBox="0 0 32 32" width="30" height="30">
                                    <circle cx="16" cy="16" r="13" stroke="rgba(255,255,255,0.14)" strokeWidth="3" fill="none" />
                                    <circle
                                      cx="16" cy="16" r="13"
                                      stroke="currentColor" strokeWidth="3" fill="none"
                                      strokeDasharray={`${(Math.max(0, Math.min(100, Number(maturityScore ?? 0))) / 100) * (2 * Math.PI * 13)} ${2 * Math.PI * 13}`}
                                      strokeLinecap="round"
                                      transform="rotate(-90 16 16)"
                                    />
                                  </svg>
                                  <div className="bp-cs-m-meta">
                                    <span className="bp-cs-m-val">{Number(maturityScore)}</span>
                                    <span className="bp-cs-m-lbl">{maturityTierLabel}</span>
                                  </div>
                                </button>
                              )}
                              <div className="bp-cs-stats-grid" aria-hidden>
                                <div className="bp-cs-stat">
                                  <span className="bp-cs-stat-v">{sectionsCount}</span>
                                  <span className="bp-cs-stat-l">章节</span>
                                </div>
                                <div className="bp-cs-stat">
                                  <span className="bp-cs-stat-v">{wordCount >= 10000 ? `${(wordCount / 1000).toFixed(1)}k` : wordCount.toLocaleString()}</span>
                                  <span className="bp-cs-stat-l">字数</span>
                                </div>
                                {pendingCount > 0 ? (
                                  <div className="bp-cs-stat is-pending">
                                    <span className="bp-cs-stat-v">{pendingCount}</span>
                                    <span className="bp-cs-stat-l">待审</span>
                                  </div>
                                ) : updatedAt ? (
                                  <div className="bp-cs-stat is-date">
                                    <span className="bp-cs-stat-v">{updatedAt.slice(5, 10)}</span>
                                    <span className="bp-cs-stat-l">更新</span>
                                  </div>
                                ) : null}
                              </div>
                            </div>
                            {/* 旧 fork 分支兼容显示（老数据，只读切换） */}
                            {bpSiblings.filter((s) => s.plan_type === "competition_fork").length > 0 && (
                              <div className="bp-legacy-fork-hint">
                                <span>旧版竞赛分支：</span>
                                {bpSiblings.filter((s) => s.plan_type === "competition_fork").map((sib) => (
                                  <button
                                    key={sib.plan_id}
                                    type="button"
                                    className={`bp-legacy-fork-chip ${sib.plan_id === plan?.plan_id ? "is-active" : ""}`}
                                    onClick={() => sib.plan_id !== plan?.plan_id && openSiblingPlan(sib.plan_id)}
                                    title={`旧版竞赛分支 · ${sib.updated_at?.slice(5, 16) || ""}`}
                                  >
                                    旧版 {(sib.updated_at || "").slice(5, 10)}
                                  </button>
                                ))}
                              </div>
                            )}
                            {bpMaturityOpen && maturityScore != null && (
                              <div className="bp-maturity-pop bp-maturity-pop-strip">
                                <div className="bp-maturity-pop-row">
                                  <span>项目骨架</span>
                                  <div className="bp-maturity-bar"><div style={{ width: `${Math.round(((maturityBreakdown.skeleton ?? 0) / (maturityBreakdown.skeleton_max || 60)) * 100)}%` }} /></div>
                                  <span>{maturityBreakdown.skeleton ?? 0}/{maturityBreakdown.skeleton_max ?? 60}</span>
                                </div>
                                <div className="bp-maturity-pop-row">
                                  <span>智能体密度</span>
                                  <div className="bp-maturity-bar"><div style={{ width: `${Math.round(((maturityBreakdown.agent_density ?? 0) / (maturityBreakdown.agent_density_max || 30)) * 100)}%` }} /></div>
                                  <span>{maturityBreakdown.agent_density ?? 0}/{maturityBreakdown.agent_density_max ?? 30}</span>
                                </div>
                                <div className="bp-maturity-pop-row">
                                  <span>逻辑自洽</span>
                                  <div className="bp-maturity-bar"><div style={{ width: `${Math.round(((maturityBreakdown.coherence ?? 0) / (maturityBreakdown.coherence_max || 10)) * 100)}%` }} /></div>
                                  <span>{maturityBreakdown.coherence ?? 0}/{maturityBreakdown.coherence_max ?? 10}</span>
                                </div>
                                {maturityNextGap.length > 0 && (
                                  <div className="bp-maturity-gaps">
                                    <div className="bp-maturity-gap-title">
                                      距离下一档还差：
                                      <span className="bp-maturity-gap-hint">点击任意建议即可填入对话</span>
                                    </div>
                                    {maturityNextGap.slice(0, 4).map((g: any, idx: number) => {
                                      const dim = (g.dimension || g.dim || "") as string;
                                      const dimLabel = dim === "skeleton" ? "骨架" : dim === "agent_density" || dim === "agent" ? "智能体" : dim === "coherence" ? "逻辑" : "";
                                      const suggestion: string = g.suggestion || "";
                                      const fieldLabel: string = g.field_label || g.field || "";
                                      return (
                                        <button
                                          key={idx}
                                          type="button"
                                          className={`bp-maturity-gap is-clickable dim-${dim || "misc"}`}
                                          onClick={() => {
                                            if (suggestion) {
                                              setInput(suggestion);
                                              setBpMaturityOpen(false);
                                              setTimeout(() => {
                                                textareaRef.current?.focus();
                                                textareaRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
                                              }, 80);
                                            }
                                          }}
                                          title="点击把这条问题填入下方对话输入框"
                                        >
                                          <div className="bp-maturity-gap-reason">
                                            {dimLabel && <span className={`bp-maturity-dim-tag dim-${dim || "misc"}`}>{dimLabel}</span>}
                                            {fieldLabel}
                                          </div>
                                          <div className="bp-maturity-gap-sugg">{suggestion}</div>
                                        </button>
                                      );
                                    })}
                                  </div>
                                )}
                                {((bpReadiness as any)?.maturity_breakdown_rationale) && (
                                  <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px dashed rgba(255,255,255,0.12)" }}>
                                    <RationaleCard
                                      rationale={(bpReadiness as any).maturity_breakdown_rationale as Rationale}
                                      compact
                                      title="成熟度打分公式"
                                    />
                                  </div>
                                )}
                                <div className="bp-maturity-foot">
                                  <span className="bp-maturity-foot-tip">评分由骨架(60) + 智能体信息(30) + 逻辑(10)加权，实时更新</span>
                                  <button className="bp-maturity-close" onClick={() => setBpMaturityOpen(false)}>关闭</button>
                                </div>
                              </div>
                            )}
                          </div>
                        )}

                        {/* 教师评分回显卡片 */}
                        {plan && bpGrading && (
                          <div className="bp-grading-card">
                            <div className="bp-grading-head">
                              <span className="bp-grading-ic">🎓</span>
                              <span className="bp-grading-title">教师批改反馈</span>
                              <button className="bp-grading-toggle" onClick={() => setBpGradingOpen((v) => !v)}>
                                {bpGradingOpen ? "收起" : "展开"}
                              </button>
                            </div>
                            <div className="bp-grading-summary">
                              <div className="bp-grading-score-wrap">
                                <div className={`bp-grading-grade grade-${bpGrading.grade || "B"}`}>{bpGrading.grade || "B"}</div>
                                <div className="bp-grading-score">
                                  <b>{Number(bpGrading.overall_score || 0).toFixed(1)}</b>
                                  <span>/100</span>
                                </div>
                                <div className={`bp-grading-pass ${bpGrading.passed ? "is-pass" : "is-fail"}`}>
                                  {bpGrading.passed ? "已通过" : "待改进"}
                                </div>
                              </div>
                              <div className="bp-grading-teacher">
                                {bpGrading.teacher_name || bpGrading.teacher_id || "教师"} · {(bpGrading.updated_at || bpGrading.created_at || "").slice(5, 16).replace("T", " ")}
                              </div>
                            </div>
                            {bpGradingOpen && (
                              <div className="bp-grading-detail">
                                {bpGrading.summary && (
                                  <div className="bp-grading-block">
                                    <div className="bp-grading-block-title">总评</div>
                                    <div className="bp-grading-block-text">{bpGrading.summary}</div>
                                  </div>
                                )}
                                {(bpGrading.strengths || []).length > 0 && (
                                  <div className="bp-grading-block">
                                    <div className="bp-grading-block-title is-ok">亮点</div>
                                    <ul className="bp-grading-list">
                                      {(bpGrading.strengths || []).map((s: string, i: number) => (<li key={i}>{s}</li>))}
                                    </ul>
                                  </div>
                                )}
                                {(bpGrading.improvements || []).length > 0 && (
                                  <div className="bp-grading-block">
                                    <div className="bp-grading-block-title is-warn">建议改进</div>
                                    <ul className="bp-grading-list">
                                      {(bpGrading.improvements || []).map((s: string, i: number) => (<li key={i}>{s}</li>))}
                                    </ul>
                                  </div>
                                )}
                                {(bpGrading.rubric || []).length > 0 && (
                                  <div className="bp-grading-block">
                                    <div className="bp-grading-block-title">
                                      章节评分
                                      <span className="bp-grading-block-hint">（点「?」看打分依据）</span>
                                    </div>
                                    <div className="bp-grading-rubric">
                                      {(bpGrading.rubric || []).map((r: any, i: number) => {
                                        const title = (plan.sections || []).find((s) => s.section_id === r.section_id)?.display_title || r.section_id;
                                        const score = Math.max(0, Math.min(10, Number(r.score || 0)));
                                        const pct = score * 10;
                                        const keyId = r.section_id || `row-${i}`;
                                        const isOpen = bpGradingWhyId === keyId;
                                        return (
                                          <div key={i} className={`bp-grading-rubric-row ${isOpen ? "is-open" : ""}`} style={{ position: "relative" }}>
                                            <span className="bp-grading-rubric-title">{title}</span>
                                            <div className="bp-grading-rubric-bar"><div style={{ width: `${pct}%` }} /></div>
                                            <span className="bp-grading-rubric-score">{score.toFixed(1)}/10</span>
                                            <button
                                              type="button"
                                              className="bp-grading-rubric-why"
                                              onClick={() => setBpGradingWhyId(isOpen ? null : keyId)}
                                              aria-label="查看打分依据"
                                              title="查看本章节打分依据"
                                            >?</button>
                                            {isOpen && (
                                              <div className="bp-grading-rubric-pop">
                                                <div className="bp-grading-rubric-pop-head">
                                                  <span>{title} · 评分依据</span>
                                                  <button onClick={() => setBpGradingWhyId(null)}>×</button>
                                                </div>
                                                <div className="bp-grading-rubric-pop-row">
                                                  <span className="bp-grr-k">得分</span>
                                                  <span className="bp-grr-v"><b>{score.toFixed(1)}</b> / 10</span>
                                                </div>
                                                <div className="bp-grading-rubric-pop-row">
                                                  <span className="bp-grr-k">档位</span>
                                                  <span className="bp-grr-v">
                                                    {score >= 8.5 ? "优" : score >= 7 ? "良" : score >= 6 ? "中" : score >= 4 ? "待改进" : "不合格"}
                                                  </span>
                                                </div>
                                                <div className="bp-grading-rubric-pop-row">
                                                  <span className="bp-grr-k">在总评占比</span>
                                                  <span className="bp-grr-v">
                                                    章节分 × 1/{(bpGrading.rubric || []).length} = {score.toFixed(1)} ÷ {(bpGrading.rubric || []).length} = {(score / (bpGrading.rubric || []).length).toFixed(2)} 分
                                                  </span>
                                                </div>
                                                {r.comment ? (
                                                  <div className="bp-grading-rubric-pop-comment">
                                                    <div className="bp-grr-k">教师批注</div>
                                                    <div className="bp-grr-comment-text">{r.comment}</div>
                                                  </div>
                                                ) : (
                                                  <div className="bp-grading-rubric-pop-empty">教师未填写额外批注。</div>
                                                )}
                                              </div>
                                            )}
                                          </div>
                                        );
                                      })}
                                    </div>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        )}

                        {/* ═ FAB 悬浮工具栏（右下）═ */}
                        <div className={`bp-fab-wrap ${bpMoreOpen ? "is-open" : ""}`} ref={bpMoreRef}>
                          {bpMoreOpen && (
                            <div className="bp-fab-menu" role="menu">
                              <button
                                className="bp-fab-item bp-fab-primary"
                                onClick={() => { setBpMoreOpen(false); generateBusinessPlan(maturityTier === "not_ready"); }}
                                disabled={bpLoading || !conversationId}
                                title={plan ? "重新生成草稿（会替换全部章节内容）" : "生成一份快速草稿"}
                              >
                                <span className="bp-fab-ic">✦</span>
                                <span className="bp-fab-lbl">{bpLoading ? "生成中…" : (plan ? "重新生成草稿" : maturityTier === "not_ready" ? "强制生成草稿" : "生成草稿")}</span>
                              </button>
                              {plan && versionTier === "draft" && maturityTier !== "not_ready" && (
                                <button
                                  className="bp-fab-item"
                                  onClick={() => { setBpMoreOpen(false); upgradeBusinessPlan(upgradeMode); }}
                                  disabled={bpUpgradeBusy}
                                  title="基于草稿 + KB + 行业资料 + 同行业范本，并发扩写为正式长版（Ctrl+U）"
                                >
                                  <span className="bp-fab-ic">↑</span>
                                  <span className="bp-fab-lbl">{bpUpgradeBusy ? "升级中…" : upgradeLabel}</span>
                                  <kbd className="bp-fab-kbd">Ctrl+U</kbd>
                                </button>
                              )}
                              {plan && versionTier !== "draft" && (
                                <button
                                  className="bp-fab-item"
                                  onClick={() => { setBpMoreOpen(false); upgradeBusinessPlan("full"); }}
                                  disabled={bpUpgradeBusy}
                                  title="再次基于最新素材重写正式版（Ctrl+U）"
                                >
                                  <span className="bp-fab-ic">↻</span>
                                  <span className="bp-fab-lbl">{bpUpgradeBusy ? "升级中…" : "重做正式版"}</span>
                                  <kbd className="bp-fab-kbd">Ctrl+U</kbd>
                                </button>
                              )}
                              {plan && pendingCount > 0 && (
                                <button
                                  className="bp-fab-item bp-fab-accent"
                                  onClick={() => { setBpMoreOpen(false); acceptAllRevisions(); }}
                                  disabled={bpAcceptAllBusy}
                                  title="把所有 AI 修订一次性合并到正文（Ctrl+Shift+A）"
                                >
                                  <span className="bp-fab-ic">✓</span>
                                  <span className="bp-fab-lbl">{bpAcceptAllBusy ? "合并中…" : "接受全部修订"}</span>
                                  <span className="bp-fab-badge">{pendingCount}</span>
                                </button>
                              )}
                              {/* 旧版 fork 入口已移除：改为顶栏的"教练模式切换"与议题板 */}
                              {plan && (
                                <>
                                  <div className="bp-fab-sep" />
                                  <button className="bp-fab-item bp-fab-ghost" onClick={() => { setBpMoreOpen(false); refreshBusinessPlan(); }} disabled={bpLoading || !plan?.plan_id}>
                                    <span className="bp-fab-ic">⟳</span><span className="bp-fab-lbl">刷新修订建议</span>
                                  </button>
                                  {bpViewMode === "edit" && (
                                    <button className="bp-fab-item bp-fab-ghost" onClick={() => { setBpMoreOpen(false); saveBusinessPlanSection(); }} disabled={bpSaving || !selectedBpSection}>
                                      <span className="bp-fab-ic">💾</span><span className="bp-fab-lbl">{bpSaving ? "保存中…" : "保存当前章节"}</span>
                                    </button>
                                  )}
                                  <button className="bp-fab-item bp-fab-ghost" onClick={() => { setBpMoreOpen(false); setBpSuggestDrawerOpen(true); if (bpSuggestions.length === 0) loadDeepenSuggestions(); }}>
                                    <span className="bp-fab-ic">💡</span>
                                    <span className="bp-fab-lbl">补充建议{suggestCount > 0 ? ` (${suggestCount})` : ""}</span>
                                  </button>
                                  {pendingCount > 0 && (
                                    <button className="bp-fab-item bp-fab-ghost" onClick={() => { setBpMoreOpen(false); rejectAllRevisions(); }} disabled={bpAcceptAllBusy}>
                                      <span className="bp-fab-ic">✕</span>
                                      <span className="bp-fab-lbl">忽略全部修订 ({pendingCount})</span>
                                    </button>
                                  )}
                                  <div className="bp-fab-sep" />
                                  <button
                                    className="bp-fab-item bp-fab-accent"
                                    onClick={() => { setBpMoreOpen(false); finalizeBusinessPlan(); }}
                                    disabled={bpFinalizeBusy || !plan?.plan_id}
                                    title="添加执行摘要 + 每章本章小结，让内容更像正式 BP"
                                  >
                                    <span className="bp-fab-ic">✨</span>
                                    <span className="bp-fab-lbl">{bpFinalizeBusy ? "润色中…" : "润色为正式稿"}</span>
                                  </button>
                                  <button
                                    className="bp-fab-item bp-fab-ghost"
                                    onClick={() => { setBpMoreOpen(false); createSnapshot(); }}
                                    disabled={bpSnapshotBusy || !plan?.plan_id}
                                    title="手动保存当前版本以便随时回滚"
                                  >
                                    <span className="bp-fab-ic">📌</span>
                                    <span className="bp-fab-lbl">{bpSnapshotBusy ? "保存中…" : "保存当前版本"}</span>
                                  </button>
                                  <button
                                    className="bp-fab-item bp-fab-ghost"
                                    onClick={() => { setBpMoreOpen(false); openSnapshotHistory(); }}
                                    disabled={!plan?.plan_id}
                                  >
                                    <span className="bp-fab-ic">🕘</span>
                                    <span className="bp-fab-lbl">版本历史</span>
                                  </button>
                                  <button
                                    className="bp-fab-item bp-fab-ghost"
                                    onClick={() => { setBpMoreOpen(false); setBpCommentsOpen(true); }}
                                    title="查看教师批注与建议"
                                  >
                                    <span className="bp-fab-ic">💬</span>
                                    <span className="bp-fab-lbl">
                                      教师建议
                                      {bpTeacherComments.filter((c: any) => (c.status || "open") === "open").length > 0 && (
                                        <span className="bp-fab-badge">{bpTeacherComments.filter((c: any) => (c.status || "open") === "open").length}</span>
                                      )}
                                    </span>
                                  </button>
                                  <div className="bp-fab-sep" />
                                  <button className="bp-fab-item bp-fab-ghost" onClick={() => { setBpMoreOpen(false); exportBusinessPlan("docx"); }} disabled={bpExportBusy}>
                                    <span className="bp-fab-ic">↓</span><span className="bp-fab-lbl">{bpExportBusy ? "导出中…" : "导出 docx"}</span>
                                  </button>
                                  <button className="bp-fab-item bp-fab-ghost" onClick={() => { setBpMoreOpen(false); exportBusinessPlan("pdf"); }}>
                                    <span className="bp-fab-ic">🖨</span><span className="bp-fab-lbl">导出 PDF（浏览器打印）</span>
                                  </button>
                                  {failedIds.length > 0 && (
                                    <button
                                      className="bp-fab-item bp-fab-ghost"
                                      onClick={() => { setBpMoreOpen(false); upgradeBusinessPlan((plan.upgrade_report?.mode as any) || "full"); }}
                                      disabled={bpUpgradeBusy}
                                    >
                                      <span className="bp-fab-ic">!</span>
                                      <span className="bp-fab-lbl">重试未完成的 {failedIds.length} 章</span>
                                    </button>
                                  )}
                                </>
                              )}
                              <div className="bp-fab-sep" />
                              <div className="bp-fab-mode">
                                {(["read", "edit"] as const).map((m) => (
                                  <button
                                    key={m}
                                    onClick={() => setBpViewMode(m)}
                                    className={bpViewMode === m ? "is-active" : ""}
                                    title={`切换${m === "read" ? "阅读" : "编辑"}（Ctrl+E）`}
                                  >
                                    {m === "read" ? "阅读" : "编辑"}
                                  </button>
                                ))}
                              </div>
                            </div>
                          )}
                          <button
                            type="button"
                            className={`bp-fab ${pendingCount > 0 ? "has-pending" : ""}`}
                            onClick={() => setBpMoreOpen((v) => !v)}
                            title="计划书工具箱"
                            aria-expanded={bpMoreOpen}
                          >
                            <span className="bp-fab-main-ic">{bpMoreOpen ? "×" : "✦"}</span>
                            {pendingCount > 0 && !bpMoreOpen && <span className="bp-fab-pill">{pendingCount}</span>}
                          </button>
                        </div>
                        {bpUpgradeToast && (
                          <div className="bp-toast-info">{bpUpgradeToast}</div>
                        )}
                      </>
                    );
                  })()}
                  {/* 竞赛教练议题板：仅在 coaching_mode === competition 时显示 */}
                  {businessPlan && String((businessPlan as any).coaching_mode || "project") === "competition" && (
                    <div className="bp-agenda-card right-card">
                      {(businessPlan as any).competition_unlocked === false && (
                        <div className="bp-agenda-lock-note">
                          成熟度未达基础就绪，竞赛教练建议仅覆盖关键章节。先补齐项目骨架与基础字段，可获得完整评委视角。
                        </div>
                      )}
                      <div className="bp-agenda-head">
                        <div className="bp-agenda-title">
                          竞赛教练议题板
                          <span className="bp-agenda-count">
                            {bpAgendaItems.filter((x) => (x.status || "pending") === "pending").length} 条待处理
                          </span>
                        </div>
                        <div className="bp-agenda-hint">
                          与竞赛教练每聊一轮，系统会把可落章节的评委视角点子堆到这里。勾选后一次性"应用到候选章节"。
                        </div>
                      </div>
                      {bpAgendaItems.length === 0 ? (
                        <div className="bp-agenda-empty-v2">
                          <svg viewBox="0 0 48 48" width="44" height="44" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="bp-ae-icon">
                            <rect x="7" y="10" width="28" height="22" rx="3" />
                            <path d="M13 16h16M13 21h11M13 26h8" />
                            <path d="M35 32l4 4M33 30l3-3 5 5-3 3-5-5z" />
                          </svg>
                          <div className="bp-ae-title">议题板空着</div>
                          <details className="bp-ae-details">
                            <summary>如何触发议题？</summary>
                            <p>切到竞赛教练后与之对话，关于评委视角、量化、反证、防守点等建议会自动沉淀到这里，勾选后可批量应用到候选章节。</p>
                          </details>
                        </div>
                      ) : (
                        <>
                          <div className="bp-agenda-list">
                            {bpAgendaItems
                              .filter((it) => (it.status || "pending") !== "applied")
                              .map((it) => {
                                const selected = bpAgendaSelected.has(it.agenda_id);
                                const expanded = bpAgendaExpanded.has(it.agenda_id);
                                const isDismissed = (it.status || "") === "dismissed";
                                return (
                                  <div
                                    key={it.agenda_id}
                                    className={`bp-agenda-item ${selected ? "is-selected" : ""} ${isDismissed ? "is-dismissed" : ""}`}
                                  >
                                    <div className="bp-agenda-row-main">
                                      <label className="bp-agenda-check">
                                        <input
                                          type="checkbox"
                                          disabled={isDismissed}
                                          checked={selected}
                                          onChange={(e) => {
                                            const next = new Set(bpAgendaSelected);
                                            if (e.target.checked) next.add(it.agenda_id);
                                            else next.delete(it.agenda_id);
                                            setBpAgendaSelected(next);
                                          }}
                                        />
                                      </label>
                                      <span className={`bp-agenda-tag tag-${(it.jury_tag || "默认").replace(/[^a-zA-Z0-9]/g, "_")}`}>
                                        {it.jury_tag || "议题"}
                                      </span>
                                      <button
                                        type="button"
                                        className="bp-agenda-title-btn"
                                        onClick={() => {
                                          const next = new Set(bpAgendaExpanded);
                                          if (next.has(it.agenda_id)) next.delete(it.agenda_id);
                                          else next.add(it.agenda_id);
                                          setBpAgendaExpanded(next);
                                        }}
                                      >
                                        {it.title || "未命名议题"}
                                      </button>
                                      {it.section_id_hint && (
                                        <span className="bp-agenda-section-hint" title={`建议落点：${it.section_id_hint}`}>
                                          → {it.section_id_hint}
                                        </span>
                                      )}
                                      <div className="bp-agenda-actions">
                                        {!isDismissed && (
                                          <button
                                            type="button"
                                            className="bp-agenda-mini-btn"
                                            title="忽略这条议题"
                                            onClick={() => businessPlan?.plan_id && patchAgendaItem(businessPlan.plan_id, it.agenda_id, { status: "dismissed" })}
                                          >
                                            忽略
                                          </button>
                                        )}
                                        {isDismissed && (
                                          <button
                                            type="button"
                                            className="bp-agenda-mini-btn"
                                            onClick={() => businessPlan?.plan_id && patchAgendaItem(businessPlan.plan_id, it.agenda_id, { status: "pending" })}
                                          >
                                            恢复
                                          </button>
                                        )}
                                      </div>
                                    </div>
                                    {expanded && (
                                      <div className="bp-agenda-detail">
                                        <div className="bp-agenda-gist">{it.gist}</div>
                                        {it.evidence_hint && (
                                          <div className="bp-agenda-evidence">
                                            <span className="bp-agenda-evidence-lbl">参考证据</span>
                                            <span>{it.evidence_hint}</span>
                                          </div>
                                        )}
                                        <div className="bp-agenda-meta-row">
                                          {it.source_message_id && (
                                            <button
                                              type="button"
                                              className="bp-agenda-jump"
                                              onClick={() => {
                                                const idx = Number(String(it.source_message_id || "").split("#")[1] || 0);
                                                const elList = document.querySelectorAll('[data-msg-index]');
                                                const target = Array.from(elList).find((el) => el.getAttribute('data-msg-index') === String(idx));
                                                if (target) (target as HTMLElement).scrollIntoView({ behavior: "smooth", block: "center" });
                                              }}
                                              title="跳到沉淀这条议题的原始对话消息"
                                            >
                                              跳原消息
                                            </button>
                                          )}
                                          {it.created_at && <span className="bp-agenda-meta">{String(it.created_at).slice(5, 16)}</span>}
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                          </div>
                          <div className="bp-agenda-foot">
                            <button
                              type="button"
                              className="bp-agenda-apply"
                              disabled={bpAgendaSelected.size === 0 || bpAgendaBusy}
                              onClick={applySelectedAgenda}
                            >
                              {bpAgendaBusy ? "应用中…" : `应用选中 · ${bpAgendaSelected.size}`}
                            </button>
                            <button
                              type="button"
                              className="bp-agenda-clear"
                              disabled={bpAgendaSelected.size === 0}
                              onClick={() => setBpAgendaSelected(new Set())}
                            >
                              清空选中
                            </button>
                            <span className="bp-agenda-foot-hint">
                              应用后自动生成待审修订，学生可逐条接受 / 拒绝。
                            </span>
                          </div>
                        </>
                      )}
                    </div>
                  )}
                  {bpError && <div className="right-card" style={{ color: "#ff8787" }}>{bpError}</div>}
                  {!businessPlan && (() => {
                    const filled = bpReadiness?.filled_core_count ?? 0;
                    const missing = bpReadiness?.missing_core_slots ?? [];
                    const suggested = bpReadiness?.suggested_questions ?? [];
                    const ready = bpReadiness ? missing.length === 0 : false;
                    const total = filled + missing.length;
                    const progress = total > 0 ? Math.round((filled / total) * 100) : 0;
                    return (
                      <div className="bp-intro-card">
                        <div className="bp-intro-head">
                          <div className="bp-intro-title-wrap">
                            <div className="bp-intro-title">还没有计划书</div>
                            <div className="bp-intro-sub">先通过下方对话补齐核心信息，系统会自动生成一份结构化草稿。</div>
                          </div>
                          <div className={`bp-intro-status ${ready ? "is-ready" : "is-wait"}`}>
                            {ready ? "已可生成" : `还差 ${missing.length} 项`}
                          </div>
                        </div>

                        {bpReadiness && total > 0 && (
                          <div className="bp-intro-progress" aria-label="核心信息完成度">
                            <div className="bp-intro-progress-bar">
                              <div className="bp-intro-progress-fill" style={{ width: `${progress}%` }} />
                            </div>
                            <div className="bp-intro-progress-label">
                              已覆盖 {filled}/{total} 个核心维度 · {progress}%
                            </div>
                          </div>
                        )}

                        <div className="bp-intro-steps">
                          <div className="bp-intro-step">
                            <span className="bp-intro-step-num">1</span>
                            <div className="bp-intro-step-body">
                              <div className="bp-intro-step-title">与项目教练对话</div>
                              <div className="bp-intro-step-desc">描述痛点、目标用户、方案与市场，系统会自动识别核心信息。</div>
                            </div>
                          </div>
                          <div className="bp-intro-step">
                            <span className="bp-intro-step-num">2</span>
                            <div className="bp-intro-step-body">
                              <div className="bp-intro-step-title">生成草稿（1 次 KB 蒸馏 + 1 次短版写作）</div>
                              <div className="bp-intro-step-desc">自动提取对话里的要点，交由多智能体链路生成 9+ 章节初稿。</div>
                            </div>
                          </div>
                          <div className="bp-intro-step">
                            <span className="bp-intro-step-num">3</span>
                            <div className="bp-intro-step-body">
                              <div className="bp-intro-step-title">按章继续深化或一键升级</div>
                              <div className="bp-intro-step-desc">每章可"继续深化"，成熟度达标后可升级为基础版 / 正式版。</div>
                            </div>
                          </div>
                        </div>

                        <div className="bp-intro-modes">
                          <div className="bp-intro-mode">
                            <span className="bp-intro-mode-dot is-project" />
                            <div>
                              <div className="bp-intro-mode-title">项目教练</div>
                              <div className="bp-intro-mode-desc">按章节完整度节奏引导、补齐骨架与证据。</div>
                            </div>
                          </div>
                          <div className="bp-intro-mode">
                            <span className="bp-intro-mode-dot is-competition" />
                            <div>
                              <div className="bp-intro-mode-title">竞赛教练</div>
                              <div className="bp-intro-mode-desc">顶栏切到"竞赛冲刺"即自动进入，以评委视角追问、产出议题板。</div>
                            </div>
                          </div>
                        </div>

                        {missing.length > 0 && (
                          <div className="bp-intro-missing">
                            <div className="bp-intro-section-title">还需补齐</div>
                            <div className="bp-intro-chip-row">
                              {missing.map((item: string) => (
                                <span key={item} className="bp-intro-chip">{item}</span>
                              ))}
                            </div>
                          </div>
                        )}

                        {suggested.length > 0 && (
                          <div className="bp-intro-suggest">
                            <div className="bp-intro-section-title">下一句可以说</div>
                            <div className="bp-intro-suggest-list">
                              {suggested.slice(0, 4).map((q: string, idx: number) => (
                                <button
                                  key={idx}
                                  type="button"
                                  className="bp-intro-suggest-item"
                                  onClick={() => {
                                    setInput(q);
                                    setTimeout(() => {
                                      textareaRef.current?.focus();
                                      textareaRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
                                    }, 80);
                                  }}
                                  title="点击填入下方对话输入框"
                                >
                                  {q}
                                </button>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })()}
                  {businessPlan && (() => {
                    const sections = businessPlan.sections ?? [];
                    const pendingRevs = businessPlan.pending_revisions ?? [];
                    const revisionIdSet = new Set(pendingRevs.map((r) => r.section_id));
                    const levelColor = (lv?: string) =>
                      lv === "complete" ? "#51cf66"
                        : lv === "mostly_complete" ? "#74c0fc"
                        : lv === "partial" ? "#ffa94d"
                        : "#ff6b6b";
                    const isPlaceholder = (section: BpSection) => {
                      const text = (section.user_edit || section.content || "").trim();
                      if (section.missing_level === "critical" && text.length < 120) return true;
                      return false;
                    };
                    const isAiStub = (section: BpSection) => !!section.is_ai_stub && !isPlaceholder(section);
                    const scrollToSection = (sid: string) => {
                      setBpSelectedSectionId(sid);
                      const section = sections.find((s) => s.section_id === sid);
                      if (section) setBpEditorContent(section.user_edit || section.content || "");
                      if (bpViewMode === "read") {
                        const el = bpSectionRefs.current[sid];
                        if (el) {
                          el.scrollIntoView({ behavior: "smooth", block: "start" });
                        }
                      }
                    };
                    const activeId = activeBpSectionId || selectedBpSection?.section_id;
                    return (
                      <>
                        {/* ═ 右浮大纲（仅阅读模式，默认收起手柄式） ═ */}
                        {bpViewMode === "read" && (
                          <aside
                            className={`bp-right-outline ${bpOutlineOpen ? "is-open" : ""} ${bpOutlinePinned ? "is-pinned" : ""}`}
                            aria-label="章节大纲"
                            onMouseEnter={() => {
                              if (bpOutlineHoverTimer.current) { clearTimeout(bpOutlineHoverTimer.current); bpOutlineHoverTimer.current = null; }
                              setBpOutlineOpen(true);
                            }}
                            onMouseLeave={() => {
                              if (bpOutlinePinned) return;
                              if (bpOutlineHoverTimer.current) clearTimeout(bpOutlineHoverTimer.current);
                              bpOutlineHoverTimer.current = setTimeout(() => setBpOutlineOpen(false), 400);
                            }}
                          >
                            <button
                              className="bp-ro-handle"
                              onClick={() => setBpOutlineOpen((v) => !v)}
                              title={bpOutlineOpen ? "收起目录（Ctrl+/）" : "展开目录（Ctrl+/）"}
                              aria-label="切换目录"
                            >
                              <span className="bp-ro-handle-text">目 录</span>
                              <span className="bp-ro-handle-arrow">{bpOutlineOpen ? "›" : "‹"}</span>
                            </button>
                            <div className="bp-ro-head">
                              <span className="bp-ro-title">章节目录</span>
                              <button
                                className={`bp-ro-pin ${bpOutlinePinned ? "is-on" : ""}`}
                                onClick={() => setBpOutlinePinned((v) => !v)}
                                title={bpOutlinePinned ? "取消固定（再次悬停可收起）" : "固定显示（不自动收起）"}
                              >📌</button>
                              <button className="bp-ro-expand" onClick={() => setBpDrawerOpen(true)} title="展开完整目录">⤢</button>
                            </div>
                            <div className="bp-ro-list">
                              {sections.map((section, idx) => {
                                const active = section.section_id === activeId;
                                const hasRevision = revisionIdSet.has(section.section_id);
                                return (
                                  <button
                                    key={section.section_id}
                                    className={`bp-ro-item ${active ? "is-active" : ""} ${isPlaceholder(section) ? "is-placeholder" : ""} ${isAiStub(section) ? "is-aistub" : ""}`}
                                    onClick={() => scrollToSection(section.section_id)}
                                    title={section.display_title || section.title}
                                  >
                                    <span className="bp-ro-num">{String(idx + 1).padStart(2, "0")}</span>
                                    <span className="bp-ro-text">{section.display_title || section.title}</span>
                                    <span className="bp-ro-dot" style={{ background: levelColor(section.missing_level) }} />
                                    {hasRevision && <span className="bp-ro-rev" />}
                                  </button>
                                );
                              })}
                            </div>
                          </aside>
                        )}

                        {bpViewMode === "read" && (
                          <div className="bp-progress" aria-hidden>
                            <div className="bp-progress-fill" style={{ width: `${Math.round(bpScrollProgress * 100)}%` }} />
                          </div>
                        )}

                        <div className={`bp-mode-fade bp-mode-${bpViewMode}`} key={bpViewMode}>
                          {bpViewMode === "read" ? (
                            <div
                              ref={bpReadRootRef}
                              className="right-card bp-read-root"
                              style={{
                                padding: "32px 40px",
                                maxHeight: "calc(100vh - 200px)",
                                overflowY: "auto",
                                lineHeight: 1.9,
                              }}
                            >
                              {(() => {
                                const realTitle = businessPlan.cover_info?.project_name || businessPlan.title;
                                if (realTitle) {
                                  return (
                                    <div
                                      style={{
                                        textAlign: "center",
                                        padding: "28px 0 30px",
                                        borderBottom: "1px dashed rgba(255,255,255,0.15)",
                                        marginBottom: 28,
                                      }}
                                    >
                                      <div style={{ fontSize: 12, color: "var(--text-muted, #9aa3b2)", letterSpacing: 3, marginBottom: 10 }}>BUSINESS PLAN</div>
                                      <div className="bp-cover-title">{realTitle}</div>
                                      <div style={{ fontSize: 13, color: "var(--text-muted, #9aa3b2)", display: "flex", gap: 16, justifyContent: "center", flexWrap: "wrap", marginTop: 12 }}>
                                        <span>负责人：{businessPlan.cover_info?.student_or_team || currentUser?.display_name || "—"}</span>
                                        {classId && <span>班级：{classId}</span>}
                                        <span>日期：{businessPlan.cover_info?.date || new Date().toISOString().slice(0, 10)}</span>
                                        {(() => {
                                          const lid = currentLogicalProjectId;
                                          if (!lid) return null;
                                          const isStd = /^P-[A-Za-z0-9_-]+-\d{2,}$/.test(lid);
                                          return (
                                            <span title={isStd ? "规范项目编号" : "历史会话编号"}>
                                              项目编号：<code style={{ color: isStd ? "#a78bfa" : "#9aa3b2", fontFamily: "ui-monospace, SF Mono, Menlo, monospace" }}>{isStd ? lid : `#${lid.slice(0, 8)}`}</code>
                                            </span>
                                          );
                                        })()}
                                      </div>
                                    </div>
                                  );
                                }
                                return (
                                  <div className="bp-cover-ghost">
                                    <svg viewBox="0 0 48 48" width="48" height="48" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" className="bp-cg-icon">
                                      <path d="M12 8h18a4 4 0 014 4v26a2 2 0 01-2 2H14a4 4 0 01-4-4V10a2 2 0 012-2z" />
                                      <path d="M18 16h14M18 22h14M18 28h10" />
                                      <path d="M10 12v24" opacity="0.5" />
                                    </svg>
                                    <div className="bp-cg-eyebrow">BUSINESS PLAN</div>
                                    <div className="bp-cg-text">尚未生成封面 · 先和教练对话几轮即可</div>
                                  </div>
                                );
                              })()}

                              <div style={{ marginBottom: 32 }}>
                                <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 12 }}>目录</div>
                                <ol style={{ paddingLeft: 22, margin: 0, display: "grid", gap: 6 }}>
                                  {sections.map((section) => (
                                    <li key={section.section_id}>
                                      <a
                                        href={`#bp-sec-${section.section_id}`}
                                        onClick={(e) => {
                                          e.preventDefault();
                                          scrollToSection(section.section_id);
                                        }}
                                        style={{ color: "inherit", textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 8 }}
                                      >
                                        <span>{section.display_title || section.title}</span>
                                        {section.missing_level && section.missing_level !== "complete" && section.missing_level !== "mostly_complete" && (
                                          <span className="tch-tag" style={{ fontSize: 11 }}>{section.status || "待完善"}</span>
                                        )}
                                      </a>
                                    </li>
                                  ))}
                                </ol>
                              </div>

                              {(sections[0]?.narrative_opening) && (
                                <div style={{ padding: "16px 20px", borderLeft: "3px solid rgba(107,138,255,0.6)", background: "rgba(107,138,255,0.06)", borderRadius: 6, marginBottom: 30, color: "var(--text-muted, #9aa3b2)", fontSize: 14, lineHeight: 1.8 }}>
                                  {sections[0].narrative_opening}
                                </div>
                              )}

                              {sections.map((section, idx) => {
                                const placeholder = isPlaceholder(section);
                                const aiStub = isAiStub(section);
                                return (
                                  <section
                                    key={section.section_id}
                                    id={`bp-sec-${section.section_id}`}
                                    ref={(el) => { bpSectionRefs.current[section.section_id] = el; }}
                                    data-section-id={section.section_id}
                                    className={`bp-section ${placeholder ? "bp-section-placeholder" : ""} ${aiStub ? "bp-section-aistub" : ""}`}
                                    style={{ marginBottom: 36, scrollMarginTop: 16 }}
                                  >
                                    <h2 style={{ fontSize: 18, fontWeight: 700, margin: "0 0 12px", display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                                      <span className="bp-chap-num">{String(idx + 1).padStart(2, "0")}</span>
                                      <span>{section.display_title || section.title}</span>
                                      {placeholder && <span className="bp-badge-placeholder">待补充</span>}
                                      {aiStub && <span className="bp-badge-aistub">AI 参考稿</span>}
                                    </h2>
                                    {aiStub && (
                                      <div className="bp-aistub-hint">本章尚未收集到用户素材，以下为基于行业通用框架生成的参考稿，建议团队校准事实后再定稿。</div>
                                    )}
                                    <div style={{ fontSize: 14 }}>
                                      {(() => {
                                        const body = section.user_edit || section.content || "";
                                        if (body.trim()) {
                                          return <MarkdownContent content={body} theme={theme} />;
                                        }
                                        return (
                                          <div className="bp-section-skeleton" aria-label="本章待补全">
                                            <span className="bp-sk-line" style={{ width: "92%" }} />
                                            <span className="bp-sk-line" style={{ width: "78%" }} />
                                            <span className="bp-sk-line" style={{ width: "64%" }} />
                                            <div className="bp-sk-hint">向教练追问即可自动补全本章</div>
                                          </div>
                                        );
                                      })()}
                                    </div>
                                    {!!section.missing_points?.length && (
                                      <div style={{ marginTop: 12, padding: "8px 12px", background: "rgba(255,169,77,0.08)", borderRadius: 8, fontSize: 12.5, color: "#ffa94d" }}>
                                        本章仍需补充：{section.missing_points.join("、")}
                                      </div>
                                    )}
                                    <div className="bp-section-actions">
                                      <button
                                        className="bp-deepen-btn"
                                        onClick={() => openDeepenDialog(section.section_id)}
                                      >
                                        继续深化本章
                                      </button>
                                    </div>
                                  </section>
                                );
                              })}

                              {pendingRevs.length > 0 && (
                                <div style={{ marginTop: 16, padding: "10px 14px", background: "rgba(255,212,59,0.08)", borderRadius: 8, fontSize: 13, color: "#ffd43b" }}>
                                  当前有 {pendingRevs.length} 条 AI 修订建议待处理，切换到编辑模式后在对应章节查看并确认。
                                </div>
                              )}
                            </div>
                          ) : (
                            selectedBpSection ? (
                              <div className="bp-edit-root" key={selectedBpSection.section_id}>
                                <div className="right-card">
                                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", marginBottom: 8 }}>
                                    <strong>{selectedBpSection.display_title || selectedBpSection.title}</strong>
                                    <span className="msg-time">{selectedBpSection.status || "部分缺失"} · 置信度 {Math.round((selectedBpSection.confidence || 0) * 100)}%</span>
                                  </div>
                                  {!!selectedBpSection.missing_points?.length && (
                                    <div className="tch-tag-row" style={{ marginBottom: 10 }}>
                                      {selectedBpSection.missing_points.map((item) => <span key={item} className="tch-tag">{item}</span>)}
                                    </div>
                                  )}
                                  <textarea
                                    value={bpEditorContent}
                                    onChange={(e) => setBpEditorContent(e.target.value)}
                                    style={{
                                      width: "100%",
                                      minHeight: 360,
                                      resize: "vertical",
                                      borderRadius: 12,
                                      border: "1px solid rgba(255,255,255,0.12)",
                                      background: "rgba(255,255,255,0.04)",
                                      color: "inherit",
                                      padding: 14,
                                      fontSize: 14,
                                      lineHeight: 1.75,
                                      fontFamily: "inherit",
                                    }}
                                  />
                                  <div className="msg-time" style={{ marginTop: 8 }}>
                                    {bpSaving ? "正在保存..." : "支持 Markdown 语法，保存后在阅读模式即可看到润色后的展示效果。"}
                                  </div>
                                </div>

                                {!!selectedBpSection.field_map && Object.keys(selectedBpSection.field_map).length > 0 && (
                                  <div className="right-card" style={{ marginTop: 12 }}>
                                    <strong>字段线索</strong>
                                    <div style={{ marginTop: 8, display: "grid", gap: 8 }}>
                                      {Object.entries(selectedBpSection.field_map).slice(0, 8).map(([key, value]) => (
                                        <div key={key}>
                                          <div className="msg-time">{key}</div>
                                          <div style={{ marginTop: 2, whiteSpace: "pre-wrap" }}>{typeof value === "string" ? value : JSON.stringify(value)}</div>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                )}

                                {(() => {
                                  const revision = pendingRevs.find((item) => item.section_id === selectedBpSection.section_id);
                                  if (!revision) return null;
                                  const changes = revision.changes ?? [];
                                  const shown = changes.slice(0, 80);
                                  return (
                                    <details className="bp-revision-card" style={{ marginTop: 12 }} open>
                                      <summary className="bp-revision-head">
                                        <span className="bp-revision-title">{revision.summary || "本章修订建议"}</span>
                                        <span className="bp-revision-reason">{revision.reason}</span>
                                        <span className="bp-revision-actions">
                                          <button className="tch-sm-btn" onClick={() => handleBpRevision(businessPlan.plan_id, revision.revision_id, "accept")} disabled={bpSaving}>接受</button>
                                          <button className="tch-sm-btn" onClick={() => handleBpRevision(businessPlan.plan_id, revision.revision_id, "reject")} disabled={bpSaving}>忽略</button>
                                        </span>
                                      </summary>
                                      {revision.source_hint && <div className="msg-time" style={{ marginBottom: 8 }}>{revision.source_hint}</div>}
                                      <div className="bp-diff-body">
                                        {shown.map((item, idx) => (
                                          <div
                                            key={idx}
                                            className={`bp-diff-line bp-diff-${item.kind === "add" ? "add" : item.kind === "remove" ? "remove" : "equal"}`}
                                          >
                                            <span className="bp-diff-sign">
                                              {item.kind === "add" ? "+" : item.kind === "remove" ? "−" : " "}
                                            </span>
                                            <span className="bp-diff-text">{item.text || " "}</span>
                                          </div>
                                        ))}
                                        {changes.length > shown.length && (
                                          <div className="bp-diff-line bp-diff-equal bp-diff-more">
                                            …还有 {changes.length - shown.length} 行差异未展示，接受后即可在正文看到完整内容
                                          </div>
                                        )}
                                      </div>
                                    </details>
                                  );
                                })()}
                              </div>
                            ) : (
                              <p className="right-hint">先在顶部选择章节，或返回阅读模式浏览整篇计划书。</p>
                            )
                          )}
                        </div>

                        {bpSuggestDrawerOpen && (
                          <>
                            <div className="bp-drawer-mask" onClick={() => setBpSuggestDrawerOpen(false)} />
                            <aside className="bp-drawer bp-drawer-suggest" role="dialog" aria-label="补充建议">
                              <div className="bp-drawer-head">
                                <strong>补充建议（按优先级）</strong>
                                <button className="bp-drawer-close" onClick={() => setBpSuggestDrawerOpen(false)} aria-label="关闭">×</button>
                              </div>
                              <div className="bp-drawer-body">
                                {bpSuggestLoading ? (
                                  <div className="bp-drawer-empty">正在生成建议…</div>
                                ) : bpSuggestions.length === 0 ? (
                                  <div className="bp-drawer-empty">暂无优先级较高的补充建议，计划书已经比较完整。</div>
                                ) : (
                                  bpSuggestions.map((item) => (
                                    <button
                                      key={`${item.section_id}-${item.priority}`}
                                      className="bp-suggest-item"
                                      onClick={() => {
                                        setBpSuggestDrawerOpen(false);
                                        openDeepenDialog(item.section_id);
                                      }}
                                    >
                                      <div className="bp-suggest-head">
                                        <span className="bp-suggest-title">{item.section_title}</span>
                                        <span className="bp-suggest-pri">优先级 {item.priority}</span>
                                      </div>
                                      <div className="bp-suggest-q">{item.question}</div>
                                      {item.why && <div className="bp-suggest-why">{item.why}</div>}
                                    </button>
                                  ))
                                )}
                              </div>
                            </aside>
                          </>
                        )}

                        {bpSnapshotOpen && (
                          <>
                            <div className="bp-dialog-mask" onClick={() => setBpSnapshotOpen(false)} />
                            <div className="bp-dialog bp-dialog-snapshots" role="dialog" aria-label="版本历史">
                              <div className="bp-dialog-head">
                                <strong>版本历史</strong>
                                <button className="bp-dialog-close" onClick={() => setBpSnapshotOpen(false)} aria-label="关闭">×</button>
                              </div>
                              <div className="bp-dialog-body">
                                {bpSnapshotLoading ? (
                                  <div className="bp-dialog-hint">读取快照中…</div>
                                ) : bpSnapshots.length === 0 ? (
                                  <div className="bp-dialog-hint">暂无已保存的版本。可在 FAB 菜单使用「保存当前版本」手动存档。</div>
                                ) : (
                                  <div className="bp-snap-list">
                                    {bpSnapshots.map((snap: any) => (
                                      <div key={snap.snap_id} className="bp-snap-row">
                                        <div className="bp-snap-main">
                                          <div className="bp-snap-label">{snap.label || "（无标注）"}</div>
                                          <div className="bp-snap-meta">
                                            {snap.created_at ? String(snap.created_at).slice(0, 19).replace("T", " ") : "-"}
                                            <span className="bp-snap-sep">·</span>
                                            {snap.section_count ?? 0} 章
                                            <span className="bp-snap-sep">·</span>
                                            {(snap.word_count ?? 0).toLocaleString()} 字
                                            {snap.version_tier && (
                                              <><span className="bp-snap-sep">·</span>{snap.version_tier === "full" ? "正式版" : snap.version_tier === "basic" ? "基础版" : "草稿"}</>
                                            )}
                                          </div>
                                        </div>
                                        <div className="bp-snap-actions">
                                          <button
                                            className="tch-sm-btn"
                                            onClick={() => rollbackToSnapshot(snap.snap_id)}
                                          >回滚到此版本</button>
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                )}
                                <div className="bp-snap-tip">回滚前系统会自动保存当前内容的兜底快照，最多保留 50 条。</div>
                              </div>
                              <div className="bp-dialog-foot">
                                <button className="tch-sm-btn" onClick={() => setBpSnapshotOpen(false)}>关闭</button>
                              </div>
                            </div>
                          </>
                        )}

                        {bpCommentsOpen && (
                          <>
                            <div className="bp-dialog-mask" onClick={() => setBpCommentsOpen(false)} />
                            <div className="bp-dialog bp-dialog-comments" role="dialog" aria-label="教师建议">
                              <div className="bp-dialog-head">
                                <strong>教师建议与批注</strong>
                                <button className="bp-dialog-close" onClick={() => setBpCommentsOpen(false)} aria-label="关闭">×</button>
                              </div>
                              <div className="bp-dialog-body">
                                {bpTeacherComments.length === 0 ? (
                                  <div className="bp-dialog-hint">教师尚未留下批注。</div>
                                ) : (
                                  <div className="bp-tch-list">
                                    {sections.map((sec) => {
                                      const list = bpTeacherComments.filter((c: any) => c.section_id === sec.section_id);
                                      if (!list.length) return null;
                                      return (
                                        <div key={sec.section_id} className="bp-tch-group">
                                          <div className="bp-tch-group-title">
                                            <button
                                              type="button"
                                              className="bp-tch-group-jump"
                                              onClick={() => {
                                                setBpCommentsOpen(false);
                                                const el = bpSectionRefs.current[sec.section_id];
                                                if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
                                              }}
                                            >{sec.display_title || sec.title}</button>
                                          </div>
                                          {list.map((c: any) => {
                                            const label = c.annotation_type === "issue" ? "问题" : c.annotation_type === "praise" ? "肯定" : "建议";
                                            return (
                                              <div key={c.comment_id} className={`bp-tch-card type-${c.annotation_type} ${c.status === "resolved" ? "resolved" : ""}`}>
                                                <div className="bp-tch-card-head">
                                                  <span className={`bp-tch-card-tag tag-${c.annotation_type}`}>{label}</span>
                                                  <span className="bp-tch-card-author">{c.teacher_name || c.teacher_id || "老师"}</span>
                                                  <span className="bp-tch-card-time">{String(c.created_at || "").slice(5, 16).replace("T", " ")}</span>
                                                </div>
                                                {c.quote && (
                                                  <blockquote className="bp-tch-card-quote">"{String(c.quote).slice(0, 80)}{String(c.quote).length > 80 ? "…" : ""}"</blockquote>
                                                )}
                                                <div className="bp-tch-card-content">{c.content}</div>
                                              </div>
                                            );
                                          })}
                                        </div>
                                      );
                                    })}
                                  </div>
                                )}
                              </div>
                              <div className="bp-dialog-foot">
                                <button className="tch-sm-btn" onClick={() => setBpCommentsOpen(false)}>关闭</button>
                              </div>
                            </div>
                          </>
                        )}

                        {bpDeepenSectionId && (
                          <>
                            <div className="bp-dialog-mask" onClick={() => (!bpDeepenSubmitting ? closeDeepenDialog() : null)} />
                            <div className="bp-dialog" role="dialog" aria-label="继续深化本章">
                              <div className="bp-dialog-head">
                                <strong>继续深化本章</strong>
                                <button className="bp-dialog-close" onClick={closeDeepenDialog} disabled={bpDeepenSubmitting} aria-label="关闭">×</button>
                              </div>
                              <div className="bp-dialog-body">
                                <div className="bp-dialog-subtitle">
                                  {sections.find((s) => s.section_id === bpDeepenSectionId)?.display_title || "本章"}
                                </div>
                                {bpDeepenLoading ? (
                                  <div className="bp-dialog-hint">AI 正在基于项目知识库生成针对性问题…</div>
                                ) : bpDeepenQuestions.length === 0 ? (
                                  <div className="bp-dialog-hint">暂未生成深化问题，请稍后重试。</div>
                                ) : (
                                  <div className="bp-dialog-questions">
                                    {bpDeepenQuestions.map((q, idx) => (
                                      <div key={q.id} className="bp-dialog-qitem">
                                        <div className="bp-dialog-qlabel">
                                          <span className="bp-dialog-qnum">Q{idx + 1}</span>
                                          <span>{q.text}</span>
                                        </div>
                                        {q.focus_point && <div className="bp-dialog-qfocus">关注点：{q.focus_point}</div>}
                                        <textarea
                                          value={bpDeepenAnswers[q.id] || ""}
                                          onChange={(e) => setBpDeepenAnswers((m) => ({ ...m, [q.id]: e.target.value }))}
                                          placeholder="在此输入你的补充…（可留空跳过）"
                                          className="bp-dialog-qinput"
                                        />
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                              <div className="bp-dialog-foot">
                                <button className="tch-sm-btn" onClick={closeDeepenDialog} disabled={bpDeepenSubmitting}>取消</button>
                                <button
                                  className="tch-sm-btn bp-btn-primary"
                                  onClick={submitDeepenAnswers}
                                  disabled={bpDeepenSubmitting || bpDeepenQuestions.length === 0}
                                >
                                  {bpDeepenSubmitting ? "扩写中…" : "提交并扩写本章"}
                                </button>
                              </div>
                            </div>
                          </>
                        )}

                        {bpDrawerOpen && (
                          <>
                            <div className="bp-drawer-mask" onClick={() => setBpDrawerOpen(false)} />
                            <aside className="bp-drawer" role="dialog" aria-label="商业计划书目录">
                              <div className="bp-drawer-head">
                                <strong>完整目录</strong>
                                <button className="bp-drawer-close" onClick={() => setBpDrawerOpen(false)} aria-label="关闭">×</button>
                              </div>
                              <div className="bp-drawer-body">
                                {sections.map((section, idx) => {
                                  const hasRevision = revisionIdSet.has(section.section_id);
                                  const active = section.section_id === activeId;
                                  return (
                                    <button
                                      key={section.section_id}
                                      className={`bp-drawer-item ${active ? "is-active" : ""} ${isPlaceholder(section) ? "is-placeholder" : ""} ${isAiStub(section) ? "is-aistub" : ""}`}
                                      onClick={() => {
                                        scrollToSection(section.section_id);
                                        setBpDrawerOpen(false);
                                      }}
                                    >
                                      <div className="bp-drawer-row-top">
                                        <span className="bp-drawer-num">{String(idx + 1).padStart(2, "0")}</span>
                                        <span className="bp-drawer-title">{section.display_title || section.title}</span>
                                        <span className="bp-pill-dot" style={{ background: levelColor(section.missing_level) }} />
                                        {hasRevision && <span className="bp-pill-rev" style={{ marginLeft: 2 }} />}
                                      </div>
                                      <div className="bp-drawer-row-meta">
                                        <span>{section.status || "部分缺失"}</span>
                                        <span>· 置信度 {Math.round((section.confidence || 0) * 100)}%</span>
                                      </div>
                                      {!!section.missing_points?.length && (
                                        <div className="bp-drawer-tags">
                                          {section.missing_points.slice(0, 4).map((m) => (
                                            <span key={m} className="bp-drawer-tag">{m}</span>
                                          ))}
                                        </div>
                                      )}
                                    </button>
                                  );
                                })}
                                {pendingRevs.length > 0 && (
                                  <div className="bp-drawer-revnote">
                                    共 {pendingRevs.length} 条待处理修订
                                  </div>
                                )}
                              </div>
                            </aside>
                          </>
                        )}
                      </>
                    );
                  })()}
                </div>
              )}

              {rightTab === "risk" && (
                <>
                  <div className="panel-desc">基于23条风险规则库，检测你描述中的隐患并给出修复建议。风险跨轮次累积追踪。</div>
                  {triggeredRules.length > 0 ? (
                    <div className="right-section">
                      {(() => {
                        const active = triggeredRules.filter((r: any) => !r.resolved);
                        const resolved = triggeredRules.filter((r: any) => r.resolved);
                        const high = active.filter((r: any) => r.severity === "high").length;
                        const med = active.filter((r: any) => r.severity === "medium").length;
                        const low = active.filter((r: any) => r.severity === "low").length;
                        const total = active.length;
                        const healthScore = total === 0 ? 100 : Math.max(10, Math.round(100 - high * 12 - med * 5 - low * 2));
                        const circumference = 2 * Math.PI * 32;
                        const strokeDashoffset = circumference * (1 - healthScore / 100);
                        const healthColor = healthScore >= 70 ? "#22c55e" : healthScore >= 40 ? "#f59e0b" : "#ef4444";
                        return (
                          <div className="risk-summary-bar">
                            <div className="risk-health-row">
                              <svg width="80" height="80" viewBox="0 0 80 80" className="risk-health-ring">
                                <circle cx="40" cy="40" r="32" fill="none" stroke="var(--border)" strokeWidth="6" />
                                <circle cx="40" cy="40" r="32" fill="none" stroke={healthColor} strokeWidth="6"
                                  strokeDasharray={circumference} strokeDashoffset={strokeDashoffset}
                                  strokeLinecap="round" transform="rotate(-90 40 40)" style={{ transition: "stroke-dashoffset 0.6s ease" }} />
                                <text x="40" y="44" textAnchor="middle" fontSize="16" fontWeight="700" fill={healthColor}>{healthScore}</text>
                              </svg>
                              <div className="risk-health-meta">
                            <div className="risk-summary-stats">
                              <span className="risk-stat high">{high} 高危</span>
                              <span className="risk-stat medium">{med} 中等</span>
                              <span className="risk-stat low">{low} 轻微</span>
                                  {resolved.length > 0 && <span className="risk-stat resolved">{resolved.length} 已解决</span>}
                            </div>
                            <div className="risk-dist-track">
                                  {high > 0 && <div className="risk-dist-seg high" style={{ width: `${(high / Math.max(total, 1)) * 100}%` }} />}
                                  {med > 0 && <div className="risk-dist-seg medium" style={{ width: `${(med / Math.max(total, 1)) * 100}%` }} />}
                                  {low > 0 && <div className="risk-dist-seg low" style={{ width: `${(low / Math.max(total, 1)) * 100}%` }} />}
                                </div>
                              </div>
                            </div>
                          </div>
                        );
                      })()}
                      {triggeredRules.map((r: any) => {
                        return (
                          <details key={r.id} className={`risk-detail-card ${r.severity}${r.resolved ? " resolved" : ""}`}>
                          <summary className="risk-detail-header">
                            <span className="risk-id">{r.id}</span>
                            <span className="risk-name">{r.name}</span>
                              <span className={`risk-badge ${r.resolved ? "resolved" : r.severity}`}>
                                {r.resolved ? "已解决" : ({ high: "高危", medium: "中等", low: "轻微" } as Record<string, string>)[r.severity] ?? r.severity}
                              </span>
                              {r.turnCount > 1 && !r.resolved && <span className="risk-repeat-badge">持续{r.turnCount}轮</span>}
                          </summary>
                          <div className="risk-detail-body">
                            {r.explanation && <p className="risk-explanation">{r.explanation}</p>}
                              {r.quote && (
                                <div className="risk-quote-block">
                                  <span className="risk-field-label">触发原文：</span>
                                  <blockquote className="risk-quote">{r.quote}</blockquote>
                                </div>
                              )}
                              {r.impact && (
                                <div className="risk-impact">
                                  <span className="risk-field-label">如不处理：</span>
                                  <p>{r.impact}</p>
                                </div>
                              )}
                            {(r.matched_keywords ?? []).length > 0 && (
                              <div className="risk-matched">
                                <span className="risk-field-label">触发关键词：</span>
                                {r.matched_keywords.map((k: string, ki: number) => <span key={ki} className="risk-kw-chip triggered">{k}</span>)}
                              </div>
                            )}
                            {(r.missing_requires ?? []).length > 0 && (
                              <div className="risk-matched">
                                <span className="risk-field-label">缺失要素：</span>
                                {r.missing_requires.map((k: string, ki: number) => <span key={ki} className="risk-kw-chip missing">{k}</span>)}
                              </div>
                            )}
                            {r.fix_hint && (
                              <div className="risk-fix">
                                <span className="risk-field-label">修复建议：</span>
                                <p>{r.fix_hint}</p>
                              </div>
                            )}
                              {r.linked_task?.title && (
                                <div className="risk-linked-task">
                                  <span className="risk-field-label">修复行动：</span>
                                  <strong>{r.linked_task.title}</strong>
                                  <p>{r.linked_task.description}</p>
                                  {(r.linked_task.acceptance_criteria ?? []).length > 0 && (
                                    <div className="risk-lt-accept">验收：{r.linked_task.acceptance_criteria.join("；")}</div>
                                  )}
                                </div>
                              )}
                              {r.competition_context && (
                                <div className="risk-competition-ctx">
                                  <span className="risk-field-label">赛事参考：</span>
                                  <p>{r.competition_context}</p>
                                </div>
                              )}
                              {(r.inference_chain?.length || r.agent_name || r.score_impact != null) && (
                                <details className="tch-conclusion" style={{ marginTop: 10 }}>
                                  <summary>查看推理链 · {r.agent_name || "综合诊断 Agent"}{r.score_impact != null ? ` · 扣分 ${r.score_impact.toFixed(2)}` : ""}</summary>
                                  <div className="tch-conclusion-body">
                                    {(r.inference_chain || []).map((step: any, si: number) => (
                                      <div key={si} style={{ padding: "6px 10px", marginBottom: 6, background: "rgba(255,255,255,0.03)", borderLeft: "2px solid rgba(139,127,216,0.4)", borderRadius: "0 6px 6px 0", fontSize: 12, lineHeight: 1.55 }}>
                                        <span style={{ display: "inline-block", minWidth: 80, color: "#a78bfa", fontWeight: 600, fontFamily: "ui-monospace, monospace", fontSize: 10.5, letterSpacing: "0.04em", textTransform: "uppercase" }}>{step.step}</span>
                                        <span style={{ color: "#cbd5e1" }}>
                                          {step.detail || step.rule_name || step.text || (step.keywords || []).join("、") || (step.missing || []).join("、") || ""}
                                        </span>
                                      </div>
                                    ))}
                                  </div>
                                </details>
                              )}
                          </div>
                        </details>
                        );
                      })}
                    </div>
                  ) : <p className="right-hint">暂无风险命中——描述越详细，风险检测越准确</p>}
                </>
              )}

              {rightTab === "score" && (
                <div className="right-section sc-panel">
                  {rubric.length > 0 ? (() => {
                    const total = overallScore ?? 0;
                    const totalColor = total >= 7 ? "var(--accent-green,#22c55e)" : total >= 4 ? "var(--accent-yellow,#f59e0b)" : "var(--accent-red,#ef4444)";
                    const circumf = 2 * Math.PI * 42;
                    const offset = circumf * (1 - total / 10);
                        const n = rubric.length;
                    const cx = 120, cy = 120, R = 95;
                        const angleStep = (2 * Math.PI) / n;
                        const pt = (i: number, r: number) => {
                          const a = -Math.PI / 2 + i * angleStep;
                          return [cx + R * r * Math.cos(a), cy + R * r * Math.sin(a)];
                        };
                        const dataPoints = rubric.map((r: any, i: number) => pt(i, Math.min(1, r.score / 10)));
                        const polygon = dataPoints.map(([x, y]: number[]) => `${x},${y}`).join(" ");
                    const highDims = rubric.filter((r: any) => r.score >= 7);
                    const lowDims = rubric.filter((r: any) => r.score < 4);
                        return (
                      <>
                        {/* Hero: Ring + Meta */}
                        <div className="sc-hero">
                          <div className="sc-hero-ring-wrap">
                            <svg width="104" height="104" viewBox="0 0 104 104">
                              <circle cx="52" cy="52" r="42" fill="none" stroke="var(--border)" strokeWidth="8" />
                              <circle cx="52" cy="52" r="42" fill="none" stroke={totalColor} strokeWidth="8"
                                strokeDasharray={circumf} strokeDashoffset={offset}
                                strokeLinecap="round" transform="rotate(-90 52 52)" style={{transition:"stroke-dashoffset .5s ease"}} />
                              <text x="52" y="48" textAnchor="middle" fontSize="24" fontWeight="800" fill={totalColor}>{total}</text>
                              <text x="52" y="64" textAnchor="middle" fontSize="10" fill="var(--text-muted)">/10</text>
                            </svg>
                          </div>
                          <div className="sc-hero-meta">
                            {projectStageLabel && <span className="sc-meta-chip">{projectStageLabel}</span>}
                            {scoreBand && <span className="sc-meta-chip">{scoreBand}</span>}
                            {resultHistory.length >= 2 && (
                              <span
                                className="sc-meta-chip muted"
                                title="为避免单轮抖动，单项分数与综合分均以最近 3 轮加权平均（权重 0.5 / 0.3 / 0.2，最新轮最大）。后端诊断本身基于项目累积语料。"
                              >
                                最近 3 轮加权 · 0.5/0.3/0.2
                              </span>
                            )}
                            {highDims.length > 0 && <div className="sc-meta-row"><span className="sc-meta-good">{highDims.length} 项达标</span></div>}
                            {lowDims.length > 0 && <div className="sc-meta-row"><span className="sc-meta-warn">{lowDims.length} 项需补强</span></div>}
                          </div>
                        </div>

                        {/* Radar */}
                        <div className="sc-radar-wrap">
                          <svg viewBox="0 0 240 240" className="sc-radar-svg">
                            {[0.25, 0.5, 0.75, 1.0].map(t => (
                              <polygon key={t} points={Array.from({length: n}, (_, i) => pt(i, t)).map(([x, y]: number[]) => `${x},${y}`).join(" ")} fill="none" stroke="var(--border)" strokeWidth="0.5" opacity={t === 1 ? 0.6 : 0.3} />
                            ))}
                            {rubric.map((_: any, i: number) => {
                              const [ex, ey] = pt(i, 1);
                              return <line key={i} x1={cx} y1={cy} x2={ex} y2={ey} stroke="var(--border)" strokeWidth="0.3" strokeDasharray="2 2" />;
                            })}
                            <polygon points={polygon} fill="rgba(99,102,241,.15)" stroke="#6366f1" strokeWidth="1.5" />
                            {dataPoints.map(([x, y]: number[], i: number) => (
                              <circle key={i} cx={x} cy={y} r="3" fill="#6366f1" stroke="#fff" strokeWidth="1" />
                            ))}
                            {rubric.map((r: any, i: number) => {
                              const [lx, ly] = pt(i, 1.18);
                              const sc = r.score;
                              const clr = sc >= 7 ? "#22c55e" : sc >= 4 ? "#f59e0b" : "#ef4444";
                              return <text key={i} x={lx} y={ly} textAnchor="middle" dominantBaseline="central" fontSize="8" fontWeight="600" fill={clr}>{r.item.length > 5 ? r.item.slice(0, 4) + ".." : r.item}</text>;
                            })}
                          </svg>
                        </div>

                        {/* Dimension Cards */}
                        <div className="sc-dim-list">
                      {rubric.map((r: any) => {
                        const pct = Math.min(100, (r.score / 10) * 100);
                            const clr = pct >= 70 ? "var(--accent-green,#22c55e)" : pct >= 40 ? "var(--accent-yellow,#f59e0b)" : "var(--accent-red,#ef4444)";
                            const levelLabel = pct >= 70 ? "达标" : pct >= 40 ? "一般" : "薄弱";
                        return (
                              <details key={r.item} className="sc-dim-card">
                                <summary className="sc-dim-head">
                                  <div className="sc-dim-info">
                                    <span className="sc-dim-name">{r.item}</span>
                                    <span className="sc-dim-level" style={{color: clr}}>{levelLabel}</span>
                                  </div>
                                  <div className="sc-dim-bar-wrap">
                                    <div className="sc-dim-bar-track">
                                      <div className="sc-dim-bar-fill" style={{width:`${pct}%`, background: clr}} />
                                      {typeof r.bestScore === "number" && r.bestScore > r.score && (
                                        <div
                                          className="sc-dim-bar-best"
                                          title={`历史最高 ${r.bestScore}`}
                                          style={{left: `${Math.min(100, (r.bestScore / 10) * 100)}%`}}
                                        />
                                      )}
                                    </div>
                                    <span className="sc-dim-score" style={{color: clr}}>{r.score}</span>
                                  </div>
                                  {r.trend && <span className={`sc-dim-trend sc-trend-${r.trend}`}>{r.trend === "up" ? "↑" : r.trend === "down" ? "↓" : "—"}{r.prevScore != null ? ` (${r.prevScore}→${r.score})` : ""}</span>}
                            </summary>
                                {r.reason && <div className="sc-dim-reason">{r.reason}</div>}
                                {(() => {
                                  const base = Number(r.base_score ?? 0);
                                  const sigBonus = Number(r.signal_bonus ?? 0);
                                  const lenBonus = Number(r.length_bonus ?? 0);
                                  const rulePen = Number(r.rule_penalty ?? 0);
                                  const dimRules: any[] = Array.isArray(r.dim_rules) ? r.dim_rules : [];
                                  const matched: string[] = Array.isArray(r.matched_evidence) ? r.matched_evidence : [];
                                  const missing: string[] = Array.isArray(r.missing_evidence) ? r.missing_evidence : [];
                                  const rationale = r.rationale;
                                  const hasRich = base > 0 || sigBonus > 0 || lenBonus > 0 || rulePen > 0 || dimRules.length > 0 || matched.length > 0 || missing.length > 0 || rationale;
                                  // 无论 hasRich 与否都渲染——保底显示一个"得分 = X"迷你推导，
                                  // 让学生始终能看到这个分数至少怎么写出来的。
                                  const weight = Number(r.weight ?? 0);
                                  const rawHistory: number[] = Array.isArray(r.rawHistory) ? r.rawHistory : [];
                                  const smoothWeights: number[] = Array.isArray(r.smoothWeights) ? r.smoothWeights : [];
                                  const smoothTurns = Number(r.smoothedFromTurns || 0);
                                  return (
                                    <div className="sc-dim-breakdown">
                                      {/* 平滑前后对照（仅在跨轮平滑时出现） */}
                                      {smoothTurns >= 2 && rawHistory.length >= smoothTurns ? (
                                        <div className="rc-smoothing-note" style={{ marginBottom: 8 }}>
                                          <span className="rc-smoothing-label">展示分</span>
                                          <span className="rc-smoothing-formula">
                                            {Number(r.score).toFixed(2)} = {rawHistory.slice(0, smoothTurns).map((v, i) => (
                                              <span key={i}>
                                                {i > 0 ? " + " : ""}
                                                {(smoothWeights[i] ?? 0).toFixed(1)}×{Number(v).toFixed(2)}
                                              </span>
                                            ))}
                                          </span>
                                          <span className="rc-smoothing-hint">最近 {smoothTurns} 轮加权 · 下方为最新一轮原值推导</span>
                                        </div>
                                      ) : null}
                                      {/* 分数构成条 */}
                                      <div className="sc-dim-breakdown-title">分数怎么算出来的</div>
                                      <div className="sc-dim-breakdown-row">
                                        {hasRich ? (
                                          <>
                                            {base > 0 && (
                                              <span className="sc-dim-breakdown-chip pos" title="按阶段或证据覆盖得到的基础分">
                                                基础 <b>{base.toFixed(1)}</b>
                                              </span>
                                            )}
                                            {lenBonus > 0.05 && (
                                              <span className="sc-dim-breakdown-chip pos" title="文本长度加成">
                                                文本加成 <b>+{lenBonus.toFixed(1)}</b>
                                              </span>
                                            )}
                                            {sigBonus > 0.05 && (
                                              <span className="sc-dim-breakdown-chip pos" title="财务/量化模块证据加成">
                                                量化证据 <b>+{sigBonus.toFixed(1)}</b>
                                              </span>
                                            )}
                                            {rulePen > 0.05 && (
                                              <span className="sc-dim-breakdown-chip neg" title="触发风险规则造成的扣分合计">
                                                规则扣分 <b>-{rulePen.toFixed(1)}</b>
                                              </span>
                                            )}
                                            <span className="sc-dim-breakdown-eq">=</span>
                                            <span className="sc-dim-breakdown-chip final">
                                              得分 <b>{Number(r.score).toFixed(1)}</b>
                                            </span>
                                          </>
                                        ) : (
                                          <>
                                            <span className="sc-dim-breakdown-chip pos" title="本次诊断给出的原始打分（未返回细化因子）">
                                              本次得分 <b>{Number(r.score).toFixed(1)}</b>
                                            </span>
                                            {weight > 0 && (
                                              <>
                                                <span className="sc-dim-breakdown-eq">×</span>
                                                <span className="sc-dim-breakdown-chip" title="该维度在综合分中的权重">
                                                  权重 <b>{weight.toFixed(2)}</b>
                                                </span>
                                                <span className="sc-dim-breakdown-eq">=</span>
                                                <span className="sc-dim-breakdown-chip final" title="本维度对综合分的贡献">
                                                  贡献 <b>{(Number(r.score) * weight).toFixed(2)}</b>
                                                </span>
                                              </>
                                            )}
                                          </>
                                        )}
                                      </div>
                                      {!hasRich && (
                                        <div className="sc-dim-breakdown-note">
                                          该次诊断未返回细化因子（基础分 / 证据加成 / 规则扣分）。重新提交后会显示完整推导链路。
                                        </div>
                                      )}

                                      {/* 命中规则 */}
                                      {dimRules.length > 0 && (
                                        <>
                                          <div className="sc-dim-breakdown-title">命中的风险规则</div>
                                          <div className="sc-dim-rule-list">
                                            {dimRules.slice(0, 4).map((dr: any, i: number) => (
                                              <div key={`${dr.id}-${i}`} className={`sc-dim-rule-row sev-${dr.severity || "mid"}`}>
                                                <span className="sc-dim-rule-id">{dr.id}</span>
                                                <span className="sc-dim-rule-name">{dr.name}</span>
                                              </div>
                                            ))}
                                          </div>
                                        </>
                                      )}

                                      {/* 证据命中 / 缺失 */}
                                      {(matched.length > 0 || missing.length > 0) && (
                                        <>
                                          <div className="sc-dim-breakdown-title">证据关键词</div>
                                          <div className="sc-dim-evidence-chips">
                                            {matched.slice(0, 6).map((kw) => (
                                              <span key={`m-${kw}`} className="sc-dim-evidence-chip matched">命中 · {kw}</span>
                                            ))}
                                            {missing.slice(0, 4).map((kw) => (
                                              <span key={`x-${kw}`} className="sc-dim-evidence-chip missing">缺 · {kw}</span>
                                            ))}
                                          </div>
                                        </>
                                      )}

                                      {/* 人话公式（详细版，可折叠） */}
                                      {rationale?.formula_display && (
                                        <details className="sc-dim-rationale">
                                          <summary>查看详细推导</summary>
                                          <pre className="sc-dim-rationale-text">{rationale.formula_display}</pre>
                                        </details>
                                      )}
                                    </div>
                                  );
                                })()}
                                {typeof r.bestScore === "number" && r.bestScore > r.score && (
                                  <div className="sc-dim-best-hint">历史最高：{r.bestScore}（点击外侧竖线查看）</div>
                                )}
                          </details>
                        );
                      })}
                    </div>

                        {/* 综合分 · 怎么算出来的 */}
                        {(() => {
                          const ovr: any = (latestResult?.diagnosis as any)?.overall_rationale;
                          if (!ovr) return null;
                          const floor = Number(ovr.stage_floor ?? 0);
                          const ceil = Number(ovr.stage_ceiling ?? 10);
                          const raw = Number(ovr.raw_score ?? ovr.value ?? 0);
                          const finalScore = Number(ovr.value ?? 0);
                          const stageCn = String(ovr.project_stage_cn || ovr.project_stage || "");
                          const clamped = raw < floor || raw > ceil;
                          // marker positions on a 0-10 scale
                          const pct = (v: number) => Math.min(100, Math.max(0, (v / 10) * 100));
                          return (
                            <div className="sc-overall-rationale">
                              <div className="sc-overall-rat-head">
                                <span className="sc-overall-rat-title">综合分 {finalScore} / 10 · 怎么算出来的</span>
                                {stageCn && <span className="sc-overall-rat-stage">{stageCn}</span>}
                              </div>
                              {overallSmoothing && overallSmoothing.turns >= 2 ? (
                                <div className="rc-smoothing-note" style={{ marginBottom: 8 }}>
                                  <span className="rc-smoothing-label">展示分</span>
                                  <span className="rc-smoothing-formula">
                                    {overallSmoothing.displayValue.toFixed(2)} = {overallSmoothing.rawHistory.slice(0, overallSmoothing.turns).map((v, i) => (
                                      <span key={i}>
                                        {i > 0 ? " + " : ""}
                                        {(overallSmoothing.weights[i] ?? 0).toFixed(1)}×{v.toFixed(2)}
                                      </span>
                                    ))}
                                  </span>
                                  <span className="rc-smoothing-hint">最近 {overallSmoothing.turns} 轮加权 · 下方为最新一轮原值推导</span>
                                </div>
                              ) : null}
                              <div className="sc-overall-rat-desc">
                                综合分 = 按 9 个维度加权平均后，再夹到「{stageCn || "当前阶段"}」允许区间
                                <b> [{floor}, {ceil}]</b>。
                                加权平均算出 <b>{raw.toFixed(2)}</b>，
                                {clamped
                                  ? (raw < floor
                                      ? <>被抬到下限 <b>{floor}</b></>
                                      : <>被压到上限 <b>{ceil}</b></>)
                                  : <>落在区间内不再修正</>
                                }，
                                最终 <b style={{ color: finalScore >= 7 ? "var(--accent-green,#22c55e)" : finalScore >= 4 ? "var(--accent-yellow,#f59e0b)" : "var(--accent-red,#ef4444)" }}>{finalScore}</b>。
                              </div>
                              {/* 标尺可视化 */}
                              <div className="sc-overall-scale-wrap">
                                <div className="sc-overall-scale">
                                  <div
                                    className="sc-overall-scale-range"
                                    style={{ left: `${pct(floor)}%`, width: `${pct(ceil) - pct(floor)}%` }}
                                    title={`阶段区间 [${floor}, ${ceil}]`}
                                  />
                                  <div className="sc-overall-scale-marker raw" style={{ left: `${pct(raw)}%` }} title={`加权平均 ${raw.toFixed(2)}`}>
                                    <span className="sc-overall-marker-dot" />
                                    <span className="sc-overall-marker-lbl">加权 {raw.toFixed(1)}</span>
                                  </div>
                                  <div className="sc-overall-scale-marker final" style={{ left: `${pct(finalScore)}%` }} title={`最终 ${finalScore}`}>
                                    <span className="sc-overall-marker-dot" />
                                    <span className="sc-overall-marker-lbl">最终 {finalScore}</span>
                                  </div>
                                </div>
                                <div className="sc-overall-scale-axis">
                                  <span>0</span><span>2</span><span>4</span><span>6</span><span>8</span><span>10</span>
                                </div>
                              </div>
                              {/* 维度贡献表 */}
                              {rubric.length > 0 && (
                                <div className="sc-overall-contrib-wrap">
                                  <div className="sc-overall-contrib-title">各维度贡献（得分 × 权重）</div>
                                  <div className="sc-overall-contrib">
                                    {rubric.map((rr: any) => {
                                      const w = Number(rr.weight ?? 1);
                                      const sc = Number(rr.score ?? 0);
                                      const contrib = sc * w;
                                      const pctContrib = Math.min(100, (contrib / 10) * 100);
                                      const col = sc >= 7 ? "#22c55e" : sc >= 4 ? "#f59e0b" : "#ef4444";
                                      return (
                                        <div key={rr.item} className="sc-overall-contrib-row">
                                          <span className="sc-overall-contrib-name">{rr.item}</span>
                                          <div className="sc-overall-contrib-bar">
                                            <div className="sc-overall-contrib-fill" style={{ width: `${pctContrib}%`, background: col }} />
                                          </div>
                                          <span className="sc-overall-contrib-val">{sc.toFixed(1)}×{w.toFixed(1)} = <b>{contrib.toFixed(2)}</b></span>
                                        </div>
                                      );
                                    })}
                                  </div>
                                </div>
                              )}
                              <details className="sc-overall-rat-formula">
                                <summary>查看公式原文</summary>
                                <pre className="sc-overall-rat-text">{ovr.formula_display}</pre>
                              </details>
                            </div>
                          );
                        })()}

                        {/* Grading Principles */}
                        {gradingPrinciples.length > 0 && (
                          <details className="sc-principles">
                            <summary>评分原则 ({gradingPrinciples.length})</summary>
                            <div className="sc-principles-list">
                              {gradingPrinciples.map((item: string, idx: number) => (
                                <div key={idx} className="sc-principle-item">{item}</div>
                              ))}
                            </div>
                          </details>
                        )}
                      </>
                    );
                  })() : <p className="right-hint">提交项目描述后显示评分，描述越完整评分越有参考价值</p>}
                </div>
              )}

              {rightTab === "finance" && (
                <div className="right-section">
                  <h4>财务分析</h4>
                  <div className="panel-desc">
                    从商业模式假设出发，做单位经济、现金流、合理性、TAM/SAM/SOM、定价框架、融资节奏六项建模。
                  </div>
                  <FinanceReportView
                    apiBase={API_BASE}
                    userId={(currentUser?.user_id || studentId || "").toString()}
                    projectId={projectId}
                    conversationId={conversationId || undefined}
                    industryHint={(latestResult?.category || "") as string}
                    onJumpBudget={() => {
                      try {
                        const btn = document.querySelector('[data-budget-open-btn]');
                        if (btn && btn instanceof HTMLElement) btn.click();
                      } catch (e) { /* ignore */ }
                    }}
                  />
                </div>
              )}

              {rightTab === "kg" && (
                <div className="right-section kg-overview">
                  {kgAnalysis && (kgAnalysis.entities ?? []).length > 0 ? (() => {
                    const s = (v: any): string => (v == null ? "" : typeof v === "string" ? v : JSON.stringify(v));
                    const typeColors: Record<string, string> = {
                      stakeholder: "#69c0e0", pain_point: "#e07070", solution: "#5cbd8a",
                      technology: "#a88ccc", market: "#e0a84c", competitor: "#c8a048",
                      resource: "#60b8b8", product: "#6ba3d6", team: "#d4a5d0",
                      business_model: "#e8b960", evidence: "#7ec87e",
                    };
                    const typeNames: Record<string, string> = {
                      stakeholder: "用户", pain_point: "痛点", solution: "方案",
                      technology: "技术", market: "市场", competitor: "竞品",
                      resource: "资源", product: "产品", team: "团队",
                      business_model: "商业", evidence: "证据",
                    };
                    const entities: any[] = kgAnalysis.entities ?? [];
                    const rels: any[] = kgAnalysis.relationships ?? [];
                    const gaps: string[] = kgAnalysis.structural_gaps ?? [];
                    const strengths: string[] = kgAnalysis.content_strengths ?? [];
                    const secScores = kgAnalysis.section_scores ?? {};
                    const grouped: Record<string, any[]> = {};
                    entities.forEach((e: any) => { const t = e.type || "other"; if (!grouped[t]) grouped[t] = []; grouped[t].push(e); });
                    const branches = Object.entries(grouped);
                    const planTasks: any[] = cumulativePlannerTasks;

                    return (
                      <div className="kg-full">
                        <div className="kg-summary-strip">
                          <div className="kg-summary-card"><strong>{entities.length}</strong><span>累积实体</span></div>
                          <div className="kg-summary-card"><strong>{rels.length}</strong><span>累积关系</span></div>
                          <div className="kg-summary-card"><strong>{strengths.length}</strong><span>已形成优势</span></div>
                          <div className="kg-summary-card"><strong>{gaps.length}</strong><span>待补结构缺口</span></div>
                        </div>
                        <div className="kg-toolbar">
                          <span className="kg-toolbar-hint">完整度 {kgAnalysis.completeness_score ?? "?"}/10 · 滚轮缩放，拖拽平移，悬停查看详情</span>
                          </div>
                        <div ref={kgGraphShellRef} className="kg-force-graph-shell" style={{ height: 380, position: "relative", borderRadius: 8, overflow: "hidden", background: "var(--bg-secondary)" }}>
                          <ForceGraph2D
                            graphData={{
                              nodes: entities.map((e: any) => {
                                const sameType = entities.filter((x: any) => x.type === e.type).length;
                                return {
                                  id: e.id, label: e.label, type: e.type,
                                  color: typeColors[e.type] ?? "#6ba3d6",
                                  val: Math.min(6, 1 + sameType),
                                };
                              }),
                              links: rels.filter((r: any) =>
                                entities.some((e: any) => e.id === r.source) &&
                                entities.some((e: any) => e.id === r.target)
                              ).map((r: any) => ({
                                source: r.source, target: r.target, label: r.relation,
                              })),
                            }}
                            width={kgGraphWidth}
                            height={374}
                            nodeRelSize={5}
                            nodeLabel={(node: any) => `${node.label} (${typeNames[node.type] ?? node.type})`}
                            nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
                              const sz = Math.max(4, Math.min(10, (node.val ?? 3) * 1.5));
                              const color = node.color || "#6ba3d6";
                              ctx.beginPath();
                              ctx.arc(node.x, node.y, sz, 0, 2 * Math.PI, false);
                              ctx.fillStyle = color + "30";
                              ctx.fill();
                              ctx.strokeStyle = color;
                              ctx.lineWidth = 1.5;
                              ctx.stroke();
                              const fontSize = Math.max(11 / globalScale, 3);
                              ctx.font = `600 ${fontSize}px sans-serif`;
                              ctx.textAlign = "center";
                              ctx.textBaseline = "middle";
                              ctx.fillStyle = color;
                              const label = node.label.length > 8 ? node.label.slice(0, 7) + ".." : node.label;
                              ctx.fillText(label, node.x, node.y);
                            }}
                            nodePointerAreaPaint={(node: any, color: string, ctx: CanvasRenderingContext2D) => {
                              ctx.beginPath();
                              ctx.arc(node.x, node.y, 7, 0, 2 * Math.PI, false);
                              ctx.fillStyle = color;
                              ctx.fill();
                            }}
                            onNodeClick={(node: any) => {
                              const relCount = rels.filter((r: any) => r.source === node.id || r.target === node.id || (typeof r.source === "object" && r.source?.id === node.id) || (typeof r.target === "object" && r.target?.id === node.id)).length;
                              alert(`[${typeNames[node.type] ?? node.type}] ${node.label}\n关联关系: ${relCount} 条`);
                            }}
                            linkLabel={(link: any) => link.label || ""}
                            linkColor={() => "rgba(150,150,150,0.3)"}
                            linkWidth={1}
                            linkDirectionalArrowLength={3.5}
                            linkDirectionalArrowRelPos={1}
                            cooldownTicks={60}
                            d3AlphaDecay={0.06}
                            d3VelocityDecay={0.3}
                            enableZoomInteraction={true}
                            enablePanInteraction={true}
                          />
                        </div>

                        {/* Radar chart for section scores */}
                        {Object.keys(secScores).length > 0 && (() => {
                          const dimNames: Record<string, string> = { problem_definition: "问题定义", user_evidence: "用户证据", solution_feasibility: "方案可行性", business_model: "商业模式", competitive_advantage: "竞争优势" };
                          const dims = Object.entries(secScores).map(([k, v]) => ({ key: k, label: dimNames[k] ?? k, score: Number(v) }));
                          const n = dims.length;
                          if (n < 3) return null;
                          const cx = 90, cy = 90, R = 70;
                          const angleStep = (2 * Math.PI) / n;
                          const gridLevels = [2, 4, 6, 8, 10];
                          const pointsFull = dims.map((d, i) => {
                            const a = -Math.PI / 2 + i * angleStep;
                            const r = (d.score / 10) * R;
                            return { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) };
                          });
                          const polyPoints = pointsFull.map(p => `${p.x},${p.y}`).join(" ");
                          return (
                            <div className="kg-radar-section">
                              <h5>维度雷达</h5>
                              <div className="kg-radar-wrap">
                                <svg viewBox="0 0 180 180" className="kg-radar-svg">
                                  {gridLevels.map(lv => {
                                    const pts = dims.map((_, i) => {
                                      const a = -Math.PI / 2 + i * angleStep;
                                      const r = (lv / 10) * R;
                                      return `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`;
                                    }).join(" ");
                                    return <polygon key={lv} points={pts} fill="none" stroke="rgba(150,150,150,0.15)" strokeWidth="0.5" />;
                                  })}
                                  {dims.map((_, i) => {
                                    const a = -Math.PI / 2 + i * angleStep;
                                    return <line key={i} x1={cx} y1={cy} x2={cx + R * Math.cos(a)} y2={cy + R * Math.sin(a)} stroke="rgba(150,150,150,0.15)" strokeWidth="0.5" />;
                                  })}
                                  <polygon points={polyPoints} fill="rgba(99,102,241,0.18)" stroke="#6366f1" strokeWidth="1.5" />
                                  {pointsFull.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r="2.5" fill="#6366f1" />)}
                                  {dims.map((d, i) => {
                                    const a = -Math.PI / 2 + i * angleStep;
                                    const lx = cx + (R + 14) * Math.cos(a);
                                    const ly = cy + (R + 14) * Math.sin(a);
                                    const color = d.score >= 7 ? "#5cbd8a" : d.score >= 4 ? "#e0a84c" : "#e07070";
                                return (
                                      <text key={i} x={lx} y={ly} textAnchor="middle" dominantBaseline="middle" fontSize="8" fill={color} fontWeight="600">{d.label}</text>
                                );
                              })}
                          </svg>
                                <div className="kg-radar-scores">
                                  {dims.map(d => {
                                    const pct = Math.min(100, (d.score / 10) * 100);
                              const color = pct >= 70 ? "#5cbd8a" : pct >= 40 ? "#e0a84c" : "#e07070";
                              return (
                                      <div key={d.key} className="kg-score-row">
                                        <span className="kg-score-name">{d.label}</span>
                                  <div className="kg-score-bar"><div className="kg-score-fill" style={{ width: `${pct}%`, background: color }} /></div>
                                        <span className="kg-score-val" style={{ color }}>{d.score}</span>
                                </div>
                              );
                            })}
                                </div>
                              </div>
                            </div>
                          );
                        })()}

                        {branches.length > 0 && (
                          <div className="kg-list-section">
                            <h5>图谱覆盖类型</h5>
                            <div className="kg-type-chip-row">
                              {branches
                                .sort((a, b) => b[1].length - a[1].length)
                                .slice(0, 8)
                                .map(([type, items]) => (
                                  <div key={type} className="kg-type-chip">
                                    <span className="kg-type-chip-dot" style={{ background: typeColors[type] ?? "#6ba3d6" }} />
                                    <span>{typeNames[type] ?? type}</span>
                                    <strong>{items.length}</strong>
                                  </div>
                                ))}
                            </div>
                          </div>
                        )}

                        {/* Strengths */}
                        {strengths.length > 0 && (
                          <div className="kg-list-section good">
                            <h5>做得好的</h5>
                            {strengths.map((item, i) => <div key={i} className="kg-list-item good">{item}</div>)}
                          </div>
                        )}

                        {/* Gaps */}
                        {gaps.length > 0 && (
                          <div className="kg-list-section gap">
                            <h5>需要补强</h5>
                            {gaps.map((item, i) => <div key={i} className="kg-list-item gap">{item}</div>)}
                          </div>
                        )}

                        {/* Insight */}
                        {kgAnalysis.insight && (
                          <div className="kg-insight-box">{kgAnalysis.insight}</div>
                        )}

                        {/* Merged Tasks */}
                        {planTasks.length > 0 && (
                          <div className="kg-tasks-section">
                            <h5>建议行动</h5>
                            {planTasks.map((t: any, ti: number) => (
                              <details key={ti} className="kg-task-card" open={ti === 0}>
                                <summary>{s(t.task)}</summary>
                                <div className="kg-task-body">
                                  {s(t.why) && <p>{s(t.why)}</p>}
                                  {s(t.how) && <div><MarkdownContent content={s(t.how)} theme={theme} /></div>}
                                </div>
                              </details>
                            ))}
                          </div>
                        )}

                        {/* Relationships summary */}
                        {rels.length > 0 && (
                          <div className="kg-rels-section">
                            <h5>关键关系 ({rels.length})</h5>
                            {rels.slice(0, 8).map((r: any, ri: number) => {
                              const srcLabel = entities.find((e: any) => e.id === r.source)?.label ?? r.source;
                              const tgtLabel = entities.find((e: any) => e.id === r.target)?.label ?? r.target;
                              return <div key={ri} className="kg-rel-row">{srcLabel} <span className="kg-rel-arrow">→ {r.relation} →</span> {tgtLabel}</div>;
                            })}
                          </div>
                        )}

                        {/* 知识图谱质量评估已迁移至首页『知识库与知识图谱』→『质量评估』标签页，此处仅保留业务梳理信息 */}

                        {/* KB Search Story (Module 3c) */}
                        {(() => {
                          const kbU = latestResult?.agent_trace?.kb_utilization ?? latestResult?.kb_utilization ?? {};
                          const totalKb = Number((kbStats as any)?.neo4j?.total_projects ?? (kbStats as any)?.rag?.corpus_count ?? 0);
                          const ragHits = kbU.hits_count ?? 0;
                          if (!ragHits) return null;
                          const neoOk = kbU.neo4j_enriched ?? false;
                          const neoCount = kbU.neo4j_enriched_count ?? 0;
                          const queryPreview = String(kbU.query_preview ?? "").trim();
                          const searchTrace: any[] = Array.isArray(kbU.search_trace) ? kbU.search_trace : [];
                          const dc = kbU.dual_channel ?? {};
                          const gHits: any[] = Array.isArray(dc.graph_details) ? dc.graph_details : [];
                          const weakDims: string[] = Array.isArray(kbU.weak_dims_for_complementary) ? kbU.weak_dims_for_complementary : [];
                          const dLabel: Record<string, string> = {
                            pain_point: "痛点", solution: "方案", innovation: "创新点",
                            business_model: "商业模式", evidence: "证据", market: "市场",
                            stakeholder: "用户", risk: "风险", channel: "渠道", technology: "技术", competitor: "竞品",
                          };
                          const srcLabel: Record<string, string> = { shared_node: "共享节点", complement: "结构互补", keyword: "关键词" };
                          return (
                            <div className="kbt-section">
                              <h5>知识库检索路径与启发</h5>
                              <p className="kbt-summary">
                                从 <strong>{totalKb}</strong> 个案例库中检索到 <strong>{ragHits}</strong> 个参考
                                {neoOk && <>，其中 <strong>{neoCount}</strong> 个获得图谱深度增强</>}
                              </p>
                              {queryPreview && (
                                <div className="kbt-query-card">
                                  <span className="kbt-q-label">检索关键词</span>
                                  <span className="kbt-q-text">{queryPreview.length > 100 ? queryPreview.slice(0, 100) + "..." : queryPreview}</span>
                                </div>
                              )}

                              {gHits.length > 0 && (
                                <details className="kbt-graph-stories collapsible-section" open>
                                  <summary className="kbt-sub-title">图谱检索启发 ({gHits.length})</summary>
                                  {gHits.map((gh: any, gi: number) => {
                                    const matchedDims: string[] = Array.isArray(gh.matched_dimensions) ? gh.matched_dimensions : [];
                                    const matchedNodes: string[] = Array.isArray(gh.matched_nodes) ? gh.matched_nodes : [];
                                    const matchSources: string[] = Array.isArray(gh.match_sources) ? gh.match_sources : [];
                                    const ctx = gh.context ?? {};
                                    const ctxPains: string[] = Array.isArray(ctx.pains) ? ctx.pains : [];
                                    const ctxSolutions: string[] = Array.isArray(ctx.solutions) ? ctx.solutions : [];
                                    const ctxInnovations: string[] = Array.isArray(ctx.innovations) ? ctx.innovations : [];
                                    const ctxBiz: string[] = Array.isArray(ctx.biz_models) ? ctx.biz_models : [];
                                    const dimText = matchedDims.map(d => dLabel[d] ?? d).join("、");
                                    const nodeExamples = matchedNodes.slice(0, 3).map(n => {
                                      const p = String(n).split(":"); return p.length > 1 ? p.slice(1).join(":") : n;
                                    });
                                    const projName = gh.project_name || gh.project_id || "未知案例";
                                    return (
                                      <div key={gi} className="kbt-story-card">
                                        <div className="kbt-story-narrative">
                                          从你的描述中发现你在 <strong>{dimText || "多个维度"}</strong> 上与 <strong className="kbt-proj-name">{projName}</strong> 高度相关
                                          {nodeExamples.length > 0 && <>，共享关键概念：{nodeExamples.map((n, i) => <strong key={i} className="kbt-node-hl">{n}</strong>)}</>}
                                        </div>
                                        {matchSources.length > 0 && (
                                          <div className="kbt-story-sources">
                                            {matchSources.map(s => <span key={s} className="kbt-src-chip">{srcLabel[s] ?? s}</span>)}
                                          </div>
                                        )}
                                        {(ctxPains.length > 0 || ctxSolutions.length > 0 || ctxInnovations.length > 0 || ctxBiz.length > 0) && (
                                          <div className="kbt-story-ctx">
                                            <span className="kbt-ctx-intro">{projName} 的做法：</span>
                                            <div className="kbt-ctx-items">
                                              {ctxPains.map((p, i) => <span key={`p${i}`} className="kbt-ctx-tag kbt-pain">{p}</span>)}
                                              {ctxSolutions.map((s, i) => <span key={`s${i}`} className="kbt-ctx-tag kbt-sol">{s}</span>)}
                                              {ctxInnovations.map((n, i) => <span key={`i${i}`} className="kbt-ctx-tag kbt-inn">{n}</span>)}
                                              {ctxBiz.map((b, i) => <span key={`b${i}`} className="kbt-ctx-tag kbt-biz">{b}</span>)}
                                            </div>
                                          </div>
                                        )}
                                      </div>
                                    );
                                  })}
                                </details>
                              )}

                              {searchTrace.length > 0 && (
                                <details className="kbt-trace-details">
                                  <summary>语义检索命中详情 ({searchTrace.length})</summary>
                                  <div className="kbt-trace-list">
                                    {searchTrace.map((st: any, si: number) => (
                                      <div key={si} className="kbt-trace-row">
                                        <span className="kbt-tr-rank">#{si + 1}</span>
                                        <span className="kbt-tr-name">{st.case_id || st.snippet}</span>
                                        {st.category && <span className="kbt-tr-cat">{st.category}</span>}
                                        <span className="kbt-tr-score">{Math.round(st.score * 100)}%</span>
                                        {st.neo4j_enriched && <span className="kbt-tr-badge kbt-b-neo">图谱增强</span>}
                                        {st.complementary && <span className="kbt-tr-badge kbt-b-comp">互补检索</span>}
                                        {st.hyper_driven && <span className="kbt-tr-badge kbt-b-hyper">超图驱动</span>}
                                      </div>
                                    ))}
                                  </div>
                                  {weakDims.length > 0 && (
                                    <div className="kbt-trace-weak">互补搜索弱势维度：{weakDims.join("、")}</div>
                                  )}
                                </details>
                              )}
                            </div>
                          );
                        })()}
                      </div>
                    );
                  })() : (
                    <div className="proj-empty-guide">
                      <p>发送项目描述或上传计划书，AI 会自动提取关键信息生成项目梳理。数据跨轮次累积，不会因追问而丢失。</p>
                    </div>
                  )}

                  {/* Global Knowledge Base Stats Panel */}
                  {kbStats?.neo4j && (() => {
                    const n = kbStats.neo4j;
                    const dims = n.dimensions ?? {};
                    const cats: {name: string; count: number}[] = n.categories ?? [];
                    const embedOk = kbStats.rag?.embed_ready ?? false;
                    const dimEntries: [string, number][] = [
                      ["痛点", dims.pain_points ?? 0],
                      ["解决方案", dims.solutions ?? 0],
                      ["商业模式", dims.business_models ?? 0],
                      ["市场", dims.markets ?? 0],
                      ["创新点", dims.innovations ?? 0],
                      ["证据", dims.evidence ?? 0],
                      ["执行路径", dims.execution_steps ?? 0],
                      ["利益相关者", dims.stakeholders ?? 0],
                      ["风控", dims.risk_controls ?? 0],
                    ];
                    const maxDim = Math.max(...dimEntries.map(d => d[1]), 1);
                    const hyperLocal = ((kbStats as any)?.hypergraph_local) || {};
                    const hyperDb = (n as any)?.hypergraph || {};
                    const ragCount = Number((kbStats as any)?.rag?.corpus_count ?? 0);
                    // 超图本体的权威静态定义（77 家族 / 95 模式 / 15 分组），来自后端 ontology_totals
                    const ontologyTotals = (hyperLocal as any)?.ontology_totals || {};
                    const totalFamilies = Number(ontologyTotals.families ?? 77);
                    const totalPatterns = Number(ontologyTotals.patterns ?? 95);
                    const totalGroups = Number(ontologyTotals.groups ?? 15);
                    // 本次生成的超图实例数量（命中家族种数 / 超边数 / 节点数）
                    const hitFamilyCount = hyperLocal.family_counts ? Object.keys(hyperLocal.family_counts).length : 0;
                    const KB_LIVE = {
                      projects: Number(n.total_projects ?? 0),
                      nodes: Number(n.total_nodes ?? 0),
                      relationships: Number(n.total_relationships ?? 0),
                      categories: Number(n.total_categories ?? (Array.isArray(cats) ? cats.length : 0)),
                      rag: ragCount || Number(n.total_projects ?? 0),
                      edgeFamilies: totalFamilies,
                      edgePatterns: totalPatterns,
                      edgeGroups: totalGroups,
                      hitFamilies: hitFamilyCount,
                      hyperNodes: Number(hyperLocal.node_count ?? hyperDb.nodes ?? 0),
                      hyperEdges: Number(hyperLocal.edge_count ?? hyperDb.edges ?? 0),
                      riskRules: Number(n.risk_rules ?? 0),
                      rubricItems: Number(n.rubric_items ?? 0),
                    };
                    return (
                      <div className="kb-global-stats">
                        <h5>知识库全局概览</h5>
                        <div className="kb-gs-summary">
                          <div className="kb-gs-card"><div className="kb-gs-num">{KB_LIVE.projects}</div><div className="kb-gs-label">标准案例</div></div>
                          <div className="kb-gs-card"><div className="kb-gs-num">{KB_LIVE.nodes}</div><div className="kb-gs-label">图谱节点</div></div>
                          <div className="kb-gs-card"><div className="kb-gs-num">{KB_LIVE.relationships}</div><div className="kb-gs-label">知识关系</div></div>
                          <div className="kb-gs-card"><div className="kb-gs-num">{KB_LIVE.categories}</div><div className="kb-gs-label">项目类别</div></div>
                          <div className="kb-gs-card"><div className="kb-gs-num">{KB_LIVE.rag}</div><div className="kb-gs-label">RAG语料</div></div>
                          <div className="kb-gs-card" title="超图本体定义的超边家族总数（静态：77 条跨维语义类）"><div className="kb-gs-num">{KB_LIVE.edgeFamilies}</div><div className="kb-gs-label">超边家族</div></div>
                          <div className="kb-gs-card" title="超图本体评分锚点模式总数（静态：95 条理想/风险/中性诊断模式）"><div className="kb-gs-num">{KB_LIVE.edgePatterns}</div><div className="kb-gs-label">超边模式</div></div>
                          <div className="kb-gs-card" title="本项目已生成的超边实例数量（动态：随对话与诊断积累）"><div className="kb-gs-num">{KB_LIVE.hyperEdges}</div><div className="kb-gs-label">本项目超边</div></div>
                        </div>
                        <details className="kb-gs-details" open>
                          <summary>类别分布 ({cats.length})</summary>
                          <div className="kb-gs-cat-list">
                            {cats.map(c => (
                              <div key={c.name} className="kb-gs-cat-row">
                                <span className="kb-gs-cat-name">{c.name}</span>
                                <div className="kb-gs-cat-bar"><div className="kb-gs-cat-fill" style={{width: `${Math.round(c.count / Math.max(...cats.map(x=>x.count), 1) * 100)}%`}} /></div>
                                <span className="kb-gs-cat-num">{c.count}</span>
                              </div>
                            ))}
                          </div>
                        </details>
                        <details className="kb-gs-details">
                          <summary>维度覆盖统计</summary>
                          <div className="kb-gs-dim-list">
                            {dimEntries.map(([label, count]) => (
                              <div key={label} className="kb-gs-dim-row">
                                <span className="kb-gs-dim-name">{label}</span>
                                <div className="kb-gs-dim-bar"><div className="kb-gs-dim-fill" style={{width: `${Math.round(count / maxDim * 100)}%`}} /></div>
                                <span className="kb-gs-dim-num">{count}</span>
                              </div>
                            ))}
                          </div>
                        </details>
                        <details className="kb-gs-details">
                          <summary>检索架构</summary>
                          <div className="kb-gs-arch">
                            <div className="kb-gs-arch-row">
                              <span className="kb-gs-arch-dot" style={{background: embedOk ? "#10b981" : "#ef4444"}} />
                              <span>向量检索 (bge-m3): {embedOk ? "就绪" : "未就绪"}</span>
                            </div>
                            <div className="kb-gs-arch-row">
                              <span className="kb-gs-arch-dot" style={{background: "#10b981"}} />
                              <span>Neo4j 图检索: {KB_LIVE.nodes} 节点 · {KB_LIVE.relationships} 关系</span>
                            </div>
                            <div className="kb-gs-arch-row">
                              <span className="kb-gs-arch-dot" style={{background: "#10b981"}} />
                              <span>TF-IDF 关键词检索: 就绪</span>
                            </div>
                            <div className="kb-gs-arch-row">
                              <span className="kb-gs-arch-dot" style={{background: "#10b981"}} />
                              <span>超图本体: {KB_LIVE.edgeFamilies} 家族 · {KB_LIVE.edgePatterns} 模式 · {KB_LIVE.edgeGroups} 分组（本项目已实例化 {KB_LIVE.hyperEdges} 超边 / {KB_LIVE.hyperNodes} 节点{KB_LIVE.hitFamilies ? ` · 命中 ${KB_LIVE.hitFamilies} 类家族` : ""}）</span>
                            </div>
                            <div className="kb-gs-arch-row">
                              <span className="kb-gs-arch-dot" style={{background: "#10b981"}} />
                              <span>风险规则: {KB_LIVE.riskRules} · 评分标准: {KB_LIVE.rubricItems} 维度</span>
                            </div>
                          </div>
                        </details>
                      </div>
                    );
                  })()}
                </div>
              )}

              {rightTab === "hyper" && (
                <div className="right-section">
                  <h4>项目全景诊断</h4>
                  {hyperStudent?.ok ? (() => {
                    const dims = Object.entries(hyperStudent.dimensions ?? {}) as [string, any][];
                    const coveredDims = dims.filter(([, v]) => v.covered);
                    const missingDims = dims.filter(([, v]) => !v.covered);
                    const kbU = latestResult?.agent_trace?.kb_utilization ?? latestResult?.kb_utilization ?? {};
                    const agentsCalled: string[] = latestResult?.agent_trace?.orchestration?.agents_called ?? [];
                    const roleAgents: Record<string, any> = latestResult?.agent_trace?.role_agents ?? {};
                    const activeAgents = agentsCalled.length > 0 ? agentsCalled : Object.keys(roleAgents).filter(k => roleAgents[k]?.analysis);
                    const agentNames: Record<string, string> = { coach: "教练", analyst: "分析师", advisor: "顾问", grader: "评分官", planner: "规划师", tutor: "导师" };
                    const covScore = Number(hyperStudent.coverage_score ?? 0);
                    const circumf = 2 * Math.PI * 38;
                    const covOffset = circumf * (1 - covScore / 10);
                    const covColor = covScore >= 7 ? "#22c55e" : covScore >= 4 ? "#f59e0b" : "#ef4444";

                    return (
                    <>
                      {/* ── 1. Hero: Coverage Ring + Stats ── */}
                      <div className="ht-hero">
                        <svg width="96" height="96" viewBox="0 0 96 96" className="ht-hero-ring">
                          <circle cx="48" cy="48" r="38" fill="none" stroke="var(--border)" strokeWidth="7" />
                          <circle cx="48" cy="48" r="38" fill="none" stroke={covColor} strokeWidth="7"
                            strokeDasharray={circumf} strokeDashoffset={covOffset}
                            strokeLinecap="round" transform="rotate(-90 48 48)" style={{ transition: "stroke-dashoffset 0.6s ease" }} />
                          <text x="48" y="44" textAnchor="middle" fontSize="20" fontWeight="700" fill={covColor}>{covScore}</text>
                          <text x="48" y="58" textAnchor="middle" fontSize="9" fill="var(--text-muted)">/10</text>
                            </svg>
                        <div className="ht-hero-stats">
                          <div className="ht-stat"><span className="ht-stat-val">{hyperStudent.covered_count ?? 0}<small>/{hyperStudent.total_dimensions ?? 15}</small></span><span className="ht-stat-lbl">维度覆盖</span></div>
                          <div className="ht-stat"><span className="ht-stat-val">{hyperTemplateComplete}<small>/{hyperTemplateMatches.length || 20}</small></span><span className="ht-stat-lbl">闭环完成</span></div>
                          <div className="ht-stat"><span className="ht-stat-val ht-warn">{hyperConsistencyIssues.length}</span><span className="ht-stat-lbl">一致性问题</span></div>
                          <div className="ht-stat"><span className="ht-stat-val ht-risk">{(hyperStudent.pattern_warnings ?? []).length}</span><span className="ht-stat-lbl">风险模式</span></div>
                          </div>
                          </div>

                      {/* ── 1b. Insight Overview (summary, signals, key dims) ── */}
                      {(hyperInsight?.summary || (hyperInsight?.top_signals ?? []).length > 0 || (hyperInsight?.key_dimensions ?? []).length > 0) && (
                        <div className="ht-section ht-overview-section">
                          {hyperInsight?.summary && <p className="ht-overview-summary">{hyperInsight.summary}</p>}
                          {(hyperInsight?.top_signals ?? []).length > 0 && (
                            <div className="ht-tag-group">
                              <span className="ht-tag-label">关键信号</span>
                              {(hyperInsight.top_signals ?? []).map((sig: string, si: number) => (
                                <span key={si} className="ht-tag signal">{sig}</span>
                              ))}
                        </div>
                          )}
                          {(hyperInsight?.key_dimensions ?? []).length > 0 && (
                            <div className="ht-tag-group">
                              <span className="ht-tag-label">焦点维度</span>
                              {(hyperInsight.key_dimensions ?? []).map((d: string, di: number) => (
                                <span key={di} className="ht-tag dim">{d}</span>
                              ))}
                            </div>
                          )}
                          {hyperInsight?.topology?.hub_nodes?.length > 0 && (
                            <div className="ht-tag-group">
                              <span className="ht-tag-label">枢纽节点</span>
                              {(hyperInsight.topology.hub_nodes ?? []).map((h: any, hi: number) => (
                                <span key={hi} className="ht-tag hub" title={h.interpretation}>{h.node} ({h.degree})</span>
                          ))}
                        </div>
                          )}
                      </div>
                      )}

                      {/* ── 2. Dimension Coverage Matrix ── */}
                      <div className="ht-section">
                        <h5 className="ht-title">维度覆盖矩阵</h5>
                        <p className="ht-guide-sub">超图引擎从你的描述中识别了 {coveredDims.length} 个已覆盖维度（绿色）和 {missingDims.length} 个待补充维度（灰色）。数字表示该维度下提取到的实体数量，越多说明描述越充分。</p>
                        <div className="ht-dim-grid">
                          {dims.map(([key, v]) => (
                            <div key={key} className={`ht-dim-cell ${v.covered ? "covered" : "missing"}`}>
                              <div className="ht-dim-name">{(v.name ?? key).slice(0, 4)}</div>
                              <div className="ht-dim-count">{v.count ?? 0}</div>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* ── 3. Template Status Grid ── */}
                      {hyperTemplateMatches.length > 0 && (
                        <div className="ht-section">
                          <h5 className="ht-title">模板闭环检测 <span className="ht-title-sub">(T1-T{hyperTemplateMatches.length})</span></h5>
                          <p className="ht-guide-sub">超图定义了 {hyperTemplateMatches.length} 种逻辑闭环模板（如「用户→痛点→方案→证据」）。绿色=完整链路，黄色=部分覆盖，红色=关键缺失。闭环越多，项目逻辑越自洽。</p>
                          <div className="ht-tmpl-grid">
                            {hyperTemplateMatches.map((t: any, ti: number) => (
                              <div key={ti} className={`ht-tmpl-chip ${t.status}`} title={t.name || t.id}>
                                <span className="ht-tmpl-id">{(t.id ?? `T${ti+1}`).replace(/_.*/, "")}</span>
                            </div>
                          ))}
                          </div>
                          <div className="ht-tmpl-legend">
                            <span className="ht-legend-item"><span className="ht-legend-dot complete" />完成</span>
                            <span className="ht-legend-item"><span className="ht-legend-dot partial" />部分</span>
                            <span className="ht-legend-item"><span className="ht-legend-dot missing" />缺失</span>
                          </div>
                        </div>
                      )}

                      {/* ── 4. Agent/Dimension Hypergraph Signal Dashboard (V3) ── */}
                      {(() => {
                        const hyperDetails: any[] = latestResult?.agent_trace?.agent_hyper_details ?? [];
                        const dimLabelsMap: Record<string, string> = {
                          status_judgment: "项目状态", core_bottleneck: "核心瓶颈", structural_cause: "结构原因",
                          counter_intuitive: "反直觉洞察", method_bridge: "方法桥接", teacher_criteria: "评审标准",
                          external_reference: "外部案例", strategy_directions: "策略方向", action_plan: "行动方案",
                          probing_questions: "启发追问",
                        };
                        if (hyperDetails.length > 0) {
                          return (
                            <div className="ht-section">
                              <h5 className="ht-title">各维度接收的超图启发 ({hyperDetails.length})</h5>
                              <p className="ht-guide-sub">超图引擎根据教学超边为每个分析维度注入了针对性的启发信息。柱状图越长，该维度获得的教学辅助信号越多。点击展开可查看具体内容。</p>
                              <p className="ht-guide-sub">每个分析维度的 Agent 在生成回答前，都会接收超图提供的教学启发信号。条数越多表示超图对该维度提供的决策依据越丰富。展开可查看具体的超图注入内容。</p>
                              <div className="ht-agent-bar-chart">
                                {hyperDetails.map((hd: any, i: number) => {
                                  const lines = String(hd.hyper ?? "").split("\n").filter((l: string) => l.trim());
                                  const maxBar = Math.max(...hyperDetails.map((h: any) => String(h.hyper ?? "").split("\n").filter((l: string) => l.trim()).length), 1);
                                  return (
                                    <div key={i} className="ht-agent-bar-row">
                                      <span className="ht-agent-label">{dimLabelsMap[hd.dim] ?? hd.dim}</span>
                                      <div className="ht-agent-bar-track">
                                        <div className="ht-agent-bar-fill" style={{ width: `${Math.round((lines.length / maxBar) * 100)}%` }} />
                                      </div>
                                      <span className="ht-agent-bar-num">{lines.length}</span>
                                    </div>
                                  );
                                })}
                              </div>
                              {hyperDetails.map((hd: any, i: number) => {
                                const lines = String(hd.hyper ?? "").split("\n").filter((l: string) => l.trim());
                                if (lines.length === 0) return null;
                                return (
                                  <details key={i} className="ht-agent-detail collapsible-section">
                                    <summary>{dimLabelsMap[hd.dim] ?? hd.dim} ({lines.length} 条)</summary>
                                    <div className="ht-agent-detail-body">
                                      {lines.map((line: string, li: number) => (
                                        <div key={li} className="ht-signal-row">
                                          <span className="ht-signal-text">{line.replace(/^[^:：]+[:：]\s*/, "").trim() || line}</span>
                                        </div>
                                      ))}
                                    </div>
                                  </details>
                                );
                              })}
                            </div>
                          );
                        }
                        if (activeAgents.length > 0) {
                          const anyHyper = activeAgents.some(a => String((roleAgents[a] ?? {}).hyper_context_sent ?? "").trim().length > 0);
                          if (!anyHyper) return null;
                          return (
                            <div className="ht-section">
                              <h5 className="ht-title">各Agent接收的超图启发</h5>
                              {activeAgents.filter(a => String((roleAgents[a] ?? {}).hyper_context_sent ?? "").trim()).map(a => {
                                const ctx = String((roleAgents[a] ?? {}).hyper_context_sent ?? "");
                                const lines = ctx.split("\n").filter((l: string) => l.trim());
                                return (
                                  <details key={a} className="ht-agent-detail collapsible-section">
                                    <summary>{agentNames[a] ?? a} ({lines.length} 条)</summary>
                                    <div className="ht-agent-detail-body">
                                      {lines.map((line: string, li: number) => (
                                        <div key={li} className="ht-signal-row">
                                          <span className="ht-signal-text">{line.replace(/^[^:：]+[:：]\s*/, "").trim() || line}</span>
                                        </div>
                                      ))}
                                    </div>
                                  </details>
                                );
                              })}
                            </div>
                          );
                        }
                        return null;
                      })()}

                      {/* ── 5. Consistency Issues ── */}
                      {hyperConsistencyIssues.length > 0 && (
                        <div className="ht-section">
                          <h5 className="ht-title">逻辑一致性检测 <span className="ht-badge-count">{hyperConsistencyIssues.length}</span></h5>
                          <p className="ht-guide-sub">超图引擎发现你的项目描述中存在 {hyperConsistencyIssues.length} 处逻辑矛盾或不一致。点击展开可查看问题详情和压力测试追问。</p>
                          {hyperConsistencyIssues.map((ci: any, idx: number) => (
                            <details key={idx} className="ht-ci-card">
                              <summary><span className="ht-ci-id">{ci.id}</span><span className="ht-ci-msg">{ci.message}</span></summary>
                              {(ci.pressure_questions ?? []).length > 0 && (
                                <div className="ht-ci-questions">{(ci.pressure_questions ?? []).map((q: string, qi: number) => <div key={qi} className="ht-ci-q">{q}</div>)}</div>
                              )}
                            </details>
                          ))}
                        </div>
                      )}

                      {/* ── 6. Insights: Missing + Warnings + Strengths ── */}
                      <div className="ht-insights-grid">
                        {(hyperStudent.missing_dimensions ?? []).length > 0 && (
                          <div className="ht-insight-card ht-card-missing">
                            <h5>优先补充</h5>
                            {(hyperStudent.missing_dimensions ?? []).map((m: any, mi: number) => (
                              <div key={mi} className="ht-insight-item ht-insight-rich">
                                <div className="ht-insight-head-row">
                                  <span className={`ht-imp-badge ${m.importance}`}>{m.importance}</span>
                                  <span className="ht-insight-dim">{m.dimension}</span>
                                </div>
                                <p className="ht-insight-desc">{m.recommendation}</p>
                                {m.action_hint && <p className="ht-action-hint">{m.action_hint}</p>}
                              </div>
                            ))}
                          </div>
                        )}
                      {(hyperStudent.pattern_warnings ?? []).length > 0 && (
                          <div className="ht-insight-card ht-card-warn">
                            <h5>风险模式</h5>
                            {(hyperStudent.pattern_warnings ?? []).map((w: any, wi: number) => (
                              <div key={wi} className="ht-insight-item ht-insight-rich">
                                {w.family_label && <span className="ht-warn-family">{w.family_label}</span>}
                                <p className="ht-insight-desc">{w.warning}</p>
                                {w.project_context && <p className="ht-insight-ctx">{w.project_context}</p>}
                                <div className="ht-insight-meta-row">
                                  <span className="ht-meta-support">支持度 {w.support ?? 0}</span>
                                  {(w.matched_rules ?? []).length > 0 && (
                                    <span className="ht-meta-rules">规则: {(w.matched_rules ?? []).slice(0, 3).join(", ")}</span>
                                  )}
                                </div>
                              </div>
                          ))}
                        </div>
                      )}
                      {(hyperStudent.pattern_strengths ?? []).length > 0 && (
                          <div className="ht-insight-card ht-card-good">
                            <h5>优势结构</h5>
                            {(hyperStudent.pattern_strengths ?? []).map((s: any, si: number) => (
                              <div key={si} className="ht-insight-item ht-insight-rich">
                                {s.family_label && <span className="ht-strength-family">{s.family_label}</span>}
                                <p className="ht-insight-desc">{s.note}</p>
                                {(s.related_entities ?? []).length > 0 && (
                                  <p className="ht-insight-ctx">涉及实体: {(s.related_entities ?? []).join("、")}</p>
                                )}
                                <div className="ht-insight-meta-row">
                                  <span className="ht-meta-support">支持度 {s.support ?? 0}</span>
                                  {s.edge_type && <span className="ht-edge-tag">{s.edge_type}</span>}
                                </div>
                              </div>
                          ))}
                        </div>
                      )}
                      </div>

                      {/* ── 7. Useful Cards (from project-view) ── */}
                      {hyperProjectView && (hyperProjectView?.useful_cards ?? []).length > 0 && (
                        <div className="ht-section">
                          <h5 className="ht-title">超图核心结论</h5>
                          <p className="ht-guide-sub">基于你提供的项目信息和超图结构分析，以下是最值得关注的发现</p>
                          <div className="ht-useful-grid">
                            {(hyperProjectView.useful_cards ?? []).map((card: any, idx: number) => {
                              const toneIcons: Record<string, string> = { gap: "🔍", risk: "⚠️", strength: "✅" };
                              const toneLabels: Record<string, string> = { gap: "待补充", risk: "风险提醒", strength: "亮点" };
                              return (
                              <div key={idx} className={`ht-useful-card-v3 ${card.tone || ""}`}>
                                <div className="ht-uc3-header">
                                  <span className="ht-uc3-icon">{toneIcons[card.tone] || "📋"}</span>
                                  <span className="ht-uc3-title">{card.title}</span>
                                  <span className={`ht-uc3-badge ${card.tone || ""}`}>{toneLabels[card.tone] || ""}</span>
                                </div>
                                <p className="ht-uc3-summary">{card.summary}</p>
                                {card.reason && <p className="ht-uc3-reason">{card.reason}</p>}
                                {card.project_hint && <p className="ht-uc3-hint">{card.project_hint}</p>}
                              </div>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {/* ── 7b. Matched Rules */}
                      {(hyperProjectView?.process_trace?.matched_rules ?? []).length > 0 && (
                        <div className="ht-section">
                          <h5 className="ht-title">命中教学规则 <span className="ht-title-sub">({(hyperProjectView.process_trace.matched_rules ?? []).length})</span></h5>
                          <div className="ht-matched-rules">
                            {(hyperProjectView.process_trace.matched_rules ?? []).map((r: string, ri: number) => (
                              <span key={ri} className="ht-rule-chip">{r}</span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* 超图质量评估（雷达图 + 维度深度热力图）已迁移至首页『知识库与知识图谱』→『质量评估』标签页 */}

                      {/* ── 8. Collapsible Details ── */}
                      <details className="ht-details-panel">
                        <summary className="ht-details-head">决策追踪与超边证据</summary>
                        <div className="ht-pipe-grid">
                          {[
                            ["KG实体", `${(latestResult?.kg_analysis?.entities ?? []).length} 个`],
                            ["覆盖度", `${hyperStudent.coverage_score}/10 (${coveredDims.length}覆盖/${missingDims.length}缺失)`],
                            ["闭环", `${hyperTemplateComplete}/${hyperTemplateMatches.length || 20} 完成`],
                            ["命中超边族", (hyperProjectView?.process_trace?.edge_families ?? []).join(", ") || "—"],
                            ["调用Agent", activeAgents.map(a => agentNames[a] ?? a).join(", ") || "—"],
                            ["RAG", `${kbU.hits_count ?? 0} 案例${kbU.neo4j_enriched ? ` · Neo4j增强${kbU.neo4j_enriched_count ?? 0}` : ""}`],
                          ].map(([k, v], i) => (
                            <div key={i} className="ht-pipe-row"><span className="ht-pipe-key">{k}</span><span className="ht-pipe-val">{v}</span></div>
                          ))}
                        </div>
                        {(hyperStudent.hub_entities ?? []).length > 0 && (
                          <div className="ht-hub-section">
                            <h6>枢纽实体</h6>
                            <div className="ht-hub-list">
                              {hyperStudent.hub_entities.map((h: any, hi: number) => (
                                <div key={hi} className="ht-hub-chip"><strong>{h.entity}</strong><span>{h.connections}维</span></div>
                              ))}
                            </div>
                        </div>
                      )}
                        {/* 命中超边按家族分类展示 */}
                        {hyperMatchedEdges.length > 0 && (() => {
                          const GRP_COLORS: Record<string, string> = {
                            "价值叙事与一致性": "#6b8aff", "用户-市场-需求": "#f06595",
                            "风险、证据与评分": "#ff6b6b", "执行、团队与里程碑": "#ffa94d",
                            "合规、监管与伦理": "#e8a84c", "单位经济与财务结构": "#20c997",
                            "产品差异化与竞争动态": "#845ef7", "增长、渠道与规模化": "#339af0",
                            "生态与多方利益": "#94d82d", "社会与ESG": "#66d9e8",
                          };
                          const famToGroup: Record<string, string> = {};
                          (hgCatalog?.families || []).forEach((f: any) => { famToGroup[f.family] = f.group; });
                          const grouped: Record<string, any[]> = {};
                          hyperMatchedEdges.forEach((e: any) => {
                            const grp = famToGroup[e.type || e.family] || "其他";
                            (grouped[grp] = grouped[grp] || []).push(e);
                          });
                          const sortedGroups = Object.entries(grouped).sort((a, b) => b[1].length - a[1].length);
                          return (
                            <div className="ht-grouped-edges">
                              <h6>命中超边分析 <span className="ht-edge-total">共 {hyperMatchedEdges.length} 条</span></h6>
                              {sortedGroups.map(([grp, edges]) => (
                                <details key={grp} className="ht-grp-detail" open={sortedGroups.indexOf([grp, edges]) === 0}>
                                  <summary className="ht-grp-summary">
                                    <span className="ht-grp-dot" style={{ background: GRP_COLORS[grp] || "var(--accent)" }} />
                                    <span className="ht-grp-name">{grp}</span>
                                    <span className="ht-grp-count">{edges.length}</span>
                                  </summary>
                                  <div className="ht-grp-edges">
                                    {edges.map((e: any, idx: number) => (
                                      <div key={e.hyperedge_id || `he-${idx}`} className="ht-edge-card">
                                        <div className="ht-edge-card-head">
                                          <span className="ht-edge-family-tag" style={{ borderColor: GRP_COLORS[grp] || "var(--accent)" }}>{e.family_label || e.type}</span>
                                          <span className="ht-edge-sup">支持度 {e.support ?? 0}</span>
                                          {e.severity && <span className={`ht-edge-sev-tag ht-sev-${e.severity}`}>{e.severity}</span>}
                                        </div>
                                        <p className="ht-edge-note-text">{e.teaching_note}</p>
                                        {(e.rules ?? []).length > 0 && (
                                          <div className="ht-edge-rules-row">{(e.rules as string[]).map((r: string, ri: number) => <span key={ri} className="ht-edge-rule">{r}</span>)}</div>
                                        )}
                                        {(e.nodes ?? []).length > 0 && (
                                          <div className="ht-edge-nodes">{(e.nodes as string[]).map((n: string, ni: number) => <span key={ni} className="ht-edge-node-tag">{n}</span>)}</div>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                </details>
                              ))}
                            </div>
                          );
                        })()}

                        {/* 超图库概览：折叠面板 */}
                        {hyperLibrary?.overview && (
                          <details className="ht-lib-detail">
                            <summary className="ht-lib-summary">
                              超图知识库
                              <span className="ht-lib-pills">
                                <span title="超图本体总家族数（静态）">{Number(((kbStats as any)?.hypergraph_local?.ontology_totals?.families) ?? 77)} 家族</span>
                                <span title="超图本体评分锚点模式数（静态）">{Number(((kbStats as any)?.hypergraph_local?.ontology_totals?.patterns) ?? 95)} 模式</span>
                                <span title="本项目已实例化的超边数量（动态）">本项目 {Number(hyperLibrary.overview.edge_count ?? 0)} 超边</span>
                              </span>
                            </summary>
                            <div className="ht-lib-body">
                              {hgCatalog?.groups && (
                                <div className="ht-cat-grid-v2">
                                  {(() => {
                                    const GRP_C: Record<string, string> = {
                                      "价值叙事与一致性": "#6b8aff", "用户-市场-需求": "#f06595",
                                      "风险、证据与评分": "#ff6b6b", "执行、团队与里程碑": "#ffa94d",
                                      "合规、监管与伦理": "#e8a84c", "单位经济与财务结构": "#20c997",
                                      "产品差异化与竞争动态": "#845ef7", "增长、渠道与规模化": "#339af0",
                                      "生态与多方利益": "#94d82d", "社会与ESG": "#66d9e8",
                                    };
                                    return (hgCatalog.groups as any[]).map((g: any) => {
                                      const hitFams = (hgCatalog.families || []).filter((f: any) => f.group === g.name && hyperMatchedEdges.some((e: any) => (e.type || e.family) === f.family));
                                      const isHit = hitFams.length > 0;
                                      const color = GRP_C[g.name] || "var(--accent)";
                                      return (
                                        <div key={g.name} className={`ht-cat-chip${isHit ? " ht-cat-chip-hit" : ""}`} style={{ borderColor: isHit ? color : "var(--border)" }}>
                                          <span className="ht-cat-chip-dot" style={{ background: color }} />
                                          <span className="ht-cat-chip-label">{g.name}</span>
                                          <span className="ht-cat-chip-num">{g.families}族·{g.edges}边</span>
                                          {isHit && <span className="ht-cat-chip-hit-badge">命中</span>}
                                        </div>
                                      );
                                    });
                                  })()}
                                </div>
                              )}
                            </div>
                          </details>
                        )}
                      </details>
                    </>);
                  })() : hyperMatchedEdges.length > 0 ? (
                    <div className="ht-insight-only">
                      <h5>超图教学洞察 <span className="ht-title-sub">(探索期)</span></h5>
                      <p className="ht-explore-note">项目还在初步探索阶段，超图引擎已为你匹配到以下教学启发。随着项目信息完善，将自动开启完整的维度覆盖、逻辑闭环、一致性分析。</p>

                      {/* Overview: summary + signals + key dims */}
                      {(hyperInsight?.summary || (hyperInsight?.top_signals ?? []).length > 0 || (hyperInsight?.key_dimensions ?? []).length > 0) && (
                        <div className="ht-section ht-overview-section">
                          {hyperInsight?.summary && <p className="ht-overview-summary">{hyperInsight.summary}</p>}
                          {(hyperInsight?.top_signals ?? []).length > 0 && (
                            <div className="ht-tag-group">
                              <span className="ht-tag-label">关键信号</span>
                              {(hyperInsight.top_signals ?? []).map((sig: string, si: number) => (
                                <span key={si} className="ht-tag signal">{sig}</span>
                              ))}
                            </div>
                          )}
                          {(hyperInsight?.key_dimensions ?? []).length > 0 && (
                            <div className="ht-tag-group">
                              <span className="ht-tag-label">焦点维度</span>
                              {(hyperInsight.key_dimensions ?? []).map((d: string, di: number) => (
                                <span key={di} className="ht-tag dim">{d}</span>
                              ))}
                            </div>
                          )}
                          {hyperInsight?.topology?.hub_nodes?.length > 0 && (
                            <div className="ht-tag-group">
                              <span className="ht-tag-label">枢纽节点</span>
                              {(hyperInsight.topology.hub_nodes ?? []).map((h: any, hi: number) => (
                                <span key={hi} className="ht-tag hub" title={h.interpretation}>{h.node} ({h.degree})</span>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      {/* 命中超边按家族分类 */}
                      {hyperMatchedEdges.length > 0 && (() => {
                        const GRP_COLORS: Record<string, string> = {
                          "价值叙事与一致性": "#6b8aff", "用户-市场-需求": "#f06595",
                          "风险、证据与评分": "#ff6b6b", "执行、团队与里程碑": "#ffa94d",
                          "合规、监管与伦理": "#e8a84c", "单位经济与财务结构": "#20c997",
                          "产品差异化与竞争动态": "#845ef7", "增长、渠道与规模化": "#339af0",
                          "生态与多方利益": "#94d82d", "社会与ESG": "#66d9e8",
                        };
                        const famToGroup: Record<string, string> = {};
                        (hgCatalog?.families || []).forEach((f: any) => { famToGroup[f.family] = f.group; });
                        const grouped: Record<string, any[]> = {};
                        hyperMatchedEdges.forEach((e: any) => {
                          const grp = famToGroup[e.type || e.family] || "其他";
                          (grouped[grp] = grouped[grp] || []).push(e);
                        });
                        return (
                          <div className="ht-grouped-edges">
                            <h6>命中超边分析 <span className="ht-edge-total">共 {hyperMatchedEdges.length} 条</span></h6>
                            {Object.entries(grouped).sort((a, b) => b[1].length - a[1].length).map(([grp, edges]) => (
                              <details key={grp} className="ht-grp-detail" open>
                                <summary className="ht-grp-summary">
                                  <span className="ht-grp-dot" style={{ background: GRP_COLORS[grp] || "var(--accent)" }} />
                                  <span className="ht-grp-name">{grp}</span>
                                  <span className="ht-grp-count">{edges.length}</span>
                                </summary>
                                <div className="ht-grp-edges">
                                  {edges.map((e: any, idx: number) => (
                                    <div key={e.hyperedge_id || `he-ex-${idx}`} className="ht-edge-card">
                                      <div className="ht-edge-card-head">
                                        <span className="ht-edge-family-tag" style={{ borderColor: GRP_COLORS[grp] || "var(--accent)" }}>{e.family_label || e.type}</span>
                                        <span className="ht-edge-sup">支持度 {e.support ?? 0}</span>
                                      </div>
                                      <p className="ht-edge-note-text">{e.teaching_note}</p>
                                      {(e.nodes ?? []).length > 0 && (
                                        <div className="ht-edge-nodes">{(e.nodes as string[]).map((n: string, ni: number) => <span key={ni} className="ht-edge-node-tag">{n}</span>)}</div>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              </details>
                            ))}
                          </div>
                        );
                      })()}

                      {/* Useful Cards (from project-view) */}
                      {hyperProjectView && (hyperProjectView?.useful_cards ?? []).length > 0 && (
                        <div className="ht-section">
                          <h5 className="ht-title">超图核心结论</h5>
                          <div className="ht-useful-grid-v2">
                            {(hyperProjectView.useful_cards ?? []).map((card: any, idx: number) => {
                              const toneIcons: Record<string, string> = { gap: "🔍", risk: "⚠", strength: "✦", default: "💡" };
                              const toneColors: Record<string, string> = { gap: "#ffa94d", risk: "#ff6b6b", strength: "#51cf66", default: "#6b8aff" };
                              const tone = card.tone || "default";
                              return (
                                <div key={idx} className={`ht-useful-card-v2 ht-tone-${tone}`} style={{ borderLeftColor: toneColors[tone] || toneColors.default }}>
                                  <div className="ht-ucard-header">
                                    <span className="ht-ucard-icon">{toneIcons[tone] || toneIcons.default}</span>
                                    <strong className="ht-ucard-title">{card.title}</strong>
                                    {card.importance && <span className="ht-ucard-imp">{card.importance}</span>}
                                  </div>
                                  <p className="ht-ucard-summary">{card.summary}</p>
                                  {card.reason && <div className="ht-ucard-reason">{card.reason}</div>}
                                  {card.project_hint && <div className="ht-ucard-hint">{card.project_hint}</div>}
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {/* Agent/Dimension hyper insights (V3: from agent_hyper_details) */}
                      {(() => {
                        const hyperDetails: any[] = latestResult?.agent_trace?.agent_hyper_details ?? [];
                        const dimLabelsMap: Record<string, string> = {
                          status_judgment: "项目状态", core_bottleneck: "核心瓶颈", structural_cause: "结构原因",
                          counter_intuitive: "反直觉洞察", method_bridge: "方法桥接", teacher_criteria: "评审标准",
                          external_reference: "外部案例", strategy_directions: "策略方向", action_plan: "行动方案",
                          probing_questions: "启发追问",
                        };
                        if (hyperDetails.length === 0) {
                          const roleAgents: Record<string, any> = latestResult?.agent_trace?.role_agents ?? {};
                          const agentsCalled: string[] = latestResult?.agent_trace?.orchestration?.agents_called ?? [];
                          const activeAgents = agentsCalled.length > 0 ? agentsCalled : Object.keys(roleAgents).filter(k => roleAgents[k]?.analysis);
                          const agentNames: Record<string, string> = { coach: "教练", analyst: "分析师", advisor: "顾问", grader: "评分官", planner: "规划师", tutor: "导师" };
                          const anyHyper = activeAgents.some(a => String((roleAgents[a] ?? {}).hyper_context_sent ?? "").trim().length > 0);
                          if (!anyHyper) return null;
                          return (
                            <div className="ht-section">
                              <h5 className="ht-title">各Agent接收的超图启发</h5>
                              {activeAgents.filter(a => String((roleAgents[a] ?? {}).hyper_context_sent ?? "").trim()).map(a => {
                                const ctx = String((roleAgents[a] ?? {}).hyper_context_sent ?? "");
                                const lines = ctx.split("\n").filter((l: string) => l.trim());
                                return (
                                  <details key={a} className="ht-agent-detail collapsible-section">
                                    <summary>{agentNames[a] ?? a} ({lines.length} 条)</summary>
                                    <div className="ht-agent-detail-body">
                                      {lines.map((line: string, li: number) => (
                                        <div key={li} className="ht-signal-row">
                                          <span className="ht-signal-text">{line.replace(/^[^:：]+[:：]\s*/, "").trim() || line}</span>
                                        </div>
                                      ))}
                                    </div>
                                  </details>
                                );
                              })}
                            </div>
                          );
                        }
                        return (
                          <div className="ht-section">
                            <h5 className="ht-title">各维度接收的超图启发 ({hyperDetails.length})</h5>
                            {hyperDetails.map((hd: any, i: number) => {
                              const lines = String(hd.hyper ?? "").split("\n").filter((l: string) => l.trim());
                              return (
                                <details key={i} className="ht-agent-detail collapsible-section">
                                  <summary>{dimLabelsMap[hd.dim] ?? hd.dim} ({lines.length} 条)</summary>
                                  <div className="ht-agent-detail-body">
                                    {lines.map((line: string, li: number) => (
                                      <div key={li} className="ht-signal-row">
                                        <span className="ht-signal-text">{line.replace(/^[^:：]+[:：]\s*/, "").trim() || line}</span>
                                      </div>
                                    ))}
                                  </div>
                                </details>
                              );
                            })}
                          </div>
                        );
                      })()}

                      {/* Matched rules from process_trace */}
                      {(hyperProjectView?.process_trace?.matched_rules ?? []).length > 0 && (
                        <div className="ht-section">
                          <h5 className="ht-title">命中教学规则</h5>
                          <div className="ht-matched-rules">
                            {(hyperProjectView.process_trace.matched_rules ?? []).map((r: string, ri: number) => (
                              <span key={ri} className="ht-rule-chip">{r}</span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Library stats */}
                      {hyperLibrary?.overview && (
                        <details className="ht-lib-detail">
                          <summary className="ht-lib-summary">
                            超图知识库
                            <span className="ht-lib-pills">
                              <span title="超图本体总家族数（静态）">{Number(((kbStats as any)?.hypergraph_local?.ontology_totals?.families) ?? 77)} 家族</span>
                              <span title="超图本体评分锚点模式数（静态）">{Number(((kbStats as any)?.hypergraph_local?.ontology_totals?.patterns) ?? 95)} 模式</span>
                              <span title="本项目已实例化的超边数量（动态）">本项目 {Number(hyperLibrary.overview.edge_count ?? 0)} 超边</span>
                            </span>
                          </summary>
                          <div className="ht-lib-body">
                            {hgCatalog?.groups && (
                              <div className="ht-cat-grid-v2">
                                {(hgCatalog.groups as any[]).map((g: any) => {
                                  const GRP_COLORS: Record<string, string> = {
                                    "价值叙事与一致性": "#6b8aff", "用户-市场-需求": "#f06595",
                                    "风险、证据与评分": "#ff6b6b", "执行、团队与里程碑": "#ffa94d",
                                    "合规、监管与伦理": "#e8a84c", "单位经济与财务结构": "#20c997",
                                    "产品差异化与竞争动态": "#845ef7", "增长、渠道与规模化": "#339af0",
                                    "生态与多方利益": "#94d82d", "社会与ESG": "#66d9e8",
                                  };
                                  const hitFams = (hgCatalog.families || []).filter((f: any) => f.group === g.name && hyperMatchedEdges.some((e: any) => (e.type || e.family) === f.family));
                                  const isHit = hitFams.length > 0;
                                  const color = GRP_COLORS[g.name] || "var(--accent)";
                                  return (
                                    <div key={g.name} className={`ht-cat-chip${isHit ? " ht-cat-chip-hit" : ""}`} style={{ borderColor: isHit ? color : "var(--border)" }}>
                                      <span className="ht-cat-chip-dot" style={{ background: color }} />
                                      <span className="ht-cat-chip-label">{g.name}</span>
                                      <span className="ht-cat-chip-num">{g.families}族·{g.edges}边</span>
                                      {isHit && <span className="ht-cat-chip-hit-badge">命中</span>}
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                          </div>
                        </details>
                      )}
                    </div>
                  ) : (
                    <div className="ht-empty-guide">
                      <h5>什么是超图分析？</h5>
                      <p>超图引擎从 <strong>15 个关键维度</strong> 检测你的项目完整度，并与 <strong>89 个历史案例</strong> 的结构模式对比：</p>
                      <div className="ht-guide-dims">
                        {["目标用户","痛点","方案","创新点","市场","竞品","商业模式","执行步骤","风控合规","证据","技术","资源","团队","风险","渠道"].map((d,i) => (
                          <span key={i} className="ht-guide-chip">{d}</span>
                        ))}
                      </div>
                      <p className="ht-guide-sub">发送项目描述或上传商业计划书后，AI 会自动分析维度覆盖、逻辑闭环、一致性问题，并将超图启发注入各个 Agent。</p>
                    </div>
                  )}
                </div>
              )}

              {rightTab === "cases" && (() => {
                const kbUtil = latestResult?.agent_trace?.kb_utilization ?? latestResult?.kb_utilization ?? {};
                const enriched = kbUtil.neo4j_enriched ?? false;
                const enrichedCount = kbUtil.neo4j_enriched_count ?? 0;
                const hitCount = kbUtil.hits_count ?? ragCases.length;
                const dc = kbUtil.dual_channel ?? {};
                const gHits: any[] = Array.isArray(dc.graph_details) ? dc.graph_details : [];
                const gCount = dc.graph_hits ?? 0;
                const insightSrc = latestResult?.insight_sources ?? {};
                const caseInsight = insightSrc.case_transfer_insight ?? "";
                const hyperNarr = insightSrc.hyper_narrative ?? "";
                const dimLabels: Record<string, string> = {
                  pain_point: "痛点", solution: "方案", innovation: "创新点",
                  business_model: "商业模式", evidence: "证据", market: "市场",
                  stakeholder: "用户", risk: "风险", channel: "渠道",
                };
                const sourceLabels: Record<string, string> = { shared_node: "共享节点", complement: "结构互补", keyword: "关键词" };
                return (
                <div className="right-section cs-panel">
                  <h4>案例参考</h4>
                  <p className="cs-desc">从 <strong>{Number((kbStats as any)?.neo4j?.total_projects ?? (kbStats as any)?.rag?.corpus_count ?? 0) || "—"}</strong> 个标准案例库中检索到 <strong>{hitCount}</strong> 个参考{enriched ? `，其中 ${enrichedCount} 个经图谱深度增强` : ""}</p>

                  {/* ── 1. Graph-Based Cross-Project Insights (TOP PRIORITY) ── */}
                  {gHits.length > 0 && (
                    <details className="cs-graph-section collapsible-section" open>
                      <summary className="cs-sec-title">跨项目图谱启发 ({gCount})</summary>
                      <p className="cs-sec-desc">基于 Neo4j 知识图谱，发现与你项目在结构维度上相关的案例</p>
                      {gHits.map((gh: any, gi: number) => {
                        const ctx = gh.context ?? {};
                        const matchSources: string[] = Array.isArray(gh.match_sources) ? gh.match_sources : [];
                        const matchedDims: string[] = Array.isArray(gh.matched_dimensions) ? gh.matched_dimensions : [];
                        const matchedNodes: string[] = Array.isArray(gh.matched_nodes) ? gh.matched_nodes : [];
                        const ctxPains: string[] = Array.isArray(ctx.pains) ? ctx.pains : [];
                        const ctxSolutions: string[] = Array.isArray(ctx.solutions) ? ctx.solutions : [];
                        const ctxInnovations: string[] = Array.isArray(ctx.innovations) ? ctx.innovations : [];
                        const ctxBiz: string[] = Array.isArray(ctx.biz_models) ? ctx.biz_models : [];
                        const ctxEv: string[] = Array.isArray(ctx.evidences) ? ctx.evidences : [];
                        const hasCtx = ctxPains.length > 0 || ctxSolutions.length > 0 || ctxInnovations.length > 0 || ctxBiz.length > 0;
                        return (
                          <div key={gi} className="cs-graph-card">
                            <div className="cs-gc-head">
                              <span className="cs-gc-name">{gh.project_name || gh.project_id || "未知项目"}</span>
                              {gh.category && <span className="cs-gc-cat">{gh.category}</span>}
                              {matchSources.map((s: string) => <span key={s} className="cs-gc-src">{sourceLabels[s] ?? s}</span>)}
                            </div>
                            {matchedDims.length > 0 && (
                              <div className="cs-gc-dims">
                                <span className="cs-gc-dims-label">共享维度</span>
                                {matchedDims.map((d: string) => <span key={d} className="cs-gc-dim-chip">{dimLabels[d] ?? d}</span>)}
                              </div>
                            )}
                            {matchedNodes.length > 0 && (
                              <div className="cs-gc-nodes">
                                {matchedNodes.slice(0, 8).map((n: string, ni: number) => {
                                  const parts = String(n).split(":");
                                  const dt = parts.length > 1 ? parts[0] : "";
                                  const nn = parts.length > 1 ? parts.slice(1).join(":") : n;
                                  return (
                                    <div key={ni} className="cs-gc-node">
                                      {dt && <span className="cs-gc-node-type">{dimLabels[dt] ?? dt}</span>}
                                      <span className="cs-gc-node-name">{nn}</span>
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                            {hasCtx && (
                              <div className="cs-gc-ctx">
                                <div className="cs-gc-ctx-title">该项目的做法</div>
                                <div className="cs-gc-ctx-grid">
                                  {ctxPains.length > 0 && <div className="cs-gc-ctx-cell"><span className="cs-gc-ctx-label">痛点</span><div className="cs-gc-ctx-tags">{ctxPains.map((p, i) => <span key={i} className="cs-gc-ctx-tag cs-tag-pain">{p}</span>)}</div></div>}
                                  {ctxSolutions.length > 0 && <div className="cs-gc-ctx-cell"><span className="cs-gc-ctx-label">方案</span><div className="cs-gc-ctx-tags">{ctxSolutions.map((s, i) => <span key={i} className="cs-gc-ctx-tag cs-tag-sol">{s}</span>)}</div></div>}
                                  {ctxInnovations.length > 0 && <div className="cs-gc-ctx-cell"><span className="cs-gc-ctx-label">创新</span><div className="cs-gc-ctx-tags">{ctxInnovations.map((n, i) => <span key={i} className="cs-gc-ctx-tag cs-tag-inn">{n}</span>)}</div></div>}
                                  {ctxBiz.length > 0 && <div className="cs-gc-ctx-cell"><span className="cs-gc-ctx-label">商业</span><div className="cs-gc-ctx-tags">{ctxBiz.map((b, i) => <span key={i} className="cs-gc-ctx-tag cs-tag-biz">{b}</span>)}</div></div>}
                                  {ctxEv.length > 0 && <div className="cs-gc-ctx-cell"><span className="cs-gc-ctx-label">证据</span><div className="cs-gc-ctx-tags">{ctxEv.map((e, i) => <span key={i} className="cs-gc-ctx-tag cs-tag-ev">{e}</span>)}</div></div>}
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </details>
                  )}

                  {/* ── 2. AI Insights (if available) ── */}
                  {(caseInsight || hyperNarr) && (
                    <div className="cs-insight-section">
                      {caseInsight && (
                        <div className="cs-insight-card">
                          <div className="cs-insight-label">案例迁移洞察</div>
                          <div className="cs-insight-body">{caseInsight}</div>
                        </div>
                      )}
                      {hyperNarr && (
                        <div className="cs-insight-card">
                          <div className="cs-insight-label">超图结构叙事</div>
                          <div className="cs-insight-body">{hyperNarr}</div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* ── 3. RAG Case Cards ── */}
                  {ragCases.length > 0 ? (
                    <div className="cs-cases-list">
                      <h5 className="cs-sec-title">语义检索案例 ({ragCases.length})</h5>
                      {ragCases.map((c: any, ci: number) => {
                    const simPct = Math.round((c.similarity ?? 0) * 100);
                    const simColor = simPct >= 70 ? "var(--accent-green)" : simPct >= 40 ? "var(--accent-yellow)" : "var(--text-muted)";
                        const gPains: string[] = Array.isArray(c.graph_pains) ? c.graph_pains : [];
                        const gSols: string[] = Array.isArray(c.graph_solutions) ? c.graph_solutions : [];
                        const gInns: string[] = Array.isArray(c.graph_innovations) ? c.graph_innovations : [];
                        const gBiz: string[] = Array.isArray(c.graph_biz_models) ? c.graph_biz_models : [];
                        const gEvSamples: any[] = Array.isArray(c.graph_evidence_samples) ? c.graph_evidence_samples : [];
                        const gEvCount = c.graph_evidence_count ?? 0;
                        const hasGraphData = !!c.neo4j_enriched;
                        const overlap = c.rule_overlap ?? {};
                        const shared: string[] = Array.isArray(overlap.shared) ? overlap.shared : [];
                        const onlyCase: string[] = Array.isArray(overlap.only_in_case) ? overlap.only_in_case : [];
                        const onlyStudent: string[] = Array.isArray(overlap.only_in_student) ? overlap.only_in_student : [];
                        const gRubricCov: string[] = Array.isArray(c.graph_rubric_covered) ? c.graph_rubric_covered : [];
                        const gRubricUnc: string[] = Array.isArray(c.graph_rubric_uncovered) ? c.graph_rubric_uncovered : [];
                        const hasGraphDims = gPains.length > 0 || gSols.length > 0 || gInns.length > 0 || gBiz.length > 0;
                    return (
                          <details key={ci} className="cs-case-card" open={ci === 0}>
                            <summary className="cs-case-head">
                              <div className="cs-case-left">
                                <span className="cs-case-name">{c.project_name ?? c.case_id}</span>
                                {c.category && <span className="cs-case-cat">{c.category}</span>}
                                {hasGraphData && <span className="cs-case-graph-badge">图谱增强</span>}
                          </div>
                              <div className="cs-case-sim">
                                <svg viewBox="0 0 36 36" width="32" height="32">
                              <circle cx="18" cy="18" r="14" fill="none" stroke="var(--border)" strokeWidth="3" />
                              <circle cx="18" cy="18" r="14" fill="none" stroke={simColor} strokeWidth="3" strokeLinecap="round" strokeDasharray={`${simPct * 0.88} 88`} transform="rotate(-90 18 18)" />
                            </svg>
                                <span className="cs-sim-num">{simPct}%</span>
                          </div>
                        </summary>
                            <div className="cs-case-body">
                              {c.summary && <p className="cs-case-summary">{c.summary}</p>}

                              {hasGraphDims && (
                                <div className="cs-case-dims">
                                  {gPains.length > 0 && <div className="cs-cd-row"><span className="cs-cd-label">痛点</span><div className="cs-cd-tags">{gPains.map((p, i) => <span key={i} className="cs-cd-tag cs-tag-pain">{p}</span>)}</div></div>}
                                  {gSols.length > 0 && <div className="cs-cd-row"><span className="cs-cd-label">方案</span><div className="cs-cd-tags">{gSols.map((s, i) => <span key={i} className="cs-cd-tag cs-tag-sol">{s}</span>)}</div></div>}
                                  {gInns.length > 0 && <div className="cs-cd-row"><span className="cs-cd-label">创新</span><div className="cs-cd-tags">{gInns.map((n, i) => <span key={i} className="cs-cd-tag cs-tag-inn">{n}</span>)}</div></div>}
                                  {gBiz.length > 0 && <div className="cs-cd-row"><span className="cs-cd-label">商业</span><div className="cs-cd-tags">{gBiz.map((b, i) => <span key={i} className="cs-cd-tag cs-tag-biz">{b}</span>)}</div></div>}
                                </div>
                              )}

                              {(shared.length > 0 || onlyCase.length > 0 || onlyStudent.length > 0) && (
                                <div className="cs-rule-overlap">
                                  <span className="cs-ro-title">风险规则对比</span>
                                  <div className="cs-ro-tags">
                                    {shared.map((r) => <span key={r} className="cs-ro-tag cs-ro-shared">{r}</span>)}
                                    {onlyCase.map((r) => <span key={r} className="cs-ro-tag cs-ro-case">{r}</span>)}
                                    {onlyStudent.map((r) => <span key={r} className="cs-ro-tag cs-ro-student">{r}</span>)}
                                  </div>
                                  <div className="cs-ro-legend">
                                    {shared.length > 0 && <span><span className="cs-ro-dot" style={{background:"var(--accent-yellow)"}} />共同</span>}
                                    {onlyCase.length > 0 && <span><span className="cs-ro-dot" style={{background:"var(--text-muted)"}} />仅案例</span>}
                                    {onlyStudent.length > 0 && <span><span className="cs-ro-dot" style={{background:"var(--accent-red,#e74c3c)"}} />仅你</span>}
                                  </div>
                                </div>
                              )}

                              {(gRubricCov.length > 0 || gRubricUnc.length > 0) && (
                                <div className="cs-rubric">
                                  <span className="cs-rubric-title">评分维度</span>
                                  <div className="cs-rubric-chips">
                                    {gRubricCov.map((r) => <span key={r} className="cs-rub-chip cs-rub-cov">{r}</span>)}
                                    {gRubricUnc.map((r) => <span key={r} className="cs-rub-chip cs-rub-unc">{r}</span>)}
                                  </div>
                                </div>
                              )}

                              {!hasGraphData && (
                                <>
                                  {Array.isArray(c.pain_points) && c.pain_points.length > 0 && <div className="cs-field"><strong>痛点：</strong>{c.pain_points.join("；")}</div>}
                                  {Array.isArray(c.solution) && c.solution.length > 0 && <div className="cs-field"><strong>方案：</strong>{c.solution.join("；")}</div>}
                                  {Array.isArray(c.innovation_points) && c.innovation_points.length > 0 && <div className="cs-field"><strong>创新点：</strong>{c.innovation_points.join("；")}</div>}
                                </>
                              )}

                              {gEvCount > 0 && gEvSamples.length > 0 && (
                                <div className="cs-evidence">
                                  <span className="cs-ev-title">证据链 ({gEvCount})</span>
                                  {gEvSamples.slice(0, 3).map((e: any, ei: number) => <blockquote key={ei} className="cs-ev-quote">{e.type && <span className="cs-ev-type">[{e.type}]</span>} {e.quote ?? String(e)}</blockquote>)}
                                </div>
                              )}

                              {Array.isArray(c.risk_flags) && c.risk_flags.length > 0 && <div className="cs-field"><strong>风险标记：</strong>{c.risk_flags.join("、")}</div>}
                        </div>
                      </details>
                    );
                      })}
                </div>
                  ) : <p className="right-hint">发送项目描述后，这里会显示知识库中最相似的参考案例</p>}
                </div>
                );
              })()}

              {rightTab === "feedback" && (
                <div className="right-section">
                  <h4>教师批注</h4>
                  <div className="panel-desc">这里会显示老师给你的带划线批注版本、阶段性反馈，以及你被批注后又进行了哪些后续修改。</div>
                  {teacherAnnotationBoards.length > 0 && (
                    <div className="student-feedback-board-list">
                      {teacherAnnotationBoards.map((board: any) => (
                        <button
                          key={board.submission_id}
                          className={`student-feedback-board-chip ${selectedAnnotationBoardId === board.submission_id ? "active" : ""}`}
                          onClick={() => setSelectedAnnotationBoardId(board.submission_id)}
                        >
                          <strong>{board.project_display_name || "项目批注"}</strong>
                          <span>{board.material_display_name || "材料"} · {board.annotation_count} 条批注</span>
                        </button>
                      ))}
                    </div>
                  )}
                  {(() => {
                    const activeBoard = teacherAnnotationBoards.find((item: any) => item.submission_id === selectedAnnotationBoardId) || teacherAnnotationBoards[0];
                    return activeBoard ? (
                      <div className="student-feedback-reader">
                        <div className="student-feedback-reader-head">
                          <div>
                            <strong>{activeBoard.project_display_name}</strong>
                            <div className="msg-time">{activeBoard.material_display_name} · {formatBjTime(activeBoard.created_at, true)}</div>
                          </div>
                          {activeBoard.download_url && (
                            <a href={`${API_BASE}${activeBoard.download_url}`} target="_blank" rel="noreferrer" className="tch-sm-btn">下载原文件</a>
                          )}
                        </div>
                        {renderAnnotatedStudentText(activeBoard.raw_text, activeBoard.latest_annotations)}
                        <div className="student-annotation-list">
                          {(activeBoard.latest_annotations || []).map((item: any) => {
                            const tone = annotationStyle(item.annotation_type);
                            return (
                              <div key={item.annotation_item_id} className={`student-annotation-item ${tone.cls}`}>
                                <strong>{tone.label}</strong>
                                {item.quote && <blockquote>“{item.quote}”</blockquote>}
                                <p>{item.content || item.overall_feedback}</p>
                                <span className="msg-time">{formatBjTime(item.created_at, true)}</span>
                              </div>
                            );
                          })}
                        </div>
                        {activeBoard.followup_submissions?.length > 0 && (
                          <div className="student-followup-strip">
                            {activeBoard.followup_submissions.map((item: any) => (
                              <div key={item.submission_id} className="right-card">
                                <strong>你后续又提交了一版</strong>
                                <p>{item.text_preview}</p>
                                <span className="msg-time">{formatBjTime(item.created_at, true)}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ) : null;
                  })()}
                  {teacherFeedback.length > 0 ? teacherFeedback.map((fb, fi) => (
                    <div key={fi} className="right-card">
                      <p>{fb.comment}</p>
                      <span className="msg-time">{fb.teacher_id} · {formatBjTime(fb.created_at, true)}</span>
                      {(fb.focus_tags ?? []).length > 0 && <div className="tch-tag-row">{fb.focus_tags.map((t: string) => <span key={t} className="tch-tag">{t}</span>)}</div>}
                    </div>
                  )) : (!teacherAnnotationBoards.length && <p className="right-hint">暂无教师批注。导师批注后会显示在这里。</p>)}
                </div>
              )}

              {rightTab === "interventions" && (
                <div className="right-section">
                  <h4>教师干预 / 任务</h4>
                  <div className="panel-desc">这是老师审核后正式下发给你的行动任务。优先看这里，再和 AI 继续迭代。</div>
                  {teacherInterventions.length > 0 ? teacherInterventions.map((item: any, idx: number) => (
                    <div key={item.intervention_id || idx} className="right-card">
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start" }}>
                        <strong>{item.title}</strong>
                        <span className={`risk-badge ${item.priority === "high" ? "high" : item.priority === "low" ? "low" : ""}`}>{item.priority === "high" ? "高优先" : item.priority === "low" ? "低优先" : "中优先"}</span>
                      </div>
                      <p style={{ marginTop: 10 }}>{item.reason_summary}</p>
                      {(item.action_items ?? []).length > 0 && (
                        <div className="rag-case-field"><strong>老师希望你先做：</strong>{item.action_items.join("；")}</div>
                      )}
                      {(item.acceptance_criteria ?? []).length > 0 && (
                        <div className="rag-case-field"><strong>验收标准：</strong>{item.acceptance_criteria.join("；")}</div>
                      )}
                      <div className="msg-time" style={{ marginTop: 8 }}>
                        {item.scope_type === "project" ? "项目任务" : item.scope_type === "team" ? "团队任务" : "个人任务"} · {item.status} · {formatBjTime(item.sent_at || item.created_at, true)}
                      </div>
                      {item.status === "sent" && (
                        <button className="tch-sm-btn" style={{ marginTop: 10 }} onClick={() => markInterventionViewed(item.intervention_id)}>标记已查看</button>
                      )}
                    </div>
                  )) : <p className="right-hint">暂无教师下发任务。老师审核并发送后会显示在这里。</p>}
                </div>
              )}

              {rightTab === "debug" && (
                <div className="right-section">
                  <div className="panel-desc">系统内部运行状态，开发调试用。</div>
                  <div className="debug-row"><span>识别意图</span><span>{orchestration?.intent ?? "-"}</span></div>
                  <div className="debug-row"><span>意图形态</span><span>{orchestration?.intent_shape ?? "-"}</span></div>
                  <div className="debug-row"><span>置信度</span><span>{orchestration?.confidence ?? "-"}</span></div>
                  <div className="debug-row"><span>识别引擎</span><span>{{ rule: "关键词匹配", llm: "LLM分类", follow_up: "追问继承", file_detect: "文件检测", heuristic_long: "长文启发", heuristic_short: "短文启发" }[orchestration?.engine as string] ?? orchestration?.engine ?? "-"}</span></div>
                  <div className="debug-row"><span>调用Agent</span><span>{(orchestration?.agents_called ?? []).join(" → ") || "-"}</span></div>
                  <div className="debug-row"><span>最终Agent</span><span>{(orchestration?.resolved_agents ?? []).join(" → ") || "-"}</span></div>
                  <div className="debug-row"><span>执行管线</span><span>{(orchestration?.pipeline ?? []).join(" → ") || "-"}</span></div>
                  <div className="debug-row"><span>编排策略</span><span>{orchestration?.strategy ?? "-"}</span></div>
                  <div className="debug-row"><span>LLM启用</span><span>{String(orchestration?.llm_enabled ?? false)}</span></div>
                  <div className="debug-row"><span>识别理由</span><span>{orchestration?.intent_reason ?? "-"}</span></div>
                  <div className="debug-row"><span>编排理由</span><span>{orchestration?.agent_reasoning ?? "-"}</span></div>
                  <div className="debug-row"><span>会话ID</span><span className="debug-conv-id">{conversationId ?? "无"}</span></div>
                  <div className="debug-row"><span>超图(顶层)</span><span>{hyperStudent?.ok ? `覆盖${hyperStudent.coverage_score}/10` : "无"}</span></div>
                  <div className="debug-row"><span>教学超边</span><span>{hyperMatchedEdges.length > 0 ? `${hyperMatchedEdges.length}条` : "无"}</span></div>
                  <div className="debug-row"><span>超图(累积)</span><span>{hyperStudent?.ok ? `覆盖${hyperStudent.coverage_score}/10` : "无"}</span></div>
                  <div className="debug-row"><span>谬误识别</span><span>{pressureTrace?.fallacy_label ?? "-"}</span></div>
                  <div className="debug-row"><span>追问策略</span><span>{pressureTrace?.selected_strategy ?? "-"}</span></div>
                  <div className="debug-row"><span>超边类型</span><span>{((pressureTrace?.retrieved_heterogeneous_subgraph ?? []).map((x: any) => x?.edge_type).filter(Boolean).join(" / ")) || "-"}</span></div>
                  <div className="debug-row"><span>超边ID</span><span>{((pressureTrace?.retrieved_heterogeneous_subgraph ?? []).map((x: any) => x?.hyperedge_id).filter(Boolean).join(" / ")) || "-"}</span></div>
                  <div className="debug-row"><span>生成追问</span><span>{pressureTrace?.generated_question ?? "-"}</span></div>
                  <div className="debug-row"><span>KG实体(累积)</span><span>{kgAnalysis?.entities?.length ?? 0}</span></div>
                  <div className="debug-row"><span>历史轮次</span><span>{resultHistory.length}</span></div>
                  <details className="debug-json"><summary>原始 JSON</summary><pre>{JSON.stringify(latestResult, null, 2) ?? "暂无"}</pre></details>
                </div>
              )}
            </div>
          </aside>
        )}
      </div>

      {/* ═══ Document Review Panel (slides in from the right) ═══ */}
      {docReviewOpen && docReview && (
        <div className="doc-review-overlay" onClick={(e) => { if (e.target === e.currentTarget) setDocReviewOpen(false); }}>
          <div className="doc-review-panel">
            <div className="doc-review-header">
              <div className="doc-review-title">
                <span className="doc-review-icon">📄</span>
                <div>
                  <span>文档审阅</span>
                  <span className="doc-review-filename">{docReview.filename}</span>
                </div>
              </div>
              <div className="doc-review-header-actions">
                {docReview.annotations.length > 0 && (
                  <span className="doc-review-stat">
                    {docReview.annotations.filter((a: any) => a.type === "issue").length} 个问题 · {docReview.annotations.filter((a: any) => a.type === "suggestion").length} 个建议 · {docReview.annotations.filter((a: any) => a.type === "praise").length} 个亮点
                  </span>
                )}
                <button className="doc-review-close" onClick={() => setDocReviewOpen(false)}>✕</button>
              </div>
            </div>

            {/* Section quick nav */}
            {docReview.sections.length > 3 && (
              <div className="doc-nav-bar">
                {docReview.sections.map((sec) => {
                  const hasAnnot = docReview.annotations.some((a: any) => a.section_id === sec.id);
                  const hasIssue = docReview.annotations.some((a: any) => a.section_id === sec.id && a.type === "issue");
                  return (
                    <button
                      key={sec.id}
                      className={`doc-nav-dot ${hasIssue ? "issue" : hasAnnot ? "annotated" : ""}`}
                      title={`${sec.source} ${hasIssue ? "(有问题)" : hasAnnot ? "(有批注)" : ""}`}
                      onClick={() => document.getElementById(`doc-sec-${sec.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" })}
                    />
                  );
                })}
              </div>
            )}

            {docReviewLoading && (
              <div className="doc-review-loading">
                <div className="typing-dots"><span /><span /><span /></div>
                <span>AI 正在逐段分析你的文档...</span>
              </div>
            )}

            <div
              className="doc-review-body"
              onMouseUp={() => {
                const sel = window.getSelection();
                const text = sel?.toString().trim() ?? "";
                if (text.length > 5 && text.length < 500) {
                  const range = sel?.getRangeAt(0);
                  const rect = range?.getBoundingClientRect();
                  if (rect) {
                    setDocSelectedText(text);
                    setDocAskPos({ x: rect.left + rect.width / 2, y: rect.top - 10 });
                  }
                } else {
                  setDocSelectedText("");
                  setDocAskPos(null);
                }
              }}
            >
              {docReview.sections.map((sec) => {
                const annots = docReview.annotations.filter((a: any) => a.section_id === sec.id);
                return (
                  <div key={sec.id} id={`doc-sec-${sec.id}`} className={`doc-section ${annots.length > 0 ? "has-annot" : ""}`}>
                    <div className="doc-section-source">
                      <span className="doc-section-num">§{sec.id + 1}</span>
                      {sec.source}
                    </div>
                    <div className="doc-section-text">{sec.text}</div>
                    {annots.map((a: any, ai: number) => (
                      <div key={ai} className={`doc-annot doc-annot-${a.type}`}>
                        <span className="doc-annot-badge">
                          {{ praise: "✅ 亮点", issue: "⚠️ 问题", suggestion: "💡 建议", question: "❓ 追问" }[a.type as string] ?? a.type}
                        </span>
                        <span className="doc-annot-text">{a.comment}</span>
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>

            {/* Floating "ask about selection" popup */}
            {docSelectedText && docAskPos && (
              <div className="doc-ask-popup" style={{ left: docAskPos.x, top: docAskPos.y }}>
                <button
                  className="doc-ask-btn"
                  onClick={() => {
                    setInput(`关于这段内容请帮我分析：「${docSelectedText.slice(0, 200)}」`);
                    setDocSelectedText("");
                    setDocAskPos(null);
                    setDocReviewOpen(false);
                    setTimeout(() => textareaRef.current?.focus(), 100);
                  }}
                >
                  🤖 询问AI关于这段
                </button>
                <button
                  className="doc-ask-btn secondary"
                  onClick={() => {
                    setInput(`这段内容有什么问题吗？如何改进？\n\n「${docSelectedText.slice(0, 200)}」`);
                    setDocSelectedText("");
                    setDocAskPos(null);
                    setDocReviewOpen(false);
                    setTimeout(() => textareaRef.current?.focus(), 100);
                  }}
                >
                  🔍 帮我改进这段
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
