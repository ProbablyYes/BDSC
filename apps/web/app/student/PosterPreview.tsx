import { useMemo, useState } from "react";

export type PosterSection = {
  id: string;
  title: string;
  bullets: string[];
  highlight?: boolean;
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
  export_hint?: string;
};

export function buildPosterPlainText(design: PosterDesign): string {
  const lines: string[] = [];
  lines.push(design.title || "项目海报");
  if (design.subtitle) lines.push(design.subtitle);
  lines.push("");
  for (const sec of design.sections || []) {
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
  tech_blue: { bg: "linear-gradient(135deg,#020617,#0f172a)", accent: "#38bdf8", text: "#e5f2ff", chip: "rgba(56,189,248,0.12)" },
  youthful_gradient: { bg: "linear-gradient(135deg,#4f46e5,#ec4899)", accent: "#fbbf24", text: "#fef9c3", chip: "rgba(251,191,36,0.14)" },
  minimal_black: { bg: "#0b0b0c", accent: "#f97316", text: "#f9fafb", chip: "rgba(249,115,22,0.16)" },
  default: { bg: "linear-gradient(135deg,#111827,#020617)", accent: "#22c55e", text: "#e5e7eb", chip: "rgba(34,197,94,0.16)" },
};

type Props = {
  design: PosterDesign;
  onChange?: (next: PosterDesign) => void;
};

export default function PosterPreview({ design, onChange }: Props) {
  const [copied, setCopied] = useState(false);

  const theme = useMemo(() => THEME_STYLES[design.theme] || THEME_STYLES.default, [design.theme]);
  const orientation = design.layout?.orientation === "landscape" ? "landscape" : "portrait";

  const sectionEntries = useMemo(
    () => (design.sections || []).map((sec, idx) => ({ sec, idx })),
    [design.sections],
  );
  const heroSections = sectionEntries.filter(({ sec }) => sec.highlight || sec.id === "hero");
  const normalSections = sectionEntries.filter(({ sec }) => !(sec.highlight || sec.id === "hero"));

  const handleTitleChange = (value: string) => {
    onChange?.({ ...design, title: value });
  };
  const handleSubtitleChange = (value: string) => {
    onChange?.({ ...design, subtitle: value });
  };
  const handleSectionTitleChange = (idx: number, value: string) => {
    const sections = [...(design.sections || [])];
    if (!sections[idx]) return;
    sections[idx] = { ...sections[idx], title: value };
    onChange?.({ ...design, sections });
  };
  const handleBulletChange = (sIdx: number, bIdx: number, value: string) => {
    const sections = [...(design.sections || [])];
    if (!sections[sIdx]) return;
    const bullets = [...(sections[sIdx].bullets || [])];
    bullets[bIdx] = value;
    sections[sIdx] = { ...sections[sIdx], bullets };
    onChange?.({ ...design, sections });
  };
  const handleAddBullet = (sIdx: number) => {
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

  const hint = design.export_hint || (orientation === "portrait" ? "建议：A3 竖版 / 1080x1920 竖屏" : "建议：A3 横版 / 1920x1080 大屏");

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
          <input
            value={sec.title}
            onChange={(e) => handleSectionTitleChange(idx, e.target.value)}
            placeholder={isHero ? "项目亮点 / 总览" : "分区标题"}
            style={{
              width: "100%",
              border: "none",
              outline: "none",
              background: "transparent",
              color: theme.accent,
              fontWeight: 700,
              fontSize: isHero ? 15 : 13,
              letterSpacing: 0.4,
            }}
          />
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
                <input
                  value={b}
                  onChange={(e) => handleBulletChange(idx, bi, e.target.value)}
                  style={{
                    width: "100%",
                    border: "none",
                    outline: "none",
                    background: "transparent",
                    color: "rgba(226,232,240,0.96)",
                    fontSize: 12,
                  }}
                />
              </li>
            ))}
          </ul>
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
        </div>
      </div>
    );
  };

  return (
    <div className="poster-preview-root">
      <div className="poster-toolbar">
        <span className="poster-toolbar-title">路演海报草稿</span>
        <div className="poster-toolbar-actions">
          <button type="button" className="poster-btn" onClick={handleCopyAll}>
            {copied ? "✓ 文案已复制" : "复制全部文案"}
          </button>
          <button
            type="button"
            className="poster-btn secondary"
            onClick={() => window.print()}
            title="使用浏览器打印为 PDF 或截图导出"
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
          borderRadius: 16,
          padding: 20,
          display: "flex",
          flexDirection: "column",
          gap: 16,
          boxShadow: "0 18px 40px rgba(15,23,42,0.85)",
          minHeight: 360,
          maxWidth: orientation === "portrait" ? 460 : 640,
          margin: "12px auto",
          aspectRatio: orientation === "portrait" ? "3 / 4" : "16 / 9",
          position: "relative",
          overflow: "hidden",
        }}
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
        {/* Header */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 12,
            borderBottom: "1px solid rgba(148,163,184,0.25)",
            paddingBottom: 10,
          }}
        >
          <div style={{ flex: 1 }}>
            <input
              value={design.title}
              onChange={(e) => handleTitleChange(e.target.value)}
              placeholder="项目海报主标题"
              style={{
                width: "100%",
                border: "none",
                outline: "none",
                background: "transparent",
                color: theme.text,
                fontSize: 26,
                fontWeight: 850,
                letterSpacing: 0.8,
                textShadow: "0 10px 25px rgba(15,23,42,0.9)",
              }}
            />
            <input
              value={design.subtitle}
              onChange={(e) => handleSubtitleChange(e.target.value)}
              placeholder="一句话电梯陈述（可编辑）"
              style={{
                width: "100%",
                marginTop: 6,
                border: "none",
                outline: "none",
                background: "transparent",
                color: "rgba(226,232,240,0.9)",
                fontSize: 13,
              }}
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
            {design.hero_image_url && (
              <div
                style={{
                  width: orientation === "portrait" ? 96 : 132,
                  aspectRatio: "4 / 3",
                  borderRadius: 12,
                  overflow: "hidden",
                  boxShadow: "0 10px 26px rgba(15,23,42,0.95)",
                  border: "1px solid rgba(148,163,184,0.7)",
                  background: "#020617",
                }}
              >
                <img
                  src={design.hero_image_url}
                  alt="海报插图"
                  style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
                />
              </div>
            )}
            <div
              style={{
                fontSize: 11,
                padding: "6px 10px",
                borderRadius: 999,
                background: theme.chip,
                color: theme.accent,
                whiteSpace: "nowrap",
              }}
            >
              {design.theme || "默认主题"}
            </div>
          </div>
        </div>

        {/* Sections */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 12,
            flex: 1,
            alignItems: "flex-start",
          }}
        >
          {heroSections.length > 0 && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 10 }}>
              {heroSections.map((entry) => renderSectionCard(entry, "hero"))}
            </div>
          )}
          {normalSections.length > 0 && (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: orientation === "portrait" ? "1.2fr 1.1fr" : "1.3fr 1.1fr",
                gap: 12,
              }}
            >
              {normalSections.map((entry) => renderSectionCard(entry, "normal"))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 4, fontSize: 11, color: "rgba(148,163,184,0.9)" }}>
          <span>{hint}</span>
          {design.layout?.grid && <span>布局: {design.layout.grid} · 强调区: {design.layout.accent_area || "自动"}</span>}
        </div>
      </div>
    </div>
  );
}
