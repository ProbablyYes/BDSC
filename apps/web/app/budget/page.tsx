"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "../hooks/useAuth";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8037").trim().replace(/\/+$/, "");

type PlanSummary = {
  plan_id: string;
  name: string;
  purpose: string;
  updated_at: string;
  summary: {
    total_investment?: number;
    health_score?: number;
    baseline_monthly_revenue?: number;
    breakeven_baseline?: number | null;
  };
};

/* ── Purpose config (no emoji, color-coded) ── */
const PURPOSE_INFO: Record<string, {
  label: string; desc: string; color: string;
  modules: string[]; detail: string;
}> = {
  quick: {
    label: "快速估算", desc: "几分钟评估项目资金需求，适合早期想法验证",
    color: "#ffa94d",
    modules: ["成本中心"],
    detail: "仅包含成本预算模块，帮你快速梳理项目需要花多少钱。",
  },
  competition: {
    label: "比赛预算", desc: "创新创业大赛的差旅、材料、赛程开销",
    color: "#ff6b6b",
    modules: ["成本中心", "比赛专项", "资金规划"],
    detail: "涵盖比赛全流程预算，包括报名费、差旅、材料、评审等环节。",
  },
  business: {
    label: "商业计划", desc: "完整商业计划书级别的财务模型与分析",
    color: "#6b8aff",
    modules: ["成本中心", "收入模型", "比赛专项", "情景分析", "资金规划"],
    detail: "包含完整财务模型：成本结构、多元收入、三档情景分析、资金缺口与融资规划。",
  },
  coursework: {
    label: "课程作业", desc: "轻量版，满足课程报告中的财务分析要求",
    color: "#51cf66",
    modules: ["成本中心", "收入模型", "资金规划"],
    detail: "适配课程作业需求，涵盖基础成本、简单收入模型和资金来源说明。",
  },
};

function cny(n: number) {
  return n.toLocaleString("zh-CN", { style: "currency", currency: "CNY", minimumFractionDigits: 0 });
}

function healthGrade(s: number) {
  if (s >= 80) return { grade: "完整", color: "#51cf66" };
  if (s >= 65) return { grade: "较完整", color: "#6b8aff" };
  if (s >= 50) return { grade: "初步", color: "#ffa94d" };
  if (s >= 35) return { grade: "待补", color: "#ff922b" };
  return { grade: "空白", color: "#ff6b6b" };
}

export default function BudgetPage() {
  const user = useAuth();
  const router = useRouter();
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  /* ── Wizard state ── */
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizStep, setWizStep] = useState(0);
  const [wzPurpose, setWzPurpose] = useState("business");
  const [wzName, setWzName] = useState("");
  const [wzDesc, setWzDesc] = useState("");
  const [wzTeamSize, setWzTeamSize] = useState("");
  const [wzIndustry, setWzIndustry] = useState("");

  const [loadError, setLoadError] = useState("");

  const loadPlans = useCallback(async () => {
    if (!user) return;
    setLoadError("");
    try {
      const r = await fetch(`${API}/api/budget/plans/${user.user_id}`);
      if (!r.ok) { setLoadError(`加载失败 (${r.status})`); setLoading(false); return; }
      const d = await r.json();
      setPlans(d.plans || []);
    } catch (err: any) {
      setLoadError(`网络错误：${err?.message || "无法连接后端"}`);
    }
    setLoading(false);
  }, [user]);

  useEffect(() => { loadPlans(); }, [loadPlans]);

  const openWizard = () => {
    setWizardOpen(true);
    setWizStep(0);
    setWzPurpose("business");
    setWzName("");
    setWzDesc("");
    setWzTeamSize("");
    setWzIndustry("");
  };

  const [createError, setCreateError] = useState("");

  const createPlan = async () => {
    if (!user || !wzName.trim()) return;
    setCreating(true);
    setCreateError("");
    try {
      const r = await fetch(`${API}/api/budget/plans/${user.user_id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: wzName.trim(), purpose: wzPurpose }),
      });
      if (!r.ok) {
        setCreateError(`创建失败 (${r.status}): ${r.statusText}`);
        setCreating(false);
        return;
      }
      const d = await r.json();
      if (d.plan?.plan_id) {
        router.push(`/budget/${d.plan.plan_id}`);
      } else {
        setCreateError("创建失败：返回数据缺少 plan_id");
      }
    } catch (err: any) {
      setCreateError(`网络错误：${err?.message || "无法连接后端"}`);
    }
    setCreating(false);
  };

  const deletePlan = async (planId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!user || !confirm("确定删除此方案？")) return;
    try {
      await fetch(`${API}/api/budget/plans/${user.user_id}/${planId}`, { method: "DELETE" });
      setPlans(prev => prev.filter(p => p.plan_id !== planId));
    } catch { /* ignore */ }
  };

  if (!user) return <div className="bw-page"><div className="bw-loading-center">加载中...</div></div>;

  /* ═══ Wizard View ═══ */
  if (wizardOpen) {
    const steps = [
      { label: "选择类型" },
      { label: "基本信息" },
      { label: "确认创建" },
    ];
    const pi = PURPOSE_INFO[wzPurpose] || PURPOSE_INFO.business;
    const canNext = wizStep === 0 ? true : wizStep === 1 ? wzName.trim().length > 0 : true;

    return (
      <div className="bw-page">
        <div className="bw-wizard">
          <div className="bw-wizard-head">
            <h1>创建财务方案</h1>
            <p>按步骤完成配置，系统会为你预填合适的财务模块和默认项</p>
          </div>

          {/* Step indicator */}
          <div className="bw-steps">
            {steps.map((s, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center" }}>
                {i > 0 && <div className={`bw-step-line${i <= wizStep ? " done" : ""}`} />}
                <div className={`bw-step${i === wizStep ? " active" : i < wizStep ? " done" : ""}`}>
                  <div className="bw-step-num">{i < wizStep ? "✓" : i + 1}</div>
                  <span className="bw-step-label">{s.label}</span>
                </div>
              </div>
            ))}
          </div>

          {/* Step content */}
          <div className="bw-wizard-body" key={wizStep}>
            {/* Step 0: Choose purpose */}
            {wizStep === 0 && (
              <div className="bw-purpose-grid">
                {Object.entries(PURPOSE_INFO).map(([key, info]) => (
                  <div
                    key={key}
                    className={`bw-purpose-card${wzPurpose === key ? " selected" : ""}`}
                    onClick={() => setWzPurpose(key)}
                  >
                    <div className="bw-pc-indicator" />
                    <div className="bw-pc-bar" style={{ background: info.color }} />
                    <div className="bw-purpose-label">{info.label}</div>
                    <div className="bw-purpose-desc">{info.desc}</div>
                    <div className="bw-purpose-modules">
                      {info.modules.map(m => <span key={m} className="bw-purpose-mod-tag">{m}</span>)}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Step 1: Basic info */}
            {wizStep === 1 && (
              <div className="bw-wz-form">
                <div className="bw-wz-field">
                  <label>方案名称</label>
                  <input
                    className="bw-wz-input"
                    value={wzName}
                    onChange={e => setWzName(e.target.value)}
                    placeholder="例如：NoteMind 创业计划 / 互联网+省赛预算"
                    autoFocus
                  />
                </div>
                <div className="bw-wz-field">
                  <label>项目简述（可选）</label>
                  <textarea
                    className="bw-wz-textarea"
                    value={wzDesc}
                    onChange={e => setWzDesc(e.target.value)}
                    placeholder="简要描述你的项目做什么，AI 会据此给出更精准的建议..."
                    rows={3}
                  />
                  <span className="bw-wz-hint">填写后 AI 助手可以自动推荐成本项和收入模型</span>
                </div>
                <div className="bw-wz-row">
                  <div className="bw-wz-field">
                    <label>团队人数（可选）</label>
                    <input
                      className="bw-wz-input"
                      value={wzTeamSize}
                      onChange={e => setWzTeamSize(e.target.value)}
                      placeholder="例如：5"
                      type="number"
                    />
                  </div>
                  <div className="bw-wz-field">
                    <label>所属行业（可选）</label>
                    <input
                      className="bw-wz-input"
                      value={wzIndustry}
                      onChange={e => setWzIndustry(e.target.value)}
                      placeholder="例如：教育科技 / 医疗健康"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Step 2: Confirm & preview */}
            {wizStep === 2 && (
              <div className="bw-wz-preview">
                <div className="bw-wz-preview-card">
                  <h4>方案概要</h4>
                  <div className="bw-wz-summary-row">
                    <span>方案名称</span>
                    <span>{wzName || "未命名"}</span>
                  </div>
                  <div className="bw-wz-summary-row">
                    <span>方案类型</span>
                    <span style={{ color: pi.color }}>{pi.label}</span>
                  </div>
                  {wzDesc && (
                    <div className="bw-wz-summary-row">
                      <span>项目简述</span>
                      <span style={{ maxWidth: 300, textAlign: "right" }}>{wzDesc}</span>
                    </div>
                  )}
                  {wzTeamSize && (
                    <div className="bw-wz-summary-row">
                      <span>团队人数</span>
                      <span>{wzTeamSize} 人</span>
                    </div>
                  )}
                  {wzIndustry && (
                    <div className="bw-wz-summary-row">
                      <span>所属行业</span>
                      <span>{wzIndustry}</span>
                    </div>
                  )}
                </div>

                <div className="bw-wz-preview-card">
                  <h4>将启用的财务模块</h4>
                  <ul className="bw-wz-preview-list">
                    {pi.modules.map(m => (
                      <li key={m}>
                        <span className="bw-dot" style={{ background: pi.color }} />
                        {m}
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="bw-wz-preview-card">
                  <h4>类型说明</h4>
                  <p style={{ fontSize: 13, color: "var(--bw-text-secondary)", lineHeight: 1.7, margin: 0 }}>
                    {pi.detail}
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* Error message */}
          {createError && (
            <div style={{ marginTop: 16, padding: "10px 16px", borderRadius: 8, background: "rgba(255,107,107,.1)", border: "1px solid rgba(255,107,107,.2)", color: "#ff6b6b", fontSize: 13 }}>
              {createError}
            </div>
          )}

          {/* Navigation */}
          <div className="bw-wizard-footer">
            <button
              className="bw-wz-back"
              onClick={() => {
                if (wizStep === 0) { setWizardOpen(false); }
                else setWizStep(s => s - 1);
              }}
            >
              {wizStep === 0 ? "取消" : "上一步"}
            </button>
            <button
              className="bw-wz-next"
              disabled={!canNext || creating}
              onClick={() => {
                if (wizStep < 2) setWizStep(s => s + 1);
                else createPlan();
              }}
            >
              {wizStep < 2 ? "下一步" : creating ? "创建中..." : "确认创建"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  /* ═══ Plan List View ═══ */
  return (
    <div className="bw-page">
      <div className="bw-list-container">
        <header className="bw-list-header">
          <Link href="/student" className="bw-back-link">返回主页</Link>
          <h1 className="bw-list-title">财务工作台</h1>
          <p className="bw-list-subtitle">管理你的财务方案，为每个项目建立独立预算</p>
        </header>

        <div className="bw-list-actions">
          <button className="bw-create-btn" onClick={openWizard}>+ 新建方案</button>
        </div>

        {loadError && (
          <div style={{ marginBottom: 16, padding: "10px 16px", borderRadius: 8, background: "rgba(255,107,107,.1)", border: "1px solid rgba(255,107,107,.2)", color: "#ff6b6b", fontSize: 13 }}>
            {loadError}
            <button onClick={loadPlans} style={{ marginLeft: 12, background: "none", border: "none", color: "var(--bw-accent)", cursor: "pointer", fontSize: 13, textDecoration: "underline" }}>重试</button>
          </div>
        )}

        {loading ? (
          <div className="bw-loading-center">加载方案列表...</div>
        ) : plans.length === 0 && !loadError ? (
          <div className="bw-empty-state">
            <div className="bw-empty-visual" />
            <h3>还没有财务方案</h3>
            <p>创建你的第一个方案，开始规划项目财务</p>
            <button className="bw-create-btn" onClick={openWizard}>+ 创建第一个方案</button>
          </div>
        ) : (
          <div className="bw-plan-grid">
            {plans.map(plan => {
              const pi = PURPOSE_INFO[plan.purpose] || PURPOSE_INFO.business;
              const sm = plan.summary || {};
              const hg = healthGrade(sm.health_score || 0);
              return (
                <div key={plan.plan_id} className="bw-plan-card" onClick={() => router.push(`/budget/${plan.plan_id}`)}>
                  <div className="bw-plan-card-top">
                    <span className="bw-plan-purpose-tag" style={{ background: pi.color + "15", color: pi.color, borderLeft: `3px solid ${pi.color}` }}>
                      {pi.label}
                    </span>
                    <button className="bw-plan-delete" onClick={(e) => deletePlan(plan.plan_id, e)} title="删除方案">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
                    </button>
                  </div>
                  <h3 className="bw-plan-name">{plan.name}</h3>
                  <div className="bw-plan-metrics">
                    <div className="bw-plan-metric">
                      <span className="bw-plan-metric-label">总投入</span>
                      <span className="bw-plan-metric-value">{cny(sm.total_investment || 0)}</span>
                    </div>
                    <div className="bw-plan-metric">
                      <span className="bw-plan-metric-label">健康度</span>
                      <span className="bw-plan-metric-value" style={{ color: hg.color }}>{hg.grade}</span>
                    </div>
                  </div>
                  <div className="bw-plan-card-footer">
                    <span className="bw-plan-time">{plan.updated_at ? new Date(plan.updated_at).toLocaleDateString("zh-CN") : "—"}</span>
                    <span className="bw-plan-enter">查看详情</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
