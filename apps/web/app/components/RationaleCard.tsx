"use client";
/**
 * RationaleCard —— 展示 AI 结论的推理链。
 * 后端 Rationale 结构：
 * { field, value, formula, formula_display, inputs: [{label, value, weight, impact, source_message_id, ...}],
 *   contributing_evidence: [...], teacher_override?: {teacher_name, reason, ai_value, created_at} }
 */

import { useState } from "react";

export type RationaleInput = {
  label: string;
  value: string | number;
  weight?: number;
  impact?: string;
  source_message_id?: string;
  source_submission_id?: string;
  rule_id?: string;
  excerpt?: string;
  agent?: string;
};

export type ContributingEvidence = {
  message_id?: string;
  turn_index?: number;
  role?: string;
  excerpt?: string;
  impact?: string;
  agent?: string;
  rule_id?: string;
  confidence?: number;
};

export type TeacherOverride = {
  teacher_name: string;
  teacher_id?: string;
  reason: string;
  ai_value: string | number;
  created_at?: string;
};

export type ReasoningStep = {
  kind?: string;               // "base" | "evidence" | "rule" | "adjust" | "aggregate"
  label: string;
  delta?: number;              // 对最终值的贡献（正负）
  severity?: string;           // info / warn / block / boost
  source_message_id?: string;
  agent_name?: string;
  quote?: string;
  detail?: string;
};

export type RationaleBaseline = {
  name: string;
  value: string | number;
  comparison?: string;
};

export type Rationale = {
  field: string;
  value: string | number;
  formula?: string;
  formula_display?: string;
  inputs?: RationaleInput[];
  contributing_evidence?: ContributingEvidence[];
  reasoning_steps?: ReasoningStep[];
  baseline?: RationaleBaseline;
  teacher_override?: TeacherOverride;
  note?: string;
};

export type SmoothingMeta = {
  displayValue: number;   // 最终展示的平滑分
  turns: number;          // 参与平滑的轮次
  weights: number[];      // 权重数组（新→旧），如 [0.5, 0.3, 0.2]
  rawHistory: number[];   // 对应原始分（新→旧）
};

export interface RationaleCardProps {
  rationale: Rationale;
  title?: string;
  compact?: boolean;
  onJumpMessage?: (messageId: string) => void;
  onEdit?: () => void;
  className?: string;
  smoothing?: SmoothingMeta;
}

export function RationaleCard({
  rationale,
  title,
  compact = false,
  onJumpMessage,
  onEdit,
  className = "",
  smoothing,
}: RationaleCardProps) {
  const [expanded, setExpanded] = useState(!compact);
  const override = rationale.teacher_override;
  const showSmoothing =
    !!smoothing &&
    smoothing.turns >= 2 &&
    Array.isArray(smoothing.rawHistory) &&
    Array.isArray(smoothing.weights) &&
    smoothing.rawHistory.length >= smoothing.turns;

  return (
    <div className={`rc-card ${compact ? "rc-compact" : ""} ${override ? "rc-has-override" : ""} ${className}`}>
      <div className="rc-head">
        <div className="rc-title-row">
          <span className="rc-field-tag">{rationale.field}</span>
          {title ? <span className="rc-title">{title}</span> : null}
        </div>
        <div className="rc-value-row">
          <span className="rc-value">{String(rationale.value)}</span>
          {override ? (
            <span className="rc-badge-override" title={`${override.teacher_name} · ${override.reason}`}>
              老师已订正
            </span>
          ) : null}
          {onEdit ? (
            <button className="rc-edit-btn" onClick={onEdit} title="订正此结论">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 20h9M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4z" />
              </svg>
              订正
            </button>
          ) : null}
          <button className="rc-toggle" onClick={() => setExpanded((x) => !x)}>
            {expanded ? "收起来源" : "展开来源"}
          </button>
        </div>
        {showSmoothing ? (
          <div className="rc-smoothing-note">
            <span className="rc-smoothing-label">展示分</span>
            <span className="rc-smoothing-formula">
              {smoothing!.displayValue.toFixed(2)} ={" "}
              {smoothing!.rawHistory.slice(0, smoothing!.turns).map((v, i) => (
                <span key={i}>
                  {i > 0 ? " + " : ""}
                  {(smoothing!.weights[i] ?? 0).toFixed(1)}×{v.toFixed(2)}
                </span>
              ))}
            </span>
            <span className="rc-smoothing-hint">
              最近 {smoothing!.turns} 轮加权 · 下方为最新一轮原值推导
            </span>
          </div>
        ) : null}
      </div>
      {override ? (
        <div className="rc-override-band">
          <span className="rc-override-label">{override.teacher_name}</span>
          <span className="rc-override-reason">理由：{override.reason}</span>
          <span className="rc-override-ai">AI 原值：{String(override.ai_value)}</span>
        </div>
      ) : null}
      {expanded ? (
        <>
          {/* ── 推理链瀑布：按步骤一条条交代分数从哪里来 ── */}
          {rationale.reasoning_steps && rationale.reasoning_steps.length > 0 ? (
            <div className="rc-steps">
              <div className="rc-section-title">推理链</div>
              <ol className="rc-step-list">
                {rationale.reasoning_steps.map((step, i) => {
                  const d = typeof step.delta === "number" ? step.delta : null;
                  const deltaSign = d === null ? "" : d > 0 ? "+" : "";
                  const deltaClass =
                    d === null
                      ? "rc-step-delta rc-step-delta-neutral"
                      : d > 0
                      ? "rc-step-delta rc-step-delta-pos"
                      : d < 0
                      ? "rc-step-delta rc-step-delta-neg"
                      : "rc-step-delta rc-step-delta-neutral";
                  const severity = (step.severity || "").toLowerCase();
                  const kind = (step.kind || "").toLowerCase();
                  return (
                    <li key={i} className={`rc-step rc-step-${kind || "info"} rc-sev-${severity || "info"}`}>
                      <div className="rc-step-main">
                        <span className="rc-step-idx">{i + 1}</span>
                        {step.kind ? <span className="rc-step-kind">{step.kind}</span> : null}
                        <span className="rc-step-label">{step.label}</span>
                        {d !== null ? (
                          <span className={deltaClass}>
                            {deltaSign}
                            {d.toFixed(2)}
                          </span>
                        ) : null}
                        {step.source_message_id && onJumpMessage ? (
                          <button
                            className="rc-jump tiny"
                            onClick={() => onJumpMessage(step.source_message_id!)}
                            title="跳到触发这一步的学生原话"
                          >
                            跳 →
                          </button>
                        ) : null}
                      </div>
                      {step.agent_name || step.detail || step.quote ? (
                        <div className="rc-step-sub">
                          {step.agent_name ? (
                            <span className="rc-step-agent">by {step.agent_name}</span>
                          ) : null}
                          {step.detail ? <span className="rc-step-detail">{step.detail}</span> : null}
                          {step.quote ? (
                            <span className="rc-step-quote" title={step.quote}>
                              "{step.quote.length > 80 ? `${step.quote.slice(0, 80)}…` : step.quote}"
                            </span>
                          ) : null}
                        </div>
                      ) : null}
                    </li>
                  );
                })}
              </ol>
              {rationale.baseline ? (
                <div className="rc-baseline">
                  参考基线：{rationale.baseline.name} = {String(rationale.baseline.value)}
                  {rationale.baseline.comparison ? ` · ${rationale.baseline.comparison}` : ""}
                </div>
              ) : null}
            </div>
          ) : rationale.formula_display ? (
            <pre className="rc-formula">{rationale.formula_display}</pre>
          ) : rationale.formula ? (
            <div className="rc-formula-mono"><code>{rationale.formula}</code></div>
          ) : null}
          {rationale.inputs && rationale.inputs.length > 0 ? (
            <div className="rc-inputs">
              <div className="rc-section-title">输入项</div>
              <ul className="rc-input-list">
                {rationale.inputs.map((inp, i) => (
                  <li key={i} className="rc-input-item">
                    <span className="rc-input-label">{inp.label}</span>
                    <span className="rc-input-value">{String(inp.value)}</span>
                    {inp.weight !== undefined ? (
                      <span className="rc-input-weight">w={inp.weight}</span>
                    ) : null}
                    {inp.impact ? <span className="rc-input-impact">{inp.impact}</span> : null}
                    {inp.source_message_id && onJumpMessage ? (
                      <button
                        className="rc-jump"
                        onClick={() => onJumpMessage(inp.source_message_id!)}
                        title="跳到原消息"
                      >
                        跳转
                      </button>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {rationale.contributing_evidence && rationale.contributing_evidence.length > 0 ? (
            <div className="rc-evidence">
              <div className="rc-section-title">贡献证据</div>
              <ul className="rc-evid-list">
                {rationale.contributing_evidence.map((ev, i) => (
                  <li key={i} className="rc-evid-item">
                    <div className="rc-evid-head">
                      {ev.role ? <span className={`rc-evid-role rc-role-${ev.role}`}>{ev.role}</span> : null}
                      {ev.agent ? <span className="rc-evid-agent">{ev.agent}</span> : null}
                      {ev.rule_id ? <span className="rc-evid-rule">{ev.rule_id}</span> : null}
                      {ev.confidence !== undefined ? (
                        <span className="rc-evid-conf">置信度 {ev.confidence}</span>
                      ) : null}
                    </div>
                    <div className="rc-evid-excerpt">"{ev.excerpt}"</div>
                    {ev.impact ? <div className="rc-evid-impact">{ev.impact}</div> : null}
                    {ev.message_id && onJumpMessage ? (
                      <button className="rc-jump small" onClick={() => onJumpMessage(ev.message_id!)}>
                        定位到原消息 →
                      </button>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {rationale.note ? <div className="rc-note">{rationale.note}</div> : null}
        </>
      ) : null}
    </div>
  );
}

/** 点击触发器，弹出 RationaleCard 的轻量 popover。 */
export function EvidencePopover({
  rationale,
  label,
  onJumpMessage,
  onEdit,
}: {
  rationale: Rationale | null | undefined;
  label: React.ReactNode;
  onJumpMessage?: (messageId: string) => void;
  onEdit?: () => void;
}) {
  const [open, setOpen] = useState(false);
  if (!rationale) return <span>{label}</span>;
  return (
    <span className="ep-root" onMouseLeave={() => setOpen(false)}>
      <button
        className={`ep-trigger ${rationale.teacher_override ? "ep-overridden" : ""}`}
        onClick={() => setOpen((x) => !x)}
        onMouseEnter={() => setOpen(true)}
      >
        {label}
        <span className="ep-indicator" aria-hidden>ⓘ</span>
      </button>
      {open ? (
        <div className="ep-popover" onMouseLeave={() => setOpen(false)}>
          <RationaleCard rationale={rationale} onJumpMessage={onJumpMessage} onEdit={onEdit} />
        </div>
      ) : null}
    </span>
  );
}
