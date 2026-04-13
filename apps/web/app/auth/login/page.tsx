"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8037").trim().replace(/\/+$/, "");
type Mode = "account" | "email_code";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("account");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [codeEmail, setCodeEmail] = useState("");
  const [emailCode, setEmailCode] = useState("");
  const [codeCooldown, setCodeCooldown] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [codeToast, setCodeToast] = useState("");

  useEffect(() => {
    try {
      const raw = localStorage.getItem("va_user");
      if (raw) {
        const u = JSON.parse(raw);
        router.replace(u.role === "teacher" ? "/teacher" : u.role === "admin" ? "/admin" : "/student");
      }
    } catch { /* ignore */ }
  }, [router]);

  useEffect(() => {
    if (codeCooldown <= 0) return;
    const t = setTimeout(() => setCodeCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [codeCooldown]);

  useEffect(() => {
    if (!codeToast) return;
    const t = setTimeout(() => setCodeToast(""), 12000);
    return () => clearTimeout(t);
  }, [codeToast]);

  const sendEmailCode = useCallback(async () => {
    if (!codeEmail.trim() || codeCooldown > 0) return;
    try {
      const res = await fetch(`${API}/api/auth/email-code/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: codeEmail.trim() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail ?? "发送失败");
      setCodeCooldown(60);
      if (data.code_hint) {
        setCodeToast(`开发模式验证码: ${data.code_hint}`);
      } else {
        setCodeToast("验证码已发送到您的邮箱，请查收");
      }
    } catch (err: any) {
      setError(err?.message ?? "发送验证码失败");
    }
  }, [codeEmail, codeCooldown]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (mode === "email_code") {
        if (!emailCode.trim()) throw new Error("请输入验证码");
        const res = await fetch(`${API}/api/auth/email-code/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: codeEmail.trim(), code: emailCode.trim() }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data?.detail ?? "登录失败");
        localStorage.setItem("va_user", JSON.stringify(data.user));
        const role = data.user?.role ?? "student";
        router.push(role === "teacher" ? "/teacher" : role === "admin" ? "/admin" : "/student");
        return;
      }
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
      {/* ── Left: brand visual ── */}
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

      {/* ── Right: login form ── */}
      <section className="auth-form-side">
        {codeToast && (
          <div style={{
            position: "fixed", top: 24, right: 24, zIndex: 9999,
            background: "linear-gradient(135deg, #6b8aff 0%, #8b5cf6 100%)",
            color: "#fff", padding: "12px 20px", borderRadius: 12,
            fontSize: 14, fontWeight: 600, boxShadow: "0 4px 24px rgba(107,138,255,.4)",
            display: "flex", alignItems: "center", gap: 8,
            animation: "fadeIn .3s ease",
          }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="4" width="20" height="16" rx="3"/><path d="M22 7l-10 7L2 7"/></svg>
            {codeToast}
            <button type="button" onClick={() => setCodeToast("")} style={{
              background: "rgba(255,255,255,.2)", border: "none", color: "#fff",
              borderRadius: 6, width: 22, height: 22, cursor: "pointer",
              display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, marginLeft: 4,
            }}>✕</button>
          </div>
        )}
        <div className="auth-form-container fade-up">
          <Link href="/" className="auth-back-link">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M10 2L4 8l6 6" /></svg>
            返回首页
          </Link>

          <div className="auth-header">
            <h1>欢迎回来</h1>
            <p>登录后将根据角色自动进入对应工作台</p>
          </div>

          {/* mode tabs */}
          <div className="auth-mode-tabs">
            <button type="button" className={`auth-mode-tab ${mode === "account" ? "active" : ""}`} onClick={() => setMode("account")}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
              账号密码
            </button>
            <button type="button" className={`auth-mode-tab ${mode === "email_code" ? "active" : ""}`} onClick={() => setMode("email_code")}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="4" width="20" height="16" rx="3"/><path d="M22 7l-10 7L2 7"/></svg>
              邮箱验证码
            </button>
          </div>

          <form className="auth-form" onSubmit={handleSubmit}>
            {mode === "account" ? (
              <>
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
              </>
            ) : (
              <>
                <label className="auth-label">
                  <span>邮箱地址</span>
                  <div className="auth-input-wrap">
                    <svg className="auth-input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="4" width="20" height="16" rx="3"/><path d="M22 7l-10 7L2 7"/></svg>
                    <input type="email" required value={codeEmail} onChange={(e) => setCodeEmail(e.target.value)} placeholder="输入您的邮箱" className="auth-input auth-input-icon-pad" />
                  </div>
                </label>
                <label className="auth-label">
                  <span>验证码</span>
                  <div className="auth-sms-row">
                    <input required value={emailCode} onChange={(e) => setEmailCode(e.target.value)} placeholder="6 位验证码" className="auth-input" maxLength={6} />
                    <button type="button" className="auth-sms-btn" onClick={sendEmailCode} disabled={codeCooldown > 0 || !codeEmail.trim()}>
                      {codeCooldown > 0 ? `${codeCooldown}s` : "获取验证码"}
                    </button>
                  </div>
                </label>
              </>
            )}

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
