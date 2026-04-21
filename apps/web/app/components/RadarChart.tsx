"use client";
import { useState } from "react";

export type RadarItem = {
  label: string;
  value: number;
  max: number;
  /** 历史基线（可选，用于叠加对比轮廓） */
  baseline?: number;
  /** 附加元数据，点击回调会原样透传 */
  meta?: any;
};

export interface RadarChartProps {
  data: RadarItem[];
  size?: number;
  /** 是否显示叠加历史均值轮廓 */
  showBaseline?: boolean;
  /** 顶点点击回调（传入 item 与索引） */
  onVertexClick?: (item: RadarItem, index: number) => void;
  /** 顶点渲染后缀（如得分 badge） */
  vertexBadge?: (item: RadarItem, index: number) => React.ReactNode;
  /** 主色 */
  accent?: string;
  /** 基线色 */
  baselineColor?: string;
}

function levelColor(value: number, max: number): string {
  if (max <= 0) return "#94a3b8";
  const ratio = value / max;
  if (ratio >= 0.7) return "#22c55e";
  if (ratio >= 0.5) return "#eab308";
  return "#ef4444";
}

/**
 * 轻量零依赖雷达图，支持：
 * - 5/10 刻度 + 自适应轴
 * - 主轮廓 + 可选历史均值轮廓叠加
 * - 顶点可点击（圆点 & 标签均可触发）
 * - 顶点分数徽标，按分段着色
 */
export function RadarChart({
  data,
  size = 260,
  showBaseline = true,
  onVertexClick,
  vertexBadge,
  accent = "var(--accent)",
  baselineColor = "rgba(148,163,184,0.55)",
}: RadarChartProps) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const n = data.length;
  if (n < 3) return null;
  const cx = size / 2;
  const cy = size / 2;
  const r = size * 0.34;
  const step = (2 * Math.PI) / n;
  const pt = (i: number, ratio: number) => ({
    x: cx + r * ratio * Math.cos(step * i - Math.PI / 2),
    y: cy + r * ratio * Math.sin(step * i - Math.PI / 2),
  });

  const gridLevels = [0.25, 0.5, 0.75, 1];
  const mainPoly = data
    .map((d, i) => {
      const p = pt(i, d.max > 0 ? Math.min(d.value / d.max, 1) : 0);
      return `${p.x},${p.y}`;
    })
    .join(" ");
  const baselinePoly = showBaseline
    ? data
        .map((d, i) => {
          const base = typeof d.baseline === "number" ? d.baseline : null;
          if (base === null || d.max <= 0) return null;
          const p = pt(i, Math.min(base / d.max, 1));
          return `${p.x},${p.y}`;
        })
        .filter(Boolean)
        .join(" ")
    : "";
  const hasBaseline = Boolean(baselinePoly) && baselinePoly.split(" ").length === n;

  return (
    <div className="radar-chart-wrap" style={{ position: "relative", width: size, margin: "0 auto" }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ display: "block", overflow: "visible" }}>
        {/* 栅格多边形 */}
        {gridLevels.map((lv) => (
          <polygon
            key={lv}
            points={data
              .map((_, i) => {
                const p = pt(i, lv);
                return `${p.x},${p.y}`;
              })
              .join(" ")}
            fill="none"
            stroke="var(--border)"
            strokeWidth={lv === 1 ? 1.2 : 1}
            opacity={lv === 1 ? 0.65 : 0.3}
          />
        ))}
        {/* 轴线 */}
        {data.map((_, i) => {
          const p = pt(i, 1);
          return (
            <line
              key={`axis-${i}`}
              x1={cx}
              y1={cy}
              x2={p.x}
              y2={p.y}
              stroke="var(--border)"
              strokeWidth="1"
              opacity={0.3}
            />
          );
        })}
        {/* 中值刻度（0.5） */}
        <text
          x={cx + 2}
          y={cy - r * 0.5 - 2}
          fill="var(--text-muted)"
          fontSize="8"
          opacity="0.6"
        >
          50%
        </text>
        {/* 历史基线轮廓 */}
        {hasBaseline && (
          <polygon
            points={baselinePoly}
            fill="rgba(148,163,184,0.12)"
            stroke={baselineColor}
            strokeWidth="1.2"
            strokeDasharray="4 3"
            strokeLinejoin="round"
          />
        )}
        {/* 主轮廓 */}
        <polygon
          points={mainPoly}
          fill="rgba(107,138,255,0.2)"
          stroke={accent}
          strokeWidth="2"
          strokeLinejoin="round"
        />
        {/* 顶点圆点 */}
        {data.map((d, i) => {
          const p = pt(i, d.max > 0 ? Math.min(d.value / d.max, 1) : 0);
          const col = levelColor(d.value, d.max);
          const isHover = hoverIdx === i;
          return (
            <g key={`pt-${i}`}>
              <circle
                cx={p.x}
                cy={p.y}
                r={isHover ? 6.5 : 4.5}
                fill={col}
                stroke="var(--bg-primary)"
                strokeWidth="2"
                style={{
                  cursor: onVertexClick ? "pointer" : "default",
                  transition: "r 0.18s ease, filter 0.18s ease",
                  filter: isHover ? `drop-shadow(0 0 6px ${col})` : "none",
                }}
                onMouseEnter={() => setHoverIdx(i)}
                onMouseLeave={() => setHoverIdx(null)}
                onClick={() => onVertexClick?.(d, i)}
              />
            </g>
          );
        })}
        {/* 标签 */}
        {data.map((d, i) => {
          const p = pt(i, 1.28);
          const col = levelColor(d.value, d.max);
          return (
            <g
              key={`lbl-${i}`}
              style={{ cursor: onVertexClick ? "pointer" : "default" }}
              onClick={() => onVertexClick?.(d, i)}
              onMouseEnter={() => setHoverIdx(i)}
              onMouseLeave={() => setHoverIdx(null)}
            >
              <text
                x={p.x}
                y={p.y - 4}
                textAnchor="middle"
                dominantBaseline="central"
                fill="var(--text-secondary)"
                fontSize="10.5"
                fontWeight="600"
              >
                {d.label}
              </text>
              <text
                x={p.x}
                y={p.y + 8}
                textAnchor="middle"
                dominantBaseline="central"
                fill={col}
                fontSize="10"
                fontWeight="700"
              >
                {d.value.toFixed(1)}
              </text>
            </g>
          );
        })}
      </svg>
      {/* 图例 */}
      {hasBaseline && (
        <div
          className="radar-legend"
          style={{ display: "flex", gap: 12, justifyContent: "center", marginTop: 4, fontSize: 10, color: "var(--text-muted)" }}
        >
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <span style={{ width: 10, height: 2, background: accent, display: "inline-block" }} /> 当前
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <span style={{ width: 10, height: 2, background: baselineColor, display: "inline-block", borderTop: `1px dashed ${baselineColor}` }} /> 历史均值
          </span>
        </div>
      )}
      {/* 可选顶点 Badge 渲染器 */}
      {vertexBadge &&
        data.map((d, i) => {
          const p = pt(i, d.max > 0 ? Math.min(d.value / d.max, 1) : 0);
          const node = vertexBadge(d, i);
          if (!node) return null;
          return (
            <div
              key={`vb-${i}`}
              style={{ position: "absolute", left: p.x - 20, top: p.y + 6, width: 40, textAlign: "center", pointerEvents: "none" }}
            >
              {node}
            </div>
          );
        })}
    </div>
  );
}

export default RadarChart;
