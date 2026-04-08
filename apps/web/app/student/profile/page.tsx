"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8037").trim().replace(/\/+$/, "");

function parseServerTime(value?: string) {
  if (!value) return null;
  const normalized = /Z$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`;
  const d = new Date(normalized);
  return Number.isNaN(d.getTime()) ? null : d;
}

function formatBjTime(value?: string) {
  const d = parseServerTime(value);
  if (!d) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

function formatBjDate(value?: string) {
  const d = parseServerTime(value);
  if (!d) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

function ScoreRing({ score, max = 10, size = 72, label }: { score: number; max?: number; size?: number; label: string }) {
  const r = (size - 10) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.min(score / max, 1);
  const offset = c * (1 - pct);
  const color = score >= 7 ? "#22c55e" : score >= 4 ? "#f59e0b" : "#ef4444";
  return (
    <div className="prof-ring-wrap">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--border)" strokeWidth="5" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth="5"
          strokeDasharray={c} strokeDashoffset={offset} strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: "stroke-dashoffset 0.6s ease" }} />
        <text x={size / 2} y={size / 2 - 4} textAnchor="middle" fontSize="18" fontWeight="700" fill={color}>{score}</text>
        <text x={size / 2} y={size / 2 + 12} textAnchor="middle" fontSize="8" fill="var(--text-muted)">/{max}</text>
      </svg>
      <span className="prof-ring-label">{label}</span>
    </div>
  );
}

export default function StudentProfilePage() {
  const [user, setUser] = useState<any>(null);
  const [submissions, setSubmissions] = useState<any[]>([]);
  const [conversations, setConversations] = useState<any[]>([]);
  const [interventions, setInterventions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    try {
      const raw = localStorage.getItem("va_user");
      if (raw) setUser(JSON.parse(raw));
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (!user) { setLoading(false); return; }
    const pid = `project-${user.user_id}`;
    Promise.all([
      fetch(`${API}/api/project/${encodeURIComponent(pid)}/submissions`).then((r) => r.json()).catch(() => ({ submissions: [] })),
      fetch(`${API}/api/conversations?project_id=${encodeURIComponent(pid)}`).then((r) => r.json()).catch(() => ({ conversations: [] })),
      fetch(`${API}/api/student/interventions?project_id=${encodeURIComponent(pid)}`).then((r) => r.json()).catch(() => ({ interventions: [] })),
    ]).then(([subData, convData, interventionData]) => {
      setSubmissions(subData.submissions ?? []);
      setConversations(convData.conversations ?? []);
      setInterventions(interventionData.interventions ?? []);
      setLoading(false);
    });
  }, [user]);

  const stats = useMemo(() => {
    if (!submissions.length) return { total: 0, avg: 0, recent: [], bestScore: 0, riskCount: 0, scoreHistory: [] };
    const scores = submissions.map((s) => s.overall_score ?? 0).filter((s) => s > 0);
    const avg = scores.length ? Math.round((scores.reduce((a: number, b: number) => a + b, 0) / scores.length) * 10) / 10 : 0;
    const best = scores.length ? Math.max(...scores) : 0;
    const riskCount = submissions.reduce((a: number, s: any) => a + ((s.triggered_rules ?? []).length), 0);
    const recent = submissions.slice(0, 8);
    const scoreHistory = submissions.slice(0, 12).reverse().map((s, i) => ({ idx: i, score: s.overall_score ?? 0, date: formatBjTime(s.created_at) }));
    return { total: submissions.length, avg, recent, bestScore: best, riskCount, scoreHistory };
  }, [submissions]);

  const totalMsgs = useMemo(() => conversations.reduce((a: number, c: any) => a + (c.message_count ?? 0), 0), [conversations]);

  if (!user) {
    return (
      <main className="profile-page">
        <div className="profile-empty">
          <div className="prof-empty-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="1.2"><circle cx="12" cy="8" r="4"/><path d="M20 21c0-4.418-3.582-8-8-8s-8 3.582-8 8"/></svg>
          </div>
          <h2>尚未登录</h2>
          <p>请先登录后查看个人中心</p>
          <Link href="/auth/login" className="prof-login-btn">前往登录</Link>
        </div>
      </main>
    );
  }

  return (
    <main className="profile-page">
      <header className="profile-topbar">
        <Link href="/student" className="profile-back">
          <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M10 2L4 8l6 6" /></svg>
          返回工作台
        </Link>
        <h1>个人中心</h1>
        <Link href="/auth/reset-password" className="profile-setting-link">修改密码</Link>
      </header>

      {/* Hero Section */}
      <div className="profile-hero fade-up">
        <div className="prof-hero-left">
          <div className="profile-avatar">
            <span>{(user.display_name ?? "S")[0].toUpperCase()}</span>
          </div>
          <div className="profile-info">
            <div className="prof-name-row">
              <h2>{user.display_name}</h2>
              <span className="profile-role-badge">{user.role === "student" ? "学生" : user.role === "teacher" ? "教师" : "管理员"}</span>
            </div>
            <p className="profile-meta">
              {user.email}
              {user.student_id ? ` · ${user.student_id}` : ""}
              {user.class_id ? ` · ${user.class_id}班` : ""}
              {user.cohort_id ? ` · ${user.cohort_id}` : ""}
            </p>
            {user.bio && <p className="profile-bio">{user.bio}</p>}
            <p className="prof-join-date">注册于 {formatBjDate(user.created_at)}</p>
          </div>
        </div>
        {stats.total > 0 && (
          <div className="prof-hero-rings">
            <ScoreRing score={stats.avg} label="平均分" />
            <ScoreRing score={stats.bestScore} label="最高分" />
          </div>
        )}
      </div>

      {loading ? (
        <div className="profile-loading">
          <div className="prof-loading-spinner" />
          <span>加载数据中...</span>
        </div>
      ) : (
        <>
          {/* KPI Grid */}
          <section className="profile-kpi-grid fade-up">
            {[
              { val: stats.total, label: "提交总数", icon: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z", color: "#6366f1" },
              { val: conversations.length, label: "对话总数", icon: "M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z", color: "#8b5cf6" },
              { val: totalMsgs, label: "消息总数", icon: "M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z", color: "#06b6d4" },
              { val: stats.riskCount, label: "累计风险", icon: "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z", color: "#f59e0b" },
              { val: interventions.length, label: "教师任务", icon: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2", color: "#ec4899" },
            ].map(({ val, label, icon, color }) => (
              <div key={label} className="profile-kpi">
                <div className="prof-kpi-icon" style={{ color }}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d={icon}/></svg>
                </div>
                <strong>{val}</strong>
                <span>{label}</span>
              </div>
            ))}
          </section>

          {/* Score Trend (mini sparkline) */}
          {stats.scoreHistory.length >= 2 && (
            <section className="profile-section prof-trend-section fade-up">
              <h3>分数趋势</h3>
              <div className="prof-sparkline-wrap">
                <svg viewBox={`0 0 ${Math.max(stats.scoreHistory.length * 40, 200)} 80`} className="prof-sparkline">
                  <defs>
                    <linearGradient id="sparkG" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#6366f1" stopOpacity="0.3" />
                      <stop offset="100%" stopColor="#6366f1" stopOpacity="0" />
                    </linearGradient>
                  </defs>
                  {(() => {
                    const pts = stats.scoreHistory;
                    const w = Math.max(pts.length * 40, 200);
                    const maxY = 10;
                    const px = (i: number) => (i / Math.max(pts.length - 1, 1)) * (w - 20) + 10;
                    const py = (v: number) => 70 - (v / maxY) * 60;
                    const line = pts.map((p, i) => `${i === 0 ? "M" : "L"}${px(i)},${py(p.score)}`).join(" ");
                    const area = line + ` L${px(pts.length - 1)},70 L${px(0)},70 Z`;
                    return (
                      <>
                        <path d={area} fill="url(#sparkG)" />
                        <path d={line} fill="none" stroke="#6366f1" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                        {pts.map((p, i) => (
                          <g key={i}>
                            <circle cx={px(i)} cy={py(p.score)} r="3.5" fill="#6366f1" stroke="var(--bg-primary)" strokeWidth="2" />
                            <text x={px(i)} y={py(p.score) - 8} textAnchor="middle" fontSize="9" fill="var(--text-muted)">{p.score}</text>
                          </g>
                        ))}
                      </>
                    );
                  })()}
                </svg>
              </div>
            </section>
          )}

          {/* Recent Submissions */}
          {stats.recent.length > 0 && (
            <section className="profile-section fade-up">
              <h3>近期提交</h3>
              <div className="profile-sub-list">
                {stats.recent.map((s: any, i: number) => {
                  const sc = s.overall_score ?? 0;
                  const clr = sc >= 7 ? "#22c55e" : sc >= 4 ? "#f59e0b" : sc > 0 ? "#ef4444" : "var(--text-muted)";
                  return (
                    <div key={i} className="profile-sub-item">
                      <div className="profile-sub-left">
                        <span className={`profile-sub-type ${s.source_type === "file" ? "file" : "text"}`}>{s.source_type === "file" ? "文件" : "文本"}</span>
                        <span className="profile-sub-preview">{s.text_preview || s.filename || "-"}</span>
                      </div>
                      <div className="profile-sub-right">
                        <span className="profile-sub-score" style={{ color: clr }}>{sc > 0 ? sc : "-"}<small>/10</small></span>
                        <span className="profile-sub-date">{formatBjTime(s.created_at)}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* Interventions */}
          <section className="profile-section fade-up">
            <h3>教师任务</h3>
            {interventions.length > 0 ? (
              <div className="profile-sub-list">
                {interventions.slice(0, 8).map((item: any, i: number) => {
                  const statusMap: Record<string, [string, string]> = {
                    pending: ["待处理", "#f59e0b"],
                    acknowledged: ["已确认", "#06b6d4"],
                    completed: ["已完成", "#22c55e"],
                  };
                  const [statusLabel, statusColor] = statusMap[item.status] ?? [item.status || "-", "var(--text-muted)"];
                  return (
                    <div key={item.intervention_id || i} className="profile-sub-item">
                      <div className="profile-sub-left">
                        <span className="profile-sub-type intervention">{item.scope_type === "project" ? "项目" : item.scope_type === "team" ? "团队" : "个人"}</span>
                        <span className="profile-sub-preview">{item.title || item.reason_summary}</span>
                      </div>
                      <div className="profile-sub-right">
                        <span className="prof-status-badge" style={{ color: statusColor, borderColor: statusColor }}>{statusLabel}</span>
                        <span className="profile-sub-date">{formatBjTime(item.sent_at || item.created_at)}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : <p className="profile-empty-hint">暂无教师下发的任务</p>}
          </section>

          {/* Conversations */}
          <section className="profile-section fade-up">
            <h3>我的对话</h3>
            {conversations.length > 0 ? (
              <div className="profile-conv-list">
                {conversations.slice(0, 12).map((c: any) => (
                  <Link key={c.conversation_id} href="/student" className="profile-conv-item">
                    <div className="prof-conv-icon">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
                    </div>
                    <div className="prof-conv-content">
                      <span className="profile-conv-title">{c.title || "新对话"}</span>
                      <span className="profile-conv-meta">{c.message_count ?? 0} 条消息 · {formatBjTime(c.created_at)}</span>
                    </div>
                  </Link>
                ))}
              </div>
            ) : <p className="profile-empty-hint">暂无对话记录，去工作台开始你的第一次对话吧</p>}
          </section>

          {/* Account Info */}
          <section className="profile-section fade-up">
            <h3>账号信息</h3>
            <div className="profile-info-grid">
              {[
                { label: "邮箱", value: user.email },
                { label: "角色", value: user.role === "student" ? "学生" : user.role === "teacher" ? "教师" : "管理员" },
                ...(user.student_id ? [{ label: "学号", value: user.student_id }] : []),
                ...(user.class_id ? [{ label: "班级", value: user.class_id }] : []),
                ...(user.cohort_id ? [{ label: "学期", value: user.cohort_id }] : []),
                { label: "注册时间", value: formatBjDate(user.created_at) },
              ].map(({ label, value }) => (
                <div key={label}>
                  <span>{label}</span>
                  <strong>{value}</strong>
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </main>
  );
}
