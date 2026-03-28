"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8787").trim().replace(/\/+$/, "");

export default function ResetPasswordPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [currentPwd, setCurrentPwd] = useState("");
  const [newPwd, setNewPwd] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSuccess(false);
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/auth/change-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), current_password: currentPwd, new_password: newPwd }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail ?? "修改失败");
      setSuccess(true);
    } catch (err: any) {
      setError(err?.message ?? "修改失败");
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
          <h2>安全设置</h2>
          <p>修改密码后请使用新密码重新登录。</p>
        </div>
      </aside>

      <section className="auth-form-side">
        <div className="auth-form-container fade-up">
          <Link href="/" className="auth-back-link">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M10 2L4 8l6 6" /></svg>
            返回首页
          </Link>

          <div className="auth-header">
            <h1>修改密码</h1>
            <p>输入当前密码与新密码完成更改</p>
          </div>

          {success ? (
            <div className="auth-success-card fade-up">
              <div className="auth-success-icon">
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#5cbd8a" strokeWidth="2.5"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
              </div>
              <h3>密码已成功修改</h3>
              <p>请使用新密码重新登录</p>
              <Link href="/auth/login" className="auth-submit" style={{ textAlign: "center", display: "block", textDecoration: "none", marginTop: 14 }}>
                去登录
              </Link>
            </div>
          ) : (
            <form className="auth-form" onSubmit={handleSubmit}>
              <label className="auth-label">
                <span>账号 / 手机号</span>
                <div className="auth-input-wrap">
                  <svg className="auth-input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="4" width="20" height="16" rx="3"/><path d="M22 7l-10 7L2 7"/></svg>
                  <input type="text" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="输入注册时使用的账号" className="auth-input auth-input-icon-pad" />
                </div>
              </label>
              <label className="auth-label">
                <span>当前密码</span>
                <div className="auth-input-wrap">
                  <svg className="auth-input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="3"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>
                  <input type="password" required minLength={6} value={currentPwd} onChange={(e) => setCurrentPwd(e.target.value)} placeholder="当前密码" className="auth-input auth-input-icon-pad" />
                </div>
              </label>
              <label className="auth-label">
                <span>新密码</span>
                <div className="auth-input-wrap">
                  <svg className="auth-input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="3"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>
                  <input type="password" required minLength={6} value={newPwd} onChange={(e) => setNewPwd(e.target.value)} placeholder="至少 6 位" className="auth-input auth-input-icon-pad" />
                </div>
              </label>
              {error && <div className="auth-error">{error}</div>}
              <button type="submit" className="auth-submit" disabled={loading}>
                {loading && <span className="auth-spinner" />}
                {loading ? "提交中..." : "确认修改"}
              </button>
            </form>
          )}

          <div className="auth-divider"><span>或</span></div>

          <div className="auth-footer-links">
            <Link href="/auth/login" className="auth-alt-link">返回登录</Link>
          </div>
        </div>
      </section>
    </main>
  );
}
