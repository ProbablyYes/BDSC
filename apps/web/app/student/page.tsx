"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8787").trim().replace(/\/+$/, "");

type ChatMessage = { role: "user" | "assistant"; text: string; ts?: string };
type RightTab = "task" | "risk" | "score" | "kg" | "upload" | "feedback" | "debug";
type ConvMeta = { conversation_id: string; title: string; created_at: string; message_count: number; last_message: string };

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
  const fileInputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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
      const msgs: ChatMessage[] = (d.messages ?? []).map((m: any) => ({
        role: m.role as "user" | "assistant",
        text: m.content ?? "",
        ts: m.timestamp ? new Date(m.timestamp).toLocaleTimeString() : undefined,
      }));
      setMessages(msgs);
      setLatestResult(null);
    } catch { /* ignore */ }
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if ((!text && !attachedFile) || loading) return;
    setLoading(true);

    const displayText = attachedFile ? `${text ? text + " " : ""}📎 ${attachedFile.name}` : text;
    setMessages((p) => [...p, { role: "user", text: displayText, ts: new Date().toLocaleTimeString() }]);
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
      setMessages((p) => [...p, { role: "assistant", text: reply, ts: new Date().toLocaleTimeString() }]);
      setAttachedFile(null);
      loadConversations();
    } catch (err: any) {
      setMessages((p) => [...p, { role: "assistant", text: `错误：${err?.message ?? "无法连接后端"}` }]);
    }
    setLoading(false);
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

  const rubric = useMemo(() => latestResult?.diagnosis?.rubric ?? [], [latestResult]);
  const triggeredRules = useMemo(() => latestResult?.diagnosis?.triggered_rules ?? [], [latestResult]);
  const nextTask = latestResult?.next_task ?? null;
  const hyperEdges = useMemo(() => latestResult?.hypergraph_insight?.edges ?? [], [latestResult]);
  const kgAnalysis = latestResult?.kg_analysis ?? latestResult?.agent_trace?.kg_analysis ?? null;
  const orchestration = latestResult?.agent_trace?.orchestration ?? {};
  const overallScore = latestResult?.diagnosis?.overall_score ?? null;

  return (
    <div className="chat-app">
      {/* ── Top Bar ── */}
      <header className="chat-topbar">
        <div className="topbar-left">
          <button type="button" className="topbar-btn sidebar-toggle" onClick={() => setConvSidebarOpen((v) => !v)} title="会话列表">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 12h18M3 6h18M3 18h18"/></svg>
          </button>
          <Link href="/" className="topbar-brand">VentureAgent</Link>
          <span className="topbar-sep" />
          <span className="topbar-label">双创智能教练</span>
        </div>
        <div className="topbar-center">
          <select className="topbar-select" value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="coursework">课程辅导</option>
            <option value="competition">竞赛冲刺</option>
          </select>
          {overallScore !== null && <span className="topbar-score">评分 {overallScore}</span>}
        </div>
        <div className="topbar-right">
          <button type="button" className="topbar-btn" onClick={() => setSettingsOpen((v) => !v)}>设置</button>
          <button type="button" className="topbar-btn" onClick={() => setRightOpen((v) => !v)}>
            {rightOpen ? "收起" : "工具"}
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
            <div className="conv-list">
              {conversations.map((c) => (
                <button
                  key={c.conversation_id}
                  className={`conv-item ${c.conversation_id === conversationId ? "active" : ""}`}
                  onClick={() => loadConversation(c.conversation_id)}
                >
                  <span className="conv-title">{c.title || "新对话"}</span>
                  <span className="conv-meta">{c.message_count}条 · {(c.created_at ?? "").slice(5, 16)}</span>
                </button>
              ))}
              {conversations.length === 0 && <p className="conv-empty">暂无历史对话</p>}
            </div>
          </aside>
        )}

        {/* ── Messages ── */}
        <main className="chat-main">
          <div className="chat-scroll">
            {messages.length === 0 && (
              <div className="chat-welcome">
                <h2>你好，我是你的双创教练</h2>
                <p>告诉我你的项目想法、当前困惑，或上传计划书，我会帮你诊断风险并给出下一步行动。</p>
                <div className="chat-hints">
                  {["我想做一个校园二手交易平台，目标用户是大学生", "帮我分析一下我的商业模式有什么问题", "什么是MVP，教我怎么做"].map((h) => (
                    <button key={h} className="hint-chip" onClick={() => { setInput(h); textareaRef.current?.focus(); }}>
                      {h}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m, i) => (
              <div key={i} className={`msg-row ${m.role}`}>
                <div className="msg-avatar">{m.role === "user" ? "你" : "AI"}</div>
                <div className="msg-content">
                  <div className="msg-bubble">
                    {m.role === "assistant" ? (
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
                    ) : (
                      m.text
                    )}
                  </div>
                  {m.ts && <span className="msg-time">{m.ts}</span>}
                </div>
              </div>
            ))}

            {loading && (
              <div className="msg-row assistant">
                <div className="msg-avatar">AI</div>
                <div className="msg-content"><div className="msg-bubble typing">
                  <span className="dot-pulse" />
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

        {/* ── Right Panel ── */}
        {rightOpen && (
          <aside className="chat-right">
            <div className="right-tabs">
              {(["task", "risk", "score", "kg", "upload", "feedback", "debug"] as RightTab[]).map((t) => (
                <button key={t} className={`right-tab ${rightTab === t ? "active" : ""}`} onClick={() => { setRightTab(t); if (t === "feedback") loadFeedback(); }}>
                  {{ task: "任务", risk: "风险", score: "评分", kg: "图谱", upload: "上传", feedback: "批注", debug: "调试" }[t]}
                </button>
              ))}
            </div>

            <div className="right-body">
              {rightTab === "task" && (
                <>
                  {nextTask ? (
                    <div className="right-card">
                      <h4>{nextTask.title}</h4>
                      <p>{nextTask.description}</p>
                      {(nextTask.acceptance_criteria ?? []).length > 0 && (
                        <ul className="right-list">{(nextTask.acceptance_criteria ?? []).map((c: string, i: number) => <li key={i}>{c}</li>)}</ul>
                      )}
                    </div>
                  ) : <p className="right-hint">发送一条消息后显示任务</p>}
                  {hyperEdges.length > 0 && (
                    <div className="right-section">
                      <h4>超图洞察</h4>
                      {hyperEdges.map((e: any) => <div key={e.hyperedge_id} className="right-tag">{e.teaching_note}</div>)}
                    </div>
                  )}
                </>
              )}

              {rightTab === "risk" && (
                triggeredRules.length > 0 ? (
                  <div className="right-section">
                    {triggeredRules.map((r: any) => (
                      <div key={r.id} className={`risk-item ${r.severity}`}>
                        <span className="risk-id">{r.id}</span>
                        <span className="risk-name">{r.name}</span>
                        <span className={`risk-badge ${r.severity}`}>{r.severity}</span>
                      </div>
                    ))}
                  </div>
                ) : <p className="right-hint">暂无风险命中</p>
              )}

              {rightTab === "score" && (
                rubric.length > 0 ? (
                  <div className="right-section">
                    {rubric.map((r: any) => (
                      <div key={r.item} className="score-row">
                        <span className="score-label">{r.item}</span>
                        <div className="score-bar-track">
                          <div className="score-bar-fill" style={{ width: `${Math.min(100, (r.score / 10) * 100)}%` }} />
                        </div>
                        <span className="score-value">{r.score}</span>
                      </div>
                    ))}
                  </div>
                ) : <p className="right-hint">暂无评分</p>
              )}

              {rightTab === "kg" && (
                <div className="right-section">
                  <h4>知识图谱分析</h4>
                  {kgAnalysis ? (
                    <>
                      <div className="kg-score-row">
                        <span>结构完整度</span>
                        <div className="score-bar-track">
                          <div className="score-bar-fill kg-bar" style={{ width: `${Math.min(100, (kgAnalysis.completeness_score ?? 0) * 10)}%` }} />
                        </div>
                        <span className="score-value">{kgAnalysis.completeness_score ?? 0}/10</span>
                      </div>
                      {kgAnalysis.insight && <p className="kg-insight">{kgAnalysis.insight}</p>}

                      {(kgAnalysis.entities ?? []).length > 0 && (
                        <div className="kg-entities">
                          <h5>提取实体 ({kgAnalysis.entities.length})</h5>
                          <div className="kg-entity-grid">
                            {kgAnalysis.entities.map((e: any) => (
                              <span key={e.id} className={`kg-entity-chip ${e.type}`}>{e.label}</span>
                            ))}
                          </div>
                        </div>
                      )}

                      {(kgAnalysis.relationships ?? []).length > 0 && (
                        <div className="kg-relations">
                          <h5>关系 ({kgAnalysis.relationships.length})</h5>
                          {kgAnalysis.relationships.map((r: any, i: number) => (
                            <div key={i} className="kg-rel-row">
                              <span className="kg-rel-src">{r.source}</span>
                              <span className="kg-rel-arrow">→ {r.relation} →</span>
                              <span className="kg-rel-tgt">{r.target}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {(kgAnalysis.structural_gaps ?? []).length > 0 && (
                        <div className="kg-gaps">
                          <h5>结构缺陷</h5>
                          {kgAnalysis.structural_gaps.map((g: string, i: number) => (
                            <div key={i} className="kg-gap-item">⚠ {g}</div>
                          ))}
                        </div>
                      )}
                    </>
                  ) : <p className="right-hint">发送项目描述后显示图谱分析</p>}
                </div>
              )}

              {rightTab === "upload" && (
                <div className="right-section">
                  <p className="right-hint">可在输入栏旁点击 📎 按钮上传文件，文件将在对话中分析。</p>
                  <p className="right-hint">支持 docx / pdf / pptx / txt / md</p>
                </div>
              )}

              {rightTab === "feedback" && (
                <div className="right-section">
                  <h4>教师批注</h4>
                  {teacherFeedback.length > 0 ? teacherFeedback.map((fb, i) => (
                    <div key={i} className="right-card">
                      <p>{fb.comment}</p>
                      <span className="msg-time">{fb.teacher_id} · {(fb.created_at ?? "").slice(0, 16)}</span>
                      {(fb.focus_tags ?? []).length > 0 && (
                        <div className="tch-tag-row">{fb.focus_tags.map((t: string) => <span key={t} className="tch-tag">{t}</span>)}</div>
                      )}
                    </div>
                  )) : <p className="right-hint">暂无教师批注</p>}
                </div>
              )}

              {rightTab === "debug" && (
                <div className="right-section">
                  <div className="debug-row"><span>意图</span><span>{orchestration?.intent ?? "-"}</span></div>
                  <div className="debug-row"><span>置信度</span><span>{orchestration?.confidence ?? "-"}</span></div>
                  <div className="debug-row"><span>管线</span><span>{(orchestration?.pipeline ?? []).join(" → ") || "-"}</span></div>
                  <div className="debug-row"><span>访问节点</span><span>{(orchestration?.nodes_visited ?? []).join(" → ") || "-"}</span></div>
                  <div className="debug-row"><span>策略</span><span>{orchestration?.strategy ?? "-"}</span></div>
                  <div className="debug-row"><span>LLM</span><span>{String(orchestration?.llm_enabled ?? false)}</span></div>
                  <div className="debug-row"><span>会话ID</span><span className="debug-conv-id">{conversationId ?? "无"}</span></div>
                  <details className="debug-json">
                    <summary>原始 JSON</summary>
                    <pre>{JSON.stringify(latestResult, null, 2) ?? "暂无"}</pre>
                  </details>
                </div>
              )}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
