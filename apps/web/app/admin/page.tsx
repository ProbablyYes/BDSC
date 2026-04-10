"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useAuth, logout } from "../hooks/useAuth";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8037").trim().replace(/\/+$/, "");

type AdminTab = "dashboard" | "teachers" | "interventions" | "users" | "projects" | "vulnerabilities" | "logs";
type UserRole = "student" | "teacher" | "admin";
type UserRecord = {
  id: string;
  name: string;
  role: UserRole;
  email: string;
  teams: string[];
  status: "active" | "disabled";
  last_login: string;
  project_count: number;
};

type TeamInfo = {
  team_id: string;
  team_name: string;
  teacher_id: string;
  teacher_name: string;
  invite_code?: string;
  members: { user_id: string; joined_at: string }[];
};

type TeacherStat = {
  teacher_id: string;
  name: string;
  email: string;
  team_count: number;
  student_count: number;
  active_students: number;
  avg_score: number;
  risk_rate: number;
  intervention_coverage: number;
  last_active: string;
  rank: number;
};

type TeacherSortKey = "rank" | "avg_score" | "risk_rate" | "active_students" | "team_count" | "intervention_coverage";

type InterventionStatus = "draft" | "approved" | "sent" | "viewed" | "completed" | "archived";

type InterventionSummary = {
  total_interventions: number;
  teacher_count: number;
  student_count: number;
  completed_count: number;
  status_counts: Record<InterventionStatus, number>;
};

type TeacherInterventionAgg = {
  teacher_id: string;
  name: string;
  email: string;
  total_interventions: number;
  draft: number;
  approved: number;
  sent: number;
  viewed: number;
  completed: number;
  archived: number;
  student_count: number;
};

type InterventionRecord = {
  intervention_id: string;
  project_id: string;
  logical_project_id: string;
  teacher_id: string;
  teacher_name: string;
  student_id: string;
  student_name: string;
  title: string;
  reason_summary: string;
  status: InterventionStatus | string;
  scope_type: string;
  scope_id: string;
  priority: string;
  created_at: string;
  updated_at: string;
};

type AdminLogEntry = {
  time: string;
  user: string;
  action: string;
  detail: string;
  status: string;
  path: string;
  method?: string;
  status_code?: number;
  duration_ms?: number;
  user_id?: string;
  role?: UserRole | string;
  display_name?: string;
};

type AdminLogPathStat = {
  path: string;
  count: number;
  avg_duration_ms: number;
  success_count: number;
  error_count: number;
  blocked_count: number;
};

type AdminLogStats = {
  total_requests: number;
  success_count: number;
  error_count: number;
  blocked_count: number;
  avg_duration_ms: number;
  p95_duration_ms: number;
  top_paths: AdminLogPathStat[];
};

const INTERVENTION_STATUS_LABEL: Record<InterventionStatus, string> = {
  draft: "草稿",
  approved: "已审批",
  sent: "已发送",
  viewed: "已查看",
  completed: "已完成",
  archived: "已归档",
};

function getUserIdFromProjectId(projectId: string | undefined | null): string {
  if (!projectId) return "";
  const pid = String(projectId);
  if (pid.startsWith("project-")) {
    return pid.slice("project-".length);
  }
  return pid;
}

export default function AdminPage() {
  const currentUser = useAuth("admin");
  const [tab, setTab] = useState<AdminTab>("dashboard");
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [loading, setLoading] = useState(false);

  // Dashboard data
  const [dashboard, setDashboard] = useState<any>(null);
  const [allProjects, setAllProjects] = useState<any[]>([]);

  // User management
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [userSearch, setUserSearch] = useState("");
  const [userRoleFilter, setUserRoleFilter] = useState<"" | UserRole>("");
  const [teamFilter, setTeamFilter] = useState<string>("");
  const [groupByTeam, setGroupByTeam] = useState(false);
  const [editingUser, setEditingUser] = useState<string | null>(null);
  const [editRole, setEditRole] = useState<UserRole>("student");
  const [showAddUser, setShowAddUser] = useState(false);
  const [newUser, setNewUser] = useState({ id: "", name: "", role: "student" as UserRole, email: "", password: "" });

  // Batch user creation
  const [showBatchCreate, setShowBatchCreate] = useState(false);
  const [batchRole, setBatchRole] = useState<UserRole>("student");
  const [batchPrefix, setBatchPrefix] = useState<string>("stu");
  const [batchStartIndex, setBatchStartIndex] = useState<number>(1);
  const [batchCount, setBatchCount] = useState<number>(10);
  const [batchPasswordSuffix, setBatchPasswordSuffix] = useState<string>("123");
  const [batchInviteCode, setBatchInviteCode] = useState<string>("");
  const [batchTeamName, setBatchTeamName] = useState<string>("");
  const [batchTeamInviteCode, setBatchTeamInviteCode] = useState<string>("");
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const [batchResult, setBatchResult] = useState<any>(null);

  // Teacher performance
  const [teachers, setTeachers] = useState<TeacherStat[]>([]);
  const [teacherSortKey, setTeacherSortKey] = useState<TeacherSortKey>("rank");

  // Teaching interventions (admin)
  const [interventionSummary, setInterventionSummary] = useState<InterventionSummary | null>(null);
  const [interventionTeachers, setInterventionTeachers] = useState<TeacherInterventionAgg[]>([]);
  const [recentInterventions, setRecentInterventions] = useState<InterventionRecord[]>([]);

  // Logs
  const [accessLogs, setAccessLogs] = useState<AdminLogEntry[]>([]);
  const [logStats, setLogStats] = useState<AdminLogStats | null>(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    loadDashboard();
    loadUsers();
    loadTeams();
    loadTeachers();
  }, []);

  useEffect(() => {
    if (tab === "users") {
      loadUsers();
      loadTeams();
    } else if (tab === "teachers") {
      loadTeachers();
    } else if (tab === "interventions") {
      loadInterventions();
    } else if (tab === "logs") {
      loadLogs();
    }
  }, [tab]);

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
      const r2 = await fetch(`${API}/api/admin/projects`);
      const d2 = await r2.json();
      const projects = Array.isArray(d2.projects) ? d2.projects : [];
      const list = [...projects];
      list.sort((a: any, b: any) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")));
      setAllProjects(list);
    } catch {
      setAllProjects([]);
    }
    setLoading(false);
  }

  async function loadTeams() {
    try {
      const r = await fetch(`${API}/api/teams`);
      const d = await r.json();
      const rows: TeamInfo[] = (d.teams ?? []).map((t: any) => ({
        team_id: t.team_id,
        team_name: t.team_name,
        teacher_id: t.teacher_id,
        teacher_name: t.teacher_name ?? "",
        invite_code: t.invite_code ?? "",
        members: Array.isArray(t.members)
          ? t.members.map((m: any) => ({ user_id: m.user_id, joined_at: m.joined_at ?? "" }))
          : [],
      }));
      setTeams(rows);
    } catch {
      setTeams([]);
    }
  }

  async function loadUsers() {
    try {
      const r = await fetch(`${API}/api/admin/users`);
      const d = await r.json();
      const rows = (d.users ?? []).map((u: any): UserRecord => ({
        id: u.user_id,
        name: u.display_name ?? u.email ?? u.user_id,
        role: u.role as UserRole,
        email: u.email,
        teams: Array.isArray(u.team_names) ? (u.team_names as string[]).filter(Boolean) : [],
        status: (u.status as "active" | "disabled") ?? "active",
        last_login: u.last_login || "",
        project_count: typeof u.project_count === "number" ? u.project_count : 0,
      }));
      setUsers(rows);
    } catch {
      setUsers([]);
    }
  }

  async function loadTeachers() {
    try {
      const r = await fetch(`${API}/api/admin/teachers`);
      const d = await r.json();
      const rows: TeacherStat[] = (d.teachers ?? []).map((t: any) => ({
        teacher_id: t.teacher_id,
        name: t.display_name ?? t.email ?? t.teacher_id,
        email: t.email ?? "",
        team_count: typeof t.team_count === "number" ? t.team_count : 0,
        student_count: typeof t.student_count === "number" ? t.student_count : 0,
        active_students: typeof t.active_students === "number" ? t.active_students : 0,
        avg_score: typeof t.avg_score === "number" ? t.avg_score : 0,
        risk_rate: typeof t.risk_rate === "number" ? t.risk_rate : 0,
        intervention_coverage: typeof t.intervention_coverage === "number" ? t.intervention_coverage : 0,
        last_active: t.last_active ?? "",
        rank: typeof t.rank === "number" ? t.rank : 0,
      }));
      setTeachers(rows);
    } catch {
      setTeachers([]);
    }
  }

  async function loadInterventions() {
    try {
      const r = await fetch(`${API}/api/admin/interventions`);
      const d = await r.json();
      const summaryRaw = d.summary ?? null;
      if (summaryRaw) {
        const statusCounts = summaryRaw.status_counts ?? {};
        const normalizedStatus: Record<InterventionStatus, number> = {
          draft: Number(statusCounts.draft ?? 0),
          approved: Number(statusCounts.approved ?? 0),
          sent: Number(statusCounts.sent ?? 0),
          viewed: Number(statusCounts.viewed ?? 0),
          completed: Number(statusCounts.completed ?? 0),
          archived: Number(statusCounts.archived ?? 0),
        };
        setInterventionSummary({
          total_interventions: Number(summaryRaw.total_interventions ?? 0),
          teacher_count: Number(summaryRaw.teacher_count ?? 0),
          student_count: Number(summaryRaw.student_count ?? 0),
          completed_count: Number(summaryRaw.completed_count ?? 0),
          status_counts: normalizedStatus,
        });
      } else {
        setInterventionSummary(null);
      }

      const teachersRaw: TeacherInterventionAgg[] = (d.teachers ?? []).map((t: any): TeacherInterventionAgg => ({
        teacher_id: String(t.teacher_id ?? ""),
        name: t.name ?? t.display_name ?? t.email ?? String(t.teacher_id ?? ""),
        email: t.email ?? "",
        total_interventions: Number(t.total_interventions ?? 0),
        draft: Number(t.draft ?? 0),
        approved: Number(t.approved ?? 0),
        sent: Number(t.sent ?? 0),
        viewed: Number(t.viewed ?? 0),
        completed: Number(t.completed ?? 0),
        archived: Number(t.archived ?? 0),
        student_count: Number(t.student_count ?? 0),
      }));
      setInterventionTeachers(teachersRaw);

      const recentRaw: InterventionRecord[] = (d.recent ?? []).map((row: any): InterventionRecord => ({
        intervention_id: String(row.intervention_id ?? ""),
        project_id: String(row.project_id ?? ""),
        logical_project_id: String(row.logical_project_id ?? ""),
        teacher_id: String(row.teacher_id ?? ""),
        teacher_name: row.teacher_name ?? row.teacher_id ?? "",
        student_id: String(row.student_id ?? ""),
        student_name: row.student_name ?? row.student_id ?? "",
        title: row.title ?? "",
        reason_summary: row.reason_summary ?? "",
        status: (row.status ?? "draft") as InterventionStatus | string,
        scope_type: row.scope_type ?? "",
        scope_id: row.scope_id ?? "",
        priority: row.priority ?? "",
        created_at: row.created_at ?? "",
        updated_at: row.updated_at ?? "",
      }));
      setRecentInterventions(recentRaw);
    } catch {
      setInterventionSummary(null);
      setInterventionTeachers([]);
      setRecentInterventions([]);
    }
  }

  async function loadLogs() {
    try {
      const r = await fetch(`${API}/api/admin/logs`);
      const d = await r.json();
      const rawLogs: AdminLogEntry[] = (d.logs ?? d ?? []).map((row: any): AdminLogEntry => ({
        time: row.time ?? "",
        user: row.user ?? "",
        action: row.action ?? "",
        detail: row.detail ?? "",
        status: row.status ?? "",
        path: row.path ?? "",
        method: row.method,
        status_code: typeof row.status_code === "number" ? row.status_code : undefined,
        duration_ms: typeof row.duration_ms === "number" ? row.duration_ms : undefined,
        user_id: row.user_id ? String(row.user_id) : undefined,
        role: row.role as UserRole | string | undefined,
        display_name: row.display_name ?? undefined,
      }));
      setAccessLogs(rawLogs);

      const s = d.stats ?? null;
      if (s) {
        const topPaths: AdminLogPathStat[] = (s.top_paths ?? []).map((p: any): AdminLogPathStat => ({
          path: p.path ?? "",
          count: Number(p.count ?? 0),
          avg_duration_ms: Number(p.avg_duration_ms ?? 0),
          success_count: Number(p.success_count ?? 0),
          error_count: Number(p.error_count ?? 0),
          blocked_count: Number(p.blocked_count ?? 0),
        }));
        setLogStats({
          total_requests: Number(s.total_requests ?? rawLogs.length ?? 0),
          success_count: Number(s.success_count ?? 0),
          error_count: Number(s.error_count ?? 0),
          blocked_count: Number(s.blocked_count ?? 0),
          avg_duration_ms: Number(s.avg_duration_ms ?? 0),
          p95_duration_ms: Number(s.p95_duration_ms ?? 0),
          top_paths: topPaths,
        });
      } else {
        setLogStats(null);
      }
    } catch {
      setAccessLogs([]);
      setLogStats(null);
    }
  }

  const [teams, setTeams] = useState<TeamInfo[]>([]);
  const [manageTeacherId, setManageTeacherId] = useState<string | null>(null);
  const [manageTeacherName, setManageTeacherName] = useState<string>("");
  const [showTeamManager, setShowTeamManager] = useState(false);
  const [newTeamName, setNewTeamName] = useState<string>("");
  const [newTeamInviteCode, setNewTeamInviteCode] = useState<string>("");
  const [teamSubmitting, setTeamSubmitting] = useState(false);
  const [editTeamId, setEditTeamId] = useState<string | null>(null);
  const [newMemberUserId, setNewMemberUserId] = useState<string>("");
  const [memberSubmitting, setMemberSubmitting] = useState(false);

  const studentNameByUserId = useMemo(() => {
    const map: Record<string, string> = {};
    for (const u of users) {
      if (u.id) {
        map[u.id] = u.name || u.email || u.id;
      }
    }
    return map;
  }, [users]);

  const userTeamNames = useMemo(() => {
    const map: Record<string, string[]> = {};
    for (const t of teams) {
      const teamName = t.team_name || "";
      if (!teamName) continue;
      for (const m of t.members) {
        const uid = m.user_id;
        if (!uid) continue;
        if (!map[uid]) map[uid] = [];
        if (!map[uid].includes(teamName)) {
          map[uid].push(teamName);
        }
      }
    }
    return map;
  }, [teams]);

  const projectTeamCount = useMemo(() => {
    const teamNames = new Set<string>();
    for (const p of allProjects) {
      const uid = getUserIdFromProjectId(p.project_id);
      if (!uid) continue;
      const names = userTeamNames[uid] ?? [];
      for (const name of names) {
        if (name) teamNames.add(name);
      }
    }
    return teamNames.size;
  }, [allProjects, userTeamNames]);

  const baseUsers = useMemo(() => {
    let list = users;
    if (userRoleFilter) list = list.filter((u) => u.role === userRoleFilter);
    if (userSearch.trim()) {
      const q = userSearch.toLowerCase();
      list = list.filter((u) => u.name.toLowerCase().includes(q) || u.id.toLowerCase().includes(q) || u.email.toLowerCase().includes(q));
    }
    return list;
  }, [users, userSearch, userRoleFilter]);

  const filteredUsers = useMemo(() => {
    let list = baseUsers;
    if (teamFilter) {
      const allMemberIds = new Set<string>();
      for (const t of teams) {
        if (t.teacher_id) allMemberIds.add(t.teacher_id);
        for (const m of t.members) allMemberIds.add(m.user_id);
      }
      if (teamFilter === "__no_team__") {
        list = list.filter((u) => !allMemberIds.has(u.id));
      } else {
        const target = teams.find((t) => t.team_id === teamFilter);
        if (!target) {
          list = [];
        } else {
          const ids = new Set<string>();
          if (target.teacher_id) ids.add(target.teacher_id);
          for (const m of target.members) ids.add(m.user_id);
          list = list.filter((u) => ids.has(u.id));
        }
      }
    }
    return list;
  }, [baseUsers, teamFilter, teams]);

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

  const sortedTeachers = useMemo(() => {
    const list = [...teachers];
    list.sort((a, b) => {
      const aVal = a[teacherSortKey];
      const bVal = b[teacherSortKey];
      if (teacherSortKey === "rank") {
        return aVal - bVal;
      }
      return bVal - aVal;
    });
    return list;
  }, [teachers, teacherSortKey]);

  function openTeacherTeamManager(teacherId: string, teacherName: string) {
    setManageTeacherId(teacherId);
    setManageTeacherName(teacherName || teacherId);
    setShowTeamManager(true);
  }

  function closeTeacherTeamManager() {
    setShowTeamManager(false);
    setManageTeacherId(null);
    setManageTeacherName("");
    setNewTeamName("");
    setNewTeamInviteCode("");
  }

  function openTeamMemberManager(teamId: string) {
    setEditTeamId(teamId);
    setNewMemberUserId("");
  }

  function closeTeamMemberManager() {
    setEditTeamId(null);
    setNewMemberUserId("");
  }

  async function createTeacherTeam() {
    if (!manageTeacherId) {
      window.alert("请选择要管理的教师");
      return;
    }
    const name = newTeamName.trim();
    if (!name) {
      window.alert("请输入团队名称");
      return;
    }

    const payload: any = {
      teacher_id: manageTeacherId,
      teacher_name: manageTeacherName || manageTeacherId,
      team_name: name,
    };
    if (newTeamInviteCode.trim()) {
      payload.invite_code = newTeamInviteCode.trim().toUpperCase();
    }

    setTeamSubmitting(true);
    try {
      const r = await fetch(`${API}/api/teams`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        let msg = "创建团队失败";
        try {
          const err = await r.json();
          if (err && err.detail) msg = String(err.detail);
        } catch {
          /* noop */
        }
        window.alert(msg);
        return;
      }
      await Promise.all([loadTeams(), loadUsers()]);
      setNewTeamName("");
      setNewTeamInviteCode("");
    } catch {
      window.alert("创建团队失败，请稍后再试");
    } finally {
      setTeamSubmitting(false);
    }
  }

  async function deleteTeacherTeam(teamId: string, teacherId: string) {
    if (!window.confirm("确定要删除该团队吗？此操作不可恢复。")) return;
    try {
      const url = `${API}/api/teams/${teamId}?teacher_id=${encodeURIComponent(teacherId)}`;
      const r = await fetch(url, { method: "DELETE" });
      if (!r.ok) {
        let msg = "删除团队失败";
        try {
          const err = await r.json();
          if (err && err.detail) msg = String(err.detail);
        } catch {
          /* noop */
        }
        window.alert(msg);
        return;
      }
      await Promise.all([loadTeams(), loadUsers()]);
    } catch {
      window.alert("删除团队失败，请稍后再试");
    }
  }

   async function addMemberToTeam() {
    if (!editTeamId) {
      window.alert("请选择要编辑的团队");
      return;
    }
    const userId = newMemberUserId.trim();
    if (!userId) {
      window.alert("请输入成员的用户ID");
      return;
    }
    const team = teams.find((t) => t.team_id === editTeamId);
    if (!team) {
      window.alert("团队不存在或已被删除");
      return;
    }
    if (!team.invite_code) {
      window.alert("该团队暂无邀请码，暂无法通过后台直接添加成员");
      return;
    }

    setMemberSubmitting(true);
    try {
      const payload = {
        user_id: userId,
        invite_code: String(team.invite_code).toUpperCase(),
      };
      const r = await fetch(`${API}/api/teams/join`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        let msg = "添加成员失败";
        try {
          const err = await r.json();
          if (err && err.detail) msg = String(err.detail);
        } catch {
          /* noop */
        }
        window.alert(msg);
        return;
      }
      await Promise.all([loadTeams(), loadUsers()]);
      setNewMemberUserId("");
    } catch {
      window.alert("添加成员失败，请稍后再试");
    } finally {
      setMemberSubmitting(false);
    }
  }

  function renderUserRow(u: UserRecord, team?: TeamInfo) {
    const inThisTeam = team && (team.teacher_id === u.id || team.members.some((m) => m.user_id === u.id));
    const canKick = !!(team && inThisTeam && team.teacher_id !== u.id);
    return (
      <div key={u.id} className={`admin-table-row ${u.status === "disabled" ? "disabled" : ""}`}>
        <span className="admin-cell-primary">{u.id}</span>
        <span>{u.name}</span>
        <span>
          {editingUser === u.id ? (
            <select
              value={editRole}
              onChange={(e) => {
                setEditRole(e.target.value as UserRole);
                changeUserRole(u.id, e.target.value as UserRole);
              }}
            >
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
        <span>{u.teams.length ? u.teams.join("、") : "未加入团队"}</span>
        <span>
          <span className={`admin-status-dot ${u.status === "active" ? "good" : "danger"}`} />
          {u.status === "active" ? "正常" : "已禁用"}
        </span>
        <span className="admin-cell-muted">{u.last_login}</span>
        <span className="admin-action-group">
          <button
            className="admin-sm-btn"
            onClick={() => {
              setEditingUser(u.id);
              setEditRole(u.role);
            }}
            title="修改角色"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
              <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
            </svg>
          </button>
          <button
            className="admin-sm-btn"
            onClick={() => toggleUserStatus(u.id)}
            title={u.status === "active" ? "禁用" : "启用"}
          >
            {u.status === "active" ? (
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="4.93" y1="4.93" x2="19.07" y2="19.07" />
              </svg>
            ) : (
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#5cbd8a" strokeWidth="2">
                <path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
                <polyline points="22 4 12 14.01 9 11.01" />
              </svg>
            )}
          </button>
          {u.id !== "admin-001" && (
            <>
              {u.role === "teacher" && (
                <button
                  className="admin-sm-btn"
                  onClick={() => openTeacherTeamManager(u.id, u.name)}
                  title="管理该教师的团队"
                >
                  团队
                </button>
              )}
              <button
                className="admin-sm-btn"
                onClick={() => resetPassword(u.id)}
                title="重置密码"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M4 4v6h6" />
                  <path d="M20 20v-6h-6" />
                  <path d="M5 19A9 9 0 0119 5" />
                </svg>
              </button>
              <button
                className="admin-sm-btn danger"
                onClick={() => deleteUser(u.id)}
                title="删除"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                </svg>
              </button>
            </>
          )}
          {canKick && team && (
            <button
              className="admin-sm-btn"
              onClick={() => removeMemberFromTeam(team.team_id, team.teacher_id, u.id)}
              title="移出该团队"
            >
              ✕
            </button>
          )}
        </span>
      </div>
    );
  }

  async function changeUserRole(userId: string, newRole: UserRole) {
    setEditingUser(userId);
    try {
      const r = await fetch(`${API}/api/admin/users/${userId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: newRole }),
      });
      const d = await r.json();
      const u = d.user ?? d;
      setUsers((prev) => prev.map((row) => row.id === userId ? {
        id: u.user_id,
        name: u.display_name ?? u.email ?? u.user_id,
        role: u.role as UserRole,
        email: u.email,
        teams: Array.isArray(u.team_names) ? (u.team_names as string[]).filter(Boolean) : row.teams,
        status: (u.status as "active" | "disabled") ?? "active",
        last_login: u.last_login || "",
        project_count: typeof u.project_count === "number" ? u.project_count : row.project_count,
      } : row));
    } finally {
      setEditingUser(null);
    }
  }

  async function toggleUserStatus(userId: string) {
    const target = users.find((u) => u.id === userId);
    const nextStatus: "active" | "disabled" = target?.status === "active" ? "disabled" : "active";
    try {
      await fetch(`${API}/api/admin/users/${userId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: nextStatus }),
      });
      setUsers((prev) => prev.map((u) => u.id === userId ? { ...u, status: nextStatus } : u));
    } catch {
      /* noop */
    }
  }

  async function addUser() {
    if (!newUser.id.trim() || !newUser.name.trim()) return;
    const payload = {
      role: newUser.role,
      display_name: newUser.name,
      email: newUser.email || `${newUser.id}@local`,
      student_id: newUser.id,
      password: newUser.password || undefined,
    };
    try {
      const r = await fetch(`${API}/api/admin/users`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const d = await r.json();
      const u = d.user ?? d;
      const record: UserRecord = {
        id: u.user_id,
        name: u.display_name ?? u.email ?? u.user_id,
        role: u.role as UserRole,
        email: u.email,
        teams: Array.isArray(u.team_names) ? (u.team_names as string[]).filter(Boolean) : [],
        status: (u.status as "active" | "disabled") ?? "active",
        last_login: u.last_login || "从未登录",
        project_count: typeof u.project_count === "number" ? u.project_count : 0,
      };
      setUsers((prev) => [...prev, record]);
      setNewUser({ id: "", name: "", role: "student", email: "", password: "" });
      setShowAddUser(false);
    } catch {
      /* noop */
    }
  }

  async function deleteUser(userId: string) {
    try {
      await fetch(`${API}/api/admin/users/${userId}`, { method: "DELETE" });
      setUsers((prev) => prev.filter((u) => u.id !== userId));
    } catch {
      /* noop */
    }
  }

  async function renameTeam(teamId: string, currentName: string, teacherId: string) {
    const name = window.prompt("请输入新的团队名称", currentName || "");
    if (!name || name.trim() === currentName.trim()) return;
    try {
      await fetch(`${API}/api/teams/${teamId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ teacher_id: teacherId, team_name: name.trim() }),
      });
      await Promise.all([loadTeams(), loadUsers()]);
    } catch {
      /* noop */
    }
  }

  async function removeMemberFromTeam(teamId: string, teacherId: string, userId: string) {
    if (!window.confirm("确定将该成员移出团队吗？")) return;
    try {
      await fetch(`${API}/api/teams/${teamId}/members/${userId}?teacher_id=${encodeURIComponent(teacherId)}`, {
        method: "DELETE",
      });
      await Promise.all([loadTeams(), loadUsers()]);
    } catch {
      /* noop */
    }
  }

  async function resetPassword(userId: string) {
    const pwd = window.prompt("请输入新密码（至少6位）", "");
    if (!pwd || pwd.length < 6) return;
    try {
      await fetch(`${API}/api/admin/users/${userId}/password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_password: pwd }),
      });
      window.alert("密码已更新");
    } catch {
      /* noop */
    }
  }

  async function batchCreateUsers() {
    if (!batchPrefix.trim()) {
      window.alert("账号前缀不能为空");
      return;
    }
    if (batchCount <= 0) {
      window.alert("创建数量必须大于 0");
      return;
    }

    const payload: any = {
      role: batchRole === "admin" ? "student" : batchRole,
      prefix: batchPrefix.trim(),
      start_index: batchStartIndex || 1,
      count: batchCount,
      password_suffix: batchPasswordSuffix || "123",
    };

    if (payload.role === "student" && batchInviteCode.trim()) {
      payload.invite_code = batchInviteCode.trim().toUpperCase();
    }
    if (payload.role === "teacher") {
      if (batchTeamName.trim()) {
        payload.team_name = batchTeamName.trim();
      }
      if (batchTeamInviteCode.trim()) {
        payload.team_invite_code = batchTeamInviteCode.trim().toUpperCase();
      }
    }

    setBatchSubmitting(true);
    setBatchResult(null);
    try {
      const r = await fetch(`${API}/api/admin/users/batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        let msg = "批量创建失败";
        try {
          const err = await r.json();
          if (err && err.detail) msg = String(err.detail);
        } catch {
          /* noop */
        }
        window.alert(msg);
        return;
      }
      const d = await r.json();
      const created = (d.users ?? []) as any[];
      const mapped: UserRecord[] = created.map((u: any): UserRecord => ({
        id: u.user_id,
        name: u.display_name ?? u.email ?? u.user_id,
        role: u.role as UserRole,
        email: u.email,
        teams: Array.isArray(u.team_names) ? (u.team_names as string[]).filter(Boolean) : [],
        status: (u.status as "active" | "disabled") ?? "active",
        last_login: u.last_login || "",
        project_count: typeof u.project_count === "number" ? u.project_count : 0,
      }));
      if (mapped.length) {
        setUsers((prev) => [...prev, ...mapped]);
      }
      setBatchResult({
        count: Number(d.count ?? mapped.length),
        passwords: Array.isArray(d.passwords) ? d.passwords : [],
      });
      window.alert(`已创建 ${mapped.length} 个账号`);
    } catch {
      window.alert("批量创建失败，请稍后再试");
    } finally {
      setBatchSubmitting(false);
    }
  }

  const TABS: { id: AdminTab; label: string; icon: string }[] = [
    { id: "dashboard", label: "全局大盘", icon: "📊" },
    { id: "teachers", label: "教师表现", icon: "🏅" },
    { id: "interventions", label: "教学干预", icon: "🧭" },
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

              {/* Team quick navigation */}
              {teams.length > 0 && (
                <div className="admin-section">
                  <h3>团队一览（点击跳转到用户列表）</h3>
                  <div className="admin-filter-group">
                    {teams.map((t) => (
                      <button
                        key={t.team_id}
                        type="button"
                        className="admin-filter-btn"
                        onClick={() => {
                          setTeamFilter(t.team_id);
                          setGroupByTeam(true);
                          setTab("users");
                        }}
                      >
                        {t.team_name} ({t.members.length})
                      </button>
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
                <div className="admin-filter-group">
                  <select value={teamFilter} onChange={(e) => setTeamFilter(e.target.value)}>
                    <option value="">全部团队</option>
                    <option value="__no_team__">未加入团队</option>
                    {teams.map((t) => (
                      <option key={t.team_id} value={t.team_id}>{t.team_name}</option>
                    ))}
                  </select>
                  <label style={{ marginLeft: 8, fontSize: 12 }}>
                    <input
                      type="checkbox"
                      checked={groupByTeam}
                      onChange={(e) => setGroupByTeam(e.target.checked)}
                      style={{ marginRight: 4 }}
                    />
                    按团队分组
                  </label>
                </div>
                <button className="admin-add-btn" onClick={() => setShowAddUser(true)}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 5v14M5 12h14"/></svg>
                  添加用户
                </button>
                <button className="admin-add-btn" onClick={() => setShowBatchCreate(true)}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 5v14M5 12h14"/></svg>
                  批量创建
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
                    <label>初始密码 <input type="password" value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} placeholder="留空则自动生成" /></label>
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

              {showBatchCreate && (
                <div className="admin-add-form">
                  <h4>批量创建用户</h4>
                  <div className="admin-form-grid">
                    <label>用户身份
                      <select
                        value={batchRole}
                        onChange={(e) => {
                          const role = e.target.value as UserRole;
                          setBatchRole(role);
                          setBatchPrefix(role === "teacher" ? "tea" : "stu");
                        }}
                      >
                        <option value="student">学生</option>
                        <option value="teacher">教师</option>
                      </select>
                    </label>
                    <label>账号前缀
                      <input
                        value={batchPrefix}
                        onChange={(e) => setBatchPrefix(e.target.value)}
                        placeholder={batchRole === "teacher" ? "tea" : "stu"}
                      />
                    </label>
                    <label>起始序号
                      <input
                        type="number"
                        min={1}
                        value={batchStartIndex}
                        onChange={(e) => setBatchStartIndex(Number(e.target.value) || 1)}
                      />
                    </label>
                    <label>创建数量
                      <input
                        type="number"
                        min={1}
                        max={500}
                        value={batchCount}
                        onChange={(e) => setBatchCount(Number(e.target.value) || 1)}
                      />
                    </label>
                    <label>默认密码后缀
                      <input
                        value={batchPasswordSuffix}
                        onChange={(e) => setBatchPasswordSuffix(e.target.value)}
                        placeholder="默认 123（实际密码 = 账号 + 后缀)"
                      />
                    </label>
                    {batchRole === "student" && (
                      <label>加入团队邀请码（可选）
                        <input
                          value={batchInviteCode}
                          onChange={(e) => setBatchInviteCode(e.target.value.toUpperCase())}
                          placeholder="如 7EISTH，留空则不自动加入团队"
                        />
                      </label>
                    )}
                    {batchRole === "teacher" && (
                      <>
                        <label>新建团队名称（可选）
                          <input
                            value={batchTeamName}
                            onChange={(e) => setBatchTeamName(e.target.value)}
                            placeholder="如 挑战杯指导一组"
                          />
                        </label>
                        <label>团队邀请码（可选）
                          <input
                            value={batchTeamInviteCode}
                            onChange={(e) => setBatchTeamInviteCode(e.target.value.toUpperCase())}
                            placeholder="如 ABC123；留空则自动生成"
                          />
                        </label>
                      </>
                    )}
                  </div>
                  <div className="admin-form-preview" style={{ marginTop: 8, fontSize: 12 }}>
                    <span>账号预览：</span>
                    <span style={{ fontFamily: "monospace" }}>{`${batchPrefix}${String(batchStartIndex).padStart(3, "0")}`}</span>
                    {batchCount > 1 && (
                      <>
                        <span style={{ margin: "0 4px" }}> ~ </span>
                        <span style={{ fontFamily: "monospace" }}>{`${batchPrefix}${String(batchStartIndex + batchCount - 1).padStart(3, "0")}`}</span>
                      </>
                    )}
                    <span style={{ marginLeft: 12 }}>
                      密码示例：
                      <span style={{ fontFamily: "monospace" }}>{`${batchPrefix}${String(batchStartIndex).padStart(3, "0")}${batchPasswordSuffix || "123"}`}</span>
                    </span>
                  </div>
                  {batchResult && (
                    <div className="admin-form-result" style={{ marginTop: 8, fontSize: 12 }}>
                      <strong>已创建 {batchResult.count} 个账号</strong>
                      {Array.isArray(batchResult.passwords) && batchResult.passwords.length > 0 && (
                        <ul style={{ marginTop: 4 }}>
                          {batchResult.passwords.slice(0, 10).map((row: any) => (
                            <li key={row.user_id || row.email}>{row.email} / {row.password}</li>
                          ))}
                          {batchResult.passwords.length > 10 && (
                            <li>… 共 {batchResult.passwords.length} 条，只展示前 10 条</li>
                          )}
                        </ul>
                      )}
                    </div>
                  )}
                  <div className="admin-form-actions">
                    <button className="admin-btn-primary" onClick={batchCreateUsers} disabled={batchSubmitting}>
                      {batchSubmitting ? "创建中…" : "开始批量创建"}
                    </button>
                    <button
                      className="admin-btn-secondary"
                      onClick={() => {
                        setShowBatchCreate(false);
                        setBatchResult(null);
                      }}
                    >
                      关闭
                    </button>
                  </div>
                </div>
              )}

              {groupByTeam ? (
                <div className="admin-team-groups">
                  {(() => {
                    const teamsForView = teamFilter && teamFilter !== "__no_team__"
                      ? teams.filter((t) => t.team_id === teamFilter)
                      : teams;
                    const memberIdsAll = new Set<string>();
                    for (const t of teams) {
                      if (t.teacher_id) memberIdsAll.add(t.teacher_id);
                      for (const m of t.members) memberIdsAll.add(m.user_id);
                    }
                    const unassignedUsers = (!teamFilter || teamFilter === "__no_team__")
                      ? baseUsers.filter((u) => !memberIdsAll.has(u.id))
                      : [];
                    return (
                      <>
                        {teamsForView.map((t) => {
                          const ids = new Set<string>();
                          if (t.teacher_id) ids.add(t.teacher_id);
                          for (const m of t.members) ids.add(m.user_id);
                          const teamUsers = baseUsers.filter((u) => ids.has(u.id));
                          if (teamUsers.length === 0) return null;
                          return (
                            <div key={t.team_id} className="admin-section">
                              <div className="admin-panel-header" style={{ marginBottom: 8 }}>
                                <h3>团队：{t.team_name}</h3>
                                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                                  <span style={{ fontSize: 12, color: "var(--muted, #888)" }}>负责人：{t.teacher_name || t.teacher_id || "-"}</span>
                                  <button
                                    type="button"
                                    className="admin-sm-btn"
                                    onClick={() => renameTeam(t.team_id, t.team_name, t.teacher_id)}
                                  >
                                    重命名
                                  </button>
                                </div>
                              </div>
                              <div className="admin-table">
                                <div className="admin-table-header">
                                  <span>用户ID</span><span>姓名</span><span>角色</span><span>邮箱</span><span>团队</span><span>状态</span><span>最后登录</span><span>操作</span>
                                </div>
                                {teamUsers.map((u) => renderUserRow(u, t))}
                              </div>
                            </div>
                          );
                        })}
                        {unassignedUsers.length > 0 && (
                          <div className="admin-section">
                            <h3>未加入任何团队</h3>
                            <div className="admin-table">
                              <div className="admin-table-header">
                                <span>用户ID</span><span>姓名</span><span>角色</span><span>邮箱</span><span>团队</span><span>状态</span><span>最后登录</span><span>操作</span>
                              </div>
                              {unassignedUsers.map((u) => renderUserRow(u))}
                            </div>
                          </div>
                        )}
                      </>
                    );
                  })()}
                </div>
              ) : (
                <div className="admin-table">
                  <div className="admin-table-header">
                    <span>用户ID</span><span>姓名</span><span>角色</span><span>邮箱</span><span>团队</span><span>状态</span><span>最后登录</span><span>操作</span>
                  </div>
                  {filteredUsers.map((u) => renderUserRow(u))}
                </div>
              )}

              <div className="admin-user-stats">
                <span>共 {users.length} 个用户</span>
                <span>学生 {users.filter((u) => u.role === "student").length}</span>
                <span>教师 {users.filter((u) => u.role === "teacher").length}</span>
                <span>管理员 {users.filter((u) => u.role === "admin").length}</span>
              </div>
            </div>
          )}

          {/* ── Teacher Performance ── */}
          {tab === "teachers" && (
            <div className="admin-panel fade-up">
              <div className="admin-panel-header">
                <h2>教师表现大盘</h2>
                <span className="admin-panel-desc">按教师维度聚合团队、学生与项目质量指标</span>
              </div>

              <div className="admin-kpi-grid">
                <div className="admin-kpi">
                  <div className="admin-kpi-icon">👩‍🏫</div>
                  <div className="admin-kpi-content">
                    <span className="admin-kpi-label">教师人数</span>
                    <strong className="admin-kpi-value">{teachers.length}</strong>
                  </div>
                </div>
                <div className="admin-kpi">
                  <div className="admin-kpi-icon">👥</div>
                  <div className="admin-kpi-content">
                    <span className="admin-kpi-label">覆盖学生</span>
                    <strong className="admin-kpi-value">{teachers.reduce((s, t) => s + t.student_count, 0)}</strong>
                  </div>
                </div>
                <div className="admin-kpi">
                  <div className="admin-kpi-icon">📈</div>
                  <div className="admin-kpi-content">
                    <span className="admin-kpi-label">平均得分（Top 3）</span>
                    <strong className="admin-kpi-value">
                      {teachers.length > 0
                        ? (Math.round((sortedTeachers.slice(0, 3).reduce((s, t) => s + t.avg_score, 0) / Math.max(1, Math.min(3, sortedTeachers.length))) * 10) / 10)
                        : "—"}
                    </strong>
                  </div>
                </div>
                <div className="admin-kpi">
                  <div className="admin-kpi-icon">🛡️</div>
                  <div className="admin-kpi-content">
                    <span className="admin-kpi-label">干预覆盖率中位数</span>
                    <strong className="admin-kpi-value">
                      {teachers.length > 0
                        ? (() => {
                            const vals = [...teachers.map((t) => t.intervention_coverage)].sort((a, b) => a - b);
                            const mid = Math.floor(vals.length / 2);
                            return vals.length % 2 === 0 ? ((vals[mid - 1] + vals[mid]) / 2).toFixed(1) : vals[mid].toFixed(1);
                          })()
                        : "—"}
                      %
                    </strong>
                  </div>
                </div>
              </div>

              <div className="admin-user-toolbar" style={{ marginTop: 16 }}>
                <div className="admin-filter-group">
                  <span style={{ fontSize: 12, marginRight: 8 }}>排序：</span>
                  <button
                    className={`admin-filter-btn ${teacherSortKey === "rank" ? "active" : ""}`}
                    onClick={() => setTeacherSortKey("rank")}
                  >
                    综合排名
                  </button>
                  <button
                    className={`admin-filter-btn ${teacherSortKey === "avg_score" ? "active" : ""}`}
                    onClick={() => setTeacherSortKey("avg_score")}
                  >
                    平均分
                  </button>
                  <button
                    className={`admin-filter-btn ${teacherSortKey === "risk_rate" ? "active" : ""}`}
                    onClick={() => setTeacherSortKey("risk_rate")}
                  >
                    风险率
                  </button>
                  <button
                    className={`admin-filter-btn ${teacherSortKey === "active_students" ? "active" : ""}`}
                    onClick={() => setTeacherSortKey("active_students")}
                  >
                    活跃学生数
                  </button>
                  <button
                    className={`admin-filter-btn ${teacherSortKey === "intervention_coverage" ? "active" : ""}`}
                    onClick={() => setTeacherSortKey("intervention_coverage")}
                  >
                    干预覆盖率
                  </button>
                </div>
              </div>

              {sortedTeachers.length > 0 ? (
                <>
                  <div className="admin-vuln-cards" style={{ marginTop: 16 }}>
                    {sortedTeachers.slice(0, 3).map((t, i) => (
                      <div key={t.teacher_id} className={`admin-vuln-card rank-${i + 1}`}>
                        <div className="admin-vuln-rank">Top {i + 1}</div>
                        <div className="admin-vuln-name">{t.name}</div>
                        <div className="admin-vuln-count">团队 {t.team_count} 个 · 学生 {t.student_count} 人</div>
                        <div className="admin-vuln-bar">
                          <div
                            className="admin-vuln-fill"
                            style={{ width: `${Math.min(100, (t.avg_score / 10) * 100)}%` }}
                          />
                        </div>
                        <div className="admin-vuln-pct">平均分 {t.avg_score} · 风险率 {t.risk_rate}%</div>
                      </div>
                    ))}
                  </div>

                  <div className="admin-section">
                    <h3>教师表现明细</h3>
                    <div className="admin-table">
                      <div className="admin-table-header">
                        <span>排名</span><span>教师</span><span>团队数</span><span>覆盖学生</span><span>活跃学生</span><span>平均分</span><span>风险率</span><span>干预覆盖率</span><span>最近活跃</span>
                      </div>
                      {sortedTeachers.map((t) => (
                        <div key={t.teacher_id} className="admin-table-row">
                          <span className="admin-cell-primary">#{t.rank}</span>
                          <span>
                            <div>{t.name}</div>
                            <div className="admin-cell-muted" style={{ fontSize: 11 }}>{t.email}</div>
                          </span>
                          <span>{t.team_count}</span>
                          <span>{t.student_count}</span>
                          <span>{t.active_students}</span>
                          <span>
                            <span className={`admin-score ${t.avg_score >= 7 ? "good" : t.avg_score >= 4 ? "warn" : "danger"}`}>
                              {t.avg_score}
                            </span>
                          </span>
                          <span>{t.risk_rate}%</span>
                          <span>{t.intervention_coverage}%</span>
                          <span className="admin-cell-muted">{t.last_active || "—"}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              ) : (
                <div className="admin-empty">
                  <div className="admin-empty-icon">👩‍🏫</div>
                  <p>暂无教师聚合数据。待有学生项目与团队数据后，将自动生成教师表现大盘。</p>
                </div>
              )}
            </div>
          )}

          {/* ── Teaching Interventions (Admin) ── */}
          {tab === "interventions" && (
            <div className="admin-panel fade-up">
              <div className="admin-panel-header">
                <h2>教学干预监控</h2>
                <span className="admin-panel-desc">从学校视角总览各教师的教学干预任务与覆盖范围</span>
              </div>

              {interventionSummary ? (
                <>
                  <div className="admin-kpi-grid">
                    <div className="admin-kpi">
                      <div className="admin-kpi-icon">📝</div>
                      <div className="admin-kpi-content">
                        <span className="admin-kpi-label">干预任务总数</span>
                        <strong className="admin-kpi-value">{interventionSummary.total_interventions}</strong>
                      </div>
                    </div>
                    <div className="admin-kpi">
                      <div className="admin-kpi-icon">👩‍🏫</div>
                      <div className="admin-kpi-content">
                        <span className="admin-kpi-label">参与教师数</span>
                        <strong className="admin-kpi-value">{interventionSummary.teacher_count}</strong>
                      </div>
                    </div>
                    <div className="admin-kpi">
                      <div className="admin-kpi-icon">👨‍🎓</div>
                      <div className="admin-kpi-content">
                        <span className="admin-kpi-label">被干预学生数</span>
                        <strong className="admin-kpi-value">{interventionSummary.student_count}</strong>
                      </div>
                    </div>
                    <div className="admin-kpi">
                      <div className="admin-kpi-icon">✅</div>
                      <div className="admin-kpi-content">
                        <span className="admin-kpi-label">已完成干预</span>
                        <strong className="admin-kpi-value">{interventionSummary.completed_count}</strong>
                      </div>
                    </div>
                  </div>

                  <div className="admin-section">
                    <h3>教师干预聚合表</h3>
                    <div className="admin-table">
                      <div className="admin-table-header">
                        <span>教师</span><span>总干预数</span><span>草稿</span><span>已审批</span><span>已发送</span><span>已查看</span><span>已完成</span><span>已归档</span><span>覆盖学生数</span>
                      </div>
                      {interventionTeachers.map((t) => (
                        <div key={t.teacher_id} className="admin-table-row">
                          <span>
                            <div className="admin-cell-primary">{t.name}</div>
                            <div className="admin-cell-muted" style={{ fontSize: 11 }}>{t.email}</div>
                          </span>
                          <span>{t.total_interventions}</span>
                          <span>{t.draft}</span>
                          <span>{t.approved}</span>
                          <span>{t.sent}</span>
                          <span>{t.viewed}</span>
                          <span>{t.completed}</span>
                          <span>{t.archived}</span>
                          <span>{t.student_count}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="admin-section">
                    <h3>最近干预记录</h3>
                    {recentInterventions.length > 0 ? (
                      <div className="admin-table">
                        <div className="admin-table-header">
                          <span>时间</span><span>教师</span><span>学生</span><span>标题</span><span>状态</span><span>作用范围</span><span>项目ID</span>
                        </div>
                        {recentInterventions.map((item) => {
                          const statusKey = (item.status || "draft") as InterventionStatus;
                          const statusLabel = INTERVENTION_STATUS_LABEL[statusKey] ?? item.status;
                          const statusClass =
                            statusKey === "completed"
                              ? "good"
                              : statusKey === "sent" || statusKey === "viewed" || statusKey === "approved"
                                ? "warn"
                                : "";
                          const timeText = (item.updated_at || item.created_at || "").slice(0, 16);
                          let scopeText = "-";
                          if (item.scope_type === "team") scopeText = `团队 ${item.scope_id}`;
                          else if (item.scope_type === "student") scopeText = `学生 ${item.scope_id}`;
                          else if (item.scope_type === "project") scopeText = `项目 ${item.scope_id}`;
                          return (
                            <div key={item.intervention_id} className="admin-table-row">
                              <span className="admin-cell-muted">{timeText}</span>
                              <span>
                                <div className="admin-cell-primary">{item.teacher_name}</div>
                                <div className="admin-cell-muted" style={{ fontSize: 11 }}>{item.teacher_id}</div>
                              </span>
                              <span>
                                <div>{item.student_name}</div>
                                <div className="admin-cell-muted" style={{ fontSize: 11 }}>{item.student_id}</div>
                              </span>
                              <span>{item.title}</span>
                              <span>
                                <span className={`admin-status-dot ${statusClass}`} />
                                {statusLabel}
                              </span>
                              <span>{scopeText}</span>
                              <span className="admin-cell-muted">{item.project_id}</span>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="admin-empty">
                        <div className="admin-empty-icon">🧭</div>
                        <p>当前暂无教学干预记录。教师在教师端创建干预计划后，这里会自动汇总。</p>
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <div className="admin-empty">
                  <div className="admin-empty-icon">🧭</div>
                  <p>暂未统计到教学干预数据。待教师端开始批量下发干预任务后，这里将展示全局监控视图。</p>
                </div>
              )}
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
                    <span className="admin-kpi-label">涉及团队</span>
                    <strong className="admin-kpi-value">{projectTeamCount}</strong>
                  </div>
                </div>
              </div>

              {allProjects.length > 0 ? (
                <div className="admin-table">
                  <div className="admin-table-header">
                    <span>项目ID</span><span>学生</span><span>团队</span><span>评分</span><span>风险规则</span><span>提交时间</span>
                  </div>
                  {allProjects.map((p, i) => {
                    const studentUserId = getUserIdFromProjectId(p.project_id);
                    const studentName =
                      (studentUserId && studentNameByUserId[studentUserId])
                      || p.student_id
                      || studentUserId
                      || "未知学生";
                    const teamNamesForStudent = studentUserId ? userTeamNames[studentUserId] ?? [] : [];
                    const teamLabel = teamNamesForStudent.length ? teamNamesForStudent.join("、") : "未加入团队";
                    return (
                      <div key={i} className="admin-table-row">
                        <span className="admin-cell-primary">{p.project_id}</span>
                        <span>{studentName}</span>
                        <span>{teamLabel}</span>
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
                    );
                  })}
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

              {logStats && (
                <div className="admin-kpi-grid" style={{ marginBottom: 16 }}>
                  <div className="admin-kpi">
                    <div className="admin-kpi-icon">📡</div>
                    <div className="admin-kpi-content">
                      <span className="admin-kpi-label">总请求数</span>
                      <strong className="admin-kpi-value">{logStats.total_requests}</strong>
                    </div>
                  </div>
                  <div className="admin-kpi">
                    <div className="admin-kpi-icon">✅</div>
                    <div className="admin-kpi-content">
                      <span className="admin-kpi-label">成功请求</span>
                      <strong className="admin-kpi-value">{logStats.success_count}</strong>
                    </div>
                  </div>
                  <div className="admin-kpi">
                    <div className="admin-kpi-icon">⚠️</div>
                    <div className="admin-kpi-content">
                      <span className="admin-kpi-label">错误请求</span>
                      <strong className="admin-kpi-value">{logStats.error_count}</strong>
                    </div>
                  </div>
                  <div className="admin-kpi">
                    <div className="admin-kpi-icon">🚫</div>
                    <div className="admin-kpi-content">
                      <span className="admin-kpi-label">拦截次数</span>
                      <strong className="admin-kpi-value">{logStats.blocked_count}</strong>
                    </div>
                  </div>
                  <div className="admin-kpi">
                    <div className="admin-kpi-icon">⏱️</div>
                    <div className="admin-kpi-content">
                      <span className="admin-kpi-label">平均耗时 / P95</span>
                      <strong className="admin-kpi-value">{Math.round(logStats.avg_duration_ms)}ms / {Math.round(logStats.p95_duration_ms)}ms</strong>
                    </div>
                  </div>
                </div>
              )}

              <div className="admin-table">
                <div className="admin-table-header">
                  <span>时间</span><span>用户</span><span>操作类型</span><span>请求路径</span><span>详情</span><span>状态</span>
                </div>
                {accessLogs.map((log, i) => {
                  const roleLabel =
                    log.role === "student"
                      ? "学生"
                      : log.role === "teacher"
                      ? "教师"
                      : log.role === "admin"
                      ? "管理员"
                      : log.role
                      ? String(log.role)
                      : "";
                  const name =
                    (log.display_name && String(log.display_name)) ||
                    (log.user && String(log.user)) ||
                    (log.user_id && String(log.user_id)) ||
                    "";
                  const userLabel = roleLabel && name ? `${roleLabel} · ${name}` : name || log.user || "-";

                  const rawCode = (log as any).status_code;
                  const statusCode =
                    typeof rawCode === "number" ? rawCode : parseInt(String(rawCode ?? "0"), 10) || 0;
                  const statusStr = String(log.status || "").toUpperCase();
                  const isBlocked = statusStr === "BLOCKED" || statusCode === 403;
                  const isSuccess = !isBlocked && statusCode >= 200 && statusCode < 400 && statusStr === "OK";
                  const isError = !isBlocked && !isSuccess;

                  return (
                    <div key={i} className={`admin-table-row ${isBlocked ? "blocked" : ""}`}>
                      <span className="admin-cell-muted">{log.time}</span>
                      <span className="admin-cell-primary">{userLabel}</span>
                      <span>
                        <span className={`admin-log-action ${log.action === "UNAUTHORIZED" ? "danger" : ""}`}>
                          {log.action}
                        </span>
                      </span>
                      <span>{log.path || "-"}</span>
                      <span>{log.detail}</span>
                      <span>
                        {isBlocked ? (
                          <span className="admin-log-blocked">🚫 已拦截{statusCode ? ` (${statusCode})` : ""}</span>
                        ) : isError ? (
                          <span className="admin-log-error">⚠ 错误{statusCode ? ` (${statusCode})` : ""}</span>
                        ) : (
                          <span className="admin-log-ok">✓ 正常{statusCode ? ` (${statusCode})` : ""}</span>
                        )}
                      </span>
                    </div>
                  );
                })}
              </div>

              <div className="admin-log-summary">
                <span>总操作 {accessLogs.length} 条</span>
                <span className="admin-log-blocked-count">
                  越权拦截 {accessLogs.filter((l) => {
                    const rawCode = (l as any).status_code;
                    const statusCode =
                      typeof rawCode === "number" ? rawCode : parseInt(String(rawCode ?? "0"), 10) || 0;
                    const statusStr = String(l.status || "").toUpperCase();
                    return statusStr === "BLOCKED" || statusCode === 403;
                  }).length} 次
                </span>
              </div>

              {logStats && logStats.top_paths.length > 0 && (
                <div className="admin-section" style={{ marginTop: 16 }}>
                  <h3>热门 API 路径</h3>
                  <div className="admin-table">
                    <div className="admin-table-header">
                      <span>路径</span><span>请求数</span><span>平均耗时 (ms)</span><span>成功</span><span>错误</span><span>拦截</span>
                    </div>
                    {logStats.top_paths.map((p) => (
                      <div key={p.path} className="admin-table-row">
                        <span className="admin-cell-primary">{p.path}</span>
                        <span>{p.count}</span>
                        <span>{Math.round(p.avg_duration_ms)}</span>
                        <span>{p.success_count}</span>
                        <span>{p.error_count}</span>
                        <span>{p.blocked_count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </main>

        {showTeamManager && manageTeacherId && (() => {
          const teacherTeams = teams.filter((t) => t.teacher_id === manageTeacherId);
          return (
            <div
              style={{
                position: "fixed",
                inset: 0,
                backgroundColor: "rgba(0,0,0,0.45)",
                zIndex: 50,
                display: "flex",
                justifyContent: "center",
                alignItems: "center",
              }}
            >
              <div
                className="admin-panel fade-up"
                style={{
                  maxWidth: 720,
                  width: "90%",
                  maxHeight: "80vh",
                  overflow: "auto",
                  background: "var(--bg, #111)",
                  borderRadius: 8,
                  boxShadow: "0 12px 30px rgba(0,0,0,0.35)",
                  padding: 20,
                }}
              >
                <div className="admin-panel-header" style={{ marginBottom: 8 }}>
                  <h3>教师团队管理：{manageTeacherName || manageTeacherId}</h3>
                  <button
                    type="button"
                    className="admin-sm-btn"
                    onClick={closeTeacherTeamManager}
                  >
                    关闭
                  </button>
                </div>

                <div className="admin-add-form">
                  <h4>为该教师新建团队</h4>
                  <div className="admin-form-grid">
                    <label>团队名称
                      <input
                        value={newTeamName}
                        onChange={(e) => setNewTeamName(e.target.value)}
                        placeholder="如 挑战杯指导一组"
                      />
                    </label>
                    <label>团队邀请码（可选）
                      <input
                        value={newTeamInviteCode}
                        onChange={(e) => setNewTeamInviteCode(e.target.value.toUpperCase())}
                        placeholder="如 ABC123；留空则自动生成"
                      />
                    </label>
                  </div>
                  <div className="admin-form-actions">
                    <button
                      className="admin-btn-primary"
                      onClick={createTeacherTeam}
                      disabled={teamSubmitting}
                    >
                      {teamSubmitting ? "创建中…" : "创建团队"}
                    </button>
                    <button
                      className="admin-btn-secondary"
                      onClick={closeTeacherTeamManager}
                    >
                      关闭
                    </button>
                  </div>
                </div>

                <div className="admin-section" style={{ marginTop: 12 }}>
                  <h4>该教师负责的团队</h4>
                  {teacherTeams.length > 0 ? (
                    <div className="admin-table">
                      <div className="admin-table-header">
                        <span>团队名称</span>
                        <span>邀请码</span>
                        <span>成员数</span>
                        <span>操作</span>
                      </div>
                      {teacherTeams.map((t) => (
                        <div key={t.team_id} className="admin-table-row">
                          <span className="admin-cell-primary">{t.team_name}</span>
                          <span className="admin-cell-muted">{t.invite_code || "—"}</span>
                          <span>{t.members.length}</span>
                          <span className="admin-action-group">
                            <button
                              type="button"
                              className="admin-sm-btn"
                              onClick={() => openTeamMemberManager(t.team_id)}
                              title="编辑成员"
                            >
                              成员
                            </button>
                            <button
                              type="button"
                              className="admin-sm-btn danger"
                              onClick={() => deleteTeacherTeam(t.team_id, t.teacher_id)}
                            >
                              删除
                            </button>
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="admin-empty">
                      <div className="admin-empty-icon">👥</div>
                      <p>该教师当前还没有负责的团队。</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })()}

        {editTeamId && (() => {
          const team = teams.find((t) => t.team_id === editTeamId);
          if (!team) return null;
          const members = team.members ?? [];
          return (
            <div
              style={{
                position: "fixed",
                inset: 0,
                backgroundColor: "rgba(0,0,0,0.45)",
                zIndex: 60,
                display: "flex",
                justifyContent: "center",
                alignItems: "center",
              }}
            >
              <div
                className="admin-panel fade-up"
                style={{
                  maxWidth: 720,
                  width: "90%",
                  maxHeight: "80vh",
                  overflow: "auto",
                  background: "var(--bg, #111)",
                  borderRadius: 8,
                  boxShadow: "0 12px 30px rgba(0,0,0,0.45)",
                  padding: 20,
                }}
              >
                <div className="admin-panel-header" style={{ marginBottom: 8 }}>
                  <h3>团队成员管理：{team.team_name}</h3>
                  <button
                    type="button"
                    className="admin-sm-btn"
                    onClick={closeTeamMemberManager}
                  >
                    关闭
                  </button>
                </div>

                <div className="admin-add-form">
                  <h4>添加团队成员</h4>
                  <div className="admin-form-grid">
                    <label>成员用户ID
                      <input
                        value={newMemberUserId}
                        onChange={(e) => setNewMemberUserId(e.target.value)}
                        placeholder="如 student-001 或 stu001"
                      />
                    </label>
                    <label>当前团队邀请码
                      <input
                        value={team.invite_code || "—"}
                        readOnly
                      />
                    </label>
                  </div>
                  {newMemberUserId.trim() && (
                    <div style={{ fontSize: 12, marginTop: 4 }}>
                      {(() => {
                        const uid = newMemberUserId.trim();
                        const candidate = users.find((u) => u.id === uid);
                        if (!candidate) {
                          return <span className="admin-cell-muted">未在当前用户列表中找到该ID，对应用户需已存在。</span>;
                        }
                        return (
                          <span className="admin-cell-muted">
                            将添加：{candidate.name || candidate.email}（{candidate.id}）
                          </span>
                        );
                      })()}
                    </div>
                  )}
                  <div className="admin-form-actions">
                    <button
                      className="admin-btn-primary"
                      onClick={addMemberToTeam}
                      disabled={memberSubmitting}
                    >
                      {memberSubmitting ? "添加中…" : "添加成员"}
                    </button>
                    <button
                      className="admin-btn-secondary"
                      onClick={closeTeamMemberManager}
                    >
                      关闭
                    </button>
                  </div>
                </div>

                <div className="admin-section" style={{ marginTop: 12 }}>
                  <h4>现有成员</h4>
                  {members.length > 0 ? (
                    <div className="admin-table">
                      <div className="admin-table-header">
                        <span>用户ID</span>
                        <span>姓名</span>
                        <span>加入时间</span>
                        <span>操作</span>
                      </div>
                      {members.map((m) => {
                        const name = studentNameByUserId[m.user_id] || m.user_id;
                        const joined = (m.joined_at || "").slice(0, 19);
                        return (
                          <div key={m.user_id} className="admin-table-row">
                            <span className="admin-cell-primary">{m.user_id}</span>
                            <span>{name}</span>
                            <span className="admin-cell-muted">{joined || "—"}</span>
                            <span>
                              <button
                                type="button"
                                className="admin-sm-btn danger"
                                onClick={() => removeMemberFromTeam(team.team_id, team.teacher_id, m.user_id)}
                              >
                                移除
                              </button>
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="admin-empty">
                      <div className="admin-empty-icon">👥</div>
                      <p>当前团队还没有成员。</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })()}
      </div>

      <div className="admin-footer-disclaimer">
        ⚠ AI生成，仅供参考 | VentureAgent 教务管理系统
      </div>
    </div>
  );
}
