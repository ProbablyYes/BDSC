"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8037").trim().replace(/\/+$/, "");

type AdminTab = "dashboard" | "users" | "projects" | "vulnerabilities" | "logs";
type UserRole = "student" | "teacher" | "admin";
type UserRecord = {
  id: string;
  name: string;
  role: UserRole;
  email: string;
  class_id: string;
  status: "active" | "disabled";
  last_login: string;
  project_count: number;
};

const MOCK_USERS: UserRecord[] = [
  { id: "student-001", name: "张三", role: "student", email: "zhangsan@edu.cn", class_id: "2026A", status: "active", last_login: "2026-03-22 14:30", project_count: 2 },
  { id: "student-002", name: "李四", role: "student", email: "lisi@edu.cn", class_id: "2026A", status: "active", last_login: "2026-03-21 09:15", project_count: 1 },
  { id: "student-003", name: "王五", role: "student", email: "wangwu@edu.cn", class_id: "2026B", status: "active", last_login: "2026-03-20 16:42", project_count: 3 },
  { id: "student-004", name: "赵六", role: "student", email: "zhaoliu@edu.cn", class_id: "2026B", status: "disabled", last_login: "2026-03-10 11:00", project_count: 0 },
  { id: "teacher-001", name: "陈老师", role: "teacher", email: "chen@edu.cn", class_id: "2026A", status: "active", last_login: "2026-03-22 08:00", project_count: 0 },
  { id: "teacher-002", name: "刘老师", role: "teacher", email: "liu@edu.cn", class_id: "2026B", status: "active", last_login: "2026-03-22 10:30", project_count: 0 },
  { id: "admin-001", name: "系统管理员", role: "admin", email: "admin@edu.cn", class_id: "", status: "active", last_login: "2026-03-22 22:00", project_count: 0 },
];

export default function AdminPage() {
  const [tab, setTab] = useState<AdminTab>("dashboard");
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [loading, setLoading] = useState(false);

  // Dashboard data
  const [dashboard, setDashboard] = useState<any>(null);
  const [allProjects, setAllProjects] = useState<any[]>([]);

  // User management
  const [users, setUsers] = useState<UserRecord[]>(MOCK_USERS);
  const [userSearch, setUserSearch] = useState("");
  const [userRoleFilter, setUserRoleFilter] = useState<"" | UserRole>("");
  const [editingUser, setEditingUser] = useState<string | null>(null);
  const [editRole, setEditRole] = useState<UserRole>("student");
  const [showAddUser, setShowAddUser] = useState(false);
  const [newUser, setNewUser] = useState({ id: "", name: "", role: "student" as UserRole, email: "", class_id: "" });

  // Logs
  const [accessLogs, setAccessLogs] = useState<any[]>([
    { time: "2026-03-22 14:32", user: "student-001", action: "LOGIN", detail: "学生登录", status: "OK" },
    { time: "2026-03-22 14:33", user: "student-001", action: "DIALOGUE", detail: "发送对话消息", status: "OK" },
    { time: "2026-03-22 14:35", user: "student-001", action: "UPLOAD", detail: "上传文件 BP.pdf", status: "OK" },
    { time: "2026-03-22 15:01", user: "student-002", action: "UNAUTHORIZED", detail: "尝试访问 /api/teacher/dashboard", status: "BLOCKED" },
    { time: "2026-03-22 15:10", user: "teacher-001", action: "LOGIN", detail: "教师登录", status: "OK" },
    { time: "2026-03-22 15:12", user: "teacher-001", action: "FEEDBACK", detail: "提交批注反馈", status: "OK" },
    { time: "2026-03-22 16:00", user: "student-003", action: "UNAUTHORIZED", detail: "尝试访问 /api/teacher/interventions", status: "BLOCKED" },
  ]);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    loadDashboard();
  }, []);

  async function loadDashboard() {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/teacher/dashboard`);
      const d = await r.json();
      setDashboard(d.data ?? d);
    } catch {
      setDashboard({
        overview: { total_projects: 0, total_evidence: 0, total_rule_hits: 0 },
        category_distribution: [],
        top_risk_rules: [],
        high_risk_projects: [],
      });
    }
    try {
      const r2 = await fetch(`${API}/api/teacher/submissions`);
      const d2 = await r2.json();
      setAllProjects(d2.submissions ?? []);
    } catch {
      setAllProjects([]);
    }
    setLoading(false);
  }

  const filteredUsers = useMemo(() => {
    let list = users;
    if (userRoleFilter) list = list.filter((u) => u.role === userRoleFilter);
    if (userSearch.trim()) {
      const q = userSearch.toLowerCase();
      list = list.filter((u) => u.name.toLowerCase().includes(q) || u.id.toLowerCase().includes(q) || u.email.toLowerCase().includes(q));
    }
    return list;
  }, [users, userSearch, userRoleFilter]);

  const stats = useMemo(() => {
    const total = allProjects.length;
    const avgScore = total > 0 ? allProjects.reduce((s, p) => s + (p.overall_score ?? 0), 0) / total : 0;
    const ruleFreq: Record<string, number> = {};
    for (const p of allProjects) {
      for (const r of p.triggered_rules ?? []) {
        ruleFreq[r] = (ruleFreq[r] || 0) + 1;
      }
    }
    const topRules = Object.entries(ruleFreq).sort((a, b) => b[1] - a[1]).slice(0, 5);

    const classStats: Record<string, { count: number; avgScore: number; riskCount: number }> = {};
    for (const p of allProjects) {
      const cls = p.class_id || "未分班";
      if (!classStats[cls]) classStats[cls] = { count: 0, avgScore: 0, riskCount: 0 };
      classStats[cls].count++;
      classStats[cls].avgScore += p.overall_score ?? 0;
      classStats[cls].riskCount += (p.triggered_rules ?? []).length;
    }
    for (const k of Object.keys(classStats)) {
      if (classStats[k].count > 0) classStats[k].avgScore = Math.round((classStats[k].avgScore / classStats[k].count) * 100) / 100;
    }

    return { total, avgScore: Math.round(avgScore * 100) / 100, topRules, classStats };
  }, [allProjects]);

  const healthScore = useMemo(() => {
    if (stats.total === 0) return 0;
    const avgNorm = Math.min(stats.avgScore / 10, 1);
    const riskPenalty = stats.topRules.reduce((s, [, c]) => s + c, 0) / Math.max(stats.total, 1);
    return Math.max(0, Math.round((avgNorm * 80 - riskPenalty * 5 + 20) * 10) / 10);
  }, [stats]);

  function changeUserRole(userId: string, newRole: UserRole) {
    setUsers((prev) => prev.map((u) => u.id === userId ? { ...u, role: newRole } : u));
    setEditingUser(null);
  }

  function toggleUserStatus(userId: string) {
    setUsers((prev) => prev.map((u) => u.id === userId ? { ...u, status: u.status === "active" ? "disabled" : "active" } : u));
  }

  function addUser() {
    if (!newUser.id.trim() || !newUser.name.trim()) return;
    setUsers((prev) => [...prev, {
      ...newUser,
      status: "active" as const,
      last_login: "从未登录",
      project_count: 0,
    }]);
    setNewUser({ id: "", name: "", role: "student", email: "", class_id: "" });
    setShowAddUser(false);
  }

  function deleteUser(userId: string) {
    if (userId === "admin-001") return;
    setUsers((prev) => prev.filter((u) => u.id !== userId));
  }

  const TABS: { id: AdminTab; label: string; icon: string }[] = [
    { id: "dashboard", label: "全局大盘", icon: "📊" },
    { id: "users", label: "用户管理", icon: "👥" },
    { id: "projects", label: "项目总览", icon: "📋" },
    { id: "vulnerabilities", label: "漏洞看板", icon: "🔍" },
    { id: "logs", label: "访问日志", icon: "📝" },
  ];

  return (
    <div className={`admin-app ${theme}`}>
      <header className="chat-topbar">
        <div className="topbar-left">
          <Link href="/" className="topbar-brand">
            <span className="brand-dot" style={{ background: "#e07070" }} />
            VentureAgent
          </Link>
          <span className="topbar-sep" />
          <span className="topbar-label" style={{ color: "var(--accent-red, #e07070)" }}>教务管理端</span>
          <span className="admin-role-badge">Admin</span>
        </div>
        <div className="topbar-center">
          <span className="admin-health-badge">
            系统健康度 <strong>{healthScore}</strong>/100
          </span>
        </div>
        <div className="topbar-right">
          <button type="button" className="topbar-icon-btn" onClick={() => setTheme((t) => t === "dark" ? "light" : "dark")} title="切换主题">
            {theme === "dark" ? (
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
            ) : (
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>
            )}
          </button>
          <button type="button" className="topbar-btn" onClick={loadDashboard} disabled={loading}>
            {loading ? "加载中…" : "刷新数据"}
          </button>
          <Link href="/teacher" className="topbar-btn">教师端</Link>
          <Link href="/student" className="topbar-btn">学生端</Link>
        </div>
      </header>

      <div className="admin-body">
        <nav className="admin-sidebar">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`admin-nav-btn ${tab === t.id ? "active" : ""}`}
              onClick={() => setTab(t.id)}
            >
              <span className="admin-nav-icon">{t.icon}</span>
              {t.label}
            </button>
          ))}
        </nav>

        <main className="admin-main">
          {/* ── Dashboard ── */}
          {tab === "dashboard" && (
            <div className="admin-panel fade-up">
              <div className="admin-panel-header">
                <h2>全局数据大盘</h2>
                <span className="admin-panel-desc">全校所有班级的聚合统计数据，实时更新</span>
              </div>

              <div className="admin-kpi-grid">
                <div className="admin-kpi">
                  <div className="admin-kpi-icon">📁</div>
                  <div className="admin-kpi-content">
                    <span className="admin-kpi-label">项目总数</span>
                    <strong className="admin-kpi-value">{dashboard?.overview?.total_projects ?? stats.total}</strong>
                  </div>
                </div>
                <div className="admin-kpi">
                  <div className="admin-kpi-icon">📊</div>
                  <div className="admin-kpi-content">
                    <span className="admin-kpi-label">平均分</span>
                    <strong className="admin-kpi-value">{stats.avgScore || (dashboard?.overview?.avg_score ?? "—")}</strong>
                  </div>
                </div>
                <div className="admin-kpi">
                  <div className="admin-kpi-icon">⚠️</div>
                  <div className="admin-kpi-content">
                    <span className="admin-kpi-label">风险触发次数</span>
                    <strong className="admin-kpi-value">{dashboard?.overview?.total_rule_hits ?? 0}</strong>
                  </div>
                </div>
                <div className="admin-kpi">
                  <div className="admin-kpi-icon">👥</div>
                  <div className="admin-kpi-content">
                    <span className="admin-kpi-label">注册用户</span>
                    <strong className="admin-kpi-value">{users.length}</strong>
                  </div>
                </div>
                <div className="admin-kpi">
                  <div className="admin-kpi-icon">💚</div>
                  <div className="admin-kpi-content">
                    <span className="admin-kpi-label">系统健康度</span>
                    <strong className="admin-kpi-value" style={{ color: healthScore >= 70 ? "#5cbd8a" : healthScore >= 40 ? "#e0a84c" : "#e07070" }}>{healthScore}/100</strong>
                  </div>
                </div>
                <div className="admin-kpi">
                  <div className="admin-kpi-icon">📄</div>
                  <div className="admin-kpi-content">
                    <span className="admin-kpi-label">证据总数</span>
                    <strong className="admin-kpi-value">{dashboard?.overview?.total_evidence ?? 0}</strong>
                  </div>
                </div>
              </div>

              {/* Class breakdown */}
              {Object.keys(stats.classStats).length > 0 && (
                <div className="admin-section">
                  <h3>各班级概况</h3>
                  <div className="admin-table">
                    <div className="admin-table-header">
                      <span>班级</span><span>项目数</span><span>平均分</span><span>风险触发</span><span>状态</span>
                    </div>
                    {Object.entries(stats.classStats).map(([cls, data]) => (
                      <div key={cls} className="admin-table-row">
                        <span className="admin-cell-primary">{cls}</span>
                        <span>{data.count}</span>
                        <span>{data.avgScore}</span>
                        <span>{data.riskCount}</span>
                        <span>
                          <span className={`admin-status-dot ${data.avgScore >= 5 ? "good" : data.avgScore >= 3 ? "warn" : "danger"}`} />
                          {data.avgScore >= 5 ? "良好" : data.avgScore >= 3 ? "需关注" : "高风险"}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Category distribution */}
              {(dashboard?.category_distribution ?? []).length > 0 && (
                <div className="admin-section">
                  <h3>项目类别分布</h3>
                  <div className="admin-bar-chart">
                    {dashboard.category_distribution.map((row: any) => {
                      const maxVal = Math.max(1, ...dashboard.category_distribution.map((r: any) => r.projects || 0));
                      return (
                        <div key={row.category} className="admin-bar-row">
                          <span className="admin-bar-label">{row.category}</span>
                          <div className="admin-bar-track">
                            <div className="admin-bar-fill" style={{ width: `${((row.projects || 0) / maxVal) * 100}%` }} />
                          </div>
                          <span className="admin-bar-value">{row.projects}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── User Management ── */}
          {tab === "users" && (
            <div className="admin-panel fade-up">
              <div className="admin-panel-header">
                <h2>用户与权限管理</h2>
                <span className="admin-panel-desc">管理所有用户账号、角色分配与状态</span>
              </div>

              <div className="admin-user-toolbar">
                <div className="admin-search-box">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
                  <input value={userSearch} onChange={(e) => setUserSearch(e.target.value)} placeholder="搜索用户名、ID或邮箱…" />
                </div>
                <div className="admin-filter-group">
                  <button className={`admin-filter-btn ${userRoleFilter === "" ? "active" : ""}`} onClick={() => setUserRoleFilter("")}>全部</button>
                  <button className={`admin-filter-btn ${userRoleFilter === "student" ? "active" : ""}`} onClick={() => setUserRoleFilter("student")}>学生</button>
                  <button className={`admin-filter-btn ${userRoleFilter === "teacher" ? "active" : ""}`} onClick={() => setUserRoleFilter("teacher")}>教师</button>
                  <button className={`admin-filter-btn ${userRoleFilter === "admin" ? "active" : ""}`} onClick={() => setUserRoleFilter("admin")}>管理员</button>
                </div>
                <button className="admin-add-btn" onClick={() => setShowAddUser(true)}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 5v14M5 12h14"/></svg>
                  添加用户
                </button>
              </div>

              {/* Add user form */}
              {showAddUser && (
                <div className="admin-add-form">
                  <h4>添加新用户</h4>
                  <div className="admin-form-grid">
                    <label>用户ID <input value={newUser.id} onChange={(e) => setNewUser({ ...newUser, id: e.target.value })} placeholder="如 student-005" /></label>
                    <label>姓名 <input value={newUser.name} onChange={(e) => setNewUser({ ...newUser, name: e.target.value })} placeholder="真实姓名" /></label>
                    <label>邮箱 <input value={newUser.email} onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} placeholder="xxx@edu.cn" /></label>
                    <label>班级 <input value={newUser.class_id} onChange={(e) => setNewUser({ ...newUser, class_id: e.target.value })} placeholder="如 2026A" /></label>
                    <label>角色
                      <select value={newUser.role} onChange={(e) => setNewUser({ ...newUser, role: e.target.value as UserRole })}>
                        <option value="student">学生</option>
                        <option value="teacher">教师</option>
                        <option value="admin">管理员</option>
                      </select>
                    </label>
                  </div>
                  <div className="admin-form-actions">
                    <button className="admin-btn-primary" onClick={addUser}>确认添加</button>
                    <button className="admin-btn-secondary" onClick={() => setShowAddUser(false)}>取消</button>
                  </div>
                </div>
              )}

              <div className="admin-table">
                <div className="admin-table-header">
                  <span>用户ID</span><span>姓名</span><span>角色</span><span>邮箱</span><span>班级</span><span>状态</span><span>最后登录</span><span>操作</span>
                </div>
                {filteredUsers.map((u) => (
                  <div key={u.id} className={`admin-table-row ${u.status === "disabled" ? "disabled" : ""}`}>
                    <span className="admin-cell-primary">{u.id}</span>
                    <span>{u.name}</span>
                    <span>
                      {editingUser === u.id ? (
                        <select value={editRole} onChange={(e) => { setEditRole(e.target.value as UserRole); changeUserRole(u.id, e.target.value as UserRole); }}>
                          <option value="student">学生</option>
                          <option value="teacher">教师</option>
                          <option value="admin">管理员</option>
                        </select>
                      ) : (
                        <span className={`admin-role-tag ${u.role}`}>
                          {{ student: "学生", teacher: "教师", admin: "管理员" }[u.role]}
                        </span>
                      )}
                    </span>
                    <span className="admin-cell-muted">{u.email}</span>
                    <span>{u.class_id || "—"}</span>
                    <span>
                      <span className={`admin-status-dot ${u.status === "active" ? "good" : "danger"}`} />
                      {u.status === "active" ? "正常" : "已禁用"}
                    </span>
                    <span className="admin-cell-muted">{u.last_login}</span>
                    <span className="admin-action-group">
                      <button className="admin-sm-btn" onClick={() => { setEditingUser(u.id); setEditRole(u.role); }} title="修改角色">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                      </button>
                      <button className="admin-sm-btn" onClick={() => toggleUserStatus(u.id)} title={u.status === "active" ? "禁用" : "启用"}>
                        {u.status === "active" ? (
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>
                        ) : (
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#5cbd8a" strokeWidth="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                        )}
                      </button>
                      {u.id !== "admin-001" && (
                        <button className="admin-sm-btn danger" onClick={() => deleteUser(u.id)} title="删除">
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                        </button>
                      )}
                    </span>
                  </div>
                ))}
              </div>

              <div className="admin-user-stats">
                <span>共 {users.length} 个用户</span>
                <span>学生 {users.filter((u) => u.role === "student").length}</span>
                <span>教师 {users.filter((u) => u.role === "teacher").length}</span>
                <span>管理员 {users.filter((u) => u.role === "admin").length}</span>
              </div>
            </div>
          )}

          {/* ── Projects Overview ── */}
          {tab === "projects" && (
            <div className="admin-panel fade-up">
              <div className="admin-panel-header">
                <h2>全校项目总览</h2>
                <span className="admin-panel-desc">所有班级、所有学生提交的项目一览</span>
              </div>

              <div className="admin-kpi-grid" style={{ marginBottom: 20 }}>
                <div className="admin-kpi">
                  <div className="admin-kpi-icon">📁</div>
                  <div className="admin-kpi-content">
                    <span className="admin-kpi-label">总项目数</span>
                    <strong className="admin-kpi-value">{stats.total}</strong>
                  </div>
                </div>
                <div className="admin-kpi">
                  <div className="admin-kpi-icon">📊</div>
                  <div className="admin-kpi-content">
                    <span className="admin-kpi-label">平均评分</span>
                    <strong className="admin-kpi-value">{stats.avgScore}</strong>
                  </div>
                </div>
                <div className="admin-kpi">
                  <div className="admin-kpi-icon">🏫</div>
                  <div className="admin-kpi-content">
                    <span className="admin-kpi-label">涉及班级</span>
                    <strong className="admin-kpi-value">{Object.keys(stats.classStats).length}</strong>
                  </div>
                </div>
              </div>

              {allProjects.length > 0 ? (
                <div className="admin-table">
                  <div className="admin-table-header">
                    <span>项目ID</span><span>学生</span><span>班级</span><span>评分</span><span>风险规则</span><span>提交时间</span>
                  </div>
                  {allProjects.map((p, i) => (
                    <div key={i} className="admin-table-row">
                      <span className="admin-cell-primary">{p.project_id}</span>
                      <span>{p.student_id}</span>
                      <span>{p.class_id || "—"}</span>
                      <span>
                        <span className={`admin-score ${(p.overall_score ?? 0) >= 7 ? "good" : (p.overall_score ?? 0) >= 4 ? "warn" : "danger"}`}>
                          {p.overall_score ?? "—"}
                        </span>
                      </span>
                      <span>
                        {(p.triggered_rules ?? []).length > 0 ? (
                          <span className="admin-risk-count">{(p.triggered_rules ?? []).length} 条</span>
                        ) : (
                          <span className="admin-cell-muted">无</span>
                        )}
                      </span>
                      <span className="admin-cell-muted">{(p.created_at ?? "").slice(0, 16)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="admin-empty">暂无项目数据。学生在学生端对话后会自动产生项目数据。</div>
              )}
            </div>
          )}

          {/* ── Vulnerabilities Board ── */}
          {tab === "vulnerabilities" && (
            <div className="admin-panel fade-up">
              <div className="admin-panel-header">
                <h2>高频漏洞看板</h2>
                <span className="admin-panel-desc">全校范围内被触发最多的业务漏洞 Top 排行，帮助教务识别共性问题</span>
              </div>

              {stats.topRules.length > 0 ? (
                <>
                  <div className="admin-vuln-cards">
                    {stats.topRules.slice(0, 3).map(([rule, count], i) => (
                      <div key={rule} className={`admin-vuln-card rank-${i + 1}`}>
                        <div className="admin-vuln-rank">Top {i + 1}</div>
                        <div className="admin-vuln-name">{rule}</div>
                        <div className="admin-vuln-count">{count} 个项目触发</div>
                        <div className="admin-vuln-bar">
                          <div className="admin-vuln-fill" style={{ width: `${(count / Math.max(1, stats.total)) * 100}%` }} />
                        </div>
                        <div className="admin-vuln-pct">{Math.round((count / Math.max(1, stats.total)) * 100)}% 项目受影响</div>
                      </div>
                    ))}
                  </div>

                  <div className="admin-section">
                    <h3>完整漏洞列表</h3>
                    <div className="admin-table">
                      <div className="admin-table-header">
                        <span>排名</span><span>规则名称</span><span>触发次数</span><span>影响比例</span><span>严重等级</span>
                      </div>
                      {stats.topRules.map(([rule, count], i) => (
                        <div key={rule} className="admin-table-row">
                          <span className="admin-cell-primary">#{i + 1}</span>
                          <span>{rule}</span>
                          <span>{count}</span>
                          <span>{Math.round((count / Math.max(1, stats.total)) * 100)}%</span>
                          <span>
                            <span className={`admin-severity ${count >= 3 ? "high" : count >= 2 ? "medium" : "low"}`}>
                              {count >= 3 ? "高危" : count >= 2 ? "中等" : "轻微"}
                            </span>
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* High risk projects from dashboard */}
                  {(dashboard?.high_risk_projects ?? []).length > 0 && (
                    <div className="admin-section">
                      <h3>高风险项目清单</h3>
                      <div className="admin-table">
                        <div className="admin-table-header">
                          <span>项目ID</span><span>项目名</span><span>类别</span><span>风险数</span>
                        </div>
                        {dashboard.high_risk_projects.slice(0, 10).map((p: any) => (
                          <div key={p.project_id} className="admin-table-row">
                            <span className="admin-cell-primary">{p.project_id}</span>
                            <span>{p.project_name || "—"}</span>
                            <span>{p.category || "—"}</span>
                            <span><span className="admin-risk-count">{p.risk_count}</span></span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <div className="admin-empty">
                  <div className="admin-empty-icon">🔍</div>
                  <p>暂无漏洞数据。学生提交项目并经过系统诊断后，高频漏洞会自动出现在此。</p>
                </div>
              )}
            </div>
          )}

          {/* ── Access Logs ── */}
          {tab === "logs" && (
            <div className="admin-panel fade-up">
              <div className="admin-panel-header">
                <h2>访问与安全日志</h2>
                <span className="admin-panel-desc">记录所有用户的关键操作与越权访问尝试</span>
              </div>

              <div className="admin-table">
                <div className="admin-table-header">
                  <span>时间</span><span>用户</span><span>操作类型</span><span>详情</span><span>状态</span>
                </div>
                {accessLogs.map((log, i) => (
                  <div key={i} className={`admin-table-row ${log.status === "BLOCKED" ? "blocked" : ""}`}>
                    <span className="admin-cell-muted">{log.time}</span>
                    <span className="admin-cell-primary">{log.user}</span>
                    <span>
                      <span className={`admin-log-action ${log.action === "UNAUTHORIZED" ? "danger" : ""}`}>
                        {log.action}
                      </span>
                    </span>
                    <span>{log.detail}</span>
                    <span>
                      {log.status === "BLOCKED" ? (
                        <span className="admin-log-blocked">🚫 已拦截 (403)</span>
                      ) : (
                        <span className="admin-log-ok">✓ 正常</span>
                      )}
                    </span>
                  </div>
                ))}
              </div>

              <div className="admin-log-summary">
                <span>总操作 {accessLogs.length} 条</span>
                <span className="admin-log-blocked-count">越权拦截 {accessLogs.filter((l) => l.status === "BLOCKED").length} 次</span>
              </div>
            </div>
          )}
        </main>
      </div>

      <div className="admin-footer-disclaimer">
        ⚠ AI生成，仅供参考 | VentureAgent 教务管理系统
      </div>
    </div>
  );
}
