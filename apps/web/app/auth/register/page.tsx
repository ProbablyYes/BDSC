"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8037").trim().replace(/\/+$/, "");
type Role = "student" | "teacher" | "admin";

const roleMeta: Record<Role, { label: string; icon: string; color: string }> = {
  student: { label: "学生", icon: "◉", color: "#6b8aff" },
  teacher: { label: "教师", icon: "△", color: "#73ccff" },
  admin:   { label: "管理员", icon: "□", color: "#e8a84c" },
};

export default function RegisterPage() {
  const router = useRouter();
  const [role, setRole] = useState<Role>("student");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    try { if (localStorage.getItem("va_user")) router.replace("/student"); } catch { /* */ }
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (password !== confirmPassword) {
      setError("两次输入的密码不一致");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role, display_name: displayName.trim(), email: email.trim(), password }),
      });
      const data = await res.json();
      if (!res.ok) {
        let duplicate = false;
        if (typeof data?.detail === "string") {
          if (data.detail.includes("该账号名已存在")) {
            setError("该账号名已存在");
            duplicate = true;
          } else if (data.detail.includes("用户名已存在")) {
            setError("用户名已存在");
            duplicate = true;
          } else {
            setError(data?.detail ?? "注册失败");
          }
        } else {
          setError("注册失败");
        }
        setLoading(false);
        if (duplicate) {
          setTimeout(() => {
            window.location.reload();
          }, 1200);
        }
        return;
      }
      localStorage.setItem("va_user", JSON.stringify(data.user));
      router.push(role === "teacher" ? "/teacher" : role === "admin" ? "/admin" : "/student");
    } catch (err: any) {
      setError(err?.message ?? "注册失败");
      setLoading(false);
    }
    setLoading(false);
  }

  return (
    <main className="auth-split-page">
      {/* ── Left visual ── */}
      <aside className="auth-visual">
        <div className="auth-visual-bg" aria-hidden="true">
          <span className="auth-visual-orb auth-visual-orb-a" />
          <span className="auth-visual-orb auth-visual-orb-b" />
          <span className="auth-visual-grid" />
        </div>
        <div className="auth-visual-content">
          <div className="auth-visual-logo">
            <span className="auth-visual-logo-mark" />
            <span>VentureCheck</span>
          </div>
          <h2>开始你的旅程</h2>
          <p>注册后自动按角色进入对应工作空间，班级、学号等信息可以登录后在个人中心补充。</p>
          <div className="auth-visual-steps">
            <div className="auth-visual-step"><span className="auth-step-num">1</span><span>选择角色并填写基本信息</span></div>
            <div className="auth-visual-step"><span className="auth-step-num">2</span><span>自动进入对应工作台</span></div>
            <div className="auth-visual-step"><span className="auth-step-num">3</span><span>在个人中心完善学号与班级</span></div>
          </div>
        </div>
      </aside>

      {/* ── Right form ── */}
      <section className="auth-form-side">
        <div className="auth-form-container fade-up">
          <Link href="/" className="auth-back-link">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M10 2L4 8l6 6" /></svg>
            返回首页
          </Link>

          <div className="auth-header">
            <h1>创建账号</h1>
            <p>选择你的角色，填写昵称、账号与密码即可</p>
          </div>

          <form className="auth-form" onSubmit={handleSubmit}>
            {/* role selector */}
            <div className="auth-role-cards">
              {(Object.keys(roleMeta) as Role[]).map((r) => (
                <button key={r} type="button" className={`auth-role-card ${role === r ? "active" : ""}`} onClick={() => setRole(r)} style={role === r ? { borderColor: roleMeta[r].color, boxShadow: `0 0 24px ${roleMeta[r].color}22` } : undefined}>
                  <span className="auth-role-card-icon" style={{ color: roleMeta[r].color }}>{roleMeta[r].icon}</span>
                  <span className="auth-role-card-label">{roleMeta[r].label}</span>
                  {role === r && <span className="auth-role-check">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><path d="M20 6L9 17l-5-5" /></svg>
                  </span>}
                </button>
              ))}
            </div>

            <label className="auth-label">
              <span>昵称</span>
              <div className="auth-input-wrap">
                <svg className="auth-input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                <input required minLength={2} value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="你的名字" className="auth-input auth-input-icon-pad" />
              </div>
            </label>

            <label className="auth-label">
              <span>账号 / 手机号</span>
              <div className="auth-input-wrap">
                <svg className="auth-input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="4" width="20" height="16" rx="3"/><path d="M22 7l-10 7L2 7"/></svg>
                <input type="text" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="可输入邮箱、手机号或任意测试账号" className="auth-input auth-input-icon-pad" autoComplete="username" />
              </div>
            </label>

            <label className="auth-label">
              <span>密码</span>
              <div className="auth-input-wrap">
                <svg className="auth-input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="3"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>
                <input type={showPwd ? "text" : "password"} required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="至少 6 位" className="auth-input auth-input-icon-pad" autoComplete="new-password" />
                <button type="button" className="auth-pwd-toggle" onClick={() => setShowPwd((v) => !v)} tabIndex={-1}>
                  {showPwd ? (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
                  ) : (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                  )}
                </button>
              </div>
            </label>

            <label className="auth-label">
              <span>确认密码</span>
              <div className="auth-input-wrap">
                <svg className="auth-input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="3"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>
                <input type={showPwd ? "text" : "password"} required minLength={6} value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} placeholder="再次输入密码" className="auth-input auth-input-icon-pad" autoComplete="new-password" />
              </div>
            </label>

            {error && <div className="auth-error">{error}</div>}

            <button type="submit" className="auth-submit" disabled={loading}>
              {loading && <span className="auth-spinner" />}
              {loading ? "注册中..." : "创建账号"}
            </button>
          </form>

          <div className="auth-divider"><span>或</span></div>

          <div className="auth-footer-links">
            <Link href="/auth/login" className="auth-alt-link">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
              已有账号？去登录
            </Link>
          </div>
        </div>
      </section>
    </main>
  );
}
