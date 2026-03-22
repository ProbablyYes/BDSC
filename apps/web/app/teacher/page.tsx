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
    <div style={{ animation: "skeleton-pulse 2s infinite" }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          style={{
            height: type === "bar" ? 40 : type === "card" ? 120 : 50,
            backgroundColor: "var(--skeleton-bg, #e8e8e8)",
            borderRadius: 8,
            marginBottom: 12,
            animation: "skeleton-loading 1.5s ease-in-out infinite",
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
        top: 80,
        right: 20,
        padding: "12px 20px",
        backgroundColor: "#2ecc71",
        color: "white",
        borderRadius: 8,
        boxShadow: "0 4px 12px rgba(46, 204, 113, 0.3)",
        animation: "toast-slide-in 0.3s ease-out",
        zIndex: 1000,
      }}
    >
      ✓ {message}
    </div>
  );
}

// 错误提示组件
function ErrorToast({ message, onClose }: { message: string; onClose: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onClose, 4000);
    return () => clearTimeout(timer);
  }, [onClose]);

  return (
    <div
      style={{
        position: "fixed",
        top: 80,
        right: 20,
        padding: "12px 20px",
        backgroundColor: "#e74c3c",
        color: "white",
        borderRadius: 8,
        boxShadow: "0 4px 12px rgba(231, 76, 60, 0.3)",
        animation: "toast-slide-in 0.3s ease-out",
        zIndex: 1001,
      }}
    >
      ⚠️ {message}
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
            fill="#333"
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
  const [isDarkMode, setIsDarkMode] = useState(false);
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
          <div style={{ fontSize: "12px", color: "#666", marginBottom: "8px", padding: "0 4px" }}>
            ✏️ 编辑模式 - 纯文本（仅显示文字内容，不包含图片或格式）
          </div>
          <textarea
            value={editedContent}
            onChange={(e) => setEditedContent(e.target.value)}
            style={{
              width: "100%",
              maxHeight: "400px",
              padding: "12px",
              borderRadius: "6px",
              border: "2px solid #4a90e2",
              fontSize: "13px",
              lineHeight: "1.6",
              fontFamily: "monospace",
              boxSizing: "border-box",
              backgroundColor: "#fffef5",
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
            backgroundColor: "#f5f5f5",
            borderRadius: "4px",
            border: "1px solid #e0e0e0",
          }}>
            <div style={{ fontSize: "12px", color: "#666", fontWeight: "500" }}>
              📄 PDF 文档 - 共 {onlinePreviewData.page_count || "?"} 页 ({Math.round((onlinePreviewData.file_size || 0) / 1024)} KB)
            </div>
            <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
              {pdfAnalysisLoading && (
                <span style={{ fontSize: "12px", color: "#ff9800" }}>⚙️ 正在分析...</span>
              )}
              <a
                href={pdfDataUrl}
                download={selectedFile.filename}
                style={{
                  padding: "6px 12px",
                  fontSize: "12px",
                  backgroundColor: "#4a90e2",
                  color: "white",
                  textDecoration: "none",
                  border: "none",
                  borderRadius: "3px",
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
              backgroundColor: "#fff",
              borderRadius: "4px",
              border: "1px solid #e0e0e0",
              overflow: "hidden",
            }}>
              <div style={{
                fontSize: "12px",
                fontWeight: "500",
                padding: "8px 12px",
                backgroundColor: "#f9f9f9",
                borderBottom: "1px solid #e0e0e0",
                color: "#666",
              }}>
                原文件预览
              </div>
              <iframe
                src={pdfDataUrl}
                style={{
                  flex: 1,
                  border: "none",
                  borderRadius: "0 0 4px 0",
                }}
                title="PDF Preview"
              />
            </div>

            {/* 右侧：LLM分析结果 */}
            <div style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              backgroundColor: "#fafafa",
              borderRadius: "4px",
              border: "1px solid #e0e0e0",
              overflow: "hidden",
            }}>
              <div style={{
                fontSize: "12px",
                fontWeight: "500",
                padding: "8px 12px",
                backgroundColor: "#e8f5e9",
                borderBottom: "1px solid #e0e0e0",
                color: "#2e7d32",
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
                    color: "#999",
                  }}>
                    <div style={{
                      width: "30px",
                      height: "30px",
                      border: "3px solid #e0e0e0",
                      borderTopColor: "#4a90e2",
                      borderRadius: "50%",
                      animation: "spin 0.8s linear infinite",
                    }} />
                    <span>正在使用AI分析文档内容...</span>
                  </div>
                ) : analysis?.status === "success" ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                    {/* 总结 */}
                    <div>
                      <div style={{ fontWeight: "600", color: "#1976d2", marginBottom: "6px" }}>
                        📝 内容总结
                      </div>
                      <div style={{
                        backgroundColor: "#fff",
                        padding: "10px",
                        borderRadius: "3px",
                        border: "1px solid #e3f2fd",
                        color: "#333",
                      }}>
                        {analysis?.summary || "暂无总结"}
                      </div>
                    </div>

                    {/* 关键要点 */}
                    {analysis?.key_points && analysis.key_points.length > 0 && (
                      <div>
                        <div style={{ fontWeight: "600", color: "#d32f2f", marginBottom: "6px" }}>
                          ⭐ 关键要点
                        </div>
                        <ul style={{
                          margin: 0,
                          paddingLeft: "20px",
                          backgroundColor: "#fff",
                          padding: "10px",
                          borderRadius: "3px",
                          border: "1px solid #ffebee",
                        }}>
                          {analysis.key_points.map((point: string, idx: number) => (
                            <li key={idx} style={{ marginBottom: idx < analysis.key_points.length - 1 ? "6px" : 0, color: "#333" }}>
                              {point}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* 重点关注领域 */}
                    {analysis?.focus_areas && analysis.focus_areas.length > 0 && (
                      <div>
                        <div style={{ fontWeight: "600", color: "#f57c00", marginBottom: "6px" }}>
                          🎯 重点领域
                        </div>
                        <div style={{
                          display: "flex",
                          flexWrap: "wrap",
                          gap: "6px",
                          backgroundColor: "#fff",
                          padding: "10px",
                          borderRadius: "3px",
                          border: "1px solid #ffe0b2",
                        }}>
                          {analysis.focus_areas.map((area: string, idx: number) => (
                            <div key={idx} style={{
                              backgroundColor: "#fff3cd",
                              padding: "4px 10px",
                              borderRadius: "12px",
                              fontSize: "12px",
                              color: "#856404",
                              border: "1px solid #ffeeba",
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
                        <div style={{ fontWeight: "600", color: "#7b1fa2", marginBottom: "6px" }}>
                          💡 深度见解
                        </div>
                        <div style={{
                          backgroundColor: "#fff",
                          padding: "10px",
                          borderRadius: "3px",
                          border: "1px solid #f3e5f5",
                          color: "#333",
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
                        color: "#999",
                        paddingTop: "8px",
                        borderTop: "1px solid #e0e0e0",
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
                    color: "#999",
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
            backgroundColor: "#f5f5f5",
            borderRadius: "4px",
            borderBottom: "1px solid #e0e0e0",
          }}>
            <div style={{ fontSize: "12px", color: "#666" }}>
              {displayName} 
              {onlinePreviewData.slide_count ? ` - 共 ${onlinePreviewData.slide_count} 页` : ""}
              ({onlinePreviewData.file_size || 0} 字节)
            </div>
          </div>
          <div style={{
            maxHeight: "500px",
            overflowY: "auto",
            backgroundColor: "white",
            borderRadius: "4px",
            border: "1px solid #e0e0e0",
            padding: "12px",
            fontSize: "14px",
            lineHeight: "1.8",
            color: "#333",
          }}>
            <div 
              dangerouslySetInnerHTML={{ __html: onlinePreviewData.html_content }}
              style={{
                "& h1, & h2, & h3": { marginTop: "16px", marginBottom: "8px" },
                "& p": { marginBottom: "8px" },
                "& table": { width: "100%", borderCollapse: "collapse" },
                "& td, & th": { border: "1px solid #ddd", padding: "8px" }
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
          backgroundColor: "#f9f9f9",
          borderRadius: "6px",
          border: "1px solid #e0e0e0",
          textAlign: "center",
        }}>
          <div style={{ fontSize: "24px", marginBottom: "12px", animation: "spin 1s linear infinite" }}>
            ⚙️
          </div>
          <div style={{ fontSize: "14px", color: "#666" }}>正在加载文件预览...</div>
        </div>
      );
    }
    
    // 在线预览失败，回退到文本预览
    if (onlinePreviewData?.status === "text_fallback" || onlinePreviewData?.status === "error") {
      if (onlinePreviewData?.raw_text && onlinePreviewData.raw_text.trim()) {
        return (
          <div>
            <div style={{ fontSize: "12px", color: "#f39c12", marginBottom: "8px", padding: "8px", backgroundColor: "#fffef5", borderRadius: "4px" }}>
              💡 原始文件不可用，显示的是提取的文本内容预览
            </div>
            <div style={{
              maxHeight: "450px",
              overflowY: "auto",
              backgroundColor: "white",
              padding: "12px",
              borderRadius: "6px",
              border: "1px solid #e0e0e0",
              fontSize: "13px",
              lineHeight: "1.6",
              color: "#333",
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
          backgroundColor: "white",
          padding: "12px",
          borderRadius: "6px",
          border: "1px solid #e0e0e0",
          fontSize: "13px",
          lineHeight: "1.6",
          color: "#333",
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
        backgroundColor: "#f5f5f5",
        borderRadius: "6px",
        border: "2px dashed #ccc",
        padding: "20px",
        textAlign: "center",
      }}>
        <div style={{ fontSize: "48px", marginBottom: "12px" }}>{fileInfo.icon}</div>
        <div style={{ fontSize: "16px", fontWeight: "600", color: "#333", marginBottom: "8px" }}>
          {fileInfo.displayName}
        </div>
        <div style={{ fontSize: "13px", color: "#666", marginBottom: "12px" }}>
          {selectedFile.filename}
        </div>
        <div style={{ fontSize: "12px", color: "#999", maxWidth: "300px", lineHeight: "1.6" }}>
          文件预览功能正在加载或暂时不可用，但已自动提取文本内容。您可以在编辑模式中查看和修改提取的文本。
        </div>
        {editedContent && (
          <div style={{
            fontSize: "12px",
            color: "#2196f3",
            marginTop: "12px",
            padding: "8px 12px",
            backgroundColor: "#e3f2fd",
            borderRadius: "4px",
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
    const savedTheme = localStorage.getItem("tch-theme") || "light";
    const isDark = savedTheme === "dark";
    setIsDarkMode(isDark);
    document.documentElement.setAttribute("data-theme", savedTheme);
  }, []);

  useEffect(() => {
    const theme = isDarkMode ? "dark" : "light";
    localStorage.setItem("tch-theme", theme);
    document.documentElement.setAttribute("data-theme", theme);
  }, [isDarkMode]);

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
            className="topbar-btn theme-toggle" 
            onClick={() => setIsDarkMode(!isDarkMode)}
            title={isDarkMode ? "切换到白天模式" : "切换到黑夜模式"}
            suppressHydrationWarning
          >
            <span suppressHydrationWarning>{isDarkMode ? "☀️ 白天" : "🌙 黑夜"}</span>
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
                background: "linear-gradient(90deg, #4a90e2, #2ecc71)",
                animation: "progress-line 1.5s ease-in-out infinite",
                zIndex: 999,
              }}
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
                  border: "3px solid #e8e8e8",
                  borderTop: "3px solid #4a90e2",
                  borderRadius: "50%",
                  animation: "spin 0.8s linear infinite",
                }}
              />
              <p>{loadingMessage}...</p>
              <p style={{ fontSize: 12, color: "#999" }}>请稍候</p>
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
                        <p style={{ color: "#999", fontSize: 12 }}>暂无类别数据</p>
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
                        <p style={{ color: "#999", fontSize: 12 }}>暂无风险规则数据</p>
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
                      <p style={{ color: "#999", fontSize: 12, padding: 16 }}>暂无高风险项目数据</p>
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
                  <p style={{ color: "#999", fontSize: 12, padding: 20, textAlign: "center" }}>📭 暂无提交记录。学生对话后这里会自动出现。</p>
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
                        <span className="tch-cell-score" style={{ color: Number(s.overall_score) >= 7 ? "#2ecc71" : Number(s.overall_score) >= 5 ? "#f39c12" : "#e74c3c" }}>
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
                <button
                  onClick={() => setTab("class")}
                  style={{
                    padding: "8px 12px",
                    fontSize: "14px",
                    backgroundColor: "#f0f0f0",
                    color: "#333",
                    border: "1px solid #ddd",
                    borderRadius: "4px",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                  }}
                >
                  ← 返回班级
                </button>
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
                    color: Number(compareData?.comparison?.risk_intensity_delta) > 0 ? "#e74c3c" : "#2ecc71"
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
                  <strong style={{ fontSize: 28, color: "#f39c12" }}>{compareData?.current_class?.avg_rubric_score ?? "-"}</strong>
                  <em className="kpi-hint">9维度评分的平均值(满分10)</em>
                </div>
              </div>
              <h3 style={{ marginTop: 24 }}>💡 自动干预建议</h3>
              <p className="tch-desc">系统根据对比差异自动生成的教学建议。建议在课堂上针对性讲解。</p>
              <div className="tch-recs" style={{ animation: "fade-in 0.6s ease-out" }}>
                {(compareData?.recommendations ?? []).length === 0 ? (
                  <p style={{ color: "#999", fontSize: 12 }}>暂无建议</p>
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
                <button
                  onClick={() => setTab("project")}
                  style={{
                    padding: "8px 12px",
                    fontSize: "14px",
                    backgroundColor: "#f0f0f0",
                    color: "#333",
                    border: "1px solid #ddd",
                    borderRadius: "4px",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                  }}
                >
                  ← 返回项目
                </button>
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
                            <strong style={{ color: "#4a90e2" }}>📝 {e.type}</strong>
                            <p style={{ margin: "8px 0" }}>{e.quote}</p>
                            <em style={{ color: "#999" }}>来源: {e.source_unit}</em>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div style={{ marginTop: 20, padding: 16, backgroundColor: "#f5f5f5", borderRadius: 8 }}>
                      <p style={{ fontSize: 12, color: "#999" }}>📭 Neo4j中暂无结构化证据数据</p>
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
                              borderLeft: "4px solid #2ecc71",
                              animation: `fade-in 0.3s ease-out ${idx * 0.05}s both`,
                              transition: "all 0.2s ease",
                            }}
                          >
                            <strong>📄 {s.filename}</strong>
                            <p style={{ marginTop: 8, marginBottom: 10, fontSize: 12, color: "#666" }}>
                              <em suppressHydrationWarning>学生: {s.student_id} | 提交时间: {s.created_at ? '已提交' : '未知'}</em>
                            </p>
                            
                            {/* Summary Section */}
                            {s.summary ? (
                              <p style={{ fontSize: 13, color: "#333", fontWeight: 500, marginBottom: 10, padding: "8px 10px", backgroundColor: "#f0f8ff", borderRadius: 4 }}>
                                {s.summary}
                              </p>
                            ) : null}
                            
                            {/* Diagnosis Details */}
                            {s.diagnosis && Object.keys(s.diagnosis).length > 0 ? (
                              <details style={{ fontSize: 12, marginTop: 8 }}>
                                <summary style={{ cursor: "pointer", color: "#4a90e2", fontWeight: 500 }}>📊 查看详细诊断信息</summary>
                                <div style={{ fontSize: 12, backgroundColor: "#f5f5f5", padding: 10, borderRadius: 4, marginTop: 8 }}>
                                  {s.diagnosis.overall_score !== undefined && (
                                    <p><strong>诊断评分:</strong> {s.diagnosis.overall_score.toFixed(2)}/5.0</p>
                                  )}
                                  {s.diagnosis.bottleneck && (
                                    <p><strong>核心瓶颈:</strong> {s.diagnosis.bottleneck}</p>
                                  )}
                                  {s.diagnosis.triggered_rules && s.diagnosis.triggered_rules.length > 0 ? (
                                    <p>
                                      <strong>触发规则:</strong> {s.diagnosis.triggered_rules.map((r: any) => (
                                        <span key={r.id} style={{ display: "inline-block", marginRight: 8, padding: "2px 6px", backgroundColor: "#ffe6e6", borderRadius: 3, fontSize: 11 }}>
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
                    <div style={{ marginTop: 20, padding: 16, backgroundColor: "#f5f5f5", borderRadius: 8 }}>
                      <p style={{ fontSize: 12, color: "#999" }}>📭 该项目暂无学生提交的文件</p>
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
                <button
                  onClick={() => setTab("class")}
                  style={{
                    padding: "8px 12px",
                    fontSize: "14px",
                    backgroundColor: "#f0f0f0",
                    color: "#333",
                    border: "1px solid #ddd",
                    borderRadius: "4px",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                  }}
                >
                  ← 返回班级
                </button>
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
                      <summary style={{ cursor: "pointer", color: "#4a90e2", fontWeight: "600" }}>📊 查看报告依据的原始数据</summary>
                      <pre style={{ marginTop: 12, padding: 12, backgroundColor: "#f5f5f5", borderRadius: 6, overflow: "auto", maxHeight: 400 }}>
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
                <div style={{ backgroundColor: "#f9f9f9", padding: "16px", borderRadius: "8px", border: "1px solid #e0e0e0" }}>
                  <h3 style={{ marginTop: 0, fontSize: "16px", color: "#333" }}>📤 学生提交文件</h3>
                  
                  <div style={{marginBottom: "16px"}}>
                    <input 
                      value={selectedProject || projectId} 
                      onChange={(e) => setSelectedProject(e.target.value)}
                      placeholder="项目ID"
                      style={{ width: "100%", padding: "8px", marginBottom: "8px", borderRadius: "4px", border: "1px solid #ddd" }}
                    />
                    <button 
                      onClick={loadStudentFiles}
                      style={{
                        width: "100%",
                        padding: "8px 16px",
                        backgroundColor: "#4a90e2",
                        color: "white",
                        border: "none",
                        borderRadius: "4px",
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
                            backgroundColor: selectedFile?.submission_id === file.submission_id ? "#e3f2fd" : "white",
                            border: selectedFile?.submission_id === file.submission_id ? "2px solid #4a90e2" : "1px solid #ddd",
                            borderRadius: "6px",
                            cursor: "pointer",
                            transition: "all 0.2s ease",
                          }}
                        >
                          <div style={{ fontSize: "13px", fontWeight: "600", color: "#333" }}>
                            {getFileTypeInfo(file.filename).icon} {file.filename}
                          </div>
                          <div style={{ fontSize: "12px", color: "#999", marginTop: "4px" }}>
                            {getFileTypeInfo(file.filename).displayName}
                          </div>
                          <div style={{ fontSize: "12px", color: "#666", marginTop: "4px" }}>
                            学生: {file.student_id} | 评分: <span style={{color: file.overall_score >= 7 ? "#2ecc71" : file.overall_score >= 5 ? "#f39c12" : "#e74c3c"}}>{file.overall_score}</span>
                          </div>
                          <div style={{ fontSize: "11px", color: "#999", marginTop: "2px" }}>
                            <span suppressHydrationWarning>{file.created_at ? '已上传' : '未知'}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p style={{ fontSize: "13px", color: "#999", textAlign: "center", padding: "20px 0" }}>
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
                            backgroundColor: isEditMode ? "#ff9800" : "#e0e0e0",
                            color: isEditMode ? "white" : "#333",
                            border: "none",
                            borderRadius: "4px",
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
                                backgroundColor: "#ccc",
                                color: "#333",
                                border: "none",
                                borderRadius: "4px",
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
                                backgroundColor: "#4caf50",
                                color: "white",
                                border: "none",
                                borderRadius: "4px",
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
                                backgroundColor: "#2196f3",
                                color: "white",
                                border: "none",
                                borderRadius: "4px",
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
                            borderRadius: "4px",
                            border: "1px solid #ddd",
                            fontSize: "12px",
                            boxSizing: "border-box",
                          }}
                        />
                      )}
                      
                      {/* 文件内容显示区域 - 根据文件类型智能显示 */}
                      {renderFilePreview(selectedFile, editedContent, isEditMode)}
                      
                      {/* 编辑历史 */}
                      {documentEdits.length > 0 && !isEditMode && (
                        <div style={{marginTop: "12px", paddingTop: "12px", borderTop: "1px solid #e0e0e0"}}>
                          <div style={{fontSize: "12px", fontWeight: "600", color: "#333", marginBottom: "6px"}}>📝 编辑历史：</div>
                          <div style={{maxHeight: "150px", overflowY: "auto"}}>
                            {documentEdits.slice(0, 5).map((edit, idx) => (
                              <div key={idx} style={{fontSize: "11px", padding: "6px", marginBottom: "4px", backgroundColor: "#f0f0f0", borderRadius: "3px", borderLeft: "3px solid #2196f3"}}>
                                <div style={{color: "#333"}}>{edit.edit_summary || "文档编辑"}</div>
                                <div style={{color: "#999", marginTop: "2px"}}>
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
                <div style={{ backgroundColor: "#f9f9f9", padding: "16px", borderRadius: "8px", border: "1px solid #e0e0e0" }}>
                  <h3 style={{ marginTop: 0, fontSize: "16px", color: "#333" }}>✏️ 添加批注 & 反馈</h3>
                  
                  {selectedFile ? (
                    <>
                      {/* 文本级反馈 */}
                      <div style={{marginBottom: "16px"}}>
                        <label style={{fontSize: "13px", fontWeight: "600", color: "#333", display: "block", marginBottom: "6px"}}>📝 文本反馈</label>
                        <textarea 
                          value={feedbackText} 
                          onChange={(e) => setFeedbackText(e.target.value)}
                          placeholder="写出对项目的整体反馈..." 
                          rows={3}
                          style={{
                            width: "100%",
                            padding: "8px",
                            borderRadius: "4px",
                            border: "1px solid #ddd",
                            fontSize: "13px",
                            boxSizing: "border-box",
                          }}
                        />
                        <div style={{fontSize: "12px", color: "#666", marginTop: "4px"}}>
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
                              border: "1px solid #ddd",
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
                            backgroundColor: "#2ecc71",
                            color: "white",
                            border: "none",
                            borderRadius: "4px",
                            cursor: "pointer",
                            fontSize: "13px",
                            fontWeight: "600",
                          }}
                        >
                          💬 提交文本反馈
                        </button>
                      </div>
                      
                      {/* 批注 */}
                      <div style={{marginBottom: "16px", borderTop: "1px solid #e0e0e0", paddingTop: "12px"}}>
                        <label style={{fontSize: "13px", fontWeight: "600", color: "#333", display: "block", marginBottom: "6px"}}>🎯 段落批注</label>
                        <select 
                          value={annotationType}
                          onChange={(e) => setAnnotationType(e.target.value)}
                          style={{
                            width: "100%",
                            padding: "6px",
                            marginBottom: "8px",
                            borderRadius: "3px",
                            border: "1px solid #ddd",
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
                            border: "1px solid #ddd",
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
                            backgroundColor: "#f39c12",
                            color: "white",
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
                      <div style={{borderTop: "1px solid #e0e0e0", paddingTop: "12px"}}>
                        <label style={{fontSize: "13px", fontWeight: "600", color: "#333", display: "block", marginBottom: "6px"}}>📎 上传反馈文件</label>
                        <input 
                          ref={feedbackFileInputRef}
                          type="file"
                          accept=".pdf,.docx,.pptx,.txt"
                          onChange={(e) => setFeedbackFileToUpload(e.target.files?.[0] || null)}
                          style={{width: "100%", marginBottom: "6px"}}
                        />
                        {feedbackFileToUpload && (
                          <div style={{fontSize: "12px", color: "#666", marginBottom: "6px"}}>
                            ✓ 已选择: {feedbackFileToUpload.name}
                          </div>
                        )}
                        <button 
                          onClick={uploadFeedbackFile}
                          disabled={!feedbackFileToUpload}
                          style={{
                            width: "100%",
                            padding: "6px",
                            backgroundColor: feedbackFileToUpload ? "#4a90e2" : "#ccc",
                            color: "white",
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
                        <div style={{marginTop: "12px", borderTop: "1px solid #e0e0e0", paddingTop: "12px"}}>
                          <div style={{fontSize: "12px", fontWeight: "600", color: "#333", marginBottom: "6px"}}>已上传反馈文件：</div>
                          {feedbackFiles.map((file, idx) => (
                            <div key={idx} style={{fontSize: "11px", color: "#666", padding: "4px", marginBottom: "4px", backgroundColor: "white", borderRadius: "3px"}}>
                              📄 {file.original_filename} &nbsp; <a href={`${API}${file.file_url}`} target="_blank" style={{color: "#4a90e2"}}>下载</a>
                            </div>
                          ))}
                        </div>
                      )}
                      
                      {/* 批注列表 */}
                      {feedbackAnnotations.length > 0 && (
                        <div style={{marginTop: "12px", borderTop: "1px solid #e0e0e0", paddingTop: "12px"}}>
                          <div style={{fontSize: "12px", fontWeight: "600", color: "#333", marginBottom: "6px"}}>已保存的批注：</div>
                          <div style={{maxHeight: "200px", overflowY: "auto"}}>
                            {feedbackAnnotations.map((ann, idx) => (
                              <div key={idx} style={{fontSize: "11px", padding: "6px", marginBottom: "6px", backgroundColor: "white", borderRadius: "3px", borderLeft: "3px solid #f39c12"}}>
                                <div style={{color: "#666"}}>{ann.overall_feedback || (ann.annotations?.[0]?.content || "")}</div>
                                <div style={{color: "#999", marginTop: "2px"}} suppressHydrationWarning>{ann.created_at ? '已添加' : '未知'}</div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  ) : (
                    <p style={{ fontSize: "13px", color: "#999", textAlign: "center", padding: "40px 20px" }}>
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
                <button
                  onClick={() => setTab("class")}
                  style={{
                    padding: "8px 12px",
                    fontSize: "14px",
                    backgroundColor: "#f0f0f0",
                    color: "#333",
                    border: "1px solid #ddd",
                    borderRadius: "4px",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                  }}
                >
                  ← 返回班级
                </button>
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
                        <p style={{ color: "#999", fontSize: 12 }}>暂无维度数据</p>
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
                            <em style={{ fontWeight: "600", color: dim.score >= 7 ? "#2ecc71" : dim.score >= 5 ? "#f39c12" : "#e74c3c" }}>
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
                          <p style={{ color: "#999", fontSize: 12 }}>暂无数据</p>
                        ) : (
                          <div>
                            {sorted.slice(0, 3).map((dim: any, i: number) => (
                              <div 
                                key={dim.name} 
                                className="bar-row"
                                style={{
                                  animation: `fade-in 0.3s ease-out ${i * 0.1}s both`,
                                  padding: "8px 12px",
                                  backgroundColor: i === 0 ? "#ffe6e6" : i === 1 ? "#fff3cd" : "#e8f5e9",
                                  borderRadius: 4,
                                  marginBottom: 8
                                }}
                              >
                                <span>{i === 0 ? "🔴 最弱" : i === 1 ? "🟡 较弱" : "🟢 需强化"}</span>
                                <span style={{ fontWeight: "600", flex: 1 }}>{dim.name}</span>
                                <strong style={{ color: i === 0 ? "#e74c3c" : i === 1 ? "#f39c12" : "#2ecc71" }}>
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
                <button
                  onClick={() => setTab("class")}
                  style={{
                    padding: "8px 12px",
                    fontSize: "14px",
                    backgroundColor: "#f0f0f0",
                    color: "#333",
                    border: "1px solid #ddd",
                    borderRadius: "4px",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                  }}
                >
                  ← 返回班级
                </button>
              </div>
              <h2>🔥 规则检查覆盖率</h2>
              <p className="tch-desc">15条关键业务规则（H1-H15）的触发统计。热力图显示哪些规则在班级中最常被触发，即班级共性风险点。</p>
              {!ruleCoverage?.rule_coverage ? (
                <SkeletonLoader rows={5} type="table" />
              ) : (
                <>
                  <div style={{ marginBottom: 16, padding: 12, backgroundColor: "#f5f5f5", borderRadius: 8, animation: "fade-in 0.3s ease-out" }}>
                    <strong>⚠️ 高危规则：</strong>
                    <span style={{ fontSize: 18, fontWeight: "bold", color: "#e74c3c", marginLeft: 8 }}>
                      {ruleCoverage.high_risk_count}
                    </span>
                    <span style={{ marginLeft: 16 }}> | </span>
                    <strong style={{ marginLeft: 16 }}>📊 总提交数：</strong>
                    <span style={{ fontSize: 18, fontWeight: "bold", color: "#4a90e2", marginLeft: 8 }}>
                      {ruleCoverage.total_submissions}
                    </span>
                  </div>
                  <div className="tch-table" style={{ animation: "fade-in 0.4s ease-out" }}>
                    <div className="tch-table-header">
                      <span>规则ID</span><span>规则名称</span><span>触发次数</span><span>覆盖率</span><span>风险等级</span>
                    </div>
                    {ruleCoverage.rule_coverage.length === 0 ? (
                      <p style={{ color: "#999", fontSize: 12, padding: 20 }}>暂无规则覆盖率数据</p>
                    ) : (
                      ruleCoverage.rule_coverage.map((rule: any, idx: number) => (
                        <div 
                          key={rule.rule_id} 
                          className="tch-table-row"
                          style={{
                            animation: `fade-in 0.3s ease-out ${idx * 0.05}s both`,
                            backgroundColor: rule.severity === "high" ? "#ffe6e6" : rule.severity === "medium" ? "#fff3cd" : "#f0f0f0",
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
                                  backgroundColor: rule.severity === "high" ? "#e74c3c" : rule.severity === "medium" ? "#f39c12" : "#2ecc71"
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
                <button
                  onClick={() => setTab("project")}
                  style={{
                    padding: "8px 12px",
                    fontSize: "14px",
                    backgroundColor: "#f0f0f0",
                    color: "#333",
                    border: "1px solid #ddd",
                    borderRadius: "4px",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                  }}
                >
                  ← 返回项目
                </button>
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
                      <strong style={{ fontSize: 32, color: "#f39c12" }}>
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
                      <p style={{ color: "#999", fontSize: 12, padding: 20 }}>暂无评分数据</p>
                    ) : (
                      rubricAssessment.rubric_items.map((item: any, idx: number) => (
                        <div 
                          key={item.item_id} 
                          className="tch-table-row"
                          style={{
                            animation: `fade-in 0.3s ease-out ${idx * 0.05}s both`,
                            backgroundColor: Number(item.score) >= item.max_score * 0.7 ? "#e8f5e9" : 
                                           Number(item.score) >= item.max_score * 0.5 ? "#fff3cd" : "#ffe6e6",
                            transition: "all 0.2s ease",
                          }}
                        >
                          <span><strong>{item.item_id}</strong> {item.item_name}</span>
                          <span style={{ fontWeight: "600", color: Number(item.score) >= item.max_score * 0.7 ? "#2ecc71" : "#f39c12" }}>
                            {item.score}/{item.max_score}
                          </span>
                          <span>{(item.weight * 100).toFixed(0)}%</span>
                          <span style={{ fontSize: "0.9em", color: "#555" }}>{item.revision_suggestion}</span>
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
                <button
                  onClick={() => setTab("project")}
                  style={{
                    padding: "8px 12px",
                    fontSize: "14px",
                    backgroundColor: "#f0f0f0",
                    color: "#333",
                    border: "1px solid #ddd",
                    borderRadius: "4px",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                  }}
                >
                  ← 返回项目
                </button>
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
                          color: competitionScore.predicted_competition_score >= 75 ? "#2ecc71" : 
                                 competitionScore.predicted_competition_score >= 60 ? "#f39c12" : "#e74c3c",
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
                      <p style={{ fontSize: 12, color: "#666", marginTop: 8 }}>
                        <strong>📌 评分说明：</strong>基于项目诊断评分、触发规则数量等因素综合计算。
                      </p>
                    </div>
                  </div>

                  <h3 style={{ marginTop: 24, marginBottom: 12, fontSize: 18 }}>⚡ 24小时快速修复（最关键的3项）</h3>
                  <ul style={{ paddingLeft: 20, lineHeight: 2, backgroundColor: "#f0f8ff", padding: 16, borderRadius: 8, borderLeft: "4px solid #4a90e2" }}>
                    {(competitionScore.quick_fixes_24h ?? []).map((fix: string, i: number) => (
                      <li key={i} style={{ animation: `fade-in 0.3s ease-out ${i * 0.1}s both` }}>✓ {fix}</li>
                    ))}
                  </ul>

                  <h3 style={{ marginTop: 24, marginBottom: 12, fontSize: 18 }}>📋 72小时完整改进方案</h3>
                  <ul style={{ paddingLeft: 20, lineHeight: 2, backgroundColor: "#f5f5f5", padding: 16, borderRadius: 8, borderLeft: "4px solid #666" }}>
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
                        backgroundColor: "#fef5f5",
                        borderRadius: "8px",
                        borderLeft: "4px solid #ff4d4d",
                        animation: "fade-in 0.5s ease-out"
                      }}>
                        {competitionScore.high_risk_rules_for_competition.map((rule: any, idx: number) => (
                          <div 
                            key={rule.rule} 
                            style={{ 
                              padding: "10px 12px", 
                              backgroundColor: "white",
                              border: "1px solid #ffb3b3",
                              borderRadius: "6px",
                              boxShadow: "0 2px 4px rgba(255, 77, 77, 0.1)",
                              display: "flex",
                              alignItems: "center",
                              gap: "8px",
                              animation: `fade-in 0.3s ease-out ${idx * 0.05}s both`,
                              transition: "all 0.2s ease",
                            }}
                          >
                            <span style={{ 
                              display: "inline-block",
                              backgroundColor: "#ff4d4d",
                              color: "white",
                              padding: "4px 8px",
                              borderRadius: "4px",
                              fontSize: "12px",
                              fontWeight: "bold",
                              minWidth: "32px",
                              textAlign: "center"
                            }}>
                              {rule.rule}
                            </span>
                            <span style={{ fontSize: "12px", color: "#555", flex: 1 }}>
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
                <button
                  onClick={() => setTab("class")}
                  style={{
                    padding: "8px 12px",
                    fontSize: "14px",
                    backgroundColor: "#f0f0f0",
                    color: "#333",
                    border: "1px solid #ddd",
                    borderRadius: "4px",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                  }}
                >
                  ← 返回班级
                </button>
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
                      <strong style={{ fontSize: 28, color: "#e74c3c" }}>
                        {teachingInterventions.total_shared_problems ?? 0}
                      </strong>
                      <em>需干预</em>
                    </div>
                  </div>

                  <h3 style={{ marginTop: 24, marginBottom: 12 }}>⚡ 优先级教学方案</h3>
                  {teachingInterventions.shared_problems.length === 0 ? (
                    <p style={{ color: "#999", fontSize: 12, padding: 20, textAlign: "center" }}>暂无共性问题识别</p>
                  ) : (
                    teachingInterventions.shared_problems.map((problem: any, idx: number) => (
                      <div 
                        key={problem.rule_id} 
                        className="viz-card"
                        style={{
                          animation: `fade-in 0.3s ease-out ${idx * 0.08}s both`,
                          borderLeft: `4px solid ${problem.priority === "高" ? "#e74c3c" : problem.priority === "中" ? "#f39c12" : "#2ecc71"}`,
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
                        <p style={{ color: "#666", fontSize: 13 }}>
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
                      backgroundColor: "#f0f8ff",
                      color: "#333",
                      padding: 16,
                      borderRadius: 8,
                      borderLeft: "4px solid #4a90e2",
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
                        border: "1px solid #d0d0d0",
                        borderRadius: "6px",
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
                        backgroundColor: projectTabInput.trim() ? "#4a90e2" : "#ccc",
                        color: "white",
                        border: "none",
                        borderRadius: "6px",
                        cursor: projectTabInput.trim() ? "pointer" : "not-allowed",
                        transition: "all 0.3s ease",
                      }}
                      disabled={!projectTabInput.trim()}
                    >
                      确认项目ID
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div style={{ marginBottom: "24px", padding: "16px", backgroundColor: "#fff3cd", borderRadius: "8px" }}>
                    <p style={{ margin: "0", color: "#333" }}>
                      <strong>当前项目 ID：</strong> {selectedProject}
                      <button
                        onClick={() => setProjectIdConfirmed(false)}
                        style={{
                          marginLeft: "16px",
                          padding: "6px 12px",
                          fontSize: "12px",
                          backgroundColor: "#ddd",
                          color: "#333",
                          border: "none",
                          borderRadius: "4px",
                          cursor: "pointer",
                        }}
                      >
                        切换项目
                      </button>
                    </p>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "12px", marginBottom: "32px" }}>
                    {PROJECT_SUB_TABS.map((subTab) => (
                      <button
                        key={subTab.id}
                        onClick={() => {
                          setTab(subTab.id as Tab);
                          if (subTab.id === "rubric") loadProjectDiagnosis();
                          if (subTab.id === "competition") loadCompetitionScore();
                          if (subTab.id === "evidence") loadEvidence(selectedProject);
                        }}
                        style={{
                          padding: "12px 16px",
                          fontSize: "14px",
                          fontWeight: "600",
                          backgroundColor: "#f0f0f0",
                          color: "#333",
                          border: "1px solid #ddd",
                          borderRadius: "6px",
                          cursor: "pointer",
                          transition: "all 0.3s ease",
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
                        border: "1px solid #d0d0d0",
                        borderRadius: "6px",
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
                        backgroundColor: classTabInput.trim() ? "#4a90e2" : "#ccc",
                        color: "white",
                        border: "none",
                        borderRadius: "6px",
                        cursor: classTabInput.trim() ? "pointer" : "not-allowed",
                        transition: "all 0.3s ease",
                      }}
                      disabled={!classTabInput.trim()}
                    >
                      确认班级ID
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div style={{ marginBottom: "24px", padding: "16px", backgroundColor: "#f0f8ff", borderRadius: "8px" }}>
                    <p style={{ margin: "0", color: "#333" }}>
                      <strong>当前班级 ID：</strong> {classId}
                      <button
                        onClick={() => setClassIdConfirmed(false)}
                        style={{
                          marginLeft: "16px",
                          padding: "6px 12px",
                          fontSize: "12px",
                          backgroundColor: "#ddd",
                          color: "#333",
                          border: "none",
                          borderRadius: "4px",
                          cursor: "pointer",
                        }}
                      >
                        切换班级
                      </button>
                    </p>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "12px", marginBottom: "32px" }}>
                    {CLASS_SUB_TABS.map((subTab) => (
                      <button
                        key={subTab.id}
                        onClick={() => {
                          setTab(subTab.id as Tab);
                          if (subTab.id === "compare") loadCompare();
                          if (subTab.id === "capability") loadCapabilityMap();
                          if (subTab.id === "rule-coverage") loadRuleCoverage();
                          if (subTab.id === "interventions") loadTeachingInterventions();
                          if (subTab.id === "report") generateReport();
                        }}
                        style={{
                          padding: "12px 16px",
                          fontSize: "14px",
                          fontWeight: "600",
                          backgroundColor: "#f0f0f0",
                          color: "#333",
                          border: "1px solid #ddd",
                          borderRadius: "6px",
                          cursor: "pointer",
                          transition: "all 0.3s ease",
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
        /* ══════════════════════════════════════ */
        /* 全局样式 - 白底黑字高对比度 */
        /* ══════════════════════════════════════ */
        
        .tch-app {
          background-color: #ffffff;
          color: #222222;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
          --skeleton-bg: #e8e8e8;
        }

        .tch-body {
          display: flex;
          background-color: #ffffff;
          min-height: calc(100vh - 64px);
        }

        .tch-app h1, .tch-app h2, .tch-app h3, .tch-app h4, .tch-app h5 {
          color: #1a1a1a;
        }

        .tch-app p, .tch-app span, .tch-app div {
          color: #333333;
        }

        /* 顶部导航栏 */
        .chat-topbar {
          background: linear-gradient(135deg, #f8f9fa 0%, #ffffff 100%);
          border-bottom: 2px solid #e8e8e8;
          color: #1a1a1a;
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
        }

        .topbar-brand {
          color: #000000 !important;
          font-weight: 700;
        }

        .topbar-label {
          color: #444444;
          font-weight: 600;
        }

        .topbar-sep {
          border-left: 2px solid #e0e0e0;
        }

        .tch-filter-input {
          background-color: #ffffff;
          border: 1px solid #d0d0d0;
          color: #333333 !important;
          padding: 8px 12px;
          border-radius: 6px;
          font-size: 14px;
        }

        .tch-filter-input::placeholder {
          color: #999999;
        }

        .tch-filter-input:focus {
          border-color: #4a90e2;
          outline: none;
          box-shadow: 0 0 0 3px rgba(74, 144, 226, 0.1);
        }

        /* 按钮样式 */
        .topbar-btn {
          background-color: #4a90e2;
          color: #ffffff;
          border: none;
          padding: 8px 16px;
          border-radius: 6px;
          cursor: pointer;
          font-weight: 600;
          transition: all 0.2s ease;
        }

        .topbar-btn:hover {
          background-color: #3a7bc8;
          box-shadow: 0 4px 12px rgba(74, 144, 226, 0.3);
        }

        .topbar-btn.theme-toggle {
          background-color: #667ecc;
          margin-right: 8px;
          display: inline-flex;
          align-items: center;
          gap: 4px;
          font-size: 14px;
          padding: 8px 14px;
        }

        .topbar-btn.theme-toggle:hover {
          background-color: #5a6eb8;
          box-shadow: 0 4px 12px rgba(102, 126, 204, 0.3);
        }

        /* 侧边栏 */
        .tch-sidebar {
          background: linear-gradient(180deg, #f5f6f7 0%, #eeeff2 100%);
          border-right: 1px solid #e0e0e0;
          min-width: 240px;
          overflow-y: auto;
          max-height: calc(100vh - 64px);
          padding: 8px 0;
        }

        .tch-nav-btn {
          background-color: transparent;
          color: #333333;
          border: none;
          border-left: 4px solid transparent;
          padding: 14px 16px;
          width: 100%;
          text-align: left;
          cursor: pointer;
          font-weight: 500;
          font-size: 15px;
          transition: all 0.3s ease;
          margin: 4px 0;
        }

        .tch-nav-btn:hover:not(.disabled) {
          background-color: #e8ecf0;
          color: #1a1a1a;
          transform: translateX(4px);
        }

        .tch-nav-btn.active {
          background-color: #e3f2fd;
          color: #1a1a1a;
          border-left-color: #4a90e2;
          font-weight: 700;
        }

        .tch-nav-btn.disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        /* 主容器 */
        .tch-main {
          background-color: #ffffff;
          padding: 40px 48px;
          flex: 1;
          overflow-y: auto;
          max-height: calc(100vh - 64px);
          display: flex;
          flex-direction: column;
          align-items: center;
        }

        .tch-main > * {
          width: 100%;
          max-width: 1200px;
          margin-left: auto;
          margin-right: auto;
        }

        /* 面板卡片 */
        .tch-panel {
          background-color: #f9fafb;
          border: 1px solid #e0e0e0;
          border-radius: 12px;
          padding: 36px 40px;
          margin-bottom: 32px;
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
        }

        .tch-panel h2 {
          color: #1a1a1a;
          font-size: 28px;
          margin: 0 0 20px 0;
          border-bottom: 2px solid #e8e8e8;
          padding-bottom: 16px;
          font-weight: 700;
          letter-spacing: -0.5px;
        }

        .tch-panel h3 {
          color: #222222;
          font-size: 18px;
          margin: 32px 0 16px 0;
          font-weight: 600;
        }

        .tch-desc {
          color: #666666;
          font-size: 15px;
          line-height: 1.8;
          margin-bottom: 24px;
          letter-spacing: 0.3px;
        }

        /* KPI 卡片 */
        .kpi-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
          gap: 24px;
          margin-bottom: 32px;
        }

        .kpi {
          background: linear-gradient(135deg, #ffffff 0%, #f8f8f8 100%);
          border: 1px solid #e0e0e0;
          border-radius: 12px;
          padding: 32px 28px;
          text-align: center;
          box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05);
          transition: all 0.3s ease;
          min-height: 160px;
          display: flex;
          flex-direction: column;
          justify-content: center;
        }

        .kpi:hover {
          background-color: #ffffff;
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
          transform: translateY(-2px);
        }

        .kpi span {
          display: block;
          color: #666666;
          font-size: 13px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.8px;
          margin-bottom: 12px;
        }

        .kpi strong {
          display: block;
          color: #1a1a1a;
          font-size: 40px;
          font-weight: 700;
          margin-bottom: 12px;
          line-height: 1.2;
        }

        .kpi em {
          display: block;
          color: #999999;
          font-size: 13px;
          font-style: normal;
          margin-top: 8px;
          line-height: 1.6;
        }

        /* 视觉卡片 */
        .viz-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
          gap: 24px;
          margin-bottom: 32px;
        }

        .viz-card {
          background-color: #ffffff;
          border: 1px solid #e0e0e0;
          border-radius: 12px;
          padding: 28px 32px;
          box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05);
        }

        .viz-card h3 {
          color: #1a1a1a;
          margin-top: 0;
          margin-bottom: 16px;
          font-size: 18px;
          font-weight: 600;
        }

        .viz-card p {
          color: #666666;
          font-size: 14px;
          line-height: 1.7;
          margin-bottom: 16px;
        }

        /* 表格样式 */
        .tch-table {
          border: 1px solid #e0e0e0;
          border-radius: 8px;
          overflow: hidden;
          background-color: #ffffff;
        }

        .table-like {
          display: flex;
          flex-direction: column;
          gap: 8px;
          background-color: #ffffff;
        }

        .tch-table-header {
          display: grid;
          grid-template-columns: repeat(7, minmax(100px, 1fr));
          gap: 0;
          background: linear-gradient(135deg, #f0f2f5 0%, #e8ecf0 100%);
          border-bottom: 2px solid #e0e0e0;
          padding: 18px 16px;
          font-weight: 700;
          color: #1a1a1a;
          font-size: 13px;
          text-transform: uppercase;
          letter-spacing: 0.6px;
        }

        .tch-table-row {
          display: grid;
          grid-template-columns: repeat(7, minmax(100px, 1fr));
          gap: 0;
          padding: 18px 16px;
          border-bottom: 1px solid #e8e8e8;
          align-items: center;
          color: #333333;
          transition: all 0.2s ease;
          font-size: 15px;
          line-height: 1.6;
        }

        .tch-table-row:hover {
          background-color: #f5f5f5;
          border-left: 3px solid #4a90e2;
          padding-left: calc(16px - 3px);
        }

        /* 表格单元格 */
        .tch-cell-time {
          color: #666666;
          font-size: 13px;
        }

        .tch-cell-score {
          font-weight: 700;
          color: #1a1a1a;
        }

        /* 柱状图 */
        .bar-row {
          display: flex;
          align-items: center;
          gap: 16px;
          margin-bottom: 18px;
          padding: 12px 0;
        }

        .bar-row span:first-child {
          min-width: 140px;
          color: #333333;
          font-weight: 500;
          font-size: 15px;
          line-height: 1.6;
        }

        .bar-track {
          flex: 1;
          height: 28px;
          background-color: #e8e8e8;
          border-radius: 6px;
          overflow: hidden;
        }

        .bar-fill {
          height: 100%;
          background: linear-gradient(90deg, #4a90e2, #2ecc71);
          transition: width 0.4s ease;
        }

        .bar-fill.danger {
          background: linear-gradient(90deg, #ff6b6b, #e74c3c);
        }

        .bar-row em {
          min-width: 50px;
          text-align: right;
          color: #1a1a1a;
          font-weight: 600;
          font-style: normal;
          font-size: 15px;
        }

        /* 按钮 */
        .tch-sm-btn {
          background-color: #e3f2fd;
          color: #1976d2;
          border: 1px solid #90caf9;
          padding: 8px 16px;
          border-radius: 6px;
          cursor: pointer;
          font-size: 14px;
          font-weight: 600;
          margin-right: 12px;
          margin-bottom: 8px;
          transition: all 0.2s ease;
          line-height: 1.5;
        }

        .tch-sm-btn:hover {
          background-color: #bbdefb;
          border-color: #64b5f6;
          transform: scale(1.05);
        }

        .tch-sm-btn:active {
          transform: scale(0.95);
        }

        /* 项目项 */
        .project-item {
          background-color: #ffffff;
          border: 1px solid #e0e0e0;
          border-radius: 8px;
          padding: 16px 20px;
          margin-bottom: 12px;
          display: flex;
          justify-content: space-between;
          align-items: center;
          cursor: pointer;
          color: #333333;
          transition: all 0.2s ease;
          font-size: 15px;
          line-height: 1.6;
        }

        .project-item:hover {
          background-color: #f5f5f5;
          border-color: #4a90e2;
          box-shadow: 0 4px 12px rgba(74, 144, 226, 0.2);
          transform: translateX(4px);
        }

        /* 风险徽章 */
        .risk-badge {
          display: inline-block;
          padding: 6px 12px;
          border-radius: 6px;
          font-size: 13px;
          font-weight: 700;
          white-space: nowrap;
          line-height: 1.4;
        }

        .risk-badge.high {
          background-color: #ffebee;
          color: #c62828;
          border: 1px solid #ef5350;
        }

        .risk-badge.high em {
          color: #c62828;
        }

        /* 输入框 */
        input[type="text"],
        input[type="email"],
        textarea {
          background-color: #ffffff;
          color: #333333;
          border: 1px solid #d0d0d0;
          padding: 12px 16px;
          border-radius: 6px;
          font-size: 15px;
          font-family: inherit;
          transition: all 0.2s ease;
          line-height: 1.6;
        }

        input[type="text"]::placeholder,
        input[type="email"]::placeholder,
        textarea::placeholder {
          color: #999999;
        }

        input[type="text"]:focus,
        input[type="email"]:focus,
        textarea:focus {
          border-color: #4a90e2;
          outline: none;
          box-shadow: 0 0 0 3px rgba(74, 144, 226, 0.1);
          background-color: #ffffff;
          color: #333333;
        }

        /* 表单 */
        .tch-feedback-form {
          background-color: #f5f5f5;
          padding: 32px;
          border-radius: 8px;
          border: 1px solid #e0e0e0;
        }

        .tch-feedback-form label {
          display: block;
          margin-bottom: 16px;
          color: #333333;
          font-weight: 600;
          font-size: 15px;
          line-height: 1.6;
        }

        .tch-feedback-form input,
        .tch-feedback-form textarea {
          width: 100%;
          margin-bottom: 20px;
          box-sizing: border-box;
        }

        .tch-feedback-form button {
          background: linear-gradient(135deg, #4a90e2, #2ecc71);
          color: #ffffff;
          border: none;
          padding: 12px 28px;
          border-radius: 6px;
          cursor: pointer;
          font-weight: 600;
          font-size: 15px;
          transition: all 0.2s ease;
          line-height: 1.6;
        }

        .tch-feedback-form button:hover:not(:disabled) {
          transform: translateY(-2px);
          box-shadow: 0 4px 12px rgba(74, 144, 226, 0.3);
        }

        /* 反馈成功信息 */
        .tch-feedback-success {
          background-color: #c8e6c9;
          border: 1px solid #81c784;
          color: #2e7d32;
          padding: 12px 16px;
          border-radius: 6px;
          margin-top: 12px;
          font-weight: 600;
        }

        /* 证据项 */
        .evidence-item {
          background-color: #ffffff;
          border: 1px solid #e0e0e0;
          border-radius: 8px;
          padding: 20px;
          margin-bottom: 16px;
        }

        .tch-evidence-actions {
          display: flex;
          gap: 12px;
          margin-bottom: 16px;
        }

        .tch-evidence-actions input {
          flex: 1;
        }

        .evidence-item strong {
          color: #1a1a1a;
          display: block;
          margin-bottom: 12px;
          font-size: 15px;
          font-weight: 600;
        }

        .evidence-item p {
          color: #333333;
          margin: 12px 0;
          font-size: 15px;
          line-height: 1.7;
        }

        .evidence-item em {
          color: #999999;
          font-style: italic;
          font-size: 14px;
          display: block;
        }

        /* 提交详情 */
        .tch-submission-detail {
          background-color: #f5f5f5;
          border-left: 3px solid #4a90e2;
          padding: 24px;
          margin-top: 16px;
          border-radius: 4px;
        }

        .tch-detail-section {
          margin-bottom: 24px;
        }

        .tch-detail-section:last-child {
          margin-bottom: 0;
        }

        .tch-detail-section h4 {
          color: #1a1a1a;
          margin: 0 0 12px 0;
          font-size: 15px;
          font-weight: 600;
        }

        .tch-detail-section p {
          color: #333333;
          margin: 8px 0;
          font-size: 15px;
          line-height: 1.7;
        }

        .tch-raw-text {
          background-color: #ffffff;
          border: 1px solid #e0e0e0;
          padding: 12px;
          border-radius: 4px;
          color: #333333;
          line-height: 1.6;
          font-size: 13px;
          max-height: 300px;
          overflow-y: auto;
        }

        /* 右侧提示 */
        .right-hint {
          background-color: #e3f2fd;
          border-left: 4px solid #2196f3;
          color: #1565c0;
          padding: 12px 16px;
          border-radius: 4px;
          margin: 12px 0;
          font-size: 13px;
        }

        .right-tag {
          display: inline-block;
          background-color: #e8f5e9;
          border-left: 4px solid #4caf50;
          color: #2e7d32;
          padding: 12px 16px;
          border-radius: 4px;
          margin: 8px 0;
          font-size: 13px;
        }

        /* 加载状态 */
        .tch-loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 12px;
          min-height: 200px;
        }

        .tch-loading p {
          color: #333333;
          font-weight: 600;
        }

        /* 报告内容 */
        .tch-report-content {
          background-color: #f9fafb;
          border: 1px solid #e0e0e0;
          border-radius: 8px;
          padding: 20px;
          color: #333333;
          line-height: 1.8;
          white-space: pre-wrap;
          word-wrap: break-word;
        }

        .debug-json summary {
          cursor: pointer;
          color: #4a90e2;
          font-weight: 600;
          margin-bottom: 8px;
          user-select: none;
        }

        .debug-json pre {
          background-color: #f5f5f5;
          border: 1px solid #e0e0e0;
          color: #222222;
          padding: 12px;
          border-radius: 4px;
          overflow-x: auto;
          font-size: 12px;
          line-height: 1.5;
        }

        /* ══════════════════════════════════════ */
        /* 动画定义 */
        /* ══════════════════════════════════════ */
        @keyframes fade-in {
          from {
            opacity: 0;
          }
          to {
            opacity: 1;
          }
        }

        @keyframes fade-up {
          from {
            opacity: 0;
            transform: translateY(20px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        @keyframes slide-down {
          from {
            opacity: 0;
            max-height: 0;
          }
          to {
            opacity: 1;
            max-height: 2000px;
          }
        }

        @keyframes spin {
          from {
            transform: rotate(0deg);
          }
          to {
            transform: rotate(360deg);
          }
        }

        @keyframes progress-line {
          0% {
            width: 0%;
          }
          50% {
            width: 80%;
          }
          100% {
            width: 100%;
          }
        }

        @keyframes toast-slide-in {
          from {
            opacity: 0;
            transform: translateX(20px);
          }
          to {
            opacity: 1;
            transform: translateX(0);
          }
        }

        @keyframes number-scale {
          from {
            opacity: 0;
            transform: scale(0.8);
          }
          to {
            opacity: 1;
            transform: scale(1);
          }
        }

        @keyframes skeleton-loading {
          0% {
            background-color: #e8e8e8;
          }
          50% {
            background-color: #f0f0f0;
          }
          100% {
            background-color: #e8e8e8;
          }
        }

        @keyframes skeleton-pulse {
          0%, 100% {
            opacity: 1;
          }
          50% {
            opacity: 0.8;
          }
        }

        /* 优化加载状态 */
        .tch-loading {
          animation: fade-in 0.3s ease-out;
        }

        /* 过渡效果 */
        .tch-panel {
          animation: fade-up 0.4s ease-out;
        }

        .tch-nav-btn {
          position: relative;
          transition: all 0.3s ease;
        }

        .tch-nav-btn:hover:not(.disabled) {
          transform: translateX(4px);
          box-shadow: 0 2px 8px rgba(74, 144, 226, 0.2);
        }

        .tch-nav-btn.active {
          font-weight: 600;
          border-left: 3px solid #4a90e2;
          padding-left: calc(1rem - 3px);
        }

        .tch-nav-btn.disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        /* 按钮优化 */
        .tch-sm-btn {
          transition: all 0.2s ease;
          transform: scale(1);
        }

        .tch-sm-btn:hover {
          transform: scale(1.05);
          box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
        }

        .tch-sm-btn:active {
          transform: scale(0.95);
        }

        /* KPI 卡片优化 */
        .kpi {
          transition: all 0.3s ease;
          transform: translateY(0);
        }

        .kpi:hover {
          transform: translateY(-2px);
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
        }

        /* 项目项优化 */
        .project-item {
          transition: all 0.2s ease;
        }

        .project-item:hover {
          transform: translateX(4px);
          box-shadow: 0 4px 12px rgba(74, 144, 226, 0.2);
        }

        /* 表格行优化 */
        .tch-table-row {
          transition: all 0.2s ease, background-color 0.2s ease;
        }

        .tch-table-row:hover {
          background-color: #f9f9f9;
        }

        /* 输入框优化 */
        input[type="text"],
        input[type="email"],
        textarea {
          transition: all 0.2s ease;
          border: 1px solid #ddd;
        }

        input[type="text"]:focus,
        input[type="email"]:focus,
        textarea:focus {
          border-color: #4a90e2;
          box-shadow: 0 0 0 3px rgba(74, 144, 226, 0.1);
          outline: none;
        }

        /* 反馈表单样式 */
        .tch-feedback-form {
          animation: fade-in 0.4s ease-out;
        }

        .tch-feedback-form button {
          transition: all 0.2s ease;
          background: linear-gradient(135deg, #4a90e2, #2ecc71);
          border: none;
          color: white;
          padding: 10px 20px;
          border-radius: 6px;
          cursor: pointer;
          font-weight: 600;
        }

        .tch-feedback-form button:hover:not(:disabled) {
          transform: translateY(-2px);
          box-shadow: 0 4px 12px rgba(74, 144, 226, 0.3);
        }

        .tch-feedback-form button:active {
          transform: translateY(0);
        }

        /* 成功提示动画 */
        .tch-feedback-success {
          animation: slide-down 0.3s ease-out;
          padding: 12px 16px;
          background-color: #d4edda;
          border: 1px solid #c3e6cb;
          border-radius: 6px;
          color: #155724;
          margin-top: 12px;
        }

        /* 骨架屏加载 */
        [style*="animation: skeleton-loading"] {
          animation: skeleton-loading 1.5s ease-in-out infinite !important;
        }

        /* ══════════════════════════════════════ */
        /* 响应式设计 - 移动端优化 */
        /* ══════════════════════════════════════ */
        
        @media (max-width: 768px) {
          .tch-main {
            padding: 24px 16px;
          }

          .tch-body {
            flex-direction: column;
          }

          .tch-sidebar {
            min-width: 100%;
            max-height: auto;
            border-right: none;
            border-bottom: 1px solid #e0e0e0;
            display: flex;
            overflow-x: auto;
            overflow-y: hidden;
          }

          .tch-nav-btn {
            border-left: none;
            border-bottom: 3px solid transparent;
            padding: 12px 16px;
            white-space: nowrap;
          }

          .tch-nav-btn.active {
            border-left: none;
            border-bottom-color: #4a90e2;
          }

          .tch-panel {
            padding: 24px 16px;
            margin-bottom: 16px;
          }

          .tch-panel h2 {
            font-size: 20px;
            margin: 0 0 16px 0;
            padding-bottom: 12px;
          }

          .kpi-grid {
            grid-template-columns: 1fr;
            gap: 12px;
          }

          .kpi {
            padding: 20px 16px;
            min-height: 120px;
          }

          .kpi strong {
            font-size: 32px;
          }

          .viz-grid {
            grid-template-columns: 1fr;
            gap: 16px;
          }

          .tch-table-header,
          .tch-table-row {
            grid-template-columns: 1fr;
            column-gap: 0;
          }

          .tch-table-header {
            display: none;
          }

          .tch-table-row {
            padding: 16px 12px;
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            margin-bottom: 12px;
          }

          .tch-feedback-form {
            padding: 16px;
          }

          input[type="text"],
          input[type="email"],
          textarea {
            font-size: 16px;
          }

          .topbar-center {
            display: none;
          }
        }

        /* 平板设备优化 */
        @media (min-width: 769px) and (max-width: 1024px) {
          .tch-main {
            padding: 32px 24px;
          }

          .kpi-grid {
            grid-template-columns: repeat(2, 1fr);
          }

          .viz-grid {
            grid-template-columns: 1fr;
          }

          .tch-table-header,
          .tch-table-row {
            grid-template-columns: repeat(4, 1fr);
          }
        }

        /* 可访问性 - 禁用动画 */
        @media (prefers-reduced-motion: reduce) {
          button,
          input,
          textarea,
          a,
          .tch-nav-btn,
          .tch-sm-btn,
          .kpi,
          .project-item,
          .tch-table-row,
          .tch-panel,
          .tch-feedback-form {
            animation-duration: 0.01ms !important;
            animation-iteration-count: 1 !important;
            transition-duration: 0.01ms !important;
          }

          @keyframes fade-in,
          @keyframes fade-up,
          @keyframes slide-down,
          @keyframes slide-up,
          @keyframes spin,
          @keyframes bounce,
          @keyframes pulse-grow {
            0% { clip-path: inset(0); }
            100% { clip-path: inset(0); }
          }
        }

        /* 焦点可见优化 - 增强可访问性 */
        button:focus-visible,
        input:focus-visible,
        textarea:focus-visible,
        a:focus-visible {
          outline: 3px solid #4a90e2;
          outline-offset: 2px;
        }

        /* 禁用状态 */
        button:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        /* 高对比度模式支持 */
        @media (prefers-contrast: more) {
          .tch-panel {
            border-color: #000;
            border-width: 2px;
          }

          .topbar-btn {
            border: 2px solid #000;
          }

          input[type="text"],
          input[type="email"],
          textarea {
            border-width: 2px;
          }
        }

        /* ══════════════════════════════════════ */
        /* 额外动画定义 */
        /* ══════════════════════════════════════ */
        
        @keyframes slide-up {
          from {
            opacity: 0;
            transform: translateY(20px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        @keyframes bounce {
          0%, 100% {
            transform: translateY(0);
          }
          50% {
            transform: translateY(-10px);
          }
        }

        @keyframes shimmer {
          0% {
            background-position: -1000px 0;
          }
          100% {
            background-position: 1000px 0;
          }
        }

        @keyframes pulse-grow {
          0% {
            transform: scale(1);
            opacity: 1;
          }
          50% {
            opacity: 0.7;
          }
          100% {
            transform: scale(1.05);
            opacity: 0;
          }
        }

        @keyframes slide-left {
          from {
            opacity: 0;
            transform: translateX(20px);
          }
          to {
            opacity: 1;
            transform: translateX(0);
          }
        }

        /* 新增样式类 */
        .bounce {
          animation: bounce 0.6s ease-in-out;
        }

        .shimmer-bg {
          background: linear-gradient(90deg, #f0f0f0, #e8e8e8, #f0f0f0);
          background-size: 200% 100%;
          animation: shimmer 2s infinite;
        }

        .pulse-ring {
          animation: pulse-grow 1.5s ease-out;
        }

        /* ══════════════════════════════════════ */
        /* 打印样式 */
        /* ══════════════════════════════════════ */
        
        @media print {
          .tch-sidebar,
          .chat-topbar,
          .tch-nav-btn {
            display: none;
          }

          .tch-body {
            min-height: auto;
          }

          .tch-main {
            padding: 0;
            max-height: none;
            overflow: visible;
          }

          .tch-panel {
            page-break-inside: avoid;
            box-shadow: none;
            border: 1px solid #ccc;
          }

          a {
            color: #0066cc;
            text-decoration: underline;
          }
        }

        /* 深色模式支持 - 纯黑底白字高对比度配色 */
        [data-theme="dark"] {
          color-scheme: dark;
        }

        [data-theme="dark"] .tch-app {
          background-color: #000000;
          color: #ffffff;
          --skeleton-bg: #1a1a1a;
        }

        [data-theme="dark"] .tch-body {
          background-color: #000000;
        }

        [data-theme="dark"] .tch-main {
          background-color: #000000;
        }

        [data-theme="dark"] .tch-panel {
          background-color: #0a0a0a;
          border-color: #333333;
        }

        [data-theme="dark"] .tch-panel h2,
        [data-theme="dark"] .tch-panel h3,
        [data-theme="dark"] .tch-app h1,
        [data-theme="dark"] .tch-app h2,
        [data-theme="dark"] .tch-app h3,
        [data-theme="dark"] .tch-app h4 {
          color: #ffffff;
        }

        [data-theme="dark"] .tch-app p,
        [data-theme="dark"] .tch-app span,
        [data-theme="dark"] .tch-app div {
          color: #ffffff;
        }

        [data-theme="dark"] .tch-sidebar {
          background: linear-gradient(180deg, #0a0a0a 0%, #000000 100%);
          border-right-color: #333333;
        }

        [data-theme="dark"] .tch-nav-btn {
          background-color: transparent;
          color: #ffffff;
          border-left-color: transparent;
        }

        [data-theme="dark"] .tch-nav-btn:hover:not(.disabled) {
          background-color: #1a1a1a;
          color: #ffffff;
          border-left-color: transparent;
        }

        [data-theme="dark"] .tch-nav-btn.active {
          background-color: #1a3a5a;
          color: #ffffff;
          border-left-color: #4a90e2;
          font-weight: 600;
        }

        [data-theme="dark"] .kpi {
          background: linear-gradient(135deg, #0a0a0a 0%, #000000 100%);
          border-color: #333333;
        }

        [data-theme="dark"] .kpi strong {
          color: #ffffff;
        }

        [data-theme="dark"] .kpi span {
          color: #cccccc;
        }

        [data-theme="dark"] .kpi em {
          color: #aaaaaa;
        }

        [data-theme="dark"] .kpi:hover {
          background: linear-gradient(135deg, #0a0a0a 0%, #000000 100%);
          border-color: #4a90e2;
          box-shadow: 0 4px 12px rgba(74, 144, 226, 0.2);
        }

        [data-theme="dark"] .chat-topbar {
          background: linear-gradient(135deg, #0a0a0a 0%, #000000 100%);
          border-bottom-color: #333333;
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.8);
        }

        [data-theme="dark"] .topbar-brand {
          color: #ffffff;
        }

        [data-theme="dark"] .topbar-label {
          color: #cccccc;
        }

        [data-theme="dark"] .topbar-sep {
          border-left-color: #333333;
        }

        [data-theme="dark"] .topbar-btn {
          background-color: #1a3a5a;
          color: #ffffff;
          border-color: #333333;
          transition: all 0.2s ease;
        }

        [data-theme="dark"] .topbar-btn:hover {
          background-color: #2a5a8a;
          border-color: #4a90e2;
          box-shadow: 0 2px 8px rgba(74, 144, 226, 0.3);
        }

        [data-theme="dark"] .topbar-btn.theme-toggle {
          background-color: #1a3a5a;
          border: 1px solid #333333;
        }

        [data-theme="dark"] .topbar-btn.theme-toggle:hover {
          background-color: #2a5a8a;
          border-color: #4a90e2;
          box-shadow: 0 2px 8px rgba(74, 144, 226, 0.2);
        }

        [data-theme="dark"] .tch-filter-input {
          background-color: #0a0a0a;
          color: #ffffff;
          border-color: #333333;
        }

        [data-theme="dark"] .tch-filter-input::placeholder {
          color: #888888;
        }

        [data-theme="dark"] .tch-filter-input:focus {
          border-color: #4a90e2;
          box-shadow: 0 0 0 3px rgba(74, 144, 226, 0.2);
          background-color: #000000;
        }

        [data-theme="dark"] input[type="text"],
        [data-theme="dark"] input[type="email"],
        [data-theme="dark"] textarea {
          background-color: #0a0a0a;
          color: #ffffff;
          border-color: #333333;
        }

        [data-theme="dark"] input[type="text"]::placeholder,
        [data-theme="dark"] input[type="email"]::placeholder,
        [data-theme="dark"] textarea::placeholder {
          color: #888888;
        }

        [data-theme="dark"] input[type="text"]:focus,
        [data-theme="dark"] input[type="email"]:focus,
        [data-theme="dark"] textarea:focus {
          border-color: #4a90e2;
          box-shadow: 0 0 0 3px rgba(74, 144, 226, 0.2);
          background-color: #000000;
        }

        [data-theme="dark"] .tch-table {
          border-color: #333333;
          background-color: #000000;
        }

        [data-theme="dark"] .tch-table-header {
          background: linear-gradient(135deg, #0a0a0a 0%, #000000 100%);
          border-bottom-color: #333333;
          color: #ffffff;
        }

        [data-theme="dark"] .tch-table-row {
          border-bottom-color: #1a1a1a;
          color: #ffffff;
        }

        [data-theme="dark"] .tch-table-row:hover {
          background-color: #0a0a0a;
          border-left-color: #4a90e2;
        }

        [data-theme="dark"] .project-item {
          background-color: #0a0a0a;
          border-color: #333333;
          color: #ffffff;
        }

        [data-theme="dark"] .project-item:hover {
          background-color: #1a1a1a;
          border-color: #4a90e2;
          box-shadow: 0 4px 12px rgba(74, 144, 226, 0.2);
        }

        [data-theme="dark"] .risk-badge {
          background-color: #1a0a0a;
          border-color: #4a2a2a;
          color: #ffaa88;
        }

        [data-theme="dark"] .risk-badge.high {
          background-color: #2a1515;
          color: #ff9999;
          border-color: #6a3a3a;
        }

        [data-theme="dark"] .tch-feedback-form {
          background-color: #0a0a0a;
          border-color: #333333;
        }

        [data-theme="dark"] .tch-feedback-form label {
          color: #ffffff;
        }

        [data-theme="dark"] .tch-feedback-form button {
          background: linear-gradient(135deg, #1a3a5a, #2a5a8a);
          border: 1px solid #4a90e2;
          color: #ffffff;
        }

        [data-theme="dark"] .tch-feedback-form button:hover:not(:disabled) {
          background: linear-gradient(135deg, #2a5a8a, #3a7aaa);
          box-shadow: 0 4px 12px rgba(74, 144, 226, 0.3);
        }

        [data-theme="dark"] .viz-card {
          background-color: #0a0a0a;
          border-color: #333333;
        }

        [data-theme="dark"] .viz-card h3 {
          color: #ffffff;
        }

        [data-theme="dark"] .viz-card p {
          color: #cccccc;
        }

        [data-theme="dark"] .evidence-item {
          background-color: #0a0a0a;
          border-color: #333333;
        }

        [data-theme="dark"] .evidence-item strong {
          color: #ffffff;
        }

        [data-theme="dark"] .evidence-item p {
          color: #ffffff;
        }

        [data-theme="dark"] .evidence-item em {
          color: #aaaaaa;
        }

        [data-theme="dark"] .tch-submission-detail {
          background-color: #000000;
          border-left-color: #4a90e2;
        }

        [data-theme="dark"] .tch-detail-section h4 {
          color: #ffffff;
        }

        [data-theme="dark"] .tch-detail-section p {
          color: #ffffff;
        }

        [data-theme="dark"] .tch-raw-text {
          background-color: #000000;
          border-color: #333333;
          color: #ffffff;
        }

        [data-theme="dark"] .tch-loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 12px;
          min-height: 200px;
        }

        [data-theme="dark"] .tch-loading p {
          color: #ffffff;
        }

        [data-theme="dark"] .tch-report-content {
          background-color: #000000;
          border-color: #333333;
          color: #ffffff;
        }

        [data-theme="dark"] .tch-sm-btn {
          background-color: #1a3a5a;
          color: #ffffff;
          border-color: #333333;
        }

        [data-theme="dark"] .tch-sm-btn:hover {
          background-color: #2a5a8a;
          border-color: #4a90e2;
        }

        [data-theme="dark"] .right-hint {
          background-color: #0a1a3a;
          border-left-color: #4a90e2;
          color: #aaddff;
        }

        [data-theme="dark"] .right-tag {
          background-color: #0a2a1a;
          border-left-color: #4fbb6a;
          color: #88ff99;
        }

        [data-theme="dark"] .bar-row span:first-child {
          color: #ffffff;
        }

        [data-theme="dark"] .bar-track {
          background-color: #1a1a1a;
        }

        [data-theme="dark"] .bar-fill {
          background: linear-gradient(90deg, #4a90e2, #4fbb6a);
        }

        [data-theme="dark"] .bar-fill.danger {
          background: linear-gradient(90deg, #ff6b6b, #ff5252);
        }

        [data-theme="dark"] .bar-row em {
          color: #ffffff;
        }

        [data-theme="dark"] .debug-json summary {
          color: #4a90e2;
        }

        [data-theme="dark"] .debug-json pre {
          background-color: #000000;
          border-color: #333333;
          color: #ffffff;
        }

        [data-theme="dark"] .tch-desc {
          color: #cccccc;
        }

        [data-theme="dark"] .tch-cell-time {
          color: #aaaaaa;
        }

        [data-theme="dark"] .tch-cell-score {
          color: #ffffff;
        }

        [data-theme="dark"] .tch-feedback-success {
          background-color: #0a2a0a;
          border: 1px solid #4a7a4a;
          color: #88ff88;
        }

        [data-theme="dark"] ::selection {
          background-color: #1a4d7a;
          color: #ffffff;
        }

        [data-theme="dark"] ::-moz-selection {
          background-color: #1a4d7a;
          color: #ffffff;
        }

        [data-theme="dark"] .tch-main::-webkit-scrollbar-track {
          background: #000000;
        }

        [data-theme="dark"] .tch-main::-webkit-scrollbar-thumb {
          background: #4a4a4a;
        }

        [data-theme="dark"] .tch-main::-webkit-scrollbar-thumb:hover {
          background: #6a6a6a;
        }

        [data-theme="dark"] .tch-sidebar::-webkit-scrollbar-track {
          background: #000000;
        }

        [data-theme="dark"] .tch-sidebar::-webkit-scrollbar-thumb {
          background: #4a4a4a;
        }

        [data-theme="dark"] .tch-sidebar::-webkit-scrollbar-thumb:hover {
          background: #6a6a6a;
        }

        [data-theme="dark"] .tch-raw-text::-webkit-scrollbar-track {
          background: #000000;
        }

        [data-theme="dark"] .tch-raw-text::-webkit-scrollbar-thumb {
          background: #4a4a4a;
        }

        [data-theme="dark"] .tch-raw-text::-webkit-scrollbar-thumb:hover {
          background: #6a6a6a;
        }

        /* 可选: 系统偏好深色模式的后备方案 */
        @media (prefers-color-scheme: dark) {
          :not([data-theme]) {
            color-scheme: dark;
          }
        }

        /* 性能优化 */
        
        .tch-nav-btn,
        .tch-sm-btn,
        .project-item,
        .kpi,
        input,
        textarea {
          will-change: transform, background-color;
        }

        /* 加速 GPU 渲染 */
        .tch-panel,
        .viz-card,
        .tch-table-row {
          transform: translateZ(0);
          backface-visibility: hidden;
        }

        /* 溢出内容处理 */
        .tch-raw-text {
          overflow-wrap: break-word;
          word-break: break-word;
        }

        /* 文本选择样式 */
        ::selection {
          background-color: #4a90e2;
          color: #ffffff;
        }

        ::-moz-selection {
          background-color: #4a90e2;
          color: #ffffff;
        }

        /* 滚动条美化 */
        .tch-main::-webkit-scrollbar,
        .tch-sidebar::-webkit-scrollbar,
        .tch-raw-text::-webkit-scrollbar {
          width: 8px;
          height: 8px;
        }

        .tch-main::-webkit-scrollbar-track,
        .tch-sidebar::-webkit-scrollbar-track,
        .tch-raw-text::-webkit-scrollbar-track {
          background: #f0f0f0;
        }

        .tch-main::-webkit-scrollbar-thumb,
        .tch-sidebar::-webkit-scrollbar-thumb,
        .tch-raw-text::-webkit-scrollbar-thumb {
          background: #ccc;
          border-radius: 4px;
        }

        .tch-main::-webkit-scrollbar-thumb:hover,
        .tch-sidebar::-webkit-scrollbar-thumb:hover,
        .tch-raw-text::-webkit-scrollbar-thumb:hover {
          background: #999;
        }

        /* iOS 及浏览器兼容性处理 */

        /* Firefox 特定修复 */
        @-moz-document url-prefix() {
          input[type="text"],
          input[type="email"],
          textarea {
            background-clip: padding-box;
          }
        }

        /* Safari 特定修复 */
        @supports (-webkit-appearance: none) {
          input[type="text"],
          input[type="email"],
          textarea {
            -webkit-appearance: none;
            -moz-appearance: none;
            appearance: none;
          }
        }

        /* 确保一致的字体渲染 */
        html {
          -webkit-font-smoothing: antialiased;
          -moz-osx-font-smoothing: grayscale;
        }
      `}
      </style>
    </div>
  );
}
