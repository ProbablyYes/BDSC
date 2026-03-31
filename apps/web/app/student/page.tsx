"use client";

import { Children, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
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

function sanitizeMermaid(raw: string): string {
  let s = raw.trim();
  s = s.replace(/\u201c/g, "'").replace(/\u201d/g, "'");
  s = s.replace(/\u2018/g, "'").replace(/\u2019/g, "'");
  s = s.replace(/\uff1f/g, "?").replace(/\uff01/g, "!").replace(/\uff1b/g, ";");
  s = s.replace(/\uff08/g, "(").replace(/\uff09/g, ")");
  s = s.replace(/[\u200b\u200c\u200d\ufeff]/g, "");
  s = s.replace(/(-->|-->) *\n/g, "$1 ");
  return s;
}

function MermaidBlock({ chart, theme }: { chart: string; theme: "dark" | "light" }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");
  const renderKey = useMemo(() => `mermaid-${Math.random().toString(36).slice(2)}`, []);
  const cleanChart = useMemo(() => sanitizeMermaid(chart), [chart]);

  useEffect(() => {
    let cancelled = false;

    async function renderChart() {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "loose",
          theme: theme === "dark" ? "dark" : "default",
          fontFamily: "Inter, Segoe UI, sans-serif",
          fontSize: 12,
          flowchart: { nodeSpacing: 16, rankSpacing: 28, curve: "basis", htmlLabels: true },
        } as any);
        const { svg, bindFunctions } = await mermaid.render(`${renderKey}-${Date.now()}`, cleanChart);
        if (cancelled || !hostRef.current) return;
        hostRef.current.innerHTML = svg;
        bindFunctions?.(hostRef.current);
        setError("");
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "图表渲染失败");
      }
    }

    renderChart();
    return () => {
      cancelled = true;
    };
  }, [cleanChart, renderKey, theme]);

  return (
    <div className="mermaid-card">
      <div className="mermaid-head">
        <span>流程图</span>
        <span>Mermaid</span>
      </div>
      {error ? (
        <div className="mermaid-error">
          <div>图表渲染失败，先显示原始代码：</div>
          <pre className="mermaid-fallback"><code>{chart}</code></pre>
        </div>
      ) : (
        <div ref={hostRef} className="mermaid-stage" />
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
  const modeWelcome = MODE_WELCOME[mode] ?? MODE_WELCOME.coursework;

  const fileInputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const dragRef = useRef<{ active: boolean; startX: number; startW: number }>({ active: false, startX: 0, startW: 360 });
  const abortRef = useRef<AbortController | null>(null);
  const kgPanRef = useRef<{ active: boolean; startX: number; startY: number; x: number; y: number }>({ active: false, startX: 0, startY: 0, x: 0, y: 0 });
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
    const all: Record<string, any> = {};
    for (const r of resultHistory) {
      for (const rule of r?.diagnosis?.triggered_rules ?? []) {
        all[rule.id] = { ...rule, turnCount: (all[rule.id]?.turnCount ?? 0) + 1 };
      }
    }
    if (Object.keys(all).length === 0) return latestResult?.diagnosis?.triggered_rules ?? [];
    return Object.values(all).sort((a: any, b: any) => {
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
    let gaps: string[] = [], strengths: string[] = [], insight = "", scores: any = {}, completeness = 0;
    for (const kg of all) {
      for (const e of kg.entities ?? []) entMap.set(e.id, e);
      for (const r of kg.relationships ?? []) { const k = `${r.source}-${r.relation}-${r.target}`; if (!relSet.has(k)) { relSet.add(k); rels.push(r); } }
      if (kg.structural_gaps?.length) gaps = kg.structural_gaps;
      if (kg.content_strengths?.length) strengths = kg.content_strengths;
      if (kg.insight) insight = kg.insight;
      if (kg.section_scores) scores = kg.section_scores;
      if (kg.completeness_score) completeness = kg.completeness_score;
    }
    return { entities: Array.from(entMap.values()), relationships: rels, structural_gaps: gaps, content_strengths: strengths, insight, section_scores: scores, completeness_score: completeness };
  }, [resultHistory, latestResult]);

  const hyperStudent = useMemo(() => {
    const pick = (r: any) => r?.hypergraph_student ?? r?.agent_trace?.hypergraph_student ?? null;
    const all = [...resultHistory.map(pick), pick(latestResult)].filter((h) => h?.ok);
    return all.length > 0 ? all[all.length - 1] : null;
  }, [resultHistory, latestResult]);

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
                    const tasks = cumulativePlannerTasks;
                    const milestone = s(cumulativeMilestone);
                    if (tasks.length > 0) {
                      return (
                        <div className="task-rich">
                          {milestone && <div className="task-milestone">{milestone}</div>}
                          {tasks.map((t: any, ti: number) => (
                            <details key={ti} className="task-card-v2" open={ti === 0}>
                              <summary className="task-card-head">
                                <span className="task-num">{ti + 1}</span>
                                <span className="task-title-v2">{s(t.task)}</span>
                              </summary>
                              <div className="task-card-body">
                                {s(t.why) && <p className="task-why">{s(t.why)}</p>}
                                {s(t.how) && <div className="task-how"><MarkdownContent content={s(t.how)} theme={theme} /></div>}
                                {s(t.acceptance) && <div className="task-accept">{s(t.acceptance)}</div>}
                              </div>
                            </details>
                          ))}
                        </div>
                      );
                    }
                    if (nextTask && nextTask.title && s(nextTask.title) !== "描述你的项目") {
                      return (
                        <div className="task-rich">
                          <details className="task-card-v2" open>
                            <summary className="task-card-head">
                              <span className="task-num">1</span>
                              <span className="task-title-v2">{s(nextTask.title)}</span>
                            </summary>
                            <div className="task-card-body">
                              <p className="task-why">{s(nextTask.description)}</p>
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
                  <div className="panel-desc">基于15条创业风险规则库，检测你描述中的隐患并给出修复建议。风险跨轮次累积。</div>
                  {triggeredRules.length > 0 ? (
                    <div className="right-section">
                      {(() => {
                        const high = triggeredRules.filter((r: any) => r.severity === "high").length;
                        const med = triggeredRules.filter((r: any) => r.severity === "medium").length;
                        const low = triggeredRules.filter((r: any) => r.severity === "low").length;
                        const total = triggeredRules.length;
                        return (
                          <div className="risk-summary-bar">
                            <div className="risk-summary-stats">
                              <span className="risk-stat high">{high} 高危</span>
                              <span className="risk-stat medium">{med} 中等</span>
                              <span className="risk-stat low">{low} 轻微</span>
                            </div>
                            <div className="risk-dist-track">
                              {high > 0 && <div className="risk-dist-seg high" style={{ width: `${(high / total) * 100}%` }} />}
                              {med > 0 && <div className="risk-dist-seg medium" style={{ width: `${(med / total) * 100}%` }} />}
                              {low > 0 && <div className="risk-dist-seg low" style={{ width: `${(low / total) * 100}%` }} />}
                            </div>
                          </div>
                        );
                      })()}
                      {triggeredRules.map((r: any) => (
                        <details key={r.id} className={`risk-detail-card ${r.severity}`}>
                          <summary className="risk-detail-header">
                            <span className="risk-id">{r.id}</span>
                            <span className="risk-name">{r.name}</span>
                            <span className={`risk-badge ${r.severity}`}>{{ high: "高危", medium: "中等", low: "轻微" }[r.severity as string] ?? r.severity}</span>
                            {r.turnCount > 1 && <span className="risk-repeat-badge">连续{r.turnCount}轮</span>}
                          </summary>
                          <div className="risk-detail-body">
                            {r.explanation && <p className="risk-explanation">{r.explanation}</p>}
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
                          </div>
                        </details>
                      ))}
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
                    const cx = 160, cy = 160, R = 120;
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
                          <span className="kg-toolbar-hint">滚轮缩放，拖拽平移</span>
                          <div style={{ display: "flex", gap: 6 }}>
                            <button className="kg-tool-btn" onClick={() => setKgViewport((v) => ({ ...v, scale: Math.max(0.7, Number((v.scale - 0.12).toFixed(2))) }))}>-</button>
                            <button className="kg-tool-btn" onClick={() => setKgViewport({ scale: 1, x: 0, y: 0 })}>重置</button>
                            <button className="kg-tool-btn" onClick={() => setKgViewport((v) => ({ ...v, scale: Math.min(2.4, Number((v.scale + 0.12).toFixed(2))) }))}>+</button>
                          </div>
                        </div>
                        <div className="kg-zoom-shell" onWheel={handleKgWheel} onMouseDown={handleKgMouseDown} onMouseMove={handleKgMouseMove} onMouseUp={handleKgMouseUp} onMouseLeave={handleKgMouseUp}>
                          <svg viewBox="0 0 320 320" className="kg-svg-graph">
                            <g transform={`translate(${kgViewport.x} ${kgViewport.y}) scale(${kgViewport.scale})`}>
                              <circle cx={cx} cy={cy} r={R + 20} fill="none" stroke="var(--border)" strokeWidth="0.5" strokeDasharray="4 4" opacity="0.4" />
                              {rels.map((r: any, ri: number) => {
                                const si = entities.findIndex((e: any) => e.id === r.source);
                                const ti = entities.findIndex((e: any) => e.id === r.target);
                                if (si < 0 || ti < 0) return null;
                                const a1 = (2 * Math.PI * si) / entities.length - Math.PI / 2;
                                const a2 = (2 * Math.PI * ti) / entities.length - Math.PI / 2;
                                return <line key={ri} x1={cx + R * Math.cos(a1)} y1={cy + R * Math.sin(a1)} x2={cx + R * Math.cos(a2)} y2={cy + R * Math.sin(a2)} stroke="var(--text-secondary)" strokeWidth="0.6" opacity="0.25" />;
                              })}
                              <circle cx={cx} cy={cy} r="20" fill="var(--accent)" opacity="0.15" />
                              <text x={cx} y={cy - 4} textAnchor="middle" fontSize="8" fill="var(--accent)" fontWeight="700">{kgAnalysis.completeness_score ?? "?"}/10</text>
                              <text x={cx} y={cy + 7} textAnchor="middle" fontSize="6" fill="var(--text-secondary)">完整度</text>
                              {entities.map((e: any, i: number) => {
                                const angle = (2 * Math.PI * i) / entities.length - Math.PI / 2;
                                const nx = cx + R * Math.cos(angle), ny = cy + R * Math.sin(angle);
                                const color = typeColors[e.type] ?? "#6ba3d6";
                                return (
                                  <g key={e.id} className="kg-node-g">
                                    <line x1={cx} y1={cy} x2={nx} y2={ny} stroke={color} strokeWidth="0.5" opacity="0.2" />
                                    <circle cx={nx} cy={ny} r="14" fill={color + "20"} stroke={color} strokeWidth="1.2" />
                                    <text x={nx} y={ny - 2} textAnchor="middle" fontSize="6.5" fill="var(--text-primary)" fontWeight="600">{e.label.length > 5 ? e.label.slice(0, 4) + ".." : e.label}</text>
                                    <text x={nx} y={ny + 6} textAnchor="middle" fontSize="5" fill={color}>{typeNames[e.type] ?? e.type}</text>
                                  </g>
                                );
                              })}
                            </g>
                          </svg>
                        </div>

                        {/* Dimension scores */}
                        {Object.keys(secScores).length > 0 && (
                          <div className="kg-dim-scores">
                            <h5>维度完成度</h5>
                            {Object.entries(secScores).map(([k, v]: [string, any]) => {
                              const score = Number(v);
                              const pct = Math.min(100, (score / 10) * 100);
                              const color = pct >= 70 ? "#5cbd8a" : pct >= 40 ? "#e0a84c" : "#e07070";
                              const names: Record<string, string> = { problem_definition: "问题定义", user_evidence: "用户证据", solution_feasibility: "方案可行性", business_model: "商业模式", competitive_advantage: "竞争优势" };
                              return (
                                <div key={k} className="kg-score-row">
                                  <span className="kg-score-name">{names[k] ?? k}</span>
                                  <div className="kg-score-bar"><div className="kg-score-fill" style={{ width: `${pct}%`, background: color }} /></div>
                                  <span className="kg-score-val">{score}</span>
                                </div>
                              );
                            })}
                          </div>
                        )}

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
                      </div>
                    );
                  })() : (
                    <div className="proj-empty-guide">
                      <p>发送项目描述或上传计划书，AI 会自动提取关键信息生成项目梳理。数据跨轮次累积，不会因追问而丢失。</p>
                    </div>
                  )}
                </div>
              )}

              {rightTab === "hyper" && (
                <div className="right-section">
                  <h4>项目全景诊断</h4>
                  <div className="panel-desc">这里不是再给你看一堆图谱术语，而是直接告诉你：你的项目目前结构上哪里强、哪里缺、评委最可能追问什么，以及这些判断背后的超图证据。</div>
                  {hyperStudent?.ok ? (
                    <>
                      <div className="hyper-impact-hero">
                        <div className="hyper-impact-main">
                          <div className="hyper-impact-title">你这个项目当前命中了多少关键维度</div>
                          <div className="hyper-impact-sub">
                            {hyperStudent.covered_count ?? 0} / {hyperStudent.total_dimensions ?? 10} 个维度已明确，覆盖度 {hyperStudent.coverage_score ?? 0}/10
                            {" · "}
                            本轮命中 {hyperProjectView?.matched_edges?.length ?? 0} 条模式，总库 {hyperLibrary?.overview?.edge_count ?? 0} 条超边
                          </div>
                        </div>
                        <div
                          className="hyper-impact-ring"
                          style={{
                            background: `conic-gradient(var(--accent) 0 ${(Number(hyperStudent.coverage_score ?? 0) / 10) * 360}deg, rgba(255,255,255,0.08) ${(Number(hyperStudent.coverage_score ?? 0) / 10) * 360}deg 360deg)`,
                          }}
                        >
                          <div className="hyper-impact-ring-inner">
                            <div className="hyper-impact-score">{hyperStudent.coverage_score ?? 0}<span>/10</span></div>
                          </div>
                        </div>
                      </div>

                      <div className="hyper-dim-matrix">
                        {Object.entries(hyperStudent.dimensions ?? {}).map(([k, v]: [string, any]) => (
                          <div key={k} className={`hyper-dim-square ${v.covered ? "covered" : "missing"}`}>
                            <div className="hyper-dim-square-name">{v.name}</div>
                            <div className="hyper-dim-square-meta">{v.covered ? `${v.count} 个信号` : "待补充"}</div>
                          </div>
                        ))}
                      </div>

                      {hyperProjectView && (
                        <div className="hyper-guided-board">
                          <div className="hyper-guided-card">
                            <h5>超图对你项目最有用的结论</h5>
                            <div className="panel-desc">先看这 3 条。它们是超图综合你本轮材料之后，最值得你立刻关注的地方。</div>
                            {(hyperProjectView?.useful_cards ?? []).length > 0 ? (
                              <div className="hyper-useful-grid">
                                {(hyperProjectView.useful_cards ?? []).map((card: any, idx: number) => (
                                  <div key={idx} className={`hyper-useful-card ${card.tone || ""}`}>
                                    <div className="hyper-useful-head">
                                      <strong>{card.title}</strong>
                                      {card.importance ? <span>{card.importance}</span> : null}
                                    </div>
                                    <div className="hyper-useful-summary">{card.summary}</div>
                                    {card.project_hint ? <div className="hyper-useful-hint">这对你意味着：{card.project_hint}</div> : null}
                                    <p>{card.reason}</p>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <div className="panel-desc">当前还没有足够稳定的超图结论，先继续补充项目描述。</div>
                            )}
                          </div>
                        </div>
                      )}

                      {(hyperInsight?.summary || (hyperInsight?.top_signals ?? []).length > 0) && (
                        <div className="hyper-teaching-summary compact">
                          {hyperInsight?.summary && <div className="hyper-insight-text">{hyperInsight.summary}</div>}
                          {(hyperInsight?.top_signals ?? []).length > 0 && (
                            <div className="hyper-signal-list">
                              {(hyperInsight.top_signals ?? []).map((signal: string, idx: number) => (
                                <div key={idx} className="hyper-signal-chip">{signal}</div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      <div className="hyper-result-board">
                        {(hyperStudent.missing_dimensions ?? []).length > 0 && (
                          <div className="hyper-result-card">
                            <h5>你最该先补的结构</h5>
                            {hyperStudent.missing_dimensions.slice(0, 3).map((m: any, mi: number) => (
                              <div key={mi} className={`hyper-missing-item importance-${m.importance}`}>
                                <span className="hyper-missing-dim">{m.dimension}</span>
                                <span className={`hyper-importance-badge ${m.importance}`}>{m.importance}</span>
                                <p className="hyper-missing-reason">{m.recommendation}</p>
                              </div>
                            ))}
                          </div>
                        )}
                        {(hyperStudent.pattern_warnings ?? []).length > 0 && (
                          <div className="hyper-result-card">
                            <h5>历史模式里的风险提醒</h5>
                            {(hyperStudent.pattern_warnings ?? []).slice(0, 3).map((w: any, wi: number) => (
                              <div key={wi} className="hyper-warning-item">{w.warning}</div>
                            ))}
                          </div>
                        )}
                        {(hyperStudent.pattern_strengths ?? []).length > 0 && (
                          <div className="hyper-result-card">
                            <h5>你已经具备的优势结构</h5>
                            {(hyperStudent.pattern_strengths ?? []).slice(0, 3).map((s: any, si: number) => (
                              <div key={si} className="hyper-strength-item">
                                {s.note}
                                {s.edge_type && <span className="hyper-inline-meta">来源：{s.edge_type}</span>}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>

                      <details className="hyper-evidence-panel">
                        <summary>展开看超图分析过程与老师可见证据</summary>
                        {hyperProjectView && (
                          <div className="hyper-guided-card" style={{ marginTop: 12 }}>
                            <h5>本轮超图参与了什么判断</h5>
                            <div className="hyper-guided-list">
                              <div className="hyper-guided-item"><strong>命中超边族</strong><span>{(hyperProjectView?.process_trace?.edge_families ?? []).join(" / ") || "暂无"}</span></div>
                              <div className="hyper-guided-item"><strong>关联规则</strong><span>{(hyperProjectView?.process_trace?.matched_rules ?? []).join(" / ") || "暂无"}</span></div>
                              <div className="hyper-guided-item"><strong>追问策略</strong><span>{hyperProjectView?.process_trace?.selected_strategy || "暂无"}</span></div>
                              <div className="hyper-guided-item"><strong>生成追问</strong><span>{hyperProjectView?.process_trace?.generated_question || "暂无"}</span></div>
                            </div>
                          </div>
                        )}

                        {hyperLibrary?.overview && (
                          <div className="hyper-library-board">
                            <h5>我们的超图库</h5>
                            <div className="panel-desc">这里显示的是当前持久化超图库总规模，不等于你这一轮命中的模式条数。</div>
                            <div className="hyper-topology-grid">
                              <div className="hyper-topology-card">
                                <div className="hyper-topology-title">总库规模</div>
                                <div className="hyper-topology-kpis">
                                  <div><strong>{hyperLibrary?.overview?.edge_count ?? 0}</strong><span>超边</span></div>
                                  <div><strong>{hyperLibrary?.overview?.node_count ?? 0}</strong><span>超节点</span></div>
                                  <div><strong>{hyperLibrary?.overview?.avg_member_count ?? 0}</strong><span>平均成员数</span></div>
                                </div>
                              </div>
                              <div className="hyper-topology-card">
                                <div className="hyper-topology-title">本轮对照</div>
                                <div className="hyper-topology-kpis">
                                  <div><strong>{hyperProjectView?.matched_edges?.length ?? 0}</strong><span>命中超边</span></div>
                                  <div><strong>{(hyperStudent?.hub_entities ?? []).length ?? 0}</strong><span>枢纽实体</span></div>
                                  <div><strong>{(hyperStudent?.cross_links ?? []).length ?? 0}</strong><span>跨维链接</span></div>
                                </div>
                              </div>
                              <div className="hyper-topology-card">
                                <div className="hyper-topology-title">家族分布</div>
                                {(hyperLibrary?.families ?? []).slice(0, 6).map((item: any, idx: number) => (
                                  <div key={idx} className="hyper-family-row">
                                    <span>{item.label ?? item.family}</span>
                                    <b>{item.count}</b>
                                  </div>
                                ))}
                              </div>
                            </div>
                          </div>
                        )}

                        {(hyperStudent.hub_entities ?? []).length > 0 && (
                          <div className="hyper-hubs">
                            <h5>核心支撑实体</h5>
                            {hyperStudent.hub_entities.map((h: any, hi: number) => (
                              <div key={hi} className="hyper-hub-item">
                                <span className="hyper-hub-name">{h.entity}</span>
                                <span className="hyper-hub-deg">{h.connections}个维度</span>
                                <p className="hyper-hub-note">{h.note}</p>
                              </div>
                            ))}
                          </div>
                        )}

                        {(hyperStudent.cross_links ?? []).length > 0 && (
                          <div className="hyper-cross">
                            <h5>维度联动证据</h5>
                            {hyperStudent.cross_links.slice(0, 8).map((cl: any, ci: number) => (
                              <div key={ci} className="hyper-cross-row">
                                <span className="hyper-cross-from">{cl.from_dim}</span>
                                <span className="hyper-cross-arrow">→ {cl.relation} →</span>
                                <span className="hyper-cross-to">{cl.to_dim}</span>
                              </div>
                            ))}
                          </div>
                        )}

                        {hyperEdges.length > 0 && (
                          <div className="hyper-teaching">
                            <h5>命中的超边证据</h5>
                            {hyperEdges.map((e: any) => (
                              <div key={e.hyperedge_id} className="hyper-edge-card">
                                <span className={`hyper-edge-type ${e.type}`}>{e.family_label || e.type}</span>
                                <span className="hyper-edge-note">{e.teaching_note}</span>
                                <div className="hyper-edge-meta">
                                  <span>支持度 {e.support ?? 0}</span>
                                  {e.stage_scope ? <span>阶段 {e.stage_scope}</span> : null}
                                  {e.severity ? <span>强度 {e.severity}</span> : null}
                                  {e.match_score ? <span>匹配分 {e.match_score}</span> : null}
                                </div>
                                {e.retrieval_reason && <div className="panel-desc" style={{marginTop: 6}}>命中原因：{e.retrieval_reason}</div>}
                                {(e.rules ?? []).length > 0 && (
                                  <div className="hyper-edge-nodes">
                                    {(e.rules ?? []).map((rule: string, ri: number) => <span key={ri} className="hyper-node-chip">规则 {rule}</span>)}
                                  </div>
                                )}
                                {(e.nodes ?? []).length > 0 && (
                                  <div className="hyper-edge-nodes">{e.nodes.map((n: string, ni: number) => <span key={ni} className="hyper-node-chip">{n.split("::").pop()}</span>)}</div>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </details>
                    </>
                  ) : (
                    <div className="hyper-empty-guide">
                      <div className="hyper-guide-icon">🌐</div>
                      <h5>什么是超图分析？</h5>
                      <p>超图分析从<strong>10个关键维度</strong>检测你的项目完整度：</p>
                      <div className="hyper-guide-dims">
                        {["👥 目标用户","🔴 痛点","💡 方案","⚙️ 技术","📊 市场","🏁 竞品","🔧 资源","💰 商业模式","👤 团队","📋 证据"].map((d,i) => (
                          <span key={i} className="hyper-guide-dim">{d}</span>
                        ))}
                      </div>
                      <p style={{marginTop:"12px",fontSize:"13px",color:"var(--text-muted)"}}>发送一段项目描述或上传商业计划书，AI会自动分析覆盖情况、发现缺口、对比历史案例模式。</p>
                    </div>
                  )}
                </div>
              )}

              {rightTab === "cases" && (
                <div className="right-section">
                  <h4>参考案例</h4>
                  <div className="panel-desc">基于 RAG 语义检索，从89份优秀案例知识库中找到与你项目最相似的参考。点击可查看详情。</div>
                  {ragCases.length > 0 ? ragCases.map((c: any, ci: number) => {
                    const simPct = Math.round((c.similarity ?? 0) * 100);
                    const simColor = simPct >= 70 ? "var(--accent-green)" : simPct >= 40 ? "var(--accent-yellow)" : "var(--text-muted)";
                    return (
                      <details key={ci} className="rag-case-card">
                        <summary className="rag-case-header">
                          <div className="rag-case-left">
                            <span className="rag-case-name">{c.project_name ?? c.case_id}</span>
                            <span className="rag-case-cat">{c.category}</span>
                          </div>
                          <div className="rag-case-sim-ring">
                            <svg viewBox="0 0 36 36" className="sim-ring-svg">
                              <circle cx="18" cy="18" r="14" fill="none" stroke="var(--border)" strokeWidth="3" />
                              <circle cx="18" cy="18" r="14" fill="none" stroke={simColor} strokeWidth="3" strokeLinecap="round" strokeDasharray={`${simPct * 0.88} 88`} transform="rotate(-90 18 18)" />
                            </svg>
                            <span className="sim-ring-num">{simPct}</span>
                          </div>
                        </summary>
                        <div className="rag-case-body">
                          {c.summary && <p className="rag-case-summary">{c.summary}</p>}
                          {(c.pain_points ?? []).length > 0 && <div className="rag-case-field"><strong>痛点：</strong>{c.pain_points.join("；")}</div>}
                          {(c.solution ?? []).length > 0 && <div className="rag-case-field"><strong>方案：</strong>{c.solution.join("；")}</div>}
                          {(c.innovation_points ?? []).length > 0 && <div className="rag-case-field"><strong>创新点：</strong>{c.innovation_points.join("；")}</div>}
                          {(c.evidence_quotes ?? []).length > 0 && <div className="rag-case-field"><strong>证据引用：</strong>{c.evidence_quotes.map((q: string, qi: number) => <blockquote key={qi}>{q}</blockquote>)}</div>}
                          {(c.risk_flags ?? []).length > 0 && <div className="rag-case-field"><strong>风险标记：</strong>{c.risk_flags.join("、")}</div>}
                        </div>
                      </details>
                    );
                  }) : <p className="right-hint">发送项目描述后，这里会显示知识库中最相似的参考案例</p>}
                </div>
              )}

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
