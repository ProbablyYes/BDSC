"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8787").replace(/\/+$/, "");

export default function StudentProfilePage() {
  const [user, setUser] = useState<any>(null);
  const [submissions, setSubmissions] = useState<any[]>([]);
  const [conversations, setConversations] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    try {
      const raw = localStorage.getItem("va_user");
      if (raw) setUser(JSON.parse(raw));
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (!user) { setLoading(false); return; }
    const pid = `demo-project-001`;
    Promise.all([
      fetch(`${API}/api/teacher/submissions?limit=200`).then((r) => r.json()).catch(() => ({ submissions: [] })),
      fetch(`${API}/api/conversations?project_id=${encodeURIComponent(pid)}`).then((r) => r.json()).catch(() => ({ conversations: [] })),
    ]).then(([subData, convData]) => {
      const sid = user.student_id || user.email;
      const mySubs = (subData.submissions ?? []).filter((s: any) => s.student_id === sid);
      setSubmissions(mySubs);
      setConversations(convData.conversations ?? []);
      setLoading(false);
    });
  }, [user]);

  const stats = useMemo(() => {
    if (!submissions.length) return { total: 0, avg: 0, recent: [], bestScore: 0, riskCount: 0 };
    const scores = submissions.map((s) => s.overall_score ?? 0).filter((s) => s > 0);
    const avg = scores.length ? Math.round((scores.reduce((a: number, b: number) => a + b, 0) / scores.length) * 10) / 10 : 0;
    const best = scores.length ? Math.max(...scores) : 0;
    const riskCount = submissions.reduce((a: number, s: any) => a + ((s.triggered_rules ?? []).length), 0);
    const recent = submissions.slice(0, 6);
    return { total: submissions.length, avg, recent, bestScore: best, riskCount };
  }, [submissions]);

  if (!user) {
    return (
      <main className="profile-page">
        <div className="profile-empty">
          <h2>未登录</h2>
          <p>请先 <Link href="/auth/login">登录</Link> 后查看个人中心。</p>
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

      <div className="profile-hero fade-up">
        <div className="profile-avatar">{(user.display_name ?? "S")[0].toUpperCase()}</div>
        <div className="profile-info">
          <h2>{user.display_name}</h2>
          <span className="profile-role-badge">{user.role === "student" ? "学生" : user.role === "teacher" ? "教师" : "管理员"}</span>
          <p className="profile-meta">{user.email}{user.student_id ? ` / ${user.student_id}` : ""}{user.class_id ? ` / ${user.class_id}` : ""}</p>
          {user.bio && <p className="profile-bio">{user.bio}</p>}
        </div>
      </div>

      {loading ? (
        <div className="profile-loading">加载中...</div>
      ) : (
        <>
          <section className="profile-kpi-grid fade-up">
            <div className="profile-kpi">
              <strong>{stats.total}</strong>
              <span>提交总数</span>
            </div>
            <div className="profile-kpi">
              <strong>{stats.avg}</strong>
              <span>平均分</span>
            </div>
            <div className="profile-kpi">
              <strong>{stats.bestScore}</strong>
              <span>历史最高分</span>
            </div>
            <div className="profile-kpi">
              <strong>{stats.riskCount}</strong>
              <span>累计风险数</span>
            </div>
            <div className="profile-kpi">
              <strong>{conversations.length}</strong>
              <span>对话总数</span>
            </div>
          </section>

          {stats.recent.length > 0 && (
            <section className="profile-section fade-up">
              <h3>近期提交</h3>
              <div className="profile-sub-list">
                {stats.recent.map((s: any, i: number) => (
                  <div key={i} className="profile-sub-item">
                    <div className="profile-sub-left">
                      <span className="profile-sub-type">{s.source_type === "file" ? "文件" : "文本"}</span>
                      <span className="profile-sub-preview">{s.text_preview || s.filename || "-"}</span>
                    </div>
                    <div className="profile-sub-right">
                      <span className="profile-sub-score">{s.overall_score ?? "-"}<small>/10</small></span>
                      <span className="profile-sub-date">{(s.created_at ?? "").slice(0, 16)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="profile-section fade-up">
            <h3>我的对话</h3>
            {conversations.length > 0 ? (
              <div className="profile-conv-list">
                {conversations.slice(0, 8).map((c: any) => (
                  <Link key={c.conversation_id} href="/student" className="profile-conv-item">
                    <span className="profile-conv-title">{c.title || "新对话"}</span>
                    <span className="profile-conv-meta">{c.message_count}条 / {(c.created_at ?? "").slice(5, 16)}</span>
                  </Link>
                ))}
              </div>
            ) : <p className="profile-empty-hint">暂无对话记录</p>}
          </section>

          <section className="profile-section fade-up">
            <h3>账号信息</h3>
            <div className="profile-info-grid">
              <div><span>邮箱</span><strong>{user.email}</strong></div>
              <div><span>角色</span><strong>{user.role}</strong></div>
              {user.student_id && <div><span>学号</span><strong>{user.student_id}</strong></div>}
              {user.class_id && <div><span>班级</span><strong>{user.class_id}</strong></div>}
              {user.cohort_id && <div><span>学期</span><strong>{user.cohort_id}</strong></div>}
              <div><span>注册时间</span><strong>{(user.created_at ?? "").slice(0, 16)}</strong></div>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
