"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8787").trim().replace(/\/+$/, "");

type ChatMessage = { role: "user" | "assistant"; text: string; ts?: string };
type RightTab = "task" | "risk" | "score" | "upload" | "debug";

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
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  function autoResize() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    setLoading(true);
    setMessages((p) => [...p, { role: "user", text, ts: new Date().toLocaleTimeString() }]);
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";

    try {
      const resp = await fetch(`${API_BASE}/api/dialogue/turn`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          student_id: studentId,
          class_id: classId || undefined,
          cohort_id: cohortId || undefined,
          message: text,
          mode,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        setMessages((p) => [...p, { role: "assistant", text: `请求出错：${data?.detail ?? resp.statusText}` }]);
      } else {
        setLatestResult(data);
        const reply = (data?.assistant_message ?? "").trim() || "（智能体未返回有效回复，请查看调试面板）";
        setMessages((p) => [...p, { role: "assistant", text: reply, ts: new Date().toLocaleTimeString() }]);
      }
    } catch (err: any) {
      setMessages((p) => [...p, { role: "assistant", text: `网络错误：${err?.message ?? "无法连接后端"}` }]);
    }
    setLoading(false);
  }

  async function uploadFile(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    const form = new FormData(e.currentTarget);
    form.set("project_id", projectId);
    form.set("student_id", studentId);
    form.set("class_id", classId);
    form.set("cohort_id", cohortId);
    form.set("mode", mode);
    try {
      const resp = await fetch(`${API_BASE}/api/upload`, { method: "POST", body: form });
      const data = await resp.json();
      setLatestResult(data);
      setMessages((p) => [
        ...p,
        { role: "user", text: `[上传文件] ${data?.filename ?? "未知文件"}` },
        { role: "assistant", text: `文件已解析（${data?.extracted_length ?? 0}字）。\n当前瓶颈：${data?.diagnosis?.bottleneck ?? "暂无"}\n下一步：${data?.next_task?.title ?? "暂无"}` },
      ]);
    } catch (err: any) {
      setMessages((p) => [...p, { role: "assistant", text: `上传失败：${err?.message}` }]);
    }
    setLoading(false);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(e as any);
    }
  }

  const rubric = useMemo(() => latestResult?.diagnosis?.rubric ?? [], [latestResult]);
  const triggeredRules = useMemo(() => latestResult?.diagnosis?.triggered_rules ?? [], [latestResult]);
  const nextTask = latestResult?.next_task ?? null;
  const hyperEdges = useMemo(() => latestResult?.hypergraph_insight?.edges ?? [], [latestResult]);
  const orchestration = latestResult?.agent_trace?.orchestration ?? {};
  const overallScore = latestResult?.agent_trace?.grader?.overall_score ?? latestResult?.diagnosis?.overall_score ?? null;

  return (
    <div className="chat-app">
      {/* ── Top Bar ── */}
      <header className="chat-topbar">
        <div className="topbar-left">
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
          <button type="button" className="topbar-btn" onClick={() => { setRightOpen((v) => !v); }} title="工具面板">
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
        {/* ── Messages ── */}
        <main className="chat-main">
          <div className="chat-scroll">
            {messages.length === 0 && (
              <div className="chat-welcome">
                <h2>你好，我是你的双创教练</h2>
                <p>告诉我你的项目想法、当前困惑，或上传计划书，我会帮你诊断风险并给出下一步行动。</p>
                <div className="chat-hints">
                  {["我想做一个校园二手交易平台，目标用户是大学生", "帮我分析一下我的商业模式有什么问题", "我做了5份用户访谈，下一步该怎么做"].map((h) => (
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
                  <div className="msg-bubble">{m.text}</div>
                  {m.ts && <span className="msg-time">{m.ts}</span>}
                </div>
              </div>
            ))}

            {loading && (
              <div className="msg-row assistant">
                <div className="msg-avatar">AI</div>
                <div className="msg-content"><div className="msg-bubble typing">思考中...</div></div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* ── Input Bar ── */}
          <form className="chat-inputbar" onSubmit={send}>
            <textarea
              ref={textareaRef}
              className="chat-textarea"
              value={input}
              onChange={(e) => { setInput(e.target.value); autoResize(); }}
              onKeyDown={handleKeyDown}
              placeholder="描述你的项目想法、困惑或问题…  (Shift+Enter 换行)"
              rows={1}
            />
            <button type="submit" className="send-btn" disabled={loading || !input.trim()}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 2L11 13"/><path d="M22 2L15 22L11 13L2 9L22 2Z"/></svg>
            </button>
          </form>
        </main>

        {/* ── Right Panel ── */}
        {rightOpen && (
          <aside className="chat-right">
            <div className="right-tabs">
              {(["task", "risk", "score", "upload", "debug"] as RightTab[]).map((t) => (
                <button key={t} className={`right-tab ${rightTab === t ? "active" : ""}`} onClick={() => setRightTab(t)}>
                  {{ task: "任务", risk: "风险", score: "评分", upload: "上传", debug: "调试" }[t]}
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

              {rightTab === "upload" && (
                <form className="upload-form" onSubmit={uploadFile}>
                  <p className="right-hint">支持 docx / pdf / pptx / txt / md</p>
                  <input type="file" name="file" required />
                  <button type="submit" className="upload-btn" disabled={loading}>{loading ? "分析中..." : "上传并分析"}</button>
                </form>
              )}

              {rightTab === "debug" && (
                <div className="right-section">
                  <div className="debug-row"><span>LLM</span><span>{String(orchestration?.llm_enabled ?? false)}</span></div>
                  <div className="debug-row"><span>调用链</span><span>{(orchestration?.called_agents ?? []).join(" → ") || "-"}</span></div>
                  <div className="debug-row"><span>跳过</span><span>{(orchestration?.skipped_agents ?? []).join(", ") || "-"}</span></div>
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
