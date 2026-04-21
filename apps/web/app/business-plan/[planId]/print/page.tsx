"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8037")
  .trim()
  .replace(/\/+$/, "");

type Section = {
  section_id: string;
  title: string;
  display_title?: string;
  content?: string;
  user_edit?: string;
  is_ai_stub?: boolean;
  narrative_opening?: string;
};

type Plan = {
  plan_id: string;
  title?: string;
  cover_info?: Record<string, any>;
  knowledge_base?: Record<string, any>;
  maturity?: { score?: number; tier_label?: string; tier?: string };
  sections?: Section[];
  created_at?: string;
  updated_at?: string;
};

export default function BusinessPlanPrintPage() {
  const params = useParams<{ planId: string }>();
  const searchParams = useSearchParams();
  const planId = params?.planId ?? "";
  const autoprint = searchParams?.get("autoprint") === "1";
  const viewOnly = searchParams?.get("viewOnly") === "1";

  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!planId) return;
    (async () => {
      try {
        const resp = await fetch(`${API_BASE}/api/business-plan/${encodeURIComponent(planId)}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (!data?.plan) throw new Error("未找到计划书");
        setPlan(data.plan);
      } catch (err: any) {
        setError(err?.message || "加载失败");
      } finally {
        setLoading(false);
      }
    })();
  }, [planId]);

  useEffect(() => {
    if (viewOnly) return;
    if (!autoprint || loading || !plan) return;
    const t = setTimeout(() => {
      try {
        window.print();
      } catch {}
    }, 500);
    return () => clearTimeout(t);
  }, [autoprint, loading, plan, viewOnly]);

  if (loading) {
    return <div className="bp-print-msg">正在加载计划书…</div>;
  }
  if (error || !plan) {
    return <div className="bp-print-msg bp-print-err">加载失败：{error || "计划书不存在"}</div>;
  }

  const cover = plan.cover_info || {};
  const kb = plan.knowledge_base || {};
  const title = plan.title || (cover.project_name as string) || "商业计划书";
  const oneLiner = (kb.one_liner as string) || "";
  const team = [cover.student_or_team, cover.course_or_class, cover.teacher_name].filter(Boolean).join(" · ");
  const dateStr = String(cover.date || (plan.updated_at || "").slice(0, 10) || "");
  const maturity = plan.maturity;
  const sections = plan.sections || [];
  const firstOpening = sections.find((s) => s.narrative_opening)?.narrative_opening || "";

  return (
    <div className="bp-print-root">
      {viewOnly ? (
        <div className="bp-print-toolbar bp-print-toolbar-readonly no-print">
          <span className="bp-print-ro-tag">只读预览</span>
          <span className="bp-print-hint">教师端视角：当前版本由学生方生成，所有编辑操作在学生端完成。</span>
        </div>
      ) : (
        <div className="bp-print-toolbar no-print">
          <button onClick={() => window.print()}>打印 / 另存为 PDF</button>
          <span className="bp-print-hint">
            在弹出的打印对话框中选择「另存为 PDF」即可；纸张推荐 A4，页边距选「默认」。
          </span>
        </div>
      )}

      {/* 封面 */}
      <section className="bp-print-cover">
        <div className="bp-print-accent-tag">商业计划书 · Business Plan</div>
        <h1 className="bp-print-cover-title">{title}</h1>
        {oneLiner && <div className="bp-print-cover-oneliner">{oneLiner}</div>}

        <div className="bp-print-cover-meta">
          <div><span>团队 / 作者</span><b>{team || "＿＿＿＿＿＿"}</b></div>
          <div><span>日期</span><b>{dateStr || "＿＿＿＿＿＿"}</b></div>
          {maturity?.score != null && (
            <div>
              <span>内容成熟度</span>
              <b>{maturity.score}/100（{maturity.tier_label || maturity.tier || ""}）</b>
            </div>
          )}
          <div><span>章节数</span><b>{sections.length}</b></div>
        </div>

        <div className="bp-print-cover-footer">
          {cover.project_name || title}
        </div>
      </section>

      {/* 目录 */}
      <section className="bp-print-toc">
        <h2>目  录</h2>
        <ol>
          {sections.map((s, i) => (
            <li key={s.section_id}>
              <span className="bp-toc-name">
                第 {i + 1} 章&nbsp;&nbsp;{s.display_title || s.title}
              </span>
              <span className="bp-toc-dots" />
              <span className="bp-toc-page">{i + 1}</span>
            </li>
          ))}
        </ol>
      </section>

      {/* 正文 */}
      {firstOpening && (
        <section className="bp-print-opening">
          <em>{firstOpening}</em>
        </section>
      )}

      {sections.map((s, idx) => (
        <section key={s.section_id} className="bp-print-section">
          <h2 className="bp-print-h1">
            <span className="bp-print-h1-num">第 {idx + 1} 章</span>
            <span className="bp-print-h1-title">{s.display_title || s.title}</span>
          </h2>
          {s.is_ai_stub && (
            <div className="bp-print-stub">
              【AI 参考稿】本章基于项目知识库与行业通用框架生成，请团队校准。
            </div>
          )}
          <div className="bp-print-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {(s.user_edit && s.user_edit.trim()) || s.content || ""}
            </ReactMarkdown>
          </div>
        </section>
      ))}

      {/* 页脚版权 */}
      <footer className="bp-print-footer-note">
        本计划书由创业辅导智能体辅助生成，数据与事实内容需项目团队最终校准。
      </footer>
    </div>
  );
}
