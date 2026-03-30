"""
教师写回反馈文件管理 API
1. 获取学生提交文件列表
2. 获取文件内容预览、在线阅读
3. 保存教师批注
4. 上传处理后的反馈文件
"""

from fastapi import FastAPI, Form, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
from datetime import datetime
from uuid import uuid4
import json
import base64
from app.services.document_parser import (
    get_file_preview_data,
    extract_pdf_text_chunked,
    get_pdf_key_insights,
)
from app.services.llm_client import LlmClient

def setup_teacher_file_feedback_routes(app: FastAPI, json_store, settings):
    """配置所有教师文件反馈相关的路由"""

    def _logical_project_key(submission: dict, project_id: str) -> str:
        return str(
            submission.get("logical_project_id")
            or submission.get("project_id")
            or submission.get("conversation_id")
            or project_id
        )

    def _project_display_name(submission: dict, order_num: int) -> str:
        filename = str(submission.get("filename", "") or "").strip()
        if filename:
            stem = Path(filename).stem.strip()
            if stem:
                return f"项目 {order_num:02d} · {stem[:24]}"
        return f"项目 {order_num:02d}"

    def _build_project_meta(submissions: list[dict], project_id: str) -> tuple[dict[str, dict], dict[str, int]]:
        grouped: dict[str, list[dict]] = {}
        for submission in submissions:
            logical_id = _logical_project_key(submission, project_id)
            grouped.setdefault(logical_id, []).append(submission)
        ordered_groups = sorted(
            grouped.items(),
            key=lambda item: max(str(row.get("created_at", "") or "") for row in item[1]),
            reverse=True,
        )
        project_meta: dict[str, dict] = {}
        material_order: dict[str, int] = {}
        for project_index, (logical_id, rows) in enumerate(ordered_groups, start=1):
            rows_sorted = sorted(rows, key=lambda row: str(row.get("created_at", "") or ""), reverse=True)
            latest = rows_sorted[0] if rows_sorted else {}
            display_name = _project_display_name(latest, project_index)
            project_meta[logical_id] = {
                "project_order": project_index,
                "project_display_name": display_name,
                "project_phase": latest.get("project_phase", "") or "",
            }
            for material_index, row in enumerate(rows_sorted, start=1):
                submission_id = str(row.get("submission_id", "") or "")
                if submission_id:
                    material_order[submission_id] = material_index
        return project_meta, material_order

    def _find_uploaded_file(project_id: str, filename: str) -> Path | None:
        if not filename:
            return None
        uploaded_files = settings.upload_root / project_id
        if not uploaded_files.exists():
            return None
        for file_path in uploaded_files.iterdir():
            if filename in file_path.name:
                return file_path
        return None

    def _flatten_annotation_records(records: list[dict]) -> list[dict]:
        flattened: list[dict] = []
        for record in records:
            annotations = record.get("annotations", []) or []
            for idx, ann in enumerate(annotations):
                if not isinstance(ann, dict):
                    continue
                flattened.append({
                    "annotation_id": str(record.get("annotation_id", "") or ""),
                    "annotation_item_id": f"{record.get('annotation_id', '')}:{idx}",
                    "created_at": str(record.get("created_at", "") or ""),
                    "teacher_id": str(record.get("teacher_id", "") or ""),
                    "overall_feedback": str(record.get("overall_feedback", "") or ""),
                    "focus_areas": [str(x) for x in (record.get("focus_areas", []) or []) if str(x).strip()],
                    "type": str(ann.get("type", "") or "comment"),
                    "position": int(ann.get("position", 0) or 0),
                    "length": int(ann.get("length", 0) or 0),
                    "quote": str(ann.get("quote", "") or ""),
                    "content": str(ann.get("content", "") or ""),
                    "annotation_type": str(ann.get("annotation_type", "") or "issue"),
                })
        flattened.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return flattened
    
    # ═══════════════════════════════════════════════════════════════════
    #  学生提交文件管理 APIs
    # ═══════════════════════════════════════════════════════════════════
    
    @app.get("/api/teacher/student-files/{project_id}")
    def get_student_files(project_id: str):
        """获取学生为某个项目提交的所有文件
        
        返回：
        - files: 文件列表，包含文件名、提交时间、学生ID、诊断信息等
        """
        project_state = json_store.load_project(project_id)
        submissions = project_state.get("submissions", []) or []
        
        file_submissions = []
        for submission in submissions:
            source_type = submission.get("source_type", "")
            # 只返回文件提交（排除纯文本对话）
            if source_type not in ["file", "file_in_chat"]:
                continue
            file_submissions.append(submission)

        project_meta, material_order = _build_project_meta(file_submissions, project_id)
        files = []
        for submission in file_submissions:
            filename = submission.get("filename", "unknown")
            diagnosis = submission.get("diagnosis", {}) or {}
            logical_project_id = _logical_project_key(submission, project_id)
            meta = project_meta.get(logical_project_id, {})
            material_index = material_order.get(str(submission.get("submission_id", "") or ""), 0)
            
            files.append({
                "submission_id": submission.get("submission_id", ""),
                "logical_project_id": logical_project_id,
                "filename": filename,
                "student_id": submission.get("student_id", ""),
                "created_at": submission.get("created_at", ""),
                "project_phase": submission.get("project_phase", "") or "",
                "project_order": meta.get("project_order", 0),
                "project_display_name": meta.get("project_display_name", logical_project_id),
                "material_order": material_index,
                "material_display_name": f"材料 {material_index:02d}" if material_index else "材料",
                "raw_text_length": len(submission.get("raw_text", "")),
                "overall_score": diagnosis.get("overall_score", 0),
                "bottleneck": diagnosis.get("bottleneck", ""),
                "triggered_rules": [r.get("id") for r in diagnosis.get("triggered_rules", []) if isinstance(r, dict)],
            })
        
        # 按时间倒序排列
        files.sort(key=lambda x: x["created_at"], reverse=True)
        
        return {
            "project_id": project_id,
            "file_count": len(files),
            "files": files,
        }
    
    
    @app.get("/api/teacher/student-file/{project_id}/{submission_id}")
    def get_student_file_content(project_id: str, submission_id: str):
        """获取学生提交文件的内容与预览数据
        
        返回：
        - filename: 文件名
        - file_type: 文件格式（pdf, docx, pptx等）
        - raw_text: 文件提取的完整文本
        - preview_data: 用于前端预览的结构化数据
        - diagnosis: 诊断结果
        - student_id: 学生ID
        - created_at: 提交时间
        """
        project_state = json_store.load_project(project_id)
        submissions = project_state.get("submissions", []) or []
        
        file_submissions = [
            submission
            for submission in submissions
            if submission.get("source_type", "") in ["file", "file_in_chat"]
        ]
        project_meta, material_order = _build_project_meta(file_submissions, project_id)

        # 查找相应的提交
        target_submission = None
        for submission in submissions:
            if submission.get("submission_id") == submission_id:
                target_submission = submission
                break
        
        if not target_submission:
            raise HTTPException(status_code=404, detail="File submission not found")
        
        source_type = target_submission.get("source_type", "")
        if source_type not in ["file", "file_in_chat"]:
            raise HTTPException(status_code=400, detail="This is not a file submission")
        
        # 提取文件格式
        filename = target_submission.get("filename", "")
        file_ext = ""
        if filename:
            file_ext = filename.split(".")[-1].lower() if "." in filename else ""
        
        # 构建预览数据 - 根据文件格式提供结构化信息
        preview_data = {}
        raw_text = target_submission.get("raw_text", "")
        
        if file_ext == "pdf":
            # PDF：返回按页分割的内容
            pages = []
            if raw_text:
                # 简单的分页逻辑 - 基于"page_X"标记或按长度分割
                segments = raw_text.split("\n\n")  # 基本分割
                current_page = {"page_num": 1, "content": ""}
                char_count = 0
                
                for seg in segments:
                    if char_count > 2000:  # 每页约2000字符
                        pages.append(current_page)
                        current_page = {"page_num": len(pages) + 1, "content": ""}
                        char_count = 0
                    current_page["content"] += seg + "\n\n"
                    char_count += len(seg)
                
                if current_page["content"].strip():
                    pages.append(current_page)
            
            preview_data = {
                "type": "pdf",
                "page_count": len(pages) if pages else 1,
                "pages": pages,
                "total_chars": len(raw_text),
            }
        
        elif file_ext in ["pptx", "ppt"]:
            # PPT：返回按幻灯片分割的内容
            slides = []
            if raw_text:
                segments = raw_text.split("\n---SLIDE_BREAK---\n")  # PPT段分割标记
                if len(segments) == 1:
                    # 如果没有标记，按长度分割
                    parts = raw_text.split("\n\n")
                    slide_content = ""
                    for i, part in enumerate(parts):
                        slide_content += part + "\n"
                        if len(slide_content) > 1500 or i == len(parts) - 1:
                            slides.append({
                                "slide_num": len(slides) + 1,
                                "content": slide_content.strip()
                            })
                            slide_content = ""
                else:
                    for i, seg in enumerate(segments):
                        if seg.strip():
                            slides.append({
                                "slide_num": i + 1,
                                "content": seg.strip()
                            })
            
            preview_data = {
                "type": "pptx",
                "slide_count": len(slides),
                "slides": slides,
                "total_chars": len(raw_text),
            }
        
        elif file_ext == "docx":
            # DOCX：返回按段落分割的内容
            paragraphs = []
            if raw_text:
                segments = raw_text.split("\n")
                for i, seg in enumerate(segments):
                    if seg.strip():
                        paragraphs.append({
                            "para_num": len(paragraphs) + 1,
                            "content": seg.strip()
                        })
            
            preview_data = {
                "type": "docx",
                "paragraph_count": len(paragraphs),
                "paragraphs": paragraphs,
                "total_chars": len(raw_text),
            }
        
        else:
            # 其他格式
            preview_data = {
                "type": file_ext,
                "total_chars": len(raw_text),
            }
        
        logical_project_id = _logical_project_key(target_submission, project_id)
        meta = project_meta.get(logical_project_id, {})
        material_index = material_order.get(submission_id, 0)

        target_file = _find_uploaded_file(project_id, filename)
        return {
            "project_id": project_id,
            "submission_id": submission_id,
            "logical_project_id": logical_project_id,
            "project_order": meta.get("project_order", 0),
            "project_display_name": meta.get("project_display_name", logical_project_id),
            "material_order": material_index,
            "material_display_name": f"材料 {material_index:02d}" if material_index else "材料",
            "filename": filename,
            "file_type": file_ext,
            "student_id": target_submission.get("student_id", ""),
            "created_at": target_submission.get("created_at", ""),
            "raw_text": raw_text,
            "preview_data": preview_data,
            "diagnosis": target_submission.get("diagnosis", {}),
            "next_task": target_submission.get("next_task", {}),
            "evidence_quotes": target_submission.get("evidence_quotes", []) or [],
            "kg_analysis": target_submission.get("kg_analysis", {}) or {},
            "matched_teacher_interventions": target_submission.get("matched_teacher_interventions", []) or [],
            "download_url": f"/api/teacher/student-file-download/{project_id}/{submission_id}" if target_file else "",
        }

    @app.get("/api/teacher/student-file-download/{project_id}/{submission_id}")
    def download_student_file(project_id: str, submission_id: str):
        project_state = json_store.load_project(project_id)
        submissions = project_state.get("submissions", []) or []
        target_submission = next((submission for submission in submissions if submission.get("submission_id") == submission_id), None)
        if not target_submission:
            raise HTTPException(status_code=404, detail="File submission not found")
        filename = str(target_submission.get("filename", "") or "")
        target_file = _find_uploaded_file(project_id, filename)
        if not target_file or not target_file.exists():
            raise HTTPException(status_code=404, detail="Original file not found")
        media_type = "application/octet-stream"
        return FileResponse(path=target_file, filename=filename or target_file.name, media_type=media_type)

    @app.get("/api/student/project/{project_id}/annotation-boards")
    def get_student_annotation_boards(project_id: str):
        project_state = json_store.load_project(project_id)
        submissions = project_state.get("submissions", []) or []
        teacher_annotations = project_state.get("teacher_annotations", []) or []
        feedback_files = project_state.get("teacher_feedback_files", []) or []
        project_feedback = project_state.get("teacher_feedback", []) or []

        project_meta, material_order = _build_project_meta(submissions, project_id)
        submission_map = {
            str(submission.get("submission_id", "") or ""): submission
            for submission in submissions
            if str(submission.get("submission_id", "") or "")
        }

        records_by_submission: dict[str, list[dict]] = {}
        for record in teacher_annotations:
            sid = str(record.get("submission_id", "") or "")
            if not sid:
                continue
            records_by_submission.setdefault(sid, []).append(record)

        files_by_submission: dict[str, list[dict]] = {}
        for record in feedback_files:
            sid = str(record.get("submission_id", "") or "")
            if not sid:
                continue
            files_by_submission.setdefault(sid, []).append({
                **record,
                "file_url": str(record.get("file_url", "") or ""),
            })

        boards: list[dict] = []
        for submission_id, records in records_by_submission.items():
            submission = submission_map.get(submission_id)
            if not submission:
                continue
            logical_project_id = _logical_project_key(submission, project_id)
            meta = project_meta.get(logical_project_id, {})
            flat_annotations = _flatten_annotation_records(records)
            followups = [
                row for row in submissions
                if _logical_project_key(row, project_id) == logical_project_id
                and str(row.get("created_at", "") or "") > str(submission.get("created_at", "") or "")
            ]
            boards.append({
                "submission_id": submission_id,
                "logical_project_id": logical_project_id,
                "project_display_name": meta.get("project_display_name", logical_project_id),
                "project_order": meta.get("project_order", 0),
                "material_order": material_order.get(submission_id, 0),
                "material_display_name": f"材料 {material_order.get(submission_id, 0):02d}" if material_order.get(submission_id, 0) else "材料",
                "filename": str(submission.get("filename", "") or ""),
                "source_type": str(submission.get("source_type", "") or "text"),
                "project_phase": str(submission.get("project_phase", "") or ""),
                "created_at": str(submission.get("created_at", "") or ""),
                "raw_text": str(submission.get("raw_text", "") or ""),
                "download_url": f"/api/teacher/student-file-download/{project_id}/{submission_id}" if _find_uploaded_file(project_id, str(submission.get('filename', '') or '')) else "",
                "annotation_versions": sorted(records, key=lambda item: str(item.get("created_at", "") or ""), reverse=True),
                "latest_annotations": flat_annotations,
                "annotation_count": len(flat_annotations),
                "feedback_files": sorted(files_by_submission.get(submission_id, []), key=lambda item: str(item.get("created_at", "") or ""), reverse=True),
                "followup_count": len(followups),
                "followup_submissions": [
                    {
                        "submission_id": str(item.get("submission_id", "") or ""),
                        "created_at": str(item.get("created_at", "") or ""),
                        "project_phase": str(item.get("project_phase", "") or ""),
                        "text_preview": str(item.get("raw_text", "") or "")[:140],
                    }
                    for item in sorted(followups, key=lambda row: str(row.get("created_at", "") or ""), reverse=True)[:3]
                ],
            })

        boards.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return {
            "project_id": project_id,
            "board_count": len(boards),
            "boards": boards,
            "project_feedback": sorted(project_feedback, key=lambda item: str(item.get("created_at", "") or ""), reverse=True),
        }
    
    
    # ═══════════════════════════════════════════════════════════════════
    #  文件在线预览 APIs
    # ═══════════════════════════════════════════════════════════════════
    
    @app.get("/api/teacher/file-preview/{project_id}/{submission_id}")
    def get_file_preview(project_id: str, submission_id: str):
        """获取学生提交文件的在线预览数据
        
        支持格式：
        - PDF: 返回base64编码的PDF文件（供PDF.js预览）
        - DOCX: 返回HTML格式内容
        - PPT/PPTX: 返回HTML格式内容（每页一个div）
        - TXT/MD: 返回纯文本内容
        
        返回：
        - type: 文件格式
        - status: success/error
        - pdf_base64: (仅PDF) base64编码的PDF内容
        - html_content: (仅DOCX/PPT) HTML格式的内容
        - raw_text: (仅TXT/MD) 纯文本内容
        - page_count/slide_count: 可选的页数/幻灯片数
        """
        project_state = json_store.load_project(project_id)
        submissions = project_state.get("submissions", []) or []
        
        # 查找相应的提交
        target_submission = None
        for submission in submissions:
            if submission.get("submission_id") == submission_id:
                target_submission = submission
                break
        
        if not target_submission:
            raise HTTPException(status_code=404, detail="File submission not found")
        
        source_type = target_submission.get("source_type", "")
        if source_type not in ["file", "file_in_chat"]:
            raise HTTPException(status_code=400, detail="This is not a file submission")
        
        filename = target_submission.get("filename", "")
        file_ext = ""
        if filename:
            file_ext = filename.split(".")[-1].lower() if "." in filename else ""
        
        # 获取原始上传的文件路径
        target_file = _find_uploaded_file(project_id, filename)
        
        # 如果找不到原始文件，使用raw_text构建预览
        if not target_file or not target_file.exists():
            # 回退到基于raw_text的预览
            raw_text = target_submission.get("raw_text", "")
            return {
                "type": file_ext,
                "status": "text_fallback",
                "filename": filename,
                "raw_text": raw_text,
                "message": "原始文件不可用，显示提取的文本内容",
            }
        
        try:
            # 生成文件预览数据
            preview_result = get_file_preview_data(target_file, file_ext)
            preview_result["filename"] = filename
            preview_result["file_type"] = file_ext
            return preview_result
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"预览文件失败: {str(e)}")
    
    
    # ═══════════════════════════════════════════════════════════════════
    #  PDF高级分析 APIs
    # ═══════════════════════════════════════════════════════════════════
    
    @app.get("/api/teacher/pdf-analysis/{project_id}/{submission_id}")
    def get_pdf_analysis(project_id: str, submission_id: str):
        """
        使用LLM分析PDF文件，提取关键内容、要点、总结
        
        返回：
        - pdf_stats: PDF统计信息（页数、提取页数、总字符数）
        - text_content: 提取的文本内容
        - analysis: LLM分析结果（总结、要点、重点领域、深度见解）
        - status: success/error
        """
        project_state = json_store.load_project(project_id)
        submissions = project_state.get("submissions", []) or []
        
        # 查找相应的提交
        target_submission = None
        for submission in submissions:
            if submission.get("submission_id") == submission_id:
                target_submission = submission
                break
        
        if not target_submission:
            raise HTTPException(status_code=404, detail="File submission not found")
        
        source_type = target_submission.get("source_type", "")
        if source_type not in ["file", "file_in_chat"]:
            raise HTTPException(status_code=400, detail="This is not a file submission")
        
        filename = target_submission.get("filename", "")
        file_ext = ""
        if filename:
            file_ext = filename.split(".")[-1].lower() if "." in filename else ""
        
        # 仅支持PDF分析
        if file_ext != "pdf":
            raise HTTPException(status_code=400, detail="仅支持PDF文件分析")
        
        # 获取原始上传的文件路径
        target_file = _find_uploaded_file(project_id, filename)
        
        # 如果找不到原始文件，返回错误
        if not target_file or not target_file.exists():
            return {
                "status": "error",
                "message": "原始PDF文件不可用",
                "filename": filename,
            }
        
        try:
            # 初始化LLM客户端
            llm_client = LlmClient()
            
            # 创建缓存检查
            cache_key = f"pdf_analysis_{submission_id}"
            
            # 获取PDF关键见解
            insights = get_pdf_key_insights(target_file, llm_client)
            
            if insights.get("status") == "success":
                return {
                    "status": "success",
                    "filename": filename,
                    "submission_id": submission_id,
                    "pdf_stats": insights.get("pdf_stats", {}),
                    "text_content": insights.get("text_content", ""),
                    "analysis": insights.get("analysis", {}),
                    "cached": False,
                }
            else:
                # 如果LLM分析失败，直接返回文本内容
                text_chunks = extract_pdf_text_chunked(target_file, max_pdf_pages=10)
                full_text = "\n".join([p["text"] for p in text_chunks.get("extracted_pages", [])])
                
                return {
                    "status": "partial",
                    "filename": filename,
                    "submission_id": submission_id,
                    "message": "LLM分析失败，仅返回文本内容",
                    "pdf_stats": text_chunks.get("pdf_stats", {}),
                    "text_content": full_text,
                    "analysis": insights.get("analysis", {}),
                }
                
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"PDF分析失败: {str(e)}")
    
    
    # ═══════════════════════════════════════════════════════════════════
    #  教师批注管理 APIs
    # ═══════════════════════════════════════════════════════════════════
    
    @app.post("/api/teacher/feedback-annotations")
    def save_feedback_annotations(payload: dict):
        """保存教师在文件上进行的批注
        
        请求体：
        {
            "project_id": "xxx",
            "submission_id": "xxx",
            "teacher_id": "teacher-001",
            "annotations": [
                {
                    "type": "comment",  // comment | highlight | suggest
                    "position": 100,  // 文本中的位置
                    "length": 50,  // 批注长度
                    "content": "这里需要补充证据...",
                    "annotation_type": "issue"  // praise | issue | suggest | question
                }
            ],
            "overall_feedback": "总体反馈内容",
            "focus_areas": ["evidence", "business_model"]
        }
        """
        project_id = payload.get("project_id", "")
        submission_id = payload.get("submission_id", "")
        teacher_id = payload.get("teacher_id", "")
        annotations = payload.get("annotations", [])
        overall_feedback = payload.get("overall_feedback", "")
        focus_areas = payload.get("focus_areas", [])
        
        if not all([project_id, submission_id, teacher_id]):
            raise HTTPException(status_code=400, detail="Missing required fields")
        
        # 获取项目状态
        project_state = json_store.load_project(project_id)
        
        # 创建批注记录
        annotation_id = str(uuid4())
        annotation_record = {
            "annotation_id": annotation_id,
            "submission_id": submission_id,
            "teacher_id": teacher_id,
            "annotations": annotations,
            "overall_feedback": overall_feedback,
            "focus_areas": focus_areas,
            "created_at": datetime.utcnow().isoformat(),
        }
        
        # 将批注保存到 teacher_feedback 中
        if "teacher_annotations" not in project_state:
            project_state["teacher_annotations"] = []
        
        project_state["teacher_annotations"].append(annotation_record)
        json_store.save_project(project_id, project_state)
        
        return {
            "status": "success",
            "annotation_id": annotation_id,
            "project_id": project_id,
            "submission_id": submission_id,
        }
    
    
    @app.get("/api/teacher/feedback-annotations/{project_id}/{submission_id}")
    def get_feedback_annotations(project_id: str, submission_id: str):
        """获取某个学生文件的所有批注"""
        project_state = json_store.load_project(project_id)
        annotations = project_state.get("teacher_annotations", []) or []
        
        # 筛选出针对该 submission 的批注
        submission_annotations = [
            a for a in annotations 
            if a.get("submission_id") == submission_id
        ]
        
        # 按时间排序
        submission_annotations.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        
        return {
            "project_id": project_id,
            "submission_id": submission_id,
            "annotation_count": len(submission_annotations),
            "annotations": submission_annotations,
        }
    
    
    # ═══════════════════════════════════════════════════════════════════
    #  反馈文件上传 API
    # ═══════════════════════════════════════════════════════════════════
    
    @app.post("/api/teacher/upload-feedback-file")
    async def upload_feedback_file(
        project_id: str = Form(...),
        submission_id: str = Form(...),
        teacher_id: str = Form(...),
        feedback_comment: str = Form(""),
        file: UploadFile = File(...),
    ):
        """教师上传处理/批注后的反馈文件
        
        此文件将被保存并可供学生下载
        """
        # 验证参数
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")
        
        # 创建反馈文件目录
        feedback_root = settings.upload_root / "feedback" / project_id
        feedback_root.mkdir(parents=True, exist_ok=True)
        
        # 生成反馈文件名（带时间戳，避免覆盖）
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"feedback_{timestamp}_{file.filename}"
        feedback_path = feedback_root / safe_filename
        
        # 保存文件
        content = await file.read()
        feedback_path.write_bytes(content)
        
        # 记录反馈文件信息到项目状态
        project_state = json_store.load_project(project_id)
        
        if "teacher_feedback_files" not in project_state:
            project_state["teacher_feedback_files"] = []
        
        feedback_record = {
            "feedback_file_id": str(uuid4()),
            "submission_id": submission_id,
            "teacher_id": teacher_id,
            "original_filename": file.filename,
            "saved_filename": safe_filename,
            "file_url": f"/uploads/feedback/{project_id}/{safe_filename}",
            "file_size": len(content),
            "feedback_comment": feedback_comment,
            "created_at": datetime.utcnow().isoformat(),
        }
        
        project_state["teacher_feedback_files"].append(feedback_record)
        json_store.save_project(project_id, project_state)
        
        return {
            "status": "success",
            "feedback_file_id": feedback_record["feedback_file_id"],
            "file_url": feedback_record["file_url"],
            "project_id": project_id,
            "submission_id": submission_id,
        }
    
    
    @app.get("/api/teacher/feedback-files/{project_id}")
    def get_feedback_files(project_id: str):
        """获取某个项目的所有反馈文件"""
        project_state = json_store.load_project(project_id)
        feedback_files = project_state.get("teacher_feedback_files", []) or []
        
        # 按时间倒序
        feedback_files = sorted(feedback_files, key=lambda x: x.get("created_at", ""), reverse=True)
        
        return {
            "project_id": project_id,
            "feedback_file_count": len(feedback_files),
            "feedback_files": feedback_files,
        }
    
    
    @app.get("/api/teacher/feedback-files/{project_id}/{submission_id}")
    def get_feedback_files_for_submission(project_id: str, submission_id: str):
        """获取某个学生提交的所有反馈文件"""
        project_state = json_store.load_project(project_id)
        feedback_files = project_state.get("teacher_feedback_files", []) or []
        
        # 筛选出针对该 submission 的反馈文件
        submission_feedback_files = [
            f for f in feedback_files 
            if f.get("submission_id") == submission_id
        ]
        
        # 按时间倒序
        submission_feedback_files.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        
        return {
            "project_id": project_id,
            "submission_id": submission_id,
            "feedback_file_count": len(submission_feedback_files),
            "feedback_files": submission_feedback_files,
        }
    
    
    # ═══════════════════════════════════════════════════════════════════
    #  文档在线编辑 APIs
    # ═══════════════════════════════════════════════════════════════════
    
    @app.post("/api/teacher/edit-document")
    def save_edited_document(payload: dict):
        """保存教师编辑过的文档内容
        
        请求体：
        {
            "project_id": "xxx",
            "submission_id": "xxx", 
            "teacher_id": "teacher-001",
            "edited_content": "编辑后的完整文本内容",
            "edit_summary": "编辑摘要（可选）"
        }
        
        返回：已保存的编辑版本信息
        """
        project_id = payload.get("project_id", "")
        submission_id = payload.get("submission_id", "")
        teacher_id = payload.get("teacher_id", "")
        edited_content = payload.get("edited_content", "")
        edit_summary = payload.get("edit_summary", "")
        
        if not all([project_id, submission_id, teacher_id, edited_content]):
            raise HTTPException(status_code=400, detail="Missing required fields")
        
        # 获取项目状态
        project_state = json_store.load_project(project_id)
        submissions = project_state.get("submissions", []) or []
        
        # 查找原始提交
        target_submission = None
        for submission in submissions:
            if submission.get("submission_id") == submission_id:
                target_submission = submission
                break
        
        if not target_submission:
            raise HTTPException(status_code=404, detail="Submission not found")
        
        # 初始化编辑历史
        if "teacher_document_edits" not in project_state:
            project_state["teacher_document_edits"] = []
        
        # 创建编辑记录
        edit_id = str(uuid4())
        edit_record = {
            "edit_id": edit_id,
            "submission_id": submission_id,
            "teacher_id": teacher_id,
            "edited_content": edited_content,
            "edit_summary": edit_summary,
            "original_length": len(target_submission.get("raw_text", "")),
            "edited_length": len(edited_content),
            "created_at": datetime.utcnow().isoformat(),
        }
        
        # 保存编辑记录
        project_state["teacher_document_edits"].append(edit_record)
        json_store.save_project(project_id, project_state)
        
        return {
            "status": "success",
            "edit_id": edit_id,
            "project_id": project_id,
            "submission_id": submission_id,
            "message": f"文档已保存，编辑后文本长度：{len(edited_content)} 字符",
        }
    
    
    @app.get("/api/teacher/document-edits/{project_id}/{submission_id}")
    def get_document_edits(project_id: str, submission_id: str):
        """获取某个学生文件的所有编辑版本"""
        project_state = json_store.load_project(project_id)
        edits = project_state.get("teacher_document_edits", []) or []
        
        # 筛选出针对该 submission 的编辑
        submission_edits = [
            e for e in edits 
            if e.get("submission_id") == submission_id
        ]
        
        # 按时间倒序
        submission_edits.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        
        return {
            "project_id": project_id,
            "submission_id": submission_id,
            "edit_count": len(submission_edits),
            "edits": [
                {
                    "edit_id": e["edit_id"],
                    "teacher_id": e["teacher_id"],
                    "edit_summary": e.get("edit_summary", ""),
                    "original_length": e.get("original_length", 0),
                    "edited_length": e.get("edited_length", 0),
                    "created_at": e.get("created_at", ""),
                }
                for e in submission_edits
            ] if submission_edits else [],
        }
    
    
    @app.get("/api/teacher/document-edit/{project_id}/{edit_id}")
    def get_document_edit_content(project_id: str, edit_id: str):
        """获取某个编辑版本的完整内容"""
        project_state = json_store.load_project(project_id)
        edits = project_state.get("teacher_document_edits", []) or []
        
        # 查找指定的编辑
        target_edit = None
        for edit in edits:
            if edit.get("edit_id") == edit_id:
                target_edit = edit
                break
        
        if not target_edit:
            raise HTTPException(status_code=404, detail="Edit not found")
        
        return {
            "project_id": project_id,
            "edit_id": edit_id,
            "submission_id": target_edit.get("submission_id", ""),
            "teacher_id": target_edit.get("teacher_id", ""),
            "edited_content": target_edit.get("edited_content", ""),
            "edit_summary": target_edit.get("edit_summary", ""),
            "created_at": target_edit.get("created_at", ""),
        }
    
    
    @app.post("/api/teacher/export-document")
    def export_document_as_file(payload: dict):
        """将编辑后的文档导出为文件（PDF或TXT）
        
        请求体：
        {
            "project_id": "xxx",
            "submission_id": "xxx",
            "edited_content": "编辑后的文本",
            "format": "txt" | "pdf",  // 默认为 txt
            "filename": "反馈_学生名.txt"
        }
        """
        project_id = payload.get("project_id", "")
        submission_id = payload.get("submission_id", "")
        edited_content = payload.get("edited_content", "")
        export_format = payload.get("format", "txt").lower()
        filename = payload.get("filename", f"edited_{submission_id}")
        
        if not all([project_id, edited_content]):
            raise HTTPException(status_code=400, detail="Missing required fields")
        
        # 验证导出格式
        if export_format not in ["txt", "pdf"]:
            raise HTTPException(status_code=400, detail="Unsupported format. Use 'txt' or 'pdf'")
        
        # 创建导出目录
        export_root = settings.upload_root / "export" / project_id
        export_root.mkdir(parents=True, exist_ok=True)
        
        # 确定文件扩展名
        ext = export_format
        if not filename.endswith(f".{ext}"):
            filename = f"{filename}.{ext}"
        
        export_path = export_root / filename
        
        # 保存文件内容
        if export_format == "txt":
            export_path.write_text(edited_content, encoding="utf-8")
        elif export_format == "pdf":
            # 对于 PDF，我们保存为文本内容（实际的PDF生成需要额外的库）
            # 这里简化为保存文本内容
            export_path.write_text(edited_content, encoding="utf-8")
        
        return {
            "status": "success",
            "format": export_format,
            "filename": filename,
            "download_url": f"/export/{project_id}/{filename}",
            "message": f"文档已导出为 {export_format.upper()} 格式",
        }
