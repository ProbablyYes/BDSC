"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8037")
  .trim()
  .replace(/\/+$/, "");

type OverviewItem = {
  plan_id: string;
  project_id?: string;
  title?: string;
  plan_type?: string;
  fork_of?: string | null;
  version_tier?: string;
  mode?: string;
  updated_at?: string;
  student_id?: string;
  word_count?: number;
  maturity_tier?: string;
  project_name?: string;
  category?: string;
  overall_score?: number | null;
  grade?: string | null;
  passed?: boolean | null;
};

type PlanSnippet = {
  plan_id: string;
  word_count: number;
  excerpt: string;
  has_content: boolean;
};

type SectionRow = {
  section_id: string;
  title: string;
  plans: PlanSnippet[];
};

type AiNote = {
  section_id: string;
  title?: string;
  diff_note?: string;
  advice?: string;
};

type Comparison = {
  generated_at: string;
  plan_count: number;
  overview: OverviewItem[];
  sections: SectionRow[];
  ai_notes: AiNote[];
};

const COLORS = ["#38bdf8", "#fb7185", "#c4b5fd", "#facc15", "#4ade80"];

export default function BusinessPlanComparePage() {
  const searchParams = useSearchParams();
  const rawIds = searchParams?.get("plan_ids") || searchParams?.get("ids") || "";
  const useLlmParam = searchParams?.get("llm");
  const planIds = useMemo(
    () => rawIds.split(",").map((s) => s.trim()).filter(Boolean).slice(0, 5),
    [rawIds],
  );
  const [useLlm, setUseLlm] = useState<boolean>(useLlmParam !== "0");
  const [focus, setFocus] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState<Comparison | null>(null);

  async function runCompare(nextFocus?: string[], nextUseLlm?: boolean) {
    if (planIds.length < 2) {
      setError("至少需要 2 份计划书才能对比。");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const resp = await fetch(`${API_BASE}/api/business-plan/compare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plan_ids: planIds,
          focus_sections: nextFocus ?? focus,
          use_llm: nextUseLlm ?? useLlm,
        }),
      });
      const json = await resp.json();
      if (json?.status === "ok" && json.comparison) {
        setData(json.comparison);
      } else {
        setError(`对比失败：${json?.status || "未知错误"}`);
      }
    } catch (err: any) {
      setError(`对比失败：${err?.message || err}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void runCompare();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rawIds]);

  const noteMap = useMemo(() => {
    const m: Record<string, AiNote> = {};
    (data?.ai_notes || []).forEach((n) => { m[n.section_id] = n; });
    return m;
  }, [data]);

  const scoreStats = useMemo(() => {
    if (!data) return null;
    const scored = data.overview.filter((o) => typeof o.overall_score === "number");
    if (scored.length === 0) return null;
    const scores = scored.map((o) => Number(o.overall_score));
    const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
    const max = Math.max(...scores);
    const min = Math.min(...scores);
    return { avg, max, min, count: scored.length };
  }, [data]);

  return (
    <div className="bp-cmp-root">
      <header className="bp-cmp-head">
        <div>
          <h1>📑 计划书对比分析</h1>
          <div className="bp-cmp-sub">
            共选中 <b>{planIds.length}</b> 份 · 服务端自动抽取章节摘要并（可选）调用大模型生成差异和建议
          </div>
        </div>
        <div className="bp-cmp-head-actions">
          <label className="bp-cmp-llm-toggle">
            <input
              type="checkbox"
              checked={useLlm}
              onChange={(e) => { setUseLlm(e.target.checked); void runCompare(undefined, e.target.checked); }}
            />
            使用 AI 生成差异点评
          </label>
          <button
            onClick={() => window.history.back()}
            className="bp-cmp-back-btn"
          >
            ← 返回
          </button>
        </div>
      </header>

      {loading && <div className="bp-cmp-loading">正在对比计划书…</div>}
      {error && !loading && <div className="bp-cmp-error">{error}</div>}

      {data && !loading && (
        <>
          {/* 概览卡 */}
          <section className="bp-cmp-overview">
            <div className="bp-cmp-section-title">① 基本信息总览</div>
            <div className="bp-cmp-overview-grid">
              {data.overview.map((o, idx) => (
                <div
                  key={o.plan_id}
                  className="bp-cmp-overview-card"
                  style={{ borderLeft: `4px solid ${COLORS[idx % COLORS.length]}` }}
                >
                  <div className="bp-cmp-plan-title">
                    <span className="bp-cmp-dot" style={{ background: COLORS[idx % COLORS.length] }} />
                    {o.project_name || o.title || o.plan_id.slice(0, 10)}
                  </div>
                  <div className="bp-cmp-kv">
                    <span>学生</span>
                    <b>{o.student_id || "匿名"}</b>
                  </div>
                  <div className="bp-cmp-kv">
                    <span>类型</span>
                    <b>
                      {o.plan_type === "competition_fork" ? "竞赛分支" : "主干"}
                      {" · "}
                      {o.mode === "competition" ? "竞赛教练" : (o.mode === "coursework" ? "课程作业" : "学习训练")}
                    </b>
                  </div>
                  <div className="bp-cmp-kv"><span>类别</span><b>{o.category || "—"}</b></div>
                  <div className="bp-cmp-kv"><span>成熟度</span><b>{o.maturity_tier || "—"}</b></div>
                  <div className="bp-cmp-kv"><span>总字数</span><b>{o.word_count || 0}</b></div>
                  <div className="bp-cmp-kv">
                    <span>教师评分</span>
                    <b>
                      {typeof o.overall_score === "number"
                        ? `${o.overall_score.toFixed(1)} / 100 · ${o.grade || "?"}`
                        : "未批改"}
                    </b>
                  </div>
                  <div className="bp-cmp-kv"><span>更新</span><b>{(o.updated_at || "").slice(0, 19).replace("T", " ")}</b></div>
                </div>
              ))}
            </div>
            {scoreStats && (
              <div className="bp-cmp-stats-row">
                已批改 {scoreStats.count} 份 · 均分 <b>{scoreStats.avg.toFixed(1)}</b> ·
                最高 <b>{scoreStats.max.toFixed(1)}</b> · 最低 <b>{scoreStats.min.toFixed(1)}</b>
              </div>
            )}
          </section>

          {/* 章节对比 */}
          <section className="bp-cmp-sections">
            <div className="bp-cmp-section-title">② 逐章节对比</div>
            <div className="bp-cmp-focus-bar">
              <span style={{ color: "#94a3b8", marginRight: 8 }}>仅关注：</span>
              {data.sections.map((s) => {
                const on = focus.includes(s.section_id);
                return (
                  <button
                    key={s.section_id}
                    className={`bp-cmp-focus-chip ${on ? "is-on" : ""}`}
                    onClick={() => {
                      const next = on ? focus.filter((x) => x !== s.section_id) : [...focus, s.section_id];
                      setFocus(next);
                      void runCompare(next);
                    }}
                  >
                    {s.title || s.section_id}
                  </button>
                );
              })}
              {focus.length > 0 && (
                <button
                  className="bp-cmp-focus-clear"
                  onClick={() => { setFocus([]); void runCompare([]); }}
                >清空</button>
              )}
            </div>

            {data.sections.map((row) => {
              const note = noteMap[row.section_id];
              const wcList = row.plans.map((p) => p.word_count || 0);
              const maxWc = Math.max(1, ...wcList);
              return (
                <div key={row.section_id} className="bp-cmp-row">
                  <div className="bp-cmp-row-head">
                    <div className="bp-cmp-row-title">
                      <b>{row.title || row.section_id}</b>
                      <span className="bp-cmp-row-id">{row.section_id}</span>
                    </div>
                    {note && (
                      <div className="bp-cmp-note">
                        {note.diff_note && <div className="bp-cmp-note-diff">差异：{note.diff_note}</div>}
                        {note.advice && <div className="bp-cmp-note-advice">建议：{note.advice}</div>}
                      </div>
                    )}
                  </div>
                  <div className="bp-cmp-row-grid">
                    {row.plans.map((p, idx) => {
                      const ov = data.overview.find((o) => o.plan_id === p.plan_id);
                      const width = `${Math.max(6, Math.round((p.word_count / maxWc) * 100))}%`;
                      return (
                        <div
                          key={p.plan_id}
                          className={`bp-cmp-plan-col ${p.has_content ? "" : "is-empty"}`}
                          style={{ borderTop: `3px solid ${COLORS[idx % COLORS.length]}` }}
                        >
                          <div className="bp-cmp-plan-col-head">
                            <span>{ov?.project_name || ov?.title || p.plan_id.slice(0, 8)}</span>
                            <span className="bp-cmp-plan-col-wc">{p.word_count} 字</span>
                          </div>
                          <div className="bp-cmp-wc-bar">
                            <div
                              className="bp-cmp-wc-bar-fill"
                              style={{ width, background: COLORS[idx % COLORS.length] }}
                            />
                          </div>
                          <div className={`bp-cmp-excerpt ${p.has_content ? "" : "is-empty"}`}>
                            {p.has_content ? p.excerpt : "（本章节尚未撰写或内容过少）"}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </section>

          <footer className="bp-cmp-foot">
            生成于 {(data.generated_at || "").slice(0, 19).replace("T", " ")} · 由 BDSC 智能教学系统生成
          </footer>
        </>
      )}
    </div>
  );
}
