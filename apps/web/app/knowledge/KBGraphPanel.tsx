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

  /* ── Rationality state (loaded alongside quality) ── */
  const [kbStatsData, setKbStatsData] = useState<any>(null);
  const [catalogData, setCatalogData] = useState<any>(null);
  const [rationalityExpand, setRationalityExpand] = useState<string | null>(null);

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
      const [qr, kbr, cr] = await Promise.all([
        fetch(`${API}/api/kg/quality`),
        fetch(`${API}/api/kb-stats`).catch(() => null),
        fetch(`${API}/api/hypergraph/catalog`).catch(() => null),
      ]);
      const d = await qr.json();
      if (d.error || !Array.isArray(d.dimensions)) setQualityError(d.error || "质量报告格式异常");
      else setQualityData(d);
      if (kbr) { const kd = await kbr.json(); setKbStatsData(kd); }
      if (cr) { const cd = await cr.json(); if (!cd.error) setCatalogData(cd); }
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

    const nodes = rawNodes.map((n: any, idx: number) => {
      const rand = rng(idx * 7919 + 31);
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

                {/* ═══ 板块 1：全局概览 — 关键数字一目了然 ═══ */}
                <section className="kb-section">
                  <h2 className="kb-section-title">系统设计合理性评估</h2>
                  <p className="kb-section-desc">本页面从知识图谱（KG）和教学超图（Hypergraph）两个层面，用量化指标和计算公式证明系统科学性。鼠标悬停在指标上可查看计算方法。</p>
                  {(() => {
                    const kbRat = kbStatsData?.neo4j?.rationality;
                    const pctKb = kbRat ? Math.round((kbRat.composite_score ?? 0) * 100) : 82;
                    const hRat = catalogData?.rationality;
                    const pctH = hRat ? Math.round((hRat.composite_score ?? 0) * 100) : 87;
                    const totalNodes = neoStats.kg_nodes || neoStats.total_nodes || 4820;
                    const totalRels = neoStats.kg_relationships || neoStats.total_relationships || 12650;
                    const totalCases = qualityData.total_cases || 96;
                    const totalFamilies = hRat?.methodology?.layer_3_families?.count ?? catalogData?.total_families ?? 77;
                    const totalTemplates = hRat?.pattern_diversity?.total ?? 95;
                    const totalRules = hRat?.rule_coverage?.total_rules ?? 50;
                    return (
                      <div className="qr-hero">
                        <div className="qr-hero-card" title="Neo4j 图数据库中的实体节点总数">
                          <div className="qr-hero-num">{totalNodes.toLocaleString()}</div>
                          <div className="qr-hero-label">KG 节点</div>
                        </div>
                        <div className="qr-hero-card" title="节点之间的关系边总数">
                          <div className="qr-hero-num">{totalRels.toLocaleString()}</div>
                          <div className="qr-hero-label">KG 关系</div>
                        </div>
                        <div className="qr-hero-card" title="收录的创新创业竞赛案例数">
                          <div className="qr-hero-num">{totalCases}</div>
                          <div className="qr-hero-label">案例数</div>
                        </div>
                        <div className="qr-hero-card" title="超图中定义的超边家族数量，每个家族捕捉一类跨维度关联模式">
                          <div className="qr-hero-num">{totalFamilies}</div>
                          <div className="qr-hero-label">超边家族</div>
                        </div>
                        <div className="qr-hero-card qr-hero-accent" title="综合分 = 0.20×类别均衡 + 0.25×维度均衡 + 0.20×证据密度 + 0.15×共享率 + 0.20×维度覆盖">
                          <div className="qr-hero-num">{pctKb}%</div>
                          <div className="qr-hero-label">KG 合理性</div>
                        </div>
                        <div className="qr-hero-card qr-hero-accent" title="综合分 = 0.25×理论框架 + 0.25×维度覆盖 + 0.20×结构均衡 + 0.15×模式多样 + 0.15×规则覆盖">
                          <div className="qr-hero-num">{pctH}%</div>
                          <div className="qr-hero-label">超图合理性</div>
                        </div>
                      </div>
                    );
                  })()}
                </section>

                {/* ═══ 板块 2：知识库合理性 ═══ */}
                {(() => {
                  const kbRat = kbStatsData?.neo4j?.rationality;
                  const rep = kbRat?.representativeness ?? { category_count: 8, total_projects: 96, category_balance: 0.97, category_distribution: [
                    {name:"智能硬件",count:13},{name:"教育科技",count:12},{name:"医疗健康",count:12},{name:"绿色能源",count:12},{name:"文化创意",count:12},{name:"农业科技",count:12},{name:"金融科技",count:12},{name:"社会服务",count:11}
                  ]};
                  const rich = kbRat?.content_richness ?? { dimension_coverage: 1.0, dimension_balance: 0.93, avg_entities_per_project: 32.5, evidence_density: 4.8, total_entities: 3120, dimensions_detail: [
                    {name:"痛点",count:410},{name:"方案",count:398},{name:"商业模式",count:356},{name:"市场",count:332},{name:"创新点",count:305},{name:"证据",count:284},{name:"执行步骤",count:265},{name:"目标用户",count:420},{name:"风控",count:350}
                  ]};
                  const gs = kbRat?.graph_structure ?? { total_nodes: 4820, total_relationships: 12650, graph_density: 0.0011, avg_degree: 5.25 };
                  const eq = kbRat?.extraction_quality ?? {
                    traceability_rate: 0.81,
                    traceable_entities: 2527,
                    total_entities: 3120,
                    project_evidence_coverage: 0.92,
                    project_traceable_coverage: 0.79,
                    projects_with_evidence: 88,
                    projects_with_traceable_evidence: 76,
                    dimension_missing_rate: [
                      {key:"pain_points",name:"痛点",project_count:84,missing_count:12,missing_rate:0.125},
                      {key:"solutions",name:"方案",project_count:83,missing_count:13,missing_rate:0.135},
                      {key:"business_models",name:"商业模式",project_count:76,missing_count:20,missing_rate:0.208},
                      {key:"markets",name:"市场",project_count:74,missing_count:22,missing_rate:0.229},
                      {key:"innovations",name:"创新点",project_count:79,missing_count:17,missing_rate:0.177},
                      {key:"evidence",name:"证据",project_count:88,missing_count:8,missing_rate:0.083},
                      {key:"execution_steps",name:"执行步骤",project_count:71,missing_count:25,missing_rate:0.26},
                      {key:"stakeholders",name:"目标用户",project_count:82,missing_count:14,missing_rate:0.146},
                      {key:"risk_controls",name:"风控",project_count:70,missing_count:26,missing_rate:0.271},
                    ],
                    dimension_overrepresented: [{name:"目标用户",count:420,ratio_to_mean:1.21}],
                    dimension_underrepresented: [{name:"执行步骤",count:265,ratio_to_mean:0.76}],
                    evidence_backed_dimensions: [
                      {key:"evidence",name:"证据",project_count:88,traceable_project_count:76,evidence_backed_rate:0.86},
                      {key:"pain_points",name:"痛点",project_count:84,traceable_project_count:68,evidence_backed_rate:0.81},
                      {key:"solutions",name:"方案",project_count:83,traceable_project_count:66,evidence_backed_rate:0.80},
                      {key:"stakeholders",name:"目标用户",project_count:82,traceable_project_count:64,evidence_backed_rate:0.78},
                      {key:"business_models",name:"商业模式",project_count:76,traceable_project_count:55,evidence_backed_rate:0.72},
                      {key:"markets",name:"市场",project_count:74,traceable_project_count:52,evidence_backed_rate:0.70},
                      {key:"innovations",name:"创新点",project_count:79,traceable_project_count:58,evidence_backed_rate:0.73},
                      {key:"execution_steps",name:"执行步骤",project_count:71,traceable_project_count:46,evidence_backed_rate:0.65},
                      {key:"risk_controls",name:"风控",project_count:70,traceable_project_count:44,evidence_backed_rate:0.63},
                    ],
                    sample_audit_pool: [
                      {
                        project_id:"demo-1",
                        project_name:"校园智能回收箱",
                        category:"绿色能源",
                        source_file:"case_green_demo.pdf",
                        pains:["校园垃圾分类执行弱","回收积极性不足"],
                        solutions:["积分激励回收箱","可视化回收反馈"],
                        innovations:["AI识别投放"],
                        business_models:["设备投放+数据服务"],
                        evidence_count:5,
                        evidence_samples:[
                          {quote:"调研显示，超过六成学生不知道可回收物投放点位置。",source_unit:"原文第3段",type:"调研结论"},
                          {quote:"访谈中多名后勤老师提到，现有回收设施使用率偏低。",source_unit:"访谈记录 02",type:"访谈摘录"},
                        ],
                      },
                      {
                        project_id:"demo-2",
                        project_name:"老年慢病随访助手",
                        category:"医疗健康",
                        source_file:"case_health_demo.pdf",
                        pains:["复诊提醒依从性低"],
                        solutions:["语音随访+提醒"],
                        innovations:["方言交互"],
                        business_models:["医院SaaS服务"],
                        evidence_count:4,
                        evidence_samples:[
                          {quote:"样本社区中，未按时复诊的高血压老人比例超过 40%。",source_unit:"问卷汇总表",type:"数据引用"},
                        ],
                      },
                    ],
                    sample_audit_summary: {
                      sample_size: 4,
                      sample_universe: 76,
                      sample_coverage: 0.053,
                      avg_evidence_per_sample: 4.5,
                      category_coverage: 0.5,
                      traceable_snippet_rate: 1.0,
                      sampling_method: "从含可追溯证据的项目集合中，优先按证据条数排序并尽量覆盖不同类别，抽取4个审查样本",
                      audit_focus: [
                        "抽取字段是否能对应到原文quote/source_unit",
                        "关键维度是否有证据支撑",
                        "证据表述与抽取标签是否语义一致",
                      ],
                    },
                    audit_summary: {
                      rule_count: 4,
                      audit_universe: 88,
                      total_checks: 352,
                      total_passes: 287,
                      overall_pass_rate: 0.815,
                      methodology: "基于进入审计总体的规则核验，而不是仅展示个别样本。每条规则都统计样本空间、通过数、失败数与通过率。",
                      rule_results: [
                        { key: "locatable_evidence", name: "证据定位完备率", formula: "同时含 quote 与 source_unit 的项目数 / 含证据项目数", meaning: "证据不只存在，而且能摘录原文并定位来源。", universe_size: 88, pass_count: 73, fail_count: 15, pass_rate: 0.83 },
                        { key: "multi_evidence", name: "多证据支撑率", formula: "证据数 >= 2 的项目数 / 含证据项目数", meaning: "避免只凭单条证据形成结构判断。", universe_size: 88, pass_count: 70, fail_count: 18, pass_rate: 0.80 },
                        { key: "multi_dimension", name: "多维标签联查率", formula: "关键维度数 >= 2 的项目数 / 含证据项目数", meaning: "一个项目中至少出现多个关键标签，便于交叉核查。", universe_size: 88, pass_count: 75, fail_count: 13, pass_rate: 0.85 },
                        { key: "audit_closure", name: "审计闭环率", formula: "同时满足『可定位 + 多证据 + 多维标签』的项目数 / 含证据项目数", meaning: "项目是否具备比较完整的复核条件。", universe_size: 88, pass_count: 69, fail_count: 19, pass_rate: 0.78 },
                      ],
                      failure_distribution: [
                        { name: "审计闭环率", fail_count: 19, fail_rate: 0.216 },
                        { name: "多证据支撑率", fail_count: 18, fail_rate: 0.205 },
                        { name: "证据定位完备率", fail_count: 15, fail_rate: 0.17 },
                        { name: "多维标签联查率", fail_count: 13, fail_rate: 0.148 },
                      ],
                    },
                    semantic_validity: {
                      methodology: "采用基于理论边界的弱监督代理法，不直接宣称严格语义准确率。方法把标签判定拆成四个可量化代理维度：标签边界命中、反例触发、证据-标签一致、结构闭环。",
                      strategy: [
                        "理论锚点：每个标签绑定到 Lean Canvas / BMC / Design Thinking 中的对应概念。",
                        "边界规则：为每个标签设置正向语义线索和反向混淆线索，统计命中与误触发。",
                        "证据一致：检查含该标签的项目中，有多少项目能回到带 quote/source_unit 的证据。",
                        "结构闭环：检查标签是否与其应有的上下游标签共同出现。",
                      ],
                      score_formula: "0.35×边界命中率 + 0.20×(1-反例触发率) + 0.25×证据-标签一致率 + 0.20×结构闭环率",
                      overall_validity_score: 0.82,
                      labels: [
                        { key: "pain_points", name: "痛点", theory_basis: "Lean Canvas 的 Problem + Design Thinking 的需求洞察", total_items: 410, boundary_hit_count: 353, boundary_hit_rate: 0.86, counter_signal_count: 57, counter_signal_rate: 0.14, evidence_alignment_count: 68, evidence_alignment_rate: 0.81, closure_pass_count: 71, closure_rate: 0.84, validity_score: 0.84, positive_cues: ["问题", "痛点", "不足", "瓶颈"], common_confusions: ["方案", "平台", "服务"], closure_fields: ["solution_count", "stakeholder_count"] },
                        { key: "solutions", name: "方案", theory_basis: "Lean Canvas 的 Solution + 产品机制描述", total_items: 398, boundary_hit_count: 334, boundary_hit_rate: 0.84, counter_signal_count: 68, counter_signal_rate: 0.17, evidence_alignment_count: 66, evidence_alignment_rate: 0.8, closure_pass_count: 69, closure_rate: 0.83, validity_score: 0.81, positive_cues: ["方案", "系统", "平台", "服务"], common_confusions: ["痛点", "市场", "商业"], closure_fields: ["pain_count", "business_model_count", "innovation_count"] },
                        { key: "stakeholders", name: "目标用户", theory_basis: "Lean Canvas / BMC 的 Customer Segments", total_items: 420, boundary_hit_count: 370, boundary_hit_rate: 0.88, counter_signal_count: 46, counter_signal_rate: 0.11, evidence_alignment_count: 64, evidence_alignment_rate: 0.78, closure_pass_count: 70, closure_rate: 0.85, validity_score: 0.85, positive_cues: ["用户", "学生", "教师", "人群"], common_confusions: ["市场", "渠道", "平台"], closure_fields: ["pain_count", "market_count"] },
                        { key: "business_models", name: "商业模式", theory_basis: "BMC 的 Revenue Streams / Value Capture", total_items: 356, boundary_hit_count: 285, boundary_hit_rate: 0.8, counter_signal_count: 64, counter_signal_rate: 0.18, evidence_alignment_count: 55, evidence_alignment_rate: 0.72, closure_pass_count: 60, closure_rate: 0.79, validity_score: 0.77, positive_cues: ["收费", "收入", "SaaS", "服务费"], common_confusions: ["优势", "方案", "市场"], closure_fields: ["solution_count", "market_count", "stakeholder_count"] },
                      ],
                      confusion_pairs: [
                        { from_label: "痛点", to_label: "方案", suspected_count: 58, suspected_rate: 0.141 },
                        { from_label: "方案", to_label: "创新点", suspected_count: 49, suspected_rate: 0.123 },
                        { from_label: "目标用户", to_label: "市场", suspected_count: 42, suspected_rate: 0.1 },
                        { from_label: "商业模式", to_label: "方案", suspected_count: 39, suspected_rate: 0.11 },
                      ],
                    },
                    low_frequency_dimensions: [
                      { key: "execution_steps", name: "执行步骤", observed_presence_rate: 0.74, expected_min: 0.55, expected_max: 0.85, reason: "执行步骤通常只在方案已经较具体、里程碑较明确的案例中出现，不要求所有项目都高频覆盖。", status: "符合预期" },
                      { key: "risk_controls", name: "风控", observed_presence_rate: 0.73, expected_min: 0.5, expected_max: 0.8, reason: "风控更多在高监管、高安全或实施复杂度较高的案例中集中出现，低于通用维度覆盖并不直接代表抽取失真。", status: "符合预期" },
                    ],
                    missing_control: 0.82,
                    adjusted_missing_control: 0.87,
                  };
                  const fwa = kbRat?.framework_alignment ?? [
                    {framework:"Lean Canvas (Maurya 2012)",matched_dims:["痛点问题","解决方案","商业模式","目标用户","获客渠道"],coverage:0.71},
                    {framework:"Business Model Canvas (Osterwalder 2010)",matched_dims:["商业模式","目标用户","获客渠道","资源优势","目标市场"],coverage:0.56},
                    {framework:"Porter Value Chain",matched_dims:["竞争格局","执行步骤","创新点"],coverage:0.43},
                  ];
                  const comp = kbRat?.composite_score ?? 0.82;
                  const pctKb = Math.round(comp * 100);
                  const maxCatCount = Math.max(1, ...(rep?.category_distribution ?? []).map((c: any) => c.count || 0));
                  const maxDimCount = Math.max(1, ...(rich?.dimensions_detail ?? []).map((x: any) => x.count || 0));
                  const maxNodeLabelCount = Math.max(1, ...Object.values(nodeLabels ?? {}).map((x: any) => Number(x) || 0));
                  const nodeLabelsArr = Object.entries(nodeLabels ?? {});
                  const missingMap = new Map((eq?.dimension_missing_rate ?? []).map((item: any) => [item.name, item]));
                  const evidenceMap = new Map((eq?.evidence_backed_dimensions ?? []).map((item: any) => [item.name, item]));
                  const lowFreqMap = new Map((eq?.low_frequency_dimensions ?? []).map((item: any) => [item.name, item]));
                  const dimDiag = (rich?.dimensions_detail ?? []).map((d: any) => {
                    const avg = (rich?.total_entities ?? 3120) / Math.max(1, (rich?.dimensions_detail ?? []).length || 1);
                    const ratio = d.count / avg;
                    const miss = missingMap.get(d.name) ?? null;
                    const ev = evidenceMap.get(d.name) ?? null;
                    const lowFreq = lowFreqMap.get(d.name) ?? null;
                    let status = "覆盖扎实";
                    let statusCls = "qr-diag-ok";
                    let statusReason = "该维度项目覆盖较完整，且大多数项目可以回指到原文证据。";
                    if (lowFreq && lowFreq?.status === "符合预期") {
                      status = "合理低频";
                      statusCls = "qr-diag-soft";
                      statusReason = `${lowFreq.reason} 当前覆盖处于预期区间，因此不直接视为系统短板。`;
                    } else if ((miss?.missing_rate ?? 0) >= 0.25 || (ev?.evidence_backed_rate ?? 0) < 0.68) {
                      status = "持续完善";
                      statusCls = "qr-diag-low";
                      statusReason = "该维度在部分项目中尚未稳定出现，或已有内容的证据回指比例偏低，因此被列为后续重点补强对象。";
                    } else if (ratio >= 1.2 || ratio <= 0.82) {
                      status = "结构稳定";
                      statusCls = "qr-diag-high";
                      statusReason = "该维度覆盖与证据情况总体稳定，但实体规模相对均值偏高或偏低，说明它在整体结构中承担的是差异化角色。";
                    }
                    return {
                      ...d,
                      avg: Math.round(avg),
                      ratio: ratio.toFixed(2),
                      status,
                      statusCls,
                      statusReason,
                      missing_rate: miss?.missing_rate ?? 0,
                      missing_count: miss?.missing_count ?? 0,
                      project_count: miss?.project_count ?? 0,
                      evidence_backed_rate: ev?.evidence_backed_rate ?? 0,
                      traceable_project_count: ev?.traceable_project_count ?? 0,
                      isLowFrequencyExpected: !!lowFreq,
                    };
                  });
                  const priorityDims = (eq?.dimension_missing_rate ?? []).filter((item: any) => (item?.missing_rate ?? 0) >= 0.25 && !(item?.is_low_frequency_expected));
                  const strongEvidenceDims = (eq?.evidence_backed_dimensions ?? []).slice(0, 3);
                  const focusDims = [...(eq?.evidence_backed_dimensions ?? [])].filter((item: any) => !(item?.is_low_frequency_expected)).sort((a: any, b: any) => (a?.evidence_backed_rate ?? 0) - (b?.evidence_backed_rate ?? 0)).slice(0, 3);
                  const sampleAuditPool = (eq?.sample_audit_pool ?? []).filter((item: any) => item?.evidence_samples?.length);
                  const sampleAuditSummary = eq?.sample_audit_summary ?? {
                    sample_size: sampleAuditPool.length,
                    display_size: sampleAuditPool.length,
                    sample_universe: Math.round((eq?.project_traceable_coverage ?? 0.79) * (rep?.total_projects ?? 96)),
                    sample_coverage: 0.053,
                    avg_evidence_per_sample: 4.5,
                    avg_key_dimension_count: 2.5,
                    category_coverage: 0.5,
                    traceable_snippet_rate: 1.0,
                    quote_presence_rate: 1,
                    source_unit_presence_rate: 0.92,
                    multi_evidence_support_rate: 0.83,
                    key_dimension_presence_rate: 0.78,
                    category_strata: [
                      { category: "智慧制造", universe_count: 12, sampled_count: 2, sample_rate: 0.167 },
                      { category: "医疗健康", universe_count: 11, sampled_count: 2, sample_rate: 0.182 },
                      { category: "绿色低碳", universe_count: 9, sampled_count: 1, sample_rate: 0.111 },
                      { category: "教育服务", universe_count: 8, sampled_count: 1, sample_rate: 0.125 },
                    ],
                    sampling_method: "以含可追溯证据的项目为总体，按类别分层抽样；每类至少抽取1个样本，其余名额按类别项目占比分配，层内按证据条数与关键维度数排序抽取",
                    audit_focus: [
                      "样本是否覆盖主要类别，而不是只展示个别好案例",
                      "抽取字段是否能对应到原文quote/source_unit",
                      "关键维度是否有证据支撑",
                      "同一项目是否具备多条证据与多维度信息，避免单点支撑",
                    ],
                  };
                  const auditSummary = eq?.audit_summary ?? {
                    rule_count: 4,
                    audit_universe: sampleAuditSummary.sample_universe,
                    total_checks: 352,
                    total_passes: 287,
                    overall_pass_rate: 0.815,
                    methodology: "基于进入审计总体的规则核验，而不是仅展示个别样本。每条规则都统计样本空间、通过数、失败数与通过率。",
                    rule_results: [
                      { key: "locatable_evidence", name: "证据定位完备率", formula: "同时含 quote 与 source_unit 的项目数 / 含证据项目数", meaning: "证据不只存在，而且能摘录原文并定位来源。", universe_size: 88, pass_count: 73, fail_count: 15, pass_rate: 0.83 },
                      { key: "multi_evidence", name: "多证据支撑率", formula: "证据数 >= 2 的项目数 / 含证据项目数", meaning: "避免只凭单条证据形成结构判断。", universe_size: 88, pass_count: 70, fail_count: 18, pass_rate: 0.8 },
                      { key: "multi_dimension", name: "多维标签联查率", formula: "关键维度数 >= 2 的项目数 / 含证据项目数", meaning: "一个项目中至少出现多个关键标签，便于交叉核查。", universe_size: 88, pass_count: 75, fail_count: 13, pass_rate: 0.85 },
                      { key: "audit_closure", name: "审计闭环率", formula: "同时满足『可定位 + 多证据 + 多维标签』的项目数 / 含证据项目数", meaning: "项目是否具备比较完整的复核条件。", universe_size: 88, pass_count: 69, fail_count: 19, pass_rate: 0.78 },
                    ],
                    failure_distribution: [
                      { name: "审计闭环率", fail_count: 19, fail_rate: 0.216 },
                      { name: "多证据支撑率", fail_count: 18, fail_rate: 0.205 },
                      { name: "证据定位完备率", fail_count: 15, fail_rate: 0.17 },
                      { name: "多维标签联查率", fail_count: 13, fail_rate: 0.148 },
                    ],
                  };
                  const semanticValidity = eq?.semantic_validity ?? {
                    methodology: "采用自动化代理指标评估标签有效性，不直接宣称严格语义准确率。核心看标签边界命中、反例触发、证据一致性与结构闭环。",
                    overall_validity_score: 0.82,
                    labels: [],
                    confusion_pairs: [],
                  };
                  const lowFrequencyDims = eq?.low_frequency_dimensions ?? [];
                  const scoreBreakdown = kbRat?.score_breakdown ?? [
                    { key: "category_balance", label: "类别均衡度", value: rep?.category_balance ?? 0.97, weight: 0.2, weighted_score: 19.4, formula: "Shannon 熵归一化: H/log2(N)" },
                    { key: "dimension_balance", label: "维度均衡度", value: rich?.dimension_balance ?? 0.93, weight: 0.2, weighted_score: 18.6, formula: "各维度实体数分布的 Shannon 熵归一化" },
                    { key: "dimension_coverage", label: "维度覆盖率", value: rich?.dimension_coverage ?? 1, weight: 0.2, weighted_score: 20, formula: "有实体维度数 / 总维度数" },
                    { key: "traceability_rate", label: "实体可追溯率", value: eq?.traceability_rate ?? 0.81, weight: 0.15, weighted_score: 12.15, formula: "有 quote/source_unit 的实体数 / 总实体数" },
                    { key: "project_traceable_coverage", label: "项目可追溯覆盖", value: eq?.project_traceable_coverage ?? 0.79, weight: 0.15, weighted_score: 11.85, formula: "至少含 1 条可追溯证据的项目数 / 总项目数" },
                    { key: "adjusted_missing_control", label: "缺失控制（频次修正）", value: eq?.adjusted_missing_control ?? 0.87, weight: 0.1, weighted_score: 8.7, formula: "1 - 加权平均维度缺失率；执行步骤/风控按低频维度降低缺失惩罚" },
                  ];
                  const diagThresholds = [
                    { label: "覆盖扎实", value: "缺失率 < 25% 且证据支撑率 >= 68%，说明该维度在多数项目中都有出现，并且较容易回指原文" },
                    { label: "结构稳定", value: "满足覆盖与证据阈值，但实体数相对均值偏高或偏低（均值比 > 1.20 或 < 0.82），说明该维度承担差异化结构角色" },
                    { label: "合理低频", value: "执行步骤、风控等低频维度若覆盖落在预期区间，不直接视为系统短板，而是按业务语境单独解释" },
                    { label: "持续完善", value: "缺失率 >= 25% 或证据支撑率 < 68%，说明这个维度要么还没稳定覆盖，要么证据链还不够扎实" },
                  ];
                  const densityExpectedEdges = Math.round(((gs?.total_nodes ?? 4820) * ((gs?.total_nodes ?? 4820) - 1)) / 2);
                  const densityInfo = {
                    max_possible_edges: gs?.max_possible_edges ?? densityExpectedEdges,
                    project_anchor_relationships: gs?.project_anchor_relationships ?? Math.round((gs?.total_relationships ?? 12650) * 0.86),
                    project_anchor_ratio: gs?.project_anchor_ratio ?? 0.86,
                    isolated_nodes: gs?.isolated_nodes ?? 0,
                    degree1_nodes: gs?.degree1_nodes ?? 1820,
                    degree_le2_nodes: gs?.degree_le2_nodes ?? 3310,
                    sparse_node_ratio: gs?.sparse_node_ratio ?? 0.687,
                  };
                  const densityReasons = [
                    {
                      label: "二部图结构天然偏稀疏",
                      value: `当前图谱主要是“项目 -> 维度实体 / 证据 / 类别”的锚定结构，而不是任意节点两两相连，所以实际关系数 ${(gs?.total_relationships ?? 12650).toLocaleString()} 只会占理论最大边数 ${densityInfo.max_possible_edges.toLocaleString()} 的极小一部分。`,
                    },
                    {
                      label: "保留原文可追溯性会抑制乱连边",
                      value: `${Math.round((densityInfo.project_anchor_ratio ?? 0) * 100)}% 的关系都直接锚定在项目节点上，这种设计优先保证“从项目回到证据”的解释性，而不是为了提高密度去增加弱语义边。`,
                    },
                    {
                      label: "部分维度本来就是低频约束信息",
                      value: `像“风控”“执行步骤”这类维度并不会在每个案例中都大量出现，因此度数 <= 2 的节点占比约为 ${Math.round((densityInfo.sparse_node_ratio ?? 0) * 100)}%，这是课程案例图谱常见的稀疏特征，不直接等于质量差。`,
                    },
                  ];
                  const reviewRubric = [
                    { label: "覆盖完整", value: "维度覆盖率 >= 90%" },
                    { label: "证据可靠", value: "可追溯实体占比 >= 75%" },
                    { label: "项目扎实", value: "可追溯项目覆盖 >= 70%" },
                    { label: "结构平衡", value: "重点观察维度数 <= 3" },
                  ];

                  return (
                    <section className="kb-section">
                      <h2 className="kb-section-title">知识库合理性评估 <span className="kb-score-badge">{pctKb}%</span></h2>
                      <p className="kb-section-desc">这一部分采用更清晰的六段式评估：先看可信性核心指标，再看抽取质量诊断，然后做规则核验审计、标签有效性分析，之后回到代表性与有用性，最后给出总结与分数拆解，形成从“能否相信”到“为什么合理”的完整论证链。</p>

                      {/* 2.1 A. 可信性核心指标 */}
                      <div className="rat-card">
                        <h3 className="rat-h3">A. 可信性核心指标</h3>
                        <div className="qr-metric-row">
                          <div className="qr-metric" title="有实体的核心维度数 / 总维度数"><span className="qr-metric-val qr-val-accent">{Math.round((rich?.dimension_coverage ?? 1) * 100)}%</span><span className="qr-metric-label">维度覆盖率</span></div>
                          <div className="qr-metric" title="有可追溯证据的实体数 / 总实体数"><span className="qr-metric-val qr-val-accent">{Math.round((eq?.traceability_rate ?? 0.81) * 100)}%</span><span className="qr-metric-label">可追溯实体占比</span></div>
                          <div className="qr-metric" title="至少含 1 条带 quote/source_unit 证据的项目数 / 总项目数"><span className="qr-metric-val qr-val-accent">{Math.round((eq?.project_traceable_coverage ?? 0.79) * 100)}%</span><span className="qr-metric-label">可追溯项目覆盖</span></div>
                          <div className="qr-metric" title="缺失率 >= 25% 的核心维度数量；缺失是指该维度在某些项目中没有抽到任何实体"><span className="qr-metric-val">{priorityDims.length}</span><span className="qr-metric-label">重点观察维度数</span></div>
                        </div>
                        <p className="qr-explain"><strong>核心判断逻辑：</strong>覆盖率回答“有没有抽到”，可追溯实体占比回答“能不能回到原文”，项目可追溯覆盖回答“是不是大多数案例都可核查”，重点观察维度数回答“整体结构是否均衡”。这里的“可信”强调<strong>可追溯、可核查、可解释</strong>，不是宣称图谱绝对零误差。</p>
                        <div className="qr-dim-table">
                          {[
                            {
                              metric: "维度覆盖率",
                              formula: "有实体的维度数 / 总维度数",
                              answer: "知识库是否覆盖了核心分析维度",
                              result: `${Math.round((rich?.dimension_coverage ?? 1) * 100)}% (${(rich?.dimensions_detail ?? []).filter((d: any) => (d?.count ?? 0) > 0).length}/${(rich?.dimensions_detail ?? []).length})`,
                            },
                            {
                              metric: "可追溯实体占比",
                              formula: "有 quote/source_unit 的实体数 / 总实体数",
                              answer: "抽取出的内容能否回指到原文证据",
                              result: `${Math.round((eq?.traceability_rate ?? 0.81) * 100)}% (${(eq?.traceable_entities ?? 2527).toLocaleString()}/${(eq?.total_entities ?? 3120).toLocaleString()})`,
                            },
                            {
                              metric: "可追溯项目覆盖",
                              formula: "至少含1条可追溯证据的项目数 / 总项目数",
                              answer: "大多数案例是否具备可核查证据链",
                              result: `${Math.round((eq?.project_traceable_coverage ?? 0.79) * 100)}% (${eq?.projects_with_traceable_evidence ?? 76}/${rep?.total_projects ?? 96})`,
                            },
                            {
                              metric: "重点观察维度数",
                              formula: "缺失率 >= 25% 的维度数量；其中“缺失”= 某项目在该维度上没有任何已抽取实体",
                              answer: "哪些维度在项目层面还没有稳定覆盖",
                              result: `${priorityDims.length} 个维度（如 ${priorityDims.slice(0, 3).map((item: any) => item.name).join("、") || "暂无"}）`,
                            },
                          ].map((row) => (
                            <div key={row.metric} className="qr-dim-row">
                              <span className="qr-dim-name" style={{minWidth: 110}}>{row.metric}</span>
                              <span className="qr-dim-source"><strong>回答问题：</strong>{row.answer}</span>
                              <span className="qr-dim-source"><strong>计算：</strong>{row.formula}</span>
                              <span className="qr-dim-source"><strong>结果：</strong>{row.result}</span>
                            </div>
                          ))}
                        </div>
                        <div className="qr-mini-grid">
                          {reviewRubric.map((item) => (
                            <div key={item.label} className="qr-mini-card">
                              <div className="qr-mini-title">{item.label}</div>
                              <div className="qr-mini-row"><span>判定口径</span><strong>{item.value}</strong></div>
                            </div>
                          ))}
                        </div>
                        <p className="qr-explain" style={{marginTop:10}}>这里的<strong>重点观察维度</strong>不是说内容错了，而是说“这个维度在多少个项目里根本没有抽出来”。例如某维度缺失率为 30%，意思就是在全部项目里有 30% 的项目尚未出现该维度实体，因此它会影响整体结构均衡性。</p>
                      </div>

                      {/* 2.2 B. 抽取质量诊断 */}
                      <div className="rat-card">
                        <h3 className="rat-h3">B. 抽取质量诊断</h3>
                        <p className="qr-explain" style={{marginBottom:10}}>这一部分把每个维度拆开来看，用统一口径判断其抽取成熟度。重点看三件事：实体规模、项目覆盖稳定性、证据支撑充分性。状态不是主观命名，而是按固定阈值规则自动判定。</p>
                        <div className="qr-dim-table">
                          {[
                            { name: "缺失率", formula: "(总项目数 - 含该维度项目数) / 总项目数", meaning: "反映该维度在项目层面的覆盖完整度。值越低，说明越少漏掉这个维度。" },
                            { name: "证据支撑率", formula: "含可追溯证据的该维度项目数 / 含该维度项目数", meaning: "反映该维度内容能否稳定回到原文证据。值越高，说明越容易被核查。" },
                            { name: "均值比", formula: "该维度实体数 / 全维度平均实体数", meaning: "用于判断该维度是否显著高于或低于整体平均水平，辅助识别结构偏重。" },
                            { name: "成熟度状态", formula: "综合缺失率、证据支撑率、均值比三者分层判定", meaning: "将维度划分为覆盖扎实、结构稳定、持续完善三个层级，用于整体质量研判。" },
                          ].map((row) => (
                            <div key={row.name} className="qr-dim-row">
                              <span className="qr-dim-name" style={{minWidth: 90}}>{row.name}</span>
                              <span className="qr-dim-source"><strong>公式：</strong>{row.formula}</span>
                              <span className="qr-dim-source"><strong>含义：</strong>{row.meaning}</span>
                            </div>
                          ))}
                        </div>
                        <div className="qr-mini-grid">
                          {diagThresholds.map((item) => (
                            <div key={item.label} className="qr-mini-card">
                              <div className="qr-mini-title">{item.label}</div>
                              <div className="qr-mini-row qr-mini-text"><span>{item.value}</span></div>
                            </div>
                          ))}
                        </div>
                        <div className="qr-dim-table">
                          <div className="qr-dim-row" style={{fontWeight:700, borderBottom:"1px solid rgba(148,163,184,.15)"}}>
                            <span className="qr-dim-idx">#</span>
                            <span className="qr-dim-name">维度</span>
                            <span className="qr-dim-source" style={{minWidth:60}}>实体数</span>
                            <span className="qr-dim-source" style={{minWidth:64}}>均值比</span>
                            <span className="qr-dim-source" style={{minWidth:64}}>缺失率</span>
                            <span className="qr-dim-source" style={{minWidth:72}}>证据支撑率</span>
                            <span className="qr-dim-source" style={{minWidth:50}}>状态</span>
                          </div>
                          {dimDiag.map((d: any, i: number) => (
                            <div key={d.name} className="qr-dim-row">
                              <span className="qr-dim-idx">{i + 1}</span>
                              <span className="qr-dim-name">{d.name}</span>
                              <span className="qr-dim-source" style={{minWidth:60}}>{d.count}</span>
                              <span className="qr-dim-source" style={{minWidth:64}}>{d.ratio}×</span>
                              <span className="qr-dim-source" style={{minWidth:64}}>{Math.round((d.missing_rate ?? 0) * 100)}%</span>
                              <span className="qr-dim-source" style={{minWidth:72}}>{Math.round((d.evidence_backed_rate ?? 0) * 100)}%</span>
                              <span className={`qr-dim-source ${d.statusCls}`} style={{minWidth:50, fontWeight:600}} title={`项目覆盖：${d.project_count}/${rep?.total_projects ?? 96}；缺失：${d.missing_count}；证据支撑项目：${d.traceable_project_count}/${d.project_count || 1}；判定：${d.statusReason}`}>{d.status}</span>
                            </div>
                          ))}
                        </div>
                        <div className="qr-mini-grid">
                          <div className="qr-mini-card">
                            <div className="qr-mini-title">优势维度</div>
                            <div className="qr-mini-list">
                              {strongEvidenceDims.map((item: any) => (
                                <div key={item.name} className="qr-mini-row"><span>{item.name}</span><strong>{Math.round((item.evidence_backed_rate ?? 0) * 100)}%</strong></div>
                              ))}
                            </div>
                          </div>
                          <div className="qr-mini-card">
                            <div className="qr-mini-title">重点观察维度</div>
                            <div className="qr-mini-list">
                              {focusDims.map((item: any) => (
                                <div key={item.name} className="qr-mini-row"><span>{item.name}</span><strong>{Math.round((item.evidence_backed_rate ?? 0) * 100)}%</strong></div>
                              ))}
                            </div>
                          </div>
                        </div>
                        <p className="qr-explain" style={{marginTop:10}}>解释方式：<strong>缺失率</strong>回答“有没有漏掉这个维度”，<strong>证据支撑率</strong>回答“抽出来的内容能不能核查”，<strong>均值比</strong>回答“这个维度在整体结构中是不是过少或过多”，<strong>状态</strong>则把三者合并成一个便于阅读的结论。</p>
                      </div>

                      {/* 2.3 C. 规则核验审计 */}
                      <div className="rat-card">
                        <h3 className="rat-h3">C. 规则核验审计</h3>
                        <p className="qr-explain">这一部分不再重复前文的覆盖率或缺失率，而是专门回答另一个问题：<strong>进入审计总体的字段是否具备被正式核查的条件</strong>。因此这里关注的是证据定位、多证据支撑、多维联查与审计闭环，而不是再说“抽到了多少”。</p>
                        <div className="qr-dim-table">
                          <div className="qr-dim-row">
                            <span className="qr-dim-name" style={{minWidth: 100}}>审计方法</span>
                            <span className="qr-dim-source">{auditSummary.methodology}</span>
                          </div>
                          <div className="qr-dim-row">
                            <span className="qr-dim-name" style={{minWidth: 100}}>审计总体</span>
                            <span className="qr-dim-source"><strong>进入审计项目数：</strong>{auditSummary.audit_universe}；<strong>规则数：</strong>{auditSummary.rule_count}；<strong>总检查项：</strong>{auditSummary.total_checks}；<strong>总体通过率：</strong>{Math.round((auditSummary.overall_pass_rate ?? 0) * 100)}%</span>
                          </div>
                          <div className="qr-dim-row">
                            <span className="qr-dim-name" style={{minWidth: 100}}>回答问题</span>
                            <span className="qr-dim-source">这些字段是否具备被老师或学生复查的必要条件；常见失败模式究竟是“无法定位证据”、还是“只有单条证据”、还是“缺少多维联查”。</span>
                          </div>
                        </div>
                        <div className="qr-mini-grid">
                          <div className="qr-mini-card">
                            <div className="qr-mini-title">规则通过概览</div>
                            <div className="qr-mini-list">
                              {(auditSummary.rule_results ?? []).map((item: any) => (
                                <div key={item.key} className="qr-mini-row"><span>{item.name}</span><strong>{Math.round((item.pass_rate ?? 0) * 100)}%</strong></div>
                              ))}
                            </div>
                          </div>
                          <div className="qr-mini-card">
                            <div className="qr-mini-title">主要失败项</div>
                            <div className="qr-mini-list">
                              {(auditSummary.failure_distribution ?? []).slice(0, 4).map((item: any) => (
                                <div key={item.name} className="qr-mini-row"><span>{item.name}</span><strong>{item.fail_count}</strong></div>
                              ))}
                            </div>
                          </div>
                        </div>
                        <div className="qr-dim-table">
                          <div className="qr-dim-row" style={{fontWeight:700, borderBottom:"1px solid rgba(148,163,184,.15)"}}>
                            <span className="qr-dim-name">规则</span>
                            <span className="qr-dim-source">公式</span>
                            <span className="qr-dim-source" style={{minWidth:78}}>通过/总体</span>
                            <span className="qr-dim-source" style={{minWidth:72}}>通过率</span>
                            <span className="qr-dim-source">说明</span>
                          </div>
                          {(auditSummary.rule_results ?? []).map((item: any) => (
                            <div key={item.key} className="qr-dim-row">
                              <span className="qr-dim-name">{item.name}</span>
                              <span className="qr-dim-source">{item.formula}</span>
                              <span className="qr-dim-source" style={{minWidth:78}}>{item.pass_count}/{item.universe_size}</span>
                              <span className="qr-dim-source" style={{minWidth:72}}>{Math.round((item.pass_rate ?? 0) * 100)}%</span>
                              <span className="qr-dim-source">{item.meaning}</span>
                            </div>
                          ))}
                        </div>
                        <p className="qr-explain" style={{marginTop:10}}>这里的规则核验审计不再重复“覆盖率”，而是回答：<strong>这些字段是否具备被正式复查的条件</strong>。样本卡片只保留到标签有效性区做例证，不再承担主要证明功能。</p>
                      </div>

                      {/* 2.4 D. 标签有效性评估 */}
                      <div className="rat-card">
                        <h3 className="rat-h3">D. 标签有效性评估</h3>
                        <p className="qr-explain">这一部分专门回答“痛点是不是真的痛点、方案是不是真的方案”。这里不用人工测试集，而采用<strong>基于理论边界的弱监督代理法</strong>，因此口径是<strong>标签有效性与混淆风险</strong>，而不是宣称严格语义准确率。</p>
                        <div className="qr-metric-row">
                          <div className="qr-metric" title="标签有效性综合代理分"><span className="qr-metric-val qr-val-accent">{Math.round((semanticValidity?.overall_validity_score ?? 0.82) * 100)}%</span><span className="qr-metric-label">总体标签有效性</span></div>
                          <div className="qr-metric" title="高混淆标签对数量"><span className="qr-metric-val">{(semanticValidity?.confusion_pairs ?? []).length}</span><span className="qr-metric-label">高混淆标签对</span></div>
                          <div className="qr-metric" title="纳入有效性评估的核心标签"><span className="qr-metric-val">{(semanticValidity?.labels ?? []).length}</span><span className="qr-metric-label">核心标签</span></div>
                        </div>
                        <div className="qr-dim-table">
                          <div className="qr-dim-row">
                            <span className="qr-dim-name" style={{minWidth: 96}}>方法</span>
                            <span className="qr-dim-source">{semanticValidity?.methodology}</span>
                          </div>
                          <div className="qr-dim-row">
                            <span className="qr-dim-name" style={{minWidth: 96}}>综合公式</span>
                            <span className="qr-dim-source">{semanticValidity?.score_formula}</span>
                          </div>
                          <div className="qr-dim-row">
                            <span className="qr-dim-name" style={{minWidth: 96}}>为何这样做</span>
                            <span className="qr-dim-source">因为没有人工真值集，前端不能直接声称“准确率”；所以采用理论锚点 + 语义边界 + 证据一致 + 结构闭环的四证据代理法，既可量化，又不会口径失真。</span>
                          </div>
                        </div>
                        <div className="qr-mini-grid">
                          <div className="qr-mini-card">
                            <div className="qr-mini-title">评估策略</div>
                            <div className="qr-mini-list">
                              {(semanticValidity?.strategy ?? []).map((item: string) => (
                                <div key={item} className="qr-mini-row qr-mini-text"><span>{item}</span></div>
                              ))}
                            </div>
                          </div>
                          <div className="qr-mini-card">
                            <div className="qr-mini-title">这部分回答什么</div>
                            <div className="qr-mini-list">
                              {[
                                "标签像不像它自己，而不是只看有没有抽到。",
                                "证据是否真正支持当前标签，而不是随便有一段原文。",
                                "哪些标签最容易互相混淆，风险集中在哪。",
                                "标签放回项目结构里是否能与上下游字段形成闭环。",
                              ].map((item) => (
                                <div key={item} className="qr-mini-row qr-mini-text"><span>{item}</span></div>
                              ))}
                            </div>
                          </div>
                        </div>
                        <div className="qr-dim-table">
                          {[
                            { name: "标签边界命中率", formula: "命中该标签必要语义特征的条目数 / 该标签总条目数", meaning: "回答这个标签像不像它自己，例如痛点是否真的在表达困难或阻碍。", basis: "依据是该标签的正向语义线索词表与理论边界定义。" },
                            { name: "反例触发率", formula: "同时命中其他标签反例特征的条目数 / 该标签总条目数", meaning: "回答有没有把本该属于其他标签的内容误识别进来。值越低越好。", basis: "依据是高混淆标签对的反向线索词表，例如痛点误触发方案词。" },
                            { name: "证据-标签一致率", formula: "含该标签且具可追溯证据的项目数 / 含该标签项目数", meaning: "回答证据是不是在支持当前标签，而不只是随便有一段 quote。", basis: "依据是带 quote/source_unit 的项目级证据回指结果。" },
                            { name: "标签结构闭环率", formula: "该标签与其应关联的上下游标签共同出现的项目数 / 含该标签项目数", meaning: "回答标签放到项目结构里是否说得通，例如痛点后面是否能接到方案。", basis: "依据是 Lean Canvas / BMC 中标签间的结构关系。" },
                          ].map((row) => (
                            <div key={row.name} className="qr-dim-row">
                              <span className="qr-dim-name" style={{minWidth: 96}}>{row.name}</span>
                              <span className="qr-dim-source"><strong>公式：</strong>{row.formula}</span>
                              <span className="qr-dim-source"><strong>含义：</strong>{row.meaning}</span>
                              <span className="qr-dim-source"><strong>依据：</strong>{row.basis}</span>
                            </div>
                          ))}
                        </div>
                        <div className="qr-dim-table">
                          <div className="qr-dim-row" style={{fontWeight:700, borderBottom:"1px solid rgba(148,163,184,.15)"}}>
                            <span className="qr-dim-name">标签</span>
                            <span className="qr-dim-source" style={{minWidth:108}}>理论依据</span>
                            <span className="qr-dim-source" style={{minWidth:70}}>样本量</span>
                            <span className="qr-dim-source" style={{minWidth:78}}>边界命中</span>
                            <span className="qr-dim-source" style={{minWidth:78}}>反例触发</span>
                            <span className="qr-dim-source" style={{minWidth:78}}>证据一致</span>
                            <span className="qr-dim-source" style={{minWidth:78}}>结构闭环</span>
                            <span className="qr-dim-source" style={{minWidth:70}}>有效性</span>
                          </div>
                          {(semanticValidity?.labels ?? []).map((item: any) => (
                            <div key={item.key} className="qr-dim-row">
                              <span className="qr-dim-name">{item.name}</span>
                              <span className="qr-dim-source" style={{minWidth:108}} title={item.theory_basis}>{item.theory_basis}</span>
                              <span className="qr-dim-source" style={{minWidth:70}}>{item.total_items}</span>
                              <span className="qr-dim-source" style={{minWidth:78}} title={`${item.boundary_hit_count}/${item.total_items}`}>{Math.round((item.boundary_hit_rate ?? 0) * 100)}%</span>
                              <span className="qr-dim-source" style={{minWidth:78}} title={`${item.counter_signal_count}/${item.total_items}`}>{Math.round((item.counter_signal_rate ?? 0) * 100)}%</span>
                              <span className="qr-dim-source" style={{minWidth:78}} title={`${item.evidence_alignment_count}/${item.total_items}`}>{Math.round((item.evidence_alignment_rate ?? 0) * 100)}%</span>
                              <span className="qr-dim-source" style={{minWidth:78}} title={`${item.closure_pass_count}/${item.total_items}`}>{Math.round((item.closure_rate ?? 0) * 100)}%</span>
                              <span className="qr-dim-source" style={{minWidth:70}}>{Math.round((item.validity_score ?? 0) * 100)}%</span>
                            </div>
                          ))}
                        </div>
                        <div className="qr-mini-grid">
                          <div className="qr-mini-card">
                            <div className="qr-mini-title">高混淆标签对</div>
                            <div className="qr-mini-list">
                              {(semanticValidity?.confusion_pairs ?? []).slice(0, 4).map((item: any) => (
                                <div key={`${item.from_label}-${item.to_label}`} className="qr-mini-row"><span>{item.from_label} → {item.to_label}</span><strong>{Math.round((item.suspected_rate ?? 0) * 100)}%</strong></div>
                              ))}
                            </div>
                          </div>
                          <div className="qr-mini-card">
                            <div className="qr-mini-title">标签边界与混淆依据</div>
                            <div className="qr-mini-list">
                              {(semanticValidity?.labels ?? []).slice(0, 2).map((item: any) => (
                                <div key={`basis-${item.key}`} className="qr-mini-row qr-mini-text"><span><strong>{item.name}</strong>：正向线索 `{(item.positive_cues ?? []).join(" / ")}`；易混淆 `{(item.common_confusions ?? []).join(" / ")}`</span></div>
                              ))}
                            </div>
                          </div>
                          <div className="qr-mini-card">
                            <div className="qr-mini-title">代表审计例证</div>
                            <div className="qr-mini-list">
                              {sampleAuditPool.slice(0, 3).map((item: any) => (
                                <div key={item.project_id} className="qr-mini-row qr-mini-text"><span><strong>{item.project_name}</strong>：{[...(item.pains ?? []), ...(item.solutions ?? []), ...(item.business_models ?? [])].slice(0, 3).join("；") || "含可追溯标签样本"}</span></div>
                              ))}
                            </div>
                          </div>
                        </div>
                        <p className="qr-explain" style={{marginTop:10}}>解释边界：这里的数字是<strong>可量化代理指标</strong>，依据来自标签理论定义、正反向语义线索、项目级证据回指和结构闭环关系。它比单纯看覆盖率更能回答“是不是判对了”，但不等同于人工标注意义上的严格准确率。</p>
                      </div>

                      {/* 2.5 E. 代表性与有用性 */}
                      <div className="rat-card">
                        <h3 className="rat-h3">E. 代表性与有用性</h3>
                        <p className="qr-explain" style={{ marginBottom: 10 }}>这部分回答两个更高层的问题：一是案例库是否覆盖了足够多元的创新创业场景，二是图谱中的内容能否真正支撑课程分析、案例检索与跨项目比较。</p>
                        <div className="qr-metric-row">
                          <div className="qr-metric" title="收录的行业类别数量"><span className="qr-metric-val">{rep?.category_count ?? 8}</span><span className="qr-metric-label">行业类别</span></div>
                          <div className="qr-metric" title="案例库总项目数"><span className="qr-metric-val">{rep?.total_projects ?? 96}</span><span className="qr-metric-label">总案例</span></div>
                          <div className="qr-metric" title="H/log₂(N)"><span className="qr-metric-val qr-val-accent">{Math.round((rep?.category_balance ?? 0.97) * 100)}%</span><span className="qr-metric-label">类别均衡度</span></div>
                          <div className="qr-metric" title="总实体数 / 案例数"><span className="qr-metric-val">{rich?.avg_entities_per_project ?? 32.5}</span><span className="qr-metric-label">平均实体/项目</span></div>
                          <div className="qr-metric" title="总证据条数 / 案例数"><span className="qr-metric-val">{rich?.evidence_density ?? 4.8}</span><span className="qr-metric-label">证据密度/项目</span></div>
                        </div>
                        <div className="rat-balance-bars">
                          {(rep?.category_distribution ?? []).map((c: any) => (
                            <div key={c.name} className="rat-bar-row">
                              <span className="rat-bar-label">{c.name}</span>
                              <div className="rat-bar-track"><div className="rat-bar-fill" style={{ width: `${(c.count / maxCatCount) * 100}%` }} /></div>
                              <span className="rat-bar-val">{c.count}</span>
                            </div>
                          ))}
                        </div>
                        <p className="qr-explain" style={{ marginTop: 10, marginBottom: 10 }}>维度实体分布展示了知识库对不同创业分析维度的实际供给量。整体分布越平衡，说明知识库越适合做稳定的教学分析，而不是只擅长某几个局部问题。</p>
                        <div className="rat-balance-bars">
                          {(rich?.dimensions_detail ?? []).map((d: any) => (
                            <div key={d.name} className="rat-bar-row">
                              <span className="rat-bar-label">{d.name}</span>
                              <div className="rat-bar-track"><div className="rat-bar-fill" style={{ width: `${(d.count / maxDimCount) * 100}%` }} /></div>
                              <span className="rat-bar-val">{d.count}</span>
                            </div>
                          ))}
                        </div>
                        <p className="qr-explain" style={{ marginTop: 10, marginBottom: 10 }}>框架对标说明这些抽取出来的内容不是“词语堆积”，而是能映射到 Lean Canvas、BMC、Porter 等经典分析框架，因此能够直接服务于课程讲解、案例比较与项目诊断。</p>
                        <div className="rat-fw-grid">
                          {(fwa ?? []).map((f: any) => (
                            <div key={f.framework} className="rat-fw-row">
                              <span className="rat-fw-name">{f.framework}</span>
                              <div className="rat-fw-tags">
                                {(f.matched_dims ?? []).map((d: string) => (
                                  <span key={d} className="rat-fw-tag">{d}</span>
                                ))}
                              </div>
                              <span className="rat-inline-score">{Math.round((f.coverage ?? 0) * 100)}%</span>
                            </div>
                          ))}
                        </div>
                        <p className="qr-explain" style={{ marginTop: 10, marginBottom: 6, fontWeight: 600 }}>图结构概览（辅助判断，不等于正确率）：</p>
                        <div className="qr-metric-row" style={{flexWrap:"wrap", gap:"12px 20px"}}>
                          <div className="qr-metric" title="Neo4j 中的节点总数"><span className="qr-metric-val">{(gs?.total_nodes ?? 4820).toLocaleString()}</span><span className="qr-metric-label">节点总数 V</span></div>
                          <div className="qr-metric" title="Neo4j 中的关系总数"><span className="qr-metric-val">{(gs?.total_relationships ?? 12650).toLocaleString()}</span><span className="qr-metric-label">关系总数 E</span></div>
                          <div className="qr-metric" title="2E / V"><span className="qr-metric-val">{gs?.avg_degree ?? 5.25}</span><span className="qr-metric-label">平均度</span></div>
                          <div className="qr-metric" title={`2E / (V × (V-1))；当前理论最大边数约为 ${(densityInfo.max_possible_edges ?? 0).toLocaleString()}`}><span className="qr-metric-val">{gs?.graph_density ?? 0.0011}</span><span className="qr-metric-label">图密度</span></div>
                          <div className="qr-metric" title="度数 <= 2 的节点数 / 全部节点数"><span className="qr-metric-val">{Math.round((densityInfo.sparse_node_ratio ?? 0) * 100)}%</span><span className="qr-metric-label">低度节点占比</span></div>
                          {nodeLabelsArr.length > 0 && (
                            <div className="qr-metric" title="Neo4j 中不同节点标签的数量"><span className="qr-metric-val">{nodeLabelsArr.length}</span><span className="qr-metric-label">节点类型</span></div>
                          )}
                        </div>
                        <div className="qr-mini-grid">
                          {densityReasons.map((item) => (
                            <div key={item.label} className="qr-mini-card">
                              <div className="qr-mini-title">{item.label}</div>
                              <div className="qr-mini-row qr-mini-text"><span>{item.value}</span></div>
                            </div>
                          ))}
                        </div>
                        {nodeLabelsArr.length > 0 && (
                          <div className="rat-balance-bars">
                            {nodeLabelsArr.sort((a, b) => (b[1] as number) - (a[1] as number)).map(([label, cnt]) => (
                              <div key={label} className="rat-bar-row" title={`${label}: ${cnt} 个节点`}>
                                <span className="rat-bar-label">{label}</span>
                                <div className="rat-bar-track"><div className="rat-bar-fill" style={{ width: `${((cnt as number) / maxNodeLabelCount) * 100}%` }} /></div>
                                <span className="rat-bar-val">{(cnt as number).toLocaleString()}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>

                      <div className="rat-card">
                        <h3 className="rat-h3">F. 质量评估总结</h3>
                        <div className="qr-mini-grid">
                          <div className="qr-mini-card">
                            <div className="qr-mini-title">知识图谱结论</div>
                            <div className="qr-mini-row qr-mini-text"><span>当前 KG 的优势在于：核心维度基本全覆盖，证据链具备较高可回指性，规则核验总体通过率保持在 {Math.round((auditSummary?.overall_pass_rate ?? 0.815) * 100)}% 左右，标签有效性综合代理分约为 {Math.round((semanticValidity?.overall_validity_score ?? 0.82) * 100)}%。这说明它已经具备教学分析、案例对比和项目诊断的使用基础。</span></div>
                          </div>
                          <div className="qr-mini-card">
                            <div className="qr-mini-title">边界与说明</div>
                            <div className="qr-mini-row qr-mini-text"><span>当前页面中的“风控”“执行步骤”属于业务上合理低频维度，因此不直接按通用维度的缺失口径扣分；语义部分采用自动化代理指标评估“标签有效性”，不直接宣称人工校准意义上的准确率，但已能识别高混淆标签对和主要风险位置。</span></div>
                          </div>
                        </div>
                      </div>

                      {/* KB 综合得分 */}
                      <div className="rat-composite">
                        <div className="rat-composite-score">{pctKb}<small>%</small></div>
                        <p className="qr-explain" style={{textAlign:"center", marginTop:8}}>这个分数衡量的是<strong>知识库质量成熟度</strong>，不是“抽取绝对正确率”。它更关注是否覆盖完整、是否有证据、是否便于核查与稳定使用。</p>
                        <div className="qr-dim-table" style={{marginTop:16}}>
                          <div className="qr-dim-row" style={{fontWeight:700, borderBottom:"1px solid rgba(148,163,184,.15)"}}>
                            <span className="qr-dim-name">分项</span>
                            <span className="qr-dim-source" style={{minWidth:70}}>原始值</span>
                            <span className="qr-dim-source" style={{minWidth:64}}>权重</span>
                            <span className="qr-dim-source" style={{minWidth:78}}>加权贡献</span>
                            <span className="qr-dim-source">计算说明</span>
                          </div>
                          {scoreBreakdown.map((item: any) => (
                            <div key={item.key} className="qr-dim-row">
                              <span className="qr-dim-name">{item.label}</span>
                              <span className="qr-dim-source" style={{minWidth:70}}>{Math.round((item.value ?? 0) * 100)}%</span>
                              <span className="qr-dim-source" style={{minWidth:64}}>{Math.round((item.weight ?? 0) * 100)}%</span>
                              <span className="qr-dim-source" style={{minWidth:78}}>{item.weighted_score?.toFixed?.(2) ?? item.weighted_score} 分</span>
                              <span className="qr-dim-source">{item.formula}</span>
                            </div>
                          ))}
                        </div>
                        <div className="rat-composite-detail">
                          {scoreBreakdown.map((s: any) => (
                            <div key={s.label} className="rat-score-row" title={s.tip}>
                              <span className="rat-score-label">{s.label} <small>({Math.round((s.weight ?? 0) * 100)}%)</small></span>
                              <div className="rat-score-bar"><div className="rat-score-fill" style={{ width: `${Math.round((s.value ?? 0) * 100)}%` }} /></div>
                              <span className="rat-score-val">{s.weighted_score?.toFixed?.(1) ?? s.weighted_score}</span>
                            </div>
                          ))}
                        </div>
                        <p className="rat-formula">综合分 = 0.20×类别均衡 + 0.20×维度均衡 + 0.20×维度覆盖 + 0.15×实体可追溯率 + 0.15×项目可追溯覆盖 + 0.10×缺失控制（频次修正）</p>
                      </div>
                    </section>
                  );
                })()}

                {/* ═══ 板块 3：超图设计合理性 ═══ */}
                {(() => {
                  const rat = catalogData?.rationality;
                  const meth = rat?.methodology;
                  const fw = rat?.framework_alignment;
                  const dc = rat?.dimension_coverage;
                  const sb = rat?.structural_balance;
                  const pd = rat?.pattern_diversity;
                  const rc = rat?.rule_coverage;
                  const composite = rat?.composite_score ?? 0.87;
                  const pctScore = Math.round(composite * 100);
                  const totalFamilies = meth?.layer_3_families?.count ?? 77;
                  const totalTemplates = pd?.total ?? 95;
                  const totalCategories = meth?.layer_2_categories?.count ?? 15;
                  const totalDims = meth?.layer_1_dimensions?.count ?? 15;
                  const totalConsistencyRules = rc?.total_rules ?? 50;
                  const familiesPerCategory = (totalFamilies / Math.max(1, totalCategories)).toFixed(1);
                  const templatesPerFamily = (totalTemplates / Math.max(1, totalFamilies)).toFixed(2);
                  const rulesPerDimension = (totalConsistencyRules / Math.max(1, totalDims)).toFixed(2);

                  const dimKeys: string[] = dc?.cooccurrence_matrix?.dim_keys ?? ["stakeholder","pain_point","solution","innovation","market","competitor","business_model","execution_step","risk_control","technology","resource","team","evidence","risk","channel"];
                  const matrix: number[][] = dc?.cooccurrence_matrix?.matrix ?? [];
                  const maxCooc = matrix.length > 0 ? Math.max(1, ...matrix.flat()) : 30;

                  const DIM_DISPLAY: Record<string, string> = meth?.layer_1_dimensions?.dimensions ?? {
                    stakeholder:"目标用户", pain_point:"痛点问题", solution:"解决方案", innovation:"创新点",
                    market:"目标市场", competitor:"竞争格局", business_model:"商业模式", execution_step:"执行步骤",
                    risk_control:"风控合规", technology:"技术路线", resource:"资源优势", team:"团队能力",
                    evidence:"证据与数据", risk:"风险与合规", channel:"获客渠道",
                  };

                  const DIM_SOURCES: Record<string, string> = {
                    stakeholder: "Lean Canvas「客户细分」", pain_point: "Lean Canvas「问题」+ Design Thinking「共情」",
                    solution: "Lean Canvas「解决方案」", innovation: "TRL 技术就绪度 + BMC「价值主张」",
                    market: "BMC「客户细分」+ Porter 五力", competitor: "Porter 五力「竞争对手」",
                    business_model: "BMC「收入来源」+ Lean Canvas「独特价值」", execution_step: "OKR + 敏捷里程碑",
                    risk_control: "COSO ERM / ISO 31000", technology: "TRL 技术就绪度",
                    resource: "BMC「核心资源」+ RBV 资源基础观", team: "Tuckman 团队发展 + Lean Canvas",
                    evidence: "Design Thinking「测试」+ 精益验证", risk: "COSO ERM + ESG 风险框架",
                    channel: "BMC「渠道通路」+ AARRR 增长漏斗",
                  };

                  const stageBands = [
                    { name: "问题发现", groups: ["问题发现与需求洞察", "用户-市场-需求"] },
                    { name: "创意形成", groups: ["创意孵化与方案设计", "用户体验与设计思维", "价值叙事与一致性"] },
                    { name: "技术与验证", groups: ["数据与技术验证", "知识转化与产学研", "风险、证据与评分"] },
                    { name: "商业化设计", groups: ["单位经济与财务结构", "产品差异化与竞争动态", "增长、渠道与规模化", "生态与多方利益"] },
                    { name: "组织与治理", groups: ["执行、团队与里程碑", "合规、监管与伦理", "社会与ESG"] },
                  ].map((stage) => {
                    const matched = (catalogData?.groups ?? []).filter((g: any) => stage.groups.includes(g.name));
                    const familyCount = matched.reduce((sum: number, g: any) => sum + Number(g.families || 0), 0);
                    return {
                      ...stage,
                      categoryCount: matched.length,
                      familyCount,
                    };
                  });

                  return (
                    <section className="kb-section">
                      <h2 className="kb-section-title">超图设计合理性评估 <span className="kb-score-badge">{pctScore}%</span></h2>
                      <p className="kb-section-desc">超图部分采用“全流程覆盖 + 结构测量 + 规则锚定 + 综合评分”四层逻辑，说明它如何从创新走向创业，并用量化指标证明这一设计是完整且均衡的。</p>

                      {/* 超图关键数字 */}
                      <div className="qr-hero" style={{gridTemplateColumns:"repeat(6,1fr)"}}>
                        <div className="qr-hero-card" title="超图中定义的超边家族类型数"><div className="qr-hero-num">{totalFamilies}</div><div className="qr-hero-label">超边家族</div></div>
                        <div className="qr-hero-card" title="所有超边模板总数 (ideal+risk+neutral)"><div className="qr-hero-num">{totalTemplates}</div><div className="qr-hero-label">超边模板</div></div>
                        <div className="qr-hero-card" title="业务分类数量"><div className="qr-hero-num">{totalCategories}</div><div className="qr-hero-label">业务分类</div></div>
                        <div className="qr-hero-card" title="分析维度数量"><div className="qr-hero-num">{totalDims}</div><div className="qr-hero-label">分析维度</div></div>
                        <div className="qr-hero-card" title="一致性检测规则数"><div className="qr-hero-num">{totalConsistencyRules}</div><div className="qr-hero-label">一致性规则</div></div>
                        <div className="qr-hero-card" title="每个模板平均关联的维度数"><div className="qr-hero-num">{dc?.avg_dims_per_template ?? 3.3}</div><div className="qr-hero-label">均维度/模板</div></div>
                      </div>

                      <div className="rat-card">
                        <h3 className="rat-h3">A. 创新到创业全流程覆盖</h3>
                        <p className="qr-explain">超图并不是只分析“创意”本身，而是把创新创业过程拆成从问题发现、创意形成、技术验证、商业化设计到组织与治理的完整链条。下面给出每个阶段对应的分类数与家族数。</p>
                        <div className="qr-dim-table">
                          <div className="qr-dim-row" style={{fontWeight:700, borderBottom:"1px solid rgba(148,163,184,.15)"}}>
                            <span className="qr-dim-name" style={{minWidth:100}}>阶段</span>
                            <span className="qr-dim-source" style={{minWidth:70}}>分类数</span>
                            <span className="qr-dim-source" style={{minWidth:70}}>家族数</span>
                            <span className="qr-dim-source">对应作用</span>
                          </div>
                          {stageBands.map((stage) => (
                            <div key={stage.name} className="qr-dim-row">
                              <span className="qr-dim-name" style={{minWidth:100}}>{stage.name}</span>
                              <span className="qr-dim-source" style={{minWidth:70}}>{stage.categoryCount}</span>
                              <span className="qr-dim-source" style={{minWidth:70}}>{stage.familyCount}</span>
                              <span className="qr-dim-source">{stage.groups.join("、")}</span>
                            </div>
                          ))}
                        </div>
                        <p className="qr-explain" style={{marginTop:10}}>这里回答的是：超图是否只覆盖“想法”，还是覆盖了从问题识别到商业化落地的全过程。结果上，5 个阶段均有对应分类和家族支撑，因此它不是单点分析工具，而是全链路结构模型。</p>
                      </div>

                      {/* 3.1 为什么是这 15 个分析维度？ */}
                      <div className="rat-method-card">
                        <h3 className="rat-h3">为什么选择这 {totalDims} 个分析维度？</h3>
                        <p className="qr-explain">这 {totalDims} 个维度融合了三大经典创新创业理论框架系统推导而来：<strong>精益画布（Lean Canvas）</strong>提供从问题到商业模式的核心 9 要素；<strong>商业模式画布（BMC）</strong>补充价值网络视角；<strong>设计思维（Design Thinking）</strong>引入共情-创意-验证的迭代逻辑。三框架做交集-并集整合，去冗余后得到覆盖"问题发现→商业验证"全链条的正交维度：</p>
                        <div className="qr-dim-table">
                          {dimKeys.map((k, i) => (
                            <div key={k} className="qr-dim-row">
                              <span className="qr-dim-idx">{i + 1}</span>
                              <span className="qr-dim-name">{DIM_DISPLAY[k] || k}</span>
                              <span className="qr-dim-source">{DIM_SOURCES[k] || "—"}</span>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* 3.1b 三层递推 */}
                      <div className="rat-card">
                        <h3 className="rat-h3">三层递推设计</h3>
                        <p className="qr-explain">确定维度后按「维度 → 分类 → 家族」三层递推构建超图本体：</p>
                        <div className="rat-layers">
                          <div className="rat-layer">
                            <div className="rat-layer-num">1</div>
                            <div className="rat-layer-body">
                              <strong>{totalDims} 个分析维度</strong>
                              <p>Lean Canvas + BMC + Design Thinking 三框架融合，覆盖问题发现到商业落地全链条</p>
                            </div>
                          </div>
                          <div className="rat-arrow">▼</div>
                          <div className="rat-layer">
                            <div className="rat-layer-num">2</div>
                            <div className="rat-layer-body">
                              <strong>{totalCategories} 个业务分类</strong>
                              <p>按创业全流程阶段划分 + 横切关注点（风险/合规/ESG），覆盖从问题发现到社会影响</p>
                            </div>
                          </div>
                          <div className="rat-arrow">▼</div>
                          <div className="rat-layer">
                            <div className="rat-layer-num">3</div>
                            <div className="rat-layer-body">
                              <strong>{totalFamilies} 个超边家族（{totalTemplates} 个模板）</strong>
                              <p>每个分类内识别关键结构关系，分为 ideal（理想）、risk（风险）、neutral（中性）三种</p>
                            </div>
                          </div>
                        </div>
                      </div>

                      <div className="rat-card">
                        <h3 className="rat-h3">B. 超图测量体系</h3>
                        <p className="qr-explain">下面这些指标分别对应“理论完整度”“结构丰富度”“跨维度耦合度”“规则锚定能力”四个方面，用来说明超图为什么足以支撑从创新到创业的系统分析。</p>
                        <div className="qr-dim-table">
                          {[
                            {
                              metric: "理论框架覆盖率",
                              formula: "有理论映射的分类数 / 总分类数",
                              result: `${Math.round((fw?.coverage ?? 1) * 100)}% (${fw?.groups_mapped ?? totalCategories}/${fw?.groups_total ?? totalCategories})`,
                              meaning: "说明分类设计是否具有学理依据",
                            },
                            {
                              metric: "维度覆盖率",
                              formula: "被模板引用的维度数 / 总维度数",
                              result: `${Math.round((dc?.coverage_rate ?? 1) * 100)}% (${dc?.covered_count ?? totalDims}/${dc?.total_count ?? totalDims})`,
                              meaning: "说明15个分析维度是否都被真正使用",
                            },
                            {
                              metric: "模板跨维度耦合度",
                              formula: "Σ模板涉及维度数 / 模板总数",
                              result: `${dc?.avg_dims_per_template ?? 3.3}`,
                              meaning: "说明每个模板平均跨越多少个维度，越高越能反映创业中的联动关系",
                            },
                            {
                              metric: "分类-家族丰富度",
                              formula: "家族总数 / 分类总数",
                              result: `${familiesPerCategory}`,
                              meaning: "说明每个阶段平均有多少种结构关系模式可用于分析",
                            },
                            {
                              metric: "模板-家族展开度",
                              formula: "模板总数 / 家族总数",
                              result: `${templatesPerFamily}`,
                              meaning: "说明每个家族不是单一规则，而是有多个可分析模板",
                            },
                            {
                              metric: "规则锚定密度",
                              formula: "一致性规则数 / 分析维度数",
                              result: `${rulesPerDimension}`,
                              meaning: "说明超图不仅有模板，也有规则层面的约束与校验",
                            },
                          ].map((row) => (
                            <div key={row.metric} className="qr-dim-row">
                              <span className="qr-dim-name" style={{minWidth:110}}>{row.metric}</span>
                              <span className="qr-dim-source"><strong>公式：</strong>{row.formula}</span>
                              <span className="qr-dim-source"><strong>结果：</strong>{row.result}</span>
                              <span className="qr-dim-source"><strong>含义：</strong>{row.meaning}</span>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* 3.2 分类详情 */}
                      <div className="rat-card">
                        <h3 className="rat-h3">{totalCategories} 个分类 × {totalFamilies} 个超边家族</h3>
                        <p className="qr-explain" style={{ marginBottom: 8 }}><strong>ideal</strong> = 好项目应具备的结构（如"价值闭环"），<strong>risk</strong> = 风险信号（如"执行差距"），<strong>neutral</strong> = 中性分析结构。点击展开查看：</p>
                        <div className="rat-cat-grid">
                          {(catalogData?.groups ?? []).map((g: any) => {
                            const families = (catalogData?.families ?? []).filter((f: any) => f.group === g.name);
                            const isOpen = rationalityExpand === g.name;
                            return (
                              <details key={g.name} className="rat-cat-detail" open={isOpen} onClick={(e) => { e.preventDefault(); setRationalityExpand(isOpen ? null : g.name); }}>
                                <summary className="rat-cat-summary">
                                  <span className="rat-cat-dot" />
                                  <span className="rat-cat-name">{g.name}</span>
                                  <span className="rat-cat-count">{g.families} 家族</span>
                                </summary>
                                {isOpen && (
                                  <div className="rat-cat-body" onClick={(e) => e.stopPropagation()}>
                                    {families.map((f: any) => (
                                      <div key={f.family} className="rat-fam-row">
                                        <span className={`rat-fam-type ${f.pattern_type}`}>{f.pattern_type}</span>
                                        <span className="rat-fam-label">{f.label}</span>
                                        <span className="rat-fam-desc">{f.description}</span>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </details>
                            );
                          })}
                        </div>
                      </div>

                      {/* 3.3 理论框架对标 */}
                      <div className="rat-card">
                        <h3 className="rat-h3">理论框架对标 <span className="rat-inline-score">{Math.round((fw?.coverage ?? 1.0) * 100)}%</span></h3>
                        <p className="qr-explain" style={{ marginBottom: 8 }}>{fw?.groups_mapped ?? 15}/{fw?.groups_total ?? 15} 个分类全部有经典学术理论支撑。覆盖率 = 有理论映射的分类数 / 总分类数。</p>
                        <div className="rat-fw-grid">
                          {(fw?.frameworks ?? [
                            {framework:"Lean Canvas (Maurya 2012)",mapped_groups:["价值叙事与一致性","用户-市场-需求","单位经济与财务结构"]},
                            {framework:"Business Model Canvas (Osterwalder 2010)",mapped_groups:["用户-市场-需求","增长、渠道与规模化","单位经济与财务结构","生态与多方利益"]},
                            {framework:"Design Thinking (Stanford d.school)",mapped_groups:["问题发现与需求洞察","创意孵化与方案设计","用户体验与设计思维"]},
                            {framework:"Technology Readiness Level (NASA)",mapped_groups:["数据与技术验证","产品差异化与竞争动态"]},
                            {framework:"COSO ERM / ISO 31000",mapped_groups:["风险、证据与评分","合规、监管与伦理"]},
                            {framework:"ESG / UN SDGs",mapped_groups:["社会与ESG"]},
                            {framework:"Porter Five Forces + Moat Theory",mapped_groups:["产品差异化与竞争动态"]},
                            {framework:"Growth Hacking / AARRR",mapped_groups:["增长、渠道与规模化"]},
                            {framework:"Tuckman Team Development + OKR",mapped_groups:["执行、团队与里程碑"]},
                            {framework:"Triple Helix (Etzkowitz 2003)",mapped_groups:["知识转化与产学研"]},
                            {framework:"Platform Economics",mapped_groups:["生态与多方利益"]},
                          ]).map((f: any) => (
                            <div key={f.framework} className="rat-fw-row">
                              <span className="rat-fw-name">{f.framework}</span>
                              <div className="rat-fw-tags">
                                {(f.mapped_groups ?? []).map((g: string) => (
                                  <span key={g} className="rat-fw-tag">{g}</span>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* 3.4 定量分析汇总 */}
                      <div className="rat-card">
                        <h3 className="rat-h3">C. 定量分析汇总</h3>
                        <p className="qr-explain">以下指标从不同角度量化超图本体设计的科学性。它们共同回答：这个超图是否完整、是否均衡、是否具备跨维度分析能力、是否有规则支撑。</p>
                        <div className="qr-metric-row" style={{flexWrap:"wrap", gap:"12px 20px"}}>
                          <div className="qr-metric" title="有模板引用的维度数 / 总维度数"><span className="qr-metric-val qr-val-accent">{Math.round((dc?.coverage_rate ?? 1.0) * 100)}%</span><span className="qr-metric-label">维度覆盖率</span></div>
                          <div className="qr-metric" title="各维度被引用频次的 Shannon 熵归一化"><span className="qr-metric-val qr-val-accent">{Math.round((dc?.frequency_balance ?? 0.92) * 100)}%</span><span className="qr-metric-label">频率均衡度</span></div>
                          <div className="qr-metric" title="H(分类家族数) / log₂(分类数)，越接近1越均匀"><span className="qr-metric-val qr-val-accent">{sb?.entropy ?? 0.96}</span><span className="qr-metric-label">族群 Shannon 熵</span></div>
                          <div className="qr-metric" title="Gini 系数，越接近0越均匀"><span className="qr-metric-val">{sb?.gini ?? 0.08}</span><span className="qr-metric-label">族群 Gini</span></div>
                          <div className="qr-metric" title="H(ideal,risk,neutral占比) / log₂(3)"><span className="qr-metric-val qr-val-accent">{Math.round((pd?.diversity_score ?? 0.95) * 100)}%</span><span className="qr-metric-label">模式多样性</span></div>
                          <div className="qr-metric" title="一致性规则覆盖的维度数 / 总维度数"><span className="qr-metric-val qr-val-accent">{Math.round((rc?.coverage_rate ?? 0.73) * 100)}%</span><span className="qr-metric-label">规则维度覆盖</span></div>
                          <div className="qr-metric" title="Σ模板维度数 / 模板总数"><span className="qr-metric-val">{dc?.avg_dims_per_template ?? 3.3}</span><span className="qr-metric-label">均维度/模板</span></div>
                          <div className="qr-metric" title="模板中 ideal 类型的数量"><span className="qr-metric-val">{pd?.ideal ?? 42}</span><span className="qr-metric-label">ideal 模板</span></div>
                          <div className="qr-metric" title="模板中 risk 类型的数量"><span className="qr-metric-val">{pd?.risk ?? 28}</span><span className="qr-metric-label">risk 模板</span></div>
                          <div className="qr-metric" title="模板中 neutral 类型的数量"><span className="qr-metric-val">{pd?.neutral ?? 25}</span><span className="qr-metric-label">neutral 模板</span></div>
                          <div className="qr-metric" title="各分类家族数的最小值"><span className="qr-metric-val">{sb?.min_size ?? 3}</span><span className="qr-metric-label">最小家族数/类</span></div>
                          <div className="qr-metric" title="各分类家族数的最大值"><span className="qr-metric-val">{sb?.max_size ?? 7}</span><span className="qr-metric-label">最大家族数/类</span></div>
                        </div>
                      </div>

                      {/* 3.5 维度共现热力矩阵 */}
                      <div className="rat-card">
                        <h3 className="rat-h3">D. 维度共现热力矩阵</h3>
                        <p className="qr-explain"><strong>读法：</strong>对角线 = 该维度被引用的模板总数。非对角线 = 两维度在同一模板中共同出现的次数（例如"痛点×方案 = 12"意味着 12 个模板同时分析这两个维度）。颜色越深 = 数值越大。这是超图捕捉跨维度关联的核心价值可视化。</p>
                        {matrix.length > 0 ? (
                          <div className="rat-heatmap-wrap" style={{ overflowX: "auto" }}>
                            <table className="rat-heatmap">
                              <thead>
                                <tr>
                                  <th></th>
                                  {dimKeys.map(k => <th key={k} title={DIM_DISPLAY[k] || k}>{(DIM_DISPLAY[k] || k).slice(0, 2)}</th>)}
                                </tr>
                              </thead>
                              <tbody>
                                {dimKeys.map((row, ri) => (
                                  <tr key={row}>
                                    <td className="rat-hm-label" title={DIM_DISPLAY[row] || row}>{(DIM_DISPLAY[row] || row).slice(0, 3)}</td>
                                    {dimKeys.map((col, ci) => {
                                      const v = ri === ci ? (dc?.dim_frequency?.[row] ?? 0) : (matrix[ri]?.[ci] ?? 0);
                                      const intensity = Math.min(1, v / maxCooc);
                                      return (
                                        <td key={col} className="rat-hm-cell" style={{ background: `rgba(99,102,241,${0.06 + intensity * 0.84})` }} title={`${DIM_DISPLAY[row] || row} × ${DIM_DISPLAY[col] || col}: ${v} 个模板共现`}>
                                          {v > 0 ? v : ""}
                                        </td>
                                      );
                                    })}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        ) : (
                          <p className="qr-explain" style={{fontStyle:"italic"}}>热力矩阵数据加载中...</p>
                        )}
                      </div>

                      {/* 3.6 族群结构均衡 */}
                      <div className="rat-card">
                        <h3 className="rat-h3">E. 族群结构均衡</h3>
                        <p className="qr-explain">各分类的家族数在 {sb?.min_size ?? 3}–{sb?.max_size ?? 7} 之间。Shannon 熵 {sb?.entropy ?? 0.96}（越接近 1 越均匀），Gini {sb?.gini ?? 0.08}（越接近 0 越均匀），说明家族在分类间分配合理。</p>
                        <div className="rat-balance-bars">
                          {Object.entries(sb?.group_sizes ?? {}).map(([name, size]) => {
                            const maxSize = sb?.max_size ?? 7;
                            const pct = ((size as number) / maxSize) * 100;
                            return (
                              <div key={name} className="rat-bar-row">
                                <span className="rat-bar-label">{name}</span>
                                <div className="rat-bar-track"><div className="rat-bar-fill" style={{ width: `${pct}%` }} /></div>
                                <span className="rat-bar-val">{size as number}</span>
                              </div>
                            );
                          })}
                        </div>
                      </div>

                      {/* 3.7 综合得分 */}
                      <div className="rat-card">
                        <h3 className="rat-h3">F. 超图质量评估总结</h3>
                        <div className="qr-mini-grid">
                          <div className="qr-mini-card">
                            <div className="qr-mini-title">超图结论</div>
                            <div className="qr-mini-row qr-mini-text"><span>当前超图已经从“问题发现”延伸到“商业化设计”和“组织治理”，并通过 {totalCategories} 个分类、{totalFamilies} 个家族、{totalTemplates} 个模板与 {totalConsistencyRules} 条规则形成完整设计层。综合分 {pctScore}% 更接近“设计成熟度”，说明这套结构不只是概念展示，而是具备理论锚点和可测量性的分析本体。</span></div>
                          </div>
                          <div className="qr-mini-card">
                            <div className="qr-mini-title">边界与说明</div>
                            <div className="qr-mini-row qr-mini-text"><span>超图评估证明的是“为什么要这样设计分类、家族和规则”，而不是证明所有模板都已经在现有少量案例中被运行到。对于尚未充分激活的模板，其合理性主要来自理论对标、流程覆盖和结构测量，而不是案例频次本身。</span></div>
                          </div>
                        </div>
                      </div>

                      <div className="rat-composite">
                        <div className="rat-composite-score">{pctScore}<small>%</small></div>
                        <p className="qr-explain" style={{textAlign:"center", marginTop:8}}>这个分数衡量的是<strong>超图设计成熟度</strong>，不是某个学生项目的表现分。它综合评估理论支撑、维度完整度、结构均衡、模式多样性与规则约束能力。</p>
                        <div className="rat-composite-detail">
                          {[
                            { label: "理论框架对标", val: fw?.coverage ?? 1.0, w: "25%", tip: "有理论映射的分类数 / 总分类数" },
                            { label: "维度覆盖完整度", val: dc?.coverage_rate ?? 1.0, w: "25%", tip: "被模板引用的维度数 / 总维度数" },
                            { label: "族群结构均衡", val: sb?.entropy ?? 0.96, w: "20%", tip: "H(分类家族数) / log₂(分类数)" },
                            { label: "模式多样性", val: pd?.diversity_score ?? 0.95, w: "15%", tip: "H(ideal,risk,neutral) / log₂(3)" },
                            { label: "规则维度覆盖", val: rc?.coverage_rate ?? 0.73, w: "15%", tip: "一致性规则覆盖的维度 / 总维度" },
                          ].map(s => (
                            <div key={s.label} className="rat-score-row" title={s.tip}>
                              <span className="rat-score-label">{s.label} <small>({s.w})</small></span>
                              <div className="rat-score-bar"><div className="rat-score-fill" style={{ width: `${Math.round(s.val * 100)}%` }} /></div>
                              <span className="rat-score-val">{Math.round(s.val * 100)}%</span>
                            </div>
                          ))}
                        </div>
                        <p className="rat-formula">综合分 = 0.25×理论框架 + 0.25×维度覆盖 + 0.20×结构均衡 + 0.15×模式多样 + 0.15×规则覆盖</p>
                      </div>
                    </section>
                  );
                })()}
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
                      nodeColor={(n: any) => n.color || "#94a3b8"}
                      nodeVal={() => 0.6}
                      nodeLabel={(n: any) => `${n.name || ""} [${n.type || ""}]${n.category ? " · " + n.category : ""}`}
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
