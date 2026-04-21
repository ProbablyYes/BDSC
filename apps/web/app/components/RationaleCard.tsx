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

export type Rationale = {
  field: string;
  value: string | number;
  formula?: string;
  formula_display?: string;
  inputs?: RationaleInput[];
  contributing_evidence?: ContributingEvidence[];
  teacher_override?: TeacherOverride;
  note?: string;
};

export interface RationaleCardProps {
  rationale: Rationale;
  title?: string;
  compact?: boolean;
  onJumpMessage?: (messageId: string) => void;
  onEdit?: () => void;
  className?: string;
}

export function RationaleCard({
  rationale,
  title,
  compact = false,
  onJumpMessage,
  onEdit,
  className = "",
}: RationaleCardProps) {
  const [expanded, setExpanded] = useState(!compact);
  const override = rationale.teacher_override;

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
          {rationale.formula_display ? (
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
