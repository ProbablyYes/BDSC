"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8787").trim().replace(/\/+$/, "");
type ViewMode = "dashboard" | "compare" | "evidence" | "agent";

export default function TeacherPage() {
  const [viewMode, setViewMode] = useState<ViewMode>("dashboard");
  const [projectId, setProjectId] = useState("demo-project-001");
  const [teacherId, setTeacherId] = useState("teacher-001");
  const [feedback, setFeedback] = useState("");
  const [response, setResponse] = useState("等待教师端数据...");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [dashboard, setDashboard] = useState<any>(null);
  const [evidence, setEvidence] = useState<any>(null);
  const [compareData, setCompareData] = useState<any>(null);
  const [classId, setClassId] = useState("");
  const [cohortId, setCohortId] = useState("");

  async function loadDashboard() {
    setLoading(true);
    const q = categoryFilter ? `?category=${encodeURIComponent(categoryFilter)}` : "";
    const resp = await fetch(`${API_BASE}/api/teacher/dashboard${q}`);
    const data = await resp.json();
    setDashboard(data.data);
    if (data?.data?.error) {
      setResponse(`dashboard_error: ${data.data.error}`);
    } else {
      setResponse(JSON.stringify(data, null, 2));
    }
    setLoading(false);
  }

  async function loadProjectEvidence() {
    setLoading(true);
    const resp = await fetch(`${API_BASE}/api/teacher/project/${encodeURIComponent(projectId)}/evidence`);
    const data = await resp.json();
    setEvidence(data.data);
    if (data?.data?.error) {
      setResponse(`evidence_error: ${data.data.error}`);
    } else {
      setResponse(JSON.stringify(data, null, 2));
    }
    setLoading(false);
  }

  async function loadCompare() {
    setLoading(true);
    const params = new URLSearchParams();
    if (classId.trim()) params.set("class_id", classId.trim());
    if (cohortId.trim()) params.set("cohort_id", cohortId.trim());
    const query = params.toString();
    const resp = await fetch(`${API_BASE}/api/teacher/compare${query ? `?${query}` : ""}`);
    const data = await resp.json();
    setCompareData(data);
    if (data?.baseline?.error) {
      setResponse(`compare_error: ${data.baseline.error}`);
    } else {
      setResponse(JSON.stringify(data, null, 2));
    }
    setLoading(false);
  }

  async function submitFeedback(event: FormEvent) {
    event.preventDefault();
    const resp = await fetch(`${API_BASE}/api/teacher-feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: projectId,
        teacher_id: teacherId,
        comment: feedback,
        focus_tags: ["evidence", "feasibility"],
      }),
    });
    const data = await resp.json();
    setResponse(JSON.stringify(data, null, 2));
  }

  async function runAgent() {
    const resp = await fetch(`${API_BASE}/api/agent/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: projectId,
        agent_type: "instructor_assistant",
      }),
    });
    const data = await resp.json();
    setResponse(JSON.stringify(data, null, 2));
  }

  useEffect(() => {
    loadDashboard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const maxCategoryProjects = useMemo(() => {
    const rows = dashboard?.category_distribution ?? [];
    return Math.max(1, ...rows.map((r: any) => Number(r.projects || 0)));
  }, [dashboard]);

  const maxRuleProjects = useMemo(() => {
    const rows = dashboard?.top_risk_rules ?? [];
    return Math.max(1, ...rows.map((r: any) => Number(r.projects || 0)));
  }, [dashboard]);

  return (
    <main className="page">
      <section className="hero fade-up">
        <div className="nav">
          <Link href="/" className="nav-link">
            返回首页
          </Link>
          <Link href="/student" className="nav-link">
            去学生端
          </Link>
        </div>
        <h1>教师端控制台</h1>
        <p>教师画像看板 + 证据链核查 + 智能体建议。先看全局，再点到具体项目干预。</p>
      </section>

      <section className="grid">
        <article className="card glow">
          <h2>控制面板</h2>
          <div className="pill-row">
            <button type="button" className={viewMode === "dashboard" ? "pill active" : "pill"} onClick={() => setViewMode("dashboard")}>
              教师画像
            </button>
            <button type="button" className={viewMode === "compare" ? "pill active" : "pill"} onClick={() => setViewMode("compare")}>
              基线对比
            </button>
            <button type="button" className={viewMode === "evidence" ? "pill active" : "pill"} onClick={() => setViewMode("evidence")}>
              项目证据链
            </button>
            <button type="button" className={viewMode === "agent" ? "pill active" : "pill"} onClick={() => setViewMode("agent")}>
              智能体建议
            </button>
          </div>

          <label>类别筛选（可空）</label>
          <input value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)} placeholder="例如：医疗健康" />
          <label>项目 ID</label>
          <input value={projectId} onChange={(e) => setProjectId(e.target.value)} />
          <label>教师 ID</label>
          <input value={teacherId} onChange={(e) => setTeacherId(e.target.value)} />
          <label>班级 ID（可空）</label>
          <input value={classId} onChange={(e) => setClassId(e.target.value)} placeholder="例如：2026A" />
          <label>届别/学期 ID（可空）</label>
          <input value={cohortId} onChange={(e) => setCohortId(e.target.value)} placeholder="例如：2026-Spring" />
          <div className="row-actions">
            <button type="button" onClick={loadDashboard}>刷新画像</button>
            <button type="button" onClick={loadCompare}>加载对比</button>
            <button type="button" onClick={loadProjectEvidence}>加载证据</button>
            <button type="button" onClick={runAgent}>运行教师智能体</button>
          </div>
          <p className="hint">{loading ? "加载中..." : "已就绪，可切换视图查看图谱洞察。"}</p>
        </article>

        <article className="card">
          <h2>写回反馈</h2>
          <form onSubmit={submitFeedback}>
            <label>反馈内容</label>
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="例如：先修正渠道可达性，再补充支付意愿证据。"
            />
            <button type="submit">提交反馈</button>
          </form>
        </article>

        {viewMode === "dashboard" && (
          <article className="card full fade-up">
            <h2>教师画像看板</h2>
            {dashboard?.error && <p className="hint">图数据读取失败：{dashboard.error}</p>}
            <div className="kpi-grid">
              <div className="kpi">
                <span>项目总数</span>
                <strong>{dashboard?.overview?.total_projects ?? "-"}</strong>
              </div>
              <div className="kpi">
                <span>证据总数</span>
                <strong>{dashboard?.overview?.total_evidence ?? "-"}</strong>
              </div>
              <div className="kpi">
                <span>规则命中</span>
                <strong>{dashboard?.overview?.total_rule_hits ?? "-"}</strong>
              </div>
            </div>

            <div className="viz-grid">
              <div className="viz-card">
                <h3>类别分布</h3>
                {(dashboard?.category_distribution ?? []).map((row: any) => (
                  <div key={row.category} className="bar-row" onClick={() => setCategoryFilter(row.category)}>
                    <span>{row.category}</span>
                    <div className="bar-track">
                      <div className="bar-fill" style={{ width: `${(Number(row.projects || 0) / maxCategoryProjects) * 100}%` }} />
                    </div>
                    <em>{row.projects}</em>
                  </div>
                ))}
              </div>
              <div className="viz-card">
                <h3>Top 风险规则</h3>
                {(dashboard?.top_risk_rules ?? []).map((row: any) => (
                  <div key={row.rule} className="bar-row">
                    <span>{row.rule}</span>
                    <div className="bar-track danger">
                      <div className="bar-fill danger" style={{ width: `${(Number(row.projects || 0) / maxRuleProjects) * 100}%` }} />
                    </div>
                    <em>{row.projects}</em>
                  </div>
                ))}
              </div>
            </div>

            <h3>高风险项目</h3>
            <div className="table-like">
              {(dashboard?.high_risk_projects ?? []).slice(0, 10).map((row: any) => (
                <button
                  key={row.project_id}
                  className="project-item"
                  onClick={() => {
                    setProjectId(row.project_id);
                    setViewMode("evidence");
                    loadProjectEvidence();
                  }}
                >
                  <span>{row.project_name || row.project_id}</span>
                  <span>{row.category}</span>
                  <span>风险{row.risk_count}</span>
                </button>
              ))}
            </div>
          </article>
        )}

        {viewMode === "compare" && (
          <article className="card full fade-up">
            <h2>市场/历史基线 vs 本班现状</h2>
            <div className="kpi-grid">
              <div className="kpi">
                <span>基线风险强度</span>
                <strong>{compareData?.baseline?.avg_rule_hits_per_project ?? "-"}</strong>
              </div>
              <div className="kpi">
                <span>本班风险强度</span>
                <strong>{compareData?.current_class?.avg_rule_hits_per_submission ?? "-"}</strong>
              </div>
              <div className="kpi">
                <span>风险强度差值</span>
                <strong>{compareData?.comparison?.risk_intensity_delta ?? "-"}</strong>
              </div>
            </div>
            <div className="kpi-grid">
              <div className="kpi">
                <span>基线高风险占比</span>
                <strong>{compareData?.baseline?.high_risk_ratio ?? "-"}</strong>
              </div>
              <div className="kpi">
                <span>本班高风险占比</span>
                <strong>{compareData?.current_class?.high_risk_ratio ?? "-"}</strong>
              </div>
              <div className="kpi">
                <span>本班 Rubric 均分</span>
                <strong>{compareData?.current_class?.avg_rubric_score ?? "-"}</strong>
              </div>
            </div>

            <div className="viz-grid">
              <div className="viz-card">
                <h3>基线 Top 风险规则</h3>
                {(compareData?.baseline?.top_risk_rules ?? []).map((row: any) => (
                  <div key={`baseline-${row.rule}`} className="bar-row">
                    <span>{row.rule}</span>
                    <div className="bar-track">
                      <div className="bar-fill" style={{ width: `${Math.max(3, Number(row.ratio || 0) * 100)}%` }} />
                    </div>
                    <em>{row.project_count}</em>
                  </div>
                ))}
              </div>
              <div className="viz-card">
                <h3>本班 Top 风险规则</h3>
                {(compareData?.current_class?.top_risk_rules ?? []).map((row: any) => (
                  <div key={`class-${row.rule}`} className="bar-row">
                    <span>{row.rule}</span>
                    <div className="bar-track danger">
                      <div className="bar-fill danger" style={{ width: `${Math.max(3, Number(row.ratio || 0) * 100)}%` }} />
                    </div>
                    <em>{row.project_count}</em>
                  </div>
                ))}
              </div>
            </div>

            <h3>自动干预建议</h3>
            <div className="table-like">
              {(compareData?.recommendations ?? []).map((item: string, idx: number) => (
                <div key={`rec-${idx}`} className="insight-item">
                  {item}
                </div>
              ))}
            </div>
          </article>
        )}

        {viewMode === "evidence" && (
          <article className="card full fade-up">
            <h2>项目证据链</h2>
            {evidence?.project ? (
              <>
                <p className="hint">
                  {evidence.project.project_name} | {evidence.project.category} | 置信度 {evidence.project.confidence}
                </p>
                <div className="table-like">
                  {(evidence.evidence ?? []).map((e: any) => (
                    <div key={e.evidence_id} className="evidence-item">
                      <strong>{e.type}</strong>
                      <p>{e.quote}</p>
                      <em>{e.source_unit}</em>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p className="hint">输入项目 ID 后点击“加载证据”。</p>
            )}
          </article>
        )}

        {viewMode === "agent" && (
          <article className="card full fade-up">
            <h2>教师智能体输出</h2>
            <pre>{response}</pre>
          </article>
        )}
      </section>
    </main>
  );
}
