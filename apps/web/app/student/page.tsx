"use client";

import { Children, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import ReactMarkdown from "react-markdown";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });
import remarkGfm from "remark-gfm";
import { useAuth, logout } from "../hooks/useAuth";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8037").trim().replace(/\/+$/, "");

type ChatMessage = { role: "user" | "assistant"; text: string; ts?: string; id: number };
type RightTab = "agents" | "task" | "risk" | "score" | "kg" | "hyper" | "cases" | "feedback" | "interventions" | "debug";
type ConvMeta = { conversation_id: string; title: string; created_at: string; message_count: number; last_message: string };

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
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [teacherFeedback, setTeacherFeedback] = useState<any[]>([]);
  const [teacherAnnotationBoards, setTeacherAnnotationBoards] = useState<any[]>([]);
  const [selectedAnnotationBoardId, setSelectedAnnotationBoardId] = useState("");
  const [teacherInterventions, setTeacherInterventions] = useState<any[]>([]);
  const [convSidebarOpen, setConvSidebarOpen] = useState(true);
  const [conversations, setConversations] = useState<ConvMeta[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [attachedFile, setAttachedFile] = useState<File | null>(null);

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
  const [kbStats, setKbStats] = useState<any>(null);
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

  useEffect(() => {
    fetch(`${API_BASE}/api/kb-stats`).then(r => r.json()).then(d => setKbStats(d)).catch(() => {});
  }, []);

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
      const rawMsgs = d.messages ?? [];
      const msgs: ChatMessage[] = rawMsgs.map((m: any) => ({
        role: m.role as "user" | "assistant",
        text: m.content ?? "",
        ts: m.timestamp ? formatBjTime(m.timestamp) : undefined,
        id: ++_msgId,
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
        form.set("message", text);
        form.set("conversation_id", conversationId ?? "");
        form.set("mode", mode);
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
            conversation_id: conversationId || undefined,
            class_id: classId || undefined, cohort_id: cohortId || undefined,
            message: text, mode,
            competition_type: mode === "competition" ? competitionType : "",
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
      setMessages((p) => p.map((m) => m.id === typeMsgId ? { ...m, text: reply } : m));

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

  const rubric = useMemo(() => {
    if (resultHistory.length === 0) return latestResult?.diagnosis?.rubric ?? [];
    const merged: Record<string, { item: string; scores: number[]; weight: number }> = {};
    for (const r of resultHistory) {
      for (const row of r?.diagnosis?.rubric ?? []) {
        if (!merged[row.item]) merged[row.item] = { item: row.item, scores: [], weight: row.weight ?? 0 };
        merged[row.item].scores.push(row.score);
      }
    }
    return Object.values(merged).map((m) => ({
      item: m.item,
      score: Math.round(Math.max(...m.scores) * 100) / 100,
      bestScore: Math.round(Math.max(...m.scores) * 100) / 100,
      prevScore: m.scores.length > 1 ? Math.round(m.scores[m.scores.length - 2] * 100) / 100 : null,
      trend: m.scores.length > 1 ? (m.scores[m.scores.length - 1] > m.scores[m.scores.length - 2] ? "up" : m.scores[m.scores.length - 1] < m.scores[m.scores.length - 2] ? "down" : "same") : null,
      weight: m.weight,
    }));
  }, [resultHistory, latestResult]);

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
    const entries = Object.entries(allSeen).map(([id, data]) => ({
      ...data.rule,
      id,
      firstTurn: data.firstTurn,
      lastTurn: data.lastTurn,
      turnCount: data.turnCount,
      resolved: resultHistory.length > 0 && !latestIds.has(id),
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

  // Cumulative KG & HyperStudent: merge across turns so data is never lost
  const kgAnalysis = useMemo(() => {
    const pick = (r: any) => r?.kg_analysis ?? r?.agent_trace?.kg_analysis ?? null;
    const all = [...resultHistory.map(pick), pick(latestResult)].filter(Boolean);
    if (all.length === 0) return null;
    const entMap = new Map<string, any>();
    const relSet = new Set<string>();
    const rels: any[] = [];
    const gapSet = new Set<string>();
    const strengthSet = new Set<string>();
    let insight = "", scores: any = {}, completeness = 0;
    for (const kg of all) {
      for (const e of kg.entities ?? []) entMap.set(e.id, e);
      for (const r of kg.relationships ?? []) { const k = `${r.source}-${r.relation}-${r.target}`; if (!relSet.has(k)) { relSet.add(k); rels.push(r); } }
      for (const g of kg.structural_gaps ?? []) gapSet.add(g);
      for (const s of kg.content_strengths ?? []) strengthSet.add(s);
      if (kg.insight) insight = kg.insight;
      if (kg.section_scores) scores = kg.section_scores;
      if (kg.completeness_score != null) completeness = kg.completeness_score;
    }
    return { entities: Array.from(entMap.values()), relationships: rels, structural_gaps: Array.from(gapSet), content_strengths: Array.from(strengthSet), insight, section_scores: scores, completeness_score: completeness };
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
    if (rightTab !== "hyper") return;
    let cancelled = false;
    fetch(`${API_BASE}/api/hypergraph/library?limit=16&t=${Date.now()}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((data) => { if (!cancelled) setHyperLibrary(data?.data ?? null); })
      .catch(() => { if (!cancelled) setHyperLibrary(null); });
    return () => { cancelled = true; };
  }, [rightTab, resultHistory.length, latestResult]);

  useEffect(() => {
    if (rightTab !== "hyper") return;
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
  }, [rightTab, hyperInsight, hyperStudent, pressureTrace, resultHistory.length, latestResult]);

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
    const scores = resultHistory.map((r) => r?.diagnosis?.overall_score).filter((s) => s != null);
    return scores.length > 0 ? scores[scores.length - 1] : latestResult?.diagnosis?.overall_score ?? null;
  }, [resultHistory, latestResult]);
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
    }
  }, [currentUser]);

  if (!currentUser) return <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", color: "var(--text-muted)" }}>加载中...</div>;

  return (
    <div className={`chat-app ${theme}`}>
      {/* ── Top Bar ── */}
      <header className="chat-topbar">
        <div className="topbar-left">
          <button type="button" className="topbar-icon-btn sidebar-toggle" onClick={() => setConvSidebarOpen((v) => !v)} title="会话列表">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 12h18M3 6h18M3 18h18"/></svg>
          </button>
          <Link href="/" className="topbar-brand">
            <span className="brand-dot" />
            VentureCheck
          </Link>
          <span className="topbar-sep" />
          <span className="topbar-label">双创智能教练</span>
        </div>
        <div className="topbar-center">
          <div className="topbar-mode-toggle">
            <button type="button" className={`topbar-mode-opt${mode === "coursework" ? " active" : ""}`} onClick={() => setMode("coursework")}>课程辅导</button>
            <button type="button" className={`topbar-mode-opt${mode === "competition" ? " active" : ""}`} onClick={() => setMode("competition")}>竞赛冲刺</button>
            <button type="button" className={`topbar-mode-opt${mode === "learning" ? " active" : ""}`} onClick={() => setMode("learning")}>项目教练</button>
          </div>
          {mode === "competition" && (
            <div className="topbar-comp-type">
              <select
                value={competitionType}
                onChange={(e) => setCompetitionType(e.target.value as any)}
                className="comp-type-select"
              >
                <option value="">通用竞赛</option>
                <option value="internet_plus">互联网+</option>
                <option value="challenge_cup">挑战杯</option>
                <option value="dachuang">大创</option>
              </select>
            </div>
          )}
          <div className="topbar-mode-hint">{modeGuide}</div>
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
            </div>
          )}
        </div>
        <div className="topbar-right">
          <button type="button" className="topbar-icon-btn" onClick={() => { setTeamPanelOpen((v) => !v); if (!teamPanelOpen) loadMyTeams(); }} title="我的团队" style={{ position: "relative" }}>
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>
            {myTeams.length > 0 && <span style={{ position: "absolute", top: 2, right: 2, width: 8, height: 8, borderRadius: "50%", background: "var(--accent)" }} />}
          </button>
          <button type="button" className="topbar-icon-btn" onClick={() => setTheme((t) => t === "dark" ? "light" : "dark")} title={theme === "dark" ? "切换日间模式" : "切换夜间模式"}>
            {theme === "dark" ? (
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
            ) : (
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>
            )}
          </button>
          <button type="button" className="topbar-icon-btn" onClick={() => setSettingsOpen((v) => !v)} title="设置">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>
          </button>
          {mode === "competition" && !pitchTimerRunning && (
            <div className="pitch-launcher">
              <select className="pitch-dur-select" value={pitchDuration} onChange={(e) => setPitchDuration(Number(e.target.value))}>
                <option value={180}>3 min</option>
                <option value={300}>5 min</option>
                <option value={420}>7 min</option>
                <option value={600}>10 min</option>
              </select>
              <button type="button" className="pitch-start-btn" onClick={startPitchTimer}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                路演模拟
              </button>
            </div>
          )}
          {pitchTimerRunning && (
            <button type="button" className="pitch-stop-btn" onClick={stopPitchTimer}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
              结束
            </button>
          )}
          <button type="button" className="topbar-btn" onClick={() => setRightOpen((v) => !v)}>
            {rightOpen ? "收起面板" : "分析面板"}
          </button>
          <Link href="/student/profile" className="topbar-avatar" title="个人中心">
            {(currentUser.display_name ?? "S")[0].toUpperCase()}
          </Link>
          <button type="button" className="topbar-btn" onClick={logout} title="退出登录">退出</button>
        </div>
      </header>

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
      {settingsOpen && (
        <div className="settings-drawer">
          <div className="settings-grid">
            <label>当前项目
              <input value={projectId} readOnly />
            </label>
            <label>当前账号
              <input value={currentUser?.display_name || studentId} readOnly />
            </label>
            <label>团队状态
              <input value={myTeams.length > 0 ? `已加入 ${myTeams.length} 个团队` : "未加入团队"} readOnly />
            </label>
            <label>北京时间
              <input value={formatBjTime(new Date(), true)} readOnly />
            </label>
          </div>
        </div>
      )}

      <div className={`chat-body ${pdfViewerOpen ? "pdf-split-mode" : ""}`}>
        {/* ── Conversation Sidebar ── */}
        {convSidebarOpen && !pdfViewerOpen && (
          <aside className="conv-sidebar">
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
                  <span className="conv-meta">{c.message_count}条 · {formatBjTime(c.created_at, true)}</span>
                </div>
              ))}
              {filteredConvs.length === 0 && <p className="conv-empty">{searchQuery ? "未找到匹配的对话" : "暂无历史对话"}</p>}
            </div>
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
              <div key={m.id} className={`msg-row ${m.role}`} style={{ animationDelay: `${Math.min(i * 0.05, 0.3)}s` }}>
                <div className="msg-avatar">{m.role === "user" ? "你" : "AI"}</div>
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
                { id: "risk",   label: "风险" },
                { id: "score",  label: "评分" },
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
                              <MarkdownContent content={val.analysis} theme={theme} />
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
                    if (tasks.length > 0) {
                      return (
                        <div className="task-rich">
                          {milestone && <div className="task-milestone">{milestone}</div>}
                          {tasks.map((t: any, ti: number) => {
                            const pri = s(t.priority);
                            return (
                              <details key={ti} className="task-card-v2" open={ti === 0}>
                                <summary className="task-card-head">
                                  <span className="task-num">{ti + 1}</span>
                                  {pri && priLabel[pri] && <span className={`task-pri-tag ${priClass[pri] || ""}`}>{priLabel[pri]}</span>}
                                  <span className="task-title-v2">{s(t.task)}</span>
                                </summary>
                                <div className="task-card-body">
                                  {s(t.why) && <p className="task-why">{s(t.why)}</p>}
                                  {s(t.how) && <div className="task-how"><MarkdownContent content={s(t.how)} theme={theme} /></div>}
                                  {s(t.acceptance) && <div className="task-accept"><span className="task-accept-label">验收标准</span> {s(t.acceptance)}</div>}
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
                      const tg = nextTask.template_guideline || [];
                      const ac = nextTask.acceptance_criteria || [];
                      return (
                        <div className="task-rich">
                          <details className="task-card-v2" open>
                            <summary className="task-card-head">
                              <span className="task-num">1</span>
                              <span className="task-title-v2">{s(nextTask.title)}</span>
                            </summary>
                            <div className="task-card-body">
                              <p className="task-why">{s(nextTask.description)}</p>
                              {tg.length > 0 && (
                                <div className="task-how">
                                  <MarkdownContent content={tg.map((step: string, i: number) => `${i + 1}. ${step}`).join("\n")} theme={theme} />
                                </div>
                              )}
                              {ac.length > 0 && (
                                <div className="task-accept">
                                  <span className="task-accept-label">验收标准</span> {ac.join("；")}
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
                        const healthScore = total === 0 ? 100 : Math.max(0, Math.round(100 - high * 20 - med * 8 - low * 3));
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
                            </div>
                          </details>
                        );
                      })}
                    </div>
                  ) : <p className="right-hint">暂无风险命中——描述越详细，风险检测越准确</p>}
                </>
              )}

              {rightTab === "score" && (
                <>
                  <div className="panel-desc">9维度量化评分，对标创业竞赛评审标准。评分取历史最高值，箭头显示本轮变化趋势。</div>
                  {rubric.length > 0 ? (
                    <div className="right-section">
                      {(scoreBand || projectStageLabel || gradingPrinciples.length > 0) && (
                        <div className="score-meta-card" style={{ marginBottom: 14, padding: 12, borderRadius: 12, border: "1px solid var(--border)", background: "var(--bg-secondary)" }}>
                          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: gradingPrinciples.length > 0 ? 10 : 0 }}>
                            {projectStageLabel && <span className="mini-chip">阶段：{projectStageLabel}</span>}
                            {scoreBand && <span className="mini-chip">分档：{scoreBand}</span>}
                          </div>
                          {gradingPrinciples.length > 0 && (
                            <div style={{ display: "grid", gap: 6 }}>
                              {gradingPrinciples.map((item: string, idx: number) => (
                                <div key={idx} className="panel-desc" style={{ margin: 0 }}>- {item}</div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                      {/* ── Radar Chart ── */}
                      {(() => {
                        const cx = 130, cy = 130, R = 100;
                        const n = rubric.length;
                        const angleStep = (2 * Math.PI) / n;
                        const tiers = [0.25, 0.5, 0.75, 1.0];
                        const pt = (i: number, r: number) => {
                          const a = -Math.PI / 2 + i * angleStep;
                          return [cx + R * r * Math.cos(a), cy + R * r * Math.sin(a)];
                        };
                        const dataPoints = rubric.map((r: any, i: number) => pt(i, Math.min(1, r.score / 10)));
                        const polygon = dataPoints.map(([x, y]: number[]) => `${x},${y}`).join(" ");
                        return (
                          <svg className="radar-svg" viewBox="0 0 260 260">
                            {tiers.map((t) => (
                              <polygon key={t} points={Array.from({ length: n }, (_, i) => pt(i, t)).map(([x, y]: number[]) => `${x},${y}`).join(" ")} className="radar-grid" />
                            ))}
                            {rubric.map((_: any, i: number) => {
                              const [ex, ey] = pt(i, 1);
                              return <line key={i} x1={cx} y1={cy} x2={ex} y2={ey} className="radar-axis" />;
                            })}
                            <polygon points={polygon} className="radar-area" />
                            {dataPoints.map(([x, y]: number[], i: number) => (
                              <circle key={i} cx={x} cy={y} r="3.5" className="radar-dot" />
                            ))}
                            {rubric.map((r: any, i: number) => {
                              const [lx, ly] = pt(i, 1.22);
                              return <text key={i} x={lx} y={ly} className="radar-label" textAnchor="middle" dominantBaseline="central">{r.item.length > 4 ? r.item.slice(0, 4) : r.item}</text>;
                            })}
                          </svg>
                        );
                      })()}
                      {overallScore !== null && <div className="score-total-ring">
                        <svg viewBox="0 0 80 80" className="ring-svg">
                          <circle cx="40" cy="40" r="32" className="ring-bg" />
                          <circle cx="40" cy="40" r="32" className="ring-fg" strokeDasharray={`${(overallScore / 10) * 201} 201`} />
                        </svg>
                        <div className="ring-text"><span className="ring-num">{overallScore}</span><span className="ring-max">/10</span></div>
                      </div>}
                      {/* ── Bar rows with trend ── */}
                      {rubric.map((r: any) => {
                        const pct = Math.min(100, (r.score / 10) * 100);
                        const color = pct >= 70 ? "var(--accent-green)" : pct >= 40 ? "var(--accent-yellow)" : "var(--accent-red)";
                        return (
                          <details key={r.item} className="score-row-details">
                            <summary className="score-row">
                            <span className="score-label">{r.item}</span>
                            <div className="score-bar-track"><div className="score-bar-fill" style={{ width: `${pct}%`, background: color }} /></div>
                            <span className="score-value">{r.score}</span>
                            {r.trend && <span className={`score-trend ${r.trend}`}>{r.trend === "up" ? "↑" : r.trend === "down" ? "↓" : "="}</span>}
                            </summary>
                            {r.reason && <p className="score-reason">{r.reason}</p>}
                          </details>
                        );
                      })}
                    </div>
                  ) : <p className="right-hint">提交项目描述后显示评分，描述越完整评分越有参考价值</p>}
                </>
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

                        {/* KB Utilization Dashboard (Module 3c) */}
                        {(() => {
                          const kbU = latestResult?.agent_trace?.kb_utilization ?? latestResult?.kb_utilization ?? {};
                          const totalKb = kbU.total_kb_cases ?? 0;
                          const ragHits = kbU.hits_count ?? 0;
                          const neoOk = kbU.neo4j_enriched ?? false;
                          const neoCount = kbU.neo4j_enriched_count ?? 0;
                          const excluded = kbU.excluded_history_count ?? 0;
                          const rMode = kbU.retrieval_mode ?? "";
                          const catF = kbU.category_filter ?? "";
                          if (!totalKb && !ragHits) return null;
                          const modeName: Record<string, string> = { vector: "向量", keyword: "关键词", hybrid: "混合", auto: "自动(MMR)" };

                          const allTypes = new Set(["stakeholder","pain_point","solution","technology","market","competitor","resource","business_model","evidence","team"]);
                          const foundTypes = new Set(entities.map((e: any) => e.type));
                          const missingTypes = [...allTypes].filter(t => !foundTypes.has(t));
                          const missingNames: Record<string, string> = { stakeholder: "用户/利益相关者", pain_point: "痛点", solution: "解决方案", technology: "技术", market: "市场", competitor: "竞品", resource: "资源", business_model: "商业模式", evidence: "证据", team: "团队" };

                          const hyperDriven = kbU.hyper_driven_search ?? false;
                          const hyperDims = kbU.hyper_driven_dims ?? [];
                          const compCount = kbU.complementary_count ?? 0;
                          const topK = kbU.top_k_requested ?? 4;
                          return (
                            <div className="kb-overview-module">
                              <h5>知识库总体状况与调用链路</h5>
                              <div className="kb-util-grid">
                                <div className="kb-util-cell"><div className="kb-util-num">{totalKb}</div><div className="kb-util-label">标准案例</div></div>
                                <div className="kb-util-cell"><div className="kb-util-num">{ragHits}</div><div className="kb-util-label">RAG命中</div></div>
                                <div className="kb-util-cell"><div className="kb-util-num">{neoCount}</div><div className="kb-util-label">Neo4j增强</div></div>
                                <div className="kb-util-cell"><div className="kb-util-num">{excluded}</div><div className="kb-util-label">去重过滤</div></div>
                              </div>
                              {/* RAG Pipeline Visualization */}
                              <div className="kb-pipeline">
                                <div className="kb-pipe-step active"><span>学生输入</span></div>
                                <div className="kb-pipe-arrow">→</div>
                                <div className={`kb-pipe-step ${ragHits > 0 ? "active" : ""}`}><span>RAG检索</span><small>{modeName[rMode] ?? rMode} · top{topK}</small></div>
                                <div className="kb-pipe-arrow">→</div>
                                <div className={`kb-pipe-step ${neoOk ? "active" : "inactive"}`}><span>Neo4j增强</span><small>{neoOk ? `${neoCount}案例` : "未启用"}</small></div>
                                <div className="kb-pipe-arrow">→</div>
                                <div className={`kb-pipe-step ${compCount > 0 ? "active" : ""}`}><span>互补搜索</span><small>{compCount > 0 ? `+${compCount}互补` : "无"}</small></div>
                                {hyperDriven && <>
                                  <div className="kb-pipe-arrow">→</div>
                                  <div className="kb-pipe-step active hyper-driven"><span>超图驱动</span><small>补{hyperDims.join(",")}</small></div>
                                </>}
                              </div>
                              <div className="kb-meta-row">
                                {catF && <span className="kb-meta-chip">类目: {catF}</span>}
                                <span className="kb-meta-chip" style={{ borderColor: neoOk ? "#10b981" : "#ef4444" }}>Neo4j: {neoOk ? "已连接" : "离线"}</span>
                                {hyperDriven && <span className="kb-meta-chip" style={{ borderColor: "var(--accent)" }}>超图驱动补充检索</span>}
                              </div>
                              {missingTypes.length > 0 && (
                                <div className="kb-util-missing">
                                  <span className="kb-util-missing-label">尚未覆盖:</span>
                                  {missingTypes.map(t => <span key={t} className="kb-util-missing-chip">{missingNames[t] ?? t}</span>)}
                                </div>
                              )}
                              {/* Structured RAG Search Trace */}
                              {(kbU.search_trace ?? []).length > 0 && (
                                <details className="kb-search-trace" open>
                                  <summary>检索过程详情 ({(kbU.search_trace as any[]).length} 条结果)</summary>
                                  {kbU.query_preview && <div className="kb-st-query"><strong>检索query:</strong> {kbU.query_preview as string}</div>}
                                  <div className="kb-st-list">
                                    {(kbU.search_trace as any[]).map((st: any, si: number) => (
                                      <div key={si} className={`kb-st-row ${st.neo4j_enriched ? "enriched" : ""} ${st.complementary ? "comp" : ""} ${st.hyper_driven ? "hyper" : ""}`}>
                                        <span className="kb-st-rank">#{si + 1}</span>
                                        <span className="kb-st-id">{st.case_id}</span>
                                        <span className="kb-st-score">相似度 {st.score}</span>
                                        <div className="kb-st-badges">
                                          {st.neo4j_enriched && <span className="kb-st-badge neo4j">Neo4j增强</span>}
                                          {st.complementary && <span className="kb-st-badge comp">互补检索</span>}
                                          {st.hyper_driven && <span className="kb-st-badge hyper">超图驱动</span>}
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                  {(kbU.weak_dims_for_complementary ?? []).length > 0 && (
                                    <div className="kb-st-weak">触发互补搜索的弱势维度: {(kbU.weak_dims_for_complementary as string[]).join(", ")}</div>
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
                    const hyper = n.hypergraph ?? {};
                    const ragC = kbStats.rag?.corpus_count ?? 0;
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
                    return (
                      <div className="kb-global-stats">
                        <h5>知识库全局概览</h5>
                        <div className="kb-gs-summary">
                          <div className="kb-gs-card"><div className="kb-gs-num">{n.total_projects}</div><div className="kb-gs-label">标准案例</div></div>
                          <div className="kb-gs-card"><div className="kb-gs-num">{n.total_nodes}</div><div className="kb-gs-label">图谱节点</div></div>
                          <div className="kb-gs-card"><div className="kb-gs-num">{n.total_relationships}</div><div className="kb-gs-label">关系总数</div></div>
                          <div className="kb-gs-card"><div className="kb-gs-num">{cats.length}</div><div className="kb-gs-label">项目类别</div></div>
                          <div className="kb-gs-card"><div className="kb-gs-num">{ragC}</div><div className="kb-gs-label">RAG语料</div></div>
                          <div className="kb-gs-card"><div className="kb-gs-num">{hyper.edges ?? 0}</div><div className="kb-gs-label">超边数</div></div>
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
                              <span className="kb-gs-arch-dot" style={{background: n.total_nodes > 0 ? "#10b981" : "#ef4444"}} />
                              <span>Neo4j 图检索: {n.total_nodes > 0 ? "已连接" : "离线"}</span>
                            </div>
                            <div className="kb-gs-arch-row">
                              <span className="kb-gs-arch-dot" style={{background: "#10b981"}} />
                              <span>TF-IDF 关键词检索: 就绪</span>
                            </div>
                            <div className="kb-gs-arch-row">
                              <span className="kb-gs-arch-dot" style={{background: (hyper.nodes ?? 0) > 0 ? "#10b981" : "#ef4444"}} />
                              <span>超图分析: {hyper.nodes ?? 0} 节点 / {hyper.edges ?? 0} 超边</span>
                            </div>
                            <div className="kb-gs-arch-row">
                              <span className="kb-gs-arch-dot" style={{background: "#10b981"}} />
                              <span>本体节点: {n.ontology_nodes ?? 0} · 风险规则: {n.risk_rules ?? 0} · 评分标准: {n.rubric_items ?? 0}</span>
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

                      {/* ── 2. Dimension Coverage Matrix ── */}
                      <div className="ht-section">
                        <h5 className="ht-title">维度覆盖矩阵</h5>
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

                      {/* ── 4. Agent Hypergraph Signal Dashboard ── */}
                      {activeAgents.length > 0 && (
                        <div className="ht-section">
                          <h5 className="ht-title">各Agent接收的超图启发</h5>
                          <div className="ht-agent-bar-chart">
                            {activeAgents.map(a => {
                              const ad = roleAgents[a] ?? {};
                              const ctx = String(ad.hyper_context_sent ?? "");
                              const lines = ctx ? ctx.split("\n").filter((l: string) => l.trim()) : [];
                              const maxBar = Math.max(...activeAgents.map(ag => {
                                const c = String((roleAgents[ag] ?? {}).hyper_context_sent ?? "");
                                return c ? c.split("\n").filter((l: string) => l.trim()).length : 0;
                              }), 1);
                              return (
                                <div key={a} className="ht-agent-bar-row">
                                  <span className="ht-agent-label">{agentNames[a] ?? a}</span>
                                  <div className="ht-agent-bar-track">
                                    <div className="ht-agent-bar-fill" style={{ width: `${Math.round((lines.length / maxBar) * 100)}%` }} />
                                  </div>
                                  <span className="ht-agent-bar-num">{lines.length}</span>
                                </div>
                              );
                            })}
                          </div>
                          {activeAgents.map(a => {
                            const ad = roleAgents[a] ?? {};
                            const ctx = String(ad.hyper_context_sent ?? "");
                            const lines = ctx ? ctx.split("\n").filter((l: string) => l.trim()) : [];
                            if (lines.length === 0) return null;
                            const catPatterns: [string, RegExp][] = [
                              ["覆盖度", /覆盖|累积|实体/],
                              ["风险", /风险|一致性|断裂|缺失|问题/],
                              ["闭环", /闭环|链路|未闭合|价值链/],
                              ["洞察", /洞察|拓扑|摘要|教学超边/],
                              ["行动", /追问|行动线索|可推进|待补/],
                            ];
                            return (
                              <details key={a} className="ht-agent-detail">
                                <summary className="ht-agent-detail-head">
                                  <span className="ht-agent-detail-name">{agentNames[a] ?? a}</span>
                                  <span className="ht-agent-detail-count">{lines.length} 条信号</span>
                                </summary>
                                <div className="ht-agent-detail-body">
                                  {lines.map((line: string, li: number) => {
                                    const cat = catPatterns.find(([, p]) => p.test(line));
                                    return (
                                      <div key={li} className="ht-signal-row">
                                        <span className={`ht-signal-tag ${(cat?.[0] ?? "其它").replace("/", "")}`}>{cat?.[0] ?? "信号"}</span>
                                        <span className="ht-signal-text">{line.replace(/^[^:：]+[:：]\s*/, "").trim() || line}</span>
                                      </div>
                                    );
                                  })}
                                </div>
                              </details>
                            );
                          })}
                        </div>
                      )}

                      {/* ── 5. Consistency Issues ── */}
                      {hyperConsistencyIssues.length > 0 && (
                        <div className="ht-section">
                          <h5 className="ht-title">逻辑一致性检测 <span className="ht-badge-count">{hyperConsistencyIssues.length}</span></h5>
                          {hyperConsistencyIssues.slice(0, 8).map((ci: any, idx: number) => (
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
                            {hyperStudent.missing_dimensions.slice(0, 4).map((m: any, mi: number) => (
                              <div key={mi} className="ht-insight-item">
                                <span className={`ht-imp-badge ${m.importance}`}>{m.importance}</span>
                                <span className="ht-insight-dim">{m.dimension}</span>
                                <p className="ht-insight-desc">{m.recommendation}</p>
                              </div>
                            ))}
                          </div>
                        )}
                        {(hyperStudent.pattern_warnings ?? []).length > 0 && (
                          <div className="ht-insight-card ht-card-warn">
                            <h5>风险模式</h5>
                            {(hyperStudent.pattern_warnings ?? []).slice(0, 4).map((w: any, wi: number) => (
                              <div key={wi} className="ht-insight-item"><p className="ht-insight-desc">{w.warning}</p></div>
                            ))}
                          </div>
                        )}
                        {(hyperStudent.pattern_strengths ?? []).length > 0 && (
                          <div className="ht-insight-card ht-card-good">
                            <h5>优势结构</h5>
                            {(hyperStudent.pattern_strengths ?? []).slice(0, 4).map((s: any, si: number) => (
                              <div key={si} className="ht-insight-item">
                                <p className="ht-insight-desc">{s.note}</p>
                                {s.edge_type && <span className="ht-edge-tag">{s.edge_type}</span>}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>

                      {/* ── 7. Useful Cards (from project-view) ── */}
                      {hyperProjectView && (hyperProjectView?.useful_cards ?? []).length > 0 && (
                        <div className="ht-section">
                          <h5 className="ht-title">超图核心结论</h5>
                          <div className="ht-useful-grid">
                            {(hyperProjectView.useful_cards ?? []).map((card: any, idx: number) => (
                              <div key={idx} className={`ht-useful-card ${card.tone || ""}`}>
                                <strong>{card.title}</strong>
                                <p>{card.summary}</p>
                                {card.project_hint && <span className="ht-useful-hint">{card.project_hint}</span>}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

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
                        {hyperEdges.length > 0 && (
                          <div className="ht-edge-section">
                            <h6>命中教学超边</h6>
                            {hyperEdges.slice(0, 5).map((e: any) => (
                              <div key={e.hyperedge_id} className="ht-edge-row">
                                <span className="ht-edge-family">{e.family_label || e.type}</span>
                                <span className="ht-edge-note">{e.teaching_note}</span>
                                <div className="ht-edge-meta">
                                  <span>支持度 {e.support ?? 0}</span>
                                  {e.severity && <span className="ht-edge-sev">{e.severity}</span>}
                                  {(e.rules ?? []).map((r: string, ri: number) => <span key={ri} className="ht-edge-rule">{r}</span>)}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                        {hyperLibrary?.overview && (
                          <div className="ht-library-stats">
                            <h6>超图库全局</h6>
                            <div className="ht-lib-row"><span>超边总数</span><strong>{hyperLibrary.overview.edge_count ?? 0}</strong></div>
                            <div className="ht-lib-row"><span>节点总数</span><strong>{hyperLibrary.overview.node_count ?? 0}</strong></div>
                            <div className="ht-lib-row"><span>本轮命中</span><strong>{hyperProjectView?.matched_edges?.length ?? 0}</strong></div>
                            {(hyperLibrary?.families ?? []).slice(0, 5).map((f: any, fi: number) => (
                              <div key={fi} className="ht-lib-row"><span>{f.label ?? f.family}</span><strong>{f.count}</strong></div>
                            ))}
                          </div>
                        )}
                      </details>
                    </>);
                  })() : (
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
                  <p className="cs-desc">从 <strong>{kbUtil.total_kb_cases ?? 96}</strong> 个标准案例库中检索到 <strong>{hitCount}</strong> 个参考{enriched ? `，其中 ${enrichedCount} 个经图谱深度增强` : ""}</p>

                  {/* ── 1. Graph-Based Cross-Project Insights (TOP PRIORITY) ── */}
                  {gHits.length > 0 && (
                    <div className="cs-graph-section">
                      <h5 className="cs-sec-title">跨项目图谱启发 ({gCount})</h5>
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
                    </div>
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
                  <div className="debug-row"><span>教学超边</span><span>{hyperEdges.length > 0 ? `${hyperEdges.length}条` : "无"}</span></div>
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
