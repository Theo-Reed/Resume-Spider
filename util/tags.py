"""
Tag extraction utilities for job descriptions
Extracts industry from job descriptions with strict context matching
Handles bilingual (Chinese + English) descriptions
"""

import re
import google.generativeai as genai

# Industry patterns for strict context matching (bilingual)
# Only matches when industry keyword appears near context words like "行业", "领域", "公司", "业务"
# This prevents false positives like "SaaS" mentioned in passing
INDUSTRY_PATTERNS = [
    # More specific patterns first (higher priority)
    (r'(跨境电商|cross-border e-commerce|cross border)(行业|领域|公司|业务|industry|sector|company|business)', '跨境电商行业'),
    (r'(在线教育|online education|edtech|教育科技)(行业|领域|公司|业务|industry|sector|company|business)', '在线教育行业'),
    (r'(人工智能|AI|artificial intelligence|机器学习|machine learning)(行业|领域|公司|业务|industry|sector|company|business)', '人工智能行业'),
    (r'(云计算|cloud computing|cloud)(行业|领域|公司|业务|industry|sector|company|business)', '云计算行业'),
    (r'(大数据|big data)(行业|领域|公司|业务|industry|sector|company|business)', '大数据行业'),
    (r'(区块链|blockchain|web3|web 3)(行业|领域|公司|业务|industry|sector|company|business)', '区块链行业'),
    (r'(金融科技|fintech)(行业|领域|公司|业务|industry|sector|company|business)', '金融科技行业'),
    (r'(SaaS|saas|软件即服务)(行业|领域|公司|业务|industry|sector|company|business)', 'SaaS行业'),
    (r'(游戏|game|gaming)(行业|领域|公司|业务|industry|sector|company|business)', '游戏行业'),
    (r'(电商|e-commerce|ecommerce)(行业|领域|公司|业务|industry|sector|company|business)', '电商行业'),
    (r'(互联网|internet)(行业|领域|公司|业务|industry|sector|company|business)', '互联网行业'),
    (r'(软件|software)(行业|领域|公司|业务|industry|sector|company|business)', '软件行业'),
    (r'(金融|finance|financial)(行业|领域|公司|业务|industry|sector|company|business)', '金融行业'),
    (r'(医疗|healthcare|health|健康)(行业|领域|公司|业务|industry|sector|company|business)', '医疗健康行业'),
    (r'(教育|education|培训|training)(行业|领域|公司|业务|industry|sector|company|business)', '教育培训行业'),
    (r'(物流|logistics)(行业|领域|公司|业务|industry|sector|company|business)', '物流行业'),
    (r'(视频|video|直播|live streaming|streaming)(行业|领域|公司|业务|industry|sector|company|business)', '视频行业'),
    (r'(营销|marketing|广告|advertising|ad)(行业|领域|公司|业务|industry|sector|company|business)', '营销行业'),
    (r'(保险|insurance)(行业|领域|公司|业务|industry|sector|company|business)', '保险行业'),
    (r'(银行|bank|banking)(行业|领域|公司|业务|industry|sector|company|business)', '银行行业'),
    (r'(证券|securities)(行业|领域|公司|业务|industry|sector|company|business)', '证券行业'),
    (r'(投资|investment)(行业|领域|公司|业务|industry|sector|company|business)', '投资行业'),
    (r'(文娱|entertainment)(行业|领域|公司|业务|industry|sector|company|business)', '文娱行业'),
    (r'(传媒|media)(行业|领域|公司|业务|industry|sector|company|business)', '传媒行业'),
    (r'(社交|social|social media)(行业|领域|公司|业务|industry|sector|company|business)', '社交行业'),
    (r'(芯片|chip|semiconductor)(行业|领域|公司|业务|industry|sector|company|business)', '芯片行业'),
    (r'(医药|pharmaceutical|pharma)(行业|领域|公司|业务|industry|sector|company|business)', '医药行业'),
    (r'(生物科技|biotech)(行业|领域|公司|业务|industry|sector|company|business)', '生物科技行业'),
    (r'(交通|transportation|出行|travel|mobility)(行业|领域|公司|业务|industry|sector|company|business)', '交通运输行业'),
    (r'(房产|real estate|property)(行业|领域|公司|业务|industry|sector|company|business)', '房产行业'),
    (r'(建筑|construction)(行业|领域|公司|业务|industry|sector|company|business)', '建筑行业'),
    (r'(制造|manufacturing)(行业|领域|公司|业务|industry|sector|company|business)', '制造行业'),
    (r'(工业|industrial)(行业|领域|公司|业务|industry|sector|company|business)', '工业行业'),
    (r'(咨询|consulting)(行业|领域|公司|业务|industry|sector|company|business)', '咨询行业'),
    (r'(管理|management)(行业|领域|公司|业务|industry|sector|company|business)', '管理咨询行业'),
    (r'(能源|energy)(行业|领域|公司|业务|industry|sector|company|business)', '能源行业'),
    (r'(新能源|renewable energy)(行业|领域|公司|业务|industry|sector|company|business)', '新能源行业'),
    (r'(农业|agriculture)(行业|领域|公司|业务|industry|sector|company|business)', '农业行业'),
    (r'(企业软件|enterprise software)(行业|领域|公司|业务|industry|sector|company|business)', '企业软件行业'),
    (r'(物联网|iot|IoT)(行业|领域|公司|业务|industry|sector|company|business)', '物联网行业'),
    (r'(硬件|hardware)(行业|领域|公司|业务|industry|sector|company|business)', '硬件行业'),
    (r'(法律|legal|law)(行业|领域|公司|业务|industry|sector|company|business)', '法律行业'),
    (r'(人力资源|hr|recruitment|talent)(行业|领域|公司|业务|industry|sector|company|business)', '人力资源行业'),
    (r'(设计|design)(行业|领域|公司|业务|industry|sector|company|business)', '设计行业'),
    (r'(创意|creative)(行业|领域|公司|业务|industry|sector|company|business)', '创意行业'),
    (r'(餐饮|food|restaurant)(行业|领域|公司|业务|industry|sector|company|business)', '餐饮行业'),
    (r'(零售|retail)(行业|领域|公司|业务|industry|sector|company|business)', '零售行业'),
    (r'(汽车|automotive|auto)(行业|领域|公司|业务|industry|sector|company|business)', '汽车行业'),
    (r'(航空|aerospace|aviation)(行业|领域|公司|业务|industry|sector|company|business)', '航空行业'),
    (r'(电信|telecom|telecommunications)(行业|领域|公司|业务|industry|sector|company|business)', '电信行业'),
    (r'(安全|security|cybersecurity|网络安全)(行业|领域|公司|业务|industry|sector|company|business)', '安全行业'),
]

# Fallback industry keywords - ONLY used when keyword appears with strong context indicators
# This is a last resort and should rarely match
FALLBACK_INDUSTRY_KEYWORDS = {
    # Only include very unambiguous keywords that are unlikely to appear in non-industry contexts
    "软件行业": "软件行业",  # Only if already has "行业" suffix
    "互联网行业": "互联网行业",
    "电商行业": "电商行业",
    "游戏行业": "游戏行业",
    "金融行业": "金融行业",
    "医疗行业": "医疗健康行业",
    "教育行业": "教育培训行业",
}


def extract_industry_with_context(description: str) -> str:
    """
    Extract industry tag with STRICT context matching to avoid false positives.
    Handles bilingual descriptions (Chinese + English).
    
    Only matches when industry keyword appears near context words like:
    - "行业", "领域", "公司", "业务" (Chinese)
    - "industry", "sector", "company", "business" (English)
    
    This prevents false positives like:
    - "SaaS" mentioned in passing in a marketing job description
    - "游戏" mentioned as a skill/hobby, not the industry
    
    Args:
        description: Job description text (bilingual)
    
    Returns:
        Industry tag string (e.g., "互联网行业") or empty string if not found
    """
    if not description:
        return ""
    
    description_lower = description.lower()
    
    # Step 1: Try pattern matching first (most reliable - requires context words)
    for pattern, industry in INDUSTRY_PATTERNS:
        if re.search(pattern, description_lower, re.IGNORECASE):
            return industry
    
    # Step 2: Fallback - only match if keyword already has "行业" suffix
    # This is very strict and should rarely match
    for keyword, industry in FALLBACK_INDUSTRY_KEYWORDS.items():
        if keyword.lower() in description_lower:
            return industry
    
    # Step 3: Last resort - check for "xx行业" pattern directly in text
    # This catches cases like "我们是一家互联网行业的公司"
    industry_suffix_pattern = r'([^，。\s]+)(行业|领域)'
    matches = re.findall(industry_suffix_pattern, description_lower)
    for match in matches:
        industry_text = match[0] + match[1]
        # Check if it matches any known industry
        for pattern, industry in INDUSTRY_PATTERNS:
            # Simple check if the industry text contains key parts of the pattern
            pattern_keywords = pattern.replace(r'(', '').replace(r')', '').replace('|', ' ').replace('*', '').lower()
            if any(kw in industry_text for kw in pattern_keywords.split() if len(kw) > 2):
                return industry
    
    return ""


def extract_tags_with_gemini(description: str, existing_tags: list, api_key: str, max_tags: int = 6) -> list:
    """
    Use Gemini API to extract important tags when Python extraction is insufficient.
    Handles bilingual descriptions.
    
    Args:
        description: Job description text (bilingual)
        existing_tags: List of tags already extracted
        api_key: Google Gemini API key
        max_tags: Maximum number of tags to return
    
    Returns:
        List of additional tags extracted by Gemini
    """
    if not description or len(existing_tags) >= max_tags:
        return []
    
    needed = max_tags - len(existing_tags)
    
    try:
        # Configure Gemini
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # Build prompt (bilingual)
        existing_tags_str = ', '.join(existing_tags) if existing_tags else "无"
        
        prompt = f"""从以下职位描述中提取最重要的标签（最多{needed}个），补充到已有标签中。
职位描述可能包含中文和英文。

已有标签：{existing_tags_str}

要求：
1. 优先提取技术栈、技能关键词（如编程语言、框架、工具等）
2. 提取行业相关标签（如果描述中明确提到且是主要业务）
3. 避免与已有标签重复
4. 只返回最重要的标签，用逗号分隔
5. 标签可以是中文或英文，保持原样
6. 不要包含"远程"、"remote"等工作地点相关标签
7. 不要包含薪资信息
8. 不要包含公司名称或团队名称

职位描述：
{description[:2000]}

请只返回标签，用逗号分隔，不要其他解释：
"""
        
        response = model.generate_content(prompt)
        content = response.text.strip()
        
        # Parse response (split by comma, clean up)
        tags = [tag.strip() for tag in content.split(',') if tag.strip()]
        
        # Remove duplicates and filter out unwanted tags
        unwanted = {'远程', 'remote', '全职', '兼职', 'full-time', 'part-time', '', '工作', 'job', '职位', 'position'}
        filtered_tags = []
        seen = {t.lower() for t in existing_tags}
        
        for tag in tags:
            tag_lower = tag.lower()
            if tag_lower not in seen and tag_lower not in unwanted and len(tag) > 0:
                filtered_tags.append(tag)
                seen.add(tag_lower)
                if len(filtered_tags) >= needed:
                    break
        
        return filtered_tags[:needed]
        
    except Exception as e:
        print(f"    ⚠️  Gemini API error: {str(e)[:100]}")
        return []


# Keep backward compatibility
def extract_industry(description: str) -> str:
    """Legacy function - use extract_industry_with_context instead."""
    return extract_industry_with_context(description)


def extract_all_tags(description: str) -> dict:
    """
    Extract all tags from job description (bilingual).
    Now only returns industry - skills and other tags should come from Gemini.
    """
    return {
        "industry": extract_industry_with_context(description),
        "skills": [],  # Removed - use Gemini instead
        "other_tags": []  # Removed - use Gemini instead
    }


def extract_tags_as_list(description: str) -> list:
    """
    Extract tags and return as a single list with industry first (bilingual).
    Now only returns industry - other tags should come from Gemini.
    """
    tags = []
    
    # Add industry only
    industry = extract_industry_with_context(description)
    if industry:
        tags.append(industry)
    
    return tags
