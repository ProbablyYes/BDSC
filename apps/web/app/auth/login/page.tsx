"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8037").trim().replace(/\/+$/, "");

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showPwd, setShowPwd] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem("va_user");
      if (raw) {
        const u = JSON.parse(raw);
        router.replace(u.role === "teacher" ? "/teacher" : u.role === "admin" ? "/admin" : "/student");
      }
    } catch { /* ignore */ }
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), password }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail ?? "登录失败");
      localStorage.setItem("va_user", JSON.stringify(data.user));
      const role = data.user?.role ?? "student";
      router.push(role === "teacher" ? "/teacher" : role === "admin" ? "/admin" : "/student");
    } catch (err: any) {
      setError(err?.message ?? "登录失败");
    }
    setLoading(false);
  }

  return (
    <main className="auth-split-page">
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
          <h2>创新创业智能体平台</h2>
          <p>面向学生、教师与管理员的三端协同空间。登录后即可进入你的专属工作台。</p>
          <div className="auth-visual-features">
            <div className="auth-visual-feat">
              <span className="auth-feat-icon">◉</span>
              <div><strong>学生端</strong><span>项目迭代、智能问答、成长反馈</span></div>
            </div>
            <div className="auth-visual-feat">
              <span className="auth-feat-icon">△</span>
              <div><strong>教师端</strong><span>团队洞察、过程追踪、教学干预</span></div>
            </div>
            <div className="auth-visual-feat">
              <span className="auth-feat-icon">□</span>
              <div><strong>管理员端</strong><span>权限治理、运行监控、安全审计</span></div>
            </div>
          </div>
        </div>
      </aside>

      <section className="auth-form-side">
        <div className="auth-form-container fade-up">
          <Link href="/" className="auth-back-link">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M10 2L4 8l6 6" /></svg>
            返回首页
          </Link>

          <div className="auth-header">
            <h1>欢迎回来</h1>
            <p>登录后将根据角色自动进入对应工作台</p>
          </div>

          <form className="auth-form" onSubmit={handleSubmit}>
            <label className="auth-label">
              <span>账号 / 邮箱</span>
              <div className="auth-input-wrap">
                <svg className="auth-input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                <input type="text" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="输入邮箱或测试账号" className="auth-input auth-input-icon-pad" autoComplete="username" />
              </div>
            </label>
            <label className="auth-label">
              <span>密码</span>
              <div className="auth-input-wrap">
                <svg className="auth-input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="3"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>
                <input type={showPwd ? "text" : "password"} required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="至少 6 位" className="auth-input auth-input-icon-pad" autoComplete="current-password" />
                <button type="button" className="auth-pwd-toggle" onClick={() => setShowPwd((v) => !v)} tabIndex={-1}>
                  {showPwd ? (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
                  ) : (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                  )}
                </button>
              </div>
            </label>

            {error && <div className="auth-error">{error}</div>}

            <button type="submit" className="auth-submit" disabled={loading}>
              {loading && <span className="auth-spinner" />}
              {loading ? "登录中..." : "登录"}
            </button>
          </form>

          <div className="auth-divider"><span>或</span></div>

          <div className="auth-footer-links">
            <Link href="/auth/register" className="auth-alt-link">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M16 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="17" y1="11" x2="23" y2="11"/></svg>
              创建新账号
            </Link>
            <Link href="/auth/reset-password" className="auth-alt-link">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="3"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>
              修改密码
            </Link>
          </div>
        </div>
      </section>
    </main>
  );
}