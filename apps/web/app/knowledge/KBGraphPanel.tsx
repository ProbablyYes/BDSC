"use client";

import React, { useState, useEffect, useCallback, useRef, useMemo } from "react";
import dynamic from "next/dynamic";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8037").trim().replace(/\/+$/, "");

function gradeClass(grade?: string | null): string {
  if (!grade) return "b";
  return grade.replace("+", "p").toLowerCase();
}

interface Props { onClose: () => void }
type TabId = "quality" | "kg" | "hyper";

const TAB_META: { id: TabId; label: string; sub: string; icon: string }[] = [
  { id: "quality", label: "质量评估", sub: "Quality", icon: "◆" },
  { id: "kg", label: "知识图谱", sub: "Knowledge Graph", icon: "◎" },
  { id: "hyper", label: "超图", sub: "Hypergraph", icon: "⬡" },
];

export default function KBGraphPanel({ onClose }: Props) {
  const [tab, setTab] = useState<TabId>("quality");

  /* ── KG state (dual-layer: galaxy overview + detail) ── */
  const [kgViewMode, setKgViewMode] = useState<"overview" | "detail">("overview");
  const [kgFullData, setKgFullData] = useState<any>(null);
  const [kgFullLoading, setKgFullLoading] = useState(false);
  const [kgFullError, setKgFullError] = useState("");
  const [kgDetailData, setKgDetailData] = useState<any>(null);
  const [kgDetailLoading, setKgDetailLoading] = useState(false);
  const [kgDetailError, setKgDetailError] = useState("");
  const [kgDetailSgId, setKgDetailSgId] = useState<string>("");
  const [kgDetailSelectedNode, setKgDetailSelectedNode] = useState<any>(null);
  const [kgDetailSearch, setKgDetailSearch] = useState("");
  const [kgDetailHighlight, setKgDetailHighlight] = useState<string>("");

  /* ── Hyper state ── */
  const [hyperData, setHyperData] = useState<any>(null);
  const [hyperLoading, setHyperLoading] = useState(false);
  const [hyperError, setHyperError] = useState("");
  const [hoveredHE, setHoveredHE] = useState<string | null>(null);
  const [hyperGroupFilter, setHyperGroupFilter] = useState<string | null>(null);
  const [hyperFamilyFilter, setHyperFamilyFilter] = useState<string | null>(null);
  const [hyperShowGroups, setHyperShowGroups] = useState(false);
  const [hyperSelectedFamilies, setHyperSelectedFamilies] = useState<Set<string>>(new Set());
  const [clickedHE, setClickedHE] = useState<string | null>(null);

  /* ── Quality state ── */
  const [qualityData, setQualityData] = useState<any>(null);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [qualityError, setQualityError] = useState("");
  const [expandedDim, setExpandedDim] = useState<string | null>(null);

  const kgGalaxyRef = useRef<any>(null);
  const kgDetailRef = useRef<any>(null);

  /* ── Loaders ── */
  const loadKGFull = useCallback(async () => {
    setKgFullLoading(true); setKgFullError("");
    try {
      const r = await fetch(`${API}/api/kg/subgraphs`);
      const d = await r.json();
      if (d.error || !d.graph) setKgFullError(d.error || "数据格式异常");
      else setKgFullData(d);
    } catch (e: any) { setKgFullError("连接后端失败: " + (e?.message || "")); }
    setKgFullLoading(false);
  }, []);

  const loadKGDetail = useCallback(async (sgId: string) => {
    setKgDetailLoading(true); setKgDetailError(""); setKgDetailSelectedNode(null);
    setKgDetailSgId(sgId);
    try {
      const r = await fetch(`${API}/api/kg/subgraph-detail/${sgId}`);
      const d = await r.json();
      if (d.error || !d.graph) setKgDetailError(d.error || "数据格式异常");
      else setKgDetailData(d);
    } catch (e: any) { setKgDetailError("连接后端失败: " + (e?.message || "")); }
    setKgDetailLoading(false);
  }, []);

  const loadHyper = useCallback(async () => {
    setHyperLoading(true); setHyperError("");
    try {
      const r = await fetch(`${API}/api/kg/hypergraph-viz`);
      const d = await r.json();
      if (d.error || !d.graph) setHyperError(d.error || "数据格式异常");
      else setHyperData(d);
    } catch (e: any) { setHyperError("连接后端失败: " + (e?.message || "")); }
    setHyperLoading(false);
  }, []);

  const loadQuality = useCallback(async () => {
    setQualityLoading(true); setQualityError("");
    try {
      const r = await fetch(`${API}/api/kg/quality`);
      const d = await r.json();
      if (d.error || !Array.isArray(d.dimensions)) setQualityError(d.error || "质量报告格式异常");
      else setQualityData(d);
    } catch (e: any) { setQualityError("连接后端失败: " + (e?.message || "")); }
    setQualityLoading(false);
  }, []);

  useEffect(() => {
    if (tab === "kg" && !kgFullData && !kgFullLoading && !kgFullError) loadKGFull();
    if (tab === "hyper" && !hyperData && !hyperLoading && !hyperError) loadHyper();
    if (tab === "quality" && !qualityData && !qualityLoading && !qualityError) loadQuality();
  }, [tab, kgFullData, kgFullLoading, kgFullError, hyperData, hyperLoading, hyperError, qualityData, qualityLoading, qualityError, loadKGFull, loadHyper, loadQuality]);

  /* ── KG Galaxy: fixed-sector layout for all real nodes ── */
  const SG_LABELS: Record<string, string> = {
    pain: "痛点", solution: "方案", innovation: "创新点",
    business_model: "商业模式", market: "市场分析", execution: "执行计划",
    risk_control: "风控", evidence: "证据", stakeholder: "利益方",
    category: "类别", risk_rule: "风险规则", rubric: "评审标准", project: "项目",
    entrepreneur_domain: "创业领域", competition: "赛事类型", entrepreneurship: "创业案例", innovation_case: "创新案例"
  };

  const galaxyGraphData = useMemo(() => {
    if (!kgFullData?.graph) return { nodes: [], links: [] };
    const rawNodes: any[] = kgFullData.graph.nodes;
    const rawLinks: any[] = kgFullData.graph.links;

    const sgIds = [...new Set(rawNodes.map((n: any) => n.subgraph).filter(Boolean))].filter(s => s !== "project");
    const sectorAngle: Record<string, number> = {};
    sgIds.forEach((sg, i) => { sectorAngle[sg] = (2 * Math.PI * i) / sgIds.length - Math.PI / 2; });

    const rng = (seed: number) => {
      let s = seed;
      return () => { s = (s * 16807 + 0) % 2147483647; return s / 2147483647; };
    };

    // 创业领域/创业/创新/赛事类型节点特殊布局
    const nodes = rawNodes.map((n: any, idx: number) => {
      const rand = rng(idx * 7919 + 31);
      // 创业领域节点聚集在右上角，颜色根据level_rank高亮
      if (n.type === "entrepreneur_domain") {
        let color = n.color || "#fb923c";
        if (n.level_rank === 2 || n.level_rank === "2") color = "#ef4444";
        return { ...n, fx: 350 + (rand() - 0.5) * 60, fy: -250 + (rand() - 0.5) * 60, color };
      }
      // 赛事类型节点聚集在右下角
      if (n.type === "competition") {
        return { ...n, fx: 350 + (rand() - 0.5) * 60, fy: 250 + (rand() - 0.5) * 60 };
      }
      // 创业案例节点聚集在左下角
      if (n.type === "entrepreneurship") {
        return { ...n, fx: -350 + (rand() - 0.5) * 60, fy: 250 + (rand() - 0.5) * 60 };
      }
      // 创新案例节点聚集在左上角
      if (n.type === "innovation") {
        return { ...n, fx: -350 + (rand() - 0.5) * 60, fy: -250 + (rand() - 0.5) * 60 };
      }
      if (n.type === "Project" || n.subgraph === "project") {
        return { ...n, fx: (rand() - 0.5) * 180, fy: (rand() - 0.5) * 180 };
      }
      const base = sectorAngle[n.subgraph];
      if (base === undefined) return { ...n, fx: (rand() - 0.5) * 200, fy: (rand() - 0.5) * 200 };
      const spread = (Math.PI / sgIds.length) * 0.75;
      const angle = base + (rand() - 0.5) * spread;
      const dist = 240 + rand() * 300;
      return { ...n, fx: dist * Math.cos(angle), fy: dist * Math.sin(angle) };
    });

    return { nodes, links: rawLinks };
  }, [kgFullData]);

  const galaxySectorLabels = useMemo(() => {
    if (!kgFullData?.graph) return [];
    const rawNodes: any[] = kgFullData.graph.nodes;
    const sgIds = [...new Set(rawNodes.map((n: any) => n.subgraph).filter(Boolean))].filter(s => s !== "project");
    const sgCounts: Record<string, number> = {};
    const sgColors: Record<string, string> = {};
    for (const n of rawNodes) {
      if (!n.subgraph || n.subgraph === "project") continue;
      sgCounts[n.subgraph] = (sgCounts[n.subgraph] || 0) + 1;
      if (!sgColors[n.subgraph]) sgColors[n.subgraph] = n.color || "#888";
    }
    return sgIds.map((sg, i) => {
      const angle = (2 * Math.PI * i) / sgIds.length - Math.PI / 2;
      const dist = 600;
      return { id: sg, label: SG_LABELS[sg] || sg, count: sgCounts[sg] || 0, color: sgColors[sg] || "#888", x: dist * Math.cos(angle), y: dist * Math.sin(angle), angle };
    });
  }, [kgFullData]);

  const renderGalaxySectors = useCallback((ctx: CanvasRenderingContext2D, globalScale: number) => {
    for (const sec of galaxySectorLabels) {
      const fontSize = Math.max(14 / globalScale, 5);
      ctx.font = `bold ${fontSize}px system-ui, sans-serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillStyle = sec.color + "CC";
      ctx.fillText(`${sec.label}`, sec.x, sec.y - fontSize * 0.7);
      ctx.font = `${fontSize * 0.7}px system-ui, sans-serif`;
      ctx.fillStyle = sec.color + "88";
      ctx.fillText(`${sec.count} 节点`, sec.x, sec.y + fontSize * 0.5);
    }
    const projCount = kgFullData?.stats?.total_projects || 0;
    if (projCount > 0) {
      const fs = Math.max(12 / globalScale, 4);
      ctx.font = `bold ${fs}px system-ui, sans-serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillStyle = "rgba(255,255,255,0.5)";
      ctx.fillText(`项目 (${projCount})`, 0, -100);
    }
  }, [galaxySectorLabels, kgFullData]);

  /* ── Detail view: filtered data for search highlighting ── */
  const kgDetailFiltered = useMemo(() => {
    if (!kgDetailData?.graph) return { nodes: [], links: [] };
    const { nodes, links } = kgDetailData.graph;
    if (!kgDetailHighlight) return { nodes, links };
    const matchIds = new Set(
      nodes.filter((n: any) => n.name?.toLowerCase().includes(kgDetailHighlight.toLowerCase())).map((n: any) => n.id)
    );
    return { nodes, links, highlightIds: matchIds };
  }, [kgDetailData, kgDetailHighlight]);

  /* ── Filtered hyper graph based on selected families ── */
  const filteredHyperGraph = useMemo(() => {
    if (!hyperData?.graph?.nodes) return { nodes: [], links: [] };
    const sel = hyperSelectedFamilies;
    if (sel.size === 0) return hyperData.graph;

    const visibleHEs = new Set<string>();
    for (const n of hyperData.graph.nodes) {
      if (n.type === "Hyperedge" && sel.has(n.family)) visibleHEs.add(n.id);
    }
    const connectedIds = new Set<string>(visibleHEs);
    for (const l of hyperData.graph.links) {
      const s = typeof l.source === "string" ? l.source : l.source?.id;
      const t = typeof l.target === "string" ? l.target : l.target?.id;
      if (visibleHEs.has(s)) connectedIds.add(t);
      if (visibleHEs.has(t)) connectedIds.add(s);
    }
    const nodes = hyperData.graph.nodes.filter((n: any) => connectedIds.has(n.id));
    const links = hyperData.graph.links.filter((l: any) => {
      const s = typeof l.source === "string" ? l.source : l.source?.id;
      const t = typeof l.target === "string" ? l.target : l.target?.id;
      return connectedIds.has(s) && connectedIds.has(t);
    });
    return { nodes, links };
  }, [hyperData, hyperSelectedFamilies]);

  const hyperFilteredStats = useMemo(() => {
    if (!filteredHyperGraph.nodes.length) return null;
    const edges = filteredHyperGraph.nodes.filter((n: any) => n.type === "Hyperedge").length;
    const hnodes = filteredHyperGraph.nodes.filter((n: any) => n.type === "HyperNode").length;
    const rules = filteredHyperGraph.nodes.filter((n: any) => n.type === "RiskRule").length;
    const rubrics = filteredHyperGraph.nodes.filter((n: any) => n.type === "RubricItem").length;
    return { edges, hnodes, rules, rubrics, total: filteredHyperGraph.nodes.length, links: filteredHyperGraph.links.length };
  }, [filteredHyperGraph]);

  const toggleHyperFamily = useCallback((family: string) => {
    setHyperSelectedFamilies(prev => {
      const next = new Set(prev);
      if (next.has(family)) next.delete(family); else next.add(family);
      return next;
    });
  }, []);

  const clearHyperFamilyFilter = useCallback(() => {
    setHyperSelectedFamilies(new Set());
  }, []);

  const _activeHE = hoveredHE || clickedHE;

  const hoveredHEMembers = useMemo(() => {
    if (!_activeHE || !filteredHyperGraph?.links) return new Set<string>();
    const links: any[] = filteredHyperGraph.links;
    const ids = new Set<string>();
    for (const l of links) {
      const s = typeof l.source === "string" ? l.source : l.source?.id;
      const t = typeof l.target === "string" ? l.target : l.target?.id;
      if (s === _activeHE) ids.add(t);
      if (t === _activeHE) ids.add(s);
    }
    return ids;
  }, [_activeHE, filteredHyperGraph]);

  const hoveredHEInfo = useMemo(() => {
    if (!_activeHE || !filteredHyperGraph?.nodes) return null;
    const heNode = filteredHyperGraph.nodes.find((n: any) => n.id === _activeHE);
    if (!heNode) return null;
    const members = filteredHyperGraph.nodes.filter((n: any) => hoveredHEMembers.has(n.id));
    const riskRules = members.filter((m: any) => m.type === "RiskRule");
    const rubricItems = members.filter((m: any) => m.type === "RubricItem");
    const hyperNodes = members.filter((m: any) => m.type === "HyperNode");
    return { ...heNode, riskRules, rubricItems, hyperNodes, totalMembers: members.length };
  }, [_activeHE, filteredHyperGraph, hoveredHEMembers]);

  const hyperNodeColor = useCallback((node: any) => {
    if (!_activeHE) return node.color || "#38bdf8";
    if (node.id === _activeHE) return "#fbbf24";
    return hoveredHEMembers.has(node.id) ? "#fbbf24" : "rgba(148,163,184,0.15)";
  }, [_activeHE, hoveredHEMembers]);

  const hyperLinkColor = useCallback((link: any) => {
    if (!_activeHE) return "rgba(148,163,184,0.15)";
    const s = typeof link.source === "string" ? link.source : link.source?.id;
    const t = typeof link.target === "string" ? link.target : link.target?.id;
    return (s === _activeHE || t === _activeHE) ? "rgba(251,191,36,0.5)" : "rgba(148,163,184,0.05)";
  }, [_activeHE]);

  const ErrorBox = ({ msg, onRetry }: { msg: string; onRetry: () => void }) => (
    <div className="kb-loading">
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: 15, color: "#f59e0b", marginBottom: 10 }}>加载失败</div>
        <div style={{ fontSize: 13, color: "#94a3b8", maxWidth: 460, lineHeight: 1.7 }}>{msg}</div>
        <button onClick={onRetry} style={{ marginTop: 16, padding: "8px 24px", background: "rgba(59,130,246,0.15)", border: "1px solid rgba(59,130,246,0.3)", borderRadius: 8, color: "#93c5fd", cursor: "pointer", fontSize: 13 }}>重试</button>
      </div>
    </div>
  );

  /* ── Neo4j stats for quality tab ── */
  const neoStats = qualityData?.neo4j_stats || {};
  const nodeLabels = neoStats.kg_node_labels || neoStats.node_labels || {};
  const relTypes = neoStats.kg_relationship_types || neoStats.relationship_types || {};
  const hyperQualityDims: any[] = qualityData?.hypergraph_quality || [];

  return (
    <div className="kb-panel">
      <header className="kb-panel-header">
        <div className="kb-panel-title">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/><path d="M12 8v3M8.5 17L10.5 11M15.5 17L13.5 11"/></svg>
          <span>知识图谱探索中心</span>
        </div>
        <nav className="kb-panel-tabs">
          {TAB_META.map(t => (
            <button key={t.id} className={`kb-tab-btn${tab === t.id ? " active" : ""}`} onClick={() => setTab(t.id)}>
              <span className="kb-tab-icon">{t.icon}</span>
              <span className="kb-tab-text">
                <span className="kb-tab-label">{t.label}</span>
                <span className="kb-tab-sub">{t.sub}</span>
              </span>
            </button>
          ))}
        </nav>
        <button className="kb-panel-close" onClick={onClose} title="关闭">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
        </button>
      </header>

      <div className="kb-panel-body">

        {/* ═══════════════════ Quality Tab ═══════════════════ */}
        {tab === "quality" && (
          <div className="kb-tab-content kb-quality">
            {qualityLoading ? <div className="kb-loading">加载质量报告中...</div>
             : qualityError ? <ErrorBox msg={qualityError} onRetry={() => { setQualityError(""); loadQuality(); }} />
             : qualityData ? (
              <div className="kb-quality-layout">

                {/* ── Database Overview ── */}
                <section className="kb-section">
                  <h2 className="kb-section-title">图数据库概况</h2>
                  <p className="kb-section-desc">以下统计数据直接来自 Neo4j 图数据库，反映知识图谱的真实规模。</p>
                  <div className="kb-stats-grid">
                    <div className="kb-stat-card">
                      <div className="kb-stat-num">{(neoStats.kg_nodes || neoStats.total_nodes || 0).toLocaleString()}</div>
                      <div className="kb-stat-label">KG 节点数</div>
                    </div>
                    <div className="kb-stat-card">
                      <div className="kb-stat-num">{(neoStats.kg_relationships || neoStats.total_relationships || 0).toLocaleString()}</div>
                      <div className="kb-stat-label">KG 关系数</div>
                    </div>
                    <div className="kb-stat-card">
                      <div className="kb-stat-num">{Object.keys(nodeLabels).length}</div>
                      <div className="kb-stat-label">节点类型</div>
                    </div>
                    <div className="kb-stat-card">
                      <div className="kb-stat-num">{Object.keys(relTypes).length}</div>
                      <div className="kb-stat-label">关系类型</div>
                    </div>
                    <div className="kb-stat-card">
                      <div className="kb-stat-num">{qualityData.total_cases || 0}</div>
                      <div className="kb-stat-label">分析案例</div>
                    </div>
                  </div>
                  {/* Node type breakdown */}
                  <div className="kb-breakdown">
                    <h4>节点类型分布</h4>
                    <div className="kb-breakdown-grid">
                      {Object.entries(nodeLabels).slice(0, 14).map(([label, count]: [string, any]) => (
                        <div key={label} className="kb-breakdown-item">
                          <span className="kb-breakdown-label">{label}</span>
                          <span className="kb-breakdown-count">{count}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </section>

                {/* ── Overall Score + Radar ── */}
                <section className="kb-section">
                  <h2 className="kb-section-title">知识图谱质量评估</h2>
                  <p className="kb-section-desc">基于 {qualityData.total_cases || 0} 个案例的结构化数据，从 7 个维度评估知识抽取的质量和完整性。</p>
                  <div className="kb-quality-radar-section">
                    <div className="kb-quality-overall">
                      <div className={`kb-grade-ring grade-${gradeClass(qualityData.overall_grade)}`}>
                        <span className="kb-grade-letter">{qualityData.overall_grade || "?"}</span>
                      </div>
                      <div className="kb-quality-score-info">
                        <div className="kb-quality-score-num">{qualityData.overall_score ?? 0}</div>
                        <div className="kb-quality-score-label">综合评分 / 100</div>
                        <div className="kb-quality-meta">{qualityData.total_cases || 0} 个案例 &middot; {(qualityData.dimensions || []).length + hyperQualityDims.length} 个评估维度</div>
                      </div>
                    </div>
                    <QualityRadar dimensions={[...(qualityData.dimensions || []), ...hyperQualityDims]} />
                  </div>
                </section>

                {/* ── KG Dimensions ── */}
                <section className="kb-section">
                  <h2 className="kb-section-title">KG 质量维度详情</h2>
                  <div className="kb-quality-dims">
                    {(qualityData.dimensions || []).map((dim: any) => (
                      <DimensionCard key={dim.id} dim={dim} expanded={expandedDim === dim.id} onToggle={() => setExpandedDim(expandedDim === dim.id ? null : dim.id)} qualityData={qualityData} />
                    ))}
                  </div>
                </section>

                {/* ── Hypergraph Quality ── */}
                {hyperQualityDims.length > 0 && (
                  <section className="kb-section">
                    <h2 className="kb-section-title">超图质量评估</h2>
                    <p className="kb-section-desc">超图（Hypergraph）是在传统知识图谱之上构建的高阶结构，用于捕获多元素之间的N元关系和跨段落语义模式。</p>
                    <div className="kb-quality-dims">
                      {hyperQualityDims.map((dim: any) => (
                        <DimensionCard key={dim.id} dim={dim} expanded={expandedDim === dim.id} onToggle={() => setExpandedDim(expandedDim === dim.id ? null : dim.id)} qualityData={qualityData} />
                      ))}
                    </div>
                  </section>
                )}

                {/* ── Coverage Matrix ── */}
                {qualityData?.coverage_matrix && (
                  <section className="kb-section">
                    <h2 className="kb-section-title">覆盖矩阵：45 家族 &times; 27 风险规则</h2>
                    <p className="kb-section-desc">展示每个超边家族与风险规则 (H1-H27) 的设计关联。矩阵越密说明家族体系对风险规则的覆盖越全面。</p>
                    <CoverageMatrix data={qualityData.coverage_matrix} />
                  </section>
                )}
              </div>
            ) : <div className="kb-loading">暂无质量报告</div>}
          </div>
        )}

        {/* ═══════════════════ KG Tab ═══════════════════ */}
        {tab === "kg" && (
          <div className="kb-tab-content kb-kg">
            {kgViewMode === "overview" ? (
              <>
                {/* ── Galaxy sidebar ── */}
                <aside className="kb-sidebar">
                  <h3>知识图谱全景</h3>
                  <p className="kb-sidebar-desc">
                    {kgFullData ? `${kgFullData.stats?.total_nodes ?? 0} 个真实节点按 ${(kgFullData.subgraphs || []).length} 个子图维度分布。每个扇区内的小圆点就是一个真实的实体节点。` : "加载中..."}
                  </p>
                  {(kgFullData?.subgraphs || []).map((sg: any) => (
                    <button key={sg.id} className="kb-sg-item" onClick={() => { setKgViewMode("detail"); loadKGDetail(sg.id); }}>
                      <span className="kb-sg-dot" style={{ background: sg.color || "#888" }} />
                      <span>{SG_LABELS[sg.id] || sg.label || sg.id}</span>
                      <span className="kb-sg-count">{sg.node_count ?? 0}</span>
                    </button>
                  ))}
                  {kgFullData && (
                    <div className="kb-sg-stats">
                      <div>节点 <strong>{kgFullData.stats?.total_nodes ?? 0}</strong></div>
                      <div>边 <strong>{kgFullData.stats?.total_links ?? 0}</strong></div>
                      <div>项目 <strong>{kgFullData.stats?.total_projects ?? 0}</strong></div>
                    </div>
                  )}
                  <div className="kb-rag-card">
                    <h3>子图 RAG 检索架构</h3>
                    <p className="kb-rag-desc">
                      知识图谱按维度划分为 <strong>{(kgFullData?.subgraphs || []).length}</strong> 个逻辑子图。
                      每个扇区就是一个子图，密度代表节点数量。点击侧栏子图可钻入查看详情。
                    </p>
                    <div className="kb-rag-flow">
                      {["用户提问", "意图识别", "锁定子图", "子图检索", "生成回答"].map((step, i) => (
                        <React.Fragment key={i}>
                          {i > 0 && <div className="kb-rag-arrow"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#64748b" strokeWidth="2"><path d="M12 5v14M19 12l-7 7-7-7"/></svg></div>}
                          <div className={`kb-rag-step${i === 2 ? " kb-rag-step-highlight" : ""}`}>
                            <div className="kb-rag-step-num">{i + 1}</div>
                            <div className="kb-rag-step-text">{step}</div>
                          </div>
                        </React.Fragment>
                      ))}
                    </div>
                  </div>
                </aside>
                {/* ── Galaxy graph (all real nodes) ── */}
                <div className="kb-graph-area">
                  {!kgFullLoading && !kgFullError && galaxyGraphData.nodes.length > 0 && (
                    <div className="kb-graph-hint">{galaxyGraphData.nodes.length} 个真实节点 — 每个小圆点是一个知识实体，按子图维度分布在不同扇区</div>
                  )}
                  {kgFullLoading ? <div className="kb-loading">加载知识图谱全部节点中...</div>
                   : kgFullError ? <ErrorBox msg={kgFullError} onRetry={() => { setKgFullError(""); loadKGFull(); }} />
                   : galaxyGraphData.nodes.length > 0 ? (
                    <ForceGraph2D ref={kgGalaxyRef} graphData={galaxyGraphData}
                      nodeColor={(n: any) => {
                        return n.color || "#94a3b8";
                      }}
                      nodeVal={() => 0.6}
                      nodeLabel={(n: any) => {
                        let label = n.name || "";
                        if (n.type === "entrepreneur_domain") label += " [创业领域]";
                        else if (n.type === "competition") label += " [赛事]";
                        else if (n.type === "entrepreneurship") label += " [创业]";
                        else if (n.type === "innovation") label += " [创新]";
                        else label += n.type ? ` [${n.type}]` : "";
                        if (n.category) label += ` · ${n.category}`;
                        return label;
                      }}
                      linkColor={() => "rgba(148,163,184,0.04)"}
                      linkWidth={0.3}
                      onRenderFramePost={renderGalaxySectors}
                      backgroundColor="transparent"
                      enableNodeDrag={false}
                      width={typeof window !== "undefined" ? Math.max(400, window.innerWidth - 320) : 800}
                      height={typeof window !== "undefined" ? Math.max(300, window.innerHeight - 150) : 600}
                      cooldownTicks={0}
                    />
                  ) : <div className="kb-loading">暂无数据</div>}
                </div>
              </>
            ) : (
              <>
                {/* ── Detail sidebar ── */}
                <aside className="kb-sidebar">
                  <button className="kb-back-btn" onClick={() => { setKgViewMode("overview"); setKgDetailData(null); setKgDetailSelectedNode(null); setKgDetailSearch(""); setKgDetailHighlight(""); }}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
                    返回子图总览
                  </button>
                  {kgDetailData && (
                    <>
                      <div className="kb-detail-sg-header" style={{ borderLeftColor: kgDetailData.color || "#888" }}>
                        <h3>{kgDetailData.sg_label}</h3>
                        <div className="kb-detail-sg-meta">
                          {kgDetailData.stats?.entity_count ?? 0} 个 {kgDetailData.node_label} 节点 &middot; {kgDetailData.stats?.project_count ?? 0} 个项目
                        </div>
                      </div>
                      {/* Search inside detail */}
                      <div className="kb-sidebar-search">
                        <input type="text" className="kb-search-input" placeholder={`搜索 ${kgDetailData.sg_label} 节点...`}
                          value={kgDetailSearch} onChange={e => { setKgDetailSearch(e.target.value); setKgDetailHighlight(e.target.value); }} />
                      </div>
                      {/* Category distribution */}
                      {kgDetailData.category_dist?.length > 0 && (
                        <div className="kb-detail-dist">
                          <h4>行业分布</h4>
                          {kgDetailData.category_dist.map((c: any, i: number) => (
                            <div key={i} className="kb-dist-bar-row">
                              <span className="kb-dist-label">{c.cat}</span>
                              <div className="kb-dist-bar">
                                <div className="kb-dist-bar-fill" style={{
                                  width: `${Math.round((c.count / (kgDetailData.category_dist[0]?.count || 1)) * 100)}%`,
                                  backgroundColor: kgDetailData.color || "#3b82f6",
                                }} />
                              </div>
                              <span className="kb-dist-count">{c.count}</span>
                            </div>
                          ))}
                        </div>
                      )}
                      {/* Top nodes */}
                      {kgDetailData.top_nodes?.length > 0 && (
                        <div className="kb-detail-top">
                          <h4>高频节点 Top-{Math.min(10, kgDetailData.top_nodes.length)}</h4>
                          {kgDetailData.top_nodes.slice(0, 10).map((n: any, i: number) => (
                            <div key={i} className="kb-top-node-item" onClick={() => {
                              const found = kgDetailData.graph?.nodes?.find((nd: any) => nd.name === n.name && nd.type !== "Project");
                              if (found) { setKgDetailSelectedNode(found); if (kgDetailRef.current && found.x !== undefined) { kgDetailRef.current.centerAt(found.x, found.y, 400); kgDetailRef.current.zoom(2.5, 400); } }
                            }}>
                              <span className="kb-top-rank">{i + 1}</span>
                              <span className="kb-top-name">{n.name}</span>
                              <span className="kb-top-freq">{n.freq} 个项目</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                {/* 图例/说明区分创业领域/创业/创新/赛事节点 */}
                <div className="kb-legend-section">
                  <h4>节点类型图例</h4>
                  <div className="kb-legend-grid">
                    <div className="kb-legend-item"><span className="kb-legend-dot" style={{ background: "#fb923c" }} />创业领域</div>
                    <div className="kb-legend-item"><span className="kb-legend-dot" style={{ background: "#fb923c" }} />创业案例</div>
                    <div className="kb-legend-item"><span className="kb-legend-dot" style={{ background: "#a78bfa" }} />创新案例</div>
                    <div className="kb-legend-item"><span className="kb-legend-dot" style={{ background: "#f472b6" }} />赛事类型</div>
                  </div>
                  <div className="kb-legend-tip">创业领域/创业/创新/赛事节点已单独分类和配色，悬停/点击节点可查看详细类型说明。</div>
                </div>
                </aside>
                {/* ── Detail graph ── */}
                <div className="kb-graph-area">
                  {!kgDetailLoading && !kgDetailError && kgDetailData && (
                    <div className="kb-graph-hint">{kgDetailData.sg_label} 子图 — 彩色节点为 {kgDetailData.node_label}，白色节点为关联项目</div>
                  )}
                  {kgDetailLoading ? <div className="kb-loading">加载子图详情中...</div>
                   : kgDetailError ? <ErrorBox msg={kgDetailError} onRetry={() => { setKgDetailError(""); loadKGDetail(kgDetailSgId); }} />
                   : kgDetailFiltered.nodes?.length > 0 ? (
                    <ForceGraph2D ref={kgDetailRef} graphData={{ nodes: kgDetailFiltered.nodes, links: kgDetailFiltered.links }}
                      nodeLabel={(n: any) => `${n.name || ""}\n[${n.type || ""}]${n.category ? " · " + n.category : ""}`}
                      nodeColor={(n: any) => {
                        if (kgDetailSelectedNode && n.id === kgDetailSelectedNode.id) return "#fbbf24";
                        if ((kgDetailFiltered as any).highlightIds?.size && !(kgDetailFiltered as any).highlightIds.has(n.id)) return "rgba(255,255,255,0.08)";
                        
                        return n.color || "#94a3b8";
                      }}
                      nodeVal={(n: any) => n.size || 4}
                      linkColor={() => "rgba(148,163,184,0.15)"} linkWidth={0.5}
                      onNodeClick={(n: any) => setKgDetailSelectedNode(n)}
                      backgroundColor="transparent"
                      width={typeof window !== "undefined" ? Math.max(400, window.innerWidth - (kgDetailSelectedNode ? 600 : 320)) : 800}
                      height={typeof window !== "undefined" ? Math.max(300, window.innerHeight - 150) : 600}
                      cooldownTicks={150}
                      d3AlphaDecay={0.02}
                      d3VelocityDecay={0.3}
                    />
                  ) : <div className="kb-loading">暂无子图数据</div>}
                </div>
                {/* ── Detail node info ── */}
                {kgDetailSelectedNode && (
                  <aside className="kb-detail-panel">
                    <div className="kb-detail-header">
                      <h4>节点详情</h4>
                      <button onClick={() => setKgDetailSelectedNode(null)}>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
                      </button>
                    </div>
                    <div className="kb-detail-body">
                      <div className="kb-detail-row"><label>名称</label><span>{kgDetailSelectedNode.name || ""}</span></div>
                      <div className="kb-detail-row"><label>类型</label><span className="kb-type-badge" style={{ borderColor: kgDetailSelectedNode.color || "#888" }}>{kgDetailSelectedNode.type || ""}</span></div>
                      {kgDetailSelectedNode.category && <div className="kb-detail-row"><label>行业</label><span>{kgDetailSelectedNode.category}</span></div>}
                      <div className="kb-detail-row"><label>关联</label><span>{(kgDetailData?.graph?.links || []).filter((l: any) => { const s = typeof l.source === "string" ? l.source : l.source?.id; const t = typeof l.target === "string" ? l.target : l.target?.id; return s === kgDetailSelectedNode.id || t === kgDetailSelectedNode.id; }).length} 条边</span></div>
                    </div>
                  </aside>
                )}
              </>
            )}
          </div>
        )}

        {/* ═══════════════════ Hyper Tab ═══════════════════ */}
        {tab === "hyper" && (
          <div className="kb-tab-content kb-hyper">
            <aside className="kb-sidebar">
              {/* ─── Hero: What is this? ─── */}
              <div className="hg-hero">
                <div className="hg-hero-badge">Hypergraph</div>
                <h3 className="hg-hero-title">教学超图</h3>
                <p className="hg-hero-desc">
                  超图是在知识图谱之上构建的<strong>高阶语义网络</strong>。每条超边同时连接多个维度的节点，
                  揭示学生项目中隐藏的<strong>跨维度关联模式</strong>——例如把分散在不同章节的痛点、方案和商业模式
                  聚合为一个完整的"价值闭环"或"风险信号"。
                </p>
              </div>

              {/* ─── Stats Dashboard ─── */}
              {hyperData?.stats && (
                <div className="hg-stats-grid">
                  <div className="hg-stat-card hg-stat-edges">
                    <div className="hg-stat-value">{hyperData.stats.total_hyperedges ?? 0}</div>
                    <div className="hg-stat-label">超边</div>
                  </div>
                  <div className="hg-stat-card hg-stat-nodes">
                    <div className="hg-stat-value">{hyperData.stats.total_hypernodes ?? 0}</div>
                    <div className="hg-stat-label">超节点</div>
                  </div>
                  <div className="hg-stat-card hg-stat-rules">
                    <div className="hg-stat-value">{hyperData.stats.total_risk_rules ?? 0}</div>
                    <div className="hg-stat-label">风险规则</div>
                  </div>
                  <div className="hg-stat-card hg-stat-families">
                    <div className="hg-stat-value">{hyperData.stats.total_families ?? 45}</div>
                    <div className="hg-stat-label">超边家族</div>
                  </div>
                </div>
              )}

              {/* ─── Insight Cards ─── */}
              <div className="hg-insight-section">
                <h3>核心洞察</h3>
                <div className="hg-insight-card">
                  <div className="hg-insight-icon" style={{ background: "rgba(251,191,36,0.12)", color: "#fbbf24" }}>⬡</div>
                  <div>
                    <div className="hg-insight-title">N元关系发现</div>
                    <div className="hg-insight-text">每条超边连接 3-8 个知识节点，捕捉传统三元组无法表达的多维语义模式</div>
                  </div>
                </div>
                <div className="hg-insight-card">
                  <div className="hg-insight-icon" style={{ background: "rgba(239,68,68,0.12)", color: "#ef4444" }}>⚡</div>
                  <div>
                    <div className="hg-insight-title">风险模式聚合</div>
                    <div className="hg-insight-text">自动将散落在不同段落的薄弱证据聚合为可识别的风险信号，触发对应的诊断规则</div>
                  </div>
                </div>
                <div className="hg-insight-card">
                  <div className="hg-insight-icon" style={{ background: "rgba(34,211,238,0.12)", color: "#22d3ee" }}>◈</div>
                  <div>
                    <div className="hg-insight-title">教学干预指引</div>
                    <div className="hg-insight-text">教师可以通过超边快速定位"哪些分散的证据共同指向某个薄弱环节"，精准制定反馈策略</div>
                  </div>
                </div>
              </div>

              {/* ─── Legend ─── */}
              <div className="hg-legend">
                <h3>图例</h3>
                <div className="hg-legend-grid">
                  <div className="hg-legend-item"><span className="hg-legend-shape hg-shape-rect" style={{ background: "#f59e0b" }} /><span>超边（方块）</span></div>
                  <div className="hg-legend-item"><span className="hg-legend-shape hg-shape-circle" style={{ background: "#38bdf8" }} /><span>超节点（语义片段）</span></div>
                  <div className="hg-legend-item"><span className="hg-legend-shape hg-shape-circle" style={{ background: "#ef4444" }} /><span>风险规则 (H1-H27)</span></div>
                  <div className="hg-legend-item"><span className="hg-legend-shape hg-shape-circle" style={{ background: "#22c55e" }} /><span>评审量表项 (9维)</span></div>
                </div>
                <div className="hg-legend-tip">悬停方块超边 → 高亮所有连接节点并在下方查看详情</div>
              </div>

              {/* ─── Family Filter + Breakdown ─── */}
              {hyperData?.stats?.family_counts && (
                <div className="hg-families-section">
                  <h3>
                    超边家族筛选
                    <span className="hg-families-count">{Object.keys(hyperData.stats.family_counts).length} 个家族</span>
                  </h3>
                  {hyperSelectedFamilies.size > 0 && (
                    <div className="hg-filter-bar">
                      <span className="hg-filter-status">
                        已选 <strong>{hyperSelectedFamilies.size}</strong> 个家族
                        {hyperFilteredStats && <> · {hyperFilteredStats.edges} 超边 · {hyperFilteredStats.hnodes} 节点</>}
                      </span>
                      <button className="hg-filter-clear" onClick={clearHyperFamilyFilter}>清除</button>
                    </div>
                  )}
                  <div className="hg-families-list">
                    {Object.entries(hyperData.stats.family_counts as Record<string, number>)
                      .sort(([, a], [, b]) => (b as number) - (a as number))
                      .map(([family, count]) => {
                        const maxCount = Math.max(...Object.values(hyperData.stats.family_counts as Record<string, number>).map(Number));
                        const pct = Math.round(((count as number) / maxCount) * 100);
                        const label = (family as string).replace(/_Edge$/, "").replace(/_/g, " ");
                        const isActive = hyperSelectedFamilies.has(family);
                        const isDimmed = hyperSelectedFamilies.size > 0 && !isActive;
                        return (
                          <div
                            key={family}
                            id={`hyper-family-${family}`}
                            className={`hg-family-row ${isActive ? "hg-family-active" : ""} ${isDimmed ? "hg-family-dimmed" : ""}`}
                            onClick={() => toggleHyperFamily(family)}
                          >
                            <div className="hg-family-info">
                              <span className="hg-family-check">{isActive ? "✓" : ""}</span>
                              <span className="hg-family-name">{label}</span>
                              <span className="hg-family-count">{count as number}</span>
                            </div>
                            <div className="hg-family-bar"><div className="hg-family-bar-fill" style={{ width: `${pct}%`, opacity: isDimmed ? 0.3 : 1 }} /></div>
                          </div>
                        );
                      })}
                  </div>
                </div>
              )}

              {/* ─── Hover Detail (dynamic) ─── */}
              {hoveredHEInfo && (
                <div className="hg-hover-detail">
                  <div className="hg-hover-header">
                    <div className="hg-hover-badge" style={{ background: hoveredHEInfo.color || "#f59e0b" }} />
                    <div>
                      <div className="hg-hover-title">{hoveredHEInfo.family_label || hoveredHEInfo.name || hoveredHEInfo.id}</div>
                      <div className="hg-hover-subtitle">{hoveredHEInfo.family || hoveredHEInfo.type || ""}</div>
                    </div>
                  </div>
                  <div className="hg-hover-meta">
                    {hoveredHEInfo.support && <span className="hg-hover-tag">支撑度 {hoveredHEInfo.support}</span>}
                    {hoveredHEInfo.severity && <span className="hg-hover-tag">{hoveredHEInfo.severity}</span>}
                    {hoveredHEInfo.category && <span className="hg-hover-tag">{hoveredHEInfo.category}</span>}
                    <span className="hg-hover-tag">成员 {hoveredHEInfo.totalMembers}</span>
                  </div>
                  {hoveredHEInfo.hyperNodes.length > 0 && (
                    <div className="hg-hover-group">
                      <div className="hg-hover-group-label">语义片段 ({hoveredHEInfo.hyperNodes.length})</div>
                      {hoveredHEInfo.hyperNodes.slice(0, 5).map((m: any) => (
                        <div key={m.id} className="hg-hover-node">{(m.name || m.id || "").slice(0, 60)}</div>
                      ))}
                      {hoveredHEInfo.hyperNodes.length > 5 && <div className="hg-hover-node hg-hover-more">...还有 {hoveredHEInfo.hyperNodes.length - 5} 个</div>}
                    </div>
                  )}
                  {hoveredHEInfo.riskRules.length > 0 && (
                    <div className="hg-hover-group">
                      <div className="hg-hover-group-label" style={{ color: "#ef4444" }}>触发规则 ({hoveredHEInfo.riskRules.length})</div>
                      {hoveredHEInfo.riskRules.map((r: any) => <div key={r.id} className="hg-hover-node" style={{ borderColor: "rgba(239,68,68,0.15)" }}>{r.name || r.id}</div>)}
                    </div>
                  )}
                  {hoveredHEInfo.rubricItems.length > 0 && (
                    <div className="hg-hover-group">
                      <div className="hg-hover-group-label" style={{ color: "#22c55e" }}>对齐评审 ({hoveredHEInfo.rubricItems.length})</div>
                      {hoveredHEInfo.rubricItems.map((r: any) => <div key={r.id} className="hg-hover-node" style={{ borderColor: "rgba(34,197,94,0.15)" }}>{r.name || r.id}</div>)}
                    </div>
                  )}
                </div>
              )}
            </aside>
            <div className="kb-graph-area">
              {!hyperLoading && !hyperError && (hyperData?.graph?.nodes?.length || 0) > 0 && (
                <div className="kb-graph-hint">
                  {clickedHE
                    ? `已锁定超边 — 左侧已定位到对应家族卡片，点击空白处取消`
                    : hyperSelectedFamilies.size > 0
                      ? `筛选中：${hyperSelectedFamilies.size} 个家族 · ${hyperFilteredStats?.edges ?? 0} 超边 · ${hyperFilteredStats?.hnodes ?? 0} 节点`
                      : "点击方块锁定超边并定位左侧卡片 — 悬停查看详情 — 左侧家族可筛选"}
                </div>
              )}
              {hyperLoading ? <div className="kb-loading">加载超图中...</div>
               : hyperError ? <ErrorBox msg={hyperError} onRetry={() => { setHyperError(""); loadHyper(); }} />
               : (hyperData?.graph?.nodes?.length || 0) > 0 ? (
                <ForceGraph2D graphData={filteredHyperGraph}
                  nodeLabel={(n: any) => `${n.name || ""}\n[${n.type || ""}]`}
                  nodeColor={hyperNodeColor} nodeVal={(n: any) => n.size || 3}
                  nodeCanvasObjectMode={() => "replace"}
                  nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
                    const size = (node.size || 3) / globalScale * 4;
                    const color = hyperNodeColor(node);
                    const isActive = node.id === _activeHE;
                    if (node.type === "Hyperedge") {
                      ctx.fillStyle = color; ctx.fillRect(node.x - size, node.y - size, size * 2, size * 2);
                      ctx.strokeStyle = isActive ? "rgba(251,191,36,0.8)" : "rgba(255,255,255,0.3)";
                      ctx.lineWidth = isActive ? 2 : 0.5;
                      ctx.strokeRect(node.x - size, node.y - size, size * 2, size * 2);
                    } else {
                      ctx.beginPath(); ctx.arc(node.x, node.y, size * 0.7, 0, 2 * Math.PI); ctx.fillStyle = color; ctx.fill();
                      if (hoveredHEMembers.has(node.id)) {
                        ctx.strokeStyle = "rgba(251,191,36,0.6)"; ctx.lineWidth = 1.5; ctx.stroke();
                      }
                    }
                  }}
                  onNodeHover={(n: any) => setHoveredHE(n?.type === "Hyperedge" ? n.id : null)}
                  onNodeClick={(n: any) => {
                    if (n?.type === "Hyperedge") {
                      setClickedHE(n.id);
                      if (n.family) {
                        const el = document.getElementById(`hyper-family-${n.family}`);
                        if (el) {
                          el.scrollIntoView({ behavior: "smooth", block: "center" });
                          el.classList.add("hg-family-flash");
                          setTimeout(() => el.classList.remove("hg-family-flash"), 1500);
                        }
                      }
                    }
                  }}
                  onBackgroundClick={() => { setClickedHE(null); }}
                  linkColor={hyperLinkColor} linkWidth={(l: any) => {
                    if (!_activeHE) return 0.3;
                    const s = typeof l.source === "string" ? l.source : l.source?.id;
                    const t = typeof l.target === "string" ? l.target : l.target?.id;
                    return (s === _activeHE || t === _activeHE) ? 1.5 : 0.1;
                  }}
                  backgroundColor="transparent"
                  width={typeof window !== "undefined" ? Math.max(400, window.innerWidth - 320) : 800}
                  height={typeof window !== "undefined" ? Math.max(300, window.innerHeight - 150) : 600}
                  cooldownTicks={80}
                />
              ) : <div className="kb-loading">暂无超图数据</div>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════
   Sub-components
   ════════════════════════════════════════════════════════════ */

function DimensionCard({ dim, expanded, onToggle, qualityData }: { dim: any; expanded: boolean; onToggle: () => void; qualityData?: any }) {
  return (
    <div className={`kb-dim-card${expanded ? " expanded" : ""}`}>
      <button className="kb-dim-card-header" onClick={onToggle}>
        <span className={`kb-dim-grade grade-${gradeClass(dim.grade)}`}>{dim.grade || "?"}</span>
        <div className="kb-dim-info">
          <div className="kb-dim-title">{dim.label || ""}</div>
          <div className="kb-dim-subtitle">{dim.label_en || ""}</div>
        </div>
        <div className="kb-dim-bar-wrap"><div className="kb-dim-bar" style={{ width: `${dim.score ?? 0}%` }} /></div>
        <span className="kb-dim-score">{dim.score ?? 0}</span>
        <svg className="kb-dim-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9l6 6 6-6"/></svg>
      </button>
      {expanded && (
        <div className="kb-dim-detail">
          {dim.description && <p className="kb-dim-description">{dim.description}</p>}
          <p className="kb-dim-summary">{dim.summary || ""}</p>
          <DimensionDetailChart dim={dim} qualityData={qualityData} />
        </div>
      )}
    </div>
  );
}

function QualityRadar({ dimensions }: { dimensions: any[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !dimensions || !dimensions.length) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const W = 340, H = 340;
    canvas.width = W * 2; canvas.height = H * 2; ctx.scale(2, 2);
    const cx = W / 2, cy = H / 2, R = 130, n = dimensions.length, step = (2 * Math.PI) / n;
    ctx.clearRect(0, 0, W, H);
    for (let ring = 1; ring <= 4; ring++) {
      const rr = (R * ring) / 4;
      ctx.beginPath();
      for (let i = 0; i <= n; i++) { const a = i * step - Math.PI / 2; const x = cx + rr * Math.cos(a), y = cy + rr * Math.sin(a); i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y); }
      ctx.closePath(); ctx.strokeStyle = "rgba(148,163,184,0.12)"; ctx.lineWidth = 1; ctx.stroke();
    }
    for (let i = 0; i < n; i++) { const a = i * step - Math.PI / 2; ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx + R * Math.cos(a), cy + R * Math.sin(a)); ctx.strokeStyle = "rgba(148,163,184,0.12)"; ctx.stroke(); }
    ctx.beginPath();
    for (let i = 0; i <= n; i++) { const idx = i % n; const a = idx * step - Math.PI / 2; const v = (dimensions[idx]?.score || 0) / 100; const x = cx + R * v * Math.cos(a), y = cy + R * v * Math.sin(a); i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y); }
    ctx.closePath(); ctx.fillStyle = "rgba(59,130,246,0.12)"; ctx.fill(); ctx.strokeStyle = "rgba(59,130,246,0.7)"; ctx.lineWidth = 2; ctx.stroke();
    for (let i = 0; i < n; i++) { const a = i * step - Math.PI / 2; const v = (dimensions[i]?.score || 0) / 100; const x = cx + R * v * Math.cos(a), y = cy + R * v * Math.sin(a); ctx.beginPath(); ctx.arc(x, y, 4, 0, 2 * Math.PI); ctx.fillStyle = "#3b82f6"; ctx.fill(); ctx.strokeStyle = "#0b1120"; ctx.lineWidth = 2; ctx.stroke(); }
    ctx.font = "11px system-ui, sans-serif"; ctx.fillStyle = "#94a3b8"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    for (let i = 0; i < n; i++) {
      const a = i * step - Math.PI / 2;
      const lx = cx + (R + 30) * Math.cos(a), ly = cy + (R + 30) * Math.sin(a);
      const label = (dimensions[i]?.label || "").slice(0, 6);
      ctx.fillText(label, lx, ly);
    }
  }, [dimensions]);
  return <canvas ref={canvasRef} className="kb-radar-canvas" style={{ width: 340, height: 340 }} />;
}

function DimensionDetailChart({ dim, qualityData }: { dim: any; qualityData?: any }) {
  const detail: any = dim?.detail || {};

  if (dim.id === "extraction_accuracy") {
    const samples = (detail.samples || []).slice(0, 5);
    return (
      <div className="kb-dim-chart">
        <div className="kb-dim-stat-row">
          <span>抽样数</span><strong>{detail.sample_size ?? 0}</strong>
          <span>检查项</span><strong>{detail.total_checks ?? 0}</strong>
          <span>通过</span><strong>{detail.passed_checks ?? 0}</strong>
        </div>
        <div className="kb-dim-table-wrap">
          <table className="kb-dim-table">
            <thead><tr><th>案例</th><th>字段</th><th>已填充</th><th>条目数</th><th>证据</th></tr></thead>
            <tbody>
              {samples.map((s: any) => (s.fields || []).map((f: any, j: number) => (
                <tr key={`${s.case_id}_${j}`}>
                  {j === 0 && <td rowSpan={(s.fields || []).length || 1}>{(s.project_name || s.case_id || "?").slice(0, 12)}</td>}
                  <td>{f.field}</td><td>{f.filled ? "Yes" : "No"}</td><td>{f.item_count ?? 0}</td><td>{f.has_evidence_hint ? "Yes" : "-"}</td>
                </tr>
              )))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }
  if (dim.id === "ontology_coverage") {
    return (
      <div className="kb-dim-chart">
        <div className="kb-dim-stat-row"><span>本体概念</span><strong>{detail.total_concepts ?? 0}</strong><span>已覆盖</span><strong>{detail.covered_concepts ?? 0}</strong></div>
        <div className="kb-onto-grid">
          {(detail.heatmap || []).map((h: any) => (
            <div key={h.concept_id} className={`kb-onto-cell${h.covered ? " covered" : ""}`} title={`${h.label}: ${h.instance_count} 个实例`}>
              <div className="kb-onto-label">{h.label}</div><div className="kb-onto-count">{h.instance_count ?? 0}</div>
            </div>
          ))}
        </div>
      </div>
    );
  }
  if (dim.id === "traceability") {
    const hist = detail.histogram || [];
    const maxC = Math.max(1, ...hist.map((h: any) => h.cases || 0));
    return (
      <div className="kb-dim-chart">
        <div className="kb-dim-stat-row"><span>有证据案例</span><strong>{detail.cases_with_evidence ?? 0}/{detail.total_cases ?? 0}</strong><span>引用非空率</span><strong>{detail.quote_rate ?? 0}%</strong><span>平均证据</span><strong>{detail.avg_evidence_per_case ?? 0}</strong></div>
        <div className="kb-histogram">
          {hist.map((h: any) => <div key={h.evidence_count} className="kb-hist-bar-wrap"><div className="kb-hist-bar" style={{ height: `${((h.cases || 0) / maxC) * 100}%` }} /><div className="kb-hist-label">{h.evidence_count}</div><div className="kb-hist-val">{h.cases}</div></div>)}
        </div>
        <div className="kb-hist-axis-label">每案例证据条数</div>
      </div>
    );
  }
  if (dim.id === "connectivity") {
    return (
      <div className="kb-dim-chart">
        <div className="kb-dim-stat-row">
          <span>KG 节点</span><strong>{(detail.total_nodes ?? 0).toLocaleString()}</strong>
          <span>关系</span><strong>{(detail.total_edges ?? 0).toLocaleString()}</strong>
          <span>节点类型</span><strong>{detail.node_label_types ?? 0}</strong>
          <span>关系类型</span><strong>{detail.relationship_types ?? 0}</strong>
          <span>平均度</span><strong>{detail.avg_degree ?? 0}</strong>
          <span>密度</span><strong>{detail.density ?? 0}</strong>
        </div>
        <div className="kb-conn-grid">
          {Object.entries(detail.dimension_stats || {}).map(([k, v]: [string, any]) => (
            <div key={k} className="kb-conn-cell">
              <div className="kb-conn-name">{k}</div>
              <div className="kb-conn-val">{v?.node_count ?? 0} 节点</div>
            </div>
          ))}
        </div>
        {detail.node_labels && (
          <div className="kb-breakdown" style={{ marginTop: 12 }}>
            <h4>节点类型分布 (Neo4j)</h4>
            <div className="kb-breakdown-grid">
              {Object.entries(detail.node_labels).slice(0, 16).map(([label, count]: [string, any]) => (
                <div key={label} className="kb-breakdown-item"><span className="kb-breakdown-label">{label}</span><span className="kb-breakdown-count">{count}</span></div>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }
  if (dim.id === "category_balance") {
    const dist = detail.distribution || [];
    const maxP = Math.max(1, ...dist.map((d: any) => d.percentage || 0));
    return (
      <div className="kb-dim-chart">
        <div className="kb-dim-stat-row"><span>类别数</span><strong>{detail.total_categories ?? 0}</strong><span>基尼系数</span><strong>{detail.gini_coefficient ?? 0}</strong><span>变异系数</span><strong>{detail.coefficient_of_variation ?? 0}</strong></div>
        <div className="kb-bar-chart">
          {dist.map((d: any) => <div key={d.category} className="kb-bar-row"><span className="kb-bar-label">{d.category}</span><div className="kb-bar-track"><div className="kb-bar-fill" style={{ width: `${((d.percentage || 0) / maxP) * 100}%` }} /></div><span className="kb-bar-val">{d.count} ({d.percentage}%)</span></div>)}
        </div>
      </div>
    );
  }
  if (dim.id === "rubric_coverage") {
    return (
      <div className="kb-dim-chart">
        <div className="kb-rubric-list">
          {(detail.heatmap || []).map((h: any) => (
            <div key={h.rubric_item} className="kb-rubric-row">
              <span className="kb-rubric-name">{h.rubric_item}</span>
              <div className="kb-rubric-bar-track"><div className="kb-rubric-bar-fill" style={{ width: `${h.coverage_rate ?? 0}%`, background: (h.coverage_rate || 0) >= 70 ? "#22c55e" : (h.coverage_rate || 0) >= 40 ? "#eab308" : "#ef4444" }} /></div>
              <span className="kb-rubric-rate">{h.coverage_rate ?? 0}%</span><span className="kb-rubric-score">avg {h.avg_score ?? 0}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }
  if (dim.id === "risk_rule_distribution") {
    const dist = detail.distribution || [];
    const maxH = Math.max(1, ...dist.map((d: any) => d.hit_count || 0));
    return (
      <div className="kb-dim-chart">
        <div className="kb-dim-stat-row">
          <span>规则数</span><strong>{detail.total_rules ?? 0}</strong><span>触发案例</span><strong>{detail.cases_with_rules ?? 0}</strong>
          {(detail.universal_rules || []).length > 0 && <><span>万能规则</span><strong className="kb-warn">{detail.universal_rules.join(", ")}</strong></>}
          {(detail.silent_rules || []).length > 0 && <><span>沉默规则</span><strong className="kb-warn">{detail.silent_rules.join(", ")}</strong></>}
        </div>
        <div className="kb-rule-bars">
          {dist.map((d: any) => <div key={d.rule_id} className="kb-rule-col"><div className="kb-rule-bar-outer"><div className="kb-rule-bar-inner" style={{ height: `${((d.hit_count || 0) / maxH) * 100}%` }} /></div><div className="kb-rule-id">{d.rule_id}</div><div className="kb-rule-count">{d.hit_count}</div></div>)}
        </div>
      </div>
    );
  }
  if (dim.id === "hypergraph_completeness") {
    const familyEvidence: any[] = qualityData?.family_evidence || [];
    const highValue = familyEvidence.filter((f: any) => f.is_high_value);
    const lowTrigger = familyEvidence.filter((f: any) => f.is_low_trigger);
    return (
      <div className="kb-dim-chart">
        <div className="kb-dim-stat-row">
          <span>超边</span><strong>{detail.total_hyperedges ?? 0}</strong>
          <span>超节点</span><strong>{detail.total_hypernodes ?? 0}</strong>
          <span>成员链接</span><strong>{detail.has_member_links ?? 0}</strong>
          <span>平均成员</span><strong>{detail.avg_members_per_edge ?? 0}</strong>
        </div>
        <div className="kb-dim-stat-row">
          <span>规则触发</span><strong>{detail.triggers_rule_links ?? 0}</strong>
          <span>评审对齐</span><strong>{detail.aligns_with_links ?? 0}</strong>
          <span>实现率</span><strong>{detail.realization_rate ?? 0}%</strong>
        </div>

        {familyEvidence.length > 0 && (
          <>
            <div className="fe-section-title">家族级实例化统计 <span className="fe-section-sub">按触发率排序</span></div>
            <div className="fe-legend-row">
              <span className="fe-legend-item fe-high">高价值家族 ({highValue.length})</span>
              <span className="fe-legend-item fe-low">低触发家族 ({lowTrigger.length})</span>
            </div>
            <div className="fe-table-wrap">
              <table className="fe-table">
                <thead>
                  <tr>
                    <th>家族</th>
                    <th>实际/目标</th>
                    <th>实现率</th>
                    <th>触发率</th>
                    <th>支撑度</th>
                    <th>关联规则</th>
                  </tr>
                </thead>
                <tbody>
                  {familyEvidence.map((f: any) => (
                    <tr key={f.family_id} className={f.is_high_value ? "fe-row-high" : f.is_low_trigger ? "fe-row-low" : ""}>
                      <td className="fe-fam-name">{f.family_label}</td>
                      <td><strong>{f.actual}</strong> / {f.target}</td>
                      <td>
                        <div className="fe-bar-wrap">
                          <div className="fe-bar-fill" style={{ width: `${Math.min(f.realization_pct, 100)}%`, background: f.realization_pct >= 90 ? "#22c55e" : f.realization_pct >= 60 ? "#eab308" : "#ef4444" }} />
                        </div>
                        <span className="fe-bar-label">{f.realization_pct}%</span>
                      </td>
                      <td className={f.is_high_value ? "fe-val-high" : f.is_low_trigger ? "fe-val-low" : ""}>{f.trigger_rate}%</td>
                      <td>{f.avg_support}</td>
                      <td className="fe-rules">{(f.rules || []).map((r: string) => <span key={r} className="fe-rule-tag">{r}</span>)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    );
  }
  if (dim.id === "template_rationale") {
    const groups = detail.groups || [];
    return (
      <div className="kb-dim-chart">
        <div className="kb-tmpl-overview">
          <span>{detail.total_families ?? 45} 个超边家族</span>
          <span>{detail.total_groups ?? 10} 个功能组</span>
          <span>风险对齐 {detail.rule_coverage_pct ?? 0}%</span>
          <span>评审对齐 {detail.rubric_coverage_pct ?? 0}%</span>
        </div>

        {/* ── Design Derivation Tree ── */}
        <div className="tmpl-tree">
          <div className="tmpl-tree-root">
            <div className="tmpl-tree-root-icon">&#9670;</div>
            <div className="tmpl-tree-root-text">
              <strong>创业项目评估体系</strong>
              <span>{detail.total_groups ?? 10} 功能组 &rarr; {detail.total_families ?? 45} 超边家族</span>
            </div>
          </div>
          <div className="tmpl-tree-connector" />
          <div className="tmpl-tree-groups">
            {groups.map((g: any, gi: number) => (
              <div key={g.group_id} className="tmpl-tree-group">
                <div className="tmpl-tree-group-head">
                  <span className="tmpl-tree-group-idx">{String(gi + 1).padStart(2, "0")}</span>
                  <span className="tmpl-tree-group-name">{g.group_name}</span>
                  <span className="tmpl-tree-group-badge">{g.family_count} 族 · {g.target_edges} 边</span>
                </div>
                <div className="tmpl-tree-group-purpose">{g.purpose}</div>
                <div className="tmpl-tree-families">
                  {(g.families || []).map((f: any) => (
                    <div key={f.id} className="tmpl-tree-family-card">
                      <div className="tmpl-tree-family-name">{f.label}</div>
                      <div className="tmpl-tree-family-meta">
                        <span className="tmpl-tree-family-target">目标 {f.target}</span>
                        {(f.rules || []).length > 0 && (
                          <div className="tmpl-tree-family-rules">
                            {(f.rules || []).map((r: string) => (
                              <span key={r} className="tmpl-tree-rule-tag">{r}</span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }
  return <pre className="kb-dim-json">{JSON.stringify(detail, null, 2)}</pre>;
}


/* ╔═══════════════════════════════════════════════════════════════╗
   ║  CoverageMatrix – 45 families × 27 rules heatmap            ║
   ╚═══════════════════════════════════════════════════════════════╝ */

const GROUP_COLORS: Record<string, string> = {
  value_narrative: "#3b82f6",
  user_market: "#22c55e",
  risk_evidence: "#ef4444",
  execution_team: "#f59e0b",
  compliance_ethics: "#a855f7",
  financial_structure: "#06b6d4",
  product_competition: "#ec4899",
  growth_scale: "#84cc16",
  ecosystem: "#f97316",
  social_esg: "#14b8a6",
};

function CoverageMatrix({ data }: { data: any }) {
  const rules: string[] = data?.rules || [];
  const matrixRows: any[] = data?.matrix || [];
  const rubricCov: any[] = data?.rubric_coverage || [];
  const ruleStats: any[] = data?.rule_stats || [];
  const summary = data?.summary || {};

  let currentGroup = "";
  return (
    <div className="cm-wrap">
      {/* Summary stats */}
      <div className="cm-summary">
        <div className="cm-stat"><div className="cm-stat-val">{summary.total_families}</div><div className="cm-stat-label">超边家族</div></div>
        <div className="cm-stat"><div className="cm-stat-val">{summary.total_rules}</div><div className="cm-stat-label">风险规则</div></div>
        <div className="cm-stat"><div className="cm-stat-val">{summary.rules_covered}/{summary.total_rules}</div><div className="cm-stat-label">规则已覆盖</div></div>
        <div className="cm-stat"><div className="cm-stat-val">{summary.matrix_density}%</div><div className="cm-stat-label">矩阵密度</div></div>
        <div className="cm-stat"><div className="cm-stat-val">{summary.rubrics_well_covered}/{summary.total_rubrics}</div><div className="cm-stat-label">评审全覆盖</div></div>
      </div>

      {/* Matrix */}
      <div className="cm-table-scroll">
        <table className="cm-table">
          <thead>
            <tr>
              <th className="cm-th-family">家族</th>
              {rules.map(r => <th key={r} className="cm-th-rule">{r}</th>)}
              <th className="cm-th-count">#</th>
            </tr>
          </thead>
          <tbody>
            {matrixRows.map((row: any) => {
              const showGroupHeader = row.group_id !== currentGroup;
              currentGroup = row.group_id;
              return (
                <React.Fragment key={row.family_id}>
                  {showGroupHeader && (
                    <tr className="cm-group-row">
                      <td colSpan={rules.length + 2} style={{ borderLeft: `3px solid ${GROUP_COLORS[row.group_id] || "#64748b"}` }}>
                        {row.group_name}
                      </td>
                    </tr>
                  )}
                  <tr>
                    <td className="cm-td-family" title={row.family_id}>{row.family_label}</td>
                    {rules.map(r => (
                      <td key={r} className={`cm-cell${row.rules?.[r] ? " cm-filled" : ""}`} style={row.rules?.[r] ? { background: GROUP_COLORS[row.group_id] || "#3b82f6" } : undefined} />
                    ))}
                    <td className="cm-td-count">{row.rule_count}</td>
                  </tr>
                </React.Fragment>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <td className="cm-td-family">规则覆盖家族数</td>
              {rules.map(r => {
                const st = ruleStats.find((s: any) => s.rule === r);
                return <td key={r} className="cm-td-foot">{st?.family_count ?? 0}</td>;
              })}
              <td />
            </tr>
          </tfoot>
        </table>
      </div>

      {/* Rubric coverage */}
      <div className="cm-rubric-section">
        <h3 className="cm-rubric-title">9 评审维度 &times; 家族覆盖</h3>
        <div className="cm-rubric-grid">
          {rubricCov.map((rc: any) => (
            <div key={rc.rubric} className="cm-rubric-card">
              <div className="cm-rubric-name">{rc.rubric}</div>
              <div className="cm-rubric-detail">
                <span className="cm-rubric-rules">{(rc.rules || []).join(", ")}</span>
                <span className="cm-rubric-fam-count">{rc.families_count} 个家族覆盖</span>
              </div>
              <div className="cm-rubric-bar-track">
                <div className="cm-rubric-bar-fill" style={{ width: `${Math.min(rc.families_count * 4, 100)}%` }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
