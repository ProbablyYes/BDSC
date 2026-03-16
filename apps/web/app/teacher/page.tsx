"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8787").trim().replace(/\/+$/, "");
type Tab = "overview" | "submissions" | "compare" | "evidence" | "report" | "feedback" | "capability" | "rule-coverage" | "rubric" | "competition" | "interventions";

// 风险规则名称映射
const RISK_RULE_NAMES: Record<string, string> = {
  "weak_user_evidence": "弱用户证据",
  "compliance_not_covered": "合规性覆盖不足",
  "market_size_fallacy": "市场规模谬误",
  "no_competitor_claim": "缺少竞争对手声明",
};

function getRuleDisplayName(ruleName: string): string {
  return RISK_RULE_NAMES[ruleName] || ruleName;
}

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

  // New state for enhanced features
  const [capabilityMap, setCapabilityMap] = useState<any>(null);
  const [ruleCoverage, setRuleCoverage] = useState<any>(null);
  const [projectDiagnosis, setProjectDiagnosis] = useState<any>(null);
  const [rubricAssessment, setRubricAssessment] = useState<any>(null);
  const [competitionScore, setCompetitionScore] = useState<any>(null);
  const [teachingInterventions, setTeachingInterventions] = useState<any>(null);

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

  async function loadCapabilityMap() {
    setLoading(true);
    const data = await api(`/api/teacher/capability-map/${encodeURIComponent(classId.trim() || "default")}`);
    setCapabilityMap(data);
    setTab("capability");
    setLoading(false);
  }

  async function loadRuleCoverage() {
    setLoading(true);
    const data = await api(`/api/teacher/rule-coverage/${encodeURIComponent(classId.trim() || "default")}`);
    setRuleCoverage(data);
    setTab("rule-coverage");
    setLoading(false);
  }

  async function loadProjectDiagnosis() {
    setLoading(true);
    if (!selectedProject) {
      setLoading(false);
      return;
    }
    const data = await api(`/api/teacher/project/${encodeURIComponent(selectedProject)}/deep-diagnosis`);
    setProjectDiagnosis(data);
    setTab("rubric");
    setLoading(false);
  }

  async function loadRubricAssessment() {
    setLoading(true);
    if (!selectedProject) {
      setLoading(false);
      return;
    }
    const data = await api(`/api/teacher/project/${encodeURIComponent(selectedProject)}/rubric-assessment`);
    setRubricAssessment(data);
    setTab("rubric");
    setLoading(false);
  }

  async function loadCompetitionScore() {
    setLoading(true);
    if (!selectedProject) {
      setLoading(false);
      return;
    }
    const data = await api(`/api/teacher/project/${encodeURIComponent(selectedProject)}/competition-score`);
    setCompetitionScore(data);
    setTab("competition");
    setLoading(false);
  }

  async function loadTeachingInterventions() {
    setLoading(true);
    const data = await api(`/api/teacher/teaching-interventions/${encodeURIComponent(classId.trim() || "default")}`);
    setTeachingInterventions(data);
    setTab("interventions");
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
    { id: "capability", label: "能力映射" },
    { id: "rule-coverage", label: "规则检查" },
    { id: "rubric", label: "评分与诊断" },
    { id: "competition", label: "竞赛预测" },
    { id: "interventions", label: "教学建议" },
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
              if (t.id === "capability") loadCapabilityMap();
              if (t.id === "rule-coverage") loadRuleCoverage();
              if (t.id === "rubric") loadRubricAssessment();
              if (t.id === "competition") loadCompetitionScore();
              if (t.id === "interventions") loadTeachingInterventions();
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
                  <h3>最高风险规则</h3>
                  <p className="tch-desc">被触发最多次的风险规则。高频风险=班级共性问题，适合课堂重点讲解。</p>
                  {(dashboard?.top_risk_rules ?? []).slice(0, 4).map((row: any) => (
                    <div key={row.rule} className="bar-row">
                      <span>{getRuleDisplayName(row.rule)}</span>
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
                        <div className="tch-detail-section">
                          <h4>快速操作</h4>
                          <button className="tch-sm-btn" onClick={() => { setSelectedProject(s.project_id); loadRubricAssessment(); }}>Rubric评分</button>
                          <button className="tch-sm-btn" onClick={() => { setSelectedProject(s.project_id); loadCompetitionScore(); }}>竞赛预测</button>
                          <button className="tch-sm-btn" onClick={() => { setSelectedProject(s.project_id); loadProjectDiagnosis(); }}>深度诊断</button>
                        </div>
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
              <p className="tch-desc">证据链包括从Neo4j图数据库中提取的关键证据，以及学生提交的项目文件。证据越完整，项目越成熟。</p>
              <div className="tch-evidence-actions">
                <input value={selectedProject || projectId} onChange={(e) => setSelectedProject(e.target.value)} placeholder="项目ID" />
                <button className="topbar-btn" onClick={() => loadEvidence(selectedProject || projectId)}>加载</button>
                <button className="topbar-btn" onClick={() => { setTab("feedback"); }}>写反馈</button>
              </div>
              {evidence && evidence.project ? (
                <>
                  <p className="right-hint">
                    {evidence.project.project_name} | {evidence.project.category} | 置信度 {evidence.project.confidence ?? 0}
                  </p>
                  
                  {/* Neo4j Evidence Section */}
                  {evidence.evidence && evidence.evidence.length > 0 ? (
                    <div>
                      <h3 style={{ marginTop: 20, marginBottom: 10 }}>图数据库证据 ({evidence.evidence.length})</h3>
                      <div className="table-like">
                        {evidence.evidence.map((e: any) => (
                          <div key={e.evidence_id} className="evidence-item">
                            <strong>{e.type}</strong>
                            <p>{e.quote}</p>
                            <em>{e.source_unit}</em>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div style={{ marginTop: 20 }}>
                      <p style={{ fontSize: 12, color: "#999" }}>Neo4j中暂无结构化证据数据</p>
                    </div>
                  )}
                  
                  {/* Student File Submissions Section */}
                  {evidence.file_submissions && evidence.file_submissions.length > 0 ? (
                    <div>
                      <h3 style={{ marginTop: 20, marginBottom: 10 }}>学生提交文件 ({evidence.file_submissions.length})</h3>
                      <div className="table-like">
                        {evidence.file_submissions.map((s: any) => (
                          <div key={s.submission_id} className="evidence-item" style={{ borderLeft: "4px solid #2ecc71" }}>
                            <strong>📄 {s.filename}</strong>
                            <p style={{ marginTop: 8, marginBottom: 10 }}>
                              <em>学生: {s.student_id} | 提交时间: {s.created_at ? new Date(s.created_at).toLocaleDateString('zh-CN') : '未知'}</em>
                            </p>
                            
                            {/* Summary Section */}
                            {s.summary ? (
                              <p style={{ fontSize: 13, color: "#333", fontWeight: 500, marginBottom: 10, padding: "8px 10px", backgroundColor: "#f0f8ff", borderRadius: 4 }}>
                                {s.summary}
                              </p>
                            ) : null}
                            
                            {/* Diagnosis Details */}
                            {s.diagnosis && Object.keys(s.diagnosis).length > 0 ? (
                              <details style={{ fontSize: 12, marginTop: 8 }}>
                                <summary style={{ cursor: "pointer", color: "#4a90e2", fontWeight: 500 }}>查看详细诊断信息</summary>
                                <div style={{ fontSize: 12, backgroundColor: "#f5f5f5", padding: 10, borderRadius: 4, marginTop: 8 }}>
                                  {s.diagnosis.overall_score !== undefined && (
                                    <p><strong>诊断评分:</strong> {s.diagnosis.overall_score.toFixed(2)}/5.0</p>
                                  )}
                                  {s.diagnosis.bottleneck && (
                                    <p><strong>核心瓶颈:</strong> {s.diagnosis.bottleneck}</p>
                                  )}
                                  {s.diagnosis.triggered_rules && s.diagnosis.triggered_rules.length > 0 ? (
                                    <p>
                                      <strong>触发规则:</strong> {s.diagnosis.triggered_rules.map((r: any) => (
                                        <span key={r.id} style={{ display: "inline-block", marginRight: 8, padding: "2px 6px", backgroundColor: "#ffe6e6", borderRadius: 3 }}>
                                          {r.id}: {r.name}
                                        </span>
                                      ))}
                                    </p>
                                  ) : null}
                                </div>
                              </details>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div style={{ marginTop: 20 }}>
                      <p style={{ fontSize: 12, color: "#999" }}>该项目暂无学生提交的文件</p>
                    </div>
                  )}
                  
                  {(!evidence.evidence || evidence.evidence.length === 0) && (!evidence.file_submissions || evidence.file_submissions.length === 0) && (
                    <p className="right-hint" style={{ marginTop: 20 }}>暂无任何证据数据</p>
                  )}
                </>
              ) : (
                <p className="right-hint">
                  {!evidence ? "请输入项目ID后点击'加载'按钮" : "项目信息加载失败，请检查项目ID是否正确或稍后重试"}
                </p>
              )}
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

          {/* ── 能力映射雷达图 ── */}
          {tab === "capability" && (
            <div className="tch-panel fade-up">
              <h2>班级能力映射</h2>
              <p className="tch-desc">基于5个维度（痛点发现、方案策划、商业建模、资源杠杆、路演表达）评估班级整体能力水平。雷达图越接近外圆表示能力越强。</p>
              {capabilityMap?.dimensions && (
                <>
                  <div className="viz-grid">
                    <div className="viz-card">
                      <h3>班级能力分布（满分10）</h3>
                      <p className="tch-desc">班级平均成绩</p>
                      {(capabilityMap.dimensions ?? []).map((dim: any) => (
                        <div key={dim.name} className="bar-row">
                          <span>{dim.name}</span>
                          <div className="bar-track"><div className="bar-fill" style={{ width: `${(dim.score / dim.max) * 100}%` }} /></div>
                          <em>{dim.score.toFixed(1)}</em>
                        </div>
                      ))}
                    </div>
                    <div className="viz-card">
                      <h3>维度强弱对比</h3>
                      <p className="tch-desc">找出班级的短板（得分最低的维度）并重点补强</p>
                      {(() => {
                        const sorted = [...(capabilityMap.dimensions ?? [])].sort((a, b) => a.score - b.score);
                        return (
                          <div>
                            {sorted.slice(0, 3).map((dim: any, i: number) => (
                              <div key={dim.name} className="bar-row">
                                <span>{i === 0 ? "🔴 最弱" : i === 1 ? "🟡 较弱" : "🟢 需强化"}</span>
                                <span>{dim.name}</span>
                                <strong>{dim.score.toFixed(1)}</strong>
                              </div>
                            ))}
                          </div>
                        );
                      })()}
                    </div>
                  </div>
                </>
              )}
              {!capabilityMap && <p className="right-hint">加载中或暂无数据...请确保班级已有学生提交。</p>}
            </div>
          )}

          {/* ── 规则检查热力图 ── */}
          {tab === "rule-coverage" && (
            <div className="tch-panel fade-up">
              <h2>规则检查覆盖率</h2>
              <p className="tch-desc">15条关键业务规则（H1-H15）的触发统计。热力图显示哪些规则在班级中最常被触发，即班级共性风险点。</p>
              {ruleCoverage?.rule_coverage && (
                <>
                  <div style={{ marginBottom: 16 }}>
                    <strong>高危规则：{ruleCoverage.high_risk_count} 条 | 总提交数：{ruleCoverage.total_submissions}</strong>
                  </div>
                  <div className="tch-table">
                    <div className="tch-table-header">
                      <span>规则ID</span><span>规则名称</span><span>触发次数</span><span>覆盖率</span><span>风险等级</span>
                    </div>
                    {ruleCoverage.rule_coverage.map((rule: any) => (
                      <div key={rule.rule_id} className="tch-table-row">
                        <span className="tch-cell-time">{rule.rule_id}</span>
                        <span>{rule.rule_name}</span>
                        <span>{rule.hit_count}</span>
                        <span>{(rule.coverage_ratio * 100).toFixed(1)}%</span>
                        <span className={rule.severity === "high" ? "risk-badge high" : rule.severity === "medium" ? "risk-badge" : "risk-badge low"}>
                          {rule.severity === "high" ? "🔴高" : rule.severity === "medium" ? "🟡中" : "🟢低"}
                        </span>
                      </div>
                    ))}
                  </div>
                </>
              )}
              {!ruleCoverage && <p className="right-hint">加载中或暂无数据...</p>}
            </div>
          )}

          {/* ── Rubric 评分与项目诊断 ── */}
          {tab === "rubric" && (
            <div className="tch-panel fade-up">
              <h2>Rubric评分与项目诊断</h2>
              <p className="tch-desc">针对单个项目的深度评估，包括9个维度（R1-R9）的Rubric评分，触发的规则及修复建议。</p>
              <div style={{ marginBottom: 16 }}>
                <input 
                  value={selectedProject || projectId} 
                  onChange={(e) => setSelectedProject(e.target.value)} 
                  placeholder="项目ID"
                  style={{ marginRight: 8 }}
                />
                <button className="topbar-btn" onClick={loadRubricAssessment}>加载评分</button>
              </div>

              {rubricAssessment?.rubric_items && (
                <div>
                  <div className="kpi-grid">
                    <div className="kpi">
                      <span>加权总分</span>
                      <strong>{rubricAssessment.overall_weighted_score}</strong>
                      <em>满分5分</em>
                    </div>
                  </div>

                  <h3 style={{ marginTop: 16 }}>各维度评分详情</h3>
                  <div className="tch-table">
                    <div className="tch-table-header">
                      <span>维度</span><span>得分</span><span>权重</span><span>修改建议</span>
                    </div>
                    {rubricAssessment.rubric_items.map((item: any) => (
                      <div key={item.item_id} className="tch-table-row">
                        <span><strong>{item.item_id}</strong> {item.item_name}</span>
                        <span>{item.score}/{item.max_score}</span>
                        <span>{(item.weight * 100).toFixed(0)}%</span>
                        <span style={{ fontSize: "0.9em" }}>{item.revision_suggestion}</span>
                      </div>
                    ))}
                  </div>

                  {projectDiagnosis?.fix_strategies && (
                    <>
                      <h3 style={{ marginTop: 16 }}>关键风险修复方案</h3>
                      {projectDiagnosis.fix_strategies.map((fix: any) => (
                        <div key={fix.rule_id} className="right-tag" style={{ marginBottom: 8 }}>
                          <strong>{fix.rule_id}</strong> {fix.rule_name} → {fix.fix_strategy}
                        </div>
                      ))}
                    </>
                  )}
                </div>
              )}
              {!rubricAssessment && <p className="right-hint">选择项目后点击"加载评分"获取详细评估...</p>}
            </div>
          )}

          {/* ── 竞赛评分预测 ── */}
          {tab === "competition" && (
            <div className="tch-panel fade-up">
              <h2>竞赛评分预测</h2>
              <p className="tch-desc">基于项目当前状态预测在竞赛中的得分（0-100分），并给出24小时和72小时的快速修复清单。</p>
              <div style={{ marginBottom: 16 }}>
                <input 
                  value={selectedProject || projectId} 
                  onChange={(e) => setSelectedProject(e.target.value)} 
                  placeholder="项目ID"
                  style={{ marginRight: 8 }}
                />
                <button className="topbar-btn" onClick={loadCompetitionScore}>预测评分</button>
              </div>

              {competitionScore?.predicted_competition_score !== undefined && (
                <div>
                  <div className="kpi-grid">
                    <div className="kpi">
                      <span>预测竞赛评分</span>
                      <strong style={{ fontSize: 32, color: "#2ecc71" }}>{competitionScore.predicted_competition_score}</strong>
                      <em>
                        预测范围：
                        {typeof competitionScore.score_range === 'string' 
                          ? competitionScore.score_range 
                          : `${competitionScore.score_range_min || competitionScore.score_range?.[0]}-${competitionScore.score_range_max || competitionScore.score_range?.[1]}`}
                        分
                      </em>
                      <p style={{ fontSize: 12, color: "#666", marginTop: 8 }}>
                        <strong>评分说明：</strong>基于项目诊断评分、触发规则数量等因素综合计算。
                      </p>
                    </div>
                  </div>

                  <h3 style={{ marginTop: 16 }}>⚡ 24小时快速修复（最关键的3项）</h3>
                  <ul style={{ paddingLeft: 20, lineHeight: 1.8 }}>
                    {(competitionScore.quick_fixes_24h ?? []).map((fix: string, i: number) => (
                      <li key={i}>{fix}</li>
                    ))}
                  </ul>

                  <h3 style={{ marginTop: 16 }}>📋 72小时完整改进方案</h3>
                  <ul style={{ paddingLeft: 20, lineHeight: 1.8 }}>
                    {(competitionScore.quick_fixes_72h ?? []).map((fix: string, i: number) => (
                      <li key={i}>{fix}</li>
                    ))}
                  </ul>

                  {competitionScore.high_risk_rules_for_competition?.length > 0 && (
                    <>
                      <h3 style={{ marginTop: 20, marginBottom: 12, fontSize: 14, color: "#333" }}>🔴 竞赛评审关注的高风险规则</h3>
                      <div style={{ 
                        display: "grid", 
                        gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                        gap: 12,
                        padding: "12px",
                        backgroundColor: "#fef5f5",
                        borderRadius: "8px",
                        borderLeft: "4px solid #ff4d4d"
                      }}>
                        {competitionScore.high_risk_rules_for_competition.map((rule: any) => (
                          <div 
                            key={rule.rule} 
                            style={{ 
                              padding: "10px 12px", 
                              backgroundColor: "white",
                              border: "1px solid #ffb3b3",
                              borderRadius: "6px",
                              boxShadow: "0 2px 4px rgba(255, 77, 77, 0.1)",
                              display: "flex",
                              alignItems: "center",
                              gap: "8px"
                            }}
                          >
                            <span style={{ 
                              display: "inline-block",
                              backgroundColor: "#ff4d4d",
                              color: "white",
                              padding: "4px 8px",
                              borderRadius: "4px",
                              fontSize: "12px",
                              fontWeight: "bold",
                              minWidth: "32px",
                              textAlign: "center"
                            }}>
                              {rule.rule}
                            </span>
                            <span style={{ fontSize: "12px", color: "#555", flex: 1 }}>
                              {rule.name}
                            </span>
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              )}
              {!competitionScore && <p className="right-hint">选择项目后点击"预测评分"获取优化建议...</p>}
            </div>
          )}

          {/* ── 教学干预建议 ── */}
          {tab === "interventions" && (
            <div className="tch-panel fade-up">
              <h2>教学干预建议</h2>
              <p className="tch-desc">基于全班共性问题智能生成的教学干预优先级清单。系统识别出现在40%以上学生提交中的问题，并给出针对性教学方案。</p>
              <button className="topbar-btn" onClick={loadTeachingInterventions} disabled={loading} style={{ marginBottom: 16 }}>
                {loading ? "分析中…" : "刷新分析"}
              </button>

              {teachingInterventions?.shared_problems && (
                <div>
                  <div className="kpi-grid">
                    <div className="kpi">
                      <span>班级规模</span>
                      <strong>{teachingInterventions.student_count}</strong>
                      <em>学生数</em>
                    </div>
                    <div className="kpi">
                      <span>共性问题</span>
                      <strong>{teachingInterventions.total_shared_problems}</strong>
                      <em>需干预</em>
                    </div>
                  </div>

                  <h3 style={{ marginTop: 16 }}>优先级教学方案</h3>
                  {teachingInterventions.shared_problems.map((problem: any) => (
                    <div key={problem.rule_id} className="viz-card">
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                        <strong>{problem.rule_id}: {problem.problem_description}</strong>
                        <span className={problem.priority === "高" ? "risk-badge high" : "risk-badge"}>{problem.priority}优先级</span>
                      </div>
                      <p><strong>教学建议：</strong>{problem.teaching_suggestion}</p>
                      <p><em>预计课时：{problem.estimated_teaching_time}</em></p>
                    </div>
                  ))}

                  <h3 style={{ marginTop: 16 }}>下周课程设计建议</h3>
                  <p className="right-tag">{teachingInterventions.recommended_next_class_focus}</p>
                </div>
              )}
              {!teachingInterventions && <p className="right-hint">加载中或暂无数据...</p>}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
