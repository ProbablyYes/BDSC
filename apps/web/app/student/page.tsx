"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8787").trim().replace(/\/+$/, "");

type ChatMessage = { role: "user" | "assistant"; text: string; ts?: string; id: number };
type RightTab = "agents" | "task" | "risk" | "score" | "kg" | "cases" | "upload" | "feedback" | "debug";
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

  const rubric = useMemo(() => latestResult?.diagnosis?.rubric ?? [], [latestResult]);
  const triggeredRules = useMemo(() => latestResult?.diagnosis?.triggered_rules ?? [], [latestResult]);
  const nextTask = latestResult?.next_task ?? null;
  const hyperEdges = useMemo(() => latestResult?.hypergraph_insight?.edges ?? [], [latestResult]);
  const kgAnalysis = latestResult?.kg_analysis ?? latestResult?.agent_trace?.kg_analysis ?? null;
  const ragCases = useMemo(() => latestResult?.rag_cases ?? latestResult?.agent_trace?.rag_cases ?? [], [latestResult]);
  const orchestration = latestResult?.agent_trace?.orchestration ?? {};
  const roleAgents = latestResult?.agent_trace?.role_agents ?? {};
  const agentsCalled = orchestration?.agents_called ?? [];
  const overallScore = latestResult?.diagnosis?.overall_score ?? null;

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
            <button type="button" className={`topbar-mode-opt${mode === "competition" ? " active" : ""}`} onClick={() => setMode("competition")}>竞赛模式</button>
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
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
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
            {attachedFile && (
              <div className="attached-file-badge">
                <span>📎 {attachedFile.name}</span>
                <button type="button" onClick={() => setAttachedFile(null)} className="remove-file">✕</button>
              </div>
            )}
            <form className="chat-inputbar" onSubmit={send}>
              <input ref={fileInputRef} type="file" hidden accept=".pdf,.docx,.pptx,.txt,.md" onChange={handleFileSelect} />
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
            <div className="right-tabs">
              {(["agents", "task", "risk", "score", "kg", "cases", "upload", "feedback", "debug"] as RightTab[]).map((t) => (
                <button key={t} className={`right-tab ${rightTab === t ? "active" : ""}`} onClick={() => { setRightTab(t); if (t === "feedback") loadFeedback(); }}>
                  {{ agents: "智能体", task: "任务", risk: "风险", score: "评分", kg: "图谱", cases: "案例", upload: "上传", feedback: "批注", debug: "调试" }[t]}
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
                      {Object.entries(roleAgents).map(([key, val]: [string, any]) => {
                        if (!val || !val.analysis) return null;
                        const nameMap: Record<string, string> = { coach: "🎯 项目教练", analyst: "⚠️ 风险分析师", advisor: "🏆 竞赛顾问", tutor: "📚 学习导师", grader: "📊 评分官", planner: "📋 行动规划师" };
                        const toolMap: Record<string, string> = { diagnosis: "诊断引擎", rag: "案例知识库", kg_extract: "知识图谱", web_search: "联网搜索", hypergraph: "超图分析", challenge_strategies: "追问策略库", critic_llm: "批判思维", competition_llm: "竞赛评审", learning_llm: "概念教学", rag_reference: "案例引用", rubric_engine: "评分标准", kg_scores: "图谱评分", next_task: "任务建议", critic: "批判分析" };
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
                  <div className="panel-desc">系统根据你的描述，自动推荐当前最应该完成的一项任务，帮你聚焦方向。</div>
                  {nextTask ? (
                    <div className="right-card">
                      <h4>{nextTask.title}</h4>
                      <p>{nextTask.description}</p>
                      {(nextTask.acceptance_criteria ?? []).length > 0 && (
                        <>
                          <h5 className="right-sub-label">验收标准（完成这些才算做好）</h5>
                          <ul className="right-list">{(nextTask.acceptance_criteria ?? []).map((c: string, ci: number) => <li key={ci}>{c}</li>)}</ul>
                        </>
                      )}
                    </div>
                  ) : <p className="right-hint">发送一条消息后，这里会显示你下一步最应该做的事</p>}
                  {hyperEdges.length > 0 && (
                    <div className="right-section">
                      <h4>超图洞察</h4>
                      <div className="panel-desc">基于知识超图发现的跨维度关联模式，帮助你发现隐藏的问题。</div>
                      {hyperEdges.map((e: any) => <div key={e.hyperedge_id} className="right-tag">{e.teaching_note}</div>)}
                    </div>
                  )}
                </>
              )}

              {rightTab === "risk" && (
                <>
                  <div className="panel-desc">基于50+创业风险规则库，检测你的描述中可能存在的隐患。颜色越深代表风险越高。</div>
                  {triggeredRules.length > 0 ? (
                    <div className="right-section">
                      {triggeredRules.map((r: any) => (
                        <div key={r.id} className={`risk-item ${r.severity}`}>
                          <span className="risk-id">{r.id}</span>
                          <span className="risk-name">{r.name}</span>
                          <span className={`risk-badge ${r.severity}`}>{{ high: "高危", medium: "中等", low: "轻微" }[r.severity as string] ?? r.severity}</span>
                        </div>
                      ))}
                    </div>
                  ) : <p className="right-hint">暂无风险命中——描述越详细，风险检测越准确</p>}
                </>
              )}

              {rightTab === "score" && (
                <>
                  <div className="panel-desc">9维度量化评分，对标创业竞赛评审标准。每个维度满分10分，帮你发现短板。</div>
                  {rubric.length > 0 ? (
                    <div className="right-section">
                      {rubric.map((r: any) => (
                        <div key={r.item} className="score-row">
                          <span className="score-label">{r.item}</span>
                          <div className="score-bar-track"><div className="score-bar-fill" style={{ width: `${Math.min(100, (r.score / 10) * 100)}%` }} /></div>
                          <span className="score-value">{r.score}</span>
                        </div>
                      ))}
                      {overallScore !== null && <div className="score-total">综合评分: <strong>{overallScore}/10</strong></div>}
                    </div>
                  ) : <p className="right-hint">提交项目描述后显示评分，描述越完整评分越有参考价值</p>}
                </>
              )}

              {rightTab === "kg" && (
                <div className="right-section">
                  <h4>知识图谱分析</h4>
                  <div className="panel-desc">AI将你的内容拆解为实体和关系，构建知识图谱。结构缺陷=你没提到但很重要的部分。</div>
                  {kgAnalysis ? (
                    <>
                      <div className="kg-score-row">
                        <span>结构完整度</span>
                        <div className="score-bar-track"><div className="score-bar-fill kg-bar" style={{ width: `${Math.min(100, (kgAnalysis.completeness_score ?? 0) * 10)}%` }} /></div>
                        <span className="score-value">{kgAnalysis.completeness_score ?? 0}/10</span>
                      </div>
                      {kgAnalysis.insight && <p className="kg-insight">{kgAnalysis.insight}</p>}
                      {(kgAnalysis.content_strengths ?? []).length > 0 && (
                        <div className="kg-strengths"><h5>做得好的地方</h5>{kgAnalysis.content_strengths.map((s: string, si: number) => <div key={si} className="kg-strength-item">{s}</div>)}</div>
                      )}
                      {kgAnalysis.section_scores && Object.keys(kgAnalysis.section_scores).length > 0 && (
                        <div className="kg-section-scores"><h5>各维度深度评估</h5>{Object.entries(kgAnalysis.section_scores).map(([k, v]: [string, any]) => (
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
                        <div className="kg-gaps"><h5>结构性缺陷</h5><div className="panel-desc">你的内容中缺失的关键要素——这些是最需要补充的部分。</div>{kgAnalysis.structural_gaps.map((g: string, gi: number) => <div key={gi} className="kg-gap-item">⚠ {g}</div>)}</div>
                      )}
                    </>
                  ) : <p className="right-hint">发送项目描述后显示知识图谱分析</p>}
                </div>
              )}

              {rightTab === "cases" && (
                <div className="right-section">
                  <h4>参考案例</h4>
                  <div className="panel-desc">基于 RAG 语义检索，从89份优秀案例知识库中找到与你项目最相似的参考。点击可查看详情。</div>
                  {ragCases.length > 0 ? ragCases.map((c: any, ci: number) => (
                    <details key={ci} className="rag-case-card">
                      <summary className="rag-case-header">
                        <span className="rag-case-name">{c.project_name ?? c.case_id}</span>
                        <span className="rag-case-cat">{c.category}</span>
                        <span className="rag-case-sim">{(c.similarity * 100).toFixed(0)}%</span>
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
                  )) : <p className="right-hint">发送项目描述后，这里会显示知识库中最相似的参考案例</p>}
                </div>
              )}

              {rightTab === "upload" && (
                <div className="right-section">
                  <h4>文件上传</h4>
                  <div className="panel-desc">上传你的计划书、PPT或文档，AI会深度阅读全文并给出具体修改建议。</div>
                  <p className="right-hint">点击输入栏左侧的 📎 按钮选择文件，支持以下格式：</p>
                  <div className="upload-formats">
                    {[".pdf", ".docx", ".pptx", ".txt", ".md"].map((f) => <span key={f} className="format-chip">{f}</span>)}
                  </div>
                  <p className="right-hint">上传后可以附带一句话描述你想重点关注的问题。</p>
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
                  <div className="debug-row"><span>调用Agent</span><span>{(orchestration?.agents_called ?? []).join(" → ") || "-"}</span></div>
                  <div className="debug-row"><span>执行管线</span><span>{(orchestration?.pipeline ?? []).join(" → ") || "-"}</span></div>
                  <div className="debug-row"><span>编排策略</span><span>{orchestration?.strategy ?? "-"}</span></div>
                  <div className="debug-row"><span>管线Agent</span><span>{(orchestration?.pipeline ?? []).join(", ") || "-"}</span></div>
                  <div className="debug-row"><span>LLM启用</span><span>{String(orchestration?.llm_enabled ?? false)}</span></div>
                  <div className="debug-row"><span>会话ID</span><span className="debug-conv-id">{conversationId ?? "无"}</span></div>
                  <details className="debug-json"><summary>原始 JSON</summary><pre>{JSON.stringify(latestResult, null, 2) ?? "暂无"}</pre></details>
                </div>
              )}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
