"use client";

import React, { useEffect, useMemo, useState } from "react";

type Verdict = { level: "red" | "yellow" | "green" | "gray"; score?: number; reason?: string };
type Module = {
  module: string;
  title: string;
  inputs?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  verdict?: Verdict;
  framework_explain?: string;
  suggestions?: string[];
  missing_inputs?: Array<{ field: string; hint: string; target_tab?: string }>;
};

type BaselineMeta = {
  industry?: string;
  source?: "seed" | "web" | "teacher_edit" | "hardcoded" | string;
  updated_at?: string;
  evidence_count?: number;
};

type Report = {
  report_id: string;
  user_id: string;
  plan_id?: string;
  project_id?: string;
  conversation_id?: string;
  industry?: string;
  generated_at: string;
  modules: Module[];
  merged_evidence?: Record<string, number>;
  inputs_snapshot?: Record<string, unknown>;
  baseline_meta?: BaselineMeta;
};

const SOURCE_LABEL: Record<string, string> = {
  seed: "内置基线",
  web: "联网更新",
  teacher_edit: "老师标注",
  hardcoded: "内置兜底",
};

function formatMetaDate(iso?: string): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  } catch {
    return "";
  }
}

export interface FinanceReportViewProps {
  apiBase: string;
  userId: string;
  planId?: string;
  projectId?: string;
  conversationId?: string;
  industryHint?: string;
  onJumpBudget?: (targetTab?: string) => void;
}

const MODULE_ORDER = [
  "finance_summary",
  "unit_economics",
  "cash_flow",
  "rationality",
  "market_size",
  "pricing_framework",
  "funding_stage",
];

// ─── Dock 风格线描图标（stroke=2 / round / 19x19） ──────────────────────
type IconProps = { size?: number };
const baseSvg = (size = 19) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none" as const,
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
});
const IconUnitEconomics: React.FC<IconProps> = ({ size }) => (
  <svg {...baseSvg(size)}>
    <path d="M4 20h16" />
    <rect x="6" y="13" width="2.5" height="5" rx="0.5" />
    <rect x="11" y="8" width="2.5" height="10" rx="0.5" />
    <rect x="16" y="4" width="2.5" height="14" rx="0.5" />
  </svg>
);
const IconCashFlow: React.FC<IconProps> = ({ size }) => (
  <svg {...baseSvg(size)}>
    <path d="M3 16c3-6 6-6 9 0s6 6 9 0" />
    <circle cx="12" cy="5" r="2" />
    <path d="M12 3v4" />
  </svg>
);
const IconScale: React.FC<IconProps> = ({ size }) => (
  <svg {...baseSvg(size)}>
    <path d="M12 4v16" />
    <path d="M5 20h14" />
    <path d="M5 9l3-5 3 5" />
    <path d="M13 9l3-5 3 5" />
    <path d="M5 9a3 3 0 006 0" />
    <path d="M13 9a3 3 0 006 0" />
  </svg>
);
const IconGlobe: React.FC<IconProps> = ({ size }) => (
  <svg {...baseSvg(size)}>
    <circle cx="12" cy="12" r="8" />
    <path d="M4 12h16" />
    <path d="M12 4c3 3 3 13 0 16" />
    <path d="M12 4c-3 3-3 13 0 16" />
  </svg>
);
const IconTag: React.FC<IconProps> = ({ size }) => (
  <svg {...baseSvg(size)}>
    <path d="M20.5 13.5l-8 8a1.5 1.5 0 01-2.1 0L3 14V5h9l8.5 8.5a1.5 1.5 0 010 2z" />
    <circle cx="8" cy="9" r="1.3" />
  </svg>
);
const IconTarget: React.FC<IconProps> = ({ size }) => (
  <svg {...baseSvg(size)}>
    <circle cx="12" cy="12" r="8" />
    <circle cx="12" cy="12" r="4.5" />
    <circle cx="12" cy="12" r="1.2" />
  </svg>
);
const IconRuler: React.FC<IconProps> = ({ size }) => (
  <svg {...baseSvg(size)}>
    <path d="M3 17l14-14 4 4L7 21z" />
    <path d="M7 11l2 2M10 8l2 2M13 5l2 2" />
  </svg>
);
const IconLock: React.FC<IconProps> = ({ size }) => (
  <svg {...baseSvg(size)}>
    <rect x="5" y="11" width="14" height="9" rx="2" />
    <path d="M8 11V7a4 4 0 018 0v4" />
  </svg>
);
const IconBriefcase: React.FC<IconProps> = ({ size }) => (
  <svg {...baseSvg(size)}>
    <rect x="3" y="7" width="18" height="13" rx="2" />
    <path d="M9 7V5a2 2 0 012-2h2a2 2 0 012 2v2" />
    <path d="M3 13h18" />
  </svg>
);
const IconRocket: React.FC<IconProps> = ({ size }) => (
  <svg {...baseSvg(size)}>
    <path d="M12 3c4 2 7 5 7 10l-3 3h-8l-3-3c0-5 3-8 7-10z" />
    <circle cx="12" cy="10" r="1.5" />
    <path d="M8 17c-1 2-1 4 0 4s2-1 3-2" />
    <path d="M16 17c1 2 1 4 0 4s-2-1-3-2" />
  </svg>
);
const IconHourglass: React.FC<IconProps> = ({ size }) => (
  <svg {...baseSvg(size)}>
    <path d="M6 3h12M6 21h12" />
    <path d="M6 3c0 5 12 7 12 12v6" />
    <path d="M18 3c0 5-12 7-12 12v6" />
  </svg>
);

const MODULE_ICON_COMP: Record<string, React.FC<IconProps>> = {
  finance_summary: IconBriefcase,
  unit_economics: IconUnitEconomics,
  cash_flow: IconCashFlow,
  rationality: IconScale,
  market_size: IconGlobe,
  pricing_framework: IconTag,
  funding_stage: IconTarget,
};

const VERDICT_LABEL: Record<string, string> = {
  red: "重点复核",
  yellow: "需补假设",
  green: "已分析",
  gray: "信息不足",
};

function MetricTable({ outputs }: { outputs: Record<string, unknown> | undefined }) {
  if (!outputs) return null;
  const keys = Object.keys(outputs).filter((k) => {
    const v = outputs[k];
    if (v === null || v === undefined) return false;
    if (Array.isArray(v) && v.length === 0) return false;
    if (
      k === "projection" ||
      k === "all_stages" ||
      k === "all_frameworks" ||
      k === "psm_survey_questions" ||
      k === "checks" ||
      k === "analysis_conclusion" ||
      k === "key_levers" ||
      k === "cashflow_implications" ||
      k === "market_implications" ||
      k === "stream_conclusions" ||
      k === "key_findings" ||
      k === "missing_fields"
    ) return false;
    return true;
  });
  if (keys.length === 0) return null;
  return (
    <table className="fr-metric-table">
      <tbody>
        {keys.map((k) => {
          const v = outputs[k];
          let disp: string;
          if (typeof v === "number") {
            if (k.includes("ratio") || k.includes("retention") || k.includes("margin")) {
              disp = v < 1 && v > -1 ? `${(v * 100).toFixed(1)}%` : v.toFixed(2);
            } else if (Math.abs(v) >= 1000) {
              disp = v.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
            } else {
              disp = v.toFixed(2);
            }
          } else if (Array.isArray(v)) {
            disp = JSON.stringify(v);
          } else if (typeof v === "object") {
            disp = JSON.stringify(v).slice(0, 60);
          } else {
            disp = String(v);
          }
          return (
            <tr key={k}>
              <td className="fr-metric-k">{k}</td>
              <td className="fr-metric-v">{disp}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function AnalysisBlocks({ outputs }: { outputs: Record<string, unknown> | undefined }) {
  if (!outputs) return null;
  const analysisConclusion = typeof outputs.analysis_conclusion === "string" ? outputs.analysis_conclusion : "";
  const keyFindings = Array.isArray(outputs.key_findings) ? outputs.key_findings.filter((v): v is string => typeof v === "string") : [];
  const streamConclusions = Array.isArray(outputs.stream_conclusions) ? outputs.stream_conclusions.filter((v): v is string => typeof v === "string") : [];
  const cashflowImplications = Array.isArray(outputs.cashflow_implications) ? outputs.cashflow_implications.filter((v): v is string => typeof v === "string") : [];
  const marketImplications = Array.isArray(outputs.market_implications) ? outputs.market_implications.filter((v): v is string => typeof v === "string") : [];
  const keyLevers = Array.isArray(outputs.key_levers) ? outputs.key_levers.filter((v): v is string => typeof v === "string") : [];
  const missingFields = Array.isArray(outputs.missing_fields) ? outputs.missing_fields.filter((v): v is string => typeof v === "string") : [];

  if (
    !analysisConclusion &&
    keyFindings.length === 0 &&
    streamConclusions.length === 0 &&
    cashflowImplications.length === 0 &&
    marketImplications.length === 0 &&
    keyLevers.length === 0 &&
    missingFields.length === 0
  ) {
    return null;
  }

  return (
    <div className="fr-section-analysis">
      {analysisConclusion && (
        <div className="fr-section-analysis-main">
          <div className="fr-section-label">结论</div>
          <p>{analysisConclusion}</p>
        </div>
      )}
      {keyFindings.length > 0 && (
        <div className="fr-section-analysis-sub">
          <div className="fr-section-label">关键判断</div>
          <ul>
            {keyFindings.map((item, idx) => <li key={idx}>{item}</li>)}
          </ul>
        </div>
      )}
      {streamConclusions.length > 0 && (
        <div className="fr-section-analysis-sub">
          <div className="fr-section-label">收入流判断</div>
          <ul>
            {streamConclusions.map((item, idx) => <li key={idx}>{item}</li>)}
          </ul>
        </div>
      )}
      {cashflowImplications.length > 0 && (
        <div className="fr-section-analysis-sub">
          <div className="fr-section-label">现金流影响</div>
          <ul>
            {cashflowImplications.map((item, idx) => <li key={idx}>{item}</li>)}
          </ul>
        </div>
      )}
      {marketImplications.length > 0 && (
        <div className="fr-section-analysis-sub">
          <div className="fr-section-label">市场规模含义</div>
          <ul>
            {marketImplications.map((item, idx) => <li key={idx}>{item}</li>)}
          </ul>
        </div>
      )}
      {keyLevers.length > 0 && (
        <div className="fr-section-analysis-sub">
          <div className="fr-section-label">敏感杠杆</div>
          <ul>
            {keyLevers.map((item, idx) => <li key={idx}>{item}</li>)}
          </ul>
        </div>
      )}
      {missingFields.length > 0 && (
        <div className="fr-section-analysis-sub">
          <div className="fr-section-label">仍需补齐</div>
          <div className="fr-section-missing">
            {missingFields.map((field, idx) => <span key={idx} className="fr-advisory-missing-chip">{field}</span>)}
          </div>
        </div>
      )}
    </div>
  );
}

function CashFlowChart({ projection }: { projection: Array<{ month: number; cash: number; revenue: number; net: number }> | undefined }) {
  if (!projection || projection.length === 0) return null;
  const w = 320;
  const h = 140;
  const pad = 24;
  const xs = projection.map((p) => p.month);
  const ys = projection.map((p) => p.cash);
  const minY = Math.min(0, ...ys);
  const maxY = Math.max(...ys, 0);
  const scaleX = (x: number) => pad + ((x - xs[0]) / (xs[xs.length - 1] - xs[0] || 1)) * (w - pad * 2);
  const scaleY = (y: number) => h - pad - ((y - minY) / (maxY - minY || 1)) * (h - pad * 2);
  const pathD = ys.map((y, i) => `${i === 0 ? "M" : "L"}${scaleX(xs[i]).toFixed(1)},${scaleY(y).toFixed(1)}`).join(" ");
  const zeroY = scaleY(0);
  return (
    <svg className="fr-cashflow-chart" viewBox={`0 0 ${w} ${h}`} width="100%">
      <line x1={pad} y1={zeroY} x2={w - pad} y2={zeroY} stroke="rgba(148,163,184,.35)" strokeDasharray="3,3" />
      <path d={pathD} fill="none" stroke="rgb(59,130,246)" strokeWidth={1.6} />
      <text x={pad} y={12} fontSize={10} fill="rgba(71,85,105,.8)">累计现金</text>
      <text x={pad} y={h - 4} fontSize={9} fill="rgba(71,85,105,.7)">月 1</text>
      <text x={w - pad - 14} y={h - 4} fontSize={9} fill="rgba(71,85,105,.7)">月 {xs[xs.length - 1]}</text>
    </svg>
  );
}

function ModuleCard({ mod, onJumpBudget }: { mod: Module; onJumpBudget?: (t?: string) => void }) {
  const [openExplain, setOpenExplain] = useState(false);
  const level = mod.verdict?.level || "gray";
  const IconComp = MODULE_ICON_COMP[mod.module] || IconRuler;
  return (
    <div className={`fr-section-card fr-verdict-${level}`}>
      <div className="fr-section-head">
        <span className="fr-section-icon fin-mod-icon" aria-hidden>
          <IconComp />
        </span>
        <span className="fr-section-title">{mod.title}</span>
        <span className={`fr-advisory-chip fr-chip-${level}`}>{VERDICT_LABEL[level] || level}</span>
      </div>
      {mod.verdict?.reason && <div className="fr-section-reason">{mod.verdict.reason}</div>}
      {mod.module === "cash_flow" && (
        <CashFlowChart projection={(mod.outputs?.projection as { month: number; cash: number; revenue: number; net: number }[]) || []} />
      )}
      <AnalysisBlocks outputs={mod.outputs} />
      <MetricTable outputs={mod.outputs} />
      {mod.suggestions && mod.suggestions.length > 0 && (
        <div className="fr-section-suggestions">
          <div className="fr-section-label">建议</div>
          <ul>
            {mod.suggestions.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
      )}
      {mod.missing_inputs && mod.missing_inputs.length > 0 && (
        <div className="fr-section-missing">
          <div className="fr-section-label">缺失假设</div>
          {mod.missing_inputs.map((m, i) => (
            <button
              type="button"
              key={i}
              className="fr-advisory-missing-chip"
              title={m.hint}
              onClick={() => onJumpBudget && onJumpBudget(m.target_tab)}
            >
              {m.field}
            </button>
          ))}
        </div>
      )}
      {mod.framework_explain && (
        <div className="fr-section-explain-wrap">
          <button type="button" className="fr-section-explain-toggle" onClick={() => setOpenExplain((v) => !v)}>
            {openExplain ? "收起框架讲解" : "展开框架讲解"}
          </button>
          {openExplain && <div className="fr-section-explain">{mod.framework_explain}</div>}
        </div>
      )}
    </div>
  );
}

const FinanceReportView: React.FC<FinanceReportViewProps> = ({
  apiBase,
  userId,
  planId,
  projectId,
  conversationId,
  industryHint,
  onJumpBudget,
}) => {
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [status, setStatus] = useState<{ status: string; detail: string } | null>(null);

  const userKey = (userId || "").trim().toLowerCase();
  const canGenerate = Boolean(userKey);

  const fetchLatest = async () => {
    if (!userKey) return;
    try {
      const r = await fetch(`${apiBase}/api/finance/report/${encodeURIComponent(userKey)}`);
      const js = await r.json();
      if (js.status === "ok" && js.report) {
        setReport(js.report);
        setError("");
      } else if (js.status === "not_found") {
        setReport(null);
      }
    } catch (e) {
      console.warn("load finance report failed", e);
    }
  };

  useEffect(() => {
    fetchLatest();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase, userKey]);

  const doGenerate = async () => {
    if (!canGenerate) {
      setError("请先登录后再生成");
      return;
    }
    setLoading(true);
    setError("");
    setStatus({ status: "running", detail: "启动中..." });
    try {
      const r = await fetch(`${apiBase}/api/finance/report/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userKey,
          plan_id: planId,
          project_id: projectId,
          conversation_id: conversationId,
          industry_hint: industryHint || "",
          use_llm_explain: true,
        }),
      });
      const js = await r.json();
      if (js.status === "ok" && js.report) {
        setReport(js.report);
        setStatus({ status: "done", detail: "生成完成" });
      } else {
        setError(js.detail || js.status || "生成失败");
        setStatus({ status: "error", detail: js.detail || "失败" });
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      setStatus({ status: "error", detail: msg });
    } finally {
      setLoading(false);
    }
  };

  const modulesOrdered = useMemo(() => {
    if (!report) return [];
    const byId = new Map(report.modules.map((m) => [m.module, m]));
    return MODULE_ORDER.map((id) => byId.get(id)).filter(Boolean) as Module[];
  }, [report]);

  const verdictCounts = useMemo(() => {
    const out = { red: 0, yellow: 0, green: 0, gray: 0 };
    if (!report) return out;
    for (const m of report.modules) {
      const lv = m.verdict?.level || "gray";
      (out as Record<string, number>)[lv] = ((out as Record<string, number>)[lv] || 0) + 1;
    }
    return out;
  }, [report]);

  if (!userKey) {
    return (
      <div className="fr-report-empty">
        <div className="fr-report-empty-emoji fin-empty-icon"><IconLock size={36} /></div>
        <div className="fr-report-empty-title">请先登录</div>
        <div className="fr-report-empty-desc">财务分析报告需要用户登录才能生成和保存。</div>
      </div>
    );
  }

  if (!report && !loading) {
    return (
      <div className="fr-report-empty">
        <div className="fr-report-empty-emoji fin-empty-icon"><IconBriefcase size={36} /></div>
        <div className="fr-report-empty-title">还没有财务分析报告</div>
        <div className="fr-report-empty-desc">
          结合预算面板 + 对话内容跑 6 个财务建模模块（单位经济 / 现金流 / 假设自检 / TAM·SAM·SOM / 定价 /
          融资节奏），把计算过程和待补假设拆出来。
        </div>
        <button type="button" className="fr-report-generate-btn" onClick={doGenerate} disabled={!canGenerate}>
          <span className="fin-mod-icon-btn" aria-hidden><IconRocket size={16} /></span>
          生成财务分析报告
        </button>
        {error && <div className="fr-report-error">{error}</div>}
      </div>
    );
  }

  if (loading) {
    return (
      <div className="fr-report-empty">
        <div className="fr-report-empty-emoji fin-empty-icon fin-empty-icon-spin"><IconHourglass size={36} /></div>
        <div className="fr-report-empty-title">正在跑财务建模...</div>
        <div className="fr-report-empty-desc">
          {status?.detail || "预计 10-30 秒"}（LLM 润色会慢一些）
        </div>
      </div>
    );
  }

  if (!report) return null;

  return (
    <div className="fr-report-view">
      <div className="fr-report-header">
        <div>
          <div className="fr-report-header-title">财务分析报告</div>
          <div className="fr-report-header-sub">
            {report.industry} · 生成于 {report.generated_at.slice(0, 16).replace("T", " ")}
          </div>
          {report.baseline_meta && report.baseline_meta.source && (
            <div className="fr-report-baseline-bar" title="参考资料的来源与时效">
              <span className={`fr-advisory-source-chip fr-source-${report.baseline_meta.source}`}>
                参考资料：{SOURCE_LABEL[report.baseline_meta.source] || report.baseline_meta.source}
              </span>
              {report.baseline_meta.updated_at && (
                <span className="fr-advisory-source-date">
                  更新于 {formatMetaDate(report.baseline_meta.updated_at)}
                </span>
              )}
              {typeof report.baseline_meta.evidence_count === "number" && report.baseline_meta.evidence_count > 0 && (
                <span className="fr-advisory-source-evidence">
                  {report.baseline_meta.evidence_count} 条外部证据
                </span>
              )}
              {report.baseline_meta.source !== "web" && (
                <span className="fr-report-baseline-hint">
                  重新生成时若资料过期将自动联网刷新
                </span>
              )}
            </div>
          )}
        </div>
        <div className="fr-report-header-actions">
          <div className="fr-report-verdict-summary">
            {verdictCounts.green > 0 && <span className="fr-chip-green">{verdictCounts.green} 已分析</span>}
            {verdictCounts.yellow > 0 && <span className="fr-chip-yellow">{verdictCounts.yellow} 需补假设</span>}
            {verdictCounts.red > 0 && <span className="fr-chip-red">{verdictCounts.red} 重点复核</span>}
            {verdictCounts.gray > 0 && <span className="fr-chip-gray">{verdictCounts.gray} 待补</span>}
          </div>
          <button type="button" className="fr-report-regen-btn" onClick={doGenerate}>
            重新生成
          </button>
        </div>
      </div>
      <div className="fr-report-sections">
        {modulesOrdered.map((m) => (
          <ModuleCard key={m.module} mod={m} onJumpBudget={onJumpBudget} />
        ))}
      </div>
      {error && <div className="fr-report-error">{error}</div>}
    </div>
  );
};

export default FinanceReportView;
