"use client";
import { useState } from "react";
import Link from "next/link";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8787").replace(/\/+$/, "");

export default function ResetPasswordPage() {
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
    <main className="auth-page">
      <div className="auth-bg" aria-hidden="true">
        <span className="auth-orb auth-orb-a" />
        <span className="auth-orb auth-orb-b" />
      </div>

      <div className="auth-card fade-up">
        <Link href="/" className="auth-back-link">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M10 2L4 8l6 6" /></svg>
          返回首页
        </Link>

        <div className="auth-header">
          <span className="auth-brand-dot" />
          <h1>修改密码</h1>
          <p>输入当前密码与新密码完成更改</p>
        </div>

        {success ? (
          <div className="auth-success">
            <p>密码已成功修改</p>
            <Link href="/auth/login" className="auth-submit" style={{ textAlign: "center", display: "block", textDecoration: "none", marginTop: 14 }}>
              去登录
            </Link>
          </div>
        ) : (
          <form className="auth-form" onSubmit={handleSubmit}>
            <label className="auth-label">
              <span>邮箱</span>
              <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="your@email.com" className="auth-input" />
            </label>
            <label className="auth-label">
              <span>当前密码</span>
              <input type="password" required minLength={6} value={currentPwd} onChange={(e) => setCurrentPwd(e.target.value)} placeholder="当前密码" className="auth-input" />
            </label>
            <label className="auth-label">
              <span>新密码</span>
              <input type="password" required minLength={6} value={newPwd} onChange={(e) => setNewPwd(e.target.value)} placeholder="至少 6 位" className="auth-input" />
            </label>
            {error && <div className="auth-error">{error}</div>}
            <button type="submit" className="auth-submit" disabled={loading}>
              {loading ? "提交中..." : "确认修改"}
            </button>
          </form>
        )}

        <div className="auth-footer">
          <Link href="/auth/login">返回登录</Link>
        </div>
      </div>
    </main>
  );
}
