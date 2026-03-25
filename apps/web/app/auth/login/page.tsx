"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8787").replace(/\/+$/, "");

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

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
      // persist user info to localStorage (simple, no jwt for now)
      localStorage.setItem("va_user", JSON.stringify(data.user));
      const role = data.user?.role ?? "student";
      router.push(role === "teacher" ? "/teacher" : role === "admin" ? "/admin" : "/student");
    } catch (err: any) {
      setError(err?.message ?? "登录失败");
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
          <h1>登录</h1>
          <p>使用邮箱与密码进入平台</p>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label className="auth-label">
            <span>邮箱</span>
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="your@email.com" className="auth-input" />
          </label>
          <label className="auth-label">
            <span>密码</span>
            <input type="password" required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="至少 6 位" className="auth-input" />
          </label>
          {error && <div className="auth-error">{error}</div>}
          <button type="submit" className="auth-submit" disabled={loading}>
            {loading ? "登录中..." : "登录"}
          </button>
        </form>

        <div className="auth-footer">
          <span>还没有账号？</span>
          <Link href="/auth/register">立即注册</Link>
          <span className="auth-footer-sep" />
          <Link href="/auth/reset-password">修改密码</Link>
        </div>
      </div>
    </main>
  );
}
