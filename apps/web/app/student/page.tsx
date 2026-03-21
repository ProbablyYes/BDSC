"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8787").trim().replace(/\/+$/, "");

type ChatMessage = { role: "user" | "assistant"; text: string; ts?: string; id: number };
type RightTab = "agents" | "task" | "risk" | "score" | "kg" | "hyper" | "cases" | "feedback" | "debug";
type ConvMeta = { conversation_id: string; title: string; created_at: string; message_count: number; last_message: string };

let _msgId = 0;

export default function StudentPage() {
  const [projectId, setProjectId] = useState("demo-project-001");
  const [studentId, setStudentId] = useState("student-001");
  const [classId, setClassId] = useState("2026A");
  const [cohortId, setCohortId] = useState("2026-Spring");
  const [mode, setMode] = useState("coursework");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [latestResult, setLatestResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [rightTab, setRightTab] = useState<RightTab>("task");
  const [rightOpen, setRightOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [teacherFeedback, setTeacherFeedback] = useState<any[]>([]);
  const [convSidebarOpen, setConvSidebarOpen] = useState(true);
  const [conversations, setConversations] = useState<ConvMeta[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [attachedFile, setAttachedFile] = useState<File | null>(null);

  // document review
  const [docReview, setDocReview] = useState<{ filename: string; sections: any[]; annotations: any[] } | null>(null);
  const [docReviewOpen, setDocReviewOpen] = useState(false);
  const [docReviewLoading, setDocReviewLoading] = useState(false);
  const [docSelectedText, setDocSelectedText] = useState("");
  const [docAskPos, setDocAskPos] = useState<{ x: number; y: number } | null>(null);

  // new features
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [searchQuery, setSearchQuery] = useState("");
  const [rightWidth, setRightWidth] = useState(360);
  const [likedMsgs, setLikedMsgs] = useState<Set<number>>(new Set());
  const [dislikedMsgs, setDislikedMsgs] = useState<Set<number>>(new Set());
  const [copiedId, setCopiedId] = useState<number | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const dragRef = useRef<{ active: boolean; startX: number; startW: number }>({ active: false, startX: 0, startW: 360 });

  // apply theme
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const loadConversations = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/api/conversations?project_id=${encodeURIComponent(projectId)}`);
      const d = await r.json();
      setConversations(d.conversations ?? []);
    } catch { /* ignore */ }
  }, [projectId]);

  useEffect(() => { loadConversations(); }, [loadConversations]);

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
  }

  async function loadConversation(cid: string) {
    try {
      const r = await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(cid)}?project_id=${encodeURIComponent(projectId)}`);
      const d = await r.json();
      setConversationId(cid);
      const rawMsgs = d.messages ?? [];
      const msgs: ChatMessage[] = rawMsgs.map((m: any) => ({
        role: m.role as "user" | "assistant",
        text: m.content ?? "",
        ts: m.timestamp ? new Date(m.timestamp).toLocaleTimeString() : undefined,
        id: ++_msgId,
      }));
      setMessages(msgs);

      const lastAssistant = [...rawMsgs].reverse().find((m: any) => m.role === "assistant" && m.agent_trace);
      if (lastAssistant?.agent_trace) {
        setLatestResult({
          diagnosis: lastAssistant.agent_trace.diagnosis ?? lastAssistant.agent_trace.orchestration ?? {},
          next_task: lastAssistant.agent_trace.next_task ?? {},
          kg_analysis: lastAssistant.agent_trace.kg_analysis ?? {},
          hypergraph_insight: lastAssistant.agent_trace.hypergraph_insight ?? {},
          hypergraph_student: lastAssistant.agent_trace.hypergraph_student ?? {},
          rag_cases: lastAssistant.agent_trace.rag_cases ?? [],
          agent_trace: lastAssistant.agent_trace,
        });
      } else {
        setLatestResult(null);
      }
    } catch { /* ignore */ }
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if ((!text && !attachedFile) || loading) return;
    setLoading(true);

    const displayText = attachedFile ? `${text ? text + " " : ""}📎 ${attachedFile.name}` : text;
    const userMsg: ChatMessage = { role: "user", text: displayText, ts: new Date().toLocaleTimeString(), id: ++_msgId };
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
        const resp = await fetch(`${API_BASE}/api/dialogue/turn-upload`, { method: "POST", body: form });
        data = await resp.json();
        if (!resp.ok) throw new Error(data?.detail ?? resp.statusText);
      } else {
        const resp = await fetch(`${API_BASE}/api/dialogue/turn`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: projectId,
            student_id: studentId,
            conversation_id: conversationId || undefined,
            class_id: classId || undefined,
            cohort_id: cohortId || undefined,
            message: text,
            mode,
          }),
        });
        data = await resp.json();
        if (!resp.ok) throw new Error(data?.detail ?? resp.statusText);
      }

      setLatestResult(data);
      if (data.conversation_id && !conversationId) {
        setConversationId(data.conversation_id);
      }
      const reply = (data?.assistant_message ?? "").trim() || "（智能体未返回有效回复）";
      setMessages((p) => [...p, { role: "assistant", text: reply, ts: new Date().toLocaleTimeString(), id: ++_msgId }]);

      // trigger doc review if file was uploaded and sections returned
      if (attachedFile && data.doc_sections?.length > 0) {
        setDocReview({ filename: attachedFile.name, sections: data.doc_sections, annotations: [] });
        setDocReviewOpen(true);
        setDocReviewLoading(true);
        fetch(`${API_BASE}/api/document-review`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sections: data.doc_sections, mode, context: text }),
        })
          .then((r) => r.json())
          .then((d) => setDocReview((prev) => prev ? { ...prev, annotations: d.annotations ?? [] } : prev))
          .catch(() => {})
          .finally(() => setDocReviewLoading(false));
      }

      setAttachedFile(null);
      loadConversations();
    } catch (err: any) {
      setMessages((p) => [...p, { role: "assistant", text: `错误：${err?.message ?? "无法连接后端"}`, id: ++_msgId }]);
    }
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
      const resp = await fetch(`${API_BASE}/api/project/${encodeURIComponent(projectId)}/feedback`);
      const data = await resp.json();
      setTeacherFeedback(data.feedback ?? []);
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

  useEffect(() => {
    if (latestResult && latestResult.diagnosis) {
      setResultHistory((prev) => [...prev, latestResult]);
    }
  }, [latestResult]);

  useEffect(() => { setResultHistory([]); }, [conversationId]);

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

  const taskHistory = useMemo(() => {
    const tasks: { task: any; turn: number }[] = [];
    resultHistory.forEach((r, i) => {
      const t = r?.next_task;
      if (t?.title && t.title !== "描述你的项目") tasks.push({ task: t, turn: i + 1 });
    });
    return tasks;
  }, [resultHistory]);

  const nextTask = latestResult?.next_task ?? null;
  const hyperEdges = useMemo(() => latestResult?.hypergraph_insight?.edges ?? [], [latestResult]);
  const hyperStudent = latestResult?.hypergraph_student ?? latestResult?.agent_trace?.hypergraph_student ?? null;
  const kgAnalysis = latestResult?.kg_analysis ?? latestResult?.agent_trace?.kg_analysis ?? null;
  const ragCases = useMemo(() => latestResult?.rag_cases ?? latestResult?.agent_trace?.rag_cases ?? [], [latestResult]);
  const webSearch = latestResult?.agent_trace?.web_search ?? latestResult?.web_search ?? null;
  const orchestration = latestResult?.agent_trace?.orchestration ?? {};
  const roleAgents = latestResult?.agent_trace?.role_agents ?? {};
  const agentsCalled = orchestration?.agents_called ?? [];
  const overallScore = useMemo(() => {
    const scores = resultHistory.map((r) => r?.diagnosis?.overall_score).filter((s) => s != null);
    return scores.length > 0 ? scores[scores.length - 1] : latestResult?.diagnosis?.overall_score ?? null;
  }, [resultHistory, latestResult]);

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
            VentureAgent
          </Link>
          <span className="topbar-sep" />
          <span className="topbar-label">双创智能教练</span>
        </div>
        <div className="topbar-center">
          <div className="topbar-mode-toggle">
            <button type="button" className={`topbar-mode-opt${mode === "coursework" ? " active" : ""}`} onClick={() => setMode("coursework")}>课程辅导</button>
            <button type="button" className={`topbar-mode-opt${mode === "competition" ? " active" : ""}`} onClick={() => setMode("competition")}>竞赛冲刺</button>
            <button type="button" className={`topbar-mode-opt${mode === "learning" ? " active" : ""}`} onClick={() => setMode("learning")}>个人学习</button>
          </div>
          {overallScore !== null && <span className="topbar-score">{overallScore}<small>/10</small></span>}
        </div>
        <div className="topbar-right">
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
          <button type="button" className="topbar-btn" onClick={() => setRightOpen((v) => !v)}>
            {rightOpen ? "收起面板" : "分析面板"}
          </button>
          <Link href="/teacher" className="topbar-btn">教师端</Link>
        </div>
      </header>

      {/* ── Settings Drawer ── */}
      {settingsOpen && (
        <div className="settings-drawer">
          <div className="settings-grid">
            <label>项目ID <input value={projectId} onChange={(e) => setProjectId(e.target.value)} /></label>
            <label>学生ID <input value={studentId} onChange={(e) => setStudentId(e.target.value)} /></label>
            <label>班级 <input value={classId} onChange={(e) => setClassId(e.target.value)} /></label>
            <label>学期 <input value={cohortId} onChange={(e) => setCohortId(e.target.value)} /></label>
          </div>
        </div>
      )}

      <div className="chat-body">
        {/* ── Conversation Sidebar ── */}
        {convSidebarOpen && (
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
                <button
                  key={c.conversation_id}
                  className={`conv-item ${c.conversation_id === conversationId ? "active" : ""}`}
                  onClick={() => loadConversation(c.conversation_id)}
                >
                  <span className="conv-title">{c.title || "新对话"}</span>
                  <span className="conv-meta">{c.message_count}条 · {(c.created_at ?? "").slice(5, 16)}</span>
                </button>
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
                <h2>你好，我是你的双创教练</h2>
                <p>告诉我你的项目想法、当前困惑，或上传计划书，我会帮你诊断风险并给出下一步行动。</p>
                <div className="chat-hints">
                  {[
                    { icon: "💡", text: "我想做一个校园二手交易平台，目标用户是大学生" },
                    { icon: "🔍", text: "帮我分析一下我的商业模式有什么问题" },
                    { icon: "📚", text: "什么是MVP，教我怎么做" },
                  ].map((h) => (
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
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
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

            {loading && (
              <div className="msg-row assistant">
                <div className="msg-avatar">AI</div>
                <div className="msg-content"><div className="msg-bubble typing">
                  <div className="typing-dots"><span /><span /><span /></div>
                  思考中...
                </div></div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* ── Input Bar ── */}
          <div className="chat-inputbar-wrapper">
            {docReview && !docReviewOpen && (
              <div className="attached-file-badge doc-review-reopen" onClick={() => setDocReviewOpen(true)} style={{ cursor: "pointer" }}>
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
                placeholder="描述你的项目想法、困惑或问题…  (Shift+Enter 换行)"
                rows={1}
              />
              <button type="submit" className="send-btn" disabled={loading || (!input.trim() && !attachedFile)}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 2L11 13"/><path d="M22 2L15 22L11 13L2 9L22 2Z"/></svg>
              </button>
            </form>
          </div>
        </main>

        {/* ── Right Panel (resizable) ── */}
        {rightOpen && (
          <aside className="chat-right" style={{ width: rightWidth }}>
            <div className="right-drag-handle" onMouseDown={startDrag} />
            <div className="right-tabs-scroll">
              {([
                { id: "agents", icon: "🤖", label: "智能体" },
                { id: "task",   icon: "📋", label: "任务" },
                { id: "risk",   icon: "⚠️", label: "风险" },
                { id: "score",  icon: "📊", label: "评分" },
                { id: "kg",     icon: "🔗", label: "图谱" },
                { id: "hyper",  icon: "🌐", label: "超图" },
                { id: "cases",  icon: "📚", label: "案例" },
                { id: "feedback", icon: "💬", label: "批注" },
                { id: "debug",  icon: "🛠", label: "调试" },
              ] as { id: RightTab; icon: string; label: string }[]).map((t) => (
                <button key={t.id} className={`rtab-pill ${rightTab === t.id ? "active" : ""}`} onClick={() => { setRightTab(t.id); if (t.id === "feedback") loadFeedback(); }}>
                  <span className="rtab-icon">{t.icon}</span>
                  <span className="rtab-label">{t.label}</span>
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
                        const nameMap: Record<string, string> = { coach: "🎯 项目教练", analyst: "⚠️ 风险分析师", advisor: "🏆 竞赛顾问", tutor: "📚 学习导师", grader: "📊 评分官", planner: "📋 行动规划师" };
                        const toolMap: Record<string, string> = { diagnosis: "诊断引擎", rag: "案例知识库", kg_extract: "知识图谱", web_search: "联网搜索", hypergraph: "超图分析", hypergraph_student: "超图维度", challenge_strategies: "追问策略库", critic_llm: "批判思维", competition_llm: "竞赛评审", learning_llm: "概念教学", rag_reference: "案例引用", rubric_engine: "评分标准", kg_scores: "图谱评分", next_task: "任务建议", critic: "批判分析" };
                        return (
                          <details key={key} className="agent-card" open>
                            <summary className="agent-card-header">
                              <span className="agent-card-name">{nameMap[key] ?? val.agent ?? key}</span>
                              <span className="agent-card-tools">{(val.tools_used ?? []).map((t: string) => toolMap[t] ?? t).join(" · ")}</span>
                            </summary>
                            <div className="agent-card-body">
                              <ReactMarkdown remarkPlugins={[remarkGfm]}>{val.analysis}</ReactMarkdown>
                            </div>
                          </details>
                        );
                      })}
                    </>
                  ) : <p className="right-hint">发送消息后，这里会展示各专家Agent的协作过程和独立分析结果</p>}
                </div>
              )}

              {rightTab === "task" && (
                <>
                  <div className="panel-desc">基于对话上下文智能推荐的行动任务，随对话深入会不断细化。</div>
                  {nextTask && nextTask.title !== "描述你的项目" ? (
                    <div className="task-current-card">
                      <div className="task-current-badge">当前最优先</div>
                      <h4>{nextTask.title}</h4>
                      <p>{nextTask.description}</p>
                      {(nextTask.acceptance_criteria ?? []).length > 0 && (
                        <div className="task-criteria">
                          <h5>验收标准</h5>
                          <ul>{(nextTask.acceptance_criteria ?? []).map((c: string, ci: number) => <li key={ci}>{c}</li>)}</ul>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="task-empty-state">
                      <div className="task-empty-icon">📋</div>
                      <p>详细描述你的项目后，系统会推荐针对性的行动任务</p>
                    </div>
                  )}
                  {taskHistory.length > 1 && (
                    <div className="task-timeline">
                      <h5>历史建议轨迹</h5>
                      <div className="task-tl-list">
                        {taskHistory.slice().reverse().slice(0, 6).map((th, ti) => (
                          <div key={ti} className={`task-tl-item ${ti === 0 ? "latest" : ""}`}>
                            <div className="task-tl-dot" />
                            <div className="task-tl-content">
                              <span className="task-tl-turn">第{th.turn}轮</span>
                              <span className="task-tl-title">{th.task.title}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
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
                          <div key={r.item} className="score-row">
                            <span className="score-label">{r.item}</span>
                            <div className="score-bar-track"><div className="score-bar-fill" style={{ width: `${pct}%`, background: color }} /></div>
                            <span className="score-value">{r.score}</span>
                            {r.trend && <span className={`score-trend ${r.trend}`}>{r.trend === "up" ? "↑" : r.trend === "down" ? "↓" : "="}</span>}
                          </div>
                        );
                      })}
                    </div>
                  ) : <p className="right-hint">提交项目描述后显示评分，描述越完整评分越有参考价值</p>}
                </>
              )}

              {rightTab === "kg" && (
                <div className="right-section">
                  <h4>项目结构体检</h4>
                  <div className="panel-desc">AI 将你的描述拆解为核心要素（用户、产品、技术、市场等），检测你是否遗漏了关键部分。<strong>结构缺陷</strong>是你最需要补充的内容。</div>
                  {kgAnalysis ? (
                    <>
                      {/* Stats overview */}
                      <div className="kg-stats-row">
                        <div className="kg-stat-box">
                          <span className="kg-stat-num">{(kgAnalysis.entities ?? []).length}</span>
                          <span className="kg-stat-label">实体</span>
                        </div>
                        <div className="kg-stat-box">
                          <span className="kg-stat-num">{(kgAnalysis.relationships ?? []).length}</span>
                          <span className="kg-stat-label">关系</span>
                        </div>
                        <div className="kg-stat-box">
                          <span className="kg-stat-num">{kgAnalysis.completeness_score ?? 0}<small>/10</small></span>
                          <span className="kg-stat-label">完整度</span>
                        </div>
                        <div className="kg-stat-box">
                          <span className="kg-stat-num">{(kgAnalysis.structural_gaps ?? []).length}</span>
                          <span className="kg-stat-label">缺陷</span>
                        </div>
                      </div>
                      {kgAnalysis.insight && <p className="kg-insight">{kgAnalysis.insight}</p>}

                      {/* Interactive Mind Map by entity type */}
                      {(kgAnalysis.entities ?? []).length > 0 && (() => {
                        const entities: any[] = kgAnalysis.entities ?? [];
                        const typeNames: Record<string, string> = {
                          stakeholder: "👥 目标用户", product: "📦 产品", market: "📊 市场",
                          pain_point: "🔴 痛点", solution: "💡 方案", technology: "⚙️ 技术",
                          competitor: "🏁 竞品", resource: "🔧 资源", team: "👤 团队",
                          business_model: "💰 商业模式", evidence: "📋 证据",
                        };
                        const typeColors: Record<string, string> = {
                          stakeholder: "#69c0e0", product: "#6ba3d6", market: "#e0a84c",
                          pain_point: "#e07070", solution: "#5cbd8a", technology: "#a88ccc",
                          competitor: "#c8a048", resource: "#60b8b8", team: "#d4a5d0",
                          business_model: "#e8b960", evidence: "#7ec87e",
                        };
                        const grouped: Record<string, any[]> = {};
                        entities.forEach((e: any) => {
                          const t = e.type || "other";
                          if (!grouped[t]) grouped[t] = [];
                          grouped[t].push(e);
                        });
                        return (
                          <div className="kg-mindmap">
                            <h5>🧠 项目结构思维导图</h5>
                            <div className="panel-desc">按维度分组展示你描述中的核心要素，点击展开/折叠。</div>
                            {Object.entries(grouped).map(([type, items]) => {
                              const color = typeColors[type] ?? "#6ba3d6";
                              const name = typeNames[type] ?? type;
                              const rels = (kgAnalysis.relationships ?? []).filter((r: any) =>
                                items.some((e: any) => e.id === r.source || e.id === r.target)
                              );
                              return (
                                <details key={type} className="kg-mm-group" open>
                                  <summary className="kg-mm-header" style={{ borderLeftColor: color }}>
                                    <span className="kg-mm-type">{name}</span>
                                    <span className="kg-mm-count">{items.length}</span>
                                  </summary>
                                  <div className="kg-mm-body">
                                    {items.map((e: any) => (
                                      <div key={e.id} className="kg-mm-entity" style={{ borderColor: color }}>
                                        <span className="kg-mm-dot" style={{ background: color }} />
                                        <span className="kg-mm-label">{e.label}</span>
                                      </div>
                                    ))}
                                    {rels.length > 0 && (
                                      <div className="kg-mm-rels">
                                        {rels.slice(0, 4).map((r: any, ri: number) => (
                                          <div key={ri} className="kg-mm-rel">
                                            <span>{entities.find((e: any) => e.id === r.source)?.label ?? r.source}</span>
                                            <span className="kg-mm-arrow">→ {r.relation} →</span>
                                            <span>{entities.find((e: any) => e.id === r.target)?.label ?? r.target}</span>
                                          </div>
                                        ))}
                                      </div>
                                    )}
                                  </div>
                                </details>
                              );
                            })}
                          </div>
                        );
                      })()}

                      {(kgAnalysis.content_strengths ?? []).length > 0 && (
                        <div className="kg-strengths"><h5>✅ 你的项目优势</h5><div className="panel-desc">这些是你已经做得比较好的部分，可以在路演中重点突出。</div>{kgAnalysis.content_strengths.map((s: string, si: number) => <div key={si} className="kg-strength-item">{s}</div>)}</div>
                      )}
                      {kgAnalysis.section_scores && Object.keys(kgAnalysis.section_scores).length > 0 && (
                        <div className="kg-section-scores"><h5>📐 各维度完成度</h5><div className="panel-desc">分数越低的维度越需要你补充内容。</div>{Object.entries(kgAnalysis.section_scores).map(([k, v]: [string, any]) => (
                          <div key={k} className="score-row">
                            <span className="score-label">{{ problem_definition: "问题定义", user_evidence: "用户证据", solution_feasibility: "方案可行性", business_model: "商业模式", competitive_advantage: "竞争优势" }[k] ?? k}</span>
                            <div className="score-bar-track"><div className="score-bar-fill" style={{ width: `${Math.min(100, (Number(v) / 10) * 100)}%` }} /></div>
                            <span className="score-value">{String(v)}</span>
                          </div>
                        ))}</div>
                      )}
                      {(kgAnalysis.entities ?? []).length > 0 && (
                        <div className="kg-entities"><h5>提取的关键实体</h5><div className="panel-desc">从你的描述中识别出的核心要素，颜色代表类型。</div><div className="kg-entity-grid">{kgAnalysis.entities.map((e: any) => <span key={e.id} className={`kg-entity-chip ${e.type}`} title={e.type}>{e.label}</span>)}</div></div>
                      )}
                      {(kgAnalysis.relationships ?? []).length > 0 && (
                        <div className="kg-relations"><h5>实体之间的关系</h5>{kgAnalysis.relationships.map((r: any, ri: number) => <div key={ri} className="kg-rel-row"><span className="kg-rel-src">{r.source}</span><span className="kg-rel-arrow">→ {r.relation} →</span><span className="kg-rel-tgt">{r.target}</span></div>)}</div>
                      )}
                      {(kgAnalysis.structural_gaps ?? []).length > 0 && (
                        <div className="kg-gaps"><h5>🔴 你需要补充的内容</h5><div className="panel-desc">以下是优秀项目通常会涵盖但你还没提到的关键要素。补上它们能显著提高项目完整度和评分。</div>{kgAnalysis.structural_gaps.map((g: string, gi: number) => <div key={gi} className="kg-gap-item">⚠ {g}</div>)}</div>
                      )}
                    </>
                  ) : <p className="right-hint">发送项目描述后显示知识图谱分析</p>}
                </div>
              )}

              {rightTab === "hyper" && (
                <div className="right-section">
                  <h4>项目全景诊断</h4>
                  <div className="panel-desc">一个好的创业项目需要覆盖10个关键维度（用户、市场、技术、团队等）。这里检测你覆盖了几个，哪些<strong>还缺</strong>，以及和历史优秀/失败项目的模式对比。</div>
                  {hyperStudent?.ok ? (
                    <>
                      {/* Dimension Coverage Ring + Grid */}
                      <div className="hyper-coverage">
                        <div className="hyper-cov-head">
                          <div className="score-total-ring" style={{ margin: "0" }}>
                            <svg viewBox="0 0 80 80" className="ring-svg">
                              <circle cx="40" cy="40" r="32" className="ring-bg" />
                              <circle cx="40" cy="40" r="32" className="ring-fg" strokeDasharray={`${((hyperStudent.coverage_score ?? 0) / 10) * 201} 201`} />
                            </svg>
                            <div className="ring-text"><span className="ring-num">{hyperStudent.coverage_score}</span><span className="ring-max">/10</span></div>
                          </div>
                          <div className="hyper-cov-meta">
                            <span className="hyper-cov-title">维度覆盖度</span>
                            <span className="hyper-cov-sub">{hyperStudent.covered_count ?? 0}个已覆盖 / {hyperStudent.total_dimensions ?? 10}个总维度</span>
                          </div>
                        </div>
                        <div className="hyper-dim-grid">
                          {Object.entries(hyperStudent.dimensions ?? {}).map(([k, v]: [string, any]) => (
                            <div key={k} className={`hyper-dim-chip ${v.covered ? "covered" : "missing"}`} title={v.covered ? `${v.count}个实体` : "未覆盖"}>
                              <span className="hdim-dot" />{v.name}
                              {v.covered && <span className="hdim-count">{v.count}</span>}
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Missing Dimensions */}
                      {(hyperStudent.missing_dimensions ?? []).length > 0 && (
                        <div className="hyper-missing">
                          <h5>🔴 你还没提到的关键维度</h5>
                          <div className="panel-desc">按紧急度排序，优先补充排在前面的。</div>
                          {hyperStudent.missing_dimensions.map((m: any, mi: number) => (
                            <div key={mi} className={`hyper-missing-item importance-${m.importance}`}>
                              <span className="hyper-missing-dim">{m.dimension}</span>
                              <span className={`hyper-importance-badge ${m.importance}`}>{m.importance}</span>
                              <p className="hyper-missing-reason">{m.recommendation}</p>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Hub Entities */}
                      {(hyperStudent.hub_entities ?? []).length > 0 && (
                        <div className="hyper-hubs">
                          <h5>核心支撑实体</h5>
                          <div className="panel-desc">连接多个维度的关键实体，是你项目的核心支撑点。</div>
                          {hyperStudent.hub_entities.map((h: any, hi: number) => (
                            <div key={hi} className="hyper-hub-item">
                              <span className="hyper-hub-name">{h.entity}</span>
                              <span className="hyper-hub-deg">{h.connections}个维度</span>
                              <p className="hyper-hub-note">{h.note}</p>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Cross-dimensional Links */}
                      {(hyperStudent.cross_links ?? []).length > 0 && (
                        <div className="hyper-cross">
                          <h5>🔗 你项目中的维度间联动</h5>
                          <div className="panel-desc">这些联动关系说明你的项目有内在逻辑串联，联动越多越好。</div>
                          {hyperStudent.cross_links.map((cl: any, ci: number) => (
                            <div key={ci} className="hyper-cross-row">
                              <span className="hyper-cross-from">{cl.from_dim}</span>
                              <span className="hyper-cross-arrow">→ {cl.relation} →</span>
                              <span className="hyper-cross-to">{cl.to_dim}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Pattern Warnings */}
                      {(hyperStudent.pattern_warnings ?? []).length > 0 && (
                        <div className="hyper-warnings">
                          <h5>⚠ 历史失败模式预警</h5>
                          <div className="panel-desc">你的项目和以往失败/高风险项目的某些模式相似，需要注意规避。</div>
                          {hyperStudent.pattern_warnings.map((w: any, wi: number) => (
                            <div key={wi} className="hyper-warning-item">{w.warning}</div>
                          ))}
                        </div>
                      )}

                      {/* Pattern Strengths */}
                      {(hyperStudent.pattern_strengths ?? []).length > 0 && (
                        <div className="hyper-strengths">
                          <h5>✅ 和优秀项目的相似之处</h5>
                          {hyperStudent.pattern_strengths.map((s: any, si: number) => (
                            <div key={si} className="hyper-strength-item">{s.note}</div>
                          ))}
                        </div>
                      )}

                      {/* Teaching Hypergraph Edges */}
                      {hyperEdges.length > 0 && (
                        <div className="hyper-teaching">
                          <h5>教学超图洞察</h5>
                          <div className="panel-desc">从历史案例库中发现的跨维度关联模式。</div>
                          {hyperEdges.map((e: any) => (
                            <div key={e.hyperedge_id} className="hyper-edge-card">
                              <span className={`hyper-edge-type ${e.type}`}>{{ Risk_Pattern_Edge: "风险", Value_Loop_Edge: "价值", Resource_Leverage_Edge: "资源" }[e.type as string] ?? e.type}</span>
                              <span className="hyper-edge-note">{e.teaching_note}</span>
                              {(e.nodes ?? []).length > 0 && (
                                <div className="hyper-edge-nodes">{e.nodes.map((n: string, ni: number) => <span key={ni} className="hyper-node-chip">{n.split("::").pop()}</span>)}</div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  ) : (
                    <>
                      {hyperEdges.length > 0 ? (
                        <div className="hyper-teaching">
                          <h5>教学超图洞察</h5>
                          {hyperEdges.map((e: any) => (
                            <div key={e.hyperedge_id} className="right-tag">{e.teaching_note}</div>
                          ))}
                        </div>
                      ) : <p className="right-hint">发送项目描述后，超图将分析你的项目跨维度覆盖情况</p>}
                    </>
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
                  <div className="panel-desc">你的导师对项目的反馈意见。这些批注会影响AI后续给你的建议方向。</div>
                  {teacherFeedback.length > 0 ? teacherFeedback.map((fb, fi) => (
                    <div key={fi} className="right-card">
                      <p>{fb.comment}</p>
                      <span className="msg-time">{fb.teacher_id} · {(fb.created_at ?? "").slice(0, 16)}</span>
                      {(fb.focus_tags ?? []).length > 0 && <div className="tch-tag-row">{fb.focus_tags.map((t: string) => <span key={t} className="tch-tag">{t}</span>)}</div>}
                    </div>
                  )) : <p className="right-hint">暂无教师批注。导师批注后会显示在这里。</p>}
                </div>
              )}

              {rightTab === "debug" && (
                <div className="right-section">
                  <div className="panel-desc">系统内部运行状态，开发调试用。</div>
                  <div className="debug-row"><span>识别意图</span><span>{orchestration?.intent ?? "-"}</span></div>
                  <div className="debug-row"><span>置信度</span><span>{orchestration?.confidence ?? "-"}</span></div>
                  <div className="debug-row"><span>识别引擎</span><span>{{ rule: "关键词匹配", llm: "LLM分类", follow_up: "追问继承", file_detect: "文件检测", heuristic_long: "长文启发", heuristic_short: "短文启发" }[orchestration?.engine as string] ?? orchestration?.engine ?? "-"}</span></div>
                  <div className="debug-row"><span>调用Agent</span><span>{(orchestration?.agents_called ?? []).join(" → ") || "-"}</span></div>
                  <div className="debug-row"><span>执行管线</span><span>{(orchestration?.pipeline ?? []).join(" → ") || "-"}</span></div>
                  <div className="debug-row"><span>编排策略</span><span>{orchestration?.strategy ?? "-"}</span></div>
                  <div className="debug-row"><span>LLM启用</span><span>{String(orchestration?.llm_enabled ?? false)}</span></div>
                  <div className="debug-row"><span>会话ID</span><span className="debug-conv-id">{conversationId ?? "无"}</span></div>
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
