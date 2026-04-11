"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8037").trim().replace(/\/+$/, "");

/* ── Types ── */
type CostItem = { name: string; unit_price: number; quantity: number; total: number; note: string; priority?: string; cost_type?: string };
type CostCategory = { name: string; items: CostItem[] };
type RevenueStream = { name: string; monthly_users: number; price: number; conversion_rate: number; monthly_revenue: number };
type CashFlowRow = { month: number; revenue: number; cost: number; net: number; cumulative: number };
type CompItem = { name: string; amount: number; note: string };
type FundingSource = { name: string; amount: number; note: string };
type ScenarioModel = { label: string; revenue_multiplier: number; conversion_multiplier: number; growth_rate_monthly: number; fixed_costs_monthly: number; variable_cost_per_user: number; note: string };
type ScenarioResult = { cash_flow_projection: CashFlowRow[]; months_to_breakeven: number | null; annual_revenue: number; annual_cost: number; annual_net: number; monthly_revenue_base: number };
type Summary = { project_cost_total: number; competition_cost_total: number; total_investment: number; baseline_monthly_revenue: number; baseline_annual_net: number; funding_gap: number; health_score: number; breakeven_fastest: number | null; breakeven_baseline: number | null; breakeven_slowest: number | null };
type Budget = {
  plan_id: string; user_id: string; name: string; purpose: string;
  visible_tabs: string[]; version: number; currency: string; updated_at: string;
  project_costs: { categories: CostCategory[] };
  business_finance: {
    revenue_streams: RevenueStream[]; fixed_costs_monthly: number;
    variable_cost_per_user: number; growth_rate_monthly: number;
    months_to_breakeven: number | null; cash_flow_projection: CashFlowRow[];
    scenario_models: Record<string, ScenarioModel>;
    scenario_results: Record<string, ScenarioResult>;
  };
  competition_budget: { items: CompItem[]; stages?: any[]; funding_sources?: FundingSource[] };
  funding_plan: { startup_capital_needed: number; sources: any[]; monthly_gap: any[]; fundraising_notes: string };
  ai_suggestions: any[];
  summary: Summary;
};

/* ── Helpers ── */
const PIE_COLORS = ["#6b8aff", "#51cf66", "#ffa94d", "#ff6b6b", "#9c6aff", "#20c997", "#339af0", "#f06595"];
function cny(n: number) { return n.toLocaleString("zh-CN", { style: "currency", currency: "CNY", minimumFractionDigits: 0 }); }
function healthGrade(s: number) { if (s >= 80) return { grade: "A", color: "#51cf66" }; if (s >= 65) return { grade: "B+", color: "#6b8aff" }; if (s >= 50) return { grade: "B", color: "#ffa94d" }; if (s >= 35) return { grade: "C", color: "#ff922b" }; return { grade: "D", color: "#ff6b6b" }; }

const TAB_LABELS: Record<string, string> = { cost: "成本中心", biz: "收入模型", comp: "比赛专项", compare: "情景分析", fund: "资金规划" };

interface Props { userId: string; planId: string; onBack?: () => void; }

export default function BudgetWorkbench({ userId, planId, onBack }: Props) {
  const [budget, setBudget] = useState<Budget | null>(null);
  const [tab, setTab] = useState("cost");
  const [saving, setSaving] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiTab, setAiTab] = useState<"diagnose" | "template" | "pitch">("diagnose");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiResult, setAiResult] = useState<any>(null);
  const [aiChatQ, setAiChatQ] = useState("");
  const [aiChatHistory, setAiChatHistory] = useState<{ q: string; a: string }[]>([]);
  const [aiChatLoading, setAiChatLoading] = useState(false);
  const saveTimer = useRef<any>(null);

  const loadBudget = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/budget/${userId}/${planId}`);
      const d = await r.json();
      if (d.status === "not_found" || !d.budget) { setNotFound(true); return; }
      setBudget(d.budget);
      if (d.budget.visible_tabs?.length) setTab(d.budget.visible_tabs[0]);
      if (d.budget.ai_result) setAiResult(d.budget.ai_result);
      if (d.budget.ai_chat_history?.length) setAiChatHistory(d.budget.ai_chat_history);
    } catch { setNotFound(true); }
  }, [userId, planId]);

  useEffect(() => { loadBudget(); }, [loadBudget]);

  const saveBudget = useCallback(async (data: Budget) => {
    setSaving(true);
    try {
      const r = await fetch(`${API}/api/budget/${userId}/${planId}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_costs: data.project_costs, business_finance: data.business_finance,
          competition_budget: data.competition_budget, funding_plan: data.funding_plan,
          name: data.name, visible_tabs: data.visible_tabs,
        }),
      });
      const d = await r.json();
      if (d.budget) setBudget(d.budget);
    } catch {} finally { setSaving(false); }
  }, [userId, planId]);

  const autoSave = (data: Budget) => {
    setBudget(data);
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => saveBudget(data), 1200);
  };

  /* ── Cost helpers ── */
  const updateCostItem = (ci: number, ii: number, field: keyof CostItem, value: any) => {
    if (!budget) return;
    const cats = [...budget.project_costs.categories];
    const items = [...cats[ci].items];
    items[ii] = { ...items[ii], [field]: value };
    if (field === "unit_price" || field === "quantity") items[ii].total = Math.round((items[ii].unit_price || 0) * (items[ii].quantity || 0) * 100) / 100;
    cats[ci] = { ...cats[ci], items };
    autoSave({ ...budget, project_costs: { categories: cats } });
  };
  const addCostItem = (ci: number) => { if (!budget) return; const cats = [...budget.project_costs.categories]; cats[ci] = { ...cats[ci], items: [...cats[ci].items, { name: "", unit_price: 0, quantity: 1, total: 0, note: "", priority: "必要", cost_type: "once" }] }; autoSave({ ...budget, project_costs: { categories: cats } }); };
  const removeCostItem = (ci: number, ii: number) => { if (!budget) return; const cats = [...budget.project_costs.categories]; cats[ci] = { ...cats[ci], items: cats[ci].items.filter((_, i) => i !== ii) }; autoSave({ ...budget, project_costs: { categories: cats } }); };
  const addCategory = () => { if (!budget) return; autoSave({ ...budget, project_costs: { categories: [...budget.project_costs.categories, { name: "新类别", items: [] }] } }); };

  /* ── Revenue helpers ── */
  const updateRevenue = (idx: number, field: keyof RevenueStream, value: any) => {
    if (!budget) return;
    const streams = [...budget.business_finance.revenue_streams];
    streams[idx] = { ...streams[idx], [field]: value };
    streams[idx].monthly_revenue = Math.round((streams[idx].monthly_users || 0) * (streams[idx].price || 0) * (streams[idx].conversion_rate || 1) * 100) / 100;
    autoSave({ ...budget, business_finance: { ...budget.business_finance, revenue_streams: streams } });
  };
  const addRevenue = () => { if (!budget) return; autoSave({ ...budget, business_finance: { ...budget.business_finance, revenue_streams: [...budget.business_finance.revenue_streams, { name: "", monthly_users: 0, price: 0, conversion_rate: 1, monthly_revenue: 0 }] } }); };
  const removeRevenue = (idx: number) => { if (!budget) return; autoSave({ ...budget, business_finance: { ...budget.business_finance, revenue_streams: budget.business_finance.revenue_streams.filter((_, i) => i !== idx) } }); };

  /* ── Scenario helpers ── */
  const updateScenario = (key: string, field: string, value: number) => {
    if (!budget) return;
    const models = { ...budget.business_finance.scenario_models };
    models[key] = { ...models[key], [field]: value };
    autoSave({ ...budget, business_finance: { ...budget.business_finance, scenario_models: models } });
  };

  /* ── Competition helpers ── */
  const updateCompItem = (idx: number, field: keyof CompItem, value: any) => { if (!budget) return; const items = [...budget.competition_budget.items]; items[idx] = { ...items[idx], [field]: value }; autoSave({ ...budget, competition_budget: { ...budget.competition_budget, items } }); };
  const addCompItem = () => { if (!budget) return; autoSave({ ...budget, competition_budget: { ...budget.competition_budget, items: [...budget.competition_budget.items, { name: "", amount: 0, note: "" }] } }); };
  const removeCompItem = (idx: number) => { if (!budget) return; autoSave({ ...budget, competition_budget: { ...budget.competition_budget, items: budget.competition_budget.items.filter((_, i) => i !== idx) } }); };

  /* ── Funding source helpers ── */
  const updateFundSrc = (idx: number, field: keyof FundingSource, value: any) => {
    if (!budget) return;
    const srcs = [...(budget.competition_budget.funding_sources || [])];
    srcs[idx] = { ...srcs[idx], [field]: value };
    autoSave({ ...budget, competition_budget: { ...budget.competition_budget, funding_sources: srcs } });
  };
  const addFundSrc = () => { if (!budget) return; autoSave({ ...budget, competition_budget: { ...budget.competition_budget, funding_sources: [...(budget.competition_budget.funding_sources || []), { name: "", amount: 0, note: "" }] } }); };

  /* ── AI ── */
  const saveAiData = useCallback(async (result: any, chatHist: { q: string; a: string }[]) => {
    try {
      await fetch(`${API}/api/budget/${userId}/${planId}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ai_result: result, ai_chat_history: chatHist }),
      });
    } catch {}
  }, [userId, planId]);

  const requestAI = async () => {
    setAiLoading(true);
    try {
      const r = await fetch(`${API}/api/budget/${userId}/${planId}/ai-suggest`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_description: "", project_type: "" }) });
      const d = await r.json();
      const result = d.suggestions || null;
      setAiResult(result);
      saveAiData(result, aiChatHistory);
    } catch {} finally { setAiLoading(false); }
  };

  const sendAiChat = async () => {
    const q = aiChatQ.trim(); if (!q) return;
    setAiChatLoading(true); setAiChatQ("");
    try {
      const r = await fetch(`${API}/api/budget/${userId}/${planId}/ai-chat`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q }) });
      const d = await r.json();
      const newHistory = [...aiChatHistory, { q, a: d.reply || "暂无回复" }];
      setAiChatHistory(newHistory);
      saveAiData(aiResult, newHistory);
    } catch {
      const newHistory = [...aiChatHistory, { q, a: "请求失败" }];
      setAiChatHistory(newHistory);
    } finally { setAiChatLoading(false); }
  };

  /* ── Export CSV ── */
  const exportCSV = () => {
    if (!budget) return;
    let csv = "\uFEFF方案: " + budget.name + "\n项目成本预算\n类别,项目,单价,数量,小计,类型,备注\n";
    for (const cat of budget.project_costs.categories) for (const item of cat.items) csv += `${cat.name},${item.name},${item.unit_price},${item.quantity},${item.total},${item.cost_type || ""},${item.note}\n`;
    csv += `\n合计,,,,${sm.project_cost_total}\n`;
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = `${budget.name}.csv`; a.click(); URL.revokeObjectURL(url);
  };

  /* ── Computed ── */
  const sm = budget?.summary || {} as Summary;
  const hg = healthGrade(sm.health_score || 0);
  const scenarios = budget?.business_finance?.scenario_results || {};
  const scenarioModels = budget?.business_finance?.scenario_models || {};
  const visibleTabs = budget?.visible_tabs || ["cost", "biz", "comp", "compare", "fund"];

  /* ── Render: Cost Pie ── */
  const renderPie = () => {
    if (!budget) return null;
    const data = budget.project_costs.categories.map((c, i) => ({ name: c.name, value: c.items.reduce((s, it) => s + (it.total || 0), 0), color: PIE_COLORS[i % PIE_COLORS.length] })).filter(d => d.value > 0);
    const total = data.reduce((s, d) => s + d.value, 0);
    if (total === 0) return null;
    let cum = 0;
    const slices = data.map(d => {
      const angle = (d.value / total) * 360; const start = cum; cum += angle;
      const s1 = Math.PI * (start - 90) / 180, s2 = Math.PI * (cum - 90) / 180;
      const x1 = 100 + 80 * Math.cos(s1), y1 = 100 + 80 * Math.sin(s1), x2 = 100 + 80 * Math.cos(s2), y2 = 100 + 80 * Math.sin(s2);
      return { ...d, path: `M100,100 L${x1},${y1} A80,80 0 ${angle > 180 ? 1 : 0},1 ${x2},${y2} Z`, pct: Math.round((d.value / total) * 100) };
    });
    return (
      <div className="bw-pie-wrap">
        <svg width={180} height={180} viewBox="0 0 200 200">
          {slices.map((s, i) => <path key={i} d={s.path} fill={s.color} opacity=".85"><title>{s.name}: {cny(s.value)}</title></path>)}
          <circle cx="100" cy="100" r="40" fill="var(--bw-card)" />
          <text x="100" y="96" textAnchor="middle" fill="var(--bw-text)" fontSize="13" fontWeight="700">{cny(total)}</text>
          <text x="100" y="110" textAnchor="middle" fill="var(--bw-muted)" fontSize="9">总成本</text>
        </svg>
        <div className="bw-pie-legend">{slices.map((s, i) => <div key={i} className="bw-pie-leg-item"><div className="bw-pie-dot" style={{ background: s.color }} /><span>{s.name} {s.pct}%</span></div>)}</div>
      </div>
    );
  };

  /* ── Render: Cash Flow Chart ── */
  const renderCFChart = (scenarioKeys?: string[]) => {
    const keys = scenarioKeys || ["baseline"];
    const colors: Record<string, string> = { conservative: "#ff6b6b", baseline: "#6b8aff", optimistic: "#51cf66" };
    const labels: Record<string, string> = { conservative: "悲观", baseline: "基准", optimistic: "乐观" };
    const W = 640, H = 220, PX = 44, PY = 24;
    const allVals: number[] = [];
    for (const k of keys) { const proj = scenarios[k]?.cash_flow_projection || []; for (const p of proj) allVals.push(p.revenue, p.cost, p.cumulative); }
    if (allVals.length === 0) return <div className="bw-empty-hint">暂无数据，请先填写收入来源</div>;
    const maxV = Math.max(...allVals, 1), minV = Math.min(...allVals, 0), range = maxV - minV || 1;
    const x = (m: number) => PX + ((m - 1) / 11) * (W - PX * 2);
    const y = (v: number) => PY + (1 - (v - minV) / range) * (H - PY * 2);
    const zeroY = y(0);
    return (
      <div className="bw-cf-chart">
        <svg viewBox={`0 0 ${W} ${H + 24}`}>
          <line x1={PX} y1={zeroY} x2={W - PX} y2={zeroY} stroke="var(--bw-border)" strokeDasharray="4" />
          <text x={PX - 4} y={zeroY + 3} textAnchor="end" fill="var(--bw-muted)" fontSize="9">0</text>
          {keys.map(k => {
            const proj = scenarios[k]?.cash_flow_projection || [];
            if (proj.length === 0) return null;
            const cumLine = proj.map(p => `${x(p.month)},${y(p.cumulative)}`).join(" ");
            const be = scenarios[k]?.months_to_breakeven;
            return (
              <g key={k}>
                <polyline points={cumLine} fill="none" stroke={colors[k] || "#999"} strokeWidth="2.5" strokeLinejoin="round" />
                {be && <><line x1={x(be)} y1={PY} x2={x(be)} y2={H - PY} stroke={colors[k]} strokeDasharray="3" strokeWidth="1.2" /><text x={x(be)} y={PY - 5} textAnchor="middle" fill={colors[k]} fontSize="9" fontWeight="600">{labels[k]} 第{be}月</text></>}
              </g>
            );
          })}
          {Array.from({ length: 12 }, (_, i) => <text key={i} x={x(i + 1)} y={H + 14} textAnchor="middle" fill="var(--bw-muted)" fontSize="9">{i + 1}月</text>)}
          {keys.length > 1 && keys.map((k, i) => <g key={`lg-${k}`}><rect x={W - PX - 48 * (keys.length - i)} y="4" width="8" height="8" rx="2" fill={colors[k]} /><text x={W - PX - 48 * (keys.length - i) + 12} y="12" fill="var(--bw-muted)" fontSize="9">{labels[k]}</text></g>)}
        </svg>
      </div>
    );
  };

  if (notFound) return <div className="bw-page"><div className="bw-loading-center">方案不存在，{onBack ? <button className="bw-link" onClick={onBack}>返回列表</button> : <Link href="/budget" className="bw-link">返回列表</Link>}</div></div>;
  if (!budget) return <div className="bw-page"><div className="bw-loading-center">加载预算数据...</div></div>;

  return (
    <div className="bw-workbench">
      {/* Header */}
      <header className="bw-wb-header">
        {onBack ? <button className="bw-back-link" onClick={onBack}>返回列表</button> : <Link href="/budget" className="bw-back-link">返回列表</Link>}
        <input className="bw-wb-title-input" value={budget.name} onChange={e => autoSave({ ...budget, name: e.target.value })} />
        <span className="bw-save-status">{saving ? "保存中..." : budget.updated_at ? `已保存 ${new Date(budget.updated_at).toLocaleTimeString("zh-CN")}` : ""}</span>
        <div className="bw-wb-header-actions">
          <button className="bw-btn-outline" onClick={() => saveBudget(budget)}>保存</button>
          <button className="bw-btn-outline" onClick={exportCSV}>导出</button>
        </div>
      </header>

      {/* Summary Cards */}
      <div className="bw-summary-strip">
        <div className="bw-sum-card"><div className="bw-sum-label">总投入</div><div className="bw-sum-value">{cny(sm.total_investment || 0)}</div><div className="bw-sum-sub">项目 {cny(sm.project_cost_total || 0)} + 比赛 {cny(sm.competition_cost_total || 0)}</div></div>
        <div className="bw-sum-card"><div className="bw-sum-label">基准月收入</div><div className="bw-sum-value">{cny(sm.baseline_monthly_revenue || 0)}</div><div className="bw-sum-sub">年净收入 {cny(sm.baseline_annual_net || 0)}</div></div>
        <div className="bw-sum-card"><div className="bw-sum-label">盈亏平衡</div><div className="bw-sum-value">{sm.breakeven_baseline ? `第 ${sm.breakeven_baseline} 月` : "未达成"}</div><div className="bw-sum-sub">乐观 {sm.breakeven_fastest || "—"} / 悲观 {sm.breakeven_slowest || "—"}</div></div>
        <div className="bw-sum-card"><div className="bw-sum-label">资金缺口</div><div className="bw-sum-value" style={{ color: (sm.funding_gap || 0) > 0 ? "#ff6b6b" : "#51cf66" }}>{cny(sm.funding_gap || 0)}</div></div>
        <div className="bw-sum-card bw-sum-grade"><div className="bw-sum-label">健康度</div><div className="bw-sum-value bw-grade-num" style={{ color: hg.color }}>{hg.grade}</div><div className="bw-sum-sub">{sm.health_score || 0}/100</div></div>
      </div>

      {/* Tab bar */}
      <div className="bw-tab-bar">
        {visibleTabs.map(k => (
          <button key={k} className={`bw-tab-btn${tab === k ? " active" : ""}`} onClick={() => setTab(k)}>{TAB_LABELS[k] || k}</button>
        ))}
      </div>

      {/* Tab content */}
      <div className="bw-tab-content">
        {/* ── TAB: 成本中心 ── */}
        {tab === "cost" && (
          <div className="bw-fade-in">
            {budget.project_costs.categories.map((cat, ci) => {
              const catTotal = cat.items.reduce((s, it) => s + (it.total || 0), 0);
              return (
                <div key={ci} className="bw-card">
                  <div className="bw-card-head">
                    <input className="bw-card-title-input" value={cat.name} onChange={e => { const cats = [...budget.project_costs.categories]; cats[ci] = { ...cats[ci], name: e.target.value }; autoSave({ ...budget, project_costs: { categories: cats } }); }} />
                    <span className="bw-card-badge">{cny(catTotal)}</span>
                  </div>
                  <table className="bw-table">
                    <thead><tr><th>名称</th><th className="num">单价</th><th className="num">数量</th><th className="num">小计</th><th>类型</th><th>优先级</th><th>备注</th><th></th></tr></thead>
                    <tbody>
                      {cat.items.map((item, ii) => (
                        <tr key={ii}>
                          <td><input value={item.name} onChange={e => updateCostItem(ci, ii, "name", e.target.value)} placeholder="项目名" /></td>
                          <td className="num"><input type="number" value={item.unit_price || ""} onChange={e => updateCostItem(ci, ii, "unit_price", parseFloat(e.target.value) || 0)} /></td>
                          <td className="num"><input type="number" value={item.quantity || ""} onChange={e => updateCostItem(ci, ii, "quantity", parseFloat(e.target.value) || 0)} /></td>
                          <td className="num bw-bold">{cny(item.total || 0)}</td>
                          <td><select value={item.cost_type || "once"} onChange={e => updateCostItem(ci, ii, "cost_type", e.target.value)}><option value="once">一次性</option><option value="monthly">月度</option></select></td>
                          <td><select value={item.priority || "必要"} onChange={e => updateCostItem(ci, ii, "priority", e.target.value)}><option>必要</option><option>可选</option></select></td>
                          <td><input value={item.note} onChange={e => updateCostItem(ci, ii, "note", e.target.value)} placeholder="备注" /></td>
                          <td><button className="bw-del" onClick={() => removeCostItem(ci, ii)}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg></button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <button className="bw-add-row" onClick={() => addCostItem(ci)}>+ 添加项目</button>
                </div>
              );
            })}
            <button className="bw-add-row" onClick={addCategory}>+ 添加成本类别</button>
            {renderPie()}
            <div className="bw-total-bar"><span>项目成本合计</span><strong>{cny(sm.project_cost_total || 0)}</strong></div>
          </div>
        )}

        {/* ── TAB: 收入模型 ── */}
        {tab === "biz" && (
          <div className="bw-fade-in">
            <div className="bw-section">
              <h3 className="bw-section-title">收入来源</h3>
              {budget.business_finance.revenue_streams.map((s, i) => (
                <div key={i} className="bw-rev-card">
                  <div className="bw-rev-fields">
                    <div className="bw-field"><label>名称</label><input value={s.name} onChange={e => updateRevenue(i, "name", e.target.value)} placeholder="如：会员订阅" /></div>
                    <div className="bw-field"><label>月活用户</label><input type="number" value={s.monthly_users || ""} onChange={e => updateRevenue(i, "monthly_users", parseFloat(e.target.value) || 0)} /></div>
                    <div className="bw-field"><label>单价 (¥)</label><input type="number" value={s.price || ""} onChange={e => updateRevenue(i, "price", parseFloat(e.target.value) || 0)} /></div>
                    <div className="bw-field"><label>转化率</label><input type="number" step="0.01" value={s.conversion_rate || ""} onChange={e => updateRevenue(i, "conversion_rate", parseFloat(e.target.value) || 0)} /></div>
                    <div className="bw-rev-result">= {cny(s.monthly_revenue || 0)}/月</div>
                    <button className="bw-del" onClick={() => removeRevenue(i)}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg></button>
                  </div>
                </div>
              ))}
              <button className="bw-add-row" onClick={addRevenue}>+ 添加收入来源</button>
            </div>
            <div className="bw-section">
              <h3 className="bw-section-title">三档情景参数</h3>
              <div className="bw-scenario-grid">
                <div className="bw-sg-header"><div></div><div className="bw-sg-label" style={{ color: "#ff6b6b" }}>悲观</div><div className="bw-sg-label" style={{ color: "#6b8aff" }}>基准</div><div className="bw-sg-label" style={{ color: "#51cf66" }}>乐观</div></div>
                {([["growth_rate_monthly", "月增长率"], ["fixed_costs_monthly", "月固定成本 (¥)"], ["variable_cost_per_user", "单用户变动成本 (¥)"], ["revenue_multiplier", "收入系数"], ["conversion_multiplier", "转化系数"]] as const).map(([field, label]) => (
                  <div key={field} className="bw-sg-row">
                    <div className="bw-sg-rlabel">{label}</div>
                    {(["conservative", "baseline", "optimistic"] as const).map(k => (
                      <div key={k} className="bw-sg-cell"><input type="number" step="0.01" value={(scenarioModels[k] as any)?.[field] ?? ""} onChange={e => updateScenario(k, field, parseFloat(e.target.value) || 0)} /></div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
            <div className="bw-section">
              <h3 className="bw-section-title">12个月累计现金流</h3>
              {renderCFChart(["conservative", "baseline", "optimistic"])}
            </div>
            <div className="bw-scenario-cards">
              {(["conservative", "baseline", "optimistic"] as const).map(k => {
                const res = scenarios[k]; if (!res) return null;
                const c: Record<string, string> = { conservative: "#ff6b6b", baseline: "#6b8aff", optimistic: "#51cf66" };
                const l: Record<string, string> = { conservative: "悲观", baseline: "基准", optimistic: "乐观" };
                return (
                  <div key={k} className="bw-sc-card" style={{ borderTopColor: c[k] }}>
                    <div className="bw-sc-title" style={{ color: c[k] }}>{l[k]}</div>
                    <div className="bw-sc-row">年收入 <strong>{cny(res.annual_revenue)}</strong></div>
                    <div className="bw-sc-row">年支出 <strong>{cny(res.annual_cost)}</strong></div>
                    <div className="bw-sc-row">年净利 <strong style={{ color: res.annual_net >= 0 ? "#51cf66" : "#ff6b6b" }}>{cny(res.annual_net)}</strong></div>
                    <div className="bw-sc-row">盈亏平衡 <strong>{res.months_to_breakeven ? `第${res.months_to_breakeven}月` : "未达成"}</strong></div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ── TAB: 比赛专项 ── */}
        {tab === "comp" && (
          <div className="bw-fade-in">
            <div className="bw-card">
              <div className="bw-card-head"><span className="bw-bold">比赛预算明细</span><span className="bw-card-badge">{cny(sm.competition_cost_total || 0)}</span></div>
              <table className="bw-table">
                <thead><tr><th>项目</th><th className="num">金额 (¥)</th><th>备注</th><th></th></tr></thead>
                <tbody>
                  {budget.competition_budget.items.map((item, i) => (
                    <tr key={i}>
                      <td><input value={item.name} onChange={e => updateCompItem(i, "name", e.target.value)} /></td>
                      <td className="num"><input type="number" value={item.amount || ""} onChange={e => updateCompItem(i, "amount", parseFloat(e.target.value) || 0)} /></td>
                      <td><input value={item.note} onChange={e => updateCompItem(i, "note", e.target.value)} placeholder="备注" /></td>
                      <td><button className="bw-del" onClick={() => removeCompItem(i)}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button className="bw-add-row" onClick={addCompItem}>+ 添加项目</button>
            </div>
            <div className="bw-section">
              <h3 className="bw-section-title">资金来源</h3>
              {(budget.competition_budget.funding_sources || []).map((src, i) => (
                <div key={i} className="bw-fund-row">
                  <input value={src.name} onChange={e => updateFundSrc(i, "name", e.target.value)} placeholder="来源名称" />
                  <input type="number" value={src.amount || ""} onChange={e => updateFundSrc(i, "amount", parseFloat(e.target.value) || 0)} placeholder="金额" />
                  <input value={src.note} onChange={e => updateFundSrc(i, "note", e.target.value)} placeholder="备注" />
                </div>
              ))}
              <button className="bw-add-row" onClick={addFundSrc}>+ 添加资金来源</button>
            </div>
          </div>
        )}

        {/* ── TAB: 情景分析 ── */}
        {tab === "compare" && (
          <div className="bw-fade-in">
            <h3 className="bw-section-title">三档情景横向对比</h3>
            <div className="bw-card">
              <table className="bw-table bw-compare-tbl">
                <thead><tr><th>指标</th><th style={{ color: "#ff6b6b" }}>悲观</th><th style={{ color: "#6b8aff" }}>基准</th><th style={{ color: "#51cf66" }}>乐观</th></tr></thead>
                <tbody>
                  {[
                    ["月增长率", (k: string) => `${(((scenarioModels[k] as any)?.growth_rate_monthly || 0) * 100).toFixed(1)}%`],
                    ["收入系数", (k: string) => `×${(scenarioModels[k] as any)?.revenue_multiplier || 0}`],
                    ["12个月总收入", (k: string) => cny(scenarios[k]?.annual_revenue || 0)],
                    ["12个月总支出", (k: string) => cny(scenarios[k]?.annual_cost || 0)],
                    ["12个月净利润", (k: string) => cny(scenarios[k]?.annual_net || 0)],
                    ["盈亏平衡", (k: string) => scenarios[k]?.months_to_breakeven ? `第 ${scenarios[k]?.months_to_breakeven} 月` : "未达成"],
                  ].map(([label, fn], i) => (
                    <tr key={i}><td className="bw-bold">{label as string}</td>{(["conservative", "baseline", "optimistic"] as const).map(k => <td key={k}>{(fn as (k: string) => string)(k)}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="bw-section" style={{ marginTop: 24 }}>
              <h3 className="bw-section-title">累计现金流对比</h3>
              {renderCFChart(["conservative", "baseline", "optimistic"])}
            </div>
          </div>
        )}

        {/* ── TAB: 资金规划 ── */}
        {tab === "fund" && (
          <div className="bw-fade-in">
            <div className="bw-fund-overview">
              <div className="bw-fund-ov-card"><div className="bw-fund-ov-label">项目成本</div><div className="bw-fund-ov-value">{cny(sm.project_cost_total || 0)}</div></div>
              <div className="bw-fund-ov-card"><div className="bw-fund-ov-label">比赛预算</div><div className="bw-fund-ov-value">{cny(sm.competition_cost_total || 0)}</div></div>
              <div className="bw-fund-ov-card bw-fund-ov-accent"><div className="bw-fund-ov-label">总启动资金</div><div className="bw-fund-ov-value">{cny(sm.total_investment || 0)}</div></div>
              <div className="bw-fund-ov-card"><div className="bw-fund-ov-label">资金缺口</div><div className="bw-fund-ov-value" style={{ color: (sm.funding_gap || 0) > 0 ? "#ff6b6b" : "#51cf66" }}>{cny(sm.funding_gap || 0)}</div></div>
            </div>
            <div className="bw-section">
              <h3 className="bw-section-title">资金来源构成</h3>
              {(budget.competition_budget.funding_sources || []).length > 0 ? (
                <div className="bw-fund-list">
                  {(budget.competition_budget.funding_sources || []).map((src, i) => (
                    <div key={i} className="bw-fund-list-item"><span className="bw-fund-list-name">{src.name || "未命名"}</span><span className="bw-fund-list-amt">{cny(src.amount || 0)}</span><span className="bw-fund-list-note">{src.note}</span></div>
                  ))}
                </div>
              ) : <div className="bw-empty-hint">请在"比赛专项"Tab中添加资金来源</div>}
            </div>
            <div className="bw-section">
              <h3 className="bw-section-title">融资备注</h3>
              <textarea className="bw-textarea" value={budget.funding_plan?.fundraising_notes || ""} onChange={e => autoSave({ ...budget, funding_plan: { ...budget.funding_plan, fundraising_notes: e.target.value } })} placeholder="融资节奏、种子轮计划、补贴申请进度..." rows={4} />
            </div>
          </div>
        )}
      </div>

      {/* ── AI Floating Bubble ── */}
      <button className="bw-ai-float" onClick={() => { setAiOpen(true); if (!aiResult) requestAI(); }} title="AI 财务助手">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
      </button>

      {/* ── AI Drawer ── */}
      {aiOpen && (
        <>
          <div className="bw-ai-overlay" onClick={() => setAiOpen(false)} />
          <div className="bw-ai-drawer">
            <div className="bw-ai-drawer-head"><strong>AI 财务助手</strong><button className="bw-ai-close" onClick={() => setAiOpen(false)}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg></button></div>
            <div className="bw-ai-tabs">
              {(["diagnose", "template", "pitch"] as const).map(t => <button key={t} className={`bw-ai-tab${aiTab === t ? " active" : ""}`} onClick={() => setAiTab(t)}>{{ diagnose: "预算诊断", template: "生成模板", pitch: "答辩口径" }[t]}</button>)}
            </div>
            <div className="bw-ai-body">
              {aiLoading ? <div className="bw-ai-thinking">AI 正在分析...</div> : !aiResult ? (
                <div className="bw-empty-hint"><button className="bw-btn-primary" onClick={requestAI}>开始 AI 分析</button></div>
              ) : (
                <>
                  {aiTab === "diagnose" && aiResult.diagnosis && (
                    <div>{aiResult.diagnosis.missing_items?.length > 0 && <div className="bw-ai-block"><h4>缺失成本项</h4><ul>{aiResult.diagnosis.missing_items.map((it: string, i: number) => <li key={i}>{it}</li>)}</ul></div>}
                    {aiResult.diagnosis.unreasonable_flags?.length > 0 && <div className="bw-ai-block bw-ai-warn"><h4>不合理假设</h4><ul>{aiResult.diagnosis.unreasonable_flags.map((it: string, i: number) => <li key={i}>{it}</li>)}</ul></div>}
                    {aiResult.diagnosis.risk_warnings?.length > 0 && <div className="bw-ai-block bw-ai-risk"><h4>风险提示</h4><ul>{aiResult.diagnosis.risk_warnings.map((it: string, i: number) => <li key={i}>{it}</li>)}</ul></div>}</div>
                  )}
                  {aiTab === "template" && aiResult.template && (
                    <div>{aiResult.template.suggested_costs?.length > 0 && <div className="bw-ai-block"><h4>建议成本项</h4><ul>{aiResult.template.suggested_costs.map((c: any, i: number) => <li key={i}><strong>{c.name}</strong>: {cny(c.estimated || 0)}</li>)}</ul></div>}
                    {aiResult.template.revenue_model && <div className="bw-ai-block"><h4>收入模式</h4><p>{aiResult.template.revenue_model}</p></div>}
                    {aiResult.template.scenario_advice && <div className="bw-ai-block"><h4>情景建议</h4><p>{aiResult.template.scenario_advice}</p></div>}</div>
                  )}
                  {aiTab === "pitch" && (
                    <div>{aiResult.pitch_summary && <div className="bw-ai-block"><h4>答辩预算说明</h4><ReactMarkdown remarkPlugins={[remarkGfm]}>{aiResult.pitch_summary}</ReactMarkdown></div>}
                    {aiResult.faq?.length > 0 && <div className="bw-ai-block"><h4>评委追问</h4>{aiResult.faq.map((f: any, i: number) => <div key={i} className="bw-ai-faq"><div className="bw-ai-faq-q">Q: {f.question}</div><div className="bw-ai-faq-a">A: {f.suggested_answer}</div></div>)}</div>}</div>
                  )}
                </>
              )}
              <button className="bw-btn-outline bw-btn-sm" onClick={requestAI} disabled={aiLoading} style={{ marginTop: 12 }}>{aiLoading ? "分析中..." : "重新分析"}</button>
              {aiChatHistory.length > 0 && <div className="bw-ai-chat-list">{aiChatHistory.map((h, i) => <div key={i} className="bw-ai-chat-item"><div className="bw-ai-chat-q">{h.q}</div><div className="bw-ai-chat-a"><ReactMarkdown remarkPlugins={[remarkGfm]}>{h.a}</ReactMarkdown></div></div>)}</div>}
            </div>
            <div className="bw-ai-input"><input value={aiChatQ} onChange={e => setAiChatQ(e.target.value)} placeholder="追问财务问题..." onKeyDown={e => { if (e.key === "Enter") sendAiChat(); }} /><button onClick={sendAiChat} disabled={aiChatLoading || !aiChatQ.trim()}>{aiChatLoading ? "..." : "发送"}</button></div>
          </div>
        </>
      )}
    </div>
  );
}
