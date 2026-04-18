"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
};

type Plan = {
  plan_id: string;
  title?: string;
  cover_info?: Record<string, any>;
  knowledge_base?: Record<string, any>;
  sections?: Section[];
  updated_at?: string;
};

type Comment = {
  comment_id: string;
  section_id: string;
  teacher_id: string;
  teacher_name?: string;
  quote: string;
  position: number;
  length: number;
  annotation_type: "suggestion" | "issue" | "praise";
  content: string;
  status: "open" | "resolved";
  created_at: string;
  updated_at?: string;
};

const ANNOTATION_LABEL: Record<string, string> = {
  suggestion: "建议",
  issue: "问题",
  praise: "肯定",
};

export default function BusinessPlanAnnotatePage() {
  const params = useParams<{ planId: string }>();
  const searchParams = useSearchParams();
  const planId = params?.planId ?? "";
  const teacherId = searchParams?.get("teacher_id") ?? "";
  const teacherName = searchParams?.get("teacher_name") ?? "";

  const [plan, setPlan] = useState<Plan | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");

  // 选区状态
  const [selection, setSelection] = useState<{
    quote: string;
    position: number;
    length: number;
    section_id: string;
    rect?: { top: number; left: number };
  } | null>(null);
  const [draftContent, setDraftContent] = useState("");
  const [draftType, setDraftType] = useState<"suggestion" | "issue" | "praise">("suggestion");
  const [submitting, setSubmitting] = useState(false);

  const [filterStatus, setFilterStatus] = useState<"all" | "open" | "resolved">("open");
  const rootRef = useRef<HTMLDivElement>(null);

  // ── 数据加载 ─────────────────────────────────────────────────
  useEffect(() => {
    if (!planId) return;
    (async () => {
      try {
        const [planResp, cmtResp] = await Promise.all([
          fetch(`${API_BASE}/api/business-plan/${encodeURIComponent(planId)}`),
          fetch(`${API_BASE}/api/business-plan/${encodeURIComponent(planId)}/comments`),
        ]);
        if (!planResp.ok) throw new Error(`HTTP ${planResp.status}`);
        const planData = await planResp.json();
        if (!planData?.plan) throw new Error("未找到计划书");
        setPlan(planData.plan);
        const cmtData = await cmtResp.json();
        if (Array.isArray(cmtData?.comments)) setComments(cmtData.comments);
      } catch (err: any) {
        setError(err?.message || "加载失败");
      } finally {
        setLoading(false);
      }
    })();
  }, [planId]);

  const flashToast = useCallback((msg: string, ms = 2600) => {
    setToast(msg);
    setTimeout(() => setToast(""), ms);
  }, []);

  // ── 选区监听 ─────────────────────────────────────────────────
  const handleMouseUp = useCallback(() => {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) {
      setSelection(null);
      return;
    }
    const text = sel.toString().trim();
    if (text.length < 2) {
      setSelection(null);
      return;
    }
    const range = sel.getRangeAt(0);
    let node: Node | null = range.commonAncestorContainer;
    if (node.nodeType === Node.TEXT_NODE) node = node.parentElement;
    let sectionEl: HTMLElement | null = null;
    while (node && node instanceof HTMLElement) {
      if (node.dataset?.sectionId) {
        sectionEl = node;
        break;
      }
      node = node.parentElement;
    }
    if (!sectionEl) {
      setSelection(null);
      return;
    }
    const sectionId = sectionEl.dataset.sectionId || "";
    const section = plan?.sections?.find((s) => s.section_id === sectionId);
    const sectionContent = (section?.user_edit && section.user_edit.trim()) || section?.content || "";
    const position = sectionContent.indexOf(text);
    const rect = range.getBoundingClientRect();
    setSelection({
      quote: text,
      position: position >= 0 ? position : 0,
      length: text.length,
      section_id: sectionId,
      rect: { top: rect.bottom + window.scrollY + 6, left: rect.left + window.scrollX },
    });
  }, [plan]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    root.addEventListener("mouseup", handleMouseUp);
    return () => root.removeEventListener("mouseup", handleMouseUp);
  }, [handleMouseUp]);

  // ── 提交批注 ─────────────────────────────────────────────────
  async function submitComment() {
    if (!selection || !draftContent.trim() || !planId) return;
    setSubmitting(true);
    try {
      const resp = await fetch(`${API_BASE}/api/business-plan/${encodeURIComponent(planId)}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          section_id: selection.section_id,
          teacher_id: teacherId,
          teacher_name: teacherName,
          quote: selection.quote,
          position: selection.position,
          length: selection.length,
          annotation_type: draftType,
          content: draftContent.trim(),
        }),
      });
      const data = await resp.json();
      if (data?.status === "ok" && data.comment) {
        setComments((cs) => [...cs, data.comment]);
        setSelection(null);
        setDraftContent("");
        window.getSelection()?.removeAllRanges();
        flashToast("批注已保存");
      } else {
        flashToast("保存失败：" + (data?.status || "未知错误"));
      }
    } catch (err: any) {
      flashToast("保存失败：" + (err?.message || ""));
    } finally {
      setSubmitting(false);
    }
  }

  async function updateComment(id: string, patch: Partial<Comment>) {
    try {
      const resp = await fetch(`${API_BASE}/api/business-plan/${encodeURIComponent(planId)}/comments/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      const data = await resp.json();
      if (data?.status === "ok" && data.comment) {
        setComments((cs) => cs.map((c) => (c.comment_id === id ? data.comment : c)));
      }
    } catch {
      flashToast("更新失败");
    }
  }

  async function deleteComment(id: string) {
    if (!window.confirm("确认删除该批注？")) return;
    try {
      await fetch(`${API_BASE}/api/business-plan/${encodeURIComponent(planId)}/comments/${encodeURIComponent(id)}`, {
        method: "DELETE",
      });
      setComments((cs) => cs.filter((c) => c.comment_id !== id));
      flashToast("已删除");
    } catch {
      flashToast("删除失败");
    }
  }

  // ── 把批注注入到渲染后 DOM ──────────────────────────────────
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    // 清理旧的 mark
    root.querySelectorAll("mark.bp-tch-mark").forEach((el) => {
      const parent = el.parentNode;
      if (!parent) return;
      while (el.firstChild) parent.insertBefore(el.firstChild, el);
      parent.removeChild(el);
      parent.normalize();
    });

    // 每章节注入自己的批注
    const sectionEls = root.querySelectorAll<HTMLElement>("[data-section-id]");
    const orphanBySection: Record<string, Comment[]> = {};
    sectionEls.forEach((secEl) => {
      const sid = secEl.dataset.sectionId || "";
      const cmts = comments.filter((c) => c.section_id === sid && c.status === "open");
      cmts.forEach((c) => {
        if (!c.quote) return;
        const ok = wrapQuoteInElement(secEl, c.quote, c);
        if (!ok) {
          orphanBySection[sid] = orphanBySection[sid] || [];
          orphanBySection[sid].push(c);
        }
      });
      // orphan 小条
      secEl.querySelectorAll(".bp-tch-orphans").forEach((el) => el.remove());
      const orphans = orphanBySection[sid] || [];
      if (orphans.length) {
        const box = document.createElement("div");
        box.className = "bp-tch-orphans";
        box.innerHTML = `<b>位置已变动的教师批注（${orphans.length}）：</b>` +
          orphans.map((c) => `<div>· <em>"${escapeHtml(c.quote.slice(0, 28))}${c.quote.length > 28 ? "…" : ""}"</em> → ${escapeHtml(c.content)}</div>`).join("");
        const h = secEl.querySelector("h2");
        if (h && h.parentElement === secEl) {
          secEl.insertBefore(box, h.nextSibling);
        } else {
          secEl.insertBefore(box, secEl.firstChild);
        }
      }
    });
  }, [comments, plan]);

  // ── 派生数据 ─────────────────────────────────────────────────
  const sectionTitleMap = useMemo(() => {
    const m: Record<string, string> = {};
    (plan?.sections || []).forEach((s) => {
      m[s.section_id] = s.display_title || s.title || s.section_id;
    });
    return m;
  }, [plan]);

  const groupedComments = useMemo(() => {
    const g: Record<string, Comment[]> = {};
    const filtered = comments.filter((c) => {
      if (filterStatus === "all") return true;
      return (c.status || "open") === filterStatus;
    });
    filtered.forEach((c) => {
      const sid = c.section_id || "_";
      (g[sid] = g[sid] || []).push(c);
    });
    // 每组按 position
    Object.values(g).forEach((arr) => arr.sort((a, b) => (a.position || 0) - (b.position || 0)));
    return g;
  }, [comments, filterStatus]);

  const totalOpen = useMemo(() => comments.filter((c) => (c.status || "open") === "open").length, [comments]);

  if (loading) return <div className="bp-print-msg">正在加载计划书…</div>;
  if (error || !plan) return <div className="bp-print-msg bp-print-err">加载失败：{error || "计划书不存在"}</div>;

  const cover = plan.cover_info || {};
  const title = plan.title || (cover.project_name as string) || "商业计划书";
  const sections = plan.sections || [];

  return (
    <div className="bp-annot-root">
      {/* 顶栏 */}
      <div className="bp-annot-toolbar">
        <a href="/teacher" className="bp-annot-back">← 返回教师端</a>
        <div className="bp-annot-title">
          <b>{title}</b>
          <span className="bp-annot-mode">划线批注模式</span>
        </div>
        <div className="bp-annot-me">
          {teacherName || teacherId || "未识别教师"} · 未解决 {totalOpen}
        </div>
      </div>

      {/* 主体：左正文 + 右批注面板 */}
      <div className="bp-annot-layout">
        <div className="bp-annot-content" ref={rootRef}>
          <section className="bp-print-cover">
            <div className="bp-print-accent-tag">商业计划书 · 教师批注</div>
            <h1 className="bp-print-cover-title">{title}</h1>
          </section>

          {sections.map((s, idx) => (
            <section
              key={s.section_id}
              className="bp-print-section"
              data-section-id={s.section_id}
            >
              <h2 className="bp-print-h1">
                <span className="bp-print-h1-num">第 {idx + 1} 章</span>
                <span className="bp-print-h1-title">{s.display_title || s.title}</span>
              </h2>
              <div className="bp-print-body">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {(s.user_edit && s.user_edit.trim()) || s.content || ""}
                </ReactMarkdown>
              </div>
            </section>
          ))}
        </div>

        {/* 右侧批注面板 */}
        <aside className="bp-annot-panel">
          <div className="bp-annot-panel-head">
            <b>批注汇总 · {comments.length}</b>
            <div className="bp-annot-filter">
              {(["open", "resolved", "all"] as const).map((k) => (
                <button
                  key={k}
                  className={filterStatus === k ? "is-on" : ""}
                  onClick={() => setFilterStatus(k)}
                >{k === "open" ? "未解决" : k === "resolved" ? "已解决" : "全部"}</button>
              ))}
            </div>
          </div>
          <div className="bp-annot-panel-body">
            {Object.keys(groupedComments).length === 0 && (
              <div className="bp-annot-empty">在左侧选中文本即可添加划线批注。</div>
            )}
            {sections.map((s) => {
              const list = groupedComments[s.section_id];
              if (!list || list.length === 0) return null;
              return (
                <div key={s.section_id} className="bp-annot-group">
                  <div className="bp-annot-group-title">{sectionTitleMap[s.section_id]}</div>
                  {list.map((c) => (
                    <div key={c.comment_id} className={`bp-annot-card type-${c.annotation_type} ${c.status === "resolved" ? "resolved" : ""}`}>
                      <div className="bp-annot-card-head">
                        <span className={`bp-annot-card-tag tag-${c.annotation_type}`}>{ANNOTATION_LABEL[c.annotation_type]}</span>
                        <span className="bp-annot-card-author">{c.teacher_name || c.teacher_id}</span>
                        <span className="bp-annot-card-time">{c.created_at?.slice(5, 16).replace("T", " ")}</span>
                      </div>
                      {c.quote && (
                        <blockquote className="bp-annot-card-quote">
                          "{c.quote.slice(0, 80)}{c.quote.length > 80 ? "…" : ""}"
                        </blockquote>
                      )}
                      <div className="bp-annot-card-content">{c.content}</div>
                      <div className="bp-annot-card-actions">
                        {c.status !== "resolved" ? (
                          <button onClick={() => updateComment(c.comment_id, { status: "resolved" })}>标为已解决</button>
                        ) : (
                          <button onClick={() => updateComment(c.comment_id, { status: "open" })}>恢复</button>
                        )}
                        <button onClick={() => deleteComment(c.comment_id)} className="bp-annot-card-del">删除</button>
                      </div>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        </aside>
      </div>

      {/* 划词添加弹出框 */}
      {selection && selection.rect && (
        <div
          className="bp-annot-popup"
          style={{ top: selection.rect.top, left: selection.rect.left }}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <div className="bp-annot-popup-quote">
            "{selection.quote.slice(0, 40)}{selection.quote.length > 40 ? "…" : ""}"
          </div>
          <div className="bp-annot-popup-types">
            {(["suggestion", "issue", "praise"] as const).map((t) => (
              <button
                key={t}
                className={`bp-annot-popup-type tag-${t} ${draftType === t ? "is-on" : ""}`}
                onClick={() => setDraftType(t)}
              >{ANNOTATION_LABEL[t]}</button>
            ))}
          </div>
          <textarea
            className="bp-annot-popup-input"
            value={draftContent}
            onChange={(e) => setDraftContent(e.target.value)}
            placeholder="写下给学生的批注..."
            autoFocus
          />
          <div className="bp-annot-popup-foot">
            <button
              onClick={() => { setSelection(null); setDraftContent(""); window.getSelection()?.removeAllRanges(); }}
              className="bp-annot-popup-cancel"
            >取消</button>
            <button
              onClick={() => void submitComment()}
              disabled={!draftContent.trim() || submitting}
              className="bp-annot-popup-submit"
            >{submitting ? "保存中…" : "保存批注"}</button>
          </div>
        </div>
      )}

      {toast && <div className="bp-annot-toast">{toast}</div>}
    </div>
  );
}

// ── DOM 辅助：把某个文本节点中的 quote 包上 <mark> ────────────
function wrapQuoteInElement(root: HTMLElement, quote: string, comment: Comment): boolean {
  if (!quote) return false;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node: Node) =>
      (node as Text).data.includes(quote) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT,
  });
  const node = walker.nextNode() as Text | null;
  if (!node) return false;
  const idx = node.data.indexOf(quote);
  if (idx < 0) return false;
  const range = document.createRange();
  range.setStart(node, idx);
  range.setEnd(node, idx + quote.length);
  const mark = document.createElement("mark");
  mark.className = `bp-tch-mark bp-tch-${comment.annotation_type}`;
  mark.setAttribute("data-comment-id", comment.comment_id);
  mark.setAttribute("title", `${ANNOTATION_LABEL[comment.annotation_type]}：${comment.content}`);
  try {
    range.surroundContents(mark);
    return true;
  } catch {
    return false;
  }
}

function escapeHtml(s: string): string {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
