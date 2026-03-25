"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8787").replace(/\/+$/, "");

type Role = "student" | "teacher" | "admin";

export default function RegisterPage() {
  const router = useRouter();
  const [role, setRole] = useState<Role>("student");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [studentId, setStudentId] = useState("");
  const [classId, setClassId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          role, display_name: displayName.trim(), email: email.trim(), password,
          student_id: studentId.trim() || undefined, class_id: classId.trim() || undefined,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail ?? "注册失败");
      localStorage.setItem("va_user", JSON.stringify(data.user));
      router.push("/auth/login");
    } catch (err: any) {
      setError(err?.message ?? "注册失败");
    }
    setLoading(false);
  }

  return (
    <main className="auth-page">
      <div className="auth-bg" aria-hidden="true">
        <span className="auth-orb auth-orb-a" />
        <span className="auth-orb auth-orb-b" />
      </div>

      <div className="auth-card auth-card-wide fade-up">
        <Link href="/" className="auth-back-link">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M10 2L4 8l6 6" /></svg>
          返回首页
        </Link>

        <div className="auth-header">
          <span className="auth-brand-dot" />
          <h1>注册</h1>
          <p>创建新账号以使用平台的完整功能</p>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <div className="auth-role-switch">
            {(["student", "teacher", "admin"] as Role[]).map((r) => (
              <button key={r} type="button" className={`auth-role-opt ${role === r ? "active" : ""}`} onClick={() => setRole(r)}>
                {{ student: "学生", teacher: "教师", admin: "管理员" }[r]}
              </button>
            ))}
          </div>

          <div className="auth-form-grid">
            <label className="auth-label">
              <span>昵称</span>
              <input required minLength={2} value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="你的名字" className="auth-input" />
            </label>
            <label className="auth-label">
              <span>邮箱</span>
              <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="your@email.com" className="auth-input" />
            </label>
            <label className="auth-label">
              <span>密码</span>
              <input type="password" required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="至少 6 位" className="auth-input" />
            </label>
            {role === "student" && (
              <>
                <label className="auth-label">
                  <span>学号（可选）</span>
                  <input value={studentId} onChange={(e) => setStudentId(e.target.value)} placeholder="student-001" className="auth-input" />
                </label>
                <label className="auth-label">
                  <span>班级（可选）</span>
                  <input value={classId} onChange={(e) => setClassId(e.target.value)} placeholder="2026A" className="auth-input" />
                </label>
              </>
            )}
          </div>

          {error && <div className="auth-error">{error}</div>}
          <button type="submit" className="auth-submit" disabled={loading}>
            {loading ? "注册中..." : "创建账号"}
          </button>
        </form>

        <div className="auth-footer">
          <span>已有账号？</span>
          <Link href="/auth/login">去登录</Link>
        </div>
      </div>
    </main>
  );
}
