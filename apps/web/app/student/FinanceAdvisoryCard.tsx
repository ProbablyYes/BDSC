"use client";

import React from "react";

type BaselineMeta = {
  industry?: string;
  source?: "seed" | "web" | "teacher_edit" | "hardcoded" | string;
  updated_at?: string;
  evidence_count?: number;
};

type FinanceCard = {
  module: string;
  title: string;
  inputs?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  verdict?: { level: "red" | "yellow" | "green" | "gray"; score?: number; reason?: string };
  framework_explain?: string;
  suggestions?: string[];
  missing_inputs?: Array<{ field: string; hint: string; target_tab?: string }>;
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

type FinanceAdvisory = {
  triggered: boolean;
  hits?: string[];
  cards?: FinanceCard[];
  industry?: string;
  evidence_for_diagnosis?: Record<string, number>;
};

export interface FinanceAdvisoryCardProps {
  advisory: FinanceAdvisory;
  onOpenReport?: () => void;
  onJumpBudget?: (targetTab?: string) => void;
}

const MODULE_ICON: Record<string, string> = {
  unit_economics: "📊",
  cash_flow: "💰",
  rationality: "⚖️",
  market_size: "🌍",
  pricing_framework: "🏷️",
  funding_stage: "🎯",
};

const VERDICT_LABEL: Record<string, string> = {
  red: "重点复核",
  yellow: "需补假设",
  green: "已分析",
  gray: "信息不足",
};

function fmtKV(k: string, v: unknown): string {
  if (v === null || v === undefined || v === "") return "";
  const keyMap: Record<string, string> = {
    arpu: "月 ARPU",
    gross_margin: "毛利率",
    avg_lifetime_months: "平均生命周期",
    ltv: "LTV",
    cac: "CAC",
    ltv_cac_ratio: "LTV/CAC",
    payback_period_months: "Payback",
    monthly_price: "月价",
    monthly_retention: "月留存",
    reference_range: "参考区间",
    reference_gap_ratio: "参考差异",
    cost_per_beneficiary: "单位受益人成本",
  };
  const label = keyMap[k] || k;
  let disp: string;
  if (typeof v === "number") {
    if (k.includes("ratio") || k.includes("margin") || k.includes("retention")) {
      disp = v < 1 ? `${(v * 100).toFixed(1)}%` : v.toFixed(2);
    } else if (Math.abs(v) >= 1000) {
      disp = v.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
    } else {
      disp = v.toFixed(2);
    }
  } else if (Array.isArray(v)) {
    disp = `[${v.join(", ")}]`;
  } else {
    disp = String(v);
  }
  return `${label}：${disp}`;
}

const FinanceAdvisoryCard: React.FC<FinanceAdvisoryCardProps> = ({ advisory, onOpenReport, onJumpBudget }) => {
  if (!advisory || !advisory.triggered || !advisory.cards || advisory.cards.length === 0) return null;

  return (
    <div className="fr-advisory-wrap" role="complementary" aria-label="财务智能提示">
      <div className="fr-advisory-header">
        <span className="fr-advisory-badge">💡 财务智能评估</span>
        {advisory.industry && <span className="fr-advisory-industry">行业：{advisory.industry}</span>}
      </div>
      {advisory.cards.map((card, idx) => {
        const level = card.verdict?.level || "gray";
        const analysisConclusion = typeof card.outputs?.analysis_conclusion === "string" ? card.outputs.analysis_conclusion : "";
        const reasonNumericKeys = Object.entries(card.outputs || {})
          .filter(([_, v]) => typeof v === "number" || typeof v === "string" || Array.isArray(v))
          .filter(([k]) =>
            [
              "arpu",
              "gross_margin",
              "avg_lifetime_months",
              "ltv",
              "cac",
              "ltv_cac_ratio",
              "payback_period_months",
              "monthly_price",
              "monthly_retention",
              "industry_range",
              "deviation_ratio",
              "cost_per_beneficiary",
              "breakeven_month",
              "runway_months",
              "bottom_up_tam",
              "bottom_up_sam",
              "bottom_up_som_yr1",
            ].includes(k),
          )
          .slice(0, 4);
        return (
          <div key={idx} className={`fr-advisory-card fr-verdict-${level}`}>
            <div className="fr-advisory-card-head">
              <span className="fr-advisory-card-icon">{MODULE_ICON[card.module] || "📐"}</span>
              <span className="fr-advisory-card-title">{card.title}</span>
              <span className={`fr-advisory-chip fr-chip-${level}`}>{VERDICT_LABEL[level] || level}</span>
            </div>
            {analysisConclusion && <div className="fr-advisory-reason">{analysisConclusion}</div>}
            {card.verdict?.reason && <div className="fr-advisory-reason">{card.verdict.reason}</div>}
            {reasonNumericKeys.length > 0 && (
              <div className="fr-advisory-metrics">
                {reasonNumericKeys.map(([k, v]) => (
                  <span key={k} className="fr-advisory-metric">
                    {fmtKV(k, v)}
                  </span>
                ))}
              </div>
            )}
            {card.suggestions && card.suggestions.length > 0 && (
              <ul className="fr-advisory-suggestions">
                {card.suggestions.slice(0, 2).map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            )}
            {card.missing_inputs && card.missing_inputs.length > 0 && (
              <div className="fr-advisory-missing">
                <span className="fr-advisory-missing-label">缺失假设：</span>
                {card.missing_inputs.slice(0, 3).map((m, i) => (
                  <button
                    type="button"
                    key={i}
                    className="fr-advisory-missing-chip"
                    onClick={() => onJumpBudget && onJumpBudget(m.target_tab)}
                    title={m.hint}
                  >
                    {m.field}
                  </button>
                ))}
              </div>
            )}
            {card.baseline_meta && card.baseline_meta.source && (
              <div className="fr-advisory-source">
                <span
                  className={`fr-advisory-source-chip fr-source-${card.baseline_meta.source}`}
                  title={`参考资料来源：${SOURCE_LABEL[card.baseline_meta.source] || card.baseline_meta.source}`}
                >
                  参考：{SOURCE_LABEL[card.baseline_meta.source] || card.baseline_meta.source}
                </span>
                {card.baseline_meta.updated_at && (
                  <span className="fr-advisory-source-date">
                    更新于 {formatMetaDate(card.baseline_meta.updated_at)}
                  </span>
                )}
                {typeof card.baseline_meta.evidence_count === "number" && card.baseline_meta.evidence_count > 0 && (
                  <span className="fr-advisory-source-evidence">
                    {card.baseline_meta.evidence_count} 条证据
                  </span>
                )}
              </div>
            )}
          </div>
        );
      })}
      <div className="fr-advisory-footer">
        {onOpenReport && (
          <button type="button" className="fr-advisory-action-primary" onClick={onOpenReport}>
            查看完整财务分析 →
          </button>
        )}
        <span className="fr-advisory-hint">这里只做计算拆解与待补假设提示，不直接下“高低优劣”结论</span>
      </div>
    </div>
  );
};

export default FinanceAdvisoryCard;
