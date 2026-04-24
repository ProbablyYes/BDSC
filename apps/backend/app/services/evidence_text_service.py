"""
Evidence Text Service

This service handles extraction of student submission text from conversation JSON files
for the teacher-facing radar dimension evidence display feature.
"""

import re
from typing import Dict, List


def _safe_str(value: str | None) -> str:
    """Safely convert value to string, defaulting to empty string."""
    return str(value or "")


# Dimension-specific keyword mapping for evidence extraction
DIMENSION_KEYWORDS: Dict[str, List[str]] = {
    "Problem Definition": ["痛点", "问题", "困难", "挑战", "需求", "目标用户", "场景", "具体"],
    "User Evidence Strength": ["访谈", "问卷", "调研", "数据", "实测", "内测", "统计"],
    "Solution Feasibility": ["方案", "技术", "实现", "可行", "MVP", "原型", "测试", "演示", "路线", "步骤", "落地"],
    "Business Model Consistency": ["商业模式", "定价", "渠道", "推广", "获客", "价值主张"],
    "Market & Competition": ["市场", "规模", "竞品", "竞争", "对手", "份额", "TAM", "SAM", "SOM"],
    "Financial Logic": ["财务", "预算", "成本", "收入", "利润", "现金流", "投资", "回报", "ROI", "盈亏", "资金", "变现"],
    "Innovation & Differentiation": [ "独特", "差异", "专利", "优势", "领先", "突破", "新颖", "核心"],
    "Team & Execution": ["团队", "成员", "负责人", "分工", "执行", "计划", "里程碑", "股权", "架构", "能力"],
    "Presentation Quality": ["路演", "PPT", "演示", "表达", "逻辑", "演讲", "展示"],
}


def get_conversation_user_messages(project_id: str, conversation_id: str, conv_store) -> List[str]:
    """
    Extract all user messages from a conversation in chronological order.
    
    Args:
        project_id: The project ID (e.g., "project-{user_id}") - may be None for search across all projects
        conversation_id: The conversation ID
        conv_store: The conversation store instance
        
    Returns:
        List of user message contents in chronological order
    """
    try:
        # First try with the provided project_id
        conv = conv_store.get(project_id, conversation_id) if project_id else None
        # If not found or no project_id provided, search across all projects
        if not conv and hasattr(conv_store, 'get_by_conversation_id'):
            conv = conv_store.get_by_conversation_id(conversation_id)
        if conv:
            messages = conv.get("messages", [])
            user_messages = [_safe_str(msg.get("content", "")) for msg in messages if msg.get("role") == "user"]
            return user_messages
    except Exception:
        pass
    return []


def get_submission_text_mapping(submissions: List[Dict], conv_store, project_id: str) -> Dict[str, List[str]]:
    """
    Build a mapping of conversation_id to list of user messages.
    
    Args:
        submissions: List of submission dictionaries
        conv_store: The conversation store instance
        project_id: The project ID
        
    Returns:
        Dictionary mapping conversation_id to list of user message contents
    """
    conv_user_messages: Dict[str, List[str]] = {}
    for sub in submissions:
        sub_cid = sub.get("conversation_id", "")
        if sub_cid and sub_cid not in conv_user_messages:
            user_messages = get_conversation_user_messages(project_id, sub_cid, conv_store)
            conv_user_messages[sub_cid] = user_messages
    return conv_user_messages


def get_submission_raw_text(submission: Dict, conv_user_messages: Dict[str, List[str]], 
                           sub_index_per_conv: Dict[str, int]) -> str:
    """
    Get the raw text for a submission, either from the submission itself or from conversation messages.
    
    Args:
        submission: The submission dictionary
        conv_user_messages: Mapping of conversation_id to user messages
        sub_index_per_conv: Tracking of submission index per conversation
        
    Returns:
        The raw text content for this submission
    """
    raw_text = _safe_str(submission.get("raw_text", ""))
    if not raw_text:
        sub_cid = submission.get("conversation_id", "")
        if sub_cid:
            user_messages = conv_user_messages.get(sub_cid, [])
            sub_index = sub_index_per_conv.get(sub_cid, 0)
            if sub_index < len(user_messages):
                raw_text = user_messages[sub_index]
            sub_index_per_conv[sub_cid] = sub_index + 1
    return raw_text


def extract_relevant_fragments(text: str, keywords: List[str]) -> List[str]:
    """
    Extract text fragments containing the given keywords from the original text.
    
    This function splits the text into sentences and returns sentences that contain
    at least one of the keywords, providing context around the keyword.
    
    Args:
        text: The original text to extract fragments from
        keywords: List of keywords to search for
        
    Returns:
        List of relevant text fragments (sentences containing keywords)
    """
    if not text or not keywords:
        return []
    
    # Normalize keywords for matching
    normalized_keywords = [kw.lower().strip() for kw in keywords if kw.strip()]
    if not normalized_keywords:
        return []
    
    # Split text into sentences (Chinese and English)
    # Split by common sentence delimiters
    sentences = re.split(r'[。！？.!?；;]\s*', text)
    
    relevant_fragments = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        
        # Check if sentence contains any keyword
        sentence_lower = sentence.lower()
        for keyword in normalized_keywords:
            if keyword in sentence_lower:
                relevant_fragments.append(sentence)
                break  # Only add each sentence once
    
    return relevant_fragments


def build_rubric_scores_with_quotes(submissions: List[Dict], conv_store, project_id: str) -> Dict[str, List[tuple[float, str]]]:
    """
    Build rubric scores with corresponding submission text quotes.
    
    This function:
    1. Collects all user messages from conversations in chronological order
    2. For each submission, extracts relevant text fragments based on dimension keywords
    3. Returns rubric scores with dimension-specific evidence fragments
    
    Args:
        submissions: List of submission dictionaries
        conv_store: The conversation store instance
        project_id: The project ID
        
    Returns:
        Dictionary mapping rubric item names to lists of (score, evidence_fragments) tuples
    """
    # First, collect all user messages from conversations in chronological order
    conv_user_messages = get_submission_text_mapping(submissions, conv_store, project_id)
    
    rubric_scores: Dict[str, List[tuple[float, str]]] = {}
    # Track submission index per conversation for chronological mapping
    sub_index_per_conv: Dict[str, int] = {}
    
    for sub in submissions:
        diag = sub.get("diagnosis") or {}
        raw_text = get_submission_raw_text(sub, conv_user_messages, sub_index_per_conv)
        
        # Get rubric items with their matched_evidence keywords
        rubric_items = diag.get("rubric") or []
        if not isinstance(rubric_items, list):
            rubric_items = []
        
        for r in rubric_items:
            if not isinstance(r, dict) or not r.get("item"):
                continue
            
            dimension_name = r["item"]
            score = float(r.get("score", 0) or 0)
            
            # Get keywords for this dimension
            matched_evidence = r.get("matched_evidence") or []
            missing_evidence = r.get("missing_evidence") or []
            
            # Combine matched and missing evidence keywords from the rubric item
            all_keywords = []
            if isinstance(matched_evidence, list):
                all_keywords.extend(matched_evidence)
            if isinstance(missing_evidence, list):
                all_keywords.extend(missing_evidence)
            
            # If no keywords from rubric item, use predefined dimension-specific keywords
            if not all_keywords:
                all_keywords = DIMENSION_KEYWORDS.get(dimension_name, [])
            
            # Extract relevant fragments based on keywords
            if all_keywords and raw_text:
                fragments = extract_relevant_fragments(raw_text, all_keywords)
                if fragments:
                    # Join fragments with separator, limit to keep it brief
                    evidence_text = " || ".join(fragments[:3])  # Take up to 3 fragments
                else:
                    # If no fragments found but keywords exist, indicate no evidence
                    evidence_text = "未找到相关证据"
            else:
                # If no keywords, indicate no evidence
                evidence_text = "未找到相关证据"
            
            rubric_scores.setdefault(dimension_name, []).append((score, evidence_text))
    
    return rubric_scores
