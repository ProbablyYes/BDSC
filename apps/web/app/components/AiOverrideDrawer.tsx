"use client";
/**
 * AiOverrideDrawer —— 教师订正任何 AI 结论的侧抽屉。
 * 需要 target_type + target_key（与 Rationale.field 对齐）。
 * 必填理由（学生端能看到）。
 */

import { useEffect, useState } from "react";

export interface AiOverridePayload {
  project_id: string;
  conversation_id?: string;
  target_type: string;
  target_key: string;
  ai_value: string | number;
  teacher_value: string | number;
  reason: string;
  teacher_id?: string;
  teacher_name?: string;
}

export interface AiOverrideDrawerProps {
  open: boolean;
  title: string;
  projectId: string;
  conversationId?: string;
  targetType: string;
  targetKey: string;
  aiValue: string | number | null | undefined;
  teacherName?: string;
  teacherId?: string;
  apiBase?: string;
  onClose: () => void;
  onSuccess?: (record: unknown) => void;
}

export function AiOverrideDrawer({
  open,
  title,
  projectId,
  conversationId,
  targetType,
  targetKey,
  aiValue,
  teacherName,
  teacherId,
  apiBase = "",
  onClose,
  onSuccess,
}: AiOverrideDrawerProps) {
  const [teacherValue, setTeacherValue] = useState<string>(aiValue == null ? "" : String(aiValue));
  const [reason, setReason] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    if (open) {
      setTeacherValue(aiValue == null ? "" : String(aiValue));
      setReason("");
      setError("");
    }
  }, [open, aiValue]);

  if (!open) return null;

  const submit = async () => {
    if (!reason.trim()) {
      setError("请填写修改理由（学生会看到）");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const res = await fetch(`${apiBase}/api/teacher/overrides`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          conversation_id: conversationId || "",
          target_type: targetType,
          target_key: targetKey,
          ai_value: aiValue,
          teacher_value: teacherValue,
          reason,
          teacher_id: teacherId,
          teacher_name: teacherName,
        } as AiOverridePayload),
      });
      const data = await res.json();
      if (data.status === "ok") {
        onSuccess?.(data.override);
        onClose();
      } else {
        setError(data.detail || "保存失败");
      }
    } catch (e) {
      setError((e as Error).message || "网络错误");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="aod-backdrop" onClick={onClose}>
      <aside className="aod-panel" onClick={(e) => e.stopPropagation()}>
        <header className="aod-head">
          <h3>{title}</h3>
          <button className="aod-close" onClick={onClose} aria-label="关闭">×</button>
        </header>
        <div className="aod-body">
          <div className="aod-row">
            <label className="aod-label">结论字段</label>
            <code className="aod-code">{targetType}:{targetKey}</code>
          </div>
          <div className="aod-row">
            <label className="aod-label">AI 原值</label>
            <div className="aod-ai-value">{aiValue == null ? "（无初始值）" : String(aiValue)}</div>
          </div>
          <div className="aod-row">
            <label className="aod-label">教师订正值</label>
            <input
              className="aod-input"
              value={teacherValue}
              onChange={(e) => setTeacherValue(e.target.value)}
              placeholder="填写你认可的正确值（数字或文字均可）"
            />
          </div>
          <div className="aod-row">
            <label className="aod-label required">修改理由（必填）</label>
            <textarea
              className="aod-textarea"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="请详细描述为何修改，学生端会看到这条说明。"
              rows={4}
            />
          </div>
          {error ? <div className="aod-error">{error}</div> : null}
        </div>
        <footer className="aod-foot">
          <button className="aod-btn-ghost" onClick={onClose} disabled={saving}>取消</button>
          <button className="aod-btn-primary" onClick={submit} disabled={saving}>
            {saving ? "保存中…" : "保存订正"}
          </button>
        </footer>
      </aside>
    </div>
  );
}
