// @ts-nocheck
import { useMemo, useRef, useState } from "react";

export type PosterSection = {
  id: string;
  title: string;
  bullets: string[];
  highlight?: boolean;
  // 语义标签：用于前端更精细地编排故事线/证据线；
  // 后端可以不提供，前端会通过标题关键词自动推断。
  kind?: "problem" | "solution" | "evidence" | "metric" | "scenario" | "cta" | "other";
};

export type PosterLayout = {
  orientation: "portrait" | "landscape";
  grid?: string | null;
  accent_area?: string | null;
};

export type PosterDesign = {
  title: string;
  subtitle: string;
  sections: PosterSection[];
  layout: PosterLayout;
  theme: string;
  image_prompts: string[];
  // 由后端视觉模型生成的主插图 URL，可选
  hero_image_url?: string;
  // 额外插图位（如用户场景、数据/奖项等的小图），按顺序展示
  gallery_image_urls?: string[];
  export_hint?: string;
};

function isHeroSection(sec: PosterSection | null | undefined): boolean {
  if (!sec) return false;
  return Boolean(sec.highlight) || sec.id === "hero";
}

function inferSectionKind(sec: PosterSection): PosterSection["kind"] {
  if (!sec) return "other";
  if (sec.kind) return sec.kind;
  const key = `${sec.id || ""} ${sec.title || ""}`.toLowerCase();
  if (/cta|call|行动|路演|活动|报名|参加/.test(key)) return "cta";
  if (/痛点|问题|困境|挑战|现状/.test(key)) return "problem";
  if (/方案|解决|设计|solution|product|产品|服务/.test(key)) return "solution";
  if (/数据|指标|kpi|证据|验证|成绩|奖项|获奖|收入|用户数|留存|转化|metric|evidence/.test(key)) return "metric";
  if (/场景|案例|故事|应用|使用|体验|scenario/.test(key)) return "scenario";
  return "other";
}

function sortSectionsForPlainText(sections: PosterSection[]): PosterSection[] {
  const heroes: PosterSection[] = [];
  const story: PosterSection[] = [];
  const proof: PosterSection[] = [];
  const ctas: PosterSection[] = [];
  const others: PosterSection[] = [];

  for (const sec of sections || []) {
    if (!sec) continue;
    if (isHeroSection(sec)) {
      heroes.push(sec);
      continue;
    }
    const kind = inferSectionKind(sec);
    if (kind === "cta") {
      ctas.push(sec);
    } else if (kind === "metric" || kind === "evidence") {
      proof.push(sec);
    } else if (kind === "problem" || kind === "solution" || kind === "scenario") {
      story.push(sec);
    } else {
      others.push(sec);
    }
  }

  // 结构化顺序：hero 概览 → 故事线 → 证据线 → CTA → 其他
  return [...heroes, ...story, ...proof, ...ctas, ...others];
}

export function buildPosterPlainText(design: PosterDesign): string {
  const lines: string[] = [];
  lines.push(design.title || "项目海报");
  if (design.subtitle) lines.push(design.subtitle);
  lines.push("");
  const ordered = sortSectionsForPlainText(design.sections || []);
  for (const sec of ordered) {
    if (!sec) continue;
    const title = sec.title || sec.id || "分区";
    lines.push(`## ${title}`);
    for (const b of sec.bullets || []) {
      const t = String(b || "").trim();
      if (!t) continue;
      lines.push(`- ${t}`);
    }
    lines.push("");
  }
  if (design.export_hint) {
    lines.push("[导出建议] " + design.export_hint);
  }
  return lines.join("\n").trim();
}

const THEME_STYLES: Record<string, { bg: string; accent: string; text: string; chip: string }> = {
  tech_blue: {
    bg: "linear-gradient(135deg,#020617,#0f172a)",
    accent: "#38bdf8",
    text: "#e5f2ff",
    chip: "rgba(56,189,248,0.12)",
  },
  youthful_gradient: {
    bg: "linear-gradient(135deg,#4f46e5,#ec4899)",
    accent: "#fbbf24",
    text: "#fef9c3",
    chip: "rgba(251,191,36,0.14)",
  },
  minimal_black: {
    bg: "#0b0b0c",
    accent: "#f97316",
    text: "#f9fafb",
    chip: "rgba(249,115,22,0.16)",
  },
  warm_orange: {
    bg: "linear-gradient(135deg,#7c2d12,#1c1917)",
    accent: "#fb923c",
    text: "#ffedd5",
    chip: "rgba(248,153,91,0.14)",
  },
  deep_navy: {
    bg: "linear-gradient(135deg,#020617,#020617)",
    accent: "#38bdf8",
    text: "#e5f2ff",
    chip: "rgba(56,189,248,0.16)",
  },
  green_growth: {
    bg: "linear-gradient(135deg,#022c22,#022c22)",
    accent: "#4ade80",
    text: "#dcfce7",
    chip: "rgba(74,222,128,0.14)",
  },
  default: {
    bg: "linear-gradient(135deg,#111827,#020617)",
    accent: "#22c55e",
    text: "#e5e7eb",
    chip: "rgba(34,197,94,0.16)",
  },
};

type Props = {
  design: PosterDesign;
  onChange?: (next: PosterDesign) => void;
  // view: 纯展示模式（适合学生端路演预览）；edit: 可编辑模式
  mode?: "view" | "edit";
};

export default function PosterPreview({ design, onChange, mode = "view" }: Props) {
  const [copied, setCopied] = useState(false);
  const posterRef = useRef<HTMLDivElement | null>(null);

  const theme = useMemo(() => THEME_STYLES[design.theme] || THEME_STYLES.default, [design.theme]);
  const orientation = design.layout?.orientation === "landscape" ? "landscape" : "portrait";
  const isEditable = mode === "edit" && !!onChange;

  const sectionEntries = useMemo(
    () => (design.sections || []).map((sec, idx) => ({ sec, idx })),
    [design.sections],
  );
  const heroSections = useMemo(
    () => sectionEntries.filter(({ sec }) => isHeroSection(sec)),
    [sectionEntries],
  );
  const nonHeroSections = useMemo(
    () => sectionEntries.filter(({ sec }) => !isHeroSection(sec)),
    [sectionEntries],
  );
  const ctaEntry = useMemo(
    () =>
      sectionEntries.find(({ sec }) => {
        const key = `${sec.id || ""} ${sec.title || ""}`.toLowerCase();
        return /cta|call|行动|路演|活动|报名|参加/.test(key);
      }) || null,
    [sectionEntries],
  );

  const storySections = useMemo(
    () =>
      nonHeroSections.filter(({ sec }) => {
        const kind = inferSectionKind(sec);
        if (kind === "metric" || kind === "evidence") return false;
        if (kind === "cta") return false;
        return true;
      }),
    [nonHeroSections],
  );

  const proofSections = useMemo(
    () =>
      nonHeroSections.filter(({ sec }) => {
        const kind = inferSectionKind(sec);
        return kind === "metric" || kind === "evidence";
      }),
    [nonHeroSections],
  );

  const handleTitleChange = (value: string) => {
    if (!isEditable) return;
    onChange?.({ ...design, title: value });
  };
  const handleSubtitleChange = (value: string) => {
    if (!isEditable) return;
    onChange?.({ ...design, subtitle: value });
  };
  const handleSectionTitleChange = (idx: number, value: string) => {
    if (!isEditable) return;
    const sections = [...(design.sections || [])];
    if (!sections[idx]) return;
    sections[idx] = { ...sections[idx], title: value };
    onChange?.({ ...design, sections });
  };
  const handleBulletChange = (sIdx: number, bIdx: number, value: string) => {
    if (!isEditable) return;
    const sections = [...(design.sections || [])];
    if (!sections[sIdx]) return;
    const bullets = [...(sections[sIdx].bullets || [])];
    bullets[bIdx] = value;
    sections[sIdx] = { ...sections[sIdx], bullets };
    onChange?.({ ...design, sections });
  };
  const handleAddBullet = (sIdx: number) => {
    if (!isEditable) return;
    const sections = [...(design.sections || [])];
    if (!sections[sIdx]) return;
    const bullets = [...(sections[sIdx].bullets || [])];
    bullets.push("新要点（双击编辑）");
    sections[sIdx] = { ...sections[sIdx], bullets };
    onChange?.({ ...design, sections });
  };

  const handleCopyAll = async () => {
    try {
      const text = buildPosterPlainText(design);
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };

  const handlePrintPoster = () => {
    if (typeof window === "undefined") return;

    const posterEl = posterRef.current as HTMLElement | null;
    if (!posterEl) {
      // 兜底：拿不到海报节点时退回整页打印
      window.print();
      return;
    }

    const printWindow = window.open("", "_blank", "width=1200,height=800");
    if (!printWindow) return;

    const doc = printWindow.document;

    // 克隆一份海报节点，仅去掉阴影/圆角，保持原有文字与图片比例
    const clone = posterEl.cloneNode(true) as HTMLElement;
    clone.style.margin = "0 auto";
    clone.style.boxShadow = "none";
    clone.style.borderRadius = "0";

    const posterHTML = clone.outerHTML;
    doc.open();
    doc.write(`<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>${(design.title || "项目海报").replace(/</g, "&lt;").replace(/>/g, "&gt;")}</title>
    <style>
      @page {
        size: A3 portrait;
        margin: 10mm;
      }
      html, body {
        margin: 0;
        padding: 0;
        width: 100%;
        height: 100%;
        background: #020617;
      }
      body {
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .poster-wrapper {
        max-width: 100%;
      }
    </style>
  </head>
  <body>
    <div class="poster-wrapper">${posterHTML}</div>
  </body>
</html>`);
    doc.close();

    // 等待新窗口完成渲染后再触发打印，保证整张海报被送入打印
    printWindow.focus();
    printWindow.onload = () => {
      try {
        printWindow.focus();
        printWindow.print();
      } finally {
        printWindow.close();
      }
    };
  };

  const hint = design.export_hint || (orientation === "portrait" ? "建议：A3 竖版 / 1080x1920 竖屏" : "建议：A3 横版 / 1920x1080 大屏");

  const renderHighlightedBullet = (text: string, isHero: boolean) => {
    const raw = String(text || "").trim();
    if (!raw) return null;
    const nodes: any[] = [];
    const re = /(\d+(?:\.\d+)?\s*%|\d+(?:\.\d+)?\s*倍|\d+(?:\.\d+)?\s*[万千万亿]?\s*(?:人|用户|客户|台|次|单|家|所)|Top\s*\d+|No\.?\s*\d+)/gi;
    let last = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(raw)) !== null) {
      if (m.index > last) {
        nodes.push(raw.slice(last, m.index));
      }
      const val = m[0];
      nodes.push(
        <span
          key={`${m.index}-${val}`}
          className={isHero ? "poster-metric poster-metric-hero" : "poster-metric"}
        >
          {val}
        </span>,
      );
      last = m.index + val.length;
    }
    if (last < raw.length) nodes.push(raw.slice(last));
    return nodes;
  };

  const imageSlots = useMemo(() => {
    const slots: string[] = [];
    if (design.hero_image_url) slots.push(design.hero_image_url);
    const galleries = design.gallery_image_urls || [];
    for (const url of galleries) {
      if (url && slots.length < 3 && !slots.includes(url)) slots.push(url);
    }
    if (slots.length === 0) return [];
    while (slots.length < 3) {
      slots.push(slots[0]);
    }
    return slots.slice(0, 3);
  }, [design.hero_image_url, design.gallery_image_urls]);

  const renderSectionCard = (entry: { sec: PosterSection; idx: number }, variant: "hero" | "normal") => {
    const { sec, idx } = entry;
    const isHero = variant === "hero";
    return (
      <div
        key={sec.id || idx}
        style={{
          background: isHero
            ? "radial-gradient(circle at 0% 0%, rgba(56,189,248,0.45), rgba(15,23,42,0.95))"
            : "rgba(15,23,42,0.78)",
          borderRadius: isHero ? 14 : 12,
          border: `1px solid ${isHero ? theme.accent : "rgba(148,163,184,0.45)"}`,
          boxShadow: isHero ? "0 16px 40px rgba(15,23,42,0.85)" : "0 8px 22px rgba(15,23,42,0.7)",
          padding: isHero ? 14 : 10,
          display: "flex",
          flexDirection: "column",
          gap: 8,
          position: "relative",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: 0,
            pointerEvents: "none",
            opacity: isHero ? 0.18 : 0.08,
            backgroundImage: "radial-gradient(circle at 0 0, rgba(148,163,184,0.6) 0, transparent 55%), radial-gradient(circle at 100% 100%, rgba(56,189,248,0.5) 0, transparent 60%)",
          }}
        />
        <div style={{ position: "relative", zIndex: 1, display: "flex", alignItems: "center", gap: 6 }}>
          <div
            style={{
              width: 4,
              alignSelf: "stretch",
              borderRadius: 999,
              background: isHero ? theme.accent : "rgba(148,163,184,0.7)",
            }}
          />
          {isEditable ? (
            <input
              value={sec.title}
              onChange={(e) => handleSectionTitleChange(idx, e.target.value)}
              placeholder={isHero ? "项目亮点 / 总览" : "分区标题"}
              style={{
                width: "100%",
                border: "none",
                outline: "none",
                background: "transparent",
                color: "var(--poster-accent-color)",
              }}
            />
          ) : (
            <div className={isHero ? "poster-section-title poster-section-title-hero" : "poster-section-title"}>
              {sec.title || (isHero ? "项目亮点 / 总览" : "分区标题")}
            </div>
          )}
        </div>
        <div style={{ position: "relative", zIndex: 1 }}>
          <ul
            style={{
              listStyle: "none",
              padding: 0,
              margin: 0,
              display: "flex",
              flexDirection: "column",
              gap: 5,
            }}
          >
            {(sec.bullets || []).map((b, bi) => (
              <li
                key={bi}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 6,
                  padding: "4px 8px",
                  borderRadius: 999,
                  background: "rgba(15,23,42,0.75)",
                  border: "1px solid rgba(51,65,85,0.9)",
                }}
              >
                <span
                  style={{
                    width: 6,
                    height: 6,
                    marginTop: 4,
                    borderRadius: "50%",
                    background: isHero ? theme.accent : "rgba(148,163,184,0.9)",
                    boxShadow: isHero ? `0 0 0 3px ${theme.accent}33` : "none",
                    flexShrink: 0,
                  }}
                />
                {isEditable ? (
                  <input
                    value={b}
                    onChange={(e) => handleBulletChange(idx, bi, e.target.value)}
                    style={{
                      width: "100%",
                      border: "none",
                      outline: "none",
                      background: "transparent",
                      color: "rgba(226,232,240,0.96)",
                    }}
                  />
                ) : (
                  <span className="poster-body">
                    {renderHighlightedBullet(b, isHero)}
                  </span>
                )}
              </li>
            ))}
          </ul>
          {isEditable && (
            <button
              type="button"
              onClick={() => handleAddBullet(idx)}
              style={{
                marginTop: 5,
                alignSelf: "flex-start",
                border: "none",
                background: "transparent",
                color: "rgba(148,163,184,0.9)",
                fontSize: 11,
                cursor: "pointer",
              }}
            >
              + 添加要点
            </button>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="poster-preview-root">
      <div className="poster-toolbar">
        <span className="poster-toolbar-title">大赛展演海报</span>
        <div className="poster-toolbar-actions">
          <button type="button" className="poster-btn" onClick={handleCopyAll}>
            {copied ? "✓ 文案已复制" : "复制全部文案"}
          </button>
          <button
            type="button"
            className="poster-btn secondary"
            onClick={handlePrintPoster}
            title="仅导出当前海报为 PDF 或打印"
          >
            打印/导出
          </button>
        </div>
      </div>

      <div
        className={`poster-canvas ${orientation}`}
        style={{
          background: theme.bg,
          color: theme.text,
          borderRadius: 24,
          padding: 24,
          display: "flex",
          flexDirection: "column",
          gap: 16,
          boxShadow: "0 24px 60px rgba(15,23,42,0.9)",
          minHeight: 320,
          width: "100%",
          maxWidth: orientation === "portrait" ? 540 : 820,
          margin: "12px auto",
          position: "relative",
          overflow: "hidden",
          // 供排版与数字高亮复用的主题色变量
          "--poster-accent-color": theme.accent,
        }}
        ref={posterRef}
      >
        <div
          style={{
            position: "absolute",
            inset: 0,
            backgroundImage:
              "linear-gradient(135deg, rgba(148,163,184,0.16) 1px, transparent 1px), linear-gradient(225deg, rgba(30,64,175,0.2) 1px, transparent 1px)",
            backgroundSize: "18px 18px",
            opacity: 0.25,
            mixBlendMode: "soft-light",
            pointerEvents: "none",
          }}
        />
        <div
          className={`poster-main-grid ${orientation === "portrait" ? "poster-portrait" : "poster-landscape"}`}
          style={{
            position: "relative",
            zIndex: 1,
          }}
        >
          {/* 标题 + Slogan */}
          <div className="poster-title-block">
            <div style={{ minWidth: 0 }}>
              {isEditable ? (
                <input
                  value={design.title}
                  onChange={(e) => handleTitleChange(e.target.value)}
                  placeholder="项目海报主标题"
                  className="poster-title-input"
                />
              ) : (
                <div className="poster-title">
                  {design.title || "项目海报主标题"}
                </div>
              )}
              {isEditable ? (
                <input
                  value={design.subtitle}
                  onChange={(e) => handleSubtitleChange(e.target.value)}
                  placeholder="一句话电梯陈述（可编辑）"
                  className="poster-subtitle-input"
                />
              ) : (
                <div className="poster-subtitle">
                  {design.subtitle || "一句话电梯陈述"}
                </div>
              )}
            </div>
          </div>

          {/* Hero 概览：项目亮点 / 总览 */}
          {heroSections.length > 0 && (
            <div className="poster-hero-block">
              <div className="poster-hero-grid">
                {heroSections.map((entry) => renderSectionCard(entry, "hero"))}
              </div>
            </div>
          )}

          {/* 故事线：痛点 / 方案 / 路径等 */}
          {storySections.length > 0 && (
            <div className="poster-story-block">
              <div className="poster-story-grid">
                {storySections.map((entry) => renderSectionCard(entry, "normal"))}
              </div>
            </div>
          )}

          {/* 证据线：数据 / 奖项 / 评语等 */}
          {proofSections.length > 0 && (
            <div className="poster-proof-block">
              <div className="poster-proof-grid">
                {proofSections.map((entry) => renderSectionCard(entry, "normal"))}
              </div>
            </div>
          )}

          {/* 右侧媒体列：主图 + 场景图 + 数据图 */}
          {imageSlots.length > 0 && (
            <div className="poster-media-rail">
              {imageSlots.map((url, idx) => (
                <div key={idx} className="poster-media-item">
                  <img src={url} alt={`海报插图 ${idx + 1}`} className="poster-media-img" />
                </div>
              ))}
            </div>
          )}

          {/* CTA + 导出提示：跨整行的收尾带 */}
          <div className="poster-cta-block">
            {ctaEntry && (
              <div className="poster-cta-band">
                <span className="poster-cta-label">路演信息</span>
                <span className="poster-cta-text">
                  {ctaEntry.sec.bullets?.[0] || ctaEntry.sec.title || ""}
                </span>
              </div>
            )}
            <div className="poster-footer">
              <span className="poster-footer-hint">{hint}</span>
              {design.layout?.grid && (
                <span className="poster-footer-layout">
                  布局: {design.layout.grid} · 强调区: {design.layout.accent_area || "自动"}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
