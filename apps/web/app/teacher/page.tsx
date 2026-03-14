"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8787").trim().replace(/\/+$/, "");
type Tab = "overview" | "submissions" | "compare" | "evidence" | "report" | "feedback";

export default function TeacherPage() {
  const [tab, setTab] = useState<Tab>("overview");
  const [projectId, setProjectId] = useState("demo-project-001");
  const [teacherId, setTeacherId] = useState("teacher-001");
  const [classId, setClassId] = useState("");
  const [cohortId, setCohortId] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [loading, setLoading] = useState(false);

  const [dashboard, setDashboard] = useState<any>(null);
  const [submissions, setSubmissions] = useState<any[]>([]);
  const [compareData, setCompareData] = useState<any>(null);
  const [evidence, setEvidence] = useState<any>(null);
  const [report, setReport] = useState("");
  const [reportSnapshot, setReportSnapshot] = useState<any>(null);

  const [feedbackText, setFeedbackText] = useState("");
  const [feedbackTags, setFeedbackTags] = useState("evidence,feasibility");
  const [feedbackResult, setFeedbackResult] = useState("");

  const [selectedProject, setSelectedProject] = useState("");
  const [expandedSubmission, setExpandedSubmission] = useState<number | null>(null);

  async function api(path: string, opts?: RequestInit) {
    const r = await fetch(`${API}${path}`, opts);
    return r.json();
  }

  async function loadDashboard() {
    setLoading(true);
    const q = categoryFilter ? `?category=${encodeURIComponent(categoryFilter)}` : "";
    const data = await api(`/api/teacher/dashboard${q}`);
    setDashboard(data.data);
    setLoading(false);
  }

  async function loadSubmissions() {
    setLoading(true);
    const params = new URLSearchParams();
    if (classId.trim()) params.set("class_id", classId.trim());
    if (cohortId.trim()) params.set("cohort_id", cohortId.trim());
    const q = params.toString();
    const data = await api(`/api/teacher/submissions${q ? `?${q}` : ""}`);
    setSubmissions(data.submissions ?? []);
    setLoading(false);
  }

  async function loadCompare() {
    setLoading(true);
    const params = new URLSearchParams();
    if (classId.trim()) params.set("class_id", classId.trim());
    if (cohortId.trim()) params.set("cohort_id", cohortId.trim());
    const q = params.toString();
    const data = await api(`/api/teacher/compare${q ? `?${q}` : ""}`);
    setCompareData(data);
    setLoading(false);
  }

  async function loadEvidence(pid: string) {
    setLoading(true);
    setSelectedProject(pid);
    const data = await api(`/api/teacher/project/${encodeURIComponent(pid)}/evidence`);
    setEvidence(data.data);
    setTab("evidence");
    setLoading(false);
  }

  async function generateReport() {
    setLoading(true);
    const params = new URLSearchParams();
    if (classId.trim()) params.set("class_id", classId.trim());
    if (cohortId.trim()) params.set("cohort_id", cohortId.trim());
    const q = params.toString();
    const data = await api(`/api/teacher/generate-report${q ? `?${q}` : ""}`, { method: "POST" });
    setReport(data.report ?? "");
    setReportSnapshot(data.snapshot ?? null);
    setTab("report");
    setLoading(false);
  }

  async function submitFeedback(e: FormEvent) {
    e.preventDefault();
    const targetPid = selectedProject || projectId;
    if (!feedbackText.trim() || feedbackText.trim().length < 5) return;
    const data = await api("/api/teacher-feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: targetPid,
        teacher_id: teacherId,
        comment: feedbackText.trim(),
        focus_tags: feedbackTags.split(",").map((t) => t.trim()).filter(Boolean),
      }),
    });
    setFeedbackResult(`反馈已保存 (ID: ${data.feedback_id ?? "?"}) → 学生端可实时看到`);
    setFeedbackText("");
  }

  useEffect(() => { loadDashboard(); }, []);

  const maxCat = useMemo(() => Math.max(1, ...(dashboard?.category_distribution ?? []).map((r: any) => Number(r.projects || 0))), [dashboard]);
  const maxRule = useMemo(() => Math.max(1, ...(dashboard?.top_risk_rules ?? []).map((r: any) => Number(r.projects || 0))), [dashboard]);

  const TABS: { id: Tab; label: string }[] = [
    { id: "overview", label: "班级总览" },
    { id: "submissions", label: "学生提交" },
    { id: "compare", label: "基线对比" },
    { id: "evidence", label: "证据链" },
    { id: "report", label: "智能报告" },
    { id: "feedback", label: "写回反馈" },
  ];

  return (
    <div className="tch-app">
      <header className="chat-topbar">
        <div className="topbar-left">
          <Link href="/" className="topbar-brand">VentureAgent</Link>
          <span className="topbar-sep" />
          <span className="topbar-label">教师控制台</span>
        </div>
        <div className="topbar-center">
          <input className="tch-filter-input" value={classId} onChange={(e) => setClassId(e.target.value)} placeholder="班级ID" />
          <input className="tch-filter-input" value={cohortId} onChange={(e) => setCohortId(e.target.value)} placeholder="学期" />
          <input className="tch-filter-input" value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)} placeholder="类别筛选" />
        </div>
        <div className="topbar-right">
          <button className="topbar-btn" onClick={generateReport} disabled={loading}>生成AI报告</button>
          <Link href="/student" className="topbar-btn">学生端</Link>
        </div>
      </header>

      <div className="tch-body">
        <nav className="tch-sidebar">
          {TABS.map((t) => (
            <button key={t.id} className={`tch-nav-btn ${tab === t.id ? "active" : ""}`} onClick={() => {
              setTab(t.id);
              if (t.id === "overview") loadDashboard();
              if (t.id === "submissions") loadSubmissions();
              if (t.id === "compare") loadCompare();
            }}>
              {t.label}
            </button>
          ))}
        </nav>

        <main className="tch-main">
          {loading && <div className="tch-loading">加载中...</div>}

          {/* ── 班级总览 ── */}
          {tab === "overview" && (
            <div className="tch-panel fade-up">
              <h2>班级总览</h2>
              <p className="tch-desc">基于Neo4j图数据库中存储的全部项目数据实时计算。数据来源：学生每次提交或对话时自动入库。</p>
              {dashboard?.error && <p className="right-hint">图数据读取失败：{dashboard.error}</p>}
              <div className="kpi-grid">
                <div className="kpi"><span>项目总数</span><strong>{dashboard?.overview?.total_projects ?? "-"}</strong><em className="kpi-hint">图数据库中的项目节点数</em></div>
                <div className="kpi"><span>证据总数</span><strong>{dashboard?.overview?.total_evidence ?? "-"}</strong><em className="kpi-hint">学生提交的证据条数</em></div>
                <div className="kpi"><span>规则命中</span><strong>{dashboard?.overview?.total_rule_hits ?? "-"}</strong><em className="kpi-hint">触发风险规则的总次数</em></div>
              </div>
              <div className="viz-grid">
                <div className="viz-card">
                  <h3>类别分布</h3>
                  <p className="tch-desc">学生项目的领域分类统计。点击类别可筛选。</p>
                  {(dashboard?.category_distribution ?? []).map((row: any) => (
                    <div key={row.category} className="bar-row" style={{ cursor: "pointer" }} onClick={() => setCategoryFilter(row.category)}>
                      <span>{row.category}</span>
                      <div className="bar-track"><div className="bar-fill" style={{ width: `${(Number(row.projects || 0) / maxCat) * 100}%` }} /></div>
                      <em>{row.projects}</em>
                    </div>
                  ))}
                </div>
                <div className="viz-card">
                  <h3>Top 风险规则</h3>
                  <p className="tch-desc">被触发最多次的风险规则。高频风险=班级共性问题，适合课堂重点讲解。</p>
                  {(dashboard?.top_risk_rules ?? []).map((row: any) => (
                    <div key={row.rule} className="bar-row">
                      <span>{row.rule}</span>
                      <div className="bar-track danger"><div className="bar-fill danger" style={{ width: `${(Number(row.projects || 0) / maxRule) * 100}%` }} /></div>
                      <em>{row.projects}</em>
                    </div>
                  ))}
                </div>
              </div>
              <h3>高风险项目</h3>
              <p className="tch-desc">触发风险规则最多的项目，建议优先关注和干预。点击可查看详细证据链。</p>
              <div className="table-like">
                {(dashboard?.high_risk_projects ?? []).slice(0, 8).map((row: any) => (
                  <button key={row.project_id} className="project-item" onClick={() => loadEvidence(row.project_id)}>
                    <span>{row.project_name || row.project_id}</span>
                    <span>{row.category}</span>
                    <span className="risk-badge high">风险{row.risk_count}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* ── 学生提交列表 ── */}
          {tab === "submissions" && (
            <div className="tch-panel fade-up">
              <h2>学生提交记录 ({submissions.length})</h2>
              <p className="tch-desc">学生每次发消息或上传文件，系统自动记录并分析。评分来自规则引擎（满分10），风险为触发的规则ID。点击"展开"查看学生提交的原始内容。</p>
              <div className="tch-table">
                <div className="tch-table-header">
                  <span>时间</span><span>项目</span><span>学生</span><span>来源</span><span>评分</span><span>风险</span><span>操作</span>
                </div>
                {submissions.map((s, i) => (
                  <div key={i} className="tch-submission-block">
                    <div className="tch-table-row">
                      <span className="tch-cell-time">{(s.created_at ?? "").slice(0, 16)}</span>
                      <span>{s.project_id}</span>
                      <span>{s.student_id}</span>
                      <span>{s.source_type}{s.filename ? ` (${s.filename})` : ""}</span>
                      <span className="tch-cell-score">{s.overall_score}</span>
                      <span>{(s.triggered_rules ?? []).join(", ") || "-"}</span>
                      <span>
                        <button className="tch-sm-btn" onClick={() => setExpandedSubmission(expandedSubmission === i ? null : i)}>
                          {expandedSubmission === i ? "收起" : "展开"}
                        </button>
                        <button className="tch-sm-btn" onClick={() => loadEvidence(s.project_id)}>证据链</button>
                        <button className="tch-sm-btn" onClick={() => { setSelectedProject(s.project_id); setTab("feedback"); }}>批注</button>
                      </span>
                    </div>
                    {expandedSubmission === i && (
                      <div className="tch-submission-detail">
                        <div className="tch-detail-section">
                          <h4>学生提交的原始内容</h4>
                          <div className="tch-raw-text">{s.full_text || s.text_preview || "（无文本内容）"}</div>
                        </div>
                        {s.bottleneck && (
                          <div className="tch-detail-section">
                            <h4>系统诊断瓶颈</h4>
                            <p>{s.bottleneck}</p>
                          </div>
                        )}
                        {s.next_task && (
                          <div className="tch-detail-section">
                            <h4>系统建议的下一步</h4>
                            <p>{s.next_task}</p>
                          </div>
                        )}
                        {s.kg_analysis?.insight && (
                          <div className="tch-detail-section">
                            <h4>知识图谱分析</h4>
                            <p>{s.kg_analysis.insight}</p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
                {!submissions.length && <p className="right-hint">暂无提交记录。学生对话后这里会自动出现。</p>}
              </div>
            </div>
          )}

          {/* ── 基线对比 ── */}
          {tab === "compare" && (
            <div className="tch-panel fade-up">
              <h2>历史基线 vs 本班现状</h2>
              <p className="tch-desc">将本班数据与历史所有班级的平均水平对比。"风险强度"=平均每个项目触发的风险规则数，数值越低越好。差值为正表示本班风险高于历史平均。</p>
              <div className="kpi-grid">
                <div className="kpi"><span>基线风险强度</span><strong>{compareData?.baseline?.avg_rule_hits_per_project ?? "-"}</strong><em className="kpi-hint">历史全部项目的平均值</em></div>
                <div className="kpi"><span>本班风险强度</span><strong>{compareData?.current_class?.avg_rule_hits_per_submission ?? "-"}</strong><em className="kpi-hint">本班学生提交的平均值</em></div>
                <div className="kpi"><span>差值</span><strong>{compareData?.comparison?.risk_intensity_delta ?? "-"}</strong><em className="kpi-hint">正数=高于基线，负数=优于基线</em></div>
              </div>
              <div className="kpi-grid">
                <div className="kpi"><span>基线高风险占比</span><strong>{compareData?.baseline?.high_risk_ratio ?? "-"}</strong><em className="kpi-hint">历史高危项目的比例</em></div>
                <div className="kpi"><span>本班高风险占比</span><strong>{compareData?.current_class?.high_risk_ratio ?? "-"}</strong><em className="kpi-hint">本班高危项目的比例</em></div>
                <div className="kpi"><span>Rubric 均分</span><strong>{compareData?.current_class?.avg_rubric_score ?? "-"}</strong><em className="kpi-hint">9维度评分的平均值(满分10)</em></div>
              </div>
              <h3>自动干预建议</h3>
              <p className="tch-desc">系统根据对比差异自动生成的教学建议。建议在课堂上针对性讲解。</p>
              <div className="tch-recs">
                {(compareData?.recommendations ?? []).map((item: string, i: number) => (
                  <div key={i} className="right-tag">{item}</div>
                ))}
              </div>
            </div>
          )}

          {/* ── 证据链 ── */}
          {tab === "evidence" && (
            <div className="tch-panel fade-up">
              <h2>项目证据链 — {selectedProject || projectId}</h2>
              <p className="tch-desc">证据链来自Neo4j图数据库，记录学生项目中被识别的关键证据（如用户访谈、市场数据、技术验证等）。证据越完整，项目越成熟。</p>
              <div className="tch-evidence-actions">
                <input value={selectedProject || projectId} onChange={(e) => setSelectedProject(e.target.value)} placeholder="项目ID" />
                <button className="topbar-btn" onClick={() => loadEvidence(selectedProject || projectId)}>加载</button>
                <button className="topbar-btn" onClick={() => { setTab("feedback"); }}>写反馈</button>
              </div>
              {evidence?.project ? (
                <>
                  <p className="right-hint">{evidence.project.project_name} | {evidence.project.category} | 置信度 {evidence.project.confidence}</p>
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
              ) : <p className="right-hint">从"班级总览"的高风险项目或"学生提交"中选择一个项目查看</p>}
            </div>
          )}

          {/* ── 智能报告 ── */}
          {tab === "report" && (
            <div className="tch-panel fade-up">
              <h2>AI 班级报告</h2>
              <p className="tch-desc">由AI基于全班提交数据自动生成的评估报告，包含风险分布、共性问题和教学建议。可反复生成获取最新分析。</p>
              <button className="topbar-btn" onClick={generateReport} disabled={loading} style={{ marginBottom: 16 }}>
                {loading ? "生成中…" : "重新生成"}
              </button>
              {report ? (
                <div className="tch-report-content">{report}</div>
              ) : (
                <p className="right-hint">点击上方按钮，系统将汇总所有学生的提交数据、风险分布和评分情况，生成一份班级分析报告。</p>
              )}
              {reportSnapshot && (
                <details className="debug-json" style={{ marginTop: 16 }}>
                  <summary>报告依据的原始数据</summary>
                  <pre>{JSON.stringify(reportSnapshot, null, 2)}</pre>
                </details>
              )}
            </div>
          )}

          {/* ── 写回反馈 ── */}
          {tab === "feedback" && (
            <div className="tch-panel fade-up">
              <h2>教师反馈 → 学生端</h2>
              <p className="tch-desc">您写的反馈会存储到该项目的数据中。当学生下次与AI对话时，AI会参考您的反馈调整建议方向。"关注标签"帮助AI理解您希望学生优先改进的领域。</p>
              <form className="tch-feedback-form" onSubmit={submitFeedback}>
                <label>目标项目 <input value={selectedProject || projectId} onChange={(e) => setSelectedProject(e.target.value)} /></label>
                <label>教师ID <input value={teacherId} onChange={(e) => setTeacherId(e.target.value)} /></label>
                <label>关注标签（逗号分隔）<input value={feedbackTags} onChange={(e) => setFeedbackTags(e.target.value)} placeholder="evidence,feasibility,compliance" /></label>
                <label>反馈内容</label>
                <textarea value={feedbackText} onChange={(e) => setFeedbackText(e.target.value)} placeholder="例如：先修正渠道可达性，再补充支付意愿证据。建议增加合规性论证。" rows={4} />
                <button type="submit">提交反馈到学生端</button>
              </form>
              {feedbackResult && <div className="tch-feedback-success">{feedbackResult}</div>}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
