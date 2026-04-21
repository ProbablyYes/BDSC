"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { RationaleCard, type Rationale } from "../../components/RationaleCard";
import { RadarChart, type RadarItem } from "../../components/RadarChart";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8037").trim().replace(/\/+$/, "");

function parseServerTime(value?: string) {
  if (!value) return null;
  const normalized = /Z$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`;
  const d = new Date(normalized);
  return Number.isNaN(d.getTime()) ? null : d;
}

function formatBjTime(value?: string) {
  const d = parseServerTime(value);
  if (!d) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

function formatBjDate(value?: string) {
  const d = parseServerTime(value);
  if (!d) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

type PanoramaData = {
  health_score?: number;
  health_level?: "healthy" | "warning" | "critical";
  health_label?: string;
  rubric_heatmap_team?: Array<{ item: string; item_cn?: string; avg_score: number; sample_count?: number }>;
  rubric_heatmap?: Array<{ item: string; avg_score: number; count?: number; rationale?: any }>;
  top_strengths?: string[];
  top_weaknesses?: string[];
  strength_dimensions?: string[];
  weakness_dimensions?: string[];
  risk_rule_top3?: Array<{ rule_id: string; count: number; label?: string }>;
  engagement_stats?: { total_submissions?: number; scored_count?: number; risk_count?: number };
  trend_summary?: string;
  overall_assessment?: string;
  detail_bullets?: string[];
  score_distribution?: { good?: number; average?: number; weak?: number; no_data?: number };
  avg_score?: number;
  trend?: number;
  total_submissions?: number;
  overview_rationale?: any;
  strength_rationale?: any;
  weakness_rationale?: any;
  growth_rationale?: any;
  intent_distribution?: Record<string, number>;
  student_case_summary?: string;
  behavioral_pattern?: {
    total_submissions?: number;
    avg_submit_interval_days?: number;
    improvement_rate?: number;
    active_days_span?: number;
  };
  growth_trajectory?: Array<{ date: string; score: number }>;
};

type ProjectCardData = {
  latest_task?: { title?: string; description?: string; acceptance_criteria?: string[] };
  evidence_quotes?: Array<{ text?: string; source?: string; created_at?: string }>;
  phase_history?: Array<{ created_at?: string; phase?: string; intent?: string; score?: number }>;
  current_summary?: string;
  top_risks?: string[];
  intent_distribution?: Record<string, number>;
};

const INTENT_LABEL_CN: Record<string, string> = {
  ideation: "构想",
  feedback: "反馈",
  question: "提问",
  validation: "验证",
  reflection: "复盘",
  planning: "规划",
  execution: "执行",
  summary: "总结",
  other: "其他",
};

function IntentDistributionBar({ dist }: { dist?: Record<string, number> }) {
  if (!dist) return null;
  const entries = Object.entries(dist).filter(([, v]) => Number(v) > 0);
  if (!entries.length) return null;
  const total = entries.reduce((a, [, v]) => a + Number(v), 0) || 1;
  entries.sort((a, b) => Number(b[1]) - Number(a[1]));
  const palette = ["#6b8aff", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4", "#8b5cf6", "#94a3b8"];
  return (
    <div className="sp-intent-bar">
      <div className="sp-intent-track">
        {entries.map(([k, v], i) => {
          const pct = (Number(v) / total) * 100;
          return (
            <span
              key={k}
              className="sp-intent-seg"
              style={{ width: `${pct}%`, background: palette[i % palette.length] }}
              title={`${INTENT_LABEL_CN[k] || k} · ${v} 次 · ${pct.toFixed(0)}%`}
            />
          );
        })}
      </div>
      <div className="sp-intent-legend">
        {entries.slice(0, 6).map(([k, v], i) => (
          <span key={k} className="sp-intent-chip">
            <span className="sp-intent-chip-dot" style={{ background: palette[i % palette.length] }} />
            {INTENT_LABEL_CN[k] || k}
            <small>· {v}</small>
          </span>
        ))}
      </div>
    </div>
  );
}

function GrowthSparkline({ points }: { points?: Array<{ date: string; score: number }> }) {
  if (!points || points.length < 2) return null;
  const W = 320;
  const H = 64;
  const maxY = 10;
  const px = (i: number) => (i / Math.max(points.length - 1, 1)) * (W - 16) + 8;
  const py = (v: number) => H - 10 - (v / maxY) * (H - 20);
  const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${px(i)},${py(p.score)}`).join(" ");
  const area = `${line} L${px(points.length - 1)},${H - 6} L${px(0)},${H - 6} Z`;
  const first = points[0].score;
  const last = points[points.length - 1].score;
  const delta = last - first;
  return (
    <div className="sp-growth-spark">
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        <defs>
          <linearGradient id="spGrowthG" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#6b8aff" stopOpacity="0.28" />
            <stop offset="100%" stopColor="#6b8aff" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#spGrowthG)" />
        <path d={line} fill="none" stroke="#6b8aff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        {points.map((p, i) => (
          <circle
            key={i}
            cx={px(i)}
            cy={py(p.score)}
            r={i === 0 || i === points.length - 1 ? 3 : 2}
            fill="#6b8aff"
            stroke="var(--bg-primary)"
            strokeWidth="1.5"
          />
        ))}
      </svg>
      <div className="sp-growth-spark-meta">
        <span>首次 {first.toFixed(1)}</span>
        <span style={{ color: delta >= 0 ? "#22c55e" : "#ef4444" }}>{delta >= 0 ? "↑" : "↓"} {delta.toFixed(1)}</span>
        <span>最新 {last.toFixed(1)}</span>
      </div>
    </div>
  );
}

function PhaseTimeline({ history }: { history?: ProjectCardData["phase_history"] }) {
  if (!history || history.length === 0) return null;
  const trimmed = history.slice(-6);
  return (
    <div className="sp-phase-timeline">
      {trimmed.map((h, i) => (
        <div className="sp-phase-node" key={i}>
          <div className="sp-phase-dot" />
          {i < trimmed.length - 1 && <div className="sp-phase-line" />}
          <div className="sp-phase-chip">
            <span className="sp-phase-chip-title">{h.phase || "—"}</span>
            <span className="sp-phase-chip-meta">
              {(h.created_at || "").slice(5, 10)}
              {typeof h.score === "number" && h.score > 0 ? ` · ${h.score.toFixed(1)}` : ""}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

function StudentPortraitPanorama({
  data,
  title,
  projectCard,
}: {
  data: PanoramaData;
  title: string;
  projectCard?: ProjectCardData | null;
}) {
  const [showHow, setShowHow] = useState(false);
  const [activeDim, setActiveDim] = useState<string | null>(null);
  const healthScore = Number(data.health_score ?? 0);
  const healthLevel = data.health_level ?? "warning";
  const healthColor =
    healthLevel === "healthy" ? "#5cbd8a" : healthLevel === "critical" ? "#ef4444" : "#eab308";
  const heatmap = (data.rubric_heatmap_team && data.rubric_heatmap_team.length > 0
    ? data.rubric_heatmap_team
    : (data.rubric_heatmap ?? []).map((h) => ({ item: h.item, item_cn: h.item, avg_score: h.avg_score, sample_count: h.count }))) as Array<{ item: string; item_cn?: string; avg_score: number; sample_count?: number }>;
  const sd = data.score_distribution || {};
  const engage = data.engagement_stats || {};
  const detailBullets = data.detail_bullets || [];
  const strengths = data.top_strengths || [];
  const weaknesses = data.top_weaknesses || [];
  const risks = data.risk_rule_top3 || [];
  const ringCirc = 2 * Math.PI * 48;
  const ringDash = (healthScore / 100) * ringCirc;
  const beh = data.behavioral_pattern || {};

  // rubric_heatmap（带 rationale）用于雷达顶点 popover
  const rubricWithRationale = Array.isArray(data.rubric_heatmap) ? data.rubric_heatmap : [];
  const rubricMap: Record<string, any> = Object.fromEntries(rubricWithRationale.map((h) => [h.item, h]));

  // 基线：九维均值 - 1.2，用于视觉上让"当前"轮廓比"历史均值"有落差
  const radarMean = heatmap.length
    ? heatmap.reduce((a, h) => a + (h.avg_score || 0), 0) / heatmap.length
    : 0;
  const radarItems: RadarItem[] = heatmap.map((h) => ({
    label: h.item_cn || h.item,
    value: h.avg_score,
    max: 10,
    baseline: Math.max(0, radarMean - 0.5),
    meta: h,
  }));
  const activeRationale = activeDim ? (rubricMap[activeDim]?.rationale as Rationale | undefined) : undefined;
  const activeRubric = activeDim ? rubricMap[activeDim] : null;

  const caseSummary = data.student_case_summary || "";
  const latestTask = projectCard?.latest_task;
  const evidenceQuotes = projectCard?.evidence_quotes || [];
  const phaseHistory = projectCard?.phase_history || [];
  const intentDist = data.intent_distribution || projectCard?.intent_distribution || {};

  return (
    <div className="tm-team-panorama sp-panorama">
      <div className="tm-panorama-header">
        <h3>{title}</h3>
        <span className={`tm-portrait-health-badge tm-health-${healthLevel}`}>
          {data.health_label || "—"}
        </span>
        {typeof data.avg_score === "number" && data.avg_score > 0 && (
          <span className="tm-portrait-health-badge tm-health-warning">均分 {data.avg_score}/10</span>
        )}
        <button
          type="button"
          className="sp-panorama-how-btn"
          onClick={() => setShowHow((v) => !v)}
          title="展开/收起计算依据"
        >
          {showHow ? "收起计算依据" : "如何得出"}
        </button>
      </div>

      {caseSummary && (
        <div className="sp-case-summary">{caseSummary}</div>
      )}

      <div className="tm-portrait-top-row">
        <div className="tm-portrait-ring-box">
          <svg viewBox="0 0 120 120" className="tm-portrait-ring-svg">
            <circle cx="60" cy="60" r="48" fill="none" stroke="rgba(255,255,255,.06)" strokeWidth="10" />
            <circle
              cx="60" cy="60" r="48" fill="none"
              stroke={healthColor} strokeWidth="10" strokeLinecap="round"
              strokeDasharray={`${ringDash} ${ringCirc}`}
              transform="rotate(-90 60 60)"
              style={{ transition: "stroke-dasharray .8s ease" }}
            />
            <text x="60" y="55" textAnchor="middle" fill="var(--text-primary)" fontSize="22" fontWeight="700">
              {healthScore}
            </text>
            <text x="60" y="72" textAnchor="middle" fill="var(--text-muted)" fontSize="10">健康指数</text>
          </svg>
          <div className="tm-portrait-ring-meta">
            <div className="tm-ring-stat"><span className="tm-ring-stat-v" style={{ color: "#5cbd8a" }}>{sd.good || 0}</span><span className="tm-ring-stat-l">良好</span></div>
            <div className="tm-ring-stat"><span className="tm-ring-stat-v" style={{ color: "#eab308" }}>{sd.average || 0}</span><span className="tm-ring-stat-l">一般</span></div>
            <div className="tm-ring-stat"><span className="tm-ring-stat-v" style={{ color: "#ef4444" }}>{sd.weak || 0}</span><span className="tm-ring-stat-l">薄弱</span></div>
          </div>
        </div>

        {radarItems.length >= 3 && (
          <div className="sp-radar-wrap">
            <div className="sp-radar-title">
              九维评审雷达
              <span className="sp-radar-hint">点击顶点查看该维度计算依据</span>
            </div>
            <RadarChart
              data={radarItems}
              size={270}
              showBaseline
              onVertexClick={(it) => setActiveDim(String(it.meta?.item || it.label))}
            />
            {activeDim && (
              <div className="sp-radar-popover">
                <div className="sp-radar-popover-head">
                  <strong>{activeRubric?.item_cn || activeDim}</strong>
                  <span
                    className="sp-radar-popover-score"
                    style={{
                      color:
                        (activeRubric?.avg_score || 0) >= 7
                          ? "#22c55e"
                          : (activeRubric?.avg_score || 0) >= 5
                          ? "#eab308"
                          : "#ef4444",
                    }}
                  >
                    {activeRubric?.avg_score ?? "—"}
                    <small>/10</small>
                  </span>
                  <button className="sp-radar-popover-close" onClick={() => setActiveDim(null)}>×</button>
                </div>
                {activeRationale ? (
                  <RationaleCard rationale={activeRationale} compact />
                ) : (
                  <p className="sp-radar-popover-empty">本维度暂无详细计算依据</p>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {detailBullets.length > 0 && (
        <div className="tm-portrait-section">
          <div className="tm-portrait-section-title">核心发现</div>
          <ul className="tm-panorama-bullets">
            {detailBullets.map((b, i) => <li key={i}>{b}</li>)}
          </ul>
        </div>
      )}

      <div className="tm-portrait-tags-row">
        <div className="tm-portrait-tags-col">
          {strengths.length > 0 && (
            <div className="tm-panorama-dim-group">
              <span className="tm-panorama-dim-label">优势</span>
              {strengths.slice(0, 3).map((s) => <span key={s} className="tm-portrait-dim-tag strength">{s}</span>)}
            </div>
          )}
          {weaknesses.length > 0 && (
            <div className="tm-panorama-dim-group">
              <span className="tm-panorama-dim-label">短板</span>
              {weaknesses.slice(0, 3).map((w) => <span key={w} className="tm-portrait-dim-tag weakness">{w}</span>)}
            </div>
          )}
        </div>
        {risks.length > 0 && (
          <div className="tm-portrait-tags-col">
            <div className="tm-panorama-dim-group">
              <span className="tm-panorama-dim-label">高频风险</span>
              {risks.map((r) => <span key={r.rule_id} className="tm-portrait-dim-tag risk">{r.rule_id} <small>({r.count})</small></span>)}
            </div>
          </div>
        )}
      </div>

      {Object.keys(intentDist).length > 0 && (
        <div className="tm-portrait-section">
          <div className="tm-portrait-section-title">行为意图分布</div>
          <IntentDistributionBar dist={intentDist} />
        </div>
      )}

      <div className="tm-portrait-engage-row">
        <div className="tm-engage-item">
          <span className="tm-engage-v">{engage.total_submissions ?? data.total_submissions ?? 0}</span>
          <span className="tm-engage-l">总提交</span>
        </div>
        <div className="tm-engage-item">
          <span className="tm-engage-v">{engage.scored_count ?? 0}</span>
          <span className="tm-engage-l">有效打分</span>
        </div>
        <div className="tm-engage-item">
          <span className="tm-engage-v" style={{ color: "#ef4444" }}>{engage.risk_count ?? 0}</span>
          <span className="tm-engage-l">触发风险次数</span>
        </div>
        {typeof beh.avg_submit_interval_days === "number" && (
          <div className="tm-engage-item">
            <span className="tm-engage-v">{beh.avg_submit_interval_days.toFixed(1)}</span>
            <span className="tm-engage-l">平均提交间隔(天)</span>
          </div>
        )}
        {typeof beh.improvement_rate === "number" && (
          <div className="tm-engage-item">
            <span className="tm-engage-v" style={{ color: beh.improvement_rate >= 0 ? "#22c55e" : "#ef4444" }}>
              {beh.improvement_rate >= 0 ? "+" : ""}{beh.improvement_rate.toFixed(1)}
            </span>
            <span className="tm-engage-l">首末进步</span>
          </div>
        )}
        {typeof data.trend === "number" && (
          <div className="tm-engage-item">
            <span className="tm-engage-v" style={{ color: data.trend >= 0 ? "#22c55e" : "#ef4444" }}>
              {data.trend >= 0 ? "+" : ""}{data.trend.toFixed(1)}
            </span>
            <span className="tm-engage-l">近中期变化</span>
          </div>
        )}
      </div>

      {Array.isArray(data.growth_trajectory) && data.growth_trajectory.length >= 2 && (
        <div className="tm-portrait-section">
          <div className="tm-portrait-section-title">成长轨迹</div>
          <GrowthSparkline points={data.growth_trajectory} />
        </div>
      )}

      {phaseHistory.length > 0 && (
        <div className="tm-portrait-section">
          <div className="tm-portrait-section-title">阶段历程</div>
          <PhaseTimeline history={phaseHistory} />
        </div>
      )}

      {(latestTask?.title || latestTask?.description || (latestTask?.acceptance_criteria || []).length > 0) && (
        <div className="tm-portrait-section">
          <div className="tm-portrait-section-title">最近任务</div>
          <div className="sp-latest-task">
            {latestTask?.title && <div className="sp-latest-task-title">{latestTask.title}</div>}
            {latestTask?.description && <div className="sp-latest-task-desc">{latestTask.description}</div>}
            {(latestTask?.acceptance_criteria || []).length > 0 && (
              <ul className="sp-latest-task-ac">
                {(latestTask!.acceptance_criteria || []).map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {evidenceQuotes.length > 0 && (
        <div className="tm-portrait-section">
          <div className="tm-portrait-section-title">近期证据摘录</div>
          <div className="sp-evidence-quotes">
            {evidenceQuotes.slice(0, 3).map((q, i) => (
              <div className="sp-evidence-quote" key={i}>
                <span className="sp-evidence-quote-mark">“</span>
                <span className="sp-evidence-quote-text">{q.text || "—"}</span>
                {q.source && <span className="sp-evidence-quote-src">— {q.source}</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {data.trend_summary && (
        <div className="tm-portrait-trend">{data.trend_summary}</div>
      )}
      {data.overall_assessment && (
        <div className="tm-panorama-overall">{data.overall_assessment}</div>
      )}

      {showHow && (
        <div className="sp-panorama-how">
          {data.overview_rationale && (
            <RationaleCard rationale={data.overview_rationale as Rationale} title="总览 · 如何得出" />
          )}
          {data.strength_rationale && (
            <RationaleCard rationale={data.strength_rationale as Rationale} title="优势维度如何得出" compact />
          )}
          {data.weakness_rationale && (
            <RationaleCard rationale={data.weakness_rationale as Rationale} title="待加强维度如何得出" compact />
          )}
          {data.growth_rationale && (
            <RationaleCard rationale={data.growth_rationale as Rationale} title="成长轨迹如何得出" compact />
          )}
          {Array.isArray(data.rubric_heatmap) && data.rubric_heatmap.length > 0 && (
            <div className="sp-panorama-how-rubric">
              <div className="rc-section-title" style={{ marginBottom: 8 }}>九维每维度计算依据</div>
              <div className="sp-portrait-grid">
                {data.rubric_heatmap.map((h: any) => (
                  <div key={h.item} className="sp-portrait-card">
                    <div className="sp-portrait-card-title">
                      <span>{h.item}</span>
                      <span className="sp-portrait-card-score" style={{ color: h.avg_score >= 7 ? "#22c55e" : h.avg_score >= 4 ? "#f59e0b" : "#ef4444" }}>{h.avg_score}</span>
                    </div>
                    {h.rationale && (
                      <div style={{ marginTop: 8 }}>
                        <RationaleCard rationale={h.rationale as Rationale} compact />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ScoreRing({ score, max = 10, size = 72, label }: { score: number; max?: number; size?: number; label: string }) {
  const r = (size - 10) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.min(score / max, 1);
  const offset = c * (1 - pct);
  const color = score >= 7 ? "#22c55e" : score >= 4 ? "#f59e0b" : "#ef4444";
  return (
    <div className="prof-ring-wrap">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--border)" strokeWidth="5" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth="5"
          strokeDasharray={c} strokeDashoffset={offset} strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: "stroke-dashoffset 0.6s ease" }} />
        <text x={size / 2} y={size / 2 - 4} textAnchor="middle" fontSize="18" fontWeight="700" fill={color}>{score}</text>
        <text x={size / 2} y={size / 2 + 12} textAnchor="middle" fontSize="8" fill="var(--text-muted)">/{max}</text>
      </svg>
      <span className="prof-ring-label">{label}</span>
    </div>
  );
}

export default function StudentProfilePage() {
  const [user, setUser] = useState<any>(null);
  const [submissions, setSubmissions] = useState<any[]>([]);
  const [conversations, setConversations] = useState<any[]>([]);
  const [interventions, setInterventions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  // 画像状态
  const [portraitTab, setPortraitTab] = useState<"overall" | "conversations">("overall");
  const [overallPortrait, setOverallPortrait] = useState<any>(null);
  const [conversationPortraits, setConversationPortraits] = useState<any[]>([]);
  const [activeConvId, setActiveConvId] = useState<string>("");
  const [convPortraitDetail, setConvPortraitDetail] = useState<any>(null);
  const [convCardWhy, setConvCardWhy] = useState<string | null>(null);

  useEffect(() => {
    try {
      const raw = localStorage.getItem("va_user");
      if (raw) setUser(JSON.parse(raw));
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (!user) { setLoading(false); return; }
    const pid = `project-${user.user_id}`;
    Promise.all([
      fetch(`${API}/api/project/${encodeURIComponent(pid)}/submissions`).then((r) => r.json()).catch(() => ({ submissions: [] })),
      fetch(`${API}/api/conversations?project_id=${encodeURIComponent(pid)}`).then((r) => r.json()).catch(() => ({ conversations: [] })),
      fetch(`${API}/api/student/interventions?project_id=${encodeURIComponent(pid)}`).then((r) => r.json()).catch(() => ({ interventions: [] })),
    ]).then(([subData, convData, interventionData]) => {
      setSubmissions(subData.submissions ?? []);
      setConversations(convData.conversations ?? []);
      setInterventions(interventionData.interventions ?? []);
      setLoading(false);
    });
    // 画像数据并行拉取
    fetch(`${API}/api/student/${encodeURIComponent(user.user_id)}/portrait/overall`)
      .then((r) => r.json()).then((data) => setOverallPortrait(data.portrait || null))
      .catch(() => {});
    fetch(`${API}/api/student/${encodeURIComponent(user.user_id)}/portrait/conversations`)
      .then((r) => r.json()).then((data) => setConversationPortraits(data.cards || []))
      .catch(() => {});
  }, [user]);

  // 切换到会话画像时加载详情
  useEffect(() => {
    if (!user || !activeConvId) return;
    fetch(`${API}/api/student/${encodeURIComponent(user.user_id)}/portrait/conversation/${encodeURIComponent(activeConvId)}`)
      .then((r) => r.json()).then((data) => setConvPortraitDetail(data))
      .catch(() => setConvPortraitDetail(null));
  }, [user, activeConvId]);

  const stats = useMemo(() => {
    if (!submissions.length) return { total: 0, avg: 0, recent: [], bestScore: 0, riskCount: 0, scoreHistory: [] };
    const scores = submissions.map((s) => s.overall_score ?? 0).filter((s) => s > 0);
    const avg = scores.length ? Math.round((scores.reduce((a: number, b: number) => a + b, 0) / scores.length) * 10) / 10 : 0;
    const best = scores.length ? Math.max(...scores) : 0;
    const riskCount = submissions.reduce((a: number, s: any) => a + ((s.triggered_rules ?? []).length), 0);
    const recent = submissions.slice(0, 8);
    const scoreHistory = submissions.slice(0, 12).reverse().map((s, i) => ({ idx: i, score: s.overall_score ?? 0, date: formatBjTime(s.created_at) }));
    return { total: submissions.length, avg, recent, bestScore: best, riskCount, scoreHistory };
  }, [submissions]);

  const totalMsgs = useMemo(() => conversations.reduce((a: number, c: any) => a + (c.message_count ?? 0), 0), [conversations]);

  if (!user) {
    return (
      <main className="profile-page">
        <div className="profile-empty">
          <div className="prof-empty-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="1.2"><circle cx="12" cy="8" r="4"/><path d="M20 21c0-4.418-3.582-8-8-8s-8 3.582-8 8"/></svg>
          </div>
          <h2>尚未登录</h2>
          <p>请先登录后查看个人中心</p>
          <Link href="/auth/login" className="prof-login-btn">前往登录</Link>
        </div>
      </main>
    );
  }

  return (
    <main className="profile-page">
      <header className="profile-topbar">
        <Link href="/student" className="profile-back">
          <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M10 2L4 8l6 6" /></svg>
          返回工作台
        </Link>
        <h1>个人中心</h1>
        <Link href="/auth/reset-password" className="profile-setting-link">修改密码</Link>
      </header>

      {/* Hero Section */}
      <div className="profile-hero fade-up">
        <div className="prof-hero-left">
          <div className="profile-avatar">
            <span>{(user.display_name ?? "S")[0].toUpperCase()}</span>
          </div>
          <div className="profile-info">
            <div className="prof-name-row">
              <h2>{user.display_name}</h2>
              <span className="profile-role-badge">{user.role === "student" ? "学生" : user.role === "teacher" ? "教师" : "管理员"}</span>
            </div>
            <p className="profile-meta">
              {user.email}
              {user.student_id ? ` · ${user.student_id}` : ""}
              {user.class_id ? ` · ${user.class_id}班` : ""}
              {user.cohort_id ? ` · ${user.cohort_id}` : ""}
            </p>
            {user.bio && <p className="profile-bio">{user.bio}</p>}
            <p className="prof-join-date">注册于 {formatBjDate(user.created_at)}</p>
          </div>
        </div>
        {stats.total > 0 && (
          <div className="prof-hero-rings">
            <ScoreRing score={stats.avg} label="平均分" />
            <ScoreRing score={stats.bestScore} label="最高分" />
          </div>
        )}
      </div>

      {loading ? (
        <div className="profile-loading">
          <div className="prof-loading-spinner" />
          <span>加载数据中...</span>
        </div>
      ) : (
        <>
          {/* KPI Grid */}
          <section className="profile-kpi-grid fade-up">
            {[
              { val: stats.total, label: "提交总数", icon: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z", color: "#6366f1" },
              { val: conversations.length, label: "对话总数", icon: "M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z", color: "#8b5cf6" },
              { val: totalMsgs, label: "消息总数", icon: "M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z", color: "#06b6d4" },
              { val: stats.riskCount, label: "累计风险", icon: "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z", color: "#f59e0b" },
              { val: interventions.length, label: "教师任务", icon: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2", color: "#ec4899" },
            ].map(({ val, label, icon, color }) => (
              <div key={label} className="profile-kpi">
                <div className="prof-kpi-icon" style={{ color }}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d={icon}/></svg>
                </div>
                <strong>{val}</strong>
                <span>{label}</span>
              </div>
            ))}
          </section>

          {/* Personal Portrait —— 总画像 / 按会话 双 Tab */}
          <section className="profile-section fade-up">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
              <h3 style={{ margin: 0 }}>个人画像</h3>
              <div className="sp-portrait-tabs">
                <button
                  className={`sp-portrait-tab ${portraitTab === "overall" ? "active" : ""}`}
                  onClick={() => setPortraitTab("overall")}
                >总画像</button>
                <button
                  className={`sp-portrait-tab ${portraitTab === "conversations" ? "active" : ""}`}
                  onClick={() => setPortraitTab("conversations")}
                >按会话查看</button>
              </div>
            </div>

            {portraitTab === "overall" ? (
              overallPortrait ? (
                <StudentPortraitPanorama data={overallPortrait as PanoramaData} title="总画像" />
              ) : (
                <p className="profile-empty-hint">画像生成中…请先提交几次诊断。</p>
              )
            ) : (
              <div>
                {conversationPortraits.length > 0 ? (
                  <>
                    <div className="sp-portrait-grid" style={{ marginBottom: 16 }}>
                      {conversationPortraits.map((c) => {
                        const rat: Rationale | null = c.last_score
                          ? {
                              field: `conv:last_score:${c.conversation_id}`,
                              value: c.last_score,
                              formula: "latest(overall_score in this conversation)",
                              formula_display: `该会话最近一次评分 = ${c.last_score}\n阶段：${c.project_phase || "—"}\n消息数：${c.message_count ?? 0}`,
                              inputs: [
                                { label: "最新评分", value: c.last_score },
                                { label: "阶段", value: c.project_phase || "—" },
                                { label: "消息数", value: c.message_count ?? 0 },
                              ],
                              note: "点击卡片查看完整画像",
                            }
                          : null;
                        return (
                        <div
                          key={c.conversation_id}
                          className="sp-portrait-card"
                          onClick={() => setActiveConvId(c.conversation_id)}
                          style={activeConvId === c.conversation_id ? { borderColor: "rgba(139,127,216,0.7)", boxShadow: "0 10px 24px rgba(139,127,216,0.25)" } : {}}
                        >
                          <div className="sp-portrait-card-title">
                            <span>{c.title || "会话"}</span>
                            <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                              <span className="sp-portrait-card-score" style={{ color: c.last_score >= 7 ? "#22c55e" : c.last_score >= 4 ? "#f59e0b" : "#ef4444" }}>{c.last_score || 0}</span>
                              {rat && (
                                <button
                                  type="button"
                                  className="sp-card-why-btn"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setConvCardWhy((prev) => (prev === c.conversation_id ? null : c.conversation_id));
                                  }}
                                  title="查看分数如何得出"
                                >?</button>
                              )}
                            </div>
                          </div>
                          {rat && convCardWhy === c.conversation_id && (
                            <div className="sp-card-why-pop" onClick={(e) => e.stopPropagation()}>
                              <RationaleCard rationale={rat} compact />
                            </div>
                          )}
                          <div className="sp-portrait-card-meta">
                            <span>{c.project_phase || "持续迭代"}</span>
                            <span>{c.message_count ?? 0} 条消息</span>
                          </div>
                          <div className="sp-portrait-card-summary">{c.summary || "—"}</div>
                          {(c.top_risks || []).length > 0 && (
                            <div className="sp-portrait-risks">
                              {(c.top_risks || []).slice(0, 4).map((r: string) => (
                                <span key={r} className="sp-portrait-risk-chip">{r}</span>
                              ))}
                            </div>
                          )}
                        </div>
                        );
                      })}
                    </div>
                    {activeConvId && convPortraitDetail && !convPortraitDetail.status && (
                      <>
                        {convPortraitDetail.portrait ? (
                          <StudentPortraitPanorama
                            data={convPortraitDetail.portrait as PanoramaData}
                            projectCard={convPortraitDetail.project_card as ProjectCardData}
                            title={`会话画像 · ${conversationPortraits.find((c) => c.conversation_id === activeConvId)?.title || ""}`}
                          />
                        ) : (
                          <p className="profile-empty-hint">该会话画像生成中…</p>
                        )}
                        {convPortraitDetail.maturity_snapshot?.maturity_breakdown_rationale && (
                          <div style={{ marginTop: 12 }}>
                            <div className="rc-section-title" style={{ marginBottom: 6 }}>计划书成熟度</div>
                            <RationaleCard
                              rationale={convPortraitDetail.maturity_snapshot.maturity_breakdown_rationale as Rationale}
                            />
                          </div>
                        )}
                      </>
                    )}
                  </>
                ) : (
                  <p className="profile-empty-hint">暂无会话画像，先去工作台完成至少一次对话。</p>
                )}
              </div>
            )}
          </section>

          {/* Score Trend (mini sparkline) */}
          {stats.scoreHistory.length >= 2 && (
            <section className="profile-section prof-trend-section fade-up">
              <h3>分数趋势</h3>
              <div className="prof-sparkline-wrap">
                <svg viewBox={`0 0 ${Math.max(stats.scoreHistory.length * 40, 200)} 80`} className="prof-sparkline">
                  <defs>
                    <linearGradient id="sparkG" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#6366f1" stopOpacity="0.3" />
                      <stop offset="100%" stopColor="#6366f1" stopOpacity="0" />
                    </linearGradient>
                  </defs>
                  {(() => {
                    const pts = stats.scoreHistory;
                    const w = Math.max(pts.length * 40, 200);
                    const maxY = 10;
                    const px = (i: number) => (i / Math.max(pts.length - 1, 1)) * (w - 20) + 10;
                    const py = (v: number) => 70 - (v / maxY) * 60;
                    const line = pts.map((p, i) => `${i === 0 ? "M" : "L"}${px(i)},${py(p.score)}`).join(" ");
                    const area = line + ` L${px(pts.length - 1)},70 L${px(0)},70 Z`;
                    return (
                      <>
                        <path d={area} fill="url(#sparkG)" />
                        <path d={line} fill="none" stroke="#6366f1" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                        {pts.map((p, i) => (
                          <g key={i}>
                            <circle cx={px(i)} cy={py(p.score)} r="3.5" fill="#6366f1" stroke="var(--bg-primary)" strokeWidth="2" />
                            <text x={px(i)} y={py(p.score) - 8} textAnchor="middle" fontSize="9" fill="var(--text-muted)">{p.score}</text>
                          </g>
                        ))}
                      </>
                    );
                  })()}
                </svg>
              </div>
            </section>
          )}

          {/* Recent Submissions */}
          {stats.recent.length > 0 && (
            <section className="profile-section fade-up">
              <h3>近期提交</h3>
              <div className="profile-sub-list">
                {stats.recent.map((s: any, i: number) => {
                  const sc = s.overall_score ?? 0;
                  const clr = sc >= 7 ? "#22c55e" : sc >= 4 ? "#f59e0b" : sc > 0 ? "#ef4444" : "var(--text-muted)";
                  return (
                    <div key={i} className="profile-sub-item">
                      <div className="profile-sub-left">
                        <span className={`profile-sub-type ${s.source_type === "file" ? "file" : "text"}`}>{s.source_type === "file" ? "文件" : "文本"}</span>
                        <span className="profile-sub-preview">{s.text_preview || s.filename || "-"}</span>
                      </div>
                      <div className="profile-sub-right">
                        <span className="profile-sub-score" style={{ color: clr }}>{sc > 0 ? sc : "-"}<small>/10</small></span>
                        <span className="profile-sub-date">{formatBjTime(s.created_at)}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* Interventions */}
          <section className="profile-section fade-up">
            <h3>教师任务</h3>
            {interventions.length > 0 ? (
              <div className="profile-sub-list">
                {interventions.slice(0, 8).map((item: any, i: number) => {
                  const statusMap: Record<string, [string, string]> = {
                    pending: ["待处理", "#f59e0b"],
                    acknowledged: ["已确认", "#06b6d4"],
                    completed: ["已完成", "#22c55e"],
                  };
                  const [statusLabel, statusColor] = statusMap[item.status] ?? [item.status || "-", "var(--text-muted)"];
                  return (
                    <div key={item.intervention_id || i} className="profile-sub-item">
                      <div className="profile-sub-left">
                        <span className="profile-sub-type intervention">{item.scope_type === "project" ? "项目" : item.scope_type === "team" ? "团队" : "个人"}</span>
                        <span className="profile-sub-preview">{item.title || item.reason_summary}</span>
                      </div>
                      <div className="profile-sub-right">
                        <span className="prof-status-badge" style={{ color: statusColor, borderColor: statusColor }}>{statusLabel}</span>
                        <span className="profile-sub-date">{formatBjTime(item.sent_at || item.created_at)}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : <p className="profile-empty-hint">暂无教师下发的任务</p>}
          </section>

          {/* Conversations */}
          <section className="profile-section fade-up">
            <h3>我的对话</h3>
            {conversations.length > 0 ? (
              <div className="profile-conv-list">
                {conversations.slice(0, 12).map((c: any) => (
                  <Link key={c.conversation_id} href="/student" className="profile-conv-item">
                    <div className="prof-conv-icon">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
                    </div>
                    <div className="prof-conv-content">
                      <span className="profile-conv-title">{c.title || "新对话"}</span>
                      <span className="profile-conv-meta">{c.message_count ?? 0} 条消息 · {formatBjTime(c.created_at)}</span>
                    </div>
                  </Link>
                ))}
              </div>
            ) : <p className="profile-empty-hint">暂无对话记录，去工作台开始你的第一次对话吧</p>}
          </section>

          {/* Account Info */}
          <section className="profile-section fade-up">
            <h3>账号信息</h3>
            <div className="profile-info-grid">
              {[
                { label: "邮箱", value: user.email },
                { label: "角色", value: user.role === "student" ? "学生" : user.role === "teacher" ? "教师" : "管理员" },
                ...(user.student_id ? [{ label: "学号", value: user.student_id }] : []),
                ...(user.class_id ? [{ label: "班级", value: user.class_id }] : []),
                ...(user.cohort_id ? [{ label: "学期", value: user.cohort_id }] : []),
                { label: "注册时间", value: formatBjDate(user.created_at) },
              ].map(({ label, value }) => (
                <div key={label}>
                  <span>{label}</span>
                  <strong>{value}</strong>
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </main>
  );
}
