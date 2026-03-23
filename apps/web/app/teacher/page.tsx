"use client";

import { FormEvent, useEffect, useMemo, useState, useRef } from "react";
import Link from "next/link";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8787").trim().replace(/\/+$/, "");
type Tab = "overview" | "submissions" | "compare" | "evidence" | "report" | "feedback" | "capability" | "rule-coverage" | "interventions" | "class" | "project" | "rubric" | "competition";

// 风险规则名称映射
const RISK_RULE_NAMES: Record<string, string> = {
  "weak_user_evidence": "弱用户证据",
  "compliance_not_covered": "合规性覆盖不足",
  "market_size_fallacy": "市场规模谬误",
  "no_competitor_claim": "缺少竞争对手声明",
};

function getRuleDisplayName(ruleName: string): string {
  return RISK_RULE_NAMES[ruleName] || ruleName;
}

// 骨架屏加载器组件
function SkeletonLoader({ rows = 3, type = "bar" }: { rows?: number; type?: "bar" | "card" | "table" }) {
  return (
    <div style={{ opacity: 0.7 }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          style={{
            height: type === "bar" ? 40 : type === "card" ? 100 : 44,
            background: "var(--bg-card)",
            borderRadius: 10,
            marginBottom: 10,
            animation: "skeleton-loading 1.5s ease-in-out infinite",
            border: "1px solid var(--border)",
          }}
        />
      ))}
    </div>
  );
}

// 成功提示组件
function SuccessToast({ message, onClose }: { message: string; onClose: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onClose, 4000);
    return () => clearTimeout(timer);
  }, [onClose]);

  return (
    <div
      style={{
        position: "fixed",
        top: 72,
        right: 20,
        padding: "12px 20px",
        background: "var(--tch-success-soft, rgba(92,189,138,0.15))",
        color: "var(--tch-success, #5cbd8a)",
        border: "1px solid rgba(92,189,138,0.3)",
        borderRadius: 10,
        backdropFilter: "blur(12px)",
        animation: "toast-slide-in 0.3s ease-out",
        zIndex: 1000,
        fontWeight: 600,
        fontSize: 13,
      }}
    >
      ✓ {message}
    </div>
  );
}

function ErrorToast({ message, onClose }: { message: string; onClose: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onClose, 4000);
    return () => clearTimeout(timer);
  }, [onClose]);

  return (
    <div
      style={{
        position: "fixed",
        top: 72,
        right: 20,
        padding: "12px 20px",
        background: "var(--tch-danger-soft, rgba(224,112,112,0.15))",
        color: "var(--tch-danger, #e07070)",
        border: "1px solid rgba(224,112,112,0.3)",
        borderRadius: 10,
        backdropFilter: "blur(12px)",
        animation: "toast-slide-in 0.3s ease-out",
        zIndex: 1001,
        fontWeight: 600,
        fontSize: 13,
      }}
    >
      ⚠ {message}
    </div>
  );
}

// 饼状图组件
function PieChart({
  data,
  colors,
  hoverItem,
  onHover,
}: {
  data: Array<{ label: string; value: number; key: string }>;
  colors: string[];
  hoverItem: string | null;
  onHover: (key: string | null) => void;
}) {
  const total = data.reduce((sum, item) => sum + item.value, 0);
  if (total === 0) return null;

  let currentAngle = 0;
  const radius = 70;
  const slices = data.map((item, idx) => {
    const sliceAngle = (item.value / total) * 360;
    const startAngle = currentAngle;
    const endAngle = currentAngle + sliceAngle;
    const isHovered = hoverItem === item.key;
    const isLarge = sliceAngle > 180 ? 1 : 0;

    const startRad = (startAngle * Math.PI) / 180;
    const endRad = (endAngle * Math.PI) / 180;

    const hoverRadius = isHovered ? 80 : radius;
    const x1 = 100 + hoverRadius * Math.cos(startRad);
    const y1 = 100 + hoverRadius * Math.sin(startRad);
    const x2 = 100 + hoverRadius * Math.cos(endRad);
    const y2 = 100 + hoverRadius * Math.sin(endRad);

    const color = colors[idx % colors.length];

    currentAngle = endAngle;

    return (
      <g key={item.key} onMouseEnter={() => onHover(item.key)} onMouseLeave={() => onHover(null)} style={{ userSelect: "none" }}>
        <path
          d={`M 100 100 L ${x1} ${y1} A ${hoverRadius} ${hoverRadius} 0 ${isLarge} 1 ${x2} ${y2} Z`}
          fill={color}
          opacity={isHovered ? 1 : 0.85}
          style={{
            cursor: "pointer",
            transition: "all 0.3s ease",
            filter: isHovered ? "saturate(1.3) brightness(1.1)" : "saturate(1) brightness(1)",
          }}
        />
        {isHovered && (
          <text
            x="100"
            y="110"
            textAnchor="middle"
            fill="var(--text-primary)"
            fontSize="12"
            fontWeight="600"
            style={{ pointerEvents: "none" }}
          >
            {item.label} ({item.value})
          </text>
        )}
      </g>
    );
  });

  return (
    <svg
      width="260"
      height="220"
      viewBox="0 0 200 200"
      style={{ margin: "0 auto", display: "block", filter: "drop-shadow(0 2px 4px rgba(0,0,0,0.05))" }}
    >
      {slices}
    </svg>
  );
}

export default function TeacherPage() {
  const [tab, setTab] = useState<Tab>("overview");
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [projectId, setProjectId] = useState("demo-project-001");
  const [teacherId, setTeacherId] = useState("teacher-001");
  const [classId, setClassId] = useState("");
  const [cohortId, setCohortId] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState("正在加载");
  const [successMessage, setSuccessMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  const [dashboard, setDashboard] = useState<any>(null);
  const [submissions, setSubmissions] = useState<any[]>([]);
  const [compareData, setCompareData] = useState<any>(null);
  const [evidence, setEvidence] = useState<any>(null);
  const [report, setReport] = useState("");
  const [reportSnapshot, setReportSnapshot] = useState<any>(null);

  const [feedbackText, setFeedbackText] = useState("");
  const [feedbackTags, setFeedbackTags] = useState("evidence,feasibility");
  const [feedbackResult, setFeedbackResult] = useState("");

  const [selectedProject, setSelectedProject] = useState("");
  const [expandedSubmission, setExpandedSubmission] = useState<number | null>(null);

  // 班级页面状态
  const [classTabInput, setClassTabInput] = useState("");
  const [classIdConfirmed, setClassIdConfirmed] = useState(false);

  // 项目页面状态
  const [projectTabInput, setProjectTabInput] = useState("");
  const [projectIdConfirmed, setProjectIdConfirmed] = useState(false);

  // 饼状图悬浮状态
  const [hoveredCategory, setHoveredCategory] = useState<string | null>(null);
  const [hoveredRisk, setHoveredRisk] = useState<string | null>(null);

  // New state for enhanced features
  const [capabilityMap, setCapabilityMap] = useState<any>(null);
  const [ruleCoverage, setRuleCoverage] = useState<any>(null);
  const [projectDiagnosis, setProjectDiagnosis] = useState<any>(null);
  const [rubricAssessment, setRubricAssessment] = useState<any>(null);
  const [competitionScore, setCompetitionScore] = useState<any>(null);
  const [teachingInterventions, setTeachingInterventions] = useState<any>(null);

  // 文件级反馈状态
  const [studentFiles, setStudentFiles] = useState<any[]>([]);
  const [selectedFile, setSelectedFile] = useState<any>(null);
  const [fileContent, setFileContent] = useState("");
  const [editedContent, setEditedContent] = useState("");
  const [isEditMode, setIsEditMode] = useState(false);
  const [documentEdits, setDocumentEdits] = useState<any[]>([]);
  const [editSummary, setEditSummary] = useState("");
  const [feedbackAnnotations, setFeedbackAnnotations] = useState<any[]>([]);
  const [annotationText, setAnnotationText] = useState("");
  const [annotationType, setAnnotationType] = useState("issue");
  const [feedbackFileToUpload, setFeedbackFileToUpload] = useState<File | null>(null);
  const [feedbackFiles, setFeedbackFiles] = useState<any[]>([]);
  const [previewData, setPreviewData] = useState<any>(null);  // 文件预览数据（分页/分段）
  const [currentPreviewPage, setCurrentPreviewPage] = useState(1);  // 当前预览页码
  const [onlinePreviewData, setOnlinePreviewData] = useState<any>(null);  // 在线预览数据（PDF base64、HTML等）
  const [onlinePreviewLoading, setOnlinePreviewLoading] = useState(false);  // 在线预览加载状态
  const [pdfAnalysisData, setPdfAnalysisData] = useState<any>(null);  // PDF LLM分析数据（摘要、要点等）
  const [pdfAnalysisLoading, setPdfAnalysisLoading] = useState(false);  // PDF分析加载状态
  const feedbackFileInputRef = useRef<HTMLInputElement>(null);

  async function api(path: string, opts?: RequestInit) {
    const r = await fetch(`${API}${path}`, opts);
    return r.json();
  }

  // 响应验证函数
  function validateResponse(response: any, errorMessage: string = "API调用失败"): any {
    if (!response) {
      throw new Error(errorMessage);
    }
    if (response.error) {
      throw new Error(response.error);
    }
    if (response.status === "error") {
      throw new Error(response.message || errorMessage);
    }
    return response;
  }

  // 提取有效内容函数 - 去除过多空白行、清理格式
  function extractValidContent(text: string): string {
    if (!text || typeof text !== "string") return "";
    
    // 去除HTML标签
    let cleaned = text.replace(/<[^>]*>/g, "");
    
    // 分割成行
    let lines = cleaned.split("\n");
    
    // 清理每一行、去除纯空白行、去除过多连续空行
    let cleanedLines: string[] = [];
    let emptyLineCount = 0;
    
    for (let line of lines) {
      const trimmed = line.trim();
      if (trimmed === "") {
        emptyLineCount++;
        // 最多保留2个连续空行
        if (emptyLineCount <= 2) {
          cleanedLines.push("");
        }
      } else {
        emptyLineCount = 0;
        cleanedLines.push(trimmed);
      }
    }
    
    // 拼接并去除两端空白
    let result = cleanedLines.join("\n").trim();
    
    // 如果文本过长，截断到合理长度
    const maxLen = 3000;
    if (result.length > maxLen) {
      result = result.substring(0, maxLen) + "\n\n[内容过长，已截断...]";
    }
    
    return result;
  }

  // 获取文件类型显示名称和图标
  function getFileTypeInfo(fileName: string): { type: string; icon: string; displayName: string; canPreview: boolean } {
    const ext = (fileName.split(".").pop() || "").toLowerCase();
    const typeMap: Record<string, { icon: string; displayName: string; canPreview: boolean }> = {
      pdf: { icon: "📄", displayName: "PDF 文档", canPreview: false },
      ppt: { icon: "🎜", displayName: "PowerPoint 97-2003", canPreview: false },
      pptx: { icon: "🎜", displayName: "PowerPoint 演示文稿", canPreview: false },
      docx: { icon: "📋", displayName: "Word 文档", canPreview: false },
      doc: { icon: "📋", displayName: "Word 97-2003", canPreview: false },
      txt: { icon: "📝", displayName: "纯文本文件", canPreview: true },
      md: { icon: "🔤", displayName: "Markdown 文档", canPreview: true },
      xlsx: { icon: "📊", displayName: "Excel 表格", canPreview: false },
      xls: { icon: "📊", displayName: "Excel 97-2003", canPreview: false },
      csv: { icon: "📊", displayName: "CSV 数据文件", canPreview: true },
    };
    
    const info = typeMap[ext] || { icon: "📎", displayName: `${ext.toUpperCase()} 文件`, canPreview: false };
    return { type: ext, ...info };
  }

  // 生成文件预览区域的内容
  function renderFilePreview(selectedFile: any, editedContent: string, isEditMode: boolean) {
    if (!selectedFile) return null;
    
    const fileInfo = getFileTypeInfo(selectedFile.filename || "");
    
    if (isEditMode) {
      // 编辑模式：显示可编辑的纯文本框（无图片）
      return (
        <div>
          <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginBottom: "8px", padding: "0 4px" }}>
            ✏️ 编辑模式 - 纯文本（仅显示文字内容，不包含图片或格式）
          </div>
          <textarea
            value={editedContent}
            onChange={(e) => setEditedContent(e.target.value)}
            style={{
              width: "100%",
              maxHeight: "400px",
              padding: "12px",
              borderRadius: "8px",
              border: "2px solid var(--accent)",
              fontSize: "13px",
              lineHeight: "1.6",
              fontFamily: "monospace",
              boxSizing: "border-box",
              background: "var(--bg-card)",
            }}
          />
        </div>
      );
    }
    
    // 查看模式：首先尝试使用在线预览数据
    
    // PDF在线预览（base64编码） + LLM分析结果
    if (onlinePreviewData?.type === "pdf" && onlinePreviewData?.pdf_base64) {
      const pdfDataUrl = `data:application/pdf;base64,${onlinePreviewData.pdf_base64}`;
      const analysis = pdfAnalysisData?.analysis;
      const pdfStats = pdfAnalysisData?.pdf_stats;
      
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          {/* 工具栏 */}
          <div style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "10px 12px",
            backgroundColor: "var(--bg-card)",
            borderRadius: "8px",
            border: "1px solid var(--border)",
          }}>
            <div style={{ fontSize: "12px", color: "var(--text-secondary)", fontWeight: "500" }}>
              📄 PDF 文档 - 共 {onlinePreviewData.page_count || "?"} 页 ({Math.round((onlinePreviewData.file_size || 0) / 1024)} KB)
            </div>
            <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
              {pdfAnalysisLoading && (
                <span style={{ fontSize: "12px", color: "var(--tch-warning)" }}>⚙️ 正在分析...</span>
              )}
              <a
                href={pdfDataUrl}
                download={selectedFile.filename}
                style={{
                  padding: "6px 12px",
                  fontSize: "12px",
                  backgroundColor: "var(--accent)",
                  color: "var(--bg-secondary)",
                  textDecoration: "none",
                  border: "none",
                  borderRadius: "8px",
                  cursor: "pointer",
                  transition: "background-color 0.2s",
                }}
              >
                ⬇️ 下载原文件
              </a>
            </div>
          </div>

          {/* 主容器：PDF + 分析结果并排 */}
          <div style={{ display: "flex", gap: "12px", height: "700px" }}>
            {/* 左侧：PDF预览 */}
            <div style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              backgroundColor: "var(--bg-secondary)",
              borderRadius: "8px",
              border: "1px solid var(--border)",
              overflow: "hidden",
            }}>
              <div style={{
                fontSize: "12px",
                fontWeight: "500",
                padding: "8px 12px",
                backgroundColor: "var(--bg-card)",
                borderBottom: "1px solid var(--border)",
                color: "var(--text-secondary)",
              }}>
                原文件预览
              </div>
              <iframe
                src={pdfDataUrl}
                style={{
                  flex: 1,
                  border: "none",
                  borderRadius: "0 0 8px 0",
                }}
                title="PDF Preview"
              />
            </div>

            {/* 右侧：LLM分析结果 */}
            <div style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              backgroundColor: "var(--bg-card)",
              borderRadius: "8px",
              border: "1px solid var(--border)",
              overflow: "hidden",
            }}>
              <div style={{
                fontSize: "12px",
                fontWeight: "500",
                padding: "8px 12px",
                background: "var(--tch-success-soft, rgba(92,189,138,0.12))",
                borderBottom: "1px solid var(--border)",
                color: "var(--tch-success)",
              }}>
                🤖 AI智能分析摘要
              </div>
              
              <div style={{
                flex: 1,
                overflowY: "auto",
                padding: "12px",
                fontSize: "13px",
                lineHeight: "1.6",
              }}>
                {pdfAnalysisLoading ? (
                  <div style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    justifyContent: "center",
                    height: "100%",
                    gap: "12px",
                    color: "var(--text-muted)",
                  }}>
                    <div style={{
                      width: "30px",
                      height: "30px",
                      border: "3px solid var(--border)",
                      borderTopColor: "var(--accent)",
                      borderRadius: "50%",
                      animation: "spin 0.8s linear infinite",
                    }} />
                    <span>正在使用AI分析文档内容...</span>
                  </div>
                ) : analysis?.status === "success" ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                    {/* 总结 */}
                    <div>
                      <div style={{ fontWeight: "600", color: "var(--accent)", marginBottom: "6px" }}>
                        📝 内容总结
                      </div>
                      <div style={{
                        backgroundColor: "var(--bg-secondary)",
                        padding: "10px",
                        borderRadius: "8px",
                        border: "1px solid var(--border)",
                        color: "var(--text-primary)",
                      }}>
                        {analysis?.summary || "暂无总结"}
                      </div>
                    </div>

                    {/* 关键要点 */}
                    {analysis?.key_points && analysis.key_points.length > 0 && (
                      <div>
                        <div style={{ fontWeight: "600", color: "var(--tch-danger)", marginBottom: "6px" }}>
                          ⭐ 关键要点
                        </div>
                        <ul style={{
                          margin: 0,
                          paddingLeft: "20px",
                          backgroundColor: "var(--bg-secondary)",
                          padding: "10px",
                          borderRadius: "8px",
                          border: "1px solid var(--border)",
                        }}>
                          {analysis.key_points.map((point: string, idx: number) => (
                            <li key={idx} style={{ marginBottom: idx < analysis.key_points.length - 1 ? "6px" : 0, color: "var(--text-primary)" }}>
                              {point}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* 重点关注领域 */}
                    {analysis?.focus_areas && analysis.focus_areas.length > 0 && (
                      <div>
                        <div style={{ fontWeight: "600", color: "var(--tch-warning)", marginBottom: "6px" }}>
                          🎯 重点领域
                        </div>
                        <div style={{
                          display: "flex",
                          flexWrap: "wrap",
                          gap: "6px",
                          backgroundColor: "var(--bg-secondary)",
                          padding: "10px",
                          borderRadius: "8px",
                          border: "1px solid var(--border)",
                        }}>
                          {analysis.focus_areas.map((area: string, idx: number) => (
                            <div key={idx} style={{
                              background: "var(--tch-warning-soft)",
                              padding: "4px 10px",
                              borderRadius: "8px",
                              fontSize: "12px",
                              color: "var(--tch-warning)",
                              border: "1px solid var(--border)",
                            }}>
                              {area}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* 深度见解 */}
                    {analysis?.insights && (
                      <div>
                        <div style={{ fontWeight: "600", color: "var(--accent-text)", marginBottom: "6px" }}>
                          💡 深度见解
                        </div>
                        <div style={{
                          backgroundColor: "var(--bg-secondary)",
                          padding: "10px",
                          borderRadius: "8px",
                          border: "1px solid var(--border)",
                          color: "var(--text-primary)",
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                        }}>
                          {analysis.insights}
                        </div>
                      </div>
                    )}

                    {/* 统计信息 */}
                    {pdfStats && (
                      <div style={{
                        fontSize: "11px",
                        color: "var(--text-muted)",
                        paddingTop: "8px",
                        borderTop: "1px solid var(--border)",
                      }}>
                        文档统计: 共 {pdfStats.total_pages} 页 | 已分析 {pdfStats.extracted_pages} 页 | 共 {pdfStats.total_chars} 字符
                      </div>
                    )}
                  </div>
                ) : (
                  <div style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    height: "100%",
                    color: "var(--text-muted)",
                    textAlign: "center",
                  }}>
                    <div>
                      <div style={{ fontSize: "24px", marginBottom: "8px" }}>💭</div>
                      <div>AI分析结果不可用</div>
                      <div style={{ fontSize: "12px", marginTop: "4px" }}>您仍可查看左侧的原始PDF文件</div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      );
    }
    
    // DOCX/PPT在线预览（HTML格式）
    if (onlinePreviewData?.status === "success" && onlinePreviewData?.html_content) {
      const docType = onlinePreviewData.type;
      const displayName = docType === "docx" ? "📋 Word 文档" :
                         docType === "pptx" || docType === "ppt" ? "🎜 PowerPoint演示文稿" :
                         "📄 文档";
      
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          <div style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "8px 12px",
            backgroundColor: "var(--bg-card)",
            borderRadius: "8px",
            borderBottom: "1px solid var(--border)",
          }}>
            <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
              {displayName} 
              {onlinePreviewData.slide_count ? ` - 共 ${onlinePreviewData.slide_count} 页` : ""}
              ({onlinePreviewData.file_size || 0} 字节)
            </div>
          </div>
          <div style={{
            maxHeight: "500px",
            overflowY: "auto",
            backgroundColor: "var(--bg-secondary)",
            borderRadius: "8px",
            border: "1px solid var(--border)",
            padding: "12px",
            fontSize: "14px",
            lineHeight: "1.8",
            color: "var(--text-primary)",
          }}>
            <div 
              dangerouslySetInnerHTML={{ __html: onlinePreviewData.html_content }}
              style={{
                "& h1, & h2, & h3": { marginTop: "16px", marginBottom: "8px" },
                "& p": { marginBottom: "8px" },
                "& table": { width: "100%", borderCollapse: "collapse" },
                "& td, & th": { border: "1px solid var(--border)", padding: "8px" }
              } as any}
            />
          </div>
        </div>
      );
    }
    
    // 加载中的在线预览
    if (onlinePreviewLoading) {
      return (
        <div style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          minHeight: "300px",
          backgroundColor: "var(--bg-card)",
          borderRadius: "8px",
          border: "1px solid var(--border)",
          textAlign: "center",
        }}>
          <div style={{ fontSize: "24px", marginBottom: "12px", animation: "spin 1s linear infinite" }}>
            ⚙️
          </div>
          <div style={{ fontSize: "14px", color: "var(--text-secondary)" }}>正在加载文件预览...</div>
        </div>
      );
    }
    
    // 在线预览失败，回退到文本预览
    if (onlinePreviewData?.status === "text_fallback" || onlinePreviewData?.status === "error") {
      if (onlinePreviewData?.raw_text && onlinePreviewData.raw_text.trim()) {
        return (
          <div>
            <div style={{ fontSize: "12px", color: "var(--tch-warning)", marginBottom: "8px", padding: "8px", background: "var(--bg-card)", borderRadius: "8px" }}>
              💡 原始文件不可用，显示的是提取的文本内容预览
            </div>
            <div style={{
              maxHeight: "450px",
              overflowY: "auto",
              backgroundColor: "var(--bg-secondary)",
              padding: "12px",
              borderRadius: "8px",
              border: "1px solid var(--border)",
              fontSize: "13px",
              lineHeight: "1.6",
              color: "var(--text-primary)",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}>
              {extractValidContent(onlinePreviewData.raw_text)}
            </div>
          </div>
        );
      }
    }
    
    // 其他格式或没有预览数据时的显示
    if (fileInfo.canPreview && editedContent && editedContent.trim()) {
      // 支持预览的文本格式
      return (
        <div style={{
          maxHeight: "400px",
          overflowY: "auto",
          backgroundColor: "var(--bg-secondary)",
          padding: "12px",
          borderRadius: "8px",
          border: "1px solid var(--border)",
          fontSize: "13px",
          lineHeight: "1.6",
          color: "var(--text-primary)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}>
          {extractValidContent(editedContent)}
        </div>
      );
    }
    
    // 无法预览的文件格式
    return (
      <div style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "300px",
        backgroundColor: "var(--bg-card)",
        borderRadius: "8px",
        border: "2px dashed var(--border)",
        padding: "20px",
        textAlign: "center",
      }}>
        <div style={{ fontSize: "48px", marginBottom: "12px" }}>{fileInfo.icon}</div>
        <div style={{ fontSize: "16px", fontWeight: "600", color: "var(--text-primary)", marginBottom: "8px" }}>
          {fileInfo.displayName}
        </div>
        <div style={{ fontSize: "13px", color: "var(--text-secondary)", marginBottom: "12px" }}>
          {selectedFile.filename}
        </div>
        <div style={{ fontSize: "12px", color: "var(--text-muted)", maxWidth: "300px", lineHeight: "1.6" }}>
          文件预览功能正在加载或暂时不可用，但已自动提取文本内容。您可以在编辑模式中查看和修改提取的文本。
        </div>
        {editedContent && (
          <div style={{
            fontSize: "12px",
            color: "var(--accent)",
            marginTop: "12px",
            padding: "8px 12px",
            background: "var(--tch-accent-soft, rgba(107,138,255,0.12))",
            borderRadius: "8px",
          }}>
            ✓ 已提取 {editedContent.length} 个字符的文本内容
          </div>
        )}
      </div>
    );
  }

  async function loadDashboard() {
    try {
      setLoadingMessage("正在加载总览数据");
      setLoading(true);
      setErrorMessage("");
      const q = categoryFilter ? `?category=${encodeURIComponent(categoryFilter)}` : "";
      const data = validateResponse(await api(`/api/teacher/dashboard${q}`), "加载总览数据失败");
      setDashboard(data.data);
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "加载总览数据失败"}`);
      setDashboard(null);
    } finally {
      setLoading(false);
    }
  }

  async function loadSubmissions() {
    setLoadingMessage("正在加载学生提交记录");
    setLoading(true);
    const params = new URLSearchParams();
    if (classId.trim()) params.set("class_id", classId.trim());
    if (cohortId.trim()) params.set("cohort_id", cohortId.trim());
    const q = params.toString();
    const data = await api(`/api/teacher/submissions${q ? `?${q}` : ""}`);
    setSubmissions(data.submissions ?? []);
    setLoading(false);
  }

  async function loadCompare() {
    setLoadingMessage("正在对比基线数据");
    setLoading(true);
    const params = new URLSearchParams();
    if (classId.trim()) params.set("class_id", classId.trim());
    if (cohortId.trim()) params.set("cohort_id", cohortId.trim());
    const q = params.toString();
    const data = await api(`/api/teacher/compare${q ? `?${q}` : ""}`);
    setCompareData(data);
    setLoading(false);
  }

  async function loadEvidence(pid: string) {
    setLoadingMessage("正在加载证据链数据");
    setLoading(true);
    setSelectedProject(pid);
    const data = await api(`/api/teacher/project/${encodeURIComponent(pid)}/evidence`);
    setEvidence(data.data);
    setTab("evidence");
    setLoading(false);
  }

  async function generateReport() {
    setLoadingMessage("正在生成AI班级报告");
    setLoading(true);
    const params = new URLSearchParams();
    if (classId.trim()) params.set("class_id", classId.trim());
    if (cohortId.trim()) params.set("cohort_id", cohortId.trim());
    const q = params.toString();
    const data = await api(`/api/teacher/generate-report${q ? `?${q}` : ""}`, { method: "POST" });
    setReport(data.report ?? "");
    setReportSnapshot(data.snapshot ?? null);
    setTab("report");
    setLoading(false);
  }

  async function loadCapabilityMap() {
    setLoadingMessage("正在加载能力映射");
    setLoading(true);
    const data = await api(`/api/teacher/capability-map/${encodeURIComponent(classId.trim() || "default")}`);
    setCapabilityMap(data);
    setTab("capability");
    setLoading(false);
  }

  async function loadRuleCoverage() {
    setLoadingMessage("正在分析规则覆盖率");
    setLoading(true);
    const data = await api(`/api/teacher/rule-coverage/${encodeURIComponent(classId.trim() || "default")}`);
    setRuleCoverage(data);
    setTab("rule-coverage");
    setLoading(false);
  }

  async function loadProjectDiagnosis() {
    setLoadingMessage("正在进行项目诊断");
    setLoading(true);
    if (!selectedProject) {
      setLoading(false);
      return;
    }
    const data = await api(`/api/teacher/project/${encodeURIComponent(selectedProject)}/deep-diagnosis`);
    setProjectDiagnosis(data);
    setTab("rubric");
    setLoading(false);
  }

  async function loadRubricAssessment() {
    setLoadingMessage("正在计算Rubric评分");
    setLoading(true);
    if (!selectedProject) {
      setLoading(false);
      return;
    }
    const data = await api(`/api/teacher/project/${encodeURIComponent(selectedProject)}/rubric-assessment`);
    setRubricAssessment(data);
    setTab("rubric");
    setLoading(false);
  }

  async function loadCompetitionScore() {
    setLoadingMessage("正在预测竞赛评分");
    setLoading(true);
    if (!selectedProject) {
      setLoading(false);
      return;
    }
    const data = await api(`/api/teacher/project/${encodeURIComponent(selectedProject)}/competition-score`);
    setCompetitionScore(data);
    setTab("competition");
    setLoading(false);
  }

  async function loadTeachingInterventions() {
    setLoadingMessage("正在分析教学干预方案");
    setLoading(true);
    const data = await api(`/api/teacher/teaching-interventions/${encodeURIComponent(classId.trim() || "default")}`);
    setTeachingInterventions(data);
    setTab("interventions");
    setLoading(false);
  }

  async function submitFeedback(e: FormEvent) {
    e.preventDefault();
    if (!feedbackText.trim() || feedbackText.trim().length < 5) {
      setErrorMessage("反馈内容至少需要5个字符");
      return;
    }
    
    try {
      setErrorMessage("");
      const targetPid = selectedProject || projectId;
      const data = await api("/api/teacher-feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: targetPid,
          teacher_id: teacherId,
          comment: feedbackText.trim(),
          focus_tags: feedbackTags.split(",").map((t) => t.trim()).filter(Boolean),
        }),
      });
      setSuccessMessage(`反馈已保存 (ID: ${data.feedback_id ?? "?"})`);
      setFeedbackText("");
      setFeedbackResult("");
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "提交反馈失败"}`);
    }
  }

  // 文件级反馈函数
  async function loadStudentFiles() {
    try {
      setLoadingMessage("正在加载学生提交文件");
      setLoading(true);
      setErrorMessage("");
      const targetPid = selectedProject || projectId;
      if (!targetPid.trim()) {
        setErrorMessage("请先输入项目ID");
        setStudentFiles([]);
        return;
      }
      const data = validateResponse(await api(`/api/teacher/student-files/${encodeURIComponent(targetPid)}`), "加载文件列表失败");
      setStudentFiles(data.files || []);
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "加载文件列表失败"}`);
      setStudentFiles([]);
    } finally {
      setLoading(false);
    }
  }

  async function loadFileContent(submissionId: string) {
    try {
      const targetPid = selectedProject || projectId;
      setErrorMessage("");
      setCurrentPreviewPage(1);  // 重置预览页码
      setOnlinePreviewLoading(true);
      setPdfAnalysisLoading(true);
      
      // 第一阶段：并行加载基本数据
      const [fileData, annotationsData, feedbackFilesData, editsData, previewDataResult] = await Promise.all([
        api(`/api/teacher/student-file/${encodeURIComponent(targetPid)}/${encodeURIComponent(submissionId)}`),
        api(`/api/teacher/feedback-annotations/${encodeURIComponent(targetPid)}/${encodeURIComponent(submissionId)}`),
        api(`/api/teacher/feedback-files/${encodeURIComponent(targetPid)}/${encodeURIComponent(submissionId)}`),
        api(`/api/teacher/document-edits/${encodeURIComponent(targetPid)}/${encodeURIComponent(submissionId)}`),
        api(`/api/teacher/file-preview/${encodeURIComponent(targetPid)}/${encodeURIComponent(submissionId)}`)
      ]);
      
      // 第二阶段：根据文件类型决定是否加载PDF分析
      let pdfAnalysisResult: any = null;
      if (previewDataResult?.type === "pdf" && previewDataResult?.pdf_base64) {
        try {
          pdfAnalysisResult = await api(`/api/teacher/pdf-analysis/${encodeURIComponent(targetPid)}/${encodeURIComponent(submissionId)}`);
        } catch (e) {
          // PDF分析失败不影响其他数据
          pdfAnalysisResult = null;
        }
      }
      
      // 批量更新状态
      setSelectedFile(fileData);
      setFileContent(fileData.raw_text || "");
      setEditedContent(fileData.raw_text || "");
      setPreviewData(fileData.preview_data || null);  // 保存预览数据
      setOnlinePreviewData(previewDataResult || null);  // 保存在线预览数据
      setPdfAnalysisData(pdfAnalysisResult || null);  // 保存PDF分析数据
      setIsEditMode(false);
      setFeedbackAnnotations(annotationsData.annotations || []);
      setFeedbackFiles(feedbackFilesData.feedback_files || []);
      setDocumentEdits(editsData.edits || []);
      setOnlinePreviewLoading(false);
      setPdfAnalysisLoading(false);
    } catch (error) {
      setErrorMessage("加载文件内容失败");
      setSelectedFile(null);
      setFileContent("");
      setPreviewData(null);
      setOnlinePreviewData(null);
      setPdfAnalysisData(null);
      setOnlinePreviewLoading(false);
      setPdfAnalysisLoading(false);
    }
  }

  async function saveAnnotation() {
    if (!annotationText.trim() || !selectedFile) {
      setErrorMessage("请输入批注内容并选择文件");
      return;
    }
    
    try {
      const targetPid = selectedProject || projectId;
      setErrorMessage("");
      const payload = {
        project_id: targetPid,
        submission_id: selectedFile.submission_id,
        teacher_id: teacherId,
        annotations: [{
          type: "comment",
          content: annotationText.trim(),
          annotation_type: annotationType,
        }],
        overall_feedback: "",
        focus_areas: [],
      };
      
      await validateResponse(await api("/api/teacher/feedback-annotations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }), "保存批注失败");
      
      setSuccessMessage("批注已保存");
      setAnnotationText("");
      
      // 重新加载批注列表
      if (selectedFile) {
        const annotationsData = await api(`/api/teacher/feedback-annotations/${encodeURIComponent(targetPid)}/${encodeURIComponent(selectedFile.submission_id)}`);
        setFeedbackAnnotations(annotationsData.annotations || []);
      }
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "保存批注失败"}`);
    }
  }

  async function uploadFeedbackFile() {
    if (!feedbackFileToUpload || !selectedFile) {
      setErrorMessage("请选择文件并选中学生文件");
      return;
    }
    
    try {
      setErrorMessage("");
      const targetPid = selectedProject || projectId;
      const formData = new FormData();
      formData.append("project_id", targetPid);
      formData.append("submission_id", selectedFile.submission_id);
      formData.append("teacher_id", teacherId);
      formData.append("feedback_comment", feedbackText || "");
      formData.append("file", feedbackFileToUpload);
      
      await api("/api/teacher/upload-feedback-file", {
        method: "POST",
        body: formData,
      });
      
      setSuccessMessage("反馈文件已上传");
      setFeedbackFileToUpload(null);
      if (feedbackFileInputRef.current) feedbackFileInputRef.current.value = "";
      
      // 重新加载反馈文件列表
      const feedbackFilesData = await api(`/api/teacher/feedback-files/${encodeURIComponent(targetPid)}/${encodeURIComponent(selectedFile.submission_id)}`);
      setFeedbackFiles(feedbackFilesData.feedback_files || []);
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "上传反馈文件失败"}`);
    }
  }

  async function loadDocumentEdits() {
    if (!selectedFile) return;
    
    const targetPid = selectedProject || projectId;
    const editsData = await api(`/api/teacher/document-edits/${encodeURIComponent(targetPid)}/${encodeURIComponent(selectedFile.submission_id)}`);
    setDocumentEdits(editsData.edits || []);
  }

  async function saveEditedDocument() {
    if (!editedContent.trim() || !selectedFile) {
      setErrorMessage("请输入编辑内容并选择文件");
      return;
    }
    
    try {
      setErrorMessage("");
      const targetPid = selectedProject || projectId;
      const payload = {
        project_id: targetPid,
        submission_id: selectedFile.submission_id,
        teacher_id: teacherId,
        edited_content: editedContent,
        edit_summary: editSummary || "文档编辑",
      };
      
      await api("/api/teacher/edit-document", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      
      setSuccessMessage("文档编辑已保存");
      setEditSummary("");
      setIsEditMode(false);
      
      // 重新加载编辑历史
      await loadDocumentEdits();
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "保存编辑失败"}`);
    }
  }

  async function exportDocument(format: 'txt' | 'pdf') {
    if (!editedContent.trim() || !selectedFile) {
      setErrorMessage("请先编辑文档内容");
      return;
    }
    
    try {
      setErrorMessage("");
      const targetPid = selectedProject || projectId;
      const filename = `反馈_${selectedFile.student_id || 'student'}_export`;
      
      const payload = {
        project_id: targetPid,
        submission_id: selectedFile.submission_id,
        edited_content: editedContent,
        format: format,
        filename: filename,
      };
      
      const data = await api("/api/teacher/export-document", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      
      if (data.download_url) {
        const link = document.createElement('a');
        link.href = `${API}${data.download_url}`;
        link.download = `${filename}.${format}`;
        link.click();
        setSuccessMessage(`文档已导出为 ${format.toUpperCase()} 格式`);
      } else {
        setErrorMessage("导出失败：无法获取下载链接");
      }
    } catch (error) {
      setErrorMessage(`${error instanceof Error ? error.message : "导出文档失败"}`);
    }
  }

  useEffect(() => {
    const saved = localStorage.getItem("tch-theme") as "dark" | "light" | null;
    if (saved) setTheme(saved);
  }, []);

  useEffect(() => {
    localStorage.setItem("tch-theme", theme);
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => { loadDashboard(); }, []);

  const maxCat = useMemo(() => Math.max(1, ...(dashboard?.category_distribution ?? []).map((r: any) => Number(r.projects || 0))), [dashboard]);
  const maxRule = useMemo(() => Math.max(1, ...(dashboard?.top_risk_rules ?? []).map((r: any) => Number(r.projects || 0))), [dashboard]);

  const TABS: { id: Tab; label: string }[] = [
    { id: "overview", label: "总览" },
    { id: "class", label: "班级" },
    { id: "project", label: "项目" },
    { id: "submissions", label: "学生提交" },
    { id: "feedback", label: "写回反馈" },
  ];

  const CLASS_SUB_TABS = [
    { id: "compare", label: "基线对比" },
    { id: "capability", label: "能力映射" },
    { id: "rule-coverage", label: "规则检查" },
    { id: "interventions", label: "教学建议" },
    { id: "report", label: "智能报告" },
  ];

  const PROJECT_SUB_TABS = [
    { id: "rubric", label: "评分与诊断" },
    { id: "competition", label: "竞赛预测" },
    { id: "evidence", label: "证据链" },
  ];

  return (
    <div className="tch-app" suppressHydrationWarning>
      <header className="chat-topbar">
        <div className="topbar-left">
          <Link href="/" className="topbar-brand">VentureAgent</Link>
          <span className="topbar-sep" />
          <span className="topbar-label">教师控制台</span>
        </div>
        <div className="topbar-center">
          <input className="tch-filter-input" value={classId} onChange={(e) => setClassId(e.target.value)} placeholder="班级ID" />
          <input className="tch-filter-input" value={cohortId} onChange={(e) => setCohortId(e.target.value)} placeholder="学期" />
          <input className="tch-filter-input" value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)} placeholder="类别筛选" />
        </div>
        <div className="topbar-right">
          <button 
            type="button"
            className="topbar-icon-btn" 
            onClick={() => setTheme((t) => t === "dark" ? "light" : "dark")}
            title={theme === "dark" ? "切换日间模式" : "切换夜间模式"}
            suppressHydrationWarning
          >
            {theme === "dark" ? (
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
            ) : (
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>
            )}
          </button>
          <button className="topbar-btn" onClick={generateReport} disabled={loading}>生成AI报告</button>
          <Link href="/student" className="topbar-btn">学生端</Link>
        </div>
      </header>

      <div className="tch-body">
        <nav className="tch-sidebar">
          {TABS.map((t) => (
            <button 
              key={t.id} 
              className={`tch-nav-btn ${tab === t.id ? "active" : ""} ${loading ? "disabled" : ""}`}
              disabled={loading}
              style={{
                transition: "all 0.3s ease",
                opacity: loading && tab !== t.id ? 0.6 : 1,
              }}
              onClick={() => {
                setTab(t.id);
                if (t.id === "overview") loadDashboard();
                if (t.id === "submissions") loadSubmissions();
                if (t.id === "compare") loadCompare();
                if (t.id === "capability") loadCapabilityMap();
                if (t.id === "rule-coverage") loadRuleCoverage();
                if (t.id === "rubric") loadRubricAssessment();
                if (t.id === "competition") loadCompetitionScore();
                if (t.id === "interventions") loadTeachingInterventions();
                if (t.id === "class") {
                  setClassIdConfirmed(false);
                  setClassTabInput(classId);
                }
              }}>
              {t.label}
              {loading && tab === t.id && <span style={{ marginLeft: 8 }}>⏳</span>}
            </button>
          ))}
        </nav>

        <main className="tch-main">
          {/* 加载进度条 */}
          {loading && (
            <div
              style={{
                position: "fixed",
                top: 0,
                left: 0,
                right: 0,
                height: "3px",
                zIndex: 999,
              }}
              className="tch-progress-bar"
            />
          )}

          {/* 加载状态提示 */}
          {loading && (
            <div
              className="tch-loading"
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                gap: 12,
                animation: "fade-in 0.3s ease-out",
              }}
            >
              <div
                style={{
                  width: 40,
                  height: 40,
                  border: "3px solid var(--border)",
                  borderTop: "3px solid var(--accent)",
                  borderRadius: "50%",
                  animation: "spin 0.8s linear infinite",
                }}
              />
              <p>{loadingMessage}...</p>
              <p style={{ fontSize: 12, color: "var(--text-muted)" }}>请稍候</p>
            </div>
          )}

          {/* 消息提示 */}
          {successMessage && <SuccessToast message={successMessage} onClose={() => setSuccessMessage("")} />}
          {errorMessage && <ErrorToast message={errorMessage} onClose={() => setErrorMessage("")} />}

          {/* ── 总览 ── */}
          {tab === "overview" && !loading && (
            <div className="tch-panel fade-up">
              <h2>总览</h2>
              <p className="tch-desc">基于Neo4j图数据库中存储的全部项目数据实时计算。数据来源：学生每次提交或对话时自动入库。</p>
              {dashboard?.error && <p className="right-hint">图数据读取失败：{dashboard.error}</p>}
              
              {!dashboard ? (
                <SkeletonLoader rows={3} type="card" />
              ) : (
                <>
                  <div className="kpi-grid" style={{ animation: "fade-in 0.5s ease-out" }}>
                    <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                      <span>项目总数</span>
                      <strong style={{ fontSize: 28 }}>{dashboard?.overview?.total_projects ?? "-"}</strong>
                      <em className="kpi-hint">图数据库中的项目节点数</em>
                    </div>
                    <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                      <span>证据总数</span>
                      <strong style={{ fontSize: 28 }}>{dashboard?.overview?.total_evidence ?? "-"}</strong>
                      <em className="kpi-hint">学生提交的证据条数</em>
                    </div>
                    <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                      <span>规则命中</span>
                      <strong style={{ fontSize: 28 }}>{dashboard?.overview?.total_rule_hits ?? "-"}</strong>
                      <em className="kpi-hint">触发风险规则的总次数</em>
                    </div>
                  </div>
                  <div className="viz-grid">
                    <div className="viz-card" style={{ animation: "fade-in 0.6s ease-out" }}>
                      <h3>📊 类别分布</h3>
                      <p className="tch-desc">学生项目的领域分类统计。点击类别可筛选。</p>
                      {(dashboard?.category_distribution ?? []).length === 0 ? (
                        <p style={{ color: "var(--text-muted)", fontSize: 12 }}>暂无类别数据</p>
                      ) : (
                        <>
                          <PieChart
                            data={(dashboard?.category_distribution ?? []).map((row: any) => ({
                              label: row.category,
                              value: Number(row.projects || 0),
                              key: row.category,
                            }))}
                            colors={["#4a90e2", "#2ecc71", "#f39c12", "#e74c3c", "#9b59b6", "#1abc9c", "#34495e", "#e67e22"]}
                            hoverItem={hoveredCategory}
                            onHover={setHoveredCategory}
                          />
                          <div style={{ marginTop: 20 }}>
                            {(dashboard?.category_distribution ?? []).map((row: any, idx: number) => (
                              <div
                                key={row.category}
                                className="bar-row"
                                style={{
                                  cursor: "pointer",
                                  transition: "all 0.2s ease",
                                  opacity: hoveredCategory === null || hoveredCategory === row.category ? 1 : 0.5,
                                }}
                                onMouseEnter={() => setHoveredCategory(row.category)}
                                onMouseLeave={() => setHoveredCategory(null)}
                                onClick={() => setCategoryFilter(row.category)}
                              >
                                <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                  <span
                                    style={{
                                      width: 12,
                                      height: 12,
                                      borderRadius: "50%",
                                      backgroundColor: ["#4a90e2", "#2ecc71", "#f39c12", "#e74c3c", "#9b59b6", "#1abc9c", "#34495e", "#e67e22"][idx % 8],
                                    }}
                                  />
                                  {row.category}
                                </span>
                                <div className="bar-track">
                                  <div
                                    className="bar-fill"
                                    style={{
                                      width: `${(Number(row.projects || 0) / maxCat) * 100}%`,
                                      transition: "width 0.4s ease",
                                      backgroundColor: ["#4a90e2", "#2ecc71", "#f39c12", "#e74c3c", "#9b59b6", "#1abc9c", "#34495e", "#e67e22"][idx % 8],
                                    }}
                                  />
                                </div>
                                <em>{row.projects}</em>
                              </div>
                            ))}
                          </div>
                        </>
                      )}
                    </div>
                    <div className="viz-card" style={{ animation: "fade-in 0.7s ease-out" }}>
                      <h3>⚠️ 最高风险规则</h3>
                      <p className="tch-desc">被触发最多次的风险规则。高频风险=班级共性问题，适合课堂重点讲解。</p>
                      {(dashboard?.top_risk_rules ?? []).length === 0 ? (
                        <p style={{ color: "var(--text-muted)", fontSize: 12 }}>暂无风险规则数据</p>
                      ) : (
                        <>
                          <PieChart
                            data={(dashboard?.top_risk_rules ?? []).slice(0, 4).map((row: any) => ({
                              label: getRuleDisplayName(row.rule),
                              value: Number(row.projects || 0),
                              key: row.rule,
                            }))}
                            colors={["#ff6b6b", "#ff8c42", "#ffa502", "#ff6b9d"]}
                            hoverItem={hoveredRisk}
                            onHover={setHoveredRisk}
                          />
                          <div style={{ marginTop: 20 }}>
                            {(dashboard?.top_risk_rules ?? []).slice(0, 4).map((row: any, idx: number) => (
                              <div
                                key={row.rule}
                                className="bar-row"
                                style={{
                                  cursor: "pointer",
                                  transition: "all 0.2s ease",
                                  opacity: hoveredRisk === null || hoveredRisk === row.rule ? 1 : 0.5,
                                }}
                                onMouseEnter={() => setHoveredRisk(row.rule)}
                                onMouseLeave={() => setHoveredRisk(null)}
                              >
                                <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                  <span
                                    style={{
                                      width: 12,
                                      height: 12,
                                      borderRadius: "50%",
                                      backgroundColor: ["#ff6b6b", "#ff8c42", "#ffa502", "#ff6b9d"][idx % 4],
                                    }}
                                  />
                                  {getRuleDisplayName(row.rule)}
                                </span>
                                <div className="bar-track danger">
                                  <div
                                    className="bar-fill danger"
                                    style={{
                                      width: `${(Number(row.projects || 0) / maxRule) * 100}%`,
                                      transition: "width 0.4s ease",
                                      backgroundColor: ["#ff6b6b", "#ff8c42", "#ffa502", "#ff6b9d"][idx % 4],
                                    }}
                                  />
                                </div>
                                <em>{row.projects}</em>
                              </div>
                            ))}
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                  <h3 style={{ marginTop: 16 }}>🎯 高风险项目</h3>
                  <p className="tch-desc">触发风险规则最多的项目，建议优先关注和干预。点击可查看详细证据链。</p>
                  <div className="table-like">
                    {(dashboard?.high_risk_projects ?? []).length === 0 ? (
                      <p style={{ color: "var(--text-muted)", fontSize: 12, padding: 16 }}>暂无高风险项目数据</p>
                    ) : (
                      (dashboard?.high_risk_projects ?? []).slice(0, 8).map((row: any, idx: number) => (
                        <button 
                          key={row.project_id} 
                          className="project-item" 
                          onClick={() => loadEvidence(row.project_id)}
                          style={{ 
                            animation: `fade-in 0.3s ease-out ${idx * 0.05}s both`,
                            transition: "all 0.2s ease"
                          }}
                        >
                          <span>{row.project_name || row.project_id}</span>
                          <span>{row.category}</span>
                          <span className="risk-badge high">风险{row.risk_count}</span>
                        </button>
                      ))
                    )}
                  </div>
                </>
              )}
            </div>
          )}

          {/* ── 学生提交列表 ── */}
          {tab === "submissions" && !loading && (
            <div className="tch-panel fade-up">
              <h2>学生提交记录 ({submissions.length})</h2>
              <p className="tch-desc">学生每次发消息或上传文件，系统自动记录并分析。评分来自规则引擎（满分10），风险为触发的规则ID。点击"展开"查看学生提交的原始内容。</p>
              <div className="tch-table" style={{ animation: "fade-in 0.4s ease-out" }}>
                <div className="tch-table-header">
                  <span>时间</span><span>项目</span><span>学生</span><span>来源</span><span>评分</span><span>风险</span><span>操作</span>
                </div>
                {submissions.length === 0 ? (
                  <p style={{ color: "var(--text-muted)", fontSize: 12, padding: 20, textAlign: "center" }}>📭 暂无提交记录。学生对话后这里会自动出现。</p>
                ) : (
                  submissions.map((s, i) => (
                    <div 
                      key={i} 
                      className="tch-submission-block"
                      style={{
                        animation: `fade-in 0.3s ease-out ${i * 0.05}s both`,
                        transition: "all 0.2s ease",
                      }}
                    >
                      <div className="tch-table-row">
                        <span className="tch-cell-time">{(s.created_at ?? "").slice(0, 16)}</span>
                        <span>{s.project_id}</span>
                        <span>{s.student_id}</span>
                        <span>{s.source_type}{s.filename ? ` (${s.filename})` : ""}</span>
                        <span className="tch-cell-score" style={{ color: Number(s.overall_score) >= 7 ? "var(--tch-success)" : Number(s.overall_score) >= 5 ? "var(--tch-warning)" : "var(--tch-danger)" }}>
                          {s.overall_score}
                        </span>
                        <span>{(s.triggered_rules ?? []).join(", ") || "-"}</span>
                        <span>
                          <button className="tch-sm-btn" onClick={() => setExpandedSubmission(expandedSubmission === i ? null : i)}>
                            {expandedSubmission === i ? "收起" : "展开"}
                          </button>
                          <button className="tch-sm-btn" onClick={() => loadEvidence(s.project_id)}>证据链</button>
                          <button className="tch-sm-btn" onClick={() => { setSelectedProject(s.project_id); setTab("feedback"); }}>批注</button>
                        </span>
                      </div>
                      {expandedSubmission === i && (
                        <div className="tch-submission-detail" style={{ animation: "slide-down 0.3s ease-out" }}>
                          {s.bottleneck && (
                            <div className="tch-detail-section">
                              <h4>💡 系统诊断瓶颈</h4>
                              <p>{s.bottleneck}</p>
                            </div>
                          )}
                          {s.next_task && (
                            <div className="tch-detail-section">
                              <h4>➡️ 系统建议的下一步</h4>
                              <p>{s.next_task}</p>
                            </div>
                          )}
                          {s.kg_analysis?.insight && (
                            <div className="tch-detail-section">
                              <h4>🔗 知识图谱分析</h4>
                              <p>{s.kg_analysis.insight}</p>
                            </div>
                          )}
                          <div className="tch-detail-section">
                            <h4>⚡ 快速操作</h4>
                            <button className="tch-sm-btn" onClick={() => { setSelectedProject(s.project_id); loadRubricAssessment(); }}>Rubric评分</button>
                            <button className="tch-sm-btn" onClick={() => { setSelectedProject(s.project_id); loadCompetitionScore(); }}>竞赛预测</button>
                            <button className="tch-sm-btn" onClick={() => { setSelectedProject(s.project_id); loadProjectDiagnosis(); }}>深度诊断</button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {/* ── 基线对比 ── */}
          {tab === "compare" && !loading && (
            <div className="tch-panel fade-up">
              <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
                <button onClick={() => setTab("class")} className="tch-back-btn">← 返回班级</button>
              </div>
              <h2>📊 历史基线 vs 本班现状</h2>
              <p className="tch-desc">将本班数据与历史所有班级的平均水平对比。"风险强度"=平均每个项目触发的风险规则数，数值越低越好。差值为正表示本班风险高于历史平均。</p>
              <div className="kpi-grid" style={{ animation: "fade-in 0.4s ease-out" }}>
                <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                  <span>📈 基线风险强度</span>
                  <strong style={{ fontSize: 28 }}>{compareData?.baseline?.avg_rule_hits_per_project ?? "-"}</strong>
                  <em className="kpi-hint">历史全部项目的平均值</em>
                </div>
                <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                  <span>🎯 本班风险强度</span>
                  <strong style={{ fontSize: 28 }}>{compareData?.current_class?.avg_rule_hits_per_submission ?? "-"}</strong>
                  <em className="kpi-hint">本班学生提交的平均值</em>
                </div>
                <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                  <span>📊 差值</span>
                  <strong style={{ 
                    fontSize: 28, 
                    color: Number(compareData?.comparison?.risk_intensity_delta) > 0 ? "var(--tch-danger)" : "var(--tch-success)"
                  }}>
                    {compareData?.comparison?.risk_intensity_delta ?? "-"}
                  </strong>
                  <em className="kpi-hint">正数=高于基线，负数=优于基线</em>
                </div>
              </div>
              <div className="kpi-grid" style={{ animation: "fade-in 0.5s ease-out" }}>
                <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                  <span>⚠️ 基线高风险占比</span>
                  <strong style={{ fontSize: 28 }}>{compareData?.baseline?.high_risk_ratio ?? "-"}</strong>
                  <em className="kpi-hint">历史高危项目的比例</em>
                </div>
                <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                  <span>🔍 本班高风险占比</span>
                  <strong style={{ fontSize: 28 }}>{compareData?.current_class?.high_risk_ratio ?? "-"}</strong>
                  <em className="kpi-hint">本班高危项目的比例</em>
                </div>
                <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                  <span>⭐ Rubric 均分</span>
                  <strong style={{ fontSize: 28, color: "var(--tch-warning)" }}>{compareData?.current_class?.avg_rubric_score ?? "-"}</strong>
                  <em className="kpi-hint">9维度评分的平均值(满分10)</em>
                </div>
              </div>
              <h3 style={{ marginTop: 24 }}>💡 自动干预建议</h3>
              <p className="tch-desc">系统根据对比差异自动生成的教学建议。建议在课堂上针对性讲解。</p>
              <div className="tch-recs" style={{ animation: "fade-in 0.6s ease-out" }}>
                {(compareData?.recommendations ?? []).length === 0 ? (
                  <p style={{ color: "var(--text-muted)", fontSize: 12 }}>暂无建议</p>
                ) : (
                  (compareData?.recommendations ?? []).map((item: string, i: number) => (
                    <div 
                      key={i} 
                      className="right-tag"
                      style={{
                        animation: `fade-in 0.3s ease-out ${i * 0.1}s both`,
                        transition: "all 0.2s ease",
                      }}
                    >
                      ✓ {item}
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {/* ── 证据链 ── */}
          {tab === "evidence" && !loading && (
            <div className="tch-panel fade-up">
              <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
                <button onClick={() => setTab("project")} className="tch-back-btn">← 返回项目</button>
              </div>
              <h2>🔗 项目证据链 — {selectedProject || projectId}</h2>
              <p className="tch-desc">证据链包括从Neo4j图数据库中提取的关键证据，以及学生提交的项目文件。证据越完整，项目越成熟。</p>
              <div className="tch-evidence-actions" style={{ display: "flex", gap: 8 }}>
                <input 
                  value={selectedProject || projectId} 
                  onChange={(e) => setSelectedProject(e.target.value)} 
                  placeholder="项目ID"
                  style={{ flex: 1 }}
                />
                <button className="topbar-btn" onClick={() => loadEvidence(selectedProject || projectId)}>加载</button>
                <button className="topbar-btn" onClick={() => { setTab("feedback"); }}>✍️ 写反馈</button>
              </div>
              {!evidence ? (
                <SkeletonLoader rows={3} type="card" />
              ) : evidence && evidence.project ? (
                <>
                  <p className="right-hint" style={{ animation: "fade-in 0.3s ease-out" }}>
                    📌 {evidence.project.project_name} | {evidence.project.category} | 置信度 {evidence.project.confidence ?? 0}
                  </p>
                  
                  {/* Neo4j Evidence Section */}
                  {evidence.evidence && evidence.evidence.length > 0 ? (
                    <div style={{ animation: "fade-in 0.4s ease-out" }}>
                      <h3 style={{ marginTop: 20, marginBottom: 10 }}>🗂️ 图数据库证据 ({evidence.evidence.length})</h3>
                      <div className="table-like">
                        {evidence.evidence.map((e: any, idx: number) => (
                          <div 
                            key={e.evidence_id} 
                            className="evidence-item"
                            style={{
                              animation: `fade-in 0.3s ease-out ${idx * 0.05}s both`,
                              transition: "all 0.2s ease",
                            }}
                          >
                            <strong style={{ color: "var(--accent-text)" }}>📝 {e.type}</strong>
                            <p style={{ margin: "8px 0" }}>{e.quote}</p>
                            <em style={{ color: "var(--text-muted)" }}>来源: {e.source_unit}</em>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div style={{ marginTop: 20, padding: 16, background: "var(--bg-card)", borderRadius: 8 }}>
                      <p style={{ fontSize: 12, color: "var(--text-muted)" }}>📭 Neo4j中暂无结构化证据数据</p>
                    </div>
                  )}
                  
                  {/* Student File Submissions Section */}
                  {evidence.file_submissions && evidence.file_submissions.length > 0 ? (
                    <div style={{ animation: "fade-in 0.5s ease-out" }}>
                      <h3 style={{ marginTop: 20, marginBottom: 10 }}>📤 学生提交文件 ({evidence.file_submissions.length})</h3>
                      <div className="table-like">
                        {evidence.file_submissions.map((s: any, idx: number) => (
                          <div 
                            key={s.submission_id} 
                            className="evidence-item" 
                            style={{ 
                              borderLeft: "3px solid var(--tch-success)",
                              animation: `fade-in 0.3s ease-out ${idx * 0.05}s both`,
                              transition: "all 0.2s ease",
                            }}
                          >
                            <strong>📄 {s.filename}</strong>
                            <p style={{ marginTop: 8, marginBottom: 10, fontSize: 12, color: "var(--text-secondary)" }}>
                              <em suppressHydrationWarning>学生: {s.student_id} | 提交时间: {s.created_at ? '已提交' : '未知'}</em>
                            </p>
                            
                            {/* Summary Section */}
                            {s.summary ? (
                              <p style={{ fontSize: 13, color: "var(--text-primary)", fontWeight: 500, marginBottom: 10, padding: "8px 10px", background: "var(--bg-card)", borderRadius: 4 }}>
                                {s.summary}
                              </p>
                            ) : null}
                            
                            {/* Diagnosis Details */}
                            {s.diagnosis && Object.keys(s.diagnosis).length > 0 ? (
                              <details style={{ fontSize: 12, marginTop: 8 }}>
                                <summary style={{ cursor: "pointer", color: "var(--accent-text)", fontWeight: 500 }}>📊 查看详细诊断信息</summary>
                                <div style={{ fontSize: 12, background: "var(--bg-card)", padding: 10, borderRadius: 4, marginTop: 8 }}>
                                  {s.diagnosis.overall_score !== undefined && (
                                    <p><strong>诊断评分:</strong> {s.diagnosis.overall_score.toFixed(2)}/5.0</p>
                                  )}
                                  {s.diagnosis.bottleneck && (
                                    <p><strong>核心瓶颈:</strong> {s.diagnosis.bottleneck}</p>
                                  )}
                                  {s.diagnosis.triggered_rules && s.diagnosis.triggered_rules.length > 0 ? (
                                    <p>
                                      <strong>触发规则:</strong> {s.diagnosis.triggered_rules.map((r: any) => (
                                        <span key={r.id} style={{ display: "inline-block", marginRight: 8, padding: "2px 6px", background: "var(--tch-danger-soft)", borderRadius: 3, fontSize: 11 }}>
                                          {r.id}: {r.name}
                                        </span>
                                      ))}
                                    </p>
                                  ) : null}
                                </div>
                              </details>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div style={{ marginTop: 20, padding: 16, background: "var(--bg-card)", borderRadius: 8 }}>
                      <p style={{ fontSize: 12, color: "var(--text-muted)" }}>📭 该项目暂无学生提交的文件</p>
                    </div>
                  )}
                  
                  {(!evidence.evidence || evidence.evidence.length === 0) && (!evidence.file_submissions || evidence.file_submissions.length === 0) && (
                    <p className="right-hint" style={{ marginTop: 20, padding: 20, textAlign: "center" }}>暂无任何证据数据</p>
                  )}
                </>
              ) : (
                <p className="right-hint" style={{ padding: 20, textAlign: "center" }}>
                  {!evidence ? "📌 请输入项目ID后点击'加载'按钮" : "❌ 项目信息加载失败，请检查项目ID是否正确或稍后重试"}
                </p>
              )}
            </div>
          )}

          {/* ── 智能报告 ── */}
          {tab === "report" && !loading && (
            <div className="tch-panel fade-up">
              <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
                <button onClick={() => setTab("class")} className="tch-back-btn">← 返回班级</button>
              </div>
              <h2>🤖 AI 班级报告</h2>
              <p className="tch-desc">由AI基于全班提交数据自动生成的评估报告，包含风险分布、共性问题和教学建议。可反复生成获取最新分析。</p>
              <button className="topbar-btn" onClick={generateReport} disabled={loading} style={{ marginBottom: 16, transition: "all 0.2s ease" }}>
                {loading ? "生成中…" : "🔄 重新生成"}
              </button>
              {!report ? (
                <SkeletonLoader rows={3} type="card" />
              ) : (
                <>
                  <div className="tch-report-content" style={{ animation: "fade-in 0.4s ease-out" }}>
                    {report}
                  </div>
                  {reportSnapshot && (
                    <details className="debug-json" style={{ marginTop: 16, animation: "fade-in 0.5s ease-out" }}>
                      <summary style={{ cursor: "pointer", color: "var(--accent-text)", fontWeight: "600" }}>📊 查看报告依据的原始数据</summary>
                      <pre style={{ marginTop: 12, padding: 12, background: "var(--bg-card)", borderRadius: 6, overflow: "auto", maxHeight: 400 }}>
                        {JSON.stringify(reportSnapshot, null, 2)}
                      </pre>
                    </details>
                  )}
                </>
              )}
              {!report && !loading && (
                <p className="right-hint" style={{ padding: 20, textAlign: "center" }}>
                  📌 点击上方按钮，系统将汇总所有学生的提交数据、风险分布和评分情况，生成一份班级分析报告。
                </p>
              )}
            </div>
          )}

          {/* ── 写回反馈 ── */}
          {tab === "feedback" && !loading && (
            <div className="tch-panel fade-up">
              <h2>📝 教师反馈 → 学生端</h2>
              <p className="tch-desc">支持三种反馈方式：1️⃣ 文本反馈（AI参考方向）2️⃣ 文件级批注（逐段评注） 3️⃣ 反馈文件上传（处理后的文件）</p>
              
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px", marginTop: "20px" }}>
                {/* 左侧：学生文件列表 + 文件查看 */}
                <div style={{ background: "var(--bg-card)", padding: "16px", borderRadius: "8px", border: "1px solid var(--border)" }}>
                  <h3 style={{ marginTop: 0, fontSize: "16px", color: "var(--text-primary)" }}>📤 学生提交文件</h3>
                  
                  <div style={{marginBottom: "16px"}}>
                    <input 
                      value={selectedProject || projectId} 
                      onChange={(e) => setSelectedProject(e.target.value)}
                      placeholder="项目ID"
                      style={{ width: "100%", padding: "8px", marginBottom: "8px", borderRadius: "8px", border: "1px solid var(--border)" }}
                    />
                    <button 
                      onClick={loadStudentFiles}
                      style={{
                        width: "100%",
                        padding: "8px 16px",
                        background: "var(--accent)",
                        color: "#fff",
                        border: "none",
                        borderRadius: "8px",
                        cursor: "pointer",
                        fontSize: "14px",
                      }}
                    >
                      🔄 刷新文件列表
                    </button>
                  </div>
                  
                  {studentFiles.length > 0 ? (
                    <div style={{ maxHeight: "400px", overflowY: "auto", marginBottom: "16px" }}>
                      {studentFiles.map((file, idx) => (
                        <div
                          key={idx}
                          onClick={() => loadFileContent(file.submission_id)}
                          style={{
                            padding: "12px",
                            marginBottom: "8px",
                            background: selectedFile?.submission_id === file.submission_id ? "var(--tch-accent-soft)" : "var(--bg-secondary)",
                            border: selectedFile?.submission_id === file.submission_id ? "2px solid var(--accent)" : "1px solid var(--border)",
                            borderRadius: "8px",
                            cursor: "pointer",
                            transition: "all 0.2s ease",
                          }}
                        >
                          <div style={{ fontSize: "13px", fontWeight: "600", color: "var(--text-primary)" }}>
                            {getFileTypeInfo(file.filename).icon} {file.filename}
                          </div>
                          <div style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "4px" }}>
                            {getFileTypeInfo(file.filename).displayName}
                          </div>
                          <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "4px" }}>
                            学生: {file.student_id} | 评分: <span style={{color: file.overall_score >= 7 ? "var(--tch-success)" : file.overall_score >= 5 ? "var(--tch-warning)" : "var(--tch-danger)"}}>{file.overall_score}</span>
                          </div>
                          <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>
                            <span suppressHydrationWarning>{file.created_at ? '已上传' : '未知'}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p style={{ fontSize: "13px", color: "var(--text-muted)", textAlign: "center", padding: "20px 0" }}>
                      📭 暂无学生文件提交，点击"刷新文件列表"查看
                    </p>
                  )}
                  
                  {/* 文件内容查看器 - 支持编辑 */}
                  {selectedFile && (
                    <div style={{marginTop: "12px"}}>
                      {/* 编辑模式切换 */}
                      <div style={{
                        display: "flex",
                        gap: "8px",
                        marginBottom: "8px",
                        flexWrap: "wrap"
                      }}>
                        <button
                          onClick={() => setIsEditMode(!isEditMode)}
                          style={{
                            padding: "6px 12px",
                            fontSize: "12px",
                            background: isEditMode ? "var(--tch-warning)" : "var(--bg-card-hover)",
                            color: isEditMode ? "#fff" : "var(--text-primary)",
                            border: "none",
                            borderRadius: "8px",
                            cursor: "pointer",
                            transition: "all 0.2s",
                          }}
                        >
                          {isEditMode ? "✏️ 编辑中" : "📖 查看"}
                        </button>
                        
                        {isEditMode && editedContent !== fileContent && (
                          <>
                            <button
                              onClick={() => setEditedContent(fileContent)}
                              style={{
                                padding: "6px 12px",
                                fontSize: "12px",
                                background: "var(--bg-card-hover)",
                                color: "var(--text-primary)",
                                border: "none",
                                borderRadius: "8px",
                                cursor: "pointer",
                              }}
                            >
                              ↩️ 撤销
                            </button>
                            <button
                              onClick={saveEditedDocument}
                              style={{
                                padding: "6px 12px",
                                fontSize: "12px",
                                background: "var(--tch-success)",
                                color: "#fff",
                                border: "none",
                                borderRadius: "8px",
                                cursor: "pointer",
                                fontWeight: "600",
                              }}
                            >
                              💾 保存编辑
                            </button>
                          </>
                        )}
                        
                        {!isEditMode && editedContent && editedContent !== fileContent && (
                          <>
                            <button
                              onClick={() => exportDocument('txt')}
                              style={{
                                padding: "6px 12px",
                                fontSize: "12px",
                                background: "var(--accent)",
                                color: "#fff",
                                border: "none",
                                borderRadius: "8px",
                                cursor: "pointer",
                              }}
                            >
                              📥 导出TXT
                            </button>
                          </>
                        )}
                      </div>
                      
                      {/* 编辑摘要输入 */}
                      {isEditMode && (
                        <input
                          value={editSummary}
                          onChange={(e) => setEditSummary(e.target.value)}
                          placeholder="编辑摘要（如：修正拼写错误）"
                          style={{
                            width: "100%",
                            padding: "6px",
                            marginBottom: "8px",
                            borderRadius: "8px",
                            border: "1px solid var(--border)",
                            fontSize: "12px",
                            boxSizing: "border-box",
                          }}
                        />
                      )}
                      
                      {/* 文件内容显示区域 - 根据文件类型智能显示 */}
                      {renderFilePreview(selectedFile, editedContent, isEditMode)}
                      
                      {/* 编辑历史 */}
                      {documentEdits.length > 0 && !isEditMode && (
                        <div style={{marginTop: "12px", paddingTop: "12px", borderTop: "1px solid var(--border)"}}>
                          <div style={{fontSize: "12px", fontWeight: "600", color: "var(--text-primary)", marginBottom: "6px"}}>📝 编辑历史：</div>
                          <div style={{maxHeight: "150px", overflowY: "auto"}}>
                            {documentEdits.slice(0, 5).map((edit, idx) => (
                              <div key={idx} style={{fontSize: "11px", padding: "6px", marginBottom: "4px", background: "var(--bg-card)", borderRadius: "3px", borderLeft: "3px solid var(--accent)"}}>
                                <div style={{color: "var(--text-primary)"}}>{edit.edit_summary || "文档编辑"}</div>
                                <div style={{color: "var(--text-muted)", marginTop: "2px"}}>
                                  {edit.edited_length || 0} 字符 · <span suppressHydrationWarning>{edit.created_at ? '已编辑' : '未知'}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
                
                {/* 右侧：反馈和批注 */}
                <div style={{ background: "var(--bg-card)", padding: "16px", borderRadius: "8px", border: "1px solid var(--border)" }}>
                  <h3 style={{ marginTop: 0, fontSize: "16px", color: "var(--text-primary)" }}>✏️ 添加批注 & 反馈</h3>
                  
                  {selectedFile ? (
                    <>
                      {/* 文本级反馈 */}
                      <div style={{marginBottom: "16px"}}>
                        <label style={{fontSize: "13px", fontWeight: "600", color: "var(--text-primary)", display: "block", marginBottom: "6px"}}>📝 文本反馈</label>
                        <textarea 
                          value={feedbackText} 
                          onChange={(e) => setFeedbackText(e.target.value)}
                          placeholder="写出对项目的整体反馈..." 
                          rows={3}
                          style={{
                            width: "100%",
                            padding: "8px",
                            borderRadius: "8px",
                            border: "1px solid var(--border)",
                            fontSize: "13px",
                            boxSizing: "border-box",
                          }}
                        />
                        <div style={{fontSize: "12px", color: "var(--text-secondary)", marginTop: "4px"}}>
                          关注标签：
                          <input 
                            value={feedbackTags} 
                            onChange={(e) => setFeedbackTags(e.target.value)}
                            placeholder="evidence,business_model,compliance"
                            style={{
                              width: "100%",
                              padding: "4px",
                              marginTop: "4px",
                              borderRadius: "3px",
                              border: "1px solid var(--border)",
                              fontSize: "12px",
                            }}
                          />
                        </div>
                        <button 
                          onClick={submitFeedback}
                          style={{
                            width: "100%",
                            padding: "8px",
                            marginTop: "8px",
                            background: "var(--tch-success)",
                            color: "#fff",
                            border: "none",
                            borderRadius: "8px",
                            cursor: "pointer",
                            fontSize: "13px",
                            fontWeight: "600",
                          }}
                        >
                          💬 提交文本反馈
                        </button>
                      </div>
                      
                      {/* 批注 */}
                      <div style={{marginBottom: "16px", borderTop: "1px solid var(--border)", paddingTop: "12px"}}>
                        <label style={{fontSize: "13px", fontWeight: "600", color: "var(--text-primary)", display: "block", marginBottom: "6px"}}>🎯 段落批注</label>
                        <select 
                          value={annotationType}
                          onChange={(e) => setAnnotationType(e.target.value)}
                          style={{
                            width: "100%",
                            padding: "6px",
                            marginBottom: "8px",
                            borderRadius: "3px",
                            border: "1px solid var(--border)",
                            fontSize: "12px",
                          }}
                        >
                          <option value="praise">👍 亮点</option>
                          <option value="issue">⚠️ 问题</option>
                          <option value="suggest">💡 建议</option>
                          <option value="question">❓ 追问</option>
                        </select>
                        <textarea 
                          value={annotationText} 
                          onChange={(e) => setAnnotationText(e.target.value)}
                          placeholder="写出对本段内容的批注..."
                          rows={2}
                          style={{
                            width: "100%",
                            padding: "6px",
                            borderRadius: "3px",
                            border: "1px solid var(--border)",
                            fontSize: "12px",
                            boxSizing: "border-box",
                          }}
                        />
                        <button 
                          onClick={saveAnnotation}
                          style={{
                            width: "100%",
                            padding: "6px",
                            marginTop: "6px",
                            background: "var(--tch-warning)",
                            color: "#fff",
                            border: "none",
                            borderRadius: "3px",
                            cursor: "pointer",
                            fontSize: "12px",
                          }}
                        >
                          ✓ 保存批注
                        </button>
                      </div>
                      
                      {/* 上传反馈文件 */}
                      <div style={{borderTop: "1px solid var(--border)", paddingTop: "12px"}}>
                        <label style={{fontSize: "13px", fontWeight: "600", color: "var(--text-primary)", display: "block", marginBottom: "6px"}}>📎 上传反馈文件</label>
                        <input 
                          ref={feedbackFileInputRef}
                          type="file"
                          accept=".pdf,.docx,.pptx,.txt"
                          onChange={(e) => setFeedbackFileToUpload(e.target.files?.[0] || null)}
                          style={{width: "100%", marginBottom: "6px"}}
                        />
                        {feedbackFileToUpload && (
                          <div style={{fontSize: "12px", color: "var(--text-secondary)", marginBottom: "6px"}}>
                            ✓ 已选择: {feedbackFileToUpload.name}
                          </div>
                        )}
                        <button 
                          onClick={uploadFeedbackFile}
                          disabled={!feedbackFileToUpload}
                          style={{
                            width: "100%",
                            padding: "6px",
                            background: feedbackFileToUpload ? "var(--accent)" : "var(--bg-card-hover)",
                            color: "#fff",
                            border: "none",
                            borderRadius: "3px",
                            cursor: feedbackFileToUpload ? "pointer" : "not-allowed",
                            fontSize: "12px",
                          }}
                        >
                          📤 上传反馈文件
                        </button>
                      </div>
                      
                      {/* 已上传的反馈文件列表 */}
                      {feedbackFiles.length > 0 && (
                        <div style={{marginTop: "12px", borderTop: "1px solid var(--border)", paddingTop: "12px"}}>
                          <div style={{fontSize: "12px", fontWeight: "600", color: "var(--text-primary)", marginBottom: "6px"}}>已上传反馈文件：</div>
                          {feedbackFiles.map((file, idx) => (
                            <div key={idx} style={{fontSize: "11px", color: "var(--text-secondary)", padding: "4px", marginBottom: "4px", background: "var(--bg-secondary)", borderRadius: "3px"}}>
                              📄 {file.original_filename} &nbsp; <a href={`${API}${file.file_url}`} target="_blank" style={{color: "var(--accent)"}}>下载</a>
                            </div>
                          ))}
                        </div>
                      )}
                      
                      {/* 批注列表 */}
                      {feedbackAnnotations.length > 0 && (
                        <div style={{marginTop: "12px", borderTop: "1px solid var(--border)", paddingTop: "12px"}}>
                          <div style={{fontSize: "12px", fontWeight: "600", color: "var(--text-primary)", marginBottom: "6px"}}>已保存的批注：</div>
                          <div style={{maxHeight: "200px", overflowY: "auto"}}>
                            {feedbackAnnotations.map((ann, idx) => (
                              <div key={idx} style={{fontSize: "11px", padding: "6px", marginBottom: "6px", background: "var(--bg-secondary)", borderRadius: "3px", borderLeft: "3px solid var(--tch-warning)"}}>
                                <div style={{color: "var(--text-secondary)"}}>{ann.overall_feedback || (ann.annotations?.[0]?.content || "")}</div>
                                <div style={{color: "var(--text-muted)", marginTop: "2px"}} suppressHydrationWarning>{ann.created_at ? '已添加' : '未知'}</div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  ) : (
                    <p style={{ fontSize: "13px", color: "var(--text-muted)", textAlign: "center", padding: "40px 20px" }}>
                      👈 请从左侧选择一个学生文件以开始批注
                    </p>
                  )}
                </div>
              </div>
              
              {successMessage && <SuccessToast message={successMessage} onClose={() => setSuccessMessage("")} />}
              {errorMessage && <ErrorToast message={errorMessage} onClose={() => setErrorMessage("")} />}
            </div>
          )}

          {/* ── 能力映射雷达图 ── */}
          {tab === "capability" && !loading && (
            <div className="tch-panel fade-up">
              <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
                <button onClick={() => setTab("class")} className="tch-back-btn">← 返回班级</button>
              </div>
              <h2>🎯 班级能力映射</h2>
              <p className="tch-desc">基于5个维度（痛点发现、方案策划、商业建模、资源杠杆、路演表达）评估班级整体能力水平。雷达图越接近外圆表示能力越强。</p>
              {!capabilityMap?.dimensions ? (
                <SkeletonLoader rows={3} type="bar" />
              ) : (
                <>
                  <div className="viz-grid" style={{ animation: "fade-in 0.4s ease-out" }}>
                    <div className="viz-card">
                      <h3>📊 班级能力分布（满分10）</h3>
                      <p className="tch-desc">班级平均成绩</p>
                      {(capabilityMap.dimensions ?? []).length === 0 ? (
                        <p style={{ color: "var(--text-muted)", fontSize: 12 }}>暂无维度数据</p>
                      ) : (
                        (capabilityMap.dimensions ?? []).map((dim: any, idx: number) => (
                          <div 
                            key={dim.name} 
                            className="bar-row"
                            style={{
                              animation: `fade-in 0.3s ease-out ${idx * 0.08}s both`,
                              transition: "all 0.2s ease",
                            }}
                          >
                            <span>{dim.name}</span>
                            <div className="bar-track">
                              <div 
                                className="bar-fill" 
                                style={{ width: `${(dim.score / dim.max) * 100}%`, transition: "width 0.4s ease" }} 
                              />
                            </div>
                            <em style={{ fontWeight: "600", color: dim.score >= 7 ? "var(--tch-success)" : dim.score >= 5 ? "var(--tch-warning)" : "var(--tch-danger)" }}>
                              {dim.score.toFixed(1)}
                            </em>
                          </div>
                        ))
                      )}
                    </div>
                    <div className="viz-card" style={{ animation: "fade-in 0.5s ease-out" }}>
                      <h3>🔍 维度强弱对比</h3>
                      <p className="tch-desc">找出班级的短板（得分最低的维度）并重点补强</p>
                      {(() => {
                        const sorted = [...(capabilityMap.dimensions ?? [])].sort((a, b) => a.score - b.score);
                        return sorted.length === 0 ? (
                          <p style={{ color: "var(--text-muted)", fontSize: 12 }}>暂无数据</p>
                        ) : (
                          <div>
                            {sorted.slice(0, 3).map((dim: any, i: number) => (
                              <div 
                                key={dim.name} 
                                className="bar-row"
                                style={{
                                  animation: `fade-in 0.3s ease-out ${i * 0.1}s both`,
                                  padding: "8px 12px",
                                  background: i === 0 ? "var(--tch-danger-soft)" : i === 1 ? "var(--tch-warning-soft)" : "var(--tch-success-soft)",
                                  borderRadius: 4,
                                  marginBottom: 8
                                }}
                              >
                                <span>{i === 0 ? "🔴 最弱" : i === 1 ? "🟡 较弱" : "🟢 需强化"}</span>
                                <span style={{ fontWeight: "600", flex: 1 }}>{dim.name}</span>
                                <strong style={{ color: i === 0 ? "var(--tch-danger)" : i === 1 ? "var(--tch-warning)" : "var(--tch-success)" }}>
                                  {dim.score.toFixed(1)}
                                </strong>
                              </div>
                            ))}
                          </div>
                        );
                      })()}
                    </div>
                  </div>
                </>
              )}
              {!capabilityMap && <p className="right-hint" style={{ padding: 20, textAlign: "center" }}>加载中或暂无数据...请确保班级已有学生提交。</p>}
            </div>
          )}

          {/* ── 规则检查热力图 ── */}
          {tab === "rule-coverage" && !loading && (
            <div className="tch-panel fade-up">
              <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
                <button onClick={() => setTab("class")} className="tch-back-btn">← 返回班级</button>
              </div>
              <h2>🔥 规则检查覆盖率</h2>
              <p className="tch-desc">15条关键业务规则（H1-H15）的触发统计。热力图显示哪些规则在班级中最常被触发，即班级共性风险点。</p>
              {!ruleCoverage?.rule_coverage ? (
                <SkeletonLoader rows={5} type="table" />
              ) : (
                <>
                  <div style={{ marginBottom: 16, padding: 12, background: "var(--bg-card)", borderRadius: 8, animation: "fade-in 0.3s ease-out" }}>
                    <strong>⚠️ 高危规则：</strong>
                    <span style={{ fontSize: 18, fontWeight: "bold", color: "var(--tch-danger)", marginLeft: 8 }}>
                      {ruleCoverage.high_risk_count}
                    </span>
                    <span style={{ marginLeft: 16 }}> | </span>
                    <strong style={{ marginLeft: 16 }}>📊 总提交数：</strong>
                    <span style={{ fontSize: 18, fontWeight: "bold", color: "var(--accent)", marginLeft: 8 }}>
                      {ruleCoverage.total_submissions}
                    </span>
                  </div>
                  <div className="tch-table" style={{ animation: "fade-in 0.4s ease-out" }}>
                    <div className="tch-table-header">
                      <span>规则ID</span><span>规则名称</span><span>触发次数</span><span>覆盖率</span><span>风险等级</span>
                    </div>
                    {ruleCoverage.rule_coverage.length === 0 ? (
                      <p style={{ color: "var(--text-muted)", fontSize: 12, padding: 20 }}>暂无规则覆盖率数据</p>
                    ) : (
                      ruleCoverage.rule_coverage.map((rule: any, idx: number) => (
                        <div 
                          key={rule.rule_id} 
                          className="tch-table-row"
                          style={{
                            animation: `fade-in 0.3s ease-out ${idx * 0.05}s both`,
                            backgroundColor: rule.severity === "high" ? "var(--tch-danger-soft)" : rule.severity === "medium" ? "var(--tch-warning-soft)" : "var(--bg-card)",
                            transition: "all 0.2s ease",
                          }}
                        >
                          <span className="tch-cell-time" style={{ fontWeight: "bold" }}>{rule.rule_id}</span>
                          <span>{rule.rule_name}</span>
                          <span style={{ fontWeight: "600" }}>{rule.hit_count}</span>
                          <span>
                            <div className="bar-track" style={{ width: 100, height: 20, display: "inline-block", marginRight: 8 }}>
                              <div 
                                className="bar-fill" 
                                style={{ 
                                  width: `${(rule.coverage_ratio * 100)}%`, 
                                  height: "100%",
                                  backgroundColor: rule.severity === "high" ? "var(--tch-danger)" : rule.severity === "medium" ? "var(--tch-warning)" : "var(--tch-success)"
                                }} 
                              />
                            </div>
                            {(rule.coverage_ratio * 100).toFixed(1)}%
                          </span>
                          <span className={rule.severity === "high" ? "risk-badge high" : rule.severity === "medium" ? "risk-badge" : "risk-badge low"}>
                            {rule.severity === "high" ? "🔴 高" : rule.severity === "medium" ? "🟡 中" : "🟢 低"}
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                </>
              )}
              {!ruleCoverage && <p className="right-hint" style={{ padding: 20, textAlign: "center" }}>加载中或暂无数据...</p>}
            </div>
          )}

          {/* ── Rubric 评分与项目诊断 ── */}
          {tab === "rubric" && !loading && (
            <div className="tch-panel fade-up">
              <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
                <button onClick={() => setTab("project")} className="tch-back-btn">← 返回项目</button>
              </div>
              <h2>📋 Rubric评分与项目诊断</h2>
              <p className="tch-desc">针对单个项目的深度评估，包括9个维度（R1-R9）的Rubric评分，触发的规则及修复建议。</p>
              <div style={{ marginBottom: 16, display: "flex", gap: 8 }}>
                <input 
                  value={selectedProject || projectId} 
                  onChange={(e) => setSelectedProject(e.target.value)} 
                  placeholder="项目ID"
                  style={{ marginRight: 0, flex: 1 }}
                />
                <button className="topbar-btn" onClick={loadRubricAssessment}>加载评分</button>
              </div>

              {!rubricAssessment?.rubric_items ? (
                <SkeletonLoader rows={3} type="table" />
              ) : (
                <div style={{ animation: "fade-in 0.4s ease-out" }}>
                  <div className="kpi-grid">
                    <div className="kpi">
                      <span>⭐ 加权总分</span>
                      <strong style={{ fontSize: 32, color: "var(--tch-warning)" }}>
                        {rubricAssessment.overall_weighted_score}
                      </strong>
                      <em>满分5分</em>
                    </div>
                  </div>

                  <h3 style={{ marginTop: 24, marginBottom: 12 }}>各维度评分详情</h3>
                  <div className="tch-table" style={{ animation: "fade-in 0.5s ease-out" }}>
                    <div className="tch-table-header">
                      <span>维度</span><span>得分</span><span>权重</span><span>修改建议</span>
                    </div>
                    {rubricAssessment.rubric_items.length === 0 ? (
                      <p style={{ color: "var(--text-muted)", fontSize: 12, padding: 20 }}>暂无评分数据</p>
                    ) : (
                      rubricAssessment.rubric_items.map((item: any, idx: number) => (
                        <div 
                          key={item.item_id} 
                          className="tch-table-row"
                          style={{
                            animation: `fade-in 0.3s ease-out ${idx * 0.05}s both`,
                            backgroundColor: Number(item.score) >= item.max_score * 0.7 ? "var(--tch-success-soft)" : 
                                           Number(item.score) >= item.max_score * 0.5 ? "var(--tch-warning-soft)" : "var(--tch-danger-soft)",
                            transition: "all 0.2s ease",
                          }}
                        >
                          <span><strong>{item.item_id}</strong> {item.item_name}</span>
                          <span style={{ fontWeight: "600", color: Number(item.score) >= item.max_score * 0.7 ? "var(--tch-success)" : "var(--tch-warning)" }}>
                            {item.score}/{item.max_score}
                          </span>
                          <span>{(item.weight * 100).toFixed(0)}%</span>
                          <span style={{ fontSize: "0.9em", color: "var(--text-secondary)" }}>{item.revision_suggestion}</span>
                        </div>
                      ))
                    )}
                  </div>

                  {projectDiagnosis?.fix_strategies && projectDiagnosis.fix_strategies.length > 0 && (
                    <>
                      <h3 style={{ marginTop: 24, marginBottom: 12 }}>🔧 关键风险修复方案</h3>
                      {projectDiagnosis.fix_strategies.map((fix: any, idx: number) => (
                        <div 
                          key={fix.rule_id} 
                          className="right-tag" 
                          style={{ 
                            marginBottom: 8,
                            animation: `fade-in 0.3s ease-out ${idx * 0.08}s both`,
                            transition: "all 0.2s ease"
                          }}
                        >
                          <strong>{fix.rule_id}</strong> {fix.rule_name} → {fix.fix_strategy}
                        </div>
                      ))}
                    </>
                  )}
                </div>
              )}
              {!rubricAssessment && <p className="right-hint" style={{ padding: 20, textAlign: "center" }}>📌 选择项目后点击"加载评分"获取详细评估...</p>}
            </div>
          )}

          {/* ── 竞赛评分预测 ── */}
          {tab === "competition" && !loading && (
            <div className="tch-panel fade-up">
              <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
                <button onClick={() => setTab("project")} className="tch-back-btn">← 返回项目</button>
              </div>
              <h2>🏆 竞赛评分预测</h2>
              <p className="tch-desc">基于项目当前状态预测在竞赛中的得分（0-100分），并给出24小时和72小时的快速修复清单。</p>
              <div style={{ marginBottom: 16, display: "flex", gap: 8 }}>
                <input 
                  value={selectedProject || projectId} 
                  onChange={(e) => setSelectedProject(e.target.value)} 
                  placeholder="项目ID"
                  style={{ marginRight: 0, flex: 1 }}
                />
                <button className="topbar-btn" onClick={loadCompetitionScore}>预测评分</button>
              </div>

              {!competitionScore ? (
                <SkeletonLoader rows={2} type="card" />
              ) : competitionScore?.predicted_competition_score !== undefined ? (
                <div style={{ animation: "fade-in 0.4s ease-out" }}>
                  <div className="kpi-grid">
                    <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                      <span>🎯 预测竞赛评分</span>
                      <strong 
                        style={{ 
                          fontSize: 40, 
                          color: competitionScore.predicted_competition_score >= 75 ? "var(--tch-success)" : 
                                 competitionScore.predicted_competition_score >= 60 ? "var(--tch-warning)" : "var(--tch-danger)",
                          animation: "number-scale 0.6s ease-out"
                        }}
                      >
                        {competitionScore.predicted_competition_score}
                      </strong>
                      <em>
                        预测范围：
                        {typeof competitionScore.score_range === 'string' 
                          ? competitionScore.score_range 
                          : `${competitionScore.score_range_min || competitionScore.score_range?.[0]}-${competitionScore.score_range_max || competitionScore.score_range?.[1]}`}
                        分
                      </em>
                      <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 8 }}>
                        <strong>📌 评分说明：</strong>基于项目诊断评分、触发规则数量等因素综合计算。
                      </p>
                    </div>
                  </div>

                  <h3 style={{ marginTop: 24, marginBottom: 12, fontSize: 18 }}>⚡ 24小时快速修复（最关键的3项）</h3>
                  <ul style={{ paddingLeft: 20, lineHeight: 2, background: "var(--tch-accent-soft)", padding: 16, borderRadius: 8, borderLeft: "3px solid var(--accent)" }}>
                    {(competitionScore.quick_fixes_24h ?? []).map((fix: string, i: number) => (
                      <li key={i} style={{ animation: `fade-in 0.3s ease-out ${i * 0.1}s both` }}>✓ {fix}</li>
                    ))}
                  </ul>

                  <h3 style={{ marginTop: 24, marginBottom: 12, fontSize: 18 }}>📋 72小时完整改进方案</h3>
                  <ul style={{ paddingLeft: 20, lineHeight: 2, background: "var(--bg-card)", padding: 16, borderRadius: 8, borderLeft: "3px solid var(--text-muted)" }}>
                    {(competitionScore.quick_fixes_72h ?? []).map((fix: string, i: number) => (
                      <li key={i} style={{ animation: `fade-in 0.3s ease-out ${i * 0.1}s both` }}>→ {fix}</li>
                    ))}
                  </ul>

                  {competitionScore.high_risk_rules_for_competition?.length > 0 && (
                    <>
                      <h3 style={{ marginTop: 24, marginBottom: 12, fontSize: 18 }}>🔴 竞赛评审关注的高风险规则</h3>
                      <div style={{ 
                        display: "grid", 
                        gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                        gap: 12,
                        padding: "12px",
                        background: "var(--tch-danger-soft)",
                        borderRadius: "10px",
                        borderLeft: "3px solid var(--tch-danger)",
                        animation: "fade-in 0.5s ease-out"
                      }}>
                        {competitionScore.high_risk_rules_for_competition.map((rule: any, idx: number) => (
                          <div 
                            key={rule.rule} 
                            style={{ 
                              padding: "10px 12px", 
                              background: "var(--bg-card)",
                              border: "1px solid var(--border)",
                              borderRadius: "8px",
                              boxShadow: "var(--shadow-sm, 0 1px 3px rgba(0,0,0,0.08))",
                              display: "flex",
                              alignItems: "center",
                              gap: "8px",
                              animation: `fade-in 0.3s ease-out ${idx * 0.05}s both`,
                              transition: "all 0.2s ease",
                            }}
                          >
                            <span style={{ 
                              display: "inline-block",
                              background: "var(--tch-danger)",
                              color: "#fff",
                              padding: "4px 8px",
                              borderRadius: "8px",
                              fontSize: "12px",
                              fontWeight: "bold",
                              minWidth: "32px",
                              textAlign: "center"
                            }}>
                              {rule.rule}
                            </span>
                            <span style={{ fontSize: "12px", color: "var(--text-secondary)", flex: 1 }}>
                              {rule.name}
                            </span>
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              ) : (
                <p className="right-hint" style={{ padding: 20, textAlign: "center" }}>📌 选择项目后点击"预测评分"获取优化建议...</p>
              )}
            </div>
          )}

          {/* ── 教学干预建议 ── */}
          {tab === "interventions" && !loading && (
            <div className="tch-panel fade-up">
              <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
                <button onClick={() => setTab("class")} className="tch-back-btn">← 返回班级</button>
              </div>
              <h2>💡 教学干预建议</h2>
              <p className="tch-desc">基于全班共性问题智能生成的教学干预优先级清单。系统识别出现在40%以上学生提交中的问题，并给出针对性教学方案。</p>
              <button className="topbar-btn" onClick={loadTeachingInterventions} disabled={loading} style={{ marginBottom: 16, transition: "all 0.2s ease" }}>
                {loading ? "分析中…" : "🔄 刷新分析"}
              </button>

              {!teachingInterventions?.shared_problems ? (
                <SkeletonLoader rows={3} type="card" />
              ) : (
                <div style={{ animation: "fade-in 0.4s ease-out" }}>
                  <div className="kpi-grid">
                    <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                      <span>👥 班级规模</span>
                      <strong style={{ fontSize: 28 }}>{teachingInterventions.student_count ?? 0}</strong>
                      <em>学生数</em>
                    </div>
                    <div className="kpi" style={{ transition: "all 0.3s ease" }}>
                      <span>🚨 共性问题</span>
                      <strong style={{ fontSize: 28, color: "var(--tch-danger)" }}>
                        {teachingInterventions.total_shared_problems ?? 0}
                      </strong>
                      <em>需干预</em>
                    </div>
                  </div>

                  <h3 style={{ marginTop: 24, marginBottom: 12 }}>⚡ 优先级教学方案</h3>
                  {teachingInterventions.shared_problems.length === 0 ? (
                    <p style={{ color: "var(--text-muted)", fontSize: 12, padding: 20, textAlign: "center" }}>暂无共性问题识别</p>
                  ) : (
                    teachingInterventions.shared_problems.map((problem: any, idx: number) => (
                      <div 
                        key={problem.rule_id} 
                        className="viz-card"
                        style={{
                          animation: `fade-in 0.3s ease-out ${idx * 0.08}s both`,
                          borderLeft: `3px solid ${problem.priority === "高" ? "var(--tch-danger)" : problem.priority === "中" ? "var(--tch-warning)" : "var(--tch-success)"}`,
                          transition: "all 0.2s ease",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                          <strong style={{ fontSize: 16 }}>
                            {problem.rule_id}: {problem.problem_description}
                          </strong>
                          <span className={problem.priority === "高" ? "risk-badge high" : problem.priority === "中" ? "risk-badge" : "risk-badge low"}>
                            {problem.priority}优先级
                          </span>
                        </div>
                        <p style={{ marginBottom: 8 }}>
                          <strong>📚 教学建议：</strong>{problem.teaching_suggestion}
                        </p>
                        <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
                          <em>⏱️ 预计课时：{problem.estimated_teaching_time}</em>
                        </p>
                      </div>
                    ))
                  )}

                  <h3 style={{ marginTop: 24, marginBottom: 12 }}>📅 下周课程设计建议</h3>
                  <p 
                    className="right-tag"
                    style={{
                      animation: "fade-in 0.5s ease-out",
                      background: "var(--tch-accent-soft)",
                      color: "var(--text-primary)",
                      padding: 16,
                      borderRadius: 10,
                      borderLeft: "3px solid var(--accent)",
                    }}
                  >
                    ✨ {teachingInterventions.recommended_next_class_focus}
                  </p>
                </div>
              )}
              {!teachingInterventions && <p className="right-hint" style={{ padding: 20, textAlign: "center" }}>加载中或暂无数据...</p>}
            </div>
          )}

          {/* ── 班级管理 ── */}
          {tab === "project" && (
            <div className="tch-panel fade-up">
              <h2>🎯 项目管理</h2>
              <p className="tch-desc">输入项目ID以访问项目级别的评分、诊断和竞赛预测。</p>

              {!projectIdConfirmed ? (
                <div style={{ padding: "32px", textAlign: "center", animation: "fade-in 0.3s ease-out" }}>
                  <div style={{ maxWidth: "400px", margin: "0 auto" }}>
                    <input
                      type="text"
                      placeholder="请输入项目 ID"
                      value={projectTabInput}
                      onChange={(e) => setProjectTabInput(e.target.value)}
                      style={{
                        width: "100%",
                        padding: "12px 16px",
                        fontSize: "16px",
                        marginBottom: "16px",
                        boxSizing: "border-box",
                        border: "1px solid var(--border)",
                        borderRadius: "10px",
                      }}
                      onKeyPress={(e) => {
                        if (e.key === "Enter" && projectTabInput.trim()) {
                          setSelectedProject(projectTabInput);
                          setProjectIdConfirmed(true);
                        }
                      }}
                    />
                    <button
                      onClick={() => {
                        if (projectTabInput.trim()) {
                          setSelectedProject(projectTabInput);
                          setProjectIdConfirmed(true);
                        }
                      }}
                      style={{
                        width: "100%",
                        padding: "12px 16px",
                        fontSize: "16px",
                        background: projectTabInput.trim() ? "var(--accent)" : "var(--bg-card-hover)",
                        color: projectTabInput.trim() ? "#fff" : "var(--text-muted)",
                        border: "none",
                        borderRadius: "10px",
                        cursor: projectTabInput.trim() ? "pointer" : "not-allowed",
                        transition: "all 0.2s",
                      }}
                      disabled={!projectTabInput.trim()}
                    >
                      确认项目ID
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="tch-info-banner">
                    <p style={{ margin: "0" }}>
                      <strong>当前项目 ID：</strong> {selectedProject}
                      <button
                        onClick={() => setProjectIdConfirmed(false)}
                        className="tch-back-btn"
                        style={{ marginLeft: 16, fontSize: 12 }}
                      >
                        切换项目
                      </button>
                    </p>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "12px", marginBottom: "32px" }}>
                    {PROJECT_SUB_TABS.map((subTab) => (
                      <button
                        key={subTab.id}
                        className="tch-sub-tab-btn"
                        onClick={() => {
                          setTab(subTab.id as Tab);
                          if (subTab.id === "rubric") loadProjectDiagnosis();
                          if (subTab.id === "competition") loadCompetitionScore();
                          if (subTab.id === "evidence") loadEvidence(selectedProject);
                        }}
                      >
                        {subTab.label}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {tab === "class" && (
            <div className="tch-panel fade-up">
              <h2>🏫 班级管理</h2>
              <p className="tch-desc">输入班级ID以访问班级级别的数据分析和教学建议。</p>

              {!classIdConfirmed ? (
                <div style={{ padding: "32px", textAlign: "center", animation: "fade-in 0.3s ease-out" }}>
                  <div style={{ maxWidth: "400px", margin: "0 auto" }}>
                    <input
                      type="text"
                      placeholder="请输入班级 ID"
                      value={classTabInput}
                      onChange={(e) => setClassTabInput(e.target.value)}
                      style={{
                        width: "100%",
                        padding: "12px 16px",
                        fontSize: "16px",
                        marginBottom: "16px",
                        boxSizing: "border-box",
                        border: "1px solid var(--border)",
                        borderRadius: "10px",
                      }}
                      onKeyPress={(e) => {
                        if (e.key === "Enter" && classTabInput.trim()) {
                          setClassId(classTabInput);
                          setClassIdConfirmed(true);
                        }
                      }}
                    />
                    <button
                      onClick={() => {
                        if (classTabInput.trim()) {
                          setClassId(classTabInput);
                          setClassIdConfirmed(true);
                        }
                      }}
                      style={{
                        width: "100%",
                        padding: "12px 16px",
                        fontSize: "16px",
                        background: classTabInput.trim() ? "var(--accent)" : "var(--bg-card-hover)",
                        color: classTabInput.trim() ? "#fff" : "var(--text-muted)",
                        border: "none",
                        borderRadius: "10px",
                        cursor: classTabInput.trim() ? "pointer" : "not-allowed",
                        transition: "all 0.2s",
                      }}
                      disabled={!classTabInput.trim()}
                    >
                      确认班级ID
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="tch-info-banner">
                    <p style={{ margin: "0" }}>
                      <strong>当前班级 ID：</strong> {classId}
                      <button
                        onClick={() => setClassIdConfirmed(false)}
                        className="tch-back-btn"
                        style={{ marginLeft: 16, fontSize: 12 }}
                      >
                        切换班级
                      </button>
                    </p>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "12px", marginBottom: "32px" }}>
                    {CLASS_SUB_TABS.map((subTab) => (
                      <button
                        key={subTab.id}
                        className="tch-sub-tab-btn"
                        onClick={() => {
                          setTab(subTab.id as Tab);
                          if (subTab.id === "compare") loadCompare();
                          if (subTab.id === "capability") loadCapabilityMap();
                          if (subTab.id === "rule-coverage") loadRuleCoverage();
                          if (subTab.id === "interventions") loadTeachingInterventions();
                          if (subTab.id === "report") generateReport();
                        }}
                      >
                        {subTab.label}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
        </main>
      </div>

      <style>{`
        .tch-app {
          background: var(--bg-primary);
          color: var(--text-primary);
          --skeleton-bg: var(--bg-card);
          --tch-accent: var(--accent);
          --tch-accent-soft: var(--accent-soft);
          --tch-accent-text: var(--accent-text);
          --tch-success: #5cbd8a;
          --tch-danger: #e07070;
          --tch-warning: #e0a84c;
          --tch-success-soft: rgba(92,189,138,0.12);
          --tch-danger-soft: rgba(224,112,112,0.12);
          --tch-warning-soft: rgba(224,168,76,0.12);
        }

        .tch-body { display: flex; background: var(--bg-primary); min-height: calc(100vh - 56px); }

        .tch-app h1,.tch-app h2,.tch-app h3,.tch-app h4,.tch-app h5 { color: var(--heading-color); }
        .tch-app p,.tch-app span,.tch-app div { color: var(--text-primary); }

        .tch-sidebar {
          background: var(--bg-secondary);
          border-right: 1px solid var(--border);
          min-width: 220px; overflow-y: auto; max-height: calc(100vh - 56px); padding: 12px 8px;
        }
        .tch-nav-btn {
          background: transparent; color: var(--text-secondary); border: none;
          border-left: 3px solid transparent; padding: 11px 14px; width: 100%;
          text-align: left; cursor: pointer; font-weight: 500; font-size: 13.5px;
          transition: all 0.2s; margin: 2px 0; border-radius: 0 8px 8px 0;
        }
        .tch-nav-btn:hover:not(.disabled) { background: var(--bg-card-hover); color: var(--text-primary); }
        .tch-nav-btn.active { background: var(--tch-accent-soft); color: var(--tch-accent-text); border-left-color: var(--tch-accent); font-weight: 600; }
        .tch-nav-btn.disabled { opacity: 0.5; cursor: not-allowed; }

        .tch-main {
          background: var(--bg-primary); padding: 28px 36px; flex: 1;
          overflow-y: auto; max-height: calc(100vh - 56px);
          display: flex; flex-direction: column; align-items: center;
        }
        .tch-main > * { width: 100%; max-width: 1100px; margin: 0 auto; }

        .tch-panel {
          background: var(--bg-card); border: 1px solid var(--border);
          border-radius: 16px; padding: 28px 32px; margin-bottom: 24px;
          animation: fade-up 0.3s ease-out;
        }
        .tch-panel h2 {
          color: var(--heading-color); font-size: 22px; margin: 0 0 16px;
          padding-bottom: 12px; border-bottom: 1px solid var(--border); font-weight: 700;
        }
        .tch-panel h3 { color: var(--text-primary); font-size: 16px; margin: 24px 0 12px; font-weight: 600; }
        .tch-desc { color: var(--text-secondary); font-size: 13.5px; line-height: 1.7; margin-bottom: 16px; }

        .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .kpi {
          background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px;
          padding: 24px 20px; text-align: center; transition: all 0.25s;
          display: flex; flex-direction: column; justify-content: center;
        }
        .kpi:hover { background: var(--bg-card-hover); border-color: var(--border-strong); transform: translateY(-2px); }
        .kpi span { display: block; color: var(--text-secondary); font-size: 12px; font-weight: 600; letter-spacing: 0.5px; margin-bottom: 8px; }
        .kpi strong { display: block; color: var(--text-primary); font-size: 32px; font-weight: 700; margin-bottom: 8px; line-height: 1.2; }
        .kpi em { display: block; color: var(--text-muted); font-size: 12px; font-style: normal; margin-top: 4px; }
        .kpi-hint { color: var(--text-muted); font-size: 11px; font-style: normal; }

        .viz-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .viz-card {
          background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px; padding: 20px 24px;
        }
        .viz-card h3 { color: var(--heading-color); margin-top: 0; margin-bottom: 12px; font-size: 16px; }
        .viz-card p { color: var(--text-secondary); font-size: 13px; line-height: 1.6; margin-bottom: 12px; }

        .tch-table { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: var(--bg-card); }
        .table-like { display: flex; flex-direction: column; gap: 8px; }
        .tch-table-header {
          display: grid; grid-template-columns: repeat(7, minmax(80px, 1fr));
          background: var(--bg-card-hover); border-bottom: 1px solid var(--border);
          padding: 12px 14px; font-weight: 600; color: var(--text-secondary);
          font-size: 12px; letter-spacing: 0.3px;
        }
        .tch-table-row {
          display: grid; grid-template-columns: repeat(7, minmax(80px, 1fr));
          padding: 12px 14px; border-bottom: 1px solid var(--border);
          align-items: center; color: var(--text-primary);
          transition: background 0.15s; font-size: 13px;
        }
        .tch-table-row:hover { background: var(--bg-card-hover); }
        .tch-cell-time { color: var(--text-muted); font-size: 12px; }
        .tch-cell-score { font-weight: 700; color: var(--accent2); }

        .bar-row { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; padding: 8px 0; }
        .bar-row span:first-child { min-width: 120px; color: var(--text-primary); font-weight: 500; font-size: 13px; }
        .bar-track { flex: 1; height: 22px; background: var(--bg-card-hover); border-radius: 6px; overflow: hidden; }
        .bar-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent2)); transition: width 0.4s; border-radius: 6px; }
        .bar-fill.danger { background: linear-gradient(90deg, #e07070, #c85050); }
        .bar-row em { min-width: 40px; text-align: right; color: var(--text-primary); font-weight: 600; font-style: normal; font-size: 13px; }

        .tch-sm-btn {
          background: var(--tch-accent-soft); color: var(--tch-accent-text);
          border: 1px solid transparent; padding: 6px 12px; border-radius: 8px;
          cursor: pointer; font-size: 12px; font-weight: 500; margin-right: 8px;
          margin-bottom: 6px; transition: all 0.2s;
        }
        .tch-sm-btn:hover { background: var(--bg-card-hover); border-color: var(--border-strong); }

        .project-item {
          margin-top: 0; width: 100%; display: flex; justify-content: space-between;
          align-items: center; gap: 12px; background: var(--bg-card); border: 1px solid var(--border);
          border-radius: 10px; padding: 14px 16px; cursor: pointer; color: var(--text-primary);
          transition: all 0.2s; font-size: 13px;
        }
        .project-item:hover { background: var(--bg-card-hover); border-color: var(--accent); }

        .risk-badge { display: inline-block; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; }
        .risk-badge.high { background: var(--tch-danger-soft); color: var(--tch-danger); border: 1px solid rgba(224,112,112,0.3); }
        .risk-badge.medium { background: var(--tch-warning-soft); color: var(--tch-warning); border: 1px solid rgba(224,168,76,0.3); }
        .risk-badge.low { background: var(--tch-success-soft); color: var(--tch-success); border: 1px solid rgba(92,189,138,0.3); }

        .tch-app input[type="text"],.tch-app input[type="email"],.tch-app textarea,.tch-app select {
          background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border-strong);
          padding: 10px 14px; border-radius: 10px; font-size: 13px; transition: border-color 0.2s;
        }
        .tch-app input::placeholder,.tch-app textarea::placeholder { color: var(--text-muted); }
        .tch-app input:focus,.tch-app textarea:focus { border-color: var(--accent); outline: none; box-shadow: 0 0 0 3px var(--tch-accent-soft); }

        .tch-feedback-form { background: var(--bg-card); padding: 24px; border-radius: 12px; border: 1px solid var(--border); }
        .tch-feedback-form label { color: var(--text-primary); font-weight: 600; font-size: 13px; }
        .tch-feedback-form button { background: linear-gradient(135deg, var(--accent), var(--accent2)); color: #fff; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-weight: 600; transition: all 0.2s; }
        .tch-feedback-form button:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px var(--tch-accent-soft); }
        .tch-feedback-success { background: var(--tch-success-soft); border: 1px solid rgba(92,189,138,0.3); color: var(--tch-success); padding: 12px 16px; border-radius: 8px; margin-top: 12px; }

        .evidence-item { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 16px; margin-bottom: 12px; }
        .evidence-item strong { color: var(--accent-text); font-size: 14px; }
        .evidence-item p { color: var(--text-primary); margin: 8px 0; font-size: 13px; line-height: 1.6; }
        .evidence-item em { color: var(--text-muted); font-size: 12px; }

        .tch-evidence-actions { display: flex; gap: 10px; margin-bottom: 16px; }
        .tch-evidence-actions input { flex: 1; }

        .tch-submission-detail { background: var(--bg-card); border-left: 3px solid var(--accent); padding: 20px; margin-top: 12px; border-radius: 0 10px 10px 0; }
        .tch-detail-section { margin-bottom: 16px; }
        .tch-detail-section:last-child { margin-bottom: 0; }
        .tch-detail-section h4 { color: var(--heading-color); margin: 0 0 8px; font-size: 14px; }
        .tch-detail-section p { color: var(--text-primary); margin: 6px 0; font-size: 13px; line-height: 1.6; }

        .tch-raw-text { background: var(--bg-card); border: 1px solid var(--border); padding: 12px; border-radius: 8px; color: var(--text-primary); font-size: 12px; line-height: 1.6; max-height: 300px; overflow-y: auto; }

        .right-hint { background: var(--tch-accent-soft); border-left: 3px solid var(--accent); color: var(--accent-text); padding: 12px 16px; border-radius: 0 8px 8px 0; margin: 12px 0; font-size: 13px; }
        .right-tag { display: block; background: var(--tch-success-soft); border-left: 3px solid var(--tch-success); color: var(--tch-success); padding: 12px 16px; border-radius: 0 8px 8px 0; margin: 8px 0; font-size: 13px; }

        .tch-loading { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; min-height: 200px; animation: fade-in 0.3s; }
        .tch-loading p { color: var(--text-secondary); font-weight: 500; }

        .tch-report-content { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; color: var(--text-primary); line-height: 1.8; white-space: pre-wrap; word-wrap: break-word; }

        .debug-json summary { cursor: pointer; color: var(--accent-text); font-weight: 600; margin-bottom: 8px; }
        .debug-json pre { background: var(--bg-card); border: 1px solid var(--border); color: var(--text-primary); padding: 12px; border-radius: 8px; overflow-x: auto; font-size: 11px; line-height: 1.5; }

        .tch-back-btn {
          padding: 7px 14px; font-size: 13px; background: var(--bg-card-hover);
          color: var(--text-primary); border: 1px solid var(--border); border-radius: 8px;
          cursor: pointer; transition: all 0.2s; font-weight: 500;
        }
        .tch-back-btn:hover { background: var(--tch-accent-soft); color: var(--tch-accent-text); border-color: var(--accent); }

        .tch-sub-tab-btn {
          padding: 10px 16px; font-size: 13px; font-weight: 600; background: var(--bg-card);
          color: var(--text-secondary); border: 1px solid var(--border); border-radius: 10px;
          cursor: pointer; transition: all 0.2s;
        }
        .tch-sub-tab-btn:hover { background: var(--tch-accent-soft); color: var(--tch-accent-text); border-color: var(--accent); }

        .tch-info-banner { padding: 14px 18px; background: var(--warm-soft); border: 1px solid rgba(232,168,76,0.2); border-radius: 10px; margin-bottom: 20px; color: var(--text-primary); }
        .tch-info-banner strong { color: var(--warm-text); }

        .tch-card-surface { background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; padding: 14px; }
        .tch-file-item { padding: 12px; margin-bottom: 6px; border-radius: 8px; border: 1px solid var(--border); background: var(--bg-card); cursor: pointer; transition: all 0.15s; }
        .tch-file-item:hover { background: var(--bg-card-hover); }
        .tch-file-item.selected { background: var(--tch-accent-soft); border-color: var(--accent); }

        .tch-primary-btn { width: 100%; padding: 9px 16px; background: linear-gradient(135deg, var(--accent), var(--accent2)); color: #fff; border: none; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600; transition: all 0.2s; }
        .tch-primary-btn:hover { transform: translateY(-1px); box-shadow: 0 4px 12px var(--tch-accent-soft); }
        .tch-primary-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
        .tch-success-btn { background: linear-gradient(135deg, var(--tch-success), #4aad7a); }
        .tch-warning-btn { background: linear-gradient(135deg, var(--tch-warning), #c89040); }
        .tch-neutral-btn { background: var(--bg-card-hover); color: var(--text-primary); border: 1px solid var(--border); }

        .tch-progress-bar {
          position: fixed; top: 0; left: 0; right: 0; height: 3px;
          background: linear-gradient(90deg, var(--accent), var(--tch-success));
          animation: progress-line 1.5s ease-in-out infinite; z-index: 999;
        }
        .tch-spinner { width: 36px; height: 36px; border: 3px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; }

        .tch-fix-list { padding-left: 20px; line-height: 2; background: var(--tch-accent-soft); padding: 16px; border-radius: 10px; border-left: 3px solid var(--accent); }
        .tch-fix-list.neutral { background: var(--bg-card); border-left-color: var(--text-muted); }
        .tch-risk-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; padding: 12px; background: var(--tch-danger-soft); border-radius: 10px; border-left: 3px solid var(--tch-danger); }
        .tch-risk-chip { padding: 8px 12px; background: var(--bg-card); border: 1px solid rgba(224,112,112,0.25); border-radius: 8px; display: flex; align-items: center; gap: 8px; font-size: 12px; }
        .tch-risk-chip-badge { display: inline-block; background: var(--tch-danger); color: #fff; padding: 3px 7px; border-radius: 4px; font-size: 11px; font-weight: 700; }

        .tch-stat-summary { margin-bottom: 16px; padding: 12px 16px; background: var(--bg-card); border-radius: 10px; border: 1px solid var(--border); display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
        .tch-stat-summary strong { color: var(--text-primary); }
        .tch-stat-value { font-size: 18px; font-weight: 700; margin-left: 6px; }
        .tch-stat-value.danger { color: var(--tch-danger); }
        .tch-stat-value.accent { color: var(--accent); }

        .tch-weak-rank { padding: 8px 12px; border-radius: 8px; margin-bottom: 6px; display: flex; align-items: center; gap: 8px; }
        .tch-weak-rank.rank-0 { background: var(--tch-danger-soft); }
        .tch-weak-rank.rank-1 { background: var(--tch-warning-soft); }
        .tch-weak-rank.rank-2 { background: var(--tch-success-soft); }

        @keyframes fade-in { from { opacity: 0; } to { opacity: 1; } }
        @keyframes fade-up { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes slide-down { from { opacity: 0; max-height: 0; } to { opacity: 1; max-height: 2000px; } }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes progress-line { 0% { width: 0%; } 50% { width: 80%; } 100% { width: 100%; } }
        @keyframes toast-slide-in { from { opacity: 0; transform: translateX(20px); } to { opacity: 1; transform: translateX(0); } }
        @keyframes number-scale { from { opacity: 0; transform: scale(0.8); } to { opacity: 1; transform: scale(1); } }
        @keyframes skeleton-loading { 0% { background: var(--bg-card); } 50% { background: var(--bg-card-hover); } 100% { background: var(--bg-card); } }

        button:focus-visible, input:focus-visible, textarea:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
        button:disabled { opacity: 0.5; cursor: not-allowed; }

        .tch-main::-webkit-scrollbar, .tch-sidebar::-webkit-scrollbar { width: 6px; }
        .tch-main::-webkit-scrollbar-track, .tch-sidebar::-webkit-scrollbar-track { background: transparent; }
        .tch-main::-webkit-scrollbar-thumb, .tch-sidebar::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 3px; }
        .tch-main::-webkit-scrollbar-thumb:hover, .tch-sidebar::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

        ::selection { background: var(--tch-accent-soft); color: var(--text-primary); }

        @media (max-width: 768px) {
          .tch-main { padding: 16px; }
          .tch-body { flex-direction: column; }
          .tch-sidebar { min-width: 100%; max-height: auto; border-right: none; border-bottom: 1px solid var(--border); display: flex; overflow-x: auto; overflow-y: hidden; padding: 4px; }
          .tch-nav-btn { border-left: none; border-bottom: 2px solid transparent; padding: 10px 14px; white-space: nowrap; border-radius: 8px; }
          .tch-nav-btn.active { border-left: none; border-bottom-color: var(--accent); }
          .tch-panel { padding: 20px 16px; }
          .tch-panel h2 { font-size: 18px; }
          .kpi-grid { grid-template-columns: 1fr; }
          .viz-grid { grid-template-columns: 1fr; }
          .tch-table-header { display: none; }
          .tch-table-row { grid-template-columns: 1fr; padding: 14px 12px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; }
          .topbar-center { display: none; }
        }
        @media (min-width: 769px) and (max-width: 1024px) {
          .tch-main { padding: 24px; }
          .kpi-grid { grid-template-columns: repeat(2, 1fr); }
          .viz-grid { grid-template-columns: 1fr; }
        }
        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
        }
        @media print {
          .tch-sidebar, .chat-topbar { display: none; }
          .tch-body { min-height: auto; }
          .tch-main { padding: 0; max-height: none; overflow: visible; }
          .tch-panel { page-break-inside: avoid; box-shadow: none; }
        }
      `}
      </style>
    </div>
  );
}
